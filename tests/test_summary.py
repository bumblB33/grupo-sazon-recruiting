from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from screening_agent.domain.enums import Status
from screening_agent.flow.state import initial_state
from screening_agent.llm import summary


class FakeStructuredModel:
    def __init__(self, parsed, raw=None) -> None:
        self.parsed = parsed
        self.raw = raw or AIMessage(content="")
        self.sent: list = []

    def with_structured_output(self, schema, include_raw=False):
        return RunnableLambda(self._invoke)

    def _invoke(self, messages):
        self.sent.extend(messages)
        return {"raw": self.raw, "parsed": self.parsed, "parsing_error": None}


def decided_state():
    state = initial_state("c")
    state["messages"] = [
        SystemMessage(content="internal prompt"),
        HumanMessage(content="sí"),
        AIMessage(content=[{"type": "text", "text": "¿Nombre?"}]),
    ]
    state["status"] = Status.QUALIFIED
    state["concerns"] = ["Licence may be expired"]
    state["candidate_questions"] = ["¿Cuánto se cobra?"]
    return state


def test_summary_is_rendered_by_code_from_the_structured_fields(monkeypatch):
    parsed = summary.RecruiterSummary(
        outcome="Cualificada.",
        profile_facts="Carnet y Madrid.",
        double_check="Carnet posiblemente caducado.",
        next_step="Llamar y responder cuánto se cobra.",
    )
    raw = AIMessage(
        content="", usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
    )
    model = FakeStructuredModel(parsed, raw)
    monkeypatch.setattr(summary, "chat_model", lambda model_id: model)
    result = summary.make_summarizer("fake:model")(decided_state())
    assert result.text.splitlines() == [
        "Cualificada.",
        "Carnet y Madrid.",
        "Carnet posiblemente caducado.",
        "Llamar y responder cuánto se cobra.",
    ]
    assert result.usage_metadata == raw.usage_metadata
    body = model.sent[-1].content
    assert "human: sí\nai: ¿Nombre?" in body
    assert "internal prompt" not in body
    assert "Status: qualified" in body
    assert "Licence may be expired" in body and "¿Cuánto se cobra?" in body


def test_missing_structured_summary_raises_so_the_engine_records_the_failure(monkeypatch):
    import pytest

    monkeypatch.setattr(summary, "chat_model", lambda model_id: FakeStructuredModel(None))
    with pytest.raises(summary.SummaryUnavailableError):
        summary.make_summarizer("fake:model")(decided_state())
