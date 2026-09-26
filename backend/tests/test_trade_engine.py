"""Phase 9: the Trade Risk Engine — 24 ordered gates, costs, sizing (spec §17-§20, §72)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_now
from app.core.config_file import get_config
from app.core.modes import SystemMode
from app.core.settings import get_settings
from app.main import app
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import AnalysisReport, TradeDecisionRecord, User
from app.orchestrator.service import _hash
from app.trade import context as trade_context
from app.trade import probability
from app.trade.costs import CostError, round_trip
from app.trade.gates import GATES, GateContext, evaluate, self_test
from app.trade.probability import ProbabilityEstimate
from app.trade.schemas import TradeProposal
from tests.conftest import auth_header
from tests.market_helpers import NOW
from tests.test_risk_portfolio import CALM, MKT, _seed_benchmark, _seed_stock

CFG = get_config()
T = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
PROB = ProbabilityEstimate(
    model_id="wf-test",
    horizon_days=20,
    as_of_date=date(2026, 9, 25),
    p_profit=0.70,
    p_outperform=0.68,
    expected_return=0.12,
    calibrated=True,
    calibration_error=0.02,
    oos_periods=6,
)
P = TradeProposal(
    ticker="TCS.NS",
    side="buy",
    quantity=10,
    entry_price=Decimal("1000"),
    stop_loss=Decimal("950"),
    target=Decimal("1150"),
    horizon_days=20,
    portfolio_id=1,
    mode="paper",
    quoted_spread_bps=5,
)
C = GateContext(
    as_of=T,
    system_mode="paper",
    live_trading_enabled=False,
    broker_healthy=None,
    kill_switch_active=False,
    kill_switch_known=True,
    stock_found=True,
    exchange="NSE",
    currency="INR",
    stock_active=True,
    delisted=False,
    portfolio_kind="paper",
    equity=1_000_000.0,
    cash=1_000_000.0,
    held_quantity=0,
    limits_status_after="PASS",
    loss_daily=0.0,
    loss_weekly=0.0,
    drawdown=0.0,
    reference_price=1000.0,
    price_date="2026-09-25",
    price_licensed=True,
    price_source="csv_import",
    fresh=True,
    freshness_reason="fresh",
    data_quality=1.0,
    adtv=1e9,
    volatility=0.2,
    report_id=1,
    report_hash_ok=True,
    report_age_hours=1.0,
    report_stance="POSITIVE_TILT",
    report_conflicts=0,
    probability=PROB,
)


def ev(p: TradeProposal = P, c: GateContext = C, cfg: Any = CFG) -> Any:
    return evaluate(p, c, cfg, T)


def tweak(cfg: Any, section: str, **kw: Any) -> Any:
    return cfg.model_copy(update={section: getattr(cfg, section).model_copy(update=kw)})


def cx(**kw: Any) -> GateContext:
    return dataclasses.replace(C, **kw)


def px(**kw: Any) -> TradeProposal:
    return P.model_copy(update=kw)


# ----------------------------------------------------------------- baseline --


def test_everything_satisfied_is_approved() -> None:
    d = ev()
    assert [g.name for g in d.gates] == [g[0] for g in GATES] and len(d.gates) == 24
    assert all(g.status == "PASS" for g in d.gates), [
        (g.name, g.reason) for g in d.gates if g.status != "PASS"
    ]
    assert d.decision == "APPROVED" and d.first_failure is None
    assert d.requires_human_approval
    assert d.metrics["expected_net_return"] == pytest.approx(0.12 - d.costs.round_trip_fraction)
    assert ev().decision_hash == d.decision_hash  # deterministic


REJECTIONS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("kill_switch", {"kill_switch_active": True}, {}),
    ("kill_switch", {"kill_switch_known": False}, {}),
    ("execution_mode", {"system_mode": "research"}, {}),
    ("execution_mode", {}, {"mode": "live"}),
    ("portfolio_match", {"portfolio_kind": "model"}, {}),
    ("instrument", {"stock_active": False}, {}),
    ("instrument", {"exchange": "NASDAQ"}, {}),
    ("data_licensed", {"price_licensed": False}, {}),
    ("data_freshness", {"fresh": False}, {}),
    ("data_freshness", {"fresh": None}, {}),
    ("data_quality", {"data_quality": 0.85}, {}),
    ("entry_deviation", {}, {"entry_price": Decimal("1010")}),
    ("entry_deviation", {"reference_price": None}, {}),
    ("research_report", {"report_id": None}, {}),
    ("research_report", {"report_age_hours": 30.0}, {}),
    ("research_report", {"report_hash_ok": False}, {}),
    ("research_stance", {"report_stance": "NO_CLEAR_TILT"}, {}),
    ("agent_conflicts", {"report_conflicts": 1}, {}),
    ("model_calibration", {"probability": None}, {}),
    ("model_calibration", {"probability": dataclasses.replace(PROB, calibrated=False)}, {}),
    ("model_calibration", {"probability": dataclasses.replace(PROB, calibration_error=0.09)}, {}),
    ("model_calibration", {}, {"horizon_days": 30}),  # estimate is for another horizon
    ("out_of_sample", {"probability": dataclasses.replace(PROB, oos_periods=2)}, {}),
    ("probability_of_profit", {"probability": dataclasses.replace(PROB, p_profit=0.6)}, {}),
    ("expected_net_return", {"probability": dataclasses.replace(PROB, expected_return=0.04)}, {}),
    ("trade_plan", {}, {"stop_loss": None}),
    ("trade_plan", {}, {"target": Decimal("990")}),
    ("reward_risk", {}, {"target": Decimal("1080")}),
    ("liquidity", {"adtv": 1e7}, {}),
    ("participation", {"adtv": 6e7}, {"quantity": 700}),
    ("spread", {}, {"quoted_spread_bps": None}),
    ("spread", {}, {"quoted_spread_bps": 40.0}),
    ("position_sizing", {}, {"quantity": 150}),
    ("position_sizing", {"equity": None}, {}),
    ("portfolio_limits", {"limits_status_after": "FAIL", "limit_failures_after": ["x"]}, {}),
    ("portfolio_limits", {"limits_status_after": "UNKNOWN"}, {}),
    ("portfolio_limits", {"limits_status_after": None}, {}),
    ("loss_limits", {"loss_daily": -0.025}, {}),
    ("loss_limits", {"loss_weekly": -0.06}, {}),
    ("loss_limits", {"drawdown": 0.2}, {}),
    ("loss_limits", {"loss_daily": None}, {}),
]


@pytest.mark.parametrize(("gate", "ctx", "prop"), REJECTIONS)
def test_each_gate_rejects(gate: str, ctx: dict[str, Any], prop: dict[str, Any]) -> None:
    d = ev(px(**prop), cx(**ctx))
    assert d.decision == "REJECTED"
    assert d.first_failure == gate, [(g.name, g.status, g.reason) for g in d.gates]


def test_every_gate_is_covered_by_a_rejection_case() -> None:
    covered = {g for g, _, _ in REJECTIONS} | {"edge_vs_benchmark"}
    assert covered == {g[0] for g in GATES}


def test_edge_gate_uses_the_benchmark() -> None:
    cfg = tweak(CFG, "trade_engine", benchmark_expected_annual_return=0.49)  # absurd benchmark
    long = px(horizon_days=200)
    d = ev(long, cx(probability=dataclasses.replace(PROB, horizon_days=200)), cfg)
    assert d.first_failure == "edge_vs_benchmark"


# -------------------------------------------------------------------- exits --


def test_exits_skip_entry_gates_but_not_safety_gates() -> None:
    sell = px(side="sell", stop_loss=None, target=None)
    held = cx(held_quantity=10, probability=None, report_id=None, report_stance=None)
    d = ev(sell, held)
    assert d.decision == "APPROVED", [(g.name, g.reason) for g in d.gates if g.status != "PASS"]
    na = [g.name for g in d.gates if g.status == "NOT_APPLICABLE"]
    assert "probability_of_profit" in na and "research_stance" in na and "kill_switch" not in na
    assert ev(sell, dataclasses.replace(held, held_quantity=5)).first_failure == "instrument"
    assert ev(sell, dataclasses.replace(held, kill_switch_active=True)).decision == "REJECTED"
    assert ev(sell, dataclasses.replace(held, price_licensed=False)).decision == "REJECTED"


# ------------------------------------------------------------------- costs --


def test_round_trip_costs_hand_worked() -> None:
    s = CFG.transaction_costs["NSE_EQ_DELIVERY"]
    c = round_trip("NSE_EQ_DELIVERY", s, 1_000_000, 1e9, 30)  # 0.1% of ADTV
    fees = s.brokerage_bps + s.exchange_fee_bps + s.regulatory_fee_bps
    common = fees * (1 + s.gst_rate_on_fees) + s.securities_tax_bps + s.slippage_bps
    common += s.half_spread_bps + s.market_impact_bps_per_pct_adv * 0.1
    assert c.sell_bps == pytest.approx(common, abs=1e-3)
    assert c.buy_bps - c.sell_bps == pytest.approx(s.stamp_duty_buy_bps)
    assert c.round_trip_fraction == pytest.approx(
        (2 * common + s.stamp_duty_buy_bps) / 1e4, abs=1e-6
    )
    with pytest.raises(CostError):
        round_trip("x", s, 1000, None, 5)


@settings(max_examples=100, deadline=None)
@given(v=st.floats(1e3, 1e8), adtv=st.floats(1e6, 1e11), extra=st.floats(1.01, 10))
def test_costs_positive_and_increase_with_size(v: float, adtv: float, extra: float) -> None:
    s = CFG.transaction_costs["NSE_EQ_DELIVERY"]
    a = round_trip("s", s, v, adtv, 20)
    b = round_trip("s", s, v * extra, adtv, 20)
    assert 0 < a.round_trip_fraction < b.round_trip_fraction
    assert a.buy_bps > a.sell_bps > 0


# ---------------------------------------------------- properties (spec §72) --

ctx_mutations = st.fixed_dictionaries(
    {},
    optional={
        "kill_switch_active": st.booleans(),
        "kill_switch_known": st.booleans(),
        "system_mode": st.sampled_from(["research", "paper", "live"]),
        "price_licensed": st.one_of(st.none(), st.booleans()),
        "fresh": st.one_of(st.none(), st.booleans()),
        "data_quality": st.one_of(st.none(), st.floats(0, 1)),
        "reference_price": st.one_of(st.none(), st.floats(900, 1100)),
        "report_age_hours": st.one_of(st.none(), st.floats(-5, 60)),
        "report_stance": st.sampled_from(["POSITIVE_TILT", "NO_CLEAR_TILT", "INSUFFICIENT_DATA"]),
        "report_conflicts": st.integers(0, 3),
        "adtv": st.one_of(st.none(), st.floats(1e5, 1e11)),
        "equity": st.one_of(st.none(), st.floats(1e4, 1e8)),
        "limits_status_after": st.sampled_from(["PASS", "FAIL", "UNKNOWN", None]),
        "loss_daily": st.one_of(st.none(), st.floats(-0.1, 0.1)),
        "drawdown": st.one_of(st.none(), st.floats(0, 0.5)),
        "probability": st.one_of(
            st.none(),
            st.builds(
                ProbabilityEstimate,
                model_id=st.just("m"),
                horizon_days=st.sampled_from([20, 30]),
                as_of_date=st.just(date(2026, 9, 25)),
                p_profit=st.floats(0, 1),
                p_outperform=st.floats(0, 1),
                expected_return=st.floats(-0.3, 0.5),
                calibrated=st.booleans(),
                calibration_error=st.floats(0, 0.3),
                oos_periods=st.integers(0, 12),
            ),
        ),
    },
)
prop_mutations = st.fixed_dictionaries(
    {},
    optional={
        "side": st.sampled_from(["buy", "sell"]),
        "quantity": st.integers(1, 5000),
        "entry_price": st.decimals(900, 1100, places=2),
        "stop_loss": st.one_of(st.none(), st.decimals(800, 1050, places=2)),
        "target": st.one_of(st.none(), st.decimals(950, 1500, places=2)),
        "quoted_spread_bps": st.one_of(st.none(), st.floats(0, 60)),
        "mode": st.sampled_from(["paper", "live"]),
    },
)


@settings(max_examples=400, deadline=None)
@given(cm=ctx_mutations, pm=prop_mutations)
def test_approval_iff_every_applicable_gate_passes(cm: dict[str, Any], pm: dict[str, Any]) -> None:
    p, c = px(**pm), cx(**cm)
    d = ev(p, c)
    applicable = [g for g in d.gates if g.status != "NOT_APPLICABLE"]
    assert (d.decision == "APPROVED") == all(g.status == "PASS" for g in applicable)
    assert len(d.gates) == 24 and [g.order for g in d.gates] == list(range(1, 25))
    if d.decision == "APPROVED":
        # the safety invariants hold for every approved trade
        assert not c.kill_switch_active and c.kill_switch_known and c.price_licensed
        assert c.system_mode == "paper" and p.mode == "paper"
        if p.side == "buy":
            assert p.stop_loss is not None and c.equity is not None
            risk = p.quantity * float(p.entry_price - p.stop_loss)
            assert risk <= c.equity * CFG.position_sizing.risk_per_trade + 1e-6
            assert c.probability is not None and c.probability.calibrated
            assert c.probability.p_profit >= CFG.trade_gates.minimum_probability_of_profit
            assert d.metrics["expected_net_return"] >= CFG.trade_gates.minimum_expected_net_return
    assert ev(p, c).decision_hash == d.decision_hash


@settings(max_examples=200, deadline=None)
@given(
    cm=ctx_mutations,
    pm=prop_mutations,
    bump=st.sampled_from(
        [
            ("trade_gates", "minimum_probability_of_profit", 0.1),
            ("trade_gates", "minimum_expected_net_return", 0.05),
            ("trade_gates", "minimum_reward_risk_ratio", 1.0),
            ("liquidity", "minimum_average_daily_traded_value", 1e8),
            ("trade_gates", "minimum_data_quality_score", 0.05),
        ]
    ),
)
def test_tightening_a_threshold_never_approves_more(
    cm: dict[str, Any], pm: dict[str, Any], bump: tuple[str, str, float]
) -> None:
    section, field, delta = bump
    cap = 1.0 if ("probability" in field or "quality" in field) else 1e12
    strict = tweak(CFG, section, **{field: min(getattr(getattr(CFG, section), field) + delta, cap)})
    p, c = px(**pm), cx(**cm)
    if ev(p, c).decision == "REJECTED":
        assert ev(p, c, strict).decision == "REJECTED"


@settings(max_examples=100, deadline=None)
@given(pm=prop_mutations)
def test_kill_switch_blocks_everything(pm: dict[str, Any]) -> None:
    d = ev(px(**pm), cx(kill_switch_active=True, held_quantity=10_000))
    assert d.decision == "REJECTED" and d.first_failure == "kill_switch"


def test_self_test() -> None:
    ok, msg = self_test(CFG)
    assert ok, msg


# -------------------------------------------------------------- end to end --


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()
    probability.set_source(None)


def _paper_portfolio(client: TestClient, h: dict[str, str]) -> int:
    r = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "1000000"}
    )
    return int(r.json()["id"])


def test_research_mode_rejects_and_records(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    pid = _paper_portfolio(client, h)
    body = {**P.model_dump(mode="json"), "portfolio_id": pid}
    r = client.post("/trade/proposals", headers=h, json=body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["decision"] == "REJECTED" and d["first_failure"] == "kill_switch"
    assert "execution_mode" in d["failed_gates"]  # research mode
    assert "model_calibration" in d["failed_gates"]  # no model registered
    got = client.get(f"/trade/decisions/{d['decision_id']}", headers=h).json()
    assert got["hash_verified"] and got["decision_hash"] == d["decision_hash"]
    lst = client.get("/trade/proposals", headers=h, params={"portfolio_id": pid}).json()
    assert lst[0]["proposal_id"] == d["proposal_id"] and lst[0]["decision"] == "REJECTED"
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE trade_decisions SET decision = 'APPROVED'"))
        db.flush()
    db.rollback()
    assert db.query(TradeDecisionRecord).one().decision == "REJECTED"
    future = {**body, "as_of": (NOW + timedelta(days=1)).isoformat()}
    assert client.post("/trade/proposals", headers=h, json=future).status_code == 422
    assert client.post("/trade/proposals", headers=h, json={**body, "rogue": 1}).status_code == 422


def test_full_pipeline_can_approve_in_paper_mode(
    api: tuple[TestClient, dict[str, str]], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every gate satisfied from REAL database state: licensed fresh prices,
    a recent POSITIVE_TILT report, a calibrated model estimate, paper mode,
    kill switch released by an admin, a paper portfolio with room."""
    client, h = api
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    stock = md.get_stock(db, Ticker.parse("TCS.NS"))
    paper = get_settings().model_copy(update={"system_mode": SystemMode.PAPER})
    monkeypatch.setattr(trade_context, "get_settings", lambda: paper)
    assert (
        client.post(
            "/trading/kill-switch", headers=h, json={"active": False, "reason": "test resume"}
        ).status_code
        == 200
    )
    body: dict[str, Any] = {"ticker": "TCS.NS", "stock_id": stock.id}
    rep = {"synthesis": {"stance": "POSITIVE_TILT", "conflicts": []}, **body}
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
    probability.set_source(lambda _db, s, _a, hz: dataclasses.replace(PROB, horizon_days=hz))
    pid = _paper_portfolio(client, h)
    close = float(client.get("/stocks/TCS.NS", headers=h).json()["latest_bar"]["close"])
    entry = Decimal(f"{close:.2f}")
    proposal = {
        "ticker": "TCS.NS",
        "side": "buy",
        "quantity": 20,
        "entry_price": str(entry),
        "stop_loss": str((entry * Decimal("0.95")).quantize(Decimal("0.01"))),
        "target": str((entry * Decimal("1.15")).quantize(Decimal("0.01"))),
        "horizon_days": 20,
        "portfolio_id": pid,
        "mode": "paper",
        "quoted_spread_bps": 5,
    }
    d = client.post("/trade/proposals", headers=h, json=proposal).json()
    assert d["decision"] == "APPROVED", [
        (g["name"], g["reason"]) for g in d["gates"] if g["status"] != "PASS"
    ]
    assert d["requires_human_approval"] is True
    # oversize the same trade -> sizing and portfolio limits reject it
    big = client.post("/trade/proposals", headers=h, json={**proposal, "quantity": 5000}).json()
    assert big["decision"] == "REJECTED"
    assert {"position_sizing", "portfolio_limits"} <= set(big["failed_gates"])


def test_gates_status_and_costs_endpoints(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    g = client.get("/trade/gates", headers=h).json()
    assert len(g["gates"]) == 24 and g["self_test"]["passed"]
    checks = {
        c["name"]: c["status"] for c in client.get("/risk/status", headers=h).json()["checks"]
    }
    assert checks["risk_engine"] == "PASS"
    _seed_stock(db, "TCS.NS", CALM)
    c = client.post(
        "/trade/costs", headers=h, json={"ticker": "TCS.NS", "quantity": 100, "entry_price": "1000"}
    ).json()
    assert c["round_trip_fraction"] > 0 and c["participation_pct_of_adv"] > 0


def test_trade_endpoints_need_auth(client: TestClient) -> None:
    assert client.post("/trade/proposals", json={}).status_code == 401
    for p in ("/trade/proposals", "/trade/gates", "/trade/decisions/1"):
        assert client.get(p).status_code == 401
