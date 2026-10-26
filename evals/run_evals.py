import sys
import uuid

from evals.graders import grade
from evals.personas.text_personas import PERSONAS
from screening_agent.config import settings
from screening_agent.flow.engine import Outcome, ScreeningEngine
from screening_agent.storage.repository import Repository


def main() -> int:
    failures = 0
    for persona in PERSONAS:
        repository = Repository(f"{settings.database_url}_eval_{uuid.uuid4().hex[:8]}")
        engine = ScreeningEngine(repository)
        agent_turns = 0
        for index, text in enumerate(persona.turns):
            result = engine.handle(
                persona.name, text, channel="eval", external_id=f"{persona.name}-{index}"
            )
            if result.outcome != Outcome.REPLIED:
                break
            agent_turns += 1
            if result.terminal:
                engine.summarize_outcome(persona.name)
        candidate = repository.get_candidate(persona.name)
        if candidate is None:
            print(f"FAIL {persona.name} ['no candidate saved']")
            failures += 1
            continue
        result = grade(candidate, agent_turns, persona.expected)
        print(f"{'PASS' if result.passed else 'FAIL'} {persona.name} {list(result.failures)}")
        failures += not result.passed
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
