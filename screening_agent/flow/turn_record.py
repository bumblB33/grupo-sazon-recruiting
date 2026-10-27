from enum import StrEnum

from pydantic import BaseModel, Field

from screening_agent.llm.usage import ModelUsage


class ReplySource(StrEnum):
    TERMINAL = "terminal"
    REASK = "reask"
    ZONE_CONFIRM = "zone_confirm"
    MODEL_TEXT = "model_text"
    POLICY_FALLBACK = "policy_fallback"
    NEXT_QUESTION = "next_question"
    GUARDRAIL_REDIRECT = "guardrail_redirect"


class ToolCallRecord(BaseModel):
    name: str
    accepted: bool
    message: str | None = None


class TurnRecord(BaseModel):
    """Why the agent replied as it did. Saved on the inbound transcript entry by the same write as the turn."""

    stage_before: str
    stage_after: str
    status_after: str
    guardrail_category: str | None = None
    tone: str | None = None
    tools_exposed: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    reply_source: ReplySource
    model_text: str | None = None
    violated_rules: list[str] = Field(default_factory=list)
    usage: list[ModelUsage] = Field(default_factory=list)
    latency_ms: float
    candidate_hash: str | None = None
    trace_id: str | None = None
