"""Phase 7: risk statistics, the Risk agent, portfolios and the Portfolio agent."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import risk as rk
from app.api.routes.stocks import get_now
from app.core.config_file import get_config
from app.macro import service as ms
from app.macro.providers import Obs
from app.main import app
from app.market_data import service as md
from app.market_data.calendar import get_calendar
from app.market_data.types import Bar, PriceBasis, ProviderBatch, Ticker
from app.models import AuditLog, User
from tests.conftest import auth_header
from tests.market_helpers import NOW

CFG = get_config()
CAL = get_calendar()
LAST = CAL.latest_completed_session(NOW, timedelta(minutes=60))
SESSIONS = CAL.sessions(LAST - timedelta(days=500), LAST)[-300:]


# ------------------------------------------------------------ pure statistics --


def test_returns_and_volatility() -> None:
    r = rk.returns([100, 101, 99.99, 100.9899])
    assert r == pytest.approx([0.01, -0.01, 0.01])
    alt = np.array([0.01, -0.01] * 50)
    assert rk.annual_volatility(alt, 252) == pytest.approx(np.std(alt, ddof=1) * np.sqrt(252))
    assert rk.annual_volatility(np.array([0.01]), 252) is None
    with pytest.raises(ValueError):
        rk.returns([100, 0, 5])


def test_max_drawdown_hand_worked() -> None:
    d = [date(2026, 1, i) for i in range(1, 7)]
    dd = rk.max_drawdown(list(zip(d, [100, 120, 90, 110, 60, 80], strict=True)))
    assert dd.max_drawdown == pytest.approx(0.5)  # 120 -> 60
    assert (dd.peak, dd.trough) == (d[1], d[4])
    assert dd.current == pytest.approx(1 - 80 / 120)
    assert rk.max_drawdown([(d[0], 1.0), (d[1], 2.0)]).max_drawdown == 0.0


def test_var_cvar_and_ratios() -> None:
    r = np.array([-0.05, -0.04, -0.03, -0.02, -0.01] + [0.01] * 95)
    v, cv = rk.var_cvar(r, 0.95)
    assert v == pytest.approx(0.01)  # 5th percentile (lower) of 100 obs
    assert cv == pytest.approx(0.03)  # mean of the 5 worst
    assert rk.var_cvar(r[:10], 0.95) == (None, None)  # too few observations
    up = np.full(252, 0.001) + np.tile([0.002, -0.002], 126)
    assert rk.sharpe(up, 0.05) > 0 and rk.sortino(up, 0.05) > rk.sharpe(up, 0.05)
    assert rk.sharpe(-up, 0.05) < 0


def test_beta_and_alignment() -> None:
    rng = np.random.default_rng(3)
    m = rng.normal(0, 0.01, 400)
    s = 1.5 * m + rng.normal(0, 0.002, 400)
    assert rk.beta_daily(s, m) == pytest.approx(1.5, abs=0.05)
    assert rk.beta_daily(s[:10], m[:10]) is None
    d = [date(2026, 1, i) for i in range(1, 6)]
    a = [(d[0], 100.0), (d[1], 110.0), (d[2], 121.0), (d[4], 133.1)]
    b = [(d[0], 10.0), (d[2], 11.0), (d[3], 12.0), (d[4], 12.1)]
    ra, rb, dates = rk.aligned_returns(a, b)
    # common dates d0, d2, d4 only: no spurious return from unmatched days
    assert dates == [d[2], d[4]]
    assert ra == pytest.approx([0.21, 0.1]) and rb == pytest.approx([0.1, 0.1])


def test_concentration() -> None:
    assert rk.herfindahl([1, 1, 1, 1]) == pytest.approx(0.25)
    assert rk.herfindahl([1]) == 1.0 and rk.herfindahl([]) == 0.0


@settings(max_examples=80, deadline=None)
@given(st.lists(st.floats(-0.09, 0.09), min_size=25, max_size=200), st.floats(0.5, 5.0))
def test_risk_stat_properties(rets: list[float], scale: float) -> None:
    prices = list(100 * np.cumprod(1 + np.array(rets)))
    pts = [(date(2020, 1, 1) + timedelta(days=i), p) for i, p in enumerate(prices)]
    dd = rk.max_drawdown(pts)
    assert 0 <= dd.max_drawdown < 1 and 0 <= dd.current <= dd.max_drawdown + 1e-12
    # drawdown is scale invariant
    scaled = rk.max_drawdown([(d, p * scale) for d, p in pts])
    assert scaled.max_drawdown == pytest.approx(dd.max_drawdown, abs=1e-9)
    v, cv = rk.var_cvar(np.array(rets), 0.95)
    assert v is not None and cv is not None and cv >= v - 1e-12


# --------------------------------------------------------------- seeding --


def _seed_stock(
    db: Session, ticker: str, rets: np.ndarray, volume: int = 2_000_000, start: float = 1000.0
) -> None:
    t = Ticker.parse(ticker)
    stock = md.add_stock(db, t, None)
    closes = start * np.cumprod(np.concatenate([[1.0], 1 + rets]))
    sessions = SESSIONS[-len(closes) :]
    bars = [
        Bar(
            session=s,
            open=Decimal(f"{c:.2f}"),
            high=Decimal(f"{c * 1.005:.2f}"),
            low=Decimal(f"{c * 0.995:.2f}"),
            close=Decimal(f"{c:.2f}"),
            volume=volume,
        )
        for s, c in zip(sessions, closes, strict=True)
    ]
    batch = ProviderBatch(
        ticker=t,
        source="test",
        licensed=True,
        basis=PriceBasis.SPLIT_ADJUSTED,
        retrieved_at=NOW - timedelta(minutes=5),
        bars=bars,
    )
    md.ingest_batch(db, stock, batch, requested=(sessions[0], sessions[-1]), now=NOW)
    db.commit()


def _seed_benchmark(db: Session, rets: np.ndarray) -> None:
    levels = 20000 * np.cumprod(np.concatenate([[1.0], 1 + rets]))
    sessions = SESSIONS[-len(levels) :]
    obs = [
        Obs(
            "nifty50",
            "daily",
            s,
            float(v),
            "points",
            "test",
            True,
            None,
            CAL.session_close_utc(s) + timedelta(hours=1),
            False,
        )
        for s, v in zip(sessions, levels, strict=True)
    ]
    ms.store(db, obs, retrieved_at=datetime(2020, 1, 1, tzinfo=UTC))
    db.commit()


RNG = np.random.default_rng(7)
MKT = RNG.normal(0.0003, 0.009, 280)
CALM = 0.6 * MKT + RNG.normal(0, 0.004, 280)  # low vol, low beta
WILD = 1.8 * MKT + RNG.normal(0, 0.025, 280)  # high vol, high beta


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()


# -------------------------------------------------------------- risk agent --


def test_risk_agent_ranks_calm_above_wild(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    _seed_stock(db, "INFY.NS", WILD)
    calm = client.get("/risk-agent/TCS.NS", headers=h).json()
    wild = client.get("/risk-agent/INFY.NS", headers=h).json()
    assert calm["status"] == wild["status"] == "ok"
    assert calm["score"] > 50 > wild["score"]
    assert calm["metrics"]["beta"] == pytest.approx(0.6, abs=0.1)
    assert wild["metrics"]["beta"] == pytest.approx(1.8, abs=0.3)
    assert wild["metrics"]["volatility_annual"] > CFG.risk_analysis.high_volatility
    assert any("High volatility" in r for r in wild["risks"])
    assert any("High market sensitivity" in r for r in wild["risks"])
    for k in ("var_95_1d", "cvar_99_1d", "max_drawdown", "sharpe", "sortino", "adtv"):
        assert calm["metrics"][k] is not None
    assert "not a forecast" in calm["score_basis"]


def test_risk_agent_liquidity_failure(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM, volume=1_000)  # ~₹10 lakh/day << ₹5 crore minimum
    out = client.get("/risk-agent/TCS.NS", headers=h).json()
    liq = next(s for s in out["signals"] if s["name"] == "liquidity")
    assert liq["direction"] == "bearish" and liq["strength"] == 1.0
    assert any("FAILS the liquidity minimum" in r for r in out["risks"])
    assert any("Beta unavailable" in w for w in out["warnings"])  # no benchmark seeded


def test_risk_agent_point_in_time_and_insufficient(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    full = client.get("/risk-agent/TCS.NS", headers=h).json()
    cut = CAL.session_close_utc(SESSIONS[-100]) + timedelta(hours=2)
    early = client.get("/risk-agent/TCS.NS", headers=h, params={"as_of": cut.isoformat()}).json()
    mid = CAL.session_close_utc(SESSIONS[-20]) + timedelta(hours=2)
    later = client.get("/risk-agent/TCS.NS", headers=h, params={"as_of": mid.isoformat()}).json()
    assert early["status"] == "ok" and full["status"] == "ok"
    assert early["metrics"]["history_sessions"] < full["metrics"]["history_sessions"]
    assert later["metrics"]["history_sessions"] <= full["metrics"]["history_sessions"]
    _seed_stock(db, "INFY.NS", CALM[-50:])
    short = client.get("/risk-agent/INFY.NS", headers=h).json()
    assert short["status"] == "insufficient_data" and short["score"] is None


# --------------------------------------------------------------- portfolios --


def _portfolio(client: TestClient, h: dict[str, str], cash: str = "1000000") -> int:
    r = client.post("/portfolios", headers=h, json={"name": "Core", "cash": cash})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_portfolio_limits_and_audit(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    _seed_stock(db, "HDFCBANK.NS", WILD)
    pid = _portfolio(client, h)
    assert (
        client.post("/portfolios", headers=h, json={"name": "Core", "cash": "1"}).status_code == 409
    )
    client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "TCS.NS", "quantity": 50, "avg_cost": "900"},
    )
    client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "HDFCBANK.NS", "quantity": 40, "avg_cost": "1000"},
    )
    a = client.get(f"/portfolios/{pid}/analysis", headers=h).json()
    checks = {c["name"]: c for c in a["checks"]}
    w = {x["ticker"]: x["weight"] for x in a["holdings"]}
    assert sum(w.values()) + a["metrics"]["cash"] / a["metrics"]["equity"] == pytest.approx(1)
    expect = "FAIL" if max(w.values()) > CFG.risk_controls.max_single_position_weight else "PASS"
    assert checks["position_weight"]["status"] == expect
    assert checks["sector_weight"]["status"] in ("PASS", "FAIL")
    assert checks["liquidity"]["status"] == "PASS"
    assert a["metrics"]["volatility_annual"] is not None and a["metrics"]["beta"] is not None
    assert a["sector_weights"].keys() == {"IT_SERVICES", "PRIVATE_BANKS"}
    # removal and audit trail
    client.put(f"/portfolios/{pid}/positions", headers=h, json={"ticker": "TCS.NS", "quantity": 0})
    assert [
        p["ticker"] for p in client.get(f"/portfolios/{pid}", headers=h).json()["positions"]
    ] == ["HDFCBANK.NS"]
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "portfolio")).all()
    assert actions.count("portfolio.position.set") == 3 and "portfolio.create" in actions


def test_paper_portfolio_is_broker_only(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    pid = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "100"}
    ).json()["id"]
    r = client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "TCS.NS", "quantity": 1, "avg_cost": "1"},
    )
    assert r.status_code == 409 and "paper" in r.json()["detail"]
    assert client.put(f"/portfolios/{pid}/cash", headers=h, json={"cash": "5"}).status_code == 409


def test_unpriced_holding_is_unknown_not_pass(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    client.post("/stocks", headers=h, json={"ticker": "WIPRO.NS"})  # never ingested
    pid = _portfolio(client, h)
    client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "WIPRO.NS", "quantity": 10, "avg_cost": "300"},
    )
    a = client.get(f"/portfolios/{pid}/analysis", headers=h).json()
    assert a["limits_status"] == "UNKNOWN"
    assert {c["name"]: c["status"] for c in a["checks"]}["position_weight"] == "UNKNOWN"
    fit = client.get(f"/portfolio-agent/{pid}/TCS.NS", headers=h).json()["analysis"]
    assert fit["status"] == "insufficient_data" and fit["score"] is None


def test_portfolio_fit(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    _seed_stock(db, "INFY.NS", CALM + RNG.normal(0, 0.0005, 280))  # near-copy of TCS
    _seed_stock(db, "HDFCBANK.NS", RNG.normal(0.0003, 0.008, 280))  # independent
    pid = _portfolio(client, h, cash="1000000")
    client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "TCS.NS", "quantity": 80, "avg_cost": "900"},
    )
    twin = client.get(f"/portfolio-agent/{pid}/INFY.NS", headers=h, params={"weight": 0.05}).json()
    indep = client.get(
        f"/portfolio-agent/{pid}/HDFCBANK.NS", headers=h, params={"weight": 0.05}
    ).json()
    tw, ind = twin["analysis"], indep["analysis"]
    assert tw["status"] == ind["status"] == "ok"
    div_t = next(s for s in tw["signals"] if s["name"] == "diversification")
    div_i = next(s for s in ind["signals"] if s["name"] == "diversification")
    assert div_t["direction"] == "bearish" and div_i["direction"] == "bullish"
    assert ind["score"] > tw["score"]
    assert any("little diversification" in r for r in tw["risks"])
    # too big a bite: breaches the single-position limit and is attributed to the trade
    big = client.get(
        f"/portfolio-agent/{pid}/HDFCBANK.NS", headers=h, params={"weight": 0.2}
    ).json()
    lim = next(s for s in big["analysis"]["signals"] if s["name"] == "limit_position_weight")
    assert lim["direction"] == "bearish" and lim["strength"] == 1.0
    # beyond available cash: the cash limit fails
    rich = client.get(
        f"/portfolio-agent/{pid}/HDFCBANK.NS", headers=h, params={"weight": 1.0}
    ).json()
    assert any(s["name"] == "limit_cash" for s in rich["analysis"]["signals"])
    assert (
        client.get(
            f"/portfolio-agent/{pid}/HDFCBANK.NS", headers=h, params={"weight": 0}
        ).status_code
        == 422
    )


def test_preexisting_breach_not_blamed_on_trade(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    _seed_stock(db, "HDFCBANK.NS", RNG.normal(0.0003, 0.008, 280))
    pid = _portfolio(client, h, cash="100000")
    client.put(
        f"/portfolios/{pid}/positions",
        headers=h,
        json={"ticker": "TCS.NS", "quantity": 500, "avg_cost": "900"},
    )  # ~80% weight
    out = client.get(
        f"/portfolio-agent/{pid}/HDFCBANK.NS", headers=h, params={"weight": 0.05}
    ).json()
    a = out["analysis"]
    assert not any(s["name"] == "limit_position_weight" for s in a["signals"])
    assert any("already breaches position weight" in w for w in a["warnings"])


def test_risk_endpoints_need_auth(client: TestClient) -> None:
    for path in (
        "/risk-agent/TCS.NS",
        "/portfolios",
        "/portfolios/1/analysis",
        "/portfolio-agent/1/TCS.NS",
    ):
        assert client.get(path).status_code == 401
