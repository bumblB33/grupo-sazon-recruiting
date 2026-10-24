from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from screening_agent.config import settings

SUMMARY_SYSTEM = (
    "You write a four-line recruiter summary of a delivery-driver screening. Line 1: outcome and reason. "
    "Line 2: key profile facts. Line 3: anything a recruiter should double-check. Line 4: suggested next step. "
    "Plain text, no markdown, same language as the transcript."
)


def summarize(profile: dict, status: str, transcript: list[AnyMessage]) -> str:
    model = init_chat_model(
        settings.summary_model, temperature=0, timeout=settings.llm_timeout_seconds
    )
    lines = [f"{m.type}: {m.content}" for m in transcript if m.type in ("human", "ai")]
    body = f"Status: {status}\nProfile: {profile}\nTranscript:\n" + "\n".join(lines)
    response = model.invoke([SystemMessage(content=SUMMARY_SYSTEM), HumanMessage(content=body)])
    return str(response.content)
