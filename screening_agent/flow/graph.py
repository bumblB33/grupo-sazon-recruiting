import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.graph import END, START, StateGraph

from screening_agent.config import settings
from screening_agent.domain.enums import Language, ReviewReason, Stage, Status
from screening_agent.domain.language import detect_language
from screening_agent.domain.names import first_name
from screening_agent.domain.profile import CandidateProfile
from screening_agent.flow import replies
from screening_agent.flow.reply_policy import style_failures
from screening_agent.flow.state import ScreeningState, is_closed, stage_of
from screening_agent.flow.tools import ALL_TOOLS, TOOL_STAGE, request_stop, tools_for
from screening_agent.flow.transitions import Transition, apply_patch, qualify_if_complete
from screening_agent.flow.turn_record import ReplySource, ToolCallRecord
from screening_agent.llm.turn import (
    COMPOSE_INSTRUCTION,
    GUIDANCE_CONSENT_DEFERRED,
    GUIDANCE_CONTINUE,
    GUIDANCE_REJECTED,
    GUIDANCE_RESTYLE,
)
from screening_agent.llm.usage import elapsed_ms, usage_of

PromptBuilder = Callable[[ScreeningState, Stage], str]


class UnexpectedModelOutputError(RuntimeError):
    pass


def exposed_tools(state: Mapping[str, Any]):
    profile = CandidateProfile.model_validate(state.get("profile", {}))
    return tools_for(
        stage_of(state),
        profile.missing_fields(),
        bool(state.get("pending_zone")),
        bool(state.get("pending_name")),
    )


