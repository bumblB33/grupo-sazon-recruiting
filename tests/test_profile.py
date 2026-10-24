import pytest
from pydantic import ValidationError

from screening_agent.domain.enums import Stage
from screening_agent.domain.profile import CandidateProfile


def test_stage_is_first_missing_field():
    assert CandidateProfile().current_stage() == Stage.FULL_NAME
    assert CandidateProfile(full_name="Ana García", has_licence=True).current_stage() == Stage.ZONE


def test_full_name_requires_two_alphabetic_tokens():
    with pytest.raises(ValidationError):
        CandidateProfile(full_name="Ana")
    with pytest.raises(ValidationError):
        CandidateProfile(full_name="Ana 123")
    assert CandidateProfile(full_name="  Ana  García ").full_name == "Ana García"


def test_experience_years_bounds():
    with pytest.raises(ValidationError):
        CandidateProfile(experience_years=41)
    assert CandidateProfile(experience_years=0).experience_years == 0
