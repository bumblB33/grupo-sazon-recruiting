from screening_agent.domain.names import first_name, name_similarity


def test_same_person_scores_high_across_case_accents_order_and_extra_surnames():
    assert name_similarity("Ana García", "ana garcia") == 1.0
    assert name_similarity("García Ana", "Ana García") == 1.0
    assert name_similarity("Ana García", "Ana María García López") >= 0.8


def test_different_people_score_low():
    assert name_similarity("Ana García", "Pedro Martínez") < 0.5
    assert name_similarity("", "Pedro Martínez") == 0.0


def test_first_name_is_the_first_token():
    assert first_name("Pedro Martínez Ruiz") == "Pedro"
    assert first_name("  ") == ""
