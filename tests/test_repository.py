from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from screening_agent.domain.enums import MessageKind
from screening_agent.flow.state import ScreeningState, initial_state
from screening_agent.storage.models import TranscriptEntry, unanswered_agent_messages
from screening_agent.storage.repository import (
    DuplicateMessageError,
    Repository,
    StaleStateError,
    UnansweredLimitError,
)


def saved(repository: Repository, candidate_id: str, **state_overrides) -> None:
    state = cast(ScreeningState, {**initial_state(candidate_id), **state_overrides})
    repository.save_turn(state, "cli", "hola", "reply", external_id=f"{candidate_id}-1")


def test_funnel_counts_by_status_and_stage(repository):
    saved(repository, "a")
    saved(repository, "b", consent=True)
    saved(repository, "c", consent=True, status="disqualified")
    funnel = repository.funnel()
    assert funnel["by_status"] == {"in_progress": 2, "disqualified": 1}
    assert funnel["by_stage"] == {"consent": 1, "full_name": 2}


def test_list_candidates_filters_by_status_and_stage(repository):
    saved(repository, "a")
    saved(repository, "b", consent=True)
    saved(repository, "c", consent=True, status="disqualified")
    assert [c.id for c in repository.list_candidates(status="disqualified")] == ["c"]
    assert {c.id for c in repository.list_candidates(stage="full_name")} == {"b", "c"}
    assert len(repository.list_candidates()) == 3


def test_stale_version_write_is_refused(repository):
    phone = "+34600999888"
    saved(repository, phone)
    stale = repository.load_state(phone)
    repository.save_turn(repository.load_state(phone), "cli", "otra", "r", external_id="a-2")
    with pytest.raises(StaleStateError) as refused:
        repository.save_state(stale, "cli")
    assert repository.load_state(phone)["version"] == 2
    # Tracing records exception messages unscrubbed, and the candidate id is a phone number.
    assert "34600999888" not in str(refused.value)


def test_reopen_override_resets_silence_clock(repository):
    saved(repository, "a", status="abandoned")
    before = repository.silence_candidate("a")
    repository.override("a", "in_progress", None, actor="recruiter:test")
    after = repository.silence_candidate("a")
    assert after.nudge_count == 0
    assert after.last_inbound_at >= before.last_inbound_at
    assert repository.load_state("a")["status"] == "in_progress"


def test_duplicate_external_id_is_refused_and_leaves_no_entry(repository):
    saved(repository, "a")
    with pytest.raises(DuplicateMessageError):
        repository.save_turn(repository.load_state("a"), "cli", "otra", "r", external_id="a-1")
    assert repository.load_state("a")["version"] == 1
    assert repository.has_message("a-1")
    assert not repository.has_message("a-2")


def entry(direction, kind=None):
    return TranscriptEntry(direction=direction, channel="cli", body="x", kind=kind)


def test_unanswered_count_skips_nudges_and_resets_on_inbound():
    nudge = entry("out", MessageKind.NUDGE)
    assert unanswered_agent_messages([entry("out", MessageKind.OPENER), nudge, nudge]) == 1
    assert unanswered_agent_messages([entry("out"), entry("out"), entry("in"), nudge]) == 0
    assert unanswered_agent_messages([entry("in"), entry("out"), entry("out")]) == 2


def test_stored_entry_without_kind_counts_as_unanswered():
    assert unanswered_agent_messages([entry("out")]) == 1


def stack_openers(repository, candidate_id, count):
    for _ in range(count):
        repository.save_opener(repository.load_state(candidate_id), "cli", "hola")


def test_third_unanswered_agent_message_is_refused_and_leaves_no_entry(repository):
    phone = "+34600111222"
    stack_openers(repository, phone, 2)
    with pytest.raises(UnansweredLimitError) as refused:
        stack_openers(repository, phone, 1)
    assert len(repository.get_candidate_detail(phone).transcript) == 2
    assert repository.load_state(phone)["version"] == 2
    assert "34600111222" not in str(refused.value)


def test_nudge_and_candidate_turn_are_accepted_at_the_limit(repository):
    stack_openers(repository, "a", 2)
    repository.save_nudge(repository.load_state("a"), "cli", "¿sigues ahí?", nudge_count=1)
    repository.save_turn(repository.load_state("a"), "cli", "sí", "reply", external_id="a-1")
    kinds = [e.kind for e in repository.get_candidate_detail("a").transcript]
    assert kinds == [
        MessageKind.OPENER,
        MessageKind.OPENER,
        MessageKind.NUDGE,
        None,
        MessageKind.REPLY,
    ]


