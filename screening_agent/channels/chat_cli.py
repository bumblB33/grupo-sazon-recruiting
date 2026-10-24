import argparse
import uuid

from screening_agent.flow.engine import ScreeningEngine
from screening_agent.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description="Text loop against the screening graph.")
    parser.add_argument("--candidate", default=None, help="Resume an existing candidate id")
    parser.add_argument("--db", default=None, help="Database URL, default from settings")
    args = parser.parse_args()
    repository = Repository(args.db)
    engine = ScreeningEngine(repository)
    candidate_id = args.candidate or uuid.uuid4().hex[:8]
    print(f"candidate {candidate_id}. Type a message, Ctrl-D to quit.")
    try:
        while True:
            text = input("you> ").strip()
            if not text:
                continue
            result = engine.handle(candidate_id, text, channel="cli")
            print(f"agent> {result.reply}" if result.reply else f"agent> ({result.outcome})")
            if result.terminal:
                engine.summarize_outcome(candidate_id)
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__main__":
    main()
