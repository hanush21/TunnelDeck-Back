from __future__ import annotations

import argparse
import sys

from fastapi import HTTPException

from app.core.config import get_settings
from app.infrastructure.persistence.database import get_db_session, init_db
from app.modules.audit.service import AuditService
from app.modules.security.service import SecurityService
from app.modules.tunnel.service import TunnelService


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


def list_config_backups(args: argparse.Namespace) -> int:
    if args.limit < 1:
        print("error: --limit must be >= 1", file=sys.stderr)
        return 1

    settings = get_settings()
    init_db()
    db = get_db_session()
    tunnel_service = TunnelService(settings)

    try:
        backups = tunnel_service.list_backups(db, limit=args.limit)
    except Exception as exc:
        print(f"error: failed to list backups: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    if not backups:
        print("no backups found")
        return 0

    for backup in backups:
        print(
            f"id={backup.id} created_at={backup.created_at.isoformat()} "
            f"triggered_by={backup.triggered_by} reason={backup.reason} path={backup.file_path}"
        )
    return 0


def restore_config_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db()
    db = get_db_session()
    tunnel_service = TunnelService(settings)
    audit_service = AuditService()

    try:
        rollback_record = tunnel_service.restore_backup(
            db,
            backup_id=args.backup_id,
            actor_email=args.actor_email,
            reason=args.reason,
        )
        audit_service.log_operation(
            db,
            actor_email=args.actor_email,
            action="cloudflared.restore_backup",
            resource_type="tunnel",
            resource_id=str(args.backup_id),
            success=True,
            details={
                "backup_id": args.backup_id,
                "safety_backup_id": rollback_record.id,
                "reason": args.reason,
            },
        )
        db.commit()
    except HTTPException as exc:
        db.rollback()
        try:
            audit_service.log_operation(
                db,
                actor_email=args.actor_email,
                action="cloudflared.restore_backup",
                resource_type="tunnel",
                resource_id=str(args.backup_id),
                success=False,
                details={"backup_id": args.backup_id, "reason": args.reason},
                error_message=str(exc.detail),
            )
            db.commit()
        except Exception:
            db.rollback()
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        print(f"error: restore failed ({exc.status_code}): {detail}", file=sys.stderr)
        return 1
    except Exception as exc:
        db.rollback()
        try:
            audit_service.log_operation(
                db,
                actor_email=args.actor_email,
                action="cloudflared.restore_backup",
                resource_type="tunnel",
                resource_id=str(args.backup_id),
                success=False,
                details={"backup_id": args.backup_id, "reason": args.reason},
                error_message=str(exc),
            )
            db.commit()
        except Exception:
            db.rollback()
        print(f"error: restore failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        "success: backup restored "
        f"(safety_backup_id={rollback_record.id}, file={rollback_record.file_path})"
    )
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

    list_backups_cmd = subparsers.add_parser(
        "list-config-backups",
        help="List latest cloudflared config backups registered in DB",
    )
    list_backups_cmd.add_argument("--limit", type=int, default=20)
    list_backups_cmd.set_defaults(handler=list_config_backups)

    restore_backup_cmd = subparsers.add_parser(
        "restore-config-backup",
        help="Restore cloudflared config from backup id",
    )
    restore_backup_cmd.add_argument("--backup-id", type=int, required=True)
    restore_backup_cmd.add_argument("--actor-email", required=False, default="system@local")
    restore_backup_cmd.add_argument(
        "--reason",
        required=False,
        default=None,
        help="Optional reason stored in config_backups",
    )
    restore_backup_cmd.set_defaults(handler=restore_config_backup)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
