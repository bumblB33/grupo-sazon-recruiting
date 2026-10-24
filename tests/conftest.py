from collections.abc import Iterable

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from screening_agent.flow.engine import ScreeningEngine
from screening_agent.flow.graph import build_graph
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


@pytest.fixture
def make_engine():
    def _make(script: Iterable[AIMessage]):
        model = ScriptedToolModel(messages=iter(script), bound_tool_names=[], seen_inputs=[])
        graph = build_graph(model, lambda state, stage: "system")
        repository = Repository("sqlite:///:memory:")
        engine = ScreeningEngine(
            repository, graph, summarizer=lambda profile, status, msgs: "summary"
        )
        return engine, repository, model

    return _make
