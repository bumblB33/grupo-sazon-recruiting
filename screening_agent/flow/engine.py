import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.exc import IntegrityError

from screening_agent.domain.enums import Language, ReviewReason, Status
from screening_agent.flow import replies
from screening_agent.flow.graph import build_graph
from screening_agent.flow.state import ScreeningState, is_closed
from screening_agent.llm.guardrail import check
from screening_agent.llm.summary import summarize
from screening_agent.llm.turn import build_prompt, live_model
from screening_agent.storage.repository import Repository, str_or_none

Summarizer = Callable[[dict[str, Any], str, list[AnyMessage]], str]

OFF_TOPIC_STRIKE_LIMIT = 2


class Outcome(StrEnum):
    REPLIED = "replied"
    DUPLICATE = "duplicate"
    CLOSED = "closed"


@dataclass(frozen=True)
class HandleResult:
    outcome: Outcome
    reply: str = ""
    # True on the turn that reached a terminal status; the channel then schedules summarize_outcome.
    terminal: bool = False


class ScreeningEngine:
    """Channel-agnostic: every channel calls handle() with a candidate id and raw text.

    Per-candidate locking is process-local; run one worker per candidate key when scaling out."""

    def __init__(
        self,
        repository: Repository,
        graph: CompiledStateGraph | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.repository = repository
        self.graph = graph or build_graph(live_model(), build_prompt)
        self.summarizer = summarizer or summarize
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    def handle(
        self, candidate_id: str, text: str, channel: str, external_id: str | None = None
    ) -> HandleResult:
        with self._locks[candidate_id]:
            if external_id and self.repository.has_message(external_id):
                return HandleResult(Outcome.DUPLICATE)
            state = self.repository.load_state(candidate_id)
            if is_closed(state):
                self.repository.record_message(candidate_id, "in", channel, text, external_id)
                return HandleResult(Outcome.CLOSED)
            new_state, reply = self._advance(candidate_id, state, text)
            try:
                self.repository.save_turn(new_state, channel, text, reply, external_id)
            except IntegrityError:
                # Another process won the race on the unique external_id.
                return HandleResult(Outcome.DUPLICATE)
            terminal = is_closed(new_state)
            if terminal:
                self._record_outcome(candidate_id, new_state)
            return HandleResult(Outcome.REPLIED, reply, terminal)

    def summarize_outcome(self, candidate_id: str) -> None:
        """Runs the summary LLM call outside the candidate lock and after the reply is sent."""
        state = self.repository.load_state(candidate_id)
        if not is_closed(state):
            return
        try:
            summary = self.summarizer(
                state.get("profile", {}), str(state["status"]), state["messages"]
            )
        except Exception as exc:  # a failed summary must not fail the candidate's reply
            self.repository.record_event(candidate_id, "summary_failed", {"error": str(exc)})
            return
        self.repository.set_summary(candidate_id, summary)

    def _advance(
        self, candidate_id: str, state: ScreeningState, text: str
    ) -> tuple[ScreeningState, str]:
        verdict = check(text)
        if not verdict.allowed:
            self.repository.record_event(
                candidate_id, "guardrail_blocked", {"reason": verdict.reason}
            )
            return _off_topic(state, text)
        new_state: ScreeningState = self.graph.invoke(
            {**state, "messages": [*state["messages"], HumanMessage(content=text)]}
        )
        return new_state, new_state.get("reply", "")

    def _record_outcome(self, candidate_id: str, state: ScreeningState) -> None:
        self.repository.record_event(
            candidate_id,
            "outcome",
            {
                "status": str(state["status"]),
                "disqualify_reason": str_or_none(state.get("disqualify_reason")),
                "review_reason": str_or_none(state.get("review_reason")),
            },
        )


def _off_topic(state: ScreeningState, text: str) -> tuple[ScreeningState, str]:
    language = state.get("language", Language.ES)
    strikes = state.get("invalid_counts", {}).get("off_topic", 0) + 1
    new_state: ScreeningState = {
        **state,
        "invalid_counts": {**state.get("invalid_counts", {}), "off_topic": strikes},
    }
    if strikes >= OFF_TOPIC_STRIKE_LIMIT:
        new_state["status"] = Status.NEEDS_RECRUITER_REVIEW
        new_state["review_reason"] = ReviewReason.OFF_TOPIC_CLOSE
        reply = replies.REVIEW[ReviewReason.OFF_TOPIC_CLOSE][language]
    else:
        reply = replies.OFF_TOPIC_REDIRECT[language]
    new_state["messages"] = [
        *state["messages"],
        HumanMessage(content=text),
        AIMessage(content=reply),
    ]
    return new_state, reply
