"""Phase 4: financial facts, deterministic ratios, point-in-time visibility,
and the fundamental agent. Uses a real recorded Yahoo fundamentals payload."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.agents.fundamental.agent import analyze_fundamentals
from app.api.routes.fundamentals import get_fundamentals_provider
from app.api.routes.stocks import get_daily_provider, get_now
from app.core.config_file import get_config
from app.fundamentals.providers import (
    YahooFundamentalsProvider,
    estimated_availability,
    parse_fundamentals_csv,
)
from app.fundamentals.ratios import annual_ratios, valuation
from app.main import app
from app.market_data.providers.base import ProviderError
from app.market_data.types import Ticker
from app.models import FinancialFact, User
from tests.conftest import auth_header
from tests.market_helpers import NOW, load, provider_for

CFG = get_config()
TCS = Ticker.parse("TCS.NS")


def fprovider(
    payload: dict | None = None, exc: Exception | None = None
) -> YahooFundamentalsProvider:  # type: ignore[type-arg]
    def handler(_: httpx.Request) -> httpx.Response:
        if exc:
            raise exc
        return httpx.Response(200, json=payload)

    return YahooFundamentalsProvider(
        CFG.market_data.providers["yahoo"], CFG.fundamentals, transport=httpx.MockTransport(handler)
    )


# ------------------------------------------------------------------ ratios --


def test_ratio_arithmetic() -> None:
    periods = {
        date(2025, 3, 31): {
            "revenue": 100.0,
            "net_income": 10.0,
            "equity": 50.0,
            "eps_diluted": 2.0,
            "operating_income": 15.0,
        },
        date(2026, 3, 31): {
            "revenue": 120.0,
            "net_income": 15.0,
            "equity": 70.0,
            "eps_diluted": 3.0,
            "operating_income": 21.0,
            "ebit": 22.0,
            "total_assets": 200.0,
            "current_liabilities": 90.0,
            "total_debt": 35.0,
            "interest_expense": -2.0,
            "operating_cash_flow": 18.0,
            "capex": -6.0,
            "gross_profit": 60.0,
        },
    }
    r = annual_ratios(periods)[-1].ratios
    assert r["revenue_growth"] == pytest.approx(0.20)
    assert r["eps_growth"] == pytest.approx(0.50)
    assert r["operating_margin"] == pytest.approx(21 / 120)
    assert r["roe"] == pytest.approx(15 / 60)  # average equity
    assert r["roce"] == pytest.approx(22 / 110)
    assert r["debt_to_equity"] == pytest.approx(0.5)
    assert r["interest_coverage"] == pytest.approx(11.0)
    assert r["free_cash_flow"] == pytest.approx(12.0)  # OCF + (negative) capex
    assert r["fcf_conversion"] == pytest.approx(0.8)
    first = annual_ratios(periods)[0].ratios
    assert first["revenue_growth"] is None and first["roce"] is None  # never zero-filled


def test_growth_off_non_positive_base_is_undefined() -> None:
    r = annual_ratios(
        {date(2025, 3, 31): {"net_income": -5.0}, date(2026, 3, 31): {"net_income": 10.0}}
    )[-1].ratios
    assert r["net_income_growth"] is None


def test_valuation_multiples() -> None:
    v = valuation(
        100.0,
        {
            "shares_diluted": 10.0,
            "eps_diluted": 5.0,
            "total_debt": 200.0,
            "cash": 50.0,
            "equity": 400.0,
            "ebitda": 150.0,
            "free_cash_flow": 40.0,
        },
        eps_growth=0.10,
    )
    assert v["market_cap"] == 1000 and v["enterprise_value"] == 1150
    assert v["pe"] == 20 and v["pb"] == 2.5
    assert v["ev_ebitda"] == pytest.approx(1150 / 150)
    assert v["peg"] == pytest.approx(2.0)
    assert v["fcf_yield"] == pytest.approx(0.04)


# ---------------------------------------------------------------- providers --


def test_estimated_availability_uses_sebi_deadlines() -> None:
    # 60 days after 31 Mar = 30 May; end of that IST day.
    a = estimated_availability("annual", date(2026, 3, 31), CFG.fundamentals)
    assert a == datetime(2026, 5, 30, 18, 29, tzinfo=UTC)
    q = estimated_availability("quarterly", date(2026, 6, 30), CFG.fundamentals)
    assert q.date() == date(2026, 8, 14)


def test_parse_recorded_yahoo_payload() -> None:
    batch = fprovider(load("yahoo_fundamentals_tcs.json")).fetch(TCS)
    assert batch.licensed is False and batch.source == "yahoo_fundamentals"
    rev = {
        f.period_end: f.value
        for f in batch.facts
        if f.line_item == "revenue" and f.period_type == "annual"
    }
    assert rev[date(2026, 3, 31)] == Decimal("2670210000000.0")
    assert len(rev) == 4
    assert all(f.availability_estimated and f.published_at is None for f in batch.facts)
    assert all(f.available_at.date() > f.period_end for f in batch.facts)


def test_empty_or_broken_payload_is_an_error() -> None:
    with pytest.raises(ProviderError):
        fprovider({"timeseries": {"result": []}}).fetch(TCS)
    with pytest.raises(ProviderError):
        fprovider({"nope": 1}).fetch(TCS)


CSV = (
    "period_type,period_end,line_item,value,published_at\n"
    "annual,2024-03-31,revenue,1000,2024-04-20T18:00:00+05:30\n"
    "annual,2024-03-31,net_income,100,2024-04-20T18:00:00+05:30\n"
    "annual,2025-03-31,revenue,1200,2025-04-18T18:00:00+05:30\n"
    "annual,2025-03-31,net_income,130,2025-04-18T18:00:00+05:30\n"
)


def test_csv_requires_real_publication_times() -> None:
    settings = CFG.market_data.providers["csv_import"]
    b = parse_fundamentals_csv(CSV, TCS, "vendor", settings)
    assert all(not f.availability_estimated for f in b.facts) and b.licensed
    for bad, msg in [
        (CSV.replace("+05:30", "", 1), "timezone"),
        (CSV.replace("2024-04-20T18", "2024-03-01T18", 1), "before period end"),
        (CSV.replace("net_income", "vibes", 1), "line_item"),
    ]:
        with pytest.raises(ProviderError, match=msg):
            parse_fundamentals_csv(bad, TCS, "vendor", settings)


# ------------------------------------------------------------ pure analysis --


def test_distress_is_flagged() -> None:
    rows = annual_ratios(
        {
            date(2025, 3, 31): {
                "revenue": 100.0,
                "operating_income": 20.0,
                "net_income": 10.0,
                "equity": 100.0,
            },
            date(2026, 3, 31): {
                "revenue": 95.0,
                "operating_income": 10.0,
                "net_income": 8.0,
                "equity": 90.0,
                "total_debt": 200.0,
                "ebit": 10.0,
                "interest_expense": -8.0,
                "free_cash_flow": 2.0,
                "operating_cash_flow": 5.0,
            },
        }
    )
    signals, risks, _ = analyze_fundamentals(rows, None, CFG.fundamentals)
    names = {s.name for s in signals}
    assert {"margin_deterioration", "leverage", "interest_coverage", "cash_conversion"} <= names
    assert any(r.startswith("Debt stress") for r in risks)
    assert any(r.startswith("Weak interest coverage") for r in risks)
    assert any(r.startswith("Margin deterioration") for r in risks)


def test_bank_skips_industrial_ratios_and_tiny_growth_skips_peg() -> None:
    rows = annual_ratios(
        {
            date(2025, 3, 31): {
                "revenue": 100.0,
                "net_income": 10.0,
                "equity": 100.0,
                "eps_diluted": 10.0,
            },
            date(2026, 3, 31): {
                "revenue": 104.0,
                "net_income": 10.2,
                "equity": 100.0,
                "eps_diluted": 10.1,
                "total_debt": 900.0,
                "ebit": 20.0,
                "interest_expense": -15.0,
                "free_cash_flow": 1.0,
                "shares_diluted": 10.0,
            },
        }
    )
    industrial, _risks, _ = analyze_fundamentals(rows, 200.0, CFG.fundamentals)
    assert {"leverage", "interest_coverage", "cash_conversion"} <= {s.name for s in industrial}
    bank, bank_risks, _ = analyze_fundamentals(rows, 200.0, CFG.fundamentals, financial_sector=True)
    names = {s.name for s in bank}
    assert not names & {"leverage", "interest_coverage", "cash_conversion", "earnings_quality"}
    assert not any("Debt stress" in r for r in bank_risks)
    assert "peg" not in names  # 1% EPS growth: PEG not meaningful


# -------------------------------------------------------------- integration --


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_tcs_ns_recent.json")
    )
    app.dependency_overrides[get_fundamentals_provider] = lambda: fprovider(
        load("yahoo_fundamentals_tcs.json")
    )
    h = auth_header(client, admin.email)
    client.post("/stocks", headers=h, json={"ticker": "TCS.NS"})
    client.post(
        "/stocks/TCS.NS/ingest", headers=h, json={"start": "2026-08-01", "end": "2026-09-25"}
    )
    yield client, h
    app.dependency_overrides.clear()


def test_ingest_idempotent_and_immutable(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    run = client.post("/financials/TCS.NS/ingest", headers=h).json()
    assert run["status"] == "succeeded" and run["rows_inserted"] > 100 and run["licensed"] is False
    again = client.post("/financials/TCS.NS/ingest", headers=h).json()
    assert again["rows_inserted"] == 0 and again["rows_unchanged"] == run["rows_inserted"]
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE financials SET value = 0"))
    db.rollback()


def test_financials_endpoint(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    client.post("/financials/TCS.NS/ingest", headers=h)
    f = client.get("/financials/TCS.NS", headers=h).json()
    assert f["licensed"] is False and f["availability_estimated"] is True and f["notice"]
    latest = f["annual"][-1]
    assert latest["period_end"] == "2026-03-31"
    assert latest["ratios"]["revenue_growth"] == pytest.approx(2670.21 / 2553.24 - 1, rel=1e-6)
    assert f["annual"][0]["ratios"]["revenue_growth"] is None


def test_agent_ok_now_but_blind_in_the_past(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    client.post("/financials/TCS.NS/ingest", headers=h)
    # as_of must be after the (real-clock) retrieval for estimated-date figures.
    real_now = datetime.now(UTC).isoformat()
    now = client.get("/fundamental/TCS.NS", headers=h, params={"as_of": real_now}).json()
    assert now["status"] == "ok", now["warnings"]
    assert now["metrics"]["pe"] is not None and now["metrics"]["roe"] is not None
    assert any("estimated" in w for w in now["warnings"])
    assert "not a probability" in now["score_basis"]
    # A year ago Aegis had not retrieved these (estimated-date) figures: no guessing.
    past = client.get(
        "/fundamental/TCS.NS", headers=h, params={"as_of": "2025-09-01T12:00:00+00:00"}
    ).json()
    assert past["status"] == "insufficient_data" and past["score"] is None


def test_licensed_csv_is_visible_historically(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    r = client.post(
        "/financials/TCS.NS/import-csv",
        headers=h,
        files={"file": ("f.csv", CSV, "text/csv")},
        data={"source": "vendor"},
    )
    assert r.status_code == 200 and r.json()["licensed"] is True
    before = client.get(
        "/financials/TCS.NS", headers=h, params={"as_of": "2025-04-18T11:00:00+00:00"}
    ).json()
    assert [p["period_end"] for p in before["annual"]] == ["2024-03-31"]  # FY25 not yet published
    after = client.get(
        "/financials/TCS.NS", headers=h, params={"as_of": "2025-04-18T13:00:00+00:00"}
    ).json()
    assert [p["period_end"] for p in after["annual"]] == ["2024-03-31", "2025-03-31"]
    out = client.get(
        "/fundamental/TCS.NS", headers=h, params={"as_of": "2025-06-01T12:00:00+00:00"}
    ).json()
    assert out["status"] == "ok"
    assert not any("estimated" in w for w in out["warnings"])


def test_provider_outage_fails_closed(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    app.dependency_overrides[get_fundamentals_provider] = lambda: fprovider(
        exc=httpx.ConnectError("down")
    )
    run = client.post("/financials/TCS.NS/ingest", headers=h).json()
    assert run["status"] == "failed" and "unreachable" in run["error"]
    assert db.scalar(select(FinancialFact).limit(1)) is None


def test_auth_and_roles(client: TestClient, analyst: User) -> None:
    h = auth_header(client, analyst.email)
    assert client.get("/fundamental/TCS.NS").status_code == 401
    assert client.get("/financials/INFY.NS", headers=h).status_code == 404
    assert (
        client.post(
            "/financials/TCS.NS/import-csv",
            headers=h,
            data={"source": "x"},
            files={"file": ("f.csv", CSV, "text/csv")},
        ).status_code
        == 403
    )
