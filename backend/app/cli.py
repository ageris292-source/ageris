"""Operator CLI.

python -m app.cli create-user --email you@example.com --role admin
python -m app.cli check-config
python -m app.cli check-deploy     # production readiness (exit 1 on any problem)
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
    sub.add_parser("check-deploy", help="report production-readiness problems (exit 1 if any)")
    ing = sub.add_parser(
        "ingest", help="add NSE/BSE stocks and fetch prices, financials and news for them"
    )
    ing.add_argument("tickers", nargs="+", help="e.g. TCS.NS RELIANCE.NS")
    ing.add_argument("--years", type=int, default=5)
    ing.add_argument("--skip-news", action="store_true")
    sub.add_parser("ingest-macro", help="fetch World Bank + market series (NIFTY, VIX, FX, oil)")
    args = parser.parse_args(argv)

    if args.cmd == "ingest":
        return _ingest(args.tickers, args.years, args.skip_news)
    if args.cmd == "ingest-macro":
        from app.macro import service as ms

        with _session_factory()() as db:
            for series, status in ms.ingest_all(db, None).items():
                print(f"{series}: {status}")
        return 0

    if args.cmd == "check-config":
        cfg = get_config()
        print(f"config {cfg.config_version} OK, fingerprint {cfg.fingerprint()}")
        return 0

    if args.cmd == "check-deploy":
        return _check_deploy()

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


def _ingest(tickers: list[str], years: int, skip_news: bool) -> int:
    """Idempotent: re-running only adds new or revised data (versioned)."""
    from datetime import UTC, datetime, timedelta

    from app.fundamentals import service as fs
    from app.market_data import service as md
    from app.market_data.types import InvalidTickerError, Ticker
    from app.news import service as ns

    now = datetime.now(UTC)
    prices = md.build_provider("yahoo")
    fin = fs.build_provider()
    news = None if skip_news else ns.build_news_provider()
    failures = 0
    with _session_factory()() as db:
        for raw in tickers:
            try:
                t = Ticker.parse(raw)
            except InvalidTickerError as exc:
                print(f"{raw}: {exc}", file=sys.stderr)
                failures += 1
                continue
            stock = md.add_stock(db, t, None)
            start = now.date() - timedelta(days=365 * years)
            for label in ("prices", "financials", "news"):
                if label == "news" and news is None:
                    continue
                try:
                    if label == "prices":
                        status = md.ingest_from_provider(
                            db, stock, prices, start, now.date(), now=now
                        ).run.status
                    elif label == "financials":
                        status = fs.ingest_from_yahoo(db, stock, fin, None).status
                    else:
                        assert news is not None
                        status = ns.ingest_news(db, stock, news, None).status
                    print(f"{t} {label}: {status}")
                except Exception as exc:  # report and continue with the next step
                    db.rollback()
                    failures += 1
                    print(f"{t} {label}: failed ({exc.__class__.__name__}: {exc})", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())


def _check_deploy() -> int:
    """Validate environment + config as production would, without secrets in
    the output. Also runs outside AEGIS_ENV=production to vet a deployment."""
    from app.core.settings import SettingsError, get_settings, production_problems
    from app.trade.gates import self_test

    try:
        settings = get_settings()
        cfg = get_config()
    except (SettingsError, RuntimeError) as exc:
        print(f"FAIL {exc}")
        return 1
    problems = production_problems(settings)
    ok, why = self_test(cfg)
    if not ok:
        problems.append(f"trade engine self-test failed: {why}")
    if settings.environment.value != "production":
        problems.append(f"AEGIS_ENV is {settings.environment.value}, not production")
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"OK production checks passed (config {cfg.fingerprint()[:12]})")
    return 1 if problems else 0
