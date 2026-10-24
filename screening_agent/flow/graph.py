from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from screening_agent.config import settings
from screening_agent.domain.enums import Language, ReviewReason, Stage, Status
from screening_agent.domain.language import detect_language
from screening_agent.domain.profile import CandidateProfile
from screening_agent.flow import replies
from screening_agent.flow.state import ScreeningState, is_closed, stage_of
from screening_agent.flow.tools import ALL_TOOLS, TOOL_STAGE, tools_for
from screening_agent.flow.transitions import Transition, apply_patch, qualify_if_complete

PromptBuilder = Callable[[ScreeningState, Stage], str]


class UnexpectedModelOutputError(RuntimeError):
    pass


def exposed_tools(state: dict[str, Any]):
    profile = CandidateProfile.model_validate(state.get("profile", {}))
    return tools_for(stage_of(state), profile.missing_fields(), bool(state.get("pending_zone")))


def build_graph(llm: BaseChatModel, build_prompt: PromptBuilder):
    def turn(state: ScreeningState) -> dict[str, Any]:
        language = _language_of_last_human(state)
        tools = exposed_tools(state)
        bound = llm.bind_tools(tools) if tools else llm
        messages = [
            SystemMessage(content=build_prompt(state, stage_of(state))),
            *state["messages"],
        ]
        response = bound.invoke(messages)
        return {
            "messages": [response],
            "language": language,
        }

    def apply_tools(state: ScreeningState) -> dict[str, Any]:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            raise UnexpectedModelOutputError(
                f"expected AIMessage from turn, got {type(last).__name__}"
            )
        language = state.get("language", Language.ES)
        turn_state = TurnState(state)
        tool_messages: list[ToolMessage] = []
        reask_stages: list[Stage] = []
        strike_stages: list[Stage] = []
        confirm_area: str | None = None

        for call in last.tool_calls:
            if turn_state.closed:
                tool_messages.append(
                    ToolMessage(content="ignored: conversation closed", tool_call_id=call["id"])
                )
                continue
            # Allowed tools are recomputed per call so consent plus name in one message both land.
            transition = _run_tool(call, turn_state.working)
            if transition.error:
                tool_messages.append(
                    ToolMessage(content=f"rejected: {transition.error}", tool_call_id=call["id"])
                )
                reask_stages.append(transition.failed_stage or Stage.FULL_NAME)
                if transition.candidate_fault:
                    strike_stages.append(transition.failed_stage or Stage.FULL_NAME)
                continue
            tool_messages.append(ToolMessage(content="recorded", tool_call_id=call["id"]))
            turn_state.apply(transition.updates)
            confirm_area = transition.confirm_area or confirm_area

        for stage in strike_stages:
            turn_state.apply(_count_rejection(turn_state.working, stage))
        turn_state.apply(qualify_if_complete(turn_state.working))

        reply = _choose_reply(turn_state.working, language, reask_stages, confirm_area, last.text)
        if reply != last.text:
            tool_messages.append(AIMessage(content=reply))
        return {**turn_state.updates, "messages": tool_messages, "reply": reply}

    graph = StateGraph(ScreeningState)
    graph.add_node("turn", turn)
    graph.add_node("apply_tools", apply_tools)
    graph.add_edge(START, "turn")
    graph.add_edge("turn", "apply_tools")
    graph.add_edge("apply_tools", END)
    return graph.compile()


class TurnState:
    """Accumulates this turn's state updates and keeps the merged working view in step with them."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.updates: dict[str, Any] = {"profile": dict(state.get("profile", {}))}
        self.working: dict[str, Any] = {**state, **self.updates}

    @property
    def closed(self) -> bool:
        return is_closed(self.working)

    def apply(self, patch: dict[str, Any]) -> None:
        patch = dict(patch)
        self.updates["profile"].update(patch.pop("profile", {}))
        self.updates.update(patch)
        self.working = {**self.working, **self.updates}


def _run_tool(call: dict[str, Any], state: dict[str, Any]) -> Transition:
    name = call["name"]
    if name not in {tool.name for tool in exposed_tools(state)}:
        return Transition.rejected(
            stage_of(state), f"tool {name} not available now", candidate_fault=False
        )
    try:
        patch = ALL_TOOLS[name].invoke(call["args"])
    except Exception as exc:  # tool arg validation errors come from pydantic and langchain
        return Transition.rejected(TOOL_STAGE[name], f"invalid arguments: {exc}")
    return apply_patch(state, patch)


def _count_rejection(state: dict[str, Any], stage: Stage) -> dict[str, Any]:
    counts = dict(state.get("invalid_counts", {}))
    counts[stage.value] = counts.get(stage.value, 0) + 1
    updates: dict[str, Any] = {"invalid_counts": counts}
    if counts[stage.value] >= settings.reask_limit and state.get("status") == Status.IN_PROGRESS:
        updates["status"] = Status.NEEDS_RECRUITER_REVIEW
        updates["review_reason"] = ReviewReason.REPEATED_INVALID_ANSWER
    return updates


def _choose_reply(
    state: dict[str, Any],
    language: Language,
    reask_stages: list[Stage],
    confirm_area: str | None,
    model_text: str,
) -> str:
    terminal = _terminal_reply(state, language)
    if terminal:
        return terminal
    if reask_stages:
        return replies.REASK[min(reask_stages, key=_stage_index)][language]
    if confirm_area:
        return replies.ZONE_CONFIRM[language].format(area=confirm_area)
    if model_text:
        return model_text
    return replies.REASK[stage_of(state)][language]


def _stage_index(stage: Stage) -> int:
    return list(Stage).index(stage)


def _language_of_last_human(state: ScreeningState) -> Language:
    for message in reversed(state["messages"]):
        if message.type == "human":
            return detect_language(str(message.content), default=state.get("language", Language.ES))
    return state.get("language", Language.ES)


def _terminal_reply(state: dict[str, Any], language: Language) -> str | None:
    status = state.get("status", Status.IN_PROGRESS)
    if status == Status.DISQUALIFIED:
        return replies.DISQUALIFIED[state["disqualify_reason"]][language]
    if status == Status.NEEDS_RECRUITER_REVIEW:
        return replies.REVIEW[state["review_reason"]][language]
    if status == Status.QUALIFIED:
        first_name = (state.get("profile", {}).get("full_name") or "").split(" ")[0]
        return replies.QUALIFIED[language].format(first_name=first_name)
    return None
