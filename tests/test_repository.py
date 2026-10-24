from screening_agent.flow.state import initial_state
from screening_agent.storage.repository import Repository


def saved(repository: Repository, candidate_id: str, **state_overrides) -> None:
    state = {**initial_state(candidate_id), **state_overrides}
    repository.save_turn(state, "cli", "hola", "reply", external_id=f"{candidate_id}-1")


def test_funnel_counts_by_status_and_stage():
    repository = Repository("sqlite:///:memory:")
    saved(repository, "a")
    saved(repository, "b", consent=True)
    saved(repository, "c", consent=True, status="disqualified")
    funnel = repository.funnel()
    assert funnel["by_status"] == {"in_progress": 2, "disqualified": 1}
    assert funnel["by_stage"] == {"consent": 1, "full_name": 2}


def test_list_candidates_filters_by_status_and_stage():
    repository = Repository("sqlite:///:memory:")
    saved(repository, "a")
    saved(repository, "b", consent=True)
    saved(repository, "c", consent=True, status="disqualified")
    assert [c.id for c in repository.list_candidates(status="disqualified")] == ["c"]
    assert {c.id for c in repository.list_candidates(stage="full_name")} == {"b", "c"}
    assert len(repository.list_candidates()) == 3
