"""Phase 16: licensed NSE end-of-day data — bhavcopy files (both formats) and
NSE corporate actions, with no network access (httpx MockTransport)."""

from __future__ import annotations

import io
import itertools
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.backtest.data import load_stock
from app.core.config_file import ProviderSettings, get_config
from app.market_data import service as md
from app.market_data.calendar import get_calendar
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.providers.nse_bhavcopy import (
    NseBhavcopyProvider,
    parse,
    parse_actions,
    url_for,
)
from app.market_data.types import PriceBasis, Ticker

CAL = get_calendar()
SETTINGS = ProviderSettings(enabled=True, licensed=True, timeout_seconds=5)
LEGACY_DAY = date(2024, 7, 5)  # last legacy-format file
UDIFF_DAY = date(2024, 7, 8)  # first UDiFF file
NOW = datetime(2024, 7, 9, 12, tzinfo=UTC)

LEGACY_HEAD = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"  # noqa: E501  (verbatim NSE text)
UDIFF_HEAD = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,"
    "PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,"
    "TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", text)
    return buf.getvalue()


def legacy(day: date, rows: list[tuple[str, str, float, int]]) -> bytes:
    stamp = day.strftime("%d-%b-%Y").upper()
    lines = [LEGACY_HEAD] + [
        f"{s},{ser},{c},{c * 1.01:.2f},{c * 0.99:.2f},{c},{c},{c},{v},1,{stamp},1,INE0,"
        for s, ser, c, v in rows
    ]
    return _zip("\n".join(lines))


def udiff(day: date, rows: list[tuple[str, str, float, int]]) -> bytes:
    lines = [UDIFF_HEAD] + [
        f"{day},{day},CM,NSE,STK,1,INE0,{s},{ser},,,,,{s} LTD,{c},{c * 1.01:.2f},{c * 0.99:.2f},"
        f"{c},{c},{c},,{c},,,{v},1,1,F1,1,,,,,"
        for s, ser, c, v in rows
    ]
    return _zip("\n".join(lines))


# Subjects exactly as NSE words them (recorded from the live feed).
ACTIONS: dict[str, list[dict[str, str]]] = {
    "RELIANCE": [
        {"exDate": "28-Oct-2024", "subject": "Bonus 1:1", "series": "EQ"},
        {"exDate": "14-Aug-2025", "subject": "Dividend - Rs 5.5 Per Share", "series": "EQ"},
    ],
    "TCS": [
        {"exDate": "05-Jul-2024", "subject": "Interim Dividend - Rs 10 Per Share", "series": "EQ"},
    ],
}


def transport(
    files: dict[date, bytes], actions: dict[str, Any] | None = None, fail_actions: str = ""
) -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []
    acts = ACTIONS if actions is None else actions

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "corporates-corporateActions" in str(req.url):
            sym = req.url.params["symbol"]
            if sym == fail_actions:
                return httpx.Response(503)
            year = int(req.url.params["from_date"][-4:])
            items = [a for a in acts.get(sym, []) if a["exDate"].endswith(str(year))]
            return httpx.Response(200, json=items)
        for d, content in files.items():
            if str(req.url) == url_for(d):
                return httpx.Response(200, content=content)
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def provider(t: httpx.MockTransport, cache: Path | None = None) -> NseBhavcopyProvider:
    return NseBhavcopyProvider(
        SETTINGS, CAL, timedelta(minutes=60), cache_dir=cache, transport=t, sleep=lambda _s: None
    )


# ------------------------------------------------------------------ parsing --


def test_both_file_formats_parse_eq_rows_only() -> None:
    assert url_for(LEGACY_DAY).endswith("/historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip")
    assert url_for(UDIFF_DAY).endswith("/cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip")
    old = parse(legacy(LEGACY_DAY, [("TCS", "EQ", 3900.5, 100), ("TCS", "BE", 1, 1)]), LEGACY_DAY)
    new = parse(udiff(UDIFF_DAY, [("TCS", "EQ", 3950.0, 200), ("SGB", "GB", 1, 1)]), UDIFF_DAY)
    assert set(old) == {"TCS"} and old["TCS"].close == Decimal("3900.5")
    assert set(new) == {"TCS"} and new["TCS"].volume == 200 and new["TCS"].name == "TCS LTD"
    with pytest.raises(ProviderError, match="dated"):  # a file for the wrong day is refused
        parse(udiff(UDIFF_DAY, [("TCS", "EQ", 1, 1)]), date(2024, 7, 9))
    with pytest.raises(ProviderError):
        parse(b"not a zip", UDIFF_DAY)


