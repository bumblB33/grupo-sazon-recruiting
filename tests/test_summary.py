from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from screening_agent.llm import summary


def test_summarizer_sends_human_and_ai_text_only_with_block_content_flattened(monkeypatch):
    sent = []

    def capture(messages):
        sent.extend(messages)
        return AIMessage(content="resumen")

    monkeypatch.setattr(summary, "chat_model", lambda model_id: RunnableLambda(capture))
    transcript = [
        SystemMessage(content="internal prompt"),
        HumanMessage(content="sí"),
        AIMessage(content=[{"type": "text", "text": "¿Nombre?"}]),
    ]
    result = summary.make_summarizer("fake:model")({"consent": True}, "qualified", transcript)
    body = sent[-1].content
    assert result.text == "resumen"
    assert "human: sí\nai: ¿Nombre?" in body
    assert "internal prompt" not in body
    assert "Status: qualified" in body