COOLDOWN = timedelta(seconds=60)
WINDOW = timedelta(hours=1)
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def acquire(repository, email="a@gruposazon.com", ip="1.1.1.1", now=NOW, ip_limit=100):
    return repository.try_acquire_login_slot(email, ip, now, COOLDOWN, ip_limit, WINDOW)


def test_login_cooldown_is_per_address_and_expires(repository):
    assert acquire(repository)
    assert not acquire(repository)
    assert acquire(repository, email="b@gruposazon.com")
    assert not acquire(repository, now=NOW + timedelta(seconds=59))
    assert acquire(repository, now=NOW + COOLDOWN)


def test_login_cooldown_admits_one_of_many_concurrent_requests(repository):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: acquire(repository), range(32)))
    assert results.count(True) == 1


def test_login_ip_limit_counts_per_ip_per_window(repository):
    emails = [f"u{index}@gruposazon.com" for index in range(4)]
    granted = [acquire(repository, email=email, ip_limit=2) for email in emails[:3]]
    assert granted == [True, True, False]
    assert acquire(repository, email=emails[3], ip="2.2.2.2", ip_limit=2)
    later = NOW + WINDOW
    assert acquire(repository, email=emails[2], ip_limit=2, now=later)


def test_invite_deactivate_and_reactivate_recruiter(repository):
    assert repository.invite_recruiter("ana@gruposazon.com").active
    assert repository.invite_recruiter("ana@gruposazon.com").sessions_valid_after is None
    repository.deactivate_recruiter("ana@gruposazon.com")
    blocked = repository.get_recruiter("ana@gruposazon.com")
    assert not blocked.active and blocked.sessions_valid_after is not None
    assert repository.reactivate_recruiter("ana@gruposazon.com")
    assert repository.get_recruiter("ana@gruposazon.com").active
    assert not repository.reactivate_recruiter("nobody@gruposazon.com")


def test_deactivate_blocks_an_address_before_its_first_login(repository):
    repository.deactivate_recruiter("mallory@gruposazon.com")
    assert not repository.get_recruiter("mallory@gruposazon.com").active
    # An invite after a block does not lift the block.
    assert not repository.invite_recruiter("mallory@gruposazon.com").active


def test_archive_frees_the_id_and_keeps_transcript_and_events_under_the_archive_id(repository):
    phone = "+34600111222"
    saved(repository, phone)
    repository.record_event(phone, "outcome", {"status": "qualified"})

    archive_id = repository.archive_candidate(phone, actor="ana@gruposazon.com")

    assert archive_id is not None and archive_id != phone
    assert repository.get_candidate(phone) is None
    assert repository.load_state(phone)["version"] == 0
    archived = repository.get_candidate_detail(archive_id)
    assert archived is not None
    assert archived.archived_at is not None
    assert archived.archived_by == "ana@gruposazon.com"
    assert [e.body for e in archived.transcript] == ["hola", "reply"]
    assert [(e.kind, e.candidate_id) for e in archived.events] == [
        ("outcome", archive_id),
        ("demo_reset", archive_id),
    ]
    assert archived.events[-1].payload == {"actor": "ana@gruposazon.com", "reset_id": phone}
    assert repository.list_events(phone) == []
    assert repository.archive_candidate(phone, actor="ana@gruposazon.com") is None


def test_archived_copies_are_hidden_from_the_list_funnel_and_sweep(repository):
    saved(repository, "+34600111222")
    saved(repository, "+34600111223")
    repository.archive_candidate("+34600111222", actor="dev-mode")
    assert [c.id for c in repository.list_candidates()] == ["+34600111223"]
    assert repository.funnel()["by_status"] == {"in_progress": 1}
    assert [c.candidate_id for c in repository.open_conversations()] == ["+34600111223"]


def test_archive_retries_when_a_writer_commits_after_the_fence(repository, monkeypatch):
    phone = "+34600111222"
    saved(repository, phone)
    real_delete = repository.candidates.delete_one
    interleaved: list[int] = []

    def delete_after_a_turn(query):
        if not interleaved:
            interleaved.append(1)
            state = repository.load_state(phone)
            repository.save_turn(state, "cli", "late", "reply", external_id="late-1")
        return real_delete(query)

    monkeypatch.setattr(repository.candidates, "delete_one", delete_after_a_turn)
    archive_id = repository.archive_candidate(phone, actor="dev-mode")
    assert archive_id is not None
    assert repository.get_candidate(phone) is None
    archived = repository.get_candidate_detail(archive_id)
    assert archived is not None
    assert [e.body for e in archived.transcript] == ["hola", "reply", "late", "reply"]
