"""Operator CLI.

python -m app.cli create-user --email you@example.com --role admin
python -m app.cli check-config
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.core.config_file import get_config
from app.db.session import _session_factory
from app.models import UserRole
from app.services.users import create_user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aegis")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.ANALYST.value)
    sub.add_parser("check-config")
    args = parser.parse_args(argv)

    if args.cmd == "check-config":
        cfg = get_config()
        print(f"config {cfg.config_version} OK, fingerprint {cfg.fingerprint()}")
        return 0

    password = getpass.getpass("Password (min 12 chars): ")
    if password != getpass.getpass("Repeat password: "):
        print("passwords do not match", file=sys.stderr)
        return 1
    with _session_factory()() as db:
        try:
            user = create_user(db, args.email, password, UserRole(args.role))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"created {user.role.value} {user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
