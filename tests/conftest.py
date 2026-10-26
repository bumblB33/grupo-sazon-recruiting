import os
import uuid
from collections.abc import Callable, Iterable

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from screening_agent.api import app as api
from screening_agent.config import settings
from screening_agent.flow.engine import ScreeningEngine
from screening_agent.flow.graph import build_graph
from screening_agent.llm.guardrail import GuardrailVerdict, permit_all
from screening_agent.storage.repository import Repository


class ScriptedToolModel(GenericFakeChatModel):
    """Replays scripted AI messages and records what the graph bound and sent, so tests can assert on it."""

    bound_tool_names: list[list[str]] = []
    seen_inputs: list[list] = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([tool.name for tool in tools])
        return self

    def invoke(self, input, config=None, **kwargs):
        self.seen_inputs.append(list(input))
        return super().invoke(input, config=config, **kwargs)


def ai(
    text: str, tool: str | None = None, args: dict | None = None, call_id: str = "c1"
) -> AIMessage:
    calls = [{"name": tool, "args": args or {}, "id": call_id, "type": "tool_call"}] if tool else []
    return AIMessage(content=text, tool_calls=calls)


def ai_multi(text: str, *calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": name, "args": args, "id": f"c{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(calls)
        ],
    )


@pytest.fixture(scope="session")
def mongo_url() -> Iterable[str]:
    """One Mongo container per session; each test gets its own database name for isolation.
    SCREENING_TEST_DATABASE_URL points at an existing server when Docker is not available."""
    external = os.environ.get("SCREENING_TEST_DATABASE_URL")
    if external:
        yield external
        return
    try:
        from testcontainers.community.mongodb import MongoDbContainer

        container = MongoDbContainer("mongo:7").start()
    except Exception as exc:  # no Docker socket on this machine
        pytest.skip(f"MongoDB test container unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def repository(mongo_url: str) -> Repository:
    # The container's root user lives in admin; a database in the path would become the auth source.
    return Repository(f"{mongo_url.rstrip('/')}/test_{uuid.uuid4().hex}?authSource=admin")


@pytest.fixture
def make_engine(repository: Repository):
    def _make(
        script: Iterable[AIMessage],
        guardrail: Callable[[str], GuardrailVerdict] = permit_all,
    ):
        model = ScriptedToolModel(messages=iter(script), bound_tool_names=[], seen_inputs=[])
        graph = build_graph(model, lambda state, stage: "system")
        engine = ScreeningEngine(
            repository,
            graph,
            summarizer=lambda profile, status, msgs: "summary",
            guardrail=guardrail,
        )
        return engine, repository, model

    return _make


class FakeOutbound:
    """Records what the engine sends; satisfies OutboundChannel for sweep and API tests."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.openers: list[tuple[str, str]] = []

    def send_text(self, candidate_id: str, text: str) -> None:
        self.texts.append((candidate_id, text))

    def send_opener(self, candidate_id: str, text: str) -> None:
        self.openers.append((candidate_id, text))


NO_LICENCE_TURNS = ["sí", "Ana García", "no tengo carnet"]
# One no-licence screening, then one consent so a test can open a second candidate.
API_SCRIPT = [
    ai("Hola", "record_consent", {"accepted": True}),
    ai("¿Nombre?", "record_full_name", {"full_name": "Ana García"}),
    ai("¿Carnet?", "record_licence", {"has_licence": False}),
    ai("Hola", "record_consent", {"accepted": True}),
]


@pytest.fixture
def client(make_engine, monkeypatch) -> Iterable[TestClient]:
    """API client in dev mode with no secrets; tests set a secret via monkeypatch to exercise auth."""
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "recruiter_api_key", None)
    monkeypatch.setattr(settings, "twilio_auth_token", None)
    monkeypatch.setattr(settings, "twilio_webhook_url", None)
    engine, repository, _ = make_engine(API_SCRIPT)
    api.app.dependency_overrides[api.get_repository] = lambda: repository
    api.app.dependency_overrides[api.get_engine] = lambda: engine
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()


def twilio_form(sid: str, phone: str, body: str) -> dict[str, str]:
    return {"MessageSid": sid, "From": f"whatsapp:{phone}", "To": "whatsapp:+1555", "Body": body}


def screen_no_licence(client: TestClient, phone: str) -> None:
    for index, text in enumerate(NO_LICENCE_TURNS):
        client.post("/webhook/whatsapp", data=twilio_form(f"{phone}-{index}", phone, text))
