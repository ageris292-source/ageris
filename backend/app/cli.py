"""Operator CLI.

python -m app.cli create-user --email you@example.com --role admin
python -m app.cli check-config
python -m app.cli check-deploy     # production readiness (exit 1 on any problem)
python -m app.cli ingest-nse --nifty50 --years 5 --with-research   # licensed NSE data
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date, datetime

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
    nse = sub.add_parser(
        "ingest-nse", help="licensed NSE end-of-day prices + corporate actions (bhavcopy)"
    )
    nse.add_argument("tickers", nargs="*", help="NSE tickers, e.g. TCS.NS (or use --nifty50)")
    nse.add_argument("--nifty50", action="store_true", help="today's NIFTY 50 list from NSE")
    nse.add_argument("--years", type=int, default=5)
    nse.add_argument("--since", help="start date YYYY-MM-DD (instead of --years)")
    nse.add_argument(
        "--offline",
        action="store_true",
        help="use only a feeder bundle in --dir (never contact NSE)",
    )
    nse.add_argument("--dir", help="data directory (default: AEGIS_DATA_CACHE_DIR/nse_bhavcopy)")
    nse.add_argument(
        "--with-research",
        action="store_true",
        help="also fetch fundamentals and news (unlicensed research sources)",
    )
    ing = sub.add_parser(
        "ingest", help="add NSE/BSE stocks and fetch prices, financials and news for them"
    )
    ing.add_argument("tickers", nargs="+", help="e.g. TCS.NS RELIANCE.NS")
    ing.add_argument("--years", type=int, default=5)
    ing.add_argument("--skip-news", action="store_true")
    pre = sub.add_parser(
        "prefetch-nse",
        help="feeder: download NSE files into --dir and write a bundle (no database needed)",
    )
    pre.add_argument("tickers", nargs="*")
    pre.add_argument("--nifty50", action="store_true")
    pre.add_argument("--years", type=int, default=5)
    pre.add_argument("--since", help="start date YYYY-MM-DD (instead of --years)")
    pre.add_argument("--dir", required=True, help="local cache directory (kept between runs)")
    pre.add_argument("--bundle", required=True, help="output .tar.gz for the deployment")
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
    if args.cmd == "ingest-nse":
        return _ingest_nse(
            args.tickers,
            args.nifty50,
            args.years,
            args.with_research,
            since=args.since,
            offline=args.offline,
            data_dir=args.dir,
        )
    if args.cmd == "prefetch-nse":
        return _prefetch_nse(
            args.tickers, args.nifty50, args.years, args.since, args.dir, args.bundle
        )

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


def _ingest(tickers: list[str], years: int, skip_news: bool, *, prices: bool = True) -> int:
    """Idempotent: re-running only adds new or revised data (versioned)."""
    from datetime import UTC, datetime, timedelta

    from app.fundamentals import service as fs
    from app.market_data import service as md
    from app.market_data.types import InvalidTickerError, Ticker
    from app.news import service as ns

    now = datetime.now(UTC)
    yahoo = md.build_provider("yahoo")
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
                if (label == "news" and news is None) or (label == "prices" and not prices):
                    continue
                try:
                    if label == "prices":
                        status = md.ingest_from_provider(
                            db, stock, yahoo, start, now.date(), now=now
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


def _nse_symbols(tickers: list[str], nifty50: bool, data_dir: str | None) -> list[str]:
    """NSE symbols from explicit tickers and/or NIFTY 50 (NSE's published list,
    or the list inside a feeder bundle when NSE is not reachable)."""
    import json
    from pathlib import Path

    from app.market_data.providers.nse_bhavcopy import nifty50_symbols
    from app.market_data.types import Exchange, Ticker

    out = [t.symbol for t in (Ticker.parse(x) for x in tickers) if t.exchange is Exchange.NSE]
    if nifty50:
        bundled = Path(data_dir) / "universe.json" if data_dir else None
        if bundled is not None and bundled.is_file():
            out += json.loads(bundled.read_text())
        else:
            out += nifty50_symbols()
    return list(dict.fromkeys(out))


def _window(years: int, since: str | None) -> tuple[date, datetime]:
    from datetime import UTC, timedelta

    now = datetime.now(UTC)
    start = date.fromisoformat(since) if since else now.date() - timedelta(days=365 * years)
    return start, now


def _prefetch_nse(
    tickers: list[str], nifty50: bool, years: int, since: str | None, data_dir: str, bundle: str
) -> int:
    from pathlib import Path

    from app.market_data import service as md
    from app.market_data.providers.nse_bhavcopy import NseBhavcopyProvider

    syms = _nse_symbols(tickers, nifty50, None)
    if not syms:
        print("give tickers or --nifty50", file=sys.stderr)
        return 2
    start, now = _window(years, since)
    p = md.build_provider("nse_bhavcopy", cache_dir=Path(data_dir))
    assert isinstance(p, NseBhavcopyProvider)
    got = p.prefetch(syms, start, now.date(), now)
    info = p.write_bundle(Path(bundle), syms, start, now.date(), now)
    print(f"prefetched {got}; bundle {bundle}: {info}", flush=True)
    return 0


def _ingest_nse(
    tickers: list[str],
    nifty50: bool,
    years: int,
    research: bool,
    *,
    since: str | None = None,
    offline: bool = False,
    data_dir: str | None = None,
) -> int:
    """Idempotent backfill, one calendar year at a time (each year commits,
    so an interrupted run resumes cheaply; downloaded files are cached).
    With --offline, only a feeder bundle unpacked in --dir is used."""
    from datetime import timedelta
    from pathlib import Path

    from app.market_data import service as md
    from app.market_data.types import Ticker

    if offline and not data_dir:
        print("--offline needs --dir", file=sys.stderr)
        return 2
    syms = _nse_symbols(tickers, nifty50, data_dir)
    if not syms:
        print("give tickers or --nifty50", file=sys.stderr)
        return 2
    start, now = _window(years, since)
    provider = md.build_provider(
        "nse_bhavcopy", offline=offline, cache_dir=Path(data_dir) if data_dir else None
    )
    failures = 0
    with _session_factory()() as db:
        stocks = [md.add_stock(db, Ticker.parse(f"{s}.NS"), None) for s in syms]
        s = start
        while s <= now.date():
            e = min(date(s.year, 12, 31), now.date())
            res = md.ingest_nse(db, stocks, s, e, now=now, provider=provider)
            bad = {k: v for k, v in res.items() if v in ("failed", "rejected")}
            failures += len(bad)
            print(f"{s}..{e}: {len(res) - len(bad)} ok, failed: {bad or '-'}", flush=True)
            s = e + timedelta(days=1)
        if research:
            failures += _ingest([str(md.ticker_of(x)) for x in stocks], years, False, prices=False)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
