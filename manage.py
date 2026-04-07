#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_subprocess(cmd: list[str]) -> int:
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        # Exit code used by shells for SIGINT / Ctrl+C.
        return 130


def runserver(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--log-level",
        args.log_level,
    ]
    if args.reload:
        cmd.append("--reload")
    return _run_subprocess(cmd)


def bootstrap_admin_totp(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "bootstrap-admin-totp",
        "--email",
        args.email,
        "--secret",
        args.secret,
    ]
    if args.firebase_uid:
        cmd.extend(["--firebase-uid", args.firebase_uid])
    if args.display_name:
        cmd.extend(["--display-name", args.display_name])
    return _run_subprocess(cmd)


def test(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if args.keyword:
        cmd.extend(["-k", args.keyword])
    return _run_subprocess(cmd)


def list_config_backups(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "list-config-backups",
        "--limit",
        str(args.limit),
    ]
    return _run_subprocess(cmd)


def restore_config_backup(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "restore-config-backup",
        "--backup-id",
        str(args.backup_id),
        "--actor-email",
        args.actor_email,
    ]
    if args.reason:
        cmd.extend(["--reason", args.reason])
    return _run_subprocess(cmd)


def _alembic_exec() -> str:
    candidate = Path(sys.executable).with_name("alembic")
    if candidate.exists():
        return str(candidate)
    return "alembic"


def migrate(args: argparse.Namespace) -> int:
    cmd = [_alembic_exec(), "upgrade", args.revision]
    return _run_subprocess(cmd)


def makemigration(args: argparse.Namespace) -> int:
    cmd = [_alembic_exec(), "revision", "--autogenerate", "-m", args.message]
    return _run_subprocess(cmd)


def downgrade(args: argparse.Namespace) -> int:
    cmd = [_alembic_exec(), "downgrade", args.revision]
    return _run_subprocess(cmd)


def stamp(args: argparse.Namespace) -> int:
    cmd = [_alembic_exec(), "stamp", args.revision]
    return _run_subprocess(cmd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TunnelDeck management commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    runserver_cmd = subparsers.add_parser("runserver", help="Run FastAPI backend")
    runserver_cmd.add_argument("--host", default="0.0.0.0")
    runserver_cmd.add_argument("--port", type=int, default=8000)
    runserver_cmd.add_argument("--reload", action="store_true")
    runserver_cmd.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )
    runserver_cmd.set_defaults(handler=runserver)

    bootstrap_cmd = subparsers.add_parser(
        "bootstrap-admin-totp",
        help="Create or update encrypted TOTP secret for an allowlisted admin",
    )
    bootstrap_cmd.add_argument("--email", required=True, help="Admin email")
    bootstrap_cmd.add_argument("--secret", required=True, help="Base32 TOTP secret")
    bootstrap_cmd.add_argument("--firebase-uid", required=False, default=None)
    bootstrap_cmd.add_argument("--display-name", required=False, default=None)
    bootstrap_cmd.set_defaults(handler=bootstrap_admin_totp)

    test_cmd = subparsers.add_parser("test", help="Run tests")
    test_cmd.add_argument("-k", "--keyword", required=False, default=None)
    test_cmd.set_defaults(handler=test)

    list_backups_cmd = subparsers.add_parser(
        "list-config-backups",
        help="List cloudflared config backups from DB",
    )
    list_backups_cmd.add_argument("--limit", type=int, default=20)
    list_backups_cmd.set_defaults(handler=list_config_backups)

    restore_backup_cmd = subparsers.add_parser(
        "restore-config-backup",
        help="Restore cloudflared config from a backup id",
    )
    restore_backup_cmd.add_argument("--backup-id", type=int, required=True)
    restore_backup_cmd.add_argument("--actor-email", required=False, default="system@local")
    restore_backup_cmd.add_argument("--reason", required=False, default=None)
    restore_backup_cmd.set_defaults(handler=restore_config_backup)

    migrate_cmd = subparsers.add_parser("migrate", help="Apply DB migrations (alembic upgrade)")
    migrate_cmd.add_argument("--revision", default="head")
    migrate_cmd.set_defaults(handler=migrate)

    make_migration_cmd = subparsers.add_parser(
        "makemigration",
        help="Create a new DB migration from model changes",
    )
    make_migration_cmd.add_argument("-m", "--message", required=True)
    make_migration_cmd.set_defaults(handler=makemigration)

    downgrade_cmd = subparsers.add_parser("downgrade", help="Rollback DB migration revision")
    downgrade_cmd.add_argument("--revision", required=True)
    downgrade_cmd.set_defaults(handler=downgrade)

    stamp_cmd = subparsers.add_parser(
        "stamp",
        help="Mark database with a migration revision without running migrations",
    )
    stamp_cmd.add_argument("--revision", default="head")
    stamp_cmd.set_defaults(handler=stamp)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
