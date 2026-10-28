import argparse
import uuid

from screening_agent.domain.enums import Language
from screening_agent.flow.engine import ScreeningEngine
from screening_agent.storage.repository import Repository


class ConsoleOutbound:
    def send_text(self, candidate_id: str, text: str) -> None:
        print(f"agent> {text}")

    def send_opener(self, candidate_id: str, text: str, first_name: str | None = None) -> None:
        print(f"agent> {text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Text loop against the screening graph.")
    parser.add_argument("--candidate", default=None, help="Resume an existing candidate id")
    parser.add_argument("--db", default=None, help="Database URL, default from settings")
    parser.add_argument("--language", type=Language, choices=list(Language), default=Language.ES)
    args = parser.parse_args()
    repository = Repository(args.db)
    engine = ScreeningEngine(repository)
    candidate_id = args.candidate or uuid.uuid4().hex[:8]
    print(f"candidate {candidate_id}. Type a message, Ctrl-D to quit.")
    engine.start_conversation(candidate_id, "cli", args.language, ConsoleOutbound())
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
