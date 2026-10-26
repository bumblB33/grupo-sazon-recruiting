import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from screening_agent.config import settings
from screening_agent.domain.enums import Language, ReviewReason, Status
from screening_agent.flow import replies
from screening_agent.flow.graph import build_graph
from screening_agent.flow.silence import (
    SilenceAction,
    SilenceCandidate,
    nudges_due,
    silence_action,
)
from screening_agent.flow.state import ScreeningState, initial_state, is_closed, stage_of
from screening_agent.llm.guardrail import Guardrail, GuardrailVerdict
from screening_agent.llm.models import chat_model
from screening_agent.llm.summary import Summarizer, make_summarizer
from screening_agent.llm.turn import build_prompt
from screening_agent.storage.repository import (
    DuplicateMessageError,
    Repository,
    StaleStateError,
    str_or_none,
)

GuardrailCheck = Callable[[str], GuardrailVerdict]

OFF_TOPIC_STRIKE_LIMIT = 2
# A stale write means the cron sweep saved between our load and save; one re-run from fresh state.
STALE_RETRIES = 1


class OutboundChannel(Protocol):
    """Reaches a candidate with no inbound message to answer (opener, nudges)."""

    def send_text(self, candidate_id: str, text: str) -> None: ...

    def send_opener(self, candidate_id: str, text: str) -> None:
        """Delivers the first contact; a channel may substitute an approved template for the text."""
        ...


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


@dataclass(frozen=True)
class SweepReport:
    nudged: int = 0
    abandoned: int = 0
    failed: int = 0


class ScreeningEngine:
    """Channel-agnostic: every channel calls handle() with a candidate id and raw text.

    Per-candidate locking is process-local; run one worker per candidate key when scaling out."""

    def __init__(
        self,
        repository: Repository,
        graph: CompiledStateGraph | None = None,
        summarizer: Summarizer | None = None,
        guardrail: GuardrailCheck | None = None,
    ) -> None:
        self.repository = repository
        self.graph = graph or build_graph(chat_model(settings.live_model), build_prompt)
        self.summarizer = summarizer or make_summarizer(settings.summary_model)
        self.guardrail = guardrail or Guardrail.for_model(settings.guardrail_model).check
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    def handle(
        self, candidate_id: str, text: str, channel: str, external_id: str | None = None
    ) -> HandleResult:
        with self._locks[candidate_id]:
            if external_id and self.repository.has_message(external_id):
                return HandleResult(Outcome.DUPLICATE)
            for _ in range(STALE_RETRIES + 1):
                state = self.repository.load_state(candidate_id)
                if is_closed(state):
                    self.repository.record_message(candidate_id, "in", channel, text, external_id)
                    return HandleResult(Outcome.CLOSED)
                new_state, reply = self._advance(candidate_id, state, text)
                try:
                    self.repository.save_turn(new_state, channel, text, reply, external_id)
                except DuplicateMessageError:
                    # Another process won the race on the external id.
                    return HandleResult(Outcome.DUPLICATE)
                except StaleStateError:
                    continue
                terminal = is_closed(new_state)
                if terminal:
                    self._record_outcome(candidate_id, new_state)
                return HandleResult(Outcome.REPLIED, reply, terminal)
            raise StaleStateError(f"{candidate_id}: state kept changing under the turn")

    def start_conversation(
        self, candidate_id: str, channel: str, language: Language, outbound: OutboundChannel
    ) -> bool:
        """False when the candidate already exists."""
        with self._locks[candidate_id]:
            if self.repository.conversation_exists(candidate_id):
                return False
            text = replies.opener(language)
            outbound.send_opener(candidate_id, text)
            state = initial_state(candidate_id)
            state["language"] = language
            state["messages"] = [AIMessage(content=text)]
            try:
                self.repository.save_opener(state, channel, text)
            except StaleStateError:
                return False
            return True

    def sweep_silence(self, now: datetime, channels: Mapping[str, OutboundChannel]) -> SweepReport:
        """A channel with no outbound sender (CLI, evals) is never nudged, only abandoned on time."""
        nudged = abandoned = failed = 0
        for snapshot in self.repository.open_conversations():
            action = silence_action(now, snapshot)
            if action == SilenceAction.ABANDON:
                abandoned += self._abandon(now, snapshot.candidate_id)
            elif action == SilenceAction.NUDGE and snapshot.channel in channels:
                try:
                    nudged += self._nudge(now, snapshot.candidate_id, channels[snapshot.channel])
                except Exception as exc:  # one unreachable number must not stall the whole sweep
                    failed += 1
                    self.repository.record_event(
                        snapshot.candidate_id, "nudge_failed", {"error": str(exc)}
                    )
        return SweepReport(nudged=nudged, abandoned=abandoned, failed=failed)

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

    def _abandon(self, now: datetime, candidate_id: str) -> int:
        with self._locks[candidate_id]:
            fresh = self._recheck(now, candidate_id, SilenceAction.ABANDON)
            if fresh is None:
                return 0
            state = self.repository.load_state(candidate_id)
            new_state: ScreeningState = {**state, "status": Status.ABANDONED}
            try:
                self.repository.save_state(new_state, fresh.channel)
            except StaleStateError:
                return 0
            self._record_outcome(candidate_id, new_state)
            return 1

    def _nudge(self, now: datetime, candidate_id: str, outbound: OutboundChannel) -> int:
        with self._locks[candidate_id]:
            fresh = self._recheck(now, candidate_id, SilenceAction.NUDGE)
            if fresh is None:
                return 0
            state = self.repository.load_state(candidate_id)
            language = state.get("language", fresh.language)
            if fresh.awaiting_first_reply:
                text = replies.opener(language)
                outbound.send_opener(candidate_id, text)
            else:
                text = _nudge_text(state, language)
                outbound.send_text(candidate_id, text)
            count = nudges_due(now, fresh)
            new_state: ScreeningState = {
                **state,
                "messages": [*state["messages"], AIMessage(content=text)],
            }
            try:
                self.repository.save_nudge(new_state, fresh.channel, text, count)
            except StaleStateError:
                # The candidate replied while we were sending; their turn wins, the nudge is logged only.
                self.repository.record_event(candidate_id, "nudge_unrecorded", {"text": text})
                return 0
            self.repository.record_event(
                candidate_id, "nudge", {"count": count, "stage": stage_of(state).value}
            )
            return 1

    def _recheck(
        self, now: datetime, candidate_id: str, expected: SilenceAction
    ) -> SilenceCandidate | None:
        """The sweep decided on a snapshot taken outside the lock; a reply may have landed since."""
        fresh = self.repository.silence_candidate(candidate_id)
        if fresh is None or silence_action(now, fresh) != expected:
            return None
        if is_closed(self.repository.load_state(candidate_id)):
            return None
        return fresh

    def _advance(
        self, candidate_id: str, state: ScreeningState, text: str
    ) -> tuple[ScreeningState, str]:
        verdict = self.guardrail(text)
        if verdict.error:
            self.repository.record_event(candidate_id, "guardrail_failed", {"error": verdict.error})
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
                "stage": stage_of(state).value,
                "disqualify_reason": str_or_none(state.get("disqualify_reason")),
                "review_reason": str_or_none(state.get("review_reason")),
            },
        )


def _nudge_text(state: ScreeningState, language: Language) -> str:
    pending = state.get("pending_zone")
    if pending:
        question = replies.ZONE_CONFIRM[language].format(area=pending)
    else:
        question = replies.REASK[stage_of(state)][language]
    return replies.NUDGE[language].format(question=question)


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
