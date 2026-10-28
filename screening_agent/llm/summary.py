from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from screening_agent.llm.models import chat_model

# Returns an AIMessage so the caller can read usage_metadata for tracing; its text is the summary.
Summarizer = Callable[[Mapping[str, Any]], AIMessage]

SUMMARY_SYSTEM = (
    "You write a recruiter summary of a delivery-driver screening chat. Plain text in each field, "
    "no markdown, in the language of the transcript. Do not repeat the same fact across fields. "
    "Never invent anything that is not in the transcript or the profile."
)


class RecruiterSummary(BaseModel):
    """Structured so the recruiter page never shows the model's own field labels or numbering."""

    outcome: str = Field(description="The outcome and the reason for it, one sentence.")
    profile_facts: str = Field(description="The key profile facts, one sentence.")
    double_check: str = Field(
        description="What a recruiter should double-check before an interview, including every "
        "flagged concern and any answer the candidate hedged. 'Nothing' if there is nothing."
    )
    next_step: str = Field(
        description="The suggested next step, one sentence, naming the candidate's questions "
        "for the recruiter when there are any."
    )

    def render(self) -> str:
        return "\n".join((self.outcome, self.profile_facts, self.double_check, self.next_step))


class SummaryUnavailableError(RuntimeError):
    pass


def make_summarizer(model_id: str) -> Summarizer:
    model = chat_model(model_id).with_structured_output(RecruiterSummary, include_raw=True)

    def summarize(state: Mapping[str, Any]) -> AIMessage:
        output: Any = model.invoke(
            [SystemMessage(content=SUMMARY_SYSTEM), HumanMessage(content=summary_input(state))]
        )
        parsed = output.get("parsed") if isinstance(output, dict) else None
        if not isinstance(parsed, RecruiterSummary):
            error = output.get("parsing_error") if isinstance(output, dict) else None
            raise SummaryUnavailableError(str(error) if error else "no summary returned")
        raw = output.get("raw")
        usage = raw.usage_metadata if isinstance(raw, AIMessage) else None
        return AIMessage(content=parsed.render(), usage_metadata=usage)

    return summarize


def summary_input(state: Mapping[str, Any]) -> str:
    lines = [f"{m.type}: {m.text}" for m in state.get("messages", []) if m.type in ("human", "ai")]
    reason = state.get("disqualify_reason") or state.get("review_reason")
    return (
        f"Status: {state.get('status')}\n"
        f"Reason: {reason or 'none'}\n"
        f"Profile: {state.get('profile', {})}\n"
        f"Flagged for a recruiter check: {_listed(state.get('concerns'))}\n"
        f"Candidate's questions for the recruiter: {_listed(state.get('candidate_questions'))}\n"
        "Transcript:\n" + "\n".join(lines)
    )


def _listed(items: list[str] | None) -> str:
    return "; ".join(items) if items else "none"
