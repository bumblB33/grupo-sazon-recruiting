import uuid
from collections.abc import Callable, Iterable

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from screening_agent.flow.engine import ScreeningEngine
from screening_agent.flow.graph import build_graph
from screening_agent.llm.guardrail import GuardrailVerdict, permit_all
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


@pytest.fixture(scope="session")
def mongo_url() -> Iterable[str]:
    """One Mongo container per session; each test gets its own database name for isolation."""
    try:
        from testcontainers.community.mongodb import MongoDbContainer

        container = MongoDbContainer("mongo:7").start()
    except Exception as exc:  # no Docker socket on this machine
        pytest.skip(f"MongoDB test container unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def repository(mongo_url: str) -> Repository:
    return Repository(f"{mongo_url.rstrip('/')}/test_{uuid.uuid4().hex}")


@pytest.fixture
def make_engine(repository: Repository):
    def _make(
        script: Iterable[AIMessage],
        guardrail: Callable[[str], GuardrailVerdict] = permit_all,
    ):
        model = ScriptedToolModel(messages=iter(script), bound_tool_names=[], seen_inputs=[])
        graph = build_graph(model, lambda state, stage: "system")
        engine = ScreeningEngine(
            repository,
            graph,
            summarizer=lambda profile, status, msgs: "summary",
            guardrail=guardrail,
        )
        return engine, repository, model

    return _make


class FakeOutbound:
    """Records what the engine sends; satisfies OutboundChannel for sweep and API tests."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.openers: list[tuple[str, str]] = []

    def send_text(self, candidate_id: str, text: str) -> None:
        self.texts.append((candidate_id, text))

    def send_opener(self, candidate_id: str, text: str) -> None:
        self.openers.append((candidate_id, text))

