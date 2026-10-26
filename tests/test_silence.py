from datetime import UTC, datetime, timedelta

from screening_agent.domain.enums import Language, Status
from screening_agent.flow.engine import Outcome
from screening_agent.flow.silence import SilenceAction, SilenceCandidate, nudges_due, silence_action
from tests.conftest import FakeOutbound, ai

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def candidate(last_inbound_hours_ago: float | None, nudges: int) -> SilenceCandidate:
    return SilenceCandidate(
        candidate_id="c",
        channel="whatsapp",
        language=Language.ES,
        opened_at=T0 - timedelta(hours=72),
        last_inbound_at=None
        if last_inbound_hours_ago is None
        else T0 - timedelta(hours=last_inbound_hours_ago),
        nudge_count=nudges,
    )


def test_after_reply_schedule_nudges_twice_then_abandons():
    assert silence_action(T0, candidate(1, 0)) == SilenceAction.NONE
    assert silence_action(T0, candidate(2, 0)) == SilenceAction.NUDGE
    assert silence_action(T0, candidate(5, 1)) == SilenceAction.NONE
    assert silence_action(T0, candidate(23, 1)) == SilenceAction.NUDGE
    assert silence_action(T0, candidate(23.5, 2)) == SilenceAction.NONE
    assert silence_action(T0, candidate(24, 2)) == SilenceAction.ABANDON


def test_abandon_wins_when_nudges_were_missed():
    assert silence_action(T0, candidate(30, 0)) == SilenceAction.ABANDON


def test_late_sweep_counts_every_passed_threshold_as_sent():
    assert nudges_due(T0, candidate(23.5, 0)) == 2
    assert silence_action(T0, candidate(23.5, 2)) == SilenceAction.NONE


def test_opener_schedule_counts_from_opened_at():
    opened = SilenceCandidate("c", "whatsapp", Language.ES, T0 - timedelta(hours=23), None, 0)
    assert silence_action(T0, opened) == SilenceAction.NONE
    retry = SilenceCandidate("c", "whatsapp", Language.ES, T0 - timedelta(hours=24), None, 0)
    assert silence_action(T0, retry) == SilenceAction.NUDGE
    gone = SilenceCandidate("c", "whatsapp", Language.ES, T0 - timedelta(hours=48), None, 1)
    assert silence_action(T0, gone) == SilenceAction.ABANDON


def events(repository, kind: str) -> list[dict]:
    return [event["payload"] for event in repository.events.find({"kind": kind})]


def test_opener_then_silence_retries_template_and_abandons_at_consent(make_engine):
    engine, repository, model = make_engine([])
    outbound = FakeOutbound()
    assert engine.start_conversation("+34600", "whatsapp", Language.EN, outbound)
    assert not engine.start_conversation("+34600", "whatsapp", Language.EN, outbound)
    assert len(outbound.openers) == 1
    assert "AI assistant" in outbound.openers[0][1]
    assert [m.type for m in repository.load_state("+34600")["messages"]] == ["ai"]

    now = datetime.now(UTC)
    report = engine.sweep_silence(now + timedelta(hours=1), {"whatsapp": outbound})
    assert (report.nudged, report.abandoned) == (0, 0)
    report = engine.sweep_silence(now + timedelta(hours=24), {"whatsapp": outbound})
    assert report.nudged == 1
    assert len(outbound.openers) == 2
    report = engine.sweep_silence(now + timedelta(hours=48), {"whatsapp": outbound})
    assert report.abandoned == 1
    saved = repository.get_candidate("+34600")
    assert saved.status == Status.ABANDONED
    assert saved.stage == "consent"
    assert events(repository, "outcome")[0]["stage"] == "consent"
    assert model.seen_inputs == []


def test_reply_after_opener_sees_it_and_asks_name(make_engine):
    engine, repository, model = make_engine([ai("", "record_consent", {"accepted": True})])
    engine.start_conversation("+34600", "whatsapp", Language.ES, FakeOutbound())
    result = engine.handle("+34600", "sí", "whatsapp", external_id="m0")
    assert [m.type for m in model.seen_inputs[0]] == ["system", "ai", "human"]
    assert "nombre" in result.reply
    assert repository.get_candidate("+34600").stage == "full_name"


