import argparse

from screening_agent.api.auth import email_domain_allowed, hash_secret, is_valid_email, new_api_key
from screening_agent.config import settings
from screening_agent.storage.repository import Repository


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


if __name__ == "__main__":
    main()
