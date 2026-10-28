import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from screening_agent.api.auth import email_domain_allowed, hash_secret, is_valid_email, new_api_key
from screening_agent.channels.whatsapp import TwilioWhatsAppSender
from screening_agent.config import settings
from screening_agent.domain.enums import Language
from screening_agent.domain.names import clean_applicant_name
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.storage.repository import Repository


class Applicant(BaseModel):
    """One row of the applicant file; the same contract as POST /candidates."""

    name: str = Field(max_length=120)
    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    language: Language = Language.ES

    @field_validator("name")
    @classmethod
    def name_is_made_of_words(cls, value: str) -> str:
        return clean_applicant_name(value)


def load_applicants(path: Path) -> list[Applicant]:
    """Validates the whole file before anything is sent, so a bad row cannot leave a half-seeded demo."""
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("applicant file must be a JSON list")
    applicants: list[Applicant] = []
    for index, row in enumerate(rows, start=1):
        try:
            applicants.append(TypeAdapter(Applicant).validate_python(row))
        except ValueError as exc:
            raise ValueError(f"entry {index}: {exc}") from exc
    return applicants


def start_from_file(
    path: Path, engine: ScreeningEngine, outbound: OutboundChannel, dry_run: bool = False
) -> list[str]:
    lines: list[str] = []
    for applicant in load_applicants(path):
        if dry_run:
            outcome = "would open"
        elif engine.start_conversation(
            applicant.phone, "whatsapp", applicant.language, outbound, applicant.name
        ):
            outcome = "opened"
        else:
            outcome = "skipped, already exists"
        lines.append(f"{applicant.phone}\t{applicant.name}\t{applicant.language.value}\t{outcome}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recruiter accounts and machine API keys. Only an invited address can log in."
    )
    parser.add_argument("--db", default=None, help="Database URL, default from settings")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("recruiters", help="List recruiters")
    invite = commands.add_parser("invite", help="Allow a work address to log in")
    invite.add_argument("email")
    deactivate = commands.add_parser("deactivate", help="Block a recruiter's login and sessions")
    deactivate.add_argument("email")
    reactivate = commands.add_parser("reactivate", help="Allow a recruiter to log in again")
    reactivate.add_argument("email")
    commands.add_parser("api-keys", help="List API keys")
    create = commands.add_parser("create-api-key", help="Mint a key; the secret is printed once")
    create.add_argument("label", help="Who or what uses it, e.g. ats-sync")
    revoke = commands.add_parser("revoke-api-key", help="Disable a key by id")
    revoke.add_argument("key_id")
    start = commands.add_parser(
        "start-from-file", help="Open a WhatsApp screening for each applicant in a JSON file"
    )
    start.add_argument("path", type=Path, help="JSON list of {name, phone, language}")
    start.add_argument("--dry-run", action="store_true", help="Validate and list, send nothing")
    args = parser.parse_args()
    repository = Repository(args.db)

    if args.command == "recruiters":
        for recruiter in repository.list_recruiters():
            state = "active" if recruiter.active else "deactivated"
            print(f"{recruiter.email}\t{state}\tlast login {recruiter.last_login_at or 'never'}")
    elif args.command == "invite":
        email = args.email.strip().lower()
        if not is_valid_email(email):
            parser.error(f"{email!r} is not a plain email address")
        if not email_domain_allowed(email, settings.recruiter_email_domains):
            parser.error(f"{email} is not at a domain in SCREENING_RECRUITER_EMAIL_DOMAINS")
        recruiter = repository.invite_recruiter(email)
        print(f"{email} invited" if recruiter.active else f"{email} is deactivated; reactivate it")
    elif args.command == "deactivate":
        email = args.email.strip().lower()
        repository.deactivate_recruiter(email)
        print(f"{email} deactivated")
    elif args.command == "reactivate":
        email = args.email.strip().lower()
        found = repository.reactivate_recruiter(email)
        print(f"{email} reactivated" if found else f"{email} not found")
    elif args.command == "api-keys":
        for key in repository.list_api_keys():
            state = "active" if key.active else "revoked"
            print(f"{key.key_id}\t{key.label}\t{state}\tcreated {key.created_at:%Y-%m-%d}")
    elif args.command == "create-api-key":
        key_id, secret, presented = new_api_key()
        repository.save_api_key(key_id, hash_secret(secret), args.label)
        print(f"X-API-Key: {presented}")
        print("Store it now; it is not shown again.")
    elif args.command == "revoke-api-key":
        found = repository.revoke_api_key(args.key_id)
        print(f"{args.key_id} revoked" if found else f"{args.key_id} not found")
    elif args.command == "start-from-file":
        engine = ScreeningEngine(repository)
        outbound = TwilioWhatsAppSender.from_settings()
        try:
            lines = start_from_file(args.path, engine, outbound, dry_run=args.dry_run)
        except ValueError as exc:
            parser.error(str(exc))
        print("\n".join(lines))


if __name__ == "__main__":
    main()
