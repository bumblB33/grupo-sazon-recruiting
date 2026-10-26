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
    repository.override("a", "in_progress", None)
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