def test_corporate_action_subjects() -> None:
    items = [
        {"exDate": "28-Oct-2024", "subject": "Bonus 1:1", "series": "EQ"},
        {"exDate": "03-Mar-2020", "subject": " Bonus 3:2", "series": "EQ"},
        {
            "exDate": "28-Jul-2022",
            "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",  # noqa: E501  (verbatim NSE text)
            "series": "EQ",
        },
        {
            "exDate": "14-Jul-2011",
            "subject": "Face Value Split From Rs.10/- To Rs.2/-",
            "series": "EQ",
        },
        {
            "exDate": "05-Jan-2021",
            "subject": "Consolidation Of Shares From Rs 1 To Rs 10",
            "series": "EQ",
        },
        {
            "exDate": "31-May-2024",
            "subject": "Annual General Meeting/Special Dividend - Rs 8 Per Share /Dividend - Rs 20 Per Share",  # noqa: E501  (verbatim NSE text)
            "series": "EQ",
        },
        {"exDate": "06-Jul-2009", "subject": "Agm/Div-Rs.16/- Per Share", "series": "EQ"},
        {
            "exDate": "31-Jan-2018",
            "subject": " Rights - 4:25 Fully Paid Up Shares @ Premium Rs 500/- Per Share",
            "series": "EQ",
        },
        {"exDate": "23-Aug-2024", "subject": "Annual General Meeting", "series": "EQ"},
        {"exDate": "14-Nov-2025", "subject": "Buy Back", "series": "EQ"},
        {"exDate": "10-Oct-2024", "subject": "Dividend - Rs 3 Per Share", "series": "BE"},
    ]
    actions, warnings = parse_actions(items)  # type: ignore[arg-type]
    splits = {a.ex_date: (a.numerator, a.denominator) for a in actions if a.kind == "split"}
    assert splits == {
        date(2024, 10, 28): (2, 1),  # bonus 1:1 = 2 shares for 1
        date(2020, 3, 3): (5, 2),  # bonus 3:2 = 5 for 2
        date(2022, 7, 28): (10, 1),  # FV 10 -> 1
        date(2011, 7, 14): (5, 1),  # FV 10 -> 2
        date(2021, 1, 5): (1, 10),  # consolidation 1 -> 10
    }
    divs = {a.ex_date: a.amount for a in actions if a.kind == "dividend"}
    assert divs == {date(2024, 5, 31): Decimal("28"), date(2009, 7, 6): Decimal("16")}
    assert len(warnings) == 1 and "Rights" in warnings[0].reason  # reported, not guessed
    assert warnings[0].session == date(2018, 1, 31)


# ----------------------------------------------------------------- fetching --


def test_fetch_many_across_the_format_change(tmp_path: Path) -> None:
    files = {
        LEGACY_DAY: legacy(
            LEGACY_DAY, [("TCS", "EQ", 3900.0, 100), ("RELIANCE", "EQ", 3100.0, 300)]
        ),
        UDIFF_DAY: udiff(UDIFF_DAY, [("TCS", "EQ", 3950.0, 200)]),  # RELIANCE missing that day
    }
    t, calls = transport(files)
    p = provider(t, tmp_path)
    now = NOW + timedelta(days=1)  # 2024-07-09 is also complete but not published
    out = p.fetch_many(
        [Ticker.parse("TCS.NS"), Ticker.parse("RELIANCE.NS")], LEGACY_DAY, date(2024, 7, 9), now
    )
    tcs, rel = out[Ticker.parse("TCS.NS")], out[Ticker.parse("RELIANCE.NS")]
    assert not isinstance(tcs, Exception) and not isinstance(rel, Exception)
    assert [(b.session, b.close) for b in tcs.bars] == [
        (LEGACY_DAY, Decimal("3900.0")),
        (UDIFF_DAY, Decimal("3950.0")),
    ]
    assert tcs.licensed and tcs.basis is PriceBasis.RAW and tcs.source == "nse_bhavcopy"
    assert [(a.kind, a.ex_date, a.amount) for a in tcs.actions] == [
        ("dividend", LEGACY_DAY, Decimal("10"))
    ]
    assert {d.reason for d in tcs.dropped} == {"bhavcopy not yet published"}
    assert [d.session for d in rel.dropped] == [UDIFF_DAY, date(2024, 7, 9)]
    # each day's file is fetched once for all stocks, then cached on disk
    assert sum("bhav" in c.lower() and "Actions" not in c for c in calls) == 3
    t2, calls2 = transport({})
    again = provider(t2, tmp_path).fetch_daily(Ticker.parse("TCS.NS"), LEGACY_DAY, UDIFF_DAY, now)
    assert [b.close for b in again.bars] == [b.close for b in tcs.bars]
    assert not any("bhav" in c.lower() and "Actions" not in c for c in calls2)


