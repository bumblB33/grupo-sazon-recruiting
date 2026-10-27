import argparse

from screening_agent.api.auth import hash_secret, new_api_key
from screening_agent.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recruiter accounts and machine API keys. Recruiters enrol themselves at login."
    )
    parser.add_argument("--db", default=None, help="Database URL, default from settings")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("recruiters", help="List recruiters")
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
    elif args.command in ("deactivate", "reactivate"):
        email = args.email.strip().lower()
        found = repository.set_recruiter_active(email, args.command == "reactivate")
        print(f"{email} {args.command}d" if found else f"{email} not found")
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
