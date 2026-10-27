from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from screening_agent.flow.state import initial_state
from screening_agent.storage.repository import DuplicateMessageError, Repository, StaleStateError


def saved(repository: Repository, candidate_id: str, **state_overrides) -> None:
    state = {**initial_state(candidate_id), **state_overrides}
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
    saved(repository, "a")
    stale = repository.load_state("a")
    repository.save_turn(repository.load_state("a"), "cli", "otra", "r", external_id="a-2")
    with pytest.raises(StaleStateError):
        repository.save_state(stale, "cli")
    assert repository.load_state("a")["version"] == 2


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


def test_enrol_recruiter_is_idempotent_and_keeps_deactivation(repository):
    first = repository.enrol_recruiter("ana@gruposazon.com")
    assert first.active
    repository.set_recruiter_active("ana@gruposazon.com", False)
    assert not repository.enrol_recruiter("ana@gruposazon.com").active
