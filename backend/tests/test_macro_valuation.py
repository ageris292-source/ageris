"""Phase 6: macro data, market regime, sector-aware macro agent, DCF and the
valuation agent."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.analysis.regime import detect
from app.analysis.stats import beta
from app.api.routes.fundamentals import get_fundamentals_provider
from app.api.routes.stocks import get_daily_provider, get_now
from app.core.config_file import get_config
from app.macro import service as ms
from app.macro.providers import Obs, WorldBankProvider, YahooSeriesProvider
from app.main import app
from app.models import User
from app.valuation.dcf import Assumptions, DcfError, cost_of_capital, run_dcf, sensitivity
from tests.conftest import auth_header
from tests.market_helpers import NOW, load, provider_for
from tests.test_fundamentals import fprovider

CFG = get_config()


# ----------------------------------------------------------------------- DCF --

BASE = Assumptions(
    revenue=100.0,
    growth=0.10,
    fcf_margin=0.20,
    wacc=0.10,
    terminal_growth=0.04,
    years=2,
    debt=10.0,
    cash=5.0,
    shares=10.0,
)


def test_dcf_hand_worked() -> None:
    r = run_dcf(BASE)
    f1, f2 = 110 * 0.2, 121 * 0.2
    pv = f1 / 1.1 + f2 / 1.21
    tv = f2 * 1.04 / 0.06
    ev = pv + tv / 1.21
    assert r.fcf == pytest.approx([f1, f2])
    assert r.enterprise_value == pytest.approx(ev)
    assert r.per_share == pytest.approx((ev - 10 + 5) / 10)
    assert r.notes  # terminal value dominates this short projection


def test_dcf_rejects_wacc_below_growth() -> None:
    with pytest.raises(DcfError):
        run_dcf(Assumptions(**{**BASE.__dict__, "wacc": 0.04}))


@settings(max_examples=60, deadline=None)
@given(w=st.floats(0.08, 0.16), g=st.floats(0.0, 0.06), m=st.floats(0.05, 0.4))
def test_dcf_monotonic(w: float, g: float, m: float) -> None:
    a = Assumptions(
        **{**BASE.__dict__, "wacc": w, "terminal_growth": g, "fcf_margin": m, "years": 5}
    )
    v = run_dcf(a).per_share
    assert run_dcf(Assumptions(**{**a.__dict__, "wacc": w + 0.01})).per_share < v
    assert run_dcf(Assumptions(**{**a.__dict__, "fcf_margin": m + 0.01})).per_share > v
    if g + 0.005 < w:
        assert run_dcf(Assumptions(**{**a.__dict__, "terminal_growth": g + 0.005})).per_share > v


def test_sensitivity_grid_and_wacc() -> None:
    grid = sensitivity(
        Assumptions(**{**BASE.__dict__, "years": 5}), [-0.01, 0, 0.01], [-0.01, 0, 0.01]
    )
    assert len(grid) == 3 and all(len(r) == 3 for r in grid)
    assert grid[0][1] > grid[1][1] > grid[2][1]  # higher WACC -> lower value
    assert grid[1][0] < grid[1][1] < grid[1][2]  # higher growth -> higher value
    wacc, parts = cost_of_capital(
        risk_free=0.06,
        erp=0.07,
        beta=1.2,
        market_cap=900,
        debt=100,
        interest_expense=-8,
        tax_rate=0.25,
    )
    assert parts["cost_of_equity"] == pytest.approx(0.144)
    assert parts["cost_of_debt_after_tax"] == pytest.approx(0.06)
    assert wacc == pytest.approx(0.9 * 0.144 + 0.1 * 0.06)


# ---------------------------------------------------------- regime and beta --


def _dates(n: int) -> list[date]:
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def test_regime_detection() -> None:
    up = list(100 * 1.002 ** np.arange(300))
    down = list(100 * 0.998 ** np.arange(300))
    kw = {"vix_high": 20, "vix_low": 13, "band": 0.02}
    bull = detect(up, [11.0], **kw)
    assert (bull.trend, bull.volatility, bull.risk, bull.label) == (
        "bull",
        "low",
        "risk_on",
        "BULL_LOW_VOL",
    )
    bear = detect(down, [25.0], **kw)
    assert (bear.trend, bear.volatility, bear.risk) == ("bear", "high", "risk_off")
    flat = detect([100.0] * 300, [15.0], **kw)
    assert flat.trend == "sideways" and flat.risk == "neutral"
    unknown = detect(up[:50], None, **kw)
    assert unknown.label == "UNKNOWN" and not unknown.known


def test_beta_recovers_known_slope() -> None:
    rng = np.random.default_rng(0)
    m = np.cumprod(1 + rng.normal(0, 0.01, 800)) * 100
    mret = np.diff(m) / m[:-1]
    s = np.concatenate([[100.0], 100 * np.cumprod(1 + 1.5 * mret)])
    d = _dates(800)
    b, n = beta(list(zip(d, s, strict=True)), list(zip(d, m, strict=True)), 104)
    assert n == 104 and b == pytest.approx(1.5, rel=0.05)
    assert (
        beta(list(zip(d[:50], s[:50], strict=True)), list(zip(d[:50], m[:50], strict=True)), 104)[0]
        is None
    )


# ---------------------------------------------------------------- providers --


def test_world_bank_parse() -> None:
    obs = WorldBankProvider(180).parse(
        "cpi_inflation", "FP.CPI.TOTL.ZG", load("worldbank_cpi_in.json")
    )
    latest = max(obs, key=lambda o: o.period_date)
    assert latest.period_date == date(2025, 12, 31) and 0 < latest.value < 0.2  # fraction, not %
    assert latest.licensed and latest.availability_estimated
    assert latest.available_at.date() == date(2026, 6, 29)
    with pytest.raises(Exception, match="no data"):
        WorldBankProvider(180).parse("x", "Y", [{"page": 1}, None])


def test_yahoo_series_parse_drops_incomplete_session() -> None:
    payload = load("yahoo_nsei_2023_2024.json")
    last_ts = payload["chart"]["result"][0]["timestamp"][-1]
    during = datetime.fromtimestamp(last_ts, UTC) + timedelta(hours=2)
    obs = YahooSeriesProvider().parse("nifty50", "^NSEI", payload, during)
    after = YahooSeriesProvider().parse("nifty50", "^NSEI", payload, during + timedelta(days=1))
    assert len(after) == len(obs) + 1
    assert all(o.unit == "INR" and not o.licensed for o in obs)


def test_point_in_time_macro_reads(db: Session) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    est = Obs(
        "cpi_inflation",
        "annual",
        date(2024, 12, 31),
        0.05,
        "fraction",
        "WB",
        True,
        None,
        datetime(2025, 6, 29, tzinfo=UTC),
        True,
    )
    ms.store(db, [est], retrieved_at=t0)
    db.commit()
    assert (
        ms.series_as_of(db, "cpi_inflation", datetime(2025, 9, 1, tzinfo=UTC)) == []
    )  # not retrieved yet
    assert ms.series_as_of(db, "cpi_inflation", t0 + timedelta(days=1)) == [
        (date(2024, 12, 31), 0.05)
    ]


# -------------------------------------------------------------- integration --


def _seed_market(db: Session, nifty_change: float, usd_inr_change: float) -> None:
    """Deterministic daily series ending at NOW: 300 sessions, with the last
    63 sessions moving by the given total change."""
    days = [NOW.date() - timedelta(days=300 - i) for i in range(301)]
    obs: list[Obs] = []
    for name, chg in (
        ("nifty50", nifty_change),
        ("nifty_it", 0.0),
        ("nifty_bank", 0.0),
        ("usd_inr", usd_inr_change),
        ("india_vix", 0.0),
    ):
        base = 15.0 if name == "india_vix" else 100.0
        for i, d in enumerate(days):
            step = max(0, i - (len(days) - 64))
            v = base * (1 + chg * step / 63)
            obs.append(
                Obs(
                    name,
                    "daily",
                    d,
                    v,
                    "INR",
                    "test",
                    False,
                    None,
                    datetime.combine(d, datetime.min.time(), UTC) + timedelta(hours=12),
                    False,
                )
            )
    ms.store(db, obs, retrieved_at=datetime(2020, 1, 1, tzinfo=UTC))
    db.commit()


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()


def test_macro_agent_is_sector_aware(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    _seed_market(db, nifty_change=0.0, usd_inr_change=0.05)  # rupee weakens 5%
    for t in ("TCS.NS", "HDFCBANK.NS", "M&M.NS"):
        client.post("/stocks", headers=h, json={"ticker": t})
    it = client.get("/macro-agent/TCS.NS", headers=h).json()
    unknown = client.get("/macro-agent/M&M.NS", headers=h).json()
    fx = next(s for s in it["signals"] if s["name"] == "macro_usd_inr")
    assert fx["direction"] == "bullish" and "tailwind" in fx["detail"]  # IT exporter
    assert not any(s["name"] == "macro_usd_inr" for s in unknown["signals"])
    assert any("No sector configured" in w for w in unknown["warnings"])
    bank = client.get("/macro-agent/HDFCBANK.NS", headers=h).json()
    assert any("RBI repo rate" in w for w in bank["warnings"])  # manual series not entered
    reg = client.get("/regime", headers=h).json()
    assert reg["known"] and reg["volatility"] == "normal"


def test_manual_macro_entry_admin_only(
    api: tuple[TestClient, dict[str, str]], analyst: User
) -> None:
    client, h = api
    body = {
        "series": "repo_rate",
        "period_date": "2026-08-06",
        "value": 0.055,
        "unit": "fraction",
        "source": "RBI MPC statement",
        "published_at": "2026-08-06T10:00:00+05:30",
    }
    assert (
        client.post(
            "/macro/manual", headers=auth_header(client, analyst.email), json=body
        ).status_code
        == 403
    )
    assert client.post("/macro/manual", headers=h, json=body).status_code == 201
    assert (
        client.post(
            "/macro/manual", headers=h, json={**body, "published_at": "2026-08-06T10:00:00"}
        ).status_code
        == 422
    )
    summary = {r["series"]: r for r in client.get("/macro", headers=h).json()}
    assert summary["repo_rate"]["latest_value"] == 0.055


def test_valuation_agent_end_to_end(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_tcs_ns_recent.json")
    )
    app.dependency_overrides[get_fundamentals_provider] = lambda: fprovider(
        load("yahoo_fundamentals_tcs.json")
    )
    client.post("/stocks", headers=h, json={"ticker": "TCS.NS"})
    client.post(
        "/stocks/TCS.NS/ingest", headers=h, json={"start": "2026-08-01", "end": "2026-09-25"}
    )
    client.post("/financials/TCS.NS/ingest", headers=h)
    as_of = datetime.now(UTC).isoformat()  # estimated-date financials need a real-clock as_of
    r = client.get("/valuation/TCS.NS", headers=h, params={"as_of": as_of}).json()
    out, d = r["analysis"], r["details"]
    assert out["status"] == "ok", out["warnings"]
    sc = d["scenarios"]
    assert sc["bear"]["per_share"] < sc["base"]["per_share"] < sc["bull"]["per_share"]
    for s in sc.values():
        assert {"growth", "fcf_margin", "wacc", "terminal_growth"} <= s["assumptions"].keys()
    grid = d["sensitivity"]["per_share"]
    assert grid[0][1] > grid[1][1] > grid[2][1]
    assert any("Beta not estimable" in w for w in out["warnings"])  # no benchmark series seeded
    assert any("assumptions" in w for w in out["warnings"])  # rf / ERP are assumptions
    assert "not a price target" in out["score_basis"]


def test_valuation_insufficient_without_financials(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    client.post("/stocks", headers=h, json={"ticker": "INFY.NS"})
    out = client.get("/valuation/INFY.NS", headers=h).json()["analysis"]
    assert out["status"] == "insufficient_data" and out["score"] is None


def test_macro_endpoints_need_auth(client: TestClient) -> None:
    for path in ("/macro", "/regime", "/macro-agent/TCS.NS", "/valuation/TCS.NS"):
        assert client.get(path).status_code == 401
    assert client.post("/macro/ingest").status_code == 401


def test_world_bank_http_failure() -> None:
    p = WorldBankProvider(180, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    with pytest.raises(Exception, match="HTTP 500"):
        p.fetch("cpi_inflation", "FP.CPI.TOTL.ZG")
