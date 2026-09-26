"""Phase 12: daily ranking, no-trade analytics, counterfactuals and alerts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
import ta
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.alerts import service as alerts
from app.api.routes.stocks import get_now
from app.core.config_file import get_config
from app.main import app
from app.market_data import service as md
from app.market_data.types import Bar, PriceBasis, ProviderBatch, Ticker
from app.models import Alert, AnalysisReport, RankingRun, User
from app.orchestrator.service import _hash
from app.ranking import service as ranking
from tests.conftest import auth_header
from tests.market_helpers import NOW
from tests.test_paper import env  # noqa: F401  (shared paper-mode fixture)
from tests.test_risk_portfolio import CAL, CALM, MKT, SESSIONS, _seed_benchmark

CFG = get_config()
RULES = CFG.ranking


def _closes(rets: np.ndarray, start: float = 1000.0) -> list[Decimal]:
    c = start * np.cumprod(np.concatenate([[1.0], 1 + rets]))
    return [Decimal(f"{x:.2f}") for x in c]


def _bars(sessions: list[date], closes: list[Decimal]) -> list[Bar]:
    return [
        Bar(
            session=s,
            open=c,
            high=(c * Decimal("1.005")).quantize(Decimal("0.01")),
            low=(c * Decimal("0.995")).quantize(Decimal("0.01")),
            close=c,
            volume=2_000_000,
        )
        for s, c in zip(sessions, closes, strict=True)
    ]


def _seed_in_two_steps(db: Session, ticker: str, cut: int) -> tuple[list[date], list[Decimal]]:
    """Bars up to SESSIONS[cut] retrieved that evening, the rest retrieved at
    NOW: a ranking at the cut only sees what was known then."""
    closes = _closes(CALM)
    sessions = list(SESSIONS[-len(closes) :])
    stock = md.add_stock(db, Ticker.parse(ticker), None)
    k = sessions.index(SESSIONS[cut]) + 1
    for part, at in (
        (slice(0, k), CAL.session_close_utc(sessions[k - 1]) + timedelta(hours=2)),
        (slice(k, None), NOW - timedelta(minutes=5)),
    ):
        if not sessions[part]:
            continue
        batch = ProviderBatch(
            ticker=Ticker.parse(ticker),
            source="test",
            licensed=True,
            basis=PriceBasis.SPLIT_ADJUSTED,
            retrieved_at=at,
            bars=_bars(sessions[part], closes[part]),
        )
        md.ingest_batch(db, stock, batch, requested=(sessions[part][0], sessions[part][-1]), now=at)
    db.commit()
    return sessions, closes


# ------------------------------------------------------------ standardised candidate --


def test_standardised_levels_are_point_in_time_and_no_qualified_headline(
    db: Session,
) -> None:
    cut = -40
    sessions, closes = _seed_in_two_steps(db, "TCS.NS", cut)
    as_of = CAL.session_close_utc(SESSIONS[cut]) + timedelta(hours=3)
    run = ranking.run_ranking(db, as_of, None, refresh=False)

    row = run.rows[0]
    i = sessions.index(SESSIONS[cut])
    close = closes[i]  # the close known at as_of, not the latest one
    assert Decimal(str(row["entry"])) == close
    # ATR(14) from an independent implementation over the same 60-day window
    win = [j for j, d in enumerate(sessions[: i + 1]) if d >= SESSIONS[cut] - timedelta(days=60)]
    c = pd.Series([float(closes[j]) for j in win])
    atr = ta.volatility.AverageTrueRange(c * 1.005, c * 0.995, c, 14).average_true_range()
    dist = max(
        RULES.stop_atr_multiple * float(atr.iloc[-1]), RULES.min_stop_fraction * float(close)
    )
    assert row["stop"] == pytest.approx(float(close) - dist, abs=0.006)
    assert row["target"] == pytest.approx(
        float(close) + RULES.target_reward_multiple * dist, abs=0.006
    )
    assert row["quantity"] == 1  # no paper portfolio -> no equity to size from
    assert row["needs_live_quote"] is True

    # Research mode, no report, no model: nothing qualifies, and says so.
    assert run.qualified == 0 and run.evaluated == 1
    assert run.headline == ranking.NO_OPPORTUNITIES
    assert row["qualified"] is False and row["first_failure"] not in ranking.OPERATIONAL_GATES
    assert run.gate_failure_counts == {row["first_failure"]: 1}
    assert any(b.startswith("execution_mode") for b in run.operational_blockers)
    assert run.config_fingerprint == CFG.fingerprint()

    alert = db.scalars(select(Alert).where(Alert.kind == "ranking")).one()
    assert alert.title == ranking.NO_OPPORTUNITIES and alert.severity == "info"
    assert row["first_failure"] in alert.body

    with pytest.raises(DBAPIError):  # a ranking is an immutable record
        db.execute(text("UPDATE ranking_runs SET qualified = 5"))
        db.flush()
    db.rollback()


def test_insufficient_history_is_reported_not_guessed(db: Session) -> None:
    stock = md.add_stock(db, Ticker.parse("INFY.NS"), None)
    s = list(SESSIONS[-5:])
    batch = ProviderBatch(
        ticker=Ticker.parse("INFY.NS"),
        source="test",
        licensed=True,
        basis=PriceBasis.SPLIT_ADJUSTED,
        retrieved_at=NOW - timedelta(minutes=5),
        bars=_bars(s, [Decimal("1500.00")] * 5),
    )
    md.ingest_batch(db, stock, batch, requested=(s[0], s[-1]), now=NOW)
    db.commit()
    run = ranking.run_ranking(db, NOW, None, refresh=False)
    assert run.rows[0]["qualified"] is False and run.rows[0]["first_failure"] == "data"
    assert "entry" not in run.rows[0]  # no levels are invented
    assert run.headline == ranking.NO_OPPORTUNITIES


def test_operational_gates_are_separate_from_opportunity_gates(
    env: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    client, h = env["client"], env["h"]
    r = client.post("/ranking/run", headers=h, json={"refresh": False})
    assert r.status_code == 201, r.text
    run = r.json()
    row = run["rows"][0]
    assert row["qualified"] is True, row["failures"]
    assert run["qualified"] == 1 and run["headline"].startswith("1 QUALIFIED OPPORTUNITY")
    assert run["portfolio_id"] == env["pid"]
    # sized from the paper portfolio's risk budget, capped by order value
    eq = 1_000_000
    dist = row["entry"] - row["stop"]
    assert row["quantity"] == int(
        min(
            eq * CFG.position_sizing.risk_per_trade / dist,
            eq * CFG.trade_engine.max_order_value_fraction / row["entry"],
        )
    )
    # the spread needs a live quote at order time: not an opportunity failure
    assert run["operational_blockers"] == [] and row["needs_live_quote"] is True
    # A qualified ranking is only a record: no proposal, decision or order.
    for table in ("trade_proposals", "trade_decisions", "paper_orders"):
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0  # noqa: S608

    client.post("/trading/kill-switch", headers=h, json={"active": True, "reason": "halt all now"})
    halted = client.post("/ranking/run", headers=h, json={"refresh": False}).json()
    assert halted["rows"][0]["qualified"] is True  # still a good opportunity ...
    assert any(b.startswith("kill_switch") for b in halted["operational_blockers"])  # ... blocked

    latest = client.get("/ranking/latest", headers=h).json()
    assert latest["id"] == halted["id"]
    hist = client.get("/ranking/history", headers=h).json()
    assert [x["id"] for x in hist] == [halted["id"], run["id"]] and "rows" not in hist[0]


def test_counterfactuals_group_realised_forward_returns(db: Session) -> None:
    cut = -40
    _seed_benchmark(db, MKT)
    sessions, closes = _seed_in_two_steps(db, "TCS.NS", cut)
    as_of = CAL.session_close_utc(SESSIONS[cut]) + timedelta(hours=3)
    run = ranking.run_ranking(db, as_of, None, refresh=False)
    # a second ranking too recent to have a realised outcome yet
    ranking.run_ranking(db, NOW, None, refresh=False)

    cf = ranking.counterfactuals(db, NOW)
    assert cf["rankings"] == 2 and cf["pending"] == 1
    (g,) = cf["groups"]
    assert g["group"] == f"blocked:{run.rows[0]['first_failure']}" and g["n"] == 1

    i = sessions.index(SESSIONS[cut])
    entry, exit_ = closes[i + 1], closes[i + 1 + RULES.horizon]  # next session's close
    ret = float(exit_) / float(entry) - 1
    bench = 20000 * np.cumprod(np.concatenate([[1.0], 1 + MKT]))
    bsess = list(SESSIONS[-len(bench) :])
    be, bx = (bench[bsess.index(sessions[j])] for j in (i + 1, i + 1 + RULES.horizon))
    assert g["mean_forward_return"] == pytest.approx(ret)
    assert g["hit_rate"] == (1.0 if ret > 0 else 0.0)
    assert g["mean_excess_vs_nifty"] == pytest.approx(ret - (bx / be - 1))


# ------------------------------------------------------------------------ alerts --


class _Boom:
    name = "telegram"

    def send(self, title: str, body: str) -> None:
        raise ConnectionError("unreachable")


def test_alert_dedupe_and_severity_threshold(db: Session) -> None:
    sent: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        return httpx.Response(200, json={"ok": True})

    alerts.set_channels(
        [alerts.TelegramChannel("123:abc", "42", transport=httpx.MockTransport(handler))]
    )
    try:
        a = alerts.raise_alert(
            db, kind="t", severity="warning", title="Hello", body="World", dedupe_key="k1"
        )
        assert a is not None and a.deliveries == {"in_app": "stored", "telegram": "sent"}
        assert json.loads(sent[0].content) == {"chat_id": "42", "text": "Hello\n\nWorld"}
        assert sent[0].url.path == "/bot123:abc/sendMessage"
        dup = alerts.raise_alert(
            db, kind="t", severity="critical", title="Again", body="x", dedupe_key="k1"
        )
        assert dup is None and len(sent) == 1  # never stored or pushed twice
        quiet = alerts.raise_alert(
            db, kind="t", severity="info", title="FYI", body="x", dedupe_key="k2"
        )
        assert quiet is not None and quiet.deliveries == {"in_app": "stored"}  # below threshold
        with pytest.raises(ValueError):
            alerts.raise_alert(db, kind="t", severity="bad", title="x", body="x", dedupe_key="k3")
        db.commit()
        assert db.query(Alert).count() == 2
    finally:
        alerts.set_channels(None)


def test_channel_failure_still_stores_the_alert(db: Session) -> None:
    def fail(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"ok": False})

    tg = alerts.TelegramChannel("123:secret-token", "42", transport=httpx.MockTransport(fail))
    alerts.set_channels([tg, _Boom()])
    try:
        a = alerts.raise_alert(
            db, kind="t", severity="critical", title="Stop", body="hit", dedupe_key="fail-1"
        )
        db.commit()
    finally:
        alerts.set_channels(None)
    assert a is not None
    stored = db.get(Alert, a.id)
    assert stored is not None
    assert stored.deliveries["in_app"] == "stored"
    assert stored.deliveries["telegram"] == "failed: ConnectionError"  # last one wins per name
    assert "secret-token" not in json.dumps(stored.deliveries)


def test_ingestion_failures_raise_one_alert_per_job_per_day(db: Session) -> None:
    ok = {"TCS.NS": "succeeded", "INFY.NS": "succeeded_with_warnings"}
    assert alerts.alert_ingestion_failures(db, "EOD prices", ok, date(2026, 9, 25)) is None
    bad = {**ok, "HDFCBANK.NS": "error: ReadTimeout", "WIPRO.NS": "failed"}
    a = alerts.alert_ingestion_failures(db, "EOD prices", bad, date(2026, 9, 25))
    assert a is not None and a.severity == "warning" and "2 of 4" in a.title
    assert "HDFCBANK.NS: error: ReadTimeout" in a.body and "TCS.NS" not in a.body
    assert alerts.alert_ingestion_failures(db, "EOD prices", bad, date(2026, 9, 25)) is None
    assert alerts.alert_ingestion_failures(db, "EOD prices", bad, date(2026, 9, 28)) is not None


def test_kill_switch_changes_alert_and_alerts_can_be_read(
    client: TestClient, admin: User, analyst: User
) -> None:
    app.dependency_overrides[get_now] = lambda: NOW
    try:
        h = auth_header(client, admin.email)
        ha = auth_header(client, analyst.email)
        client.post(
            "/trading/kill-switch", headers=ha, json={"active": True, "reason": "odd fills"}
        )
        client.post("/trading/kill-switch", headers=h, json={"active": False, "reason": "reviewed"})
        r = client.get("/alerts", headers=ha).json()
        assert r["unread"] == 2
        resume, halt = r["alerts"]
        assert halt["severity"] == "critical" and "odd fills" in halt["body"]
        assert resume["severity"] == "warning" and "live trading remains disabled" in resume["body"]
        read = client.post(f"/alerts/{halt['id']}/read", headers=ha).json()
        assert read["read_at"] is not None
        assert client.get("/alerts?unread_only=true", headers=ha).json()["unread"] == 1
        assert client.post("/alerts/read-all", headers=ha).json() == {"marked": 1}
        assert client.get("/alerts", headers=ha).json()["unread"] == 0
        assert client.post("/alerts/999999/read", headers=ha).status_code == 404
        ch = client.get("/alerts/channels", headers=ha).json()
        assert ch["in_app"]["available"] is True and ch["telegram"]["available"] is False
        assert "disabled" in ch["telegram"]["reason"]
    finally:
        app.dependency_overrides.clear()


# -------------------------------------------------------------------------- auth --


def test_ranking_and_alert_endpoints_need_auth(
    client: TestClient, analyst: User, db: Session
) -> None:
    for method, path in (
        ("post", "/ranking/run"),
        ("get", "/ranking/latest"),
        ("get", "/ranking/history"),
        ("get", "/ranking/counterfactuals"),
        ("get", "/alerts"),
        ("post", "/alerts/1/read"),
        ("post", "/alerts/read-all"),
        ("get", "/alerts/channels"),
    ):
        assert getattr(client, method)(path).status_code == 401, path
    ha = auth_header(client, analyst.email)
    assert client.post("/ranking/run", headers=ha, json={}).status_code == 403  # admin only
    assert client.get("/ranking/latest", headers=ha).status_code == 404
    assert db.scalar(select(RankingRun)) is None


def test_refreshed_reports_are_visible_to_the_evaluation(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_in_two_steps(db, "TCS.NS", -1)
    stock = md.get_stock(db, Ticker.parse("TCS.NS"))
    made = NOW + timedelta(minutes=10)
    calls: list[tuple[str, Any]] = []

    def fake_analysis(db_: Session, ticker: Ticker, as_of: Any, user: Any) -> None:
        calls.append((str(ticker), as_of))
        rep = {"synthesis": {"stance": "NO_CLEAR_TILT", "conflicts": [], "invalidation": []}}
        db_.add(
            AnalysisReport(
                stock_id=stock.id,
                as_of=as_of,
                knowledge_at=made,
                created_at=made,
                stance="NO_CLEAR_TILT",
                composite_score=50,
                confidence=0.4,
                agent_run_ids={},
                report=rep,
                report_hash=_hash(rep),
                config_fingerprint=CFG.fingerprint(),
            )
        )
        db_.commit()

    monkeypatch.setattr(ranking.orch, "run_analysis", fake_analysis)
    run = ranking.run_ranking(
        db, NOW, None, refresh=True, clock=lambda: made + timedelta(seconds=1)
    )
    assert calls == [("TCS.NS", NOW)]  # stale (missing) report refreshed at as_of
    # evaluated after the refresh, so the new report is visible to the gates
    assert run.as_of == made + timedelta(seconds=1)
    assert run.rows[0]["stance"] == "NO_CLEAR_TILT" and run.rows[0]["report_id"] is not None
    assert run.rows[0]["first_failure"] != "research_report"
    again = ranking.run_ranking(db, made + timedelta(minutes=1), None, refresh=True)
    assert len(calls) == 1 and again.as_of == made + timedelta(minutes=1)  # fresh: no refresh
