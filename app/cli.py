from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.infrastructure.persistence.database import get_db_session, init_db
from app.modules.security.service import SecurityService


def bootstrap_admin_totp(args: argparse.Namespace) -> int:
    settings = get_settings()
    email = args.email.strip().lower()

    if email not in settings.allowed_admin_emails:
        print(
            f"error: '{email}' is not in ALLOWED_ADMIN_EMAILS. Add it before bootstrapping.",
            file=sys.stderr,
        )
        return 1

    init_db()
    db = get_db_session()
    security_service = SecurityService(settings)

    try:
        security_service.set_user_totp_secret(
            db,
            email=email,
            secret=args.secret.strip(),
            firebase_uid=args.firebase_uid,
            display_name=args.display_name,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"error: failed to bootstrap admin TOTP: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"success: TOTP secret configured for {email}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TunnelDeck backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_cmd = subparsers.add_parser(
        "bootstrap-admin-totp",
        help="Create or update encrypted TOTP secret for an allowlisted admin",
    )
    bootstrap_cmd.add_argument("--email", required=True, help="Admin email")
    bootstrap_cmd.add_argument("--secret", required=True, help="Base32 TOTP secret")
    bootstrap_cmd.add_argument("--firebase-uid", required=False, default=None)
    bootstrap_cmd.add_argument("--display-name", required=False, default=None)
    bootstrap_cmd.set_defaults(handler=bootstrap_admin_totp)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