def build_graph(llm: BaseChatModel, build_prompt: PromptBuilder, model_id: str = ""):
    """turn extracts with tools, apply_tools runs code, compose lets the model write the reply once it
    has seen the tool results. compose is skipped when the first text can go out as it is."""

    def turn(state: ScreeningState) -> dict[str, Any]:
        language = _language_of_last_human(state)
        tools = exposed_tools(state)
        bound = llm.bind_tools(tools) if tools else llm
        messages = [
            SystemMessage(content=build_prompt(state, stage_of(state))),
            *state["messages"],
        ]
        started = time.perf_counter()
        response = bound.invoke(messages)
        latency_ms = elapsed_ms(started, time.perf_counter())
        return {
            "messages": [response],
            "language": language,
            "turn": {
                "tools_exposed": [tool.name for tool in tools],
                "usage": [usage_of(response, "turn", model_id, latency_ms)],
            },
        }

    def apply_tools(state: ScreeningState) -> dict[str, Any]:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            raise UnexpectedModelOutputError(
                f"expected AIMessage from turn, got {type(last).__name__}"
            )
        language = state.get("language", Language.ES)
        turn_state = TurnState(state)
        tool_messages: list[ToolMessage | AIMessage] = []
        call_records: list[ToolCallRecord] = []
        rejections: list[tuple[Stage, str]] = []
        strike_stages: list[Stage] = []
        confirm_area: str | None = None
        confirm_name: str | None = None
        consent_deferred = False

        # A stop request wins over anything else in the same message, whatever order the model used.
        calls = sorted(last.tool_calls, key=lambda call: call["name"] != request_stop.name)
        for call in calls:
            if turn_state.closed:
                tool_messages.append(
                    ToolMessage(content="ignored: conversation closed", tool_call_id=call["id"])
                )
                call_records.append(
                    ToolCallRecord(name=call["name"], accepted=False, message="conversation closed")
                )
                continue
            # Allowed tools are recomputed per call so consent plus name in one message both land.
            transition = _run_tool(call, turn_state.working)
            if transition.error:
                tool_messages.append(
                    ToolMessage(content=f"rejected: {transition.error}", tool_call_id=call["id"])
                )
                call_records.append(
                    ToolCallRecord(name=call["name"], accepted=False, message=transition.error)
                )
                failed_stage = transition.failed_stage or Stage.FULL_NAME
                rejections.append((failed_stage, transition.error))
                if transition.candidate_fault:
                    strike_stages.append(failed_stage)
                continue
            tool_messages.append(ToolMessage(content="recorded", tool_call_id=call["id"]))
            call_records.append(ToolCallRecord(name=call["name"], accepted=True))
            turn_state.apply(transition.updates)
            confirm_area = transition.confirm_area or confirm_area
            confirm_name = transition.confirm_name or confirm_name
            consent_deferred = consent_deferred or transition.consent_deferred

        # A strike is one rejected candidate message per stage, not one per tool call in it.
        for stage in dict.fromkeys(strike_stages):
            turn_state.apply(_count_rejection(turn_state.working, stage))
        turn_state.apply(qualify_if_complete(turn_state.working))

        choice = _choose_reply(
            turn_state.working,
            language,
            rejections,
            confirm_area,
            confirm_name,
            consent_deferred,
            last.text,
        )
        turn = {
            **state.get("turn", {}),
            "tool_calls": call_records,
            "reply_source": choice.source,
            "model_text": last.text if choice.text != last.text and last.text else None,
            "violated_rules": choice.violated_rules,
        }
        if choice.guidance:
            turn["compose_guidance"] = choice.guidance
            turn["compose_question"] = choice.question
        elif choice.text != last.text:
            tool_messages.append(AIMessage(content=choice.text))
        return {
            **turn_state.updates,
            "messages": tool_messages,
            "reply": choice.text,
            "turn": turn,
        }

    def compose(state: ScreeningState) -> dict[str, Any]:
        """The fallback text chosen by apply_tools goes out unless the model writes a reply that
        passes the style rules and asks (or, for a wait message, does not ask) a question."""
        turn = dict(state.get("turn", {}))
        guidance = turn.pop("compose_guidance")
        question = turn.pop("compose_question", None)
        language = state.get("language", Language.ES)
        fallback = state.get("reply", "")
        system = SystemMessage(
            content=f"{build_prompt(state, stage_of(state))}\n"
            f"{COMPOSE_INSTRUCTION.format(guidance=guidance)}"
        )
        # The history holds tool_use blocks, and Anthropic rejects those unless tools are defined.
        # Any tool call the model still makes here is ignored; only the text is used.
        tools = exposed_tools(state)
        bound = llm.bind_tools(tools) if tools else llm
        started = time.perf_counter()
        try:
            response = bound.invoke([system, *_history_for_compose(state["messages"])])
        except (
            Exception
        ) as exc:  # a provider failure after the state is decided must not lose the turn
            turn["violated_rules"] = [f"compose failed: {type(exc).__name__}"]
            return {"messages": [AIMessage(content=fallback)], "turn": turn}
        latency_ms = elapsed_ms(started, time.perf_counter())
        turn["usage"] = [
            *turn.get("usage", []),
            usage_of(response, "compose", model_id, latency_ms),
        ]
        text = response.text
        if not text:
            return {"messages": [AIMessage(content=fallback)], "turn": turn}
        failures = [*style_failures(text, language), *_question_failures(text, question)]
        if failures:
            turn["violated_rules"] = failures
            turn["model_text"] = text
            return {"messages": [AIMessage(content=fallback)], "turn": turn}
        turn["reply_source"] = ReplySource.MODEL_COMPOSED
        turn["violated_rules"] = []
        composed = AIMessage(content=text, usage_metadata=response.usage_metadata)
        return {"messages": [composed], "reply": text, "turn": turn}

    def needs_compose(state: ScreeningState) -> str:
        return "compose" if state.get("turn", {}).get("compose_guidance") else END

    graph = StateGraph(ScreeningState)
    graph.add_node("turn", turn)
    graph.add_node("apply_tools", apply_tools)
    graph.add_node("compose", compose)
    graph.add_edge(START, "turn")
    graph.add_edge("turn", "apply_tools")
    graph.add_conditional_edges("apply_tools", needs_compose, ["compose", END])
    graph.add_edge("compose", END)
    return graph.compile()


