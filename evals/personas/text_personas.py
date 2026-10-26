from dataclasses import dataclass

from evals.graders import Expectation


@dataclass(frozen=True)
class Persona:
    name: str
    turns: tuple[str, ...]
    expected: Expectation


PERSONAS: tuple[Persona, ...] = (
    Persona(
        name="no_licence",
        turns=("hola", "sí", "Luis Hernández", "no tengo carnet"),
        expected=Expectation(status="disqualified", disqualify_reason="no_licence", max_turns=5),
    ),
    Persona(
        name="wrong_city",
        turns=("hola", "sí", "Marta Ruiz", "sí", "vivo en Toledo"),
        expected=Expectation(
            status="disqualified", disqualify_reason="outside_service_area", max_turns=6
        ),
    ),
)