def test_silence_after_reply_nudges_with_stage_question_then_abandons(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"accepted": True})])
    outbound = FakeOutbound()
    engine.handle("+34601", "sí", "whatsapp", external_id="m0")
    now = datetime.now(UTC)
    engine.sweep_silence(now + timedelta(hours=2), {"whatsapp": outbound})
    assert len(outbound.texts) == 1
    assert "nombre" in outbound.texts[0][1]
    assert "Sigues" in outbound.texts[0][1]
    engine.sweep_silence(now + timedelta(hours=2, minutes=5), {"whatsapp": outbound})
    assert len(outbound.texts) == 1
    engine.sweep_silence(now + timedelta(hours=23), {"whatsapp": outbound})
    assert len(outbound.texts) == 2
    assert events(repository, "nudge")[-1]["count"] == 2
    engine.sweep_silence(now + timedelta(hours=24), {"whatsapp": outbound})
    saved = repository.get_candidate("+34601")
    assert saved.status == Status.ABANDONED
    assert saved.stage == "full_name"
    assert engine.handle("+34601", "hola", "whatsapp", external_id="m1").outcome == Outcome.CLOSED


def test_candidate_reply_resets_nudges_and_keeps_nudge_in_history(make_engine):
    engine, repository, _ = make_engine(
        [ai("Hola", "record_consent", {"accepted": True}), ai("¿Nombre?")]
    )
    outbound = FakeOutbound()
    engine.handle("+34602", "sí", "whatsapp", external_id="m0")
    now = datetime.now(UTC)
    engine.sweep_silence(now + timedelta(hours=2), {"whatsapp": outbound})
    engine.handle("+34602", "un momento", "whatsapp", external_id="m1")
    assert repository.silence_candidate("+34602").nudge_count == 0
    history = repository.load_state("+34602")["messages"]
    assert history[-3].type == "ai" and "Sigues" in history[-3].content


def test_channel_without_outbound_is_only_abandoned(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"accepted": True})])
    engine.handle("cli-1", "sí", "cli", external_id="m0")
    now = datetime.now(UTC)
    assert engine.sweep_silence(now + timedelta(hours=3), {}).nudged == 0
    assert engine.sweep_silence(now + timedelta(hours=25), {}).abandoned == 1
    assert repository.get_candidate("cli-1").status == Status.ABANDONED


class FailingOutbound(FakeOutbound):
    def send_text(self, candidate_id: str, text: str) -> None:
        if candidate_id == "+34610":
            raise RuntimeError("unreachable number")
        super().send_text(candidate_id, text)


def test_one_failed_send_does_not_stall_the_sweep(make_engine):
    engine, repository, _ = make_engine(
        [
            ai("Hola", "record_consent", {"accepted": True}),
            ai("Hola", "record_consent", {"accepted": True}),
        ]
    )
    engine.handle("+34610", "sí", "whatsapp", external_id="m0")
    engine.handle("+34611", "sí", "whatsapp", external_id="m1")
    outbound = FailingOutbound()
    report = engine.sweep_silence(datetime.now(UTC) + timedelta(hours=2), {"whatsapp": outbound})
    assert (report.nudged, report.failed) == (1, 1)
    assert [phone for phone, _ in outbound.texts] == ["+34611"]
    assert "unreachable" in events(repository, "nudge_failed")[0]["error"]


def test_reply_landing_during_sweep_wins(make_engine):
    engine, repository, _ = make_engine(
        [ai("Hola", "record_consent", {"accepted": True}), ai("¿Nombre?")]
    )
    engine.handle("+34620", "sí", "whatsapp", external_id="m0")
    now = datetime.now(UTC)

    class ReplyingOutbound(FakeOutbound):
        def send_text(self, candidate_id: str, text: str) -> None:
            super().send_text(candidate_id, text)
            # Simulates the webhook in another process committing while the nudge is in flight.
            engine.repository.save_turn(
                {**repository.load_state(candidate_id)}, "whatsapp", "ya voy", "", "m1"
            )

    report = engine.sweep_silence(now + timedelta(hours=2), {"whatsapp": ReplyingOutbound()})
    assert report.nudged == 0
    assert repository.silence_candidate("+34620").nudge_count == 0
    assert events(repository, "nudge_unrecorded")
