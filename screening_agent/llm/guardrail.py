from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str | None = None


def check(message: str) -> GuardrailVerdict:
    # TODO: classify off-topic, abusive and prompt-injection input with settings.guardrail_model
    return GuardrailVerdict(allowed=True)
