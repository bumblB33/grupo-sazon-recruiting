from collections.abc import Callable

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from screening_agent.llm.models import chat_model

# Returns the model message so the caller can read usage_metadata for tracing.
Summarizer = Callable[[dict, str, list[AnyMessage]], AIMessage]

SUMMARY_SYSTEM = (
    "You write a four-line recruiter summary of a delivery-driver screening. Line 1: outcome and reason. "
    "Line 2: key profile facts. Line 3: anything a recruiter should double-check. Line 4: suggested next step. "
    "Plain text, no markdown, same language as the transcript. Don't restate the same information across lines."
)


def make_summarizer(model_id: str) -> Summarizer:
    model = chat_model(model_id)

    def summarize(profile: dict, status: str, transcript: list[AnyMessage]) -> AIMessage:
        lines = [f"{m.type}: {m.text}" for m in transcript if m.type in ("human", "ai")]
        body = f"Status: {status}\nProfile: {profile}\nTranscript:\n" + "\n".join(lines)
        return model.invoke([SystemMessage(content=SUMMARY_SYSTEM), HumanMessage(content=body)])

    return summarize