def test_unavailable_actions_fail_only_that_stock() -> None:
    files = {
        LEGACY_DAY: legacy(LEGACY_DAY, [("TCS", "EQ", 3900.0, 1), ("RELIANCE", "EQ", 3100.0, 1)])
    }
    t, _ = transport(files, fail_actions="RELIANCE")
    out = provider(t).fetch_many(
        [Ticker.parse("TCS.NS"), Ticker.parse("RELIANCE.NS")], LEGACY_DAY, LEGACY_DAY, NOW
    )
    assert isinstance(out[Ticker.parse("RELIANCE.NS")], ProviderUnavailableError)
    assert not isinstance(out[Ticker.parse("TCS.NS")], Exception)
    with pytest.raises(ProviderUnavailableError):
        provider(transport(files, fail_actions="RELIANCE")[0]).fetch_daily(
            Ticker.parse("RELIANCE.NS"), LEGACY_DAY, LEGACY_DAY, NOW
        )
    with pytest.raises(ProviderError, match="NSE listing"):
        provider(t).fetch_many([Ticker.parse("TCS.BO")], LEGACY_DAY, LEGACY_DAY, NOW)


# -------------------------------------------------------------- end to end --


def test_bonus_is_back_adjusted_and_the_gate_sees_licensed_data(db: Session) -> None:
    days = CAL.sessions(date(2024, 10, 21), date(2024, 10, 31))
    files = {}
    for d in days:
        close = 2700.0 if d < date(2024, 10, 28) else 1340.0  # 1:1 bonus on 28-Oct-2024
        files[d] = udiff(d, [("RELIANCE", "EQ", close, 1_000_000)])
    now = CAL.session_close_utc(days[-1]) + timedelta(hours=2)
    t, _ = transport(files)
    stock = md.add_stock(db, Ticker.parse("RELIANCE.NS"), None)
    res = md.ingest_from_provider(db, stock, provider(t), days[0], days[-1], now=now)
    assert res.run.status in ("succeeded", "succeeded_with_warnings"), res.run.validation_report
    assert res.run.licensed is True
    adj = md.get_series(db, stock, PriceBasis.SPLIT_ADJUSTED, days[0], days[-1], as_of=now)
    closes = [float(b.bar.close) for b in adj.bars]
    assert closes[0] == pytest.approx(1350.0) and closes[-1] == pytest.approx(1340.0)
    assert max(abs(b / a - 1) for a, b in itertools.pairwise(closes)) < 0.02
    # point in time: before the ex-date the bonus is not known, prices are as traded
    before = md.get_series(
        db,
        stock,
        PriceBasis.SPLIT_ADJUSTED,
        days[0],
        days[-1],
        as_of=CAL.session_close_utc(days[3]),
    )
    assert float(before.bars[0].bar.close) == pytest.approx(2700.0)
    assert load_stock(db, stock, now, None).basis == "total_return"  # NSE supplies dividends


