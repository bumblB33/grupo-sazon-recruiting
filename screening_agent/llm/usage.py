from langchain_core.messages import AIMessage
from pydantic import BaseModel


class ModelUsage(BaseModel):
    """Token counts are None when the provider reports no usage_metadata."""

    call: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float


def usage_of(message: AIMessage, call: str, model: str, latency_ms: float) -> ModelUsage:
    metadata = message.usage_metadata
    return ModelUsage(
        call=call,
        model=model,
        input_tokens=metadata["input_tokens"] if metadata else None,
        output_tokens=metadata["output_tokens"] if metadata else None,
        latency_ms=latency_ms,
    )


def elapsed_ms(started: float, finished: float) -> float:
    return round((finished - started) * 1000, 1)
