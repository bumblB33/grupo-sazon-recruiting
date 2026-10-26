from collections.abc import Callable

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from screening_agent.llm.models import chat_model

Summarizer = Callable[[dict, str, list[AnyMessage]], str]

SUMMARY_SYSTEM = (
    "You write a four-line recruiter summary of a delivery-driver screening. Line 1: outcome and reason. "
    "Line 2: key profile facts. Line 3: anything a recruiter should double-check. Line 4: suggested next step. "
    "Plain text, no markdown, same language as the transcript."
)


def make_summarizer(model_id: str) -> Summarizer:
    model = chat_model(model_id)

    def summarize(profile: dict, status: str, transcript: list[AnyMessage]) -> str:
        lines = [f"{m.type}: {m.text}" for m in transcript if m.type in ("human", "ai")]
        body = f"Status: {status}\nProfile: {profile}\nTranscript:\n" + "\n".join(lines)
        response = model.invoke([SystemMessage(content=SUMMARY_SYSTEM), HumanMessage(content=body)])
        return str(response.content)

    return summarize
