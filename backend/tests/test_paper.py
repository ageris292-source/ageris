"""Phase 11: paper trading — human approval, pre-order re-check,
idempotency, fills, positions, P&L, theses and monitoring."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_now
from app.core.config_file import get_config
from app.core.modes import SystemMode
from app.core.settings import get_settings
from app.main import app
from app.market_data import service as md
from app.market_data.types import Bar, PriceBasis, ProviderBatch, Ticker
from app.models import AnalysisReport, PaperExecution, PortfolioSnapshot, User
from app.orchestrator.service import _hash
from app.trade import context as trade_context
from app.trade import probability
from tests.conftest import auth_header
from tests.market_helpers import NOW
from tests.test_risk_portfolio import CAL, CALM, LAST, MKT, _seed_benchmark, _seed_stock
from tests.test_trade_engine import PROB

CFG = get_config()


@pytest.fixture
def env(
    client: TestClient, admin: User, db: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    stock = md.get_stock(db, Ticker.parse("TCS.NS"))
    paper = get_settings().model_copy(update={"system_mode": SystemMode.PAPER})
    monkeypatch.setattr(trade_context, "get_settings", lambda: paper)
    client.post("/trading/kill-switch", headers=h, json={"active": False, "reason": "test resume"})
    rep = {
        "synthesis": {
            "stance": "POSITIVE_TILT",
            "conflicts": [],
            "invalidation": [
                {"agent": "technical", "condition": "Close below the 200-day average"}
            ],
        }
    }
    db.add(
        AnalysisReport(
            stock_id=stock.id,
            as_of=NOW - timedelta(hours=1),
            knowledge_at=NOW - timedelta(hours=1),
            created_at=NOW - timedelta(hours=1),
            stance="POSITIVE_TILT",
            composite_score=70,
            confidence=0.5,
            agent_run_ids={},
            report=rep,
            report_hash=_hash(rep),
            config_fingerprint=CFG.fingerprint(),
        )
    )
    db.commit()
    probability.set_source(lambda _db, _s, _a, hz: dataclasses.replace(PROB, horizon_days=hz))
    pid = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "1000000"}
    ).json()["id"]
    close = Decimal(client.get("/stocks/TCS.NS", headers=h).json()["latest_bar"]["close"])
    yield {"client": client, "h": h, "pid": pid, "close": close, "stock": stock}
    app.dependency_overrides.clear()
    probability.set_source(None)


def _propose(e: dict[str, Any], **kw: Any) -> dict[str, Any]:
    c = e["close"]
    body = {
        "ticker": "TCS.NS",
        "side": "buy",
        "quantity": 20,
        "entry_price": str((c * Decimal("1.004")).quantize(Decimal("0.01"))),
        "stop_loss": str((c * Decimal("0.95")).quantize(Decimal("0.01"))),
        "target": str((c * Decimal("1.15")).quantize(Decimal("0.01"))),
        "horizon_days": 20,
        "portfolio_id": e["pid"],
        "mode": "paper",
        "quoted_spread_bps": 4,
        **kw,
    }
    r = e["client"].post("/trade/proposals", headers=e["h"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _order(e: dict[str, Any], decision_id: int, key: str, h: dict[str, str] | None = None) -> Any:
    return e["client"].post(
        "/paper/orders",
        headers={**(h or e["h"]), "Idempotency-Key": key},
        json={"decision_id": decision_id},
    )


def test_buy_is_approved_rechecked_filled_and_idempotent(
    env: dict[str, Any], db: Session, analyst: User
) -> None:
    client, h = env["client"], env["h"]
    d = _propose(env)
    assert d["decision"] == "APPROVED", d["failed_gates"]
    no_key = client.post("/paper/orders", headers=h, json={"decision_id": d["decision_id"]})
    assert no_key.status_code == 422
    assert _order(env, d["decision_id"], "bad key!").status_code == 422
    assert (
        _order(
            env, d["decision_id"], "analyst-key-1", auth_header(client, analyst.email)
        ).status_code
        == 403
    )  # human approver role
    r = _order(env, d["decision_id"], "order-key-0001")
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["status"] == "FILLED" and o["recheck_decision_id"] not in (None, d["decision_id"])

    ex = db.scalars(select(PaperExecution)).one()
    assert ex.fill_price >= ex.reference_price  # never better than the reference for a buy
    assert ex.fill_price <= Decimal(d["proposal"]["entry_price"])  # within the limit
    assert ex.notional == (ex.fill_price * 20).quantize(Decimal("0.01"))
    fees = sum(Decimal(v) for v in ex.fee_breakdown.values())
    assert fees == ex.fees and Decimal(ex.fee_breakdown["stamp_duty"]) > 0
    pf = client.get(f"/paper/portfolios/{env['pid']}", headers=h).json()
    assert Decimal(pf["analysis"]["metrics"]["cash"]).quantize(Decimal("0.01")) == (
        Decimal("1000000") - ex.notional - ex.fees
    )
    hold = pf["analysis"]["holdings"][0]
    assert hold["quantity"] == 20 and Decimal(str(hold["avg_cost"])) == ex.fill_price
    th = pf["theses"][0]
    assert th["status"] == "OPEN" and th["invalidation"] == [
        "(technical) Close below the 200-day average"
    ]
    assert db.query(PortfolioSnapshot).filter_by(source="execution").count() == 1

    replay = _order(env, d["decision_id"], "order-key-0001")
    assert (
        replay.status_code == 200 and replay.json()["replayed"] and replay.json()["id"] == o["id"]
    )
    assert db.query(PaperExecution).count() == 1  # no double fill
    recheck = _order(env, o["recheck_decision_id"], "order-key-0003")
    assert recheck.status_code == 409 and "re-check" in recheck.json()["detail"]
    again = _order(env, d["decision_id"], "order-key-0002")
    assert again.status_code == 409 and "already executed" in again.json()["detail"]
    d2 = _propose(env, quantity=5)
    clash = _order(env, d2["decision_id"], "order-key-0001")
    assert clash.status_code == 409 and "idempotency" in clash.json()["detail"]
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE paper_executions SET fill_price = 1"))
        db.flush()
    db.rollback()


def test_pre_order_recheck_blocks_when_conditions_change(env: dict[str, Any], db: Session) -> None:
    client, h = env["client"], env["h"]
    d = _propose(env)
    assert d["decision"] == "APPROVED"
    client.post("/trading/kill-switch", headers=h, json={"active": True, "reason": "halt all now"})
    o = _order(env, d["decision_id"], "recheck-key-01").json()
    assert o["status"] == "REJECTED" and "kill_switch" in o["reason"]
    assert db.query(PaperExecution).count() == 0
    assert (
        client.get(f"/paper/portfolios/{env['pid']}", headers=h).json()["analysis"]["holdings"]
        == []
    )


def test_stale_or_rejected_decisions_cannot_be_ordered(env: dict[str, Any]) -> None:
    rejected = _propose(env, quoted_spread_bps=None)  # spread unknown -> REJECTED
    assert rejected["decision"] == "REJECTED"
    r = _order(env, rejected["decision_id"], "rejected-key-1")
    assert r.status_code == 409 and "REJECTED" in r.json()["detail"]
    d = _propose(env)
    app.dependency_overrides[get_now] = lambda: NOW + timedelta(hours=2)
    stale = _order(env, d["decision_id"], "stale-key-0001")
    assert stale.status_code == 409 and "old" in stale.json()["detail"]
    assert _order(env, 999999, "missing-key-01").status_code == 404


def test_exit_realises_pnl_and_closes_the_thesis(env: dict[str, Any], db: Session) -> None:
    client, h = env["client"], env["h"]
    buy = _propose(env)
    _order(env, buy["decision_id"], "buy-key-00001")
    sell = _propose(
        env,
        side="sell",
        stop_loss=None,
        target=None,
        entry_price=str((env["close"] * Decimal("0.996")).quantize(Decimal("0.01"))),
    )
    assert sell["decision"] == "APPROVED", sell["failed_gates"]
    na = {g["name"] for g in sell["gates"] if g["status"] == "NOT_APPLICABLE"}
    assert "probability_of_profit" in na
    o = _order(env, sell["decision_id"], "sell-key-0001").json()
    assert o["status"] == "FILLED", o["reason"]
    b, s = db.scalars(select(PaperExecution).order_by(PaperExecution.id)).all()
    assert s.fill_price <= s.reference_price  # adverse for a sell
    assert s.realised_pnl == ((s.fill_price - b.fill_price) * 20 - s.fees).quantize(Decimal("0.01"))
    pf = client.get(f"/paper/portfolios/{env['pid']}", headers=h).json()
    assert pf["analysis"]["holdings"] == [] and pf["theses"][0]["status"] == "CLOSED"
    assert Decimal(pf["analysis"]["metrics"]["cash"]).quantize(Decimal("0.01")) == s.cash_after
    assert Decimal(pf["realised_pnl"]) == s.realised_pnl
    oversell = _propose(env, side="sell", stop_loss=None, target=None)
    assert oversell["decision"] == "REJECTED" and oversell["first_failure"] == "instrument"


def test_monitor_flags_stop_and_suggests_an_exit(env: dict[str, Any], db: Session) -> None:
    client, h = env["client"], env["h"]
    d = _propose(env)
    _order(env, d["decision_id"], "mon-key-00001")
    # next session: the stock gaps 10% down, below the 5% stop
    nxt = CAL.sessions(LAST + timedelta(days=1), LAST + timedelta(days=10))[0]
    later = CAL.session_close_utc(nxt) + timedelta(hours=3)
    px = (env["close"] * Decimal("0.90")).quantize(Decimal("0.01"))
    batch = ProviderBatch(
        ticker=Ticker.parse("TCS.NS"),
        source="test",
        licensed=True,
        basis=PriceBasis.SPLIT_ADJUSTED,
        retrieved_at=later,
        bars=[Bar(session=nxt, open=px, high=px, low=px, close=px, volume=2_000_000)],
    )
    md.ingest_batch(db, env["stock"], batch, requested=(nxt, nxt), now=later)
    db.commit()
    app.dependency_overrides[get_now] = lambda: later
    ev = client.post("/paper/monitor", headers=h).json()["events"]
    kinds = {e["kind"] for e in ev}
    assert "STOP_HIT" in kinds
    stop = next(e for e in ev if e["kind"] == "STOP_HIT")
    assert stop["exit_proposal_id"] is not None and stop["exit_decision"] in (
        "APPROVED",
        "REJECTED",
    )
    assert client.post("/paper/monitor", headers=h).json()["events"] == []  # once per session
    th = client.get(f"/paper/portfolios/{env['pid']}", headers=h).json()["theses"][0]
    assert th["events"][0]["kind"] == "STOP_HIT" and th["status"] == "OPEN"  # human decides
    stop_alert = next(
        a
        for a in client.get("/alerts", headers=h).json()["alerts"]
        if a["kind"] == "thesis.stop_hit"
    )
    assert stop_alert["severity"] == "critical" and "human must still approve" in stop_alert["body"]
    kinds_alerted = [a["kind"] for a in client.get("/alerts", headers=h).json()["alerts"]]
    assert kinds_alerted.count("thesis.stop_hit") == 1  # no duplicate on the second check


def test_paper_endpoints_need_auth(client: TestClient) -> None:
    assert client.post("/paper/orders", json={"decision_id": 1}).status_code == 401
    assert client.get("/paper/orders").status_code == 401
    assert client.get("/paper/portfolios/1").status_code == 401
    assert client.post("/paper/monitor").status_code == 401
