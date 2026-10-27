import argparse
import sys
from datetime import UTC, datetime

from screening_agent.channels.whatsapp import OutboundNotConfiguredError, TwilioWhatsAppSender
from screening_agent.config import settings
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.observability import configure_observability
from screening_agent.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Silence sweep for cron: nudge quiet candidates, abandon the rest."
    )
    parser.add_argument("--db", default=None, help="Database URL, default from settings")
    args = parser.parse_args()
    if settings.logfire_token:
        configure_observability("screening-sweep")
    engine = ScreeningEngine(Repository(args.db))
    channels: dict[str, OutboundChannel] = {}
    try:
        channels["whatsapp"] = TwilioWhatsAppSender.from_settings()
    except OutboundNotConfiguredError as exc:
        print(f"whatsapp outbound disabled, abandon only: {exc}", file=sys.stderr)
    report = engine.sweep_silence(datetime.now(UTC), channels)
    print(f"nudged {report.nudged} abandoned {report.abandoned}")


if __name__ == "__main__":
    main()