def test_source_without_dividends_gives_no_total_return(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = get_config()
    prov = dict(cfg.market_data.providers)
    prov["nse_bhavcopy"] = prov["nse_bhavcopy"].model_copy(update={"supplies_dividends": False})
    patched = cfg.model_copy(
        update={"market_data": cfg.market_data.model_copy(update={"providers": prov})}
    )
    monkeypatch.setattr(md, "get_config", lambda: patched)
    days = CAL.sessions(date(2024, 10, 21), date(2024, 10, 25))
    files = {d: udiff(d, [("TCS", "EQ", 4000.0, 10)]) for d in days}
    t, _ = transport(files, actions={})
    stock = md.add_stock(db, Ticker.parse("TCS.NS"), None)
    now = CAL.session_close_utc(days[-1]) + timedelta(hours=2)
    md.ingest_from_provider(db, stock, provider(t), days[0], days[-1], now=now)
    s = load_stock(db, stock, now, None)
    assert s.basis == "split_adjusted" and len(s.close) == len(days)  # labelled honestly
    assert json.dumps(md.provider_statuses(patched)[1].__dict__)  # nse listed with the others


def test_bulk_ingest_runs_per_stock(db: Session) -> None:
    days = CAL.sessions(date(2024, 10, 21), date(2024, 10, 25))
    files = {d: udiff(d, [("TCS", "EQ", 4000.0, 10), ("RELIANCE", "EQ", 2700.0, 10)]) for d in days}
    t, calls = transport(files, fail_actions="RELIANCE")
    stocks = [md.add_stock(db, Ticker.parse(x), None) for x in ("TCS.NS", "RELIANCE.NS", "TCS.BO")]
    now = CAL.session_close_utc(days[-1]) + timedelta(hours=2)
    res = md.ingest_nse(db, stocks, days[0], days[-1], now=now, provider=provider(t))
    assert set(res) == {"TCS.NS", "RELIANCE.NS"}  # the BSE listing is not touched
    assert res["TCS.NS"].startswith("succeeded")  # (flat test prices trip the stale check)
    assert res["RELIANCE.NS"] == "failed"  # actions unavailable -> no unadjusted prices
    assert sum("BhavCopy" in c for c in calls) == len(days)  # one download per day, not per stock


def test_cli_module_entry_point_runs() -> None:
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "app.cli", "check-deploy"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
        check=False,
    )
    assert r.returncode == 1 and "FAIL AEGIS_ENV" in r.stdout, r.stderr[-500:]


def test_feeder_bundle_serves_an_offline_ingest(db: Session, tmp_path: Path) -> None:
    import tarfile

    days = CAL.sessions(date(2024, 10, 21), date(2024, 10, 31))
    files = {
        d: udiff(
            d,
            [
                ("RELIANCE", "EQ", 2700.0 if d < date(2024, 10, 28) else 1340.0, 1_000_000),
                ("TCS", "EQ", 4000.0, 10),
                ("OTHER", "EQ", 10.0, 1),
            ],
        )
        for d in days
    }
    now = CAL.session_close_utc(days[-1]) + timedelta(hours=2)
    # on the feeder machine (NSE reachable)
    t, _ = transport(files)
    feeder = provider(t, tmp_path / "mac-cache")
    feeder.prefetch(["RELIANCE", "TCS"], days[0], days[-1], now)
    info = feeder.write_bundle(tmp_path / "b.tar.gz", ["RELIANCE", "TCS"], days[0], days[-1], now)
    assert info == {"days": len(days), "action_files": 2, "symbols": 2}
    # on the deployment (NSE blocked): unpack, ingest offline, no network at all
    dest = tmp_path / "railway"
    with tarfile.open(tmp_path / "b.tar.gz") as tar:
        tar.extractall(dest, filter="data")
    day0 = json.loads((dest / f"{days[0]:%Y%m%d}.json").read_text())
    assert set(day0) == {"RELIANCE", "TCS"}  # filtered to the tracked stocks

    def no_network(req: httpx.Request) -> httpx.Response:
        raise AssertionError(f"offline provider contacted {req.url}")

    offline = NseBhavcopyProvider(
        SETTINGS,
        CAL,
        timedelta(minutes=60),
        cache_dir=dest,
        transport=httpx.MockTransport(no_network),
        offline=True,
    )
    stocks = [md.add_stock(db, Ticker.parse(x), None) for x in ("RELIANCE.NS", "TCS.NS", "INFY.NS")]
    res = md.ingest_nse(db, stocks, days[0], days[-1], now=now, provider=offline)
    assert res["RELIANCE.NS"].startswith("succeeded") and res["TCS.NS"].startswith("succeeded")
    assert res["INFY.NS"] == "failed"  # not in the bundle: no actions -> no unadjusted prices
    adj = md.get_series(db, stocks[0], PriceBasis.SPLIT_ADJUSTED, days[0], days[-1], as_of=now)
    assert float(adj.bars[0].bar.close) == pytest.approx(1350.0)  # bonus applied offline
    with pytest.raises(ProviderUnavailableError):
        offline.prefetch(["TCS"], days[0], days[-1], now)


def test_push_mode_skips_the_direct_download(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import settings as settings_mod
    from app.scheduler import celery_app

    pushed = settings_mod.get_settings().model_copy(update={"nse_feed": "push"})
    monkeypatch.setattr(settings_mod, "get_settings", lambda: pushed)
    out = celery_app.refresh_nse_eod()
    assert "skipped" in out and "feeder" in str(out["skipped"])
