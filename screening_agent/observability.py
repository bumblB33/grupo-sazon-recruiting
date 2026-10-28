import hashlib
import hmac
import logging
import re
from collections.abc import Sequence
from typing import Any

import logfire
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import format_trace_id

from screening_agent.config import settings

TRACER = trace.get_tracer("screening_agent")
REDACTED = "[redacted]"
E164 = r"\+\d{8,15}"
EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
CONTACT = re.compile(rf"{E164}|{EMAIL}")
# The candidate id is a phone or a web id; every route that carries it puts it after /candidates/.
CANDIDATE_SEGMENT = re.compile(r"(/candidates/)[^/?#]+")
URL_ATTRIBUTES = ("http.target", "http.url", "url.path", "url.full")
# The path holds a live login token until it is used.
LOGIN_LINK_URLS = r".*/recruiter/login/.+"


def candidate_hash(candidate_id: str) -> str | None:
    """None without a secret: the candidate then appears in traces with no identifier at all."""
    if settings.candidate_hash_secret is None:
        return None
    key = settings.candidate_hash_secret.get_secret_value().encode()
    return hmac.new(key, candidate_id.encode(), hashlib.sha256).hexdigest()[:16]


def trace_id_of(span: trace.Span) -> str | None:
    context = span.get_span_context()
    return format_trace_id(context.trace_id) if context.is_valid else None


def redact_path(value: str) -> str:
    return CONTACT.sub(REDACTED, CANDIDATE_SEGMENT.sub(r"\1{candidate_id}", value))


def redact_url_attributes(span: Any, scope: Any = None) -> None:
    """Also the FastAPI server_request_hook: ASGI re-sets the URL attributes after span start."""
    for name in URL_ATTRIBUTES:
        value = (span.attributes or {}).get(name)
        if isinstance(value, str):
            span.set_attribute(name, redact_path(value))


class CandidatePathProcessor(SpanProcessor):
    """Runs at span start, before Logfire emits the pending span, which carries the raw URL."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        redact_url_attributes(span)

    def on_end(self, span: ReadableSpan) -> None:
        pass


def redact_contact(match: logfire.ScrubMatch) -> Any:
    """Logfire's default redaction text quotes the match, which would echo the phone or email."""
    if CONTACT.fullmatch(match.pattern_match.group(0)):
        return REDACTED
    return None


def configure_observability(
    service_name: str,
    app: FastAPI | None = None,
    additional_span_processors: Sequence[SpanProcessor] = (),
) -> None:
    """Sends only when a token is set. Instruments the app after its middleware stack was built."""
    token = settings.logfire_token
    logfire.configure(
        service_name=service_name,
        token=token.get_secret_value() if token else None,
        send_to_logfire="if-token-present",
        console=False,
        # Old-semconv HTTP duration metrics carry the raw request path.
        metrics=False,
        scrubbing=logfire.ScrubbingOptions(extra_patterns=[E164, EMAIL], callback=redact_contact),
        additional_span_processors=[CandidatePathProcessor(), *additional_span_processors],
    )
    logfire.instrument_pymongo(capture_statement=False)
    logfire.instrument_httpx()
    if app is not None:
        logfire.instrument_fastapi(
            app,
            request_attributes_mapper=_no_request_attributes,
            excluded_urls=LOGIN_LINK_URLS,
            server_request_hook=redact_url_attributes,
        )
        # Starlette builds the stack once, before the lifespan runs; None makes it rebuild with tracing.
        app.middleware_stack = None
    root = logging.getLogger()
    if not any(isinstance(h, logfire.LogfireLoggingHandler) for h in root.handlers):
        root.addHandler(logfire.LogfireLoggingHandler())


def _no_request_attributes(request: Any, attributes: dict[str, Any]) -> None:
    """The default mapper records endpoint argument values: phone numbers, emails, message text."""
    return None