class TurnState:
    """Accumulates this turn's state updates and keeps the merged working view in step with them."""

    def __init__(self, state: Mapping[str, Any]) -> None:
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


def _run_tool(call: ToolCall, state: dict[str, Any]) -> Transition:
    name = call["name"]
    if name not in {tool.name for tool in exposed_tools(state)}:
        return Transition.rejected(
            stage_of(state), f"tool {name} not available now", candidate_fault=False
        )
    try:
        patch = ALL_TOOLS[name].invoke(call["args"])
    except Exception as exc:  # tool arg validation errors come from pydantic and langchain
        return Transition.rejected(
            TOOL_STAGE.get(name, stage_of(state)), f"invalid arguments: {exc}"
        )
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
    rejections: list[tuple[Stage, str]],
    confirm_area: str | None,
    confirm_name: str | None,
    consent_deferred: bool,
    model_text: str,
) -> "ReplyChoice":
    """Terminal messages are fixed. Everything else is a fallback text plus the guidance the model
    gets to write the reply itself; model text from the first call is kept when it needs no rewrite."""
    terminal = _terminal_reply(state, language)
    if terminal:
        return ReplyChoice(terminal, ReplySource.TERMINAL)
    if rejections:
        stage, reason = min(rejections, key=lambda item: _stage_index(item[0]))
        guidance = GUIDANCE_REJECTED.format(reason=reason)
        # A rejection at the current stage re-asks what is pending there, which may be a confirmation.
        if stage == stage_of(state):
            return ReplyChoice(
                replies.next_question(state, language), ReplySource.REASK, guidance, question=True
            )
        return ReplyChoice(
            replies.REASK[stage][language], ReplySource.REASK, guidance, question=True
        )
    if confirm_area:
        text = replies.ZONE_CONFIRM[language].format(area=confirm_area)
        return ReplyChoice(text, ReplySource.ZONE_CONFIRM, GUIDANCE_CONTINUE, question=True)
    if confirm_name:
        text = replies.NAME_CONFIRM[language].format(name=confirm_name)
        return ReplyChoice(text, ReplySource.NAME_CONFIRM, GUIDANCE_CONTINUE, question=True)
    if consent_deferred:
        text = replies.CONSENT_LATER[language]
        return ReplyChoice(
            text, ReplySource.CONSENT_DEFERRED, GUIDANCE_CONSENT_DEFERRED, question=False
        )
    next_question = replies.next_question(state, language)
    if not model_text:
        return ReplyChoice(
            next_question, ReplySource.NEXT_QUESTION, GUIDANCE_CONTINUE, question=True
        )
    violated = style_failures(model_text, language)
    if violated:
        guidance = GUIDANCE_RESTYLE.format(rules=", ".join(violated))
        return ReplyChoice(
            next_question, ReplySource.POLICY_FALLBACK, guidance, violated, question=True
        )
    return ReplyChoice(model_text, ReplySource.MODEL_TEXT)


@dataclass(frozen=True)
class ReplyChoice:
    text: str
    source: ReplySource
    # Set when the model should write the reply; `text` is then the fallback if it cannot.
    guidance: str | None = None
    violated_rules: list[str] = field(default_factory=list)
    # True: the composed text must ask the pending question. False: it must not ask anything.
    question: bool | None = None


def _question_failures(text: str, question: bool | None) -> list[str]:
    asked = "?" in text
    if question is True and not asked:
        return ["no question"]
    if question is False and asked:
        return ["asked a question"]
    return []


def _history_for_compose(messages: list[AnyMessage]) -> list[AnyMessage]:
    """A trailing draft with no tool calls is dropped: a provider would continue it as a prefill
    instead of writing a new message, and an empty one is rejected outright."""
    history = list(messages)
    if history and isinstance(history[-1], AIMessage) and not history[-1].tool_calls:
        history.pop()
    return history


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
        name = first_name(state.get("profile", {}).get("full_name") or "")
        return replies.QUALIFIED[language].format(first_name=name)
    return None
