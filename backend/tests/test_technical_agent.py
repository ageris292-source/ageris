"""Technical agent: contract, deterministic analysis, data gates, point-in-time
behaviour, reproducibility and persistence — against real Postgres and a real
recorded RELIANCE.NS history (2023-2024, includes the Oct 2024 1:1 bonus)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.agents.base import AgentOutput, AgentStatus
from app.agents.technical.analysis import analyze
from app.api.routes.stocks import get_daily_provider, get_now
from app.core.config_file import get_config
from app.main import app
from app.market_data import service as md
from app.market_data.types import Bar, PriceBasis, Ticker
from app.models import AgentOutputRecord, AgentRun, TechnicalIndicator, User
from tests.conftest import auth_header
from tests.market_helpers import NOW, load, provider_for, with_close

CFG = get_config()
REL = "RELIANCE.NS"
YEARS = {"start": "2023-01-01", "end": "2024-12-31"}
END_2024 = datetime(2024, 12, 31, 12, 0, tzinfo=UTC)


def bars_from(closes: np.ndarray, start: date = date(2020, 1, 1)) -> list[Bar]:
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        cd = Decimal(str(round(float(c), 2)))
        out.append(Bar(session=d, open=cd, high=cd + 1, low=cd - 1, close=cd, volume=1_000_000))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- contract --


def _out(**kw: object) -> AgentOutput:
    base: dict[str, object] = dict(
        agent="technical",
        agent_version="x",
        ticker=REL,
        as_of=NOW,
        generated_at=NOW,
        status=AgentStatus.OK,
        score=55.0,
        score_basis="b",
        confidence=0.5,
        confidence_basis="heuristic_uncalibrated",
        data_quality=1.0,
        data_snapshot_id="s",
        config_fingerprint="f",
    )
    base.update(kw)
    return AgentOutput.model_validate(base)


def test_contract_fails_closed() -> None:
    _out()
    with pytest.raises(ValidationError, match="requires a score"):
        _out(score=None)
    with pytest.raises(ValidationError, match="may not carry"):
        _out(status=AgentStatus.INSUFFICIENT_DATA, confidence=0.0, warnings=["x"])
    with pytest.raises(ValidationError, match="explain why"):
        _out(status=AgentStatus.FAILED, score=None, confidence=0.0)
    with pytest.raises(ValidationError):
        _out(score=101.0)


# ------------------------------------------------------- pure analysis --


def test_uptrend_scores_above_50_and_downtrend_below() -> None:
    up = analyze(bars_from(100 * 1.002 ** np.arange(400)), CFG.technical, CFG.liquidity)
    down = analyze(bars_from(100 * 0.998 ** np.arange(400)), CFG.technical, CFG.liquidity)
    assert up.score > 60 > 40 > down.score
    assert any(s.name == "price_vs_sma_long" and s.direction == "bullish" for s in up.signals)
    assert any("below" in c for c in up.invalidation_conditions)
    assert any("above" in c for c in down.invalidation_conditions)


@pytest.mark.parametrize("seed", range(25))
def test_invalidation_levels_are_never_already_breached(seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    r = analyze(bars_from(closes), CFG.technical, CFG.liquidity)
    close = r.metrics["close"]
    assert close is not None
    for cond in r.invalidation_conditions:
        if "₹" not in cond:
            continue
        level = float(cond.split("₹")[1].split(" ")[0].rstrip(")").replace(",", ""))
        if r.score > 50:
            assert "below" in cond and level < close, cond
        else:
            assert "above" in cond and level > close, cond


def test_flat_market_has_no_directional_thesis() -> None:
    r = analyze(bars_from(np.full(400, 100.0)), CFG.technical, CFG.liquidity)
    assert r.score == 50.0
    assert all(s.direction == "neutral" for s in r.signals)
    assert r.invalidation_conditions == ["No directional thesis: nothing to invalidate"]


def test_analysis_is_deterministic_and_bounded() -> None:
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    a = analyze(bars_from(closes), CFG.technical, CFG.liquidity)
    b = analyze(bars_from(closes), CFG.technical, CFG.liquidity)
    assert a.score == b.score and a.signals == b.signals and a.metrics == b.metrics
    assert 0 <= a.score <= 100 and 0 <= a.agreement <= 1 and 0 <= a.breadth <= 1


def test_low_liquidity_is_flagged() -> None:
    bars = [b.model_copy(update={"volume": 10}) for b in bars_from(np.full(300, 100.0))]
    r = analyze(bars, CFG.technical, CFG.liquidity)
    assert any(x.startswith("Low liquidity") for x in r.risks)


# ------------------------------------------------------- integration --


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_reliance_ns_2023_2024.json")
    )
    h = auth_header(client, admin.email)
    assert client.post("/stocks", headers=h, json={"ticker": REL}).status_code == 201
    run = client.post(f"/stocks/{REL}/ingest", headers=h, json=YEARS).json()
    assert run["usable"] is True, run
    yield client, h
    app.dependency_overrides.clear()


def test_agent_ok_on_real_history(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    r = client.get(f"/technical/{REL}", headers=h, params={"as_of": END_2024.isoformat()})
    assert r.status_code == 200
    out = AgentOutput.model_validate(r.json())
    assert out.status is AgentStatus.OK and out.score is not None
    assert out.confidence_basis == "heuristic_uncalibrated"
    assert "not a probability" in out.score_basis
    assert "Unlicensed price source: research use only" in out.warnings
    assert not any("Data freshness" in w for w in out.warnings)  # 31 Dec close is available
    assert out.metrics["sma_200"] is not None and out.signals and out.invalidation_conditions
    assert out.evidence[0].ref.startswith(f"prices:{REL}:split_adjusted:yahoo:")
    # Recorded: run, immutable output, feature-store rows tied to the snapshot.
    run = db.scalars(select(AgentRun)).one()
    assert run.status == "ok" and run.data_snapshot_id == out.data_snapshot_id
    rec = db.scalars(select(AgentOutputRecord)).one()
    assert rec.output["score"] == out.score
    feats = db.scalars(select(TechnicalIndicator)).all()
    assert {f.feature_name for f in feats} >= {"rsi", "sma_200", "macd", "atr"}
    assert all(f.session_date == date(2024, 12, 31) for f in feats)
    assert all(f.availability_timestamp.isoformat() == "2024-12-31T11:00:00+00:00" for f in feats)
    for stmt in ("UPDATE agent_outputs SET score = 0", "DELETE FROM technical_indicators"):
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(stmt))
        db.rollback()


def test_stale_data_warns_and_halves_confidence(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api

    def expected(o: dict) -> float:  # type: ignore[type-arg]
        m = o["metrics"]
        return m["signal_agreement"] * m["category_breadth"] * o["data_quality"]

    fresh = client.get(f"/technical/{REL}", headers=h, params={"as_of": END_2024.isoformat()})
    later = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)  # no 2025 bars stored
    stale = client.get(f"/technical/{REL}", headers=h, params={"as_of": later.isoformat()})
    f, s_ = fresh.json(), stale.json()
    assert f["confidence"] == pytest.approx(expected(f), abs=1e-4)
    assert s_["status"] == "ok" and any("Data freshness FAIL" in w for w in s_["warnings"])
    assert s_["confidence"] == pytest.approx(expected(s_) / 2, abs=1e-4)


def test_insufficient_history_is_not_scored(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    early = datetime(2023, 6, 1, 12, 0, tzinfo=UTC)
    out = client.get(f"/technical/{REL}", headers=h, params={"as_of": early.isoformat()}).json()
    assert out["status"] == "insufficient_data"
    assert out["score"] is None and out["signals"] == [] and out["confidence"] == 0
    assert "Need 260 sessions" in out["warnings"][0]


def test_point_in_time_equals_truncated_history(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    """The agent at as_of=T must see exactly the bars available at T."""
    client, h = api
    as_of = datetime(2024, 6, 28, 12, 0, tzinfo=UTC)  # after 2024-06-28 close + lag
    out = client.get(f"/technical/{REL}", headers=h, params={"as_of": as_of.isoformat()}).json()
    stock = md.get_stock(db, Ticker.parse(REL))
    series = md.get_series(
        db, stock, PriceBasis.SPLIT_ADJUSTED, date(2023, 1, 1), date(2024, 12, 31)
    )
    upto = [sb.bar for sb in series.bars if sb.bar.session <= date(2024, 6, 28)]
    expected = analyze(upto, CFG.technical, CFG.liquidity)
    assert out["metrics"]["close"] == expected.metrics["close"]
    assert out["score"] == expected.score
    # One minute before close + availability lag, that session is invisible.
    before = datetime(2024, 6, 28, 10, 59, tzinfo=UTC)
    out2 = client.get(f"/technical/{REL}", headers=h, params={"as_of": before.isoformat()}).json()
    assert out2["metrics"]["close"] == float(upto[-2].close)


def test_replay_is_exact_despite_later_revisions(
    api: tuple[TestClient, dict[str, str]],
) -> None:
    client, h = api
    q = {"as_of": END_2024.isoformat()}
    first = client.get(f"/technical/{REL}", headers=h, params=q).json()
    stable = ("score", "confidence", "signals", "metrics", "data_snapshot_id")
    # The provider now revises a Dec-2024 price (index 480).
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        with_close(load("yahoo_reliance_ns_2023_2024.json"), 480, 1300.0)
    )
    assert client.post(f"/stocks/{REL}/ingest", headers=h, json=YEARS).json()["rows_revised"] == 1
    # Replaying with the recorded knowledge_at reproduces the original run exactly...
    replay = client.get(
        f"/technical/{REL}", headers=h, params={**q, "knowledge_at": first["knowledge_at"]}
    ).json()
    for k in stable:
        assert replay[k] == first[k], k
    assert replay["config_fingerprint"] == first["config_fingerprint"]
    # ...while a fresh run as of the same market date sees the revised data.
    fresh = client.get(f"/technical/{REL}", headers=h, params=q).json()
    assert fresh["data_snapshot_id"] != first["data_snapshot_id"]


def test_unusable_data_blocks_analysis(client: TestClient, admin: User) -> None:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    client.post("/stocks", headers=h, json={"ticker": "GAPPY.NS"})
    closes = 100 * 1.001 ** np.arange(420)
    rows = [b for i, b in enumerate(bars_from(closes, date(2023, 1, 2))) if i % 4]  # 25% missing
    csv = "date,open,high,low,close,volume\n" + "".join(
        f"{b.session},{b.open},{b.high},{b.low},{b.close},{b.volume}\n" for b in rows
    )
    r = client.post(
        "/stocks/GAPPY.NS/import-csv",
        headers=h,
        files={"file": ("g.csv", csv, "text/csv")},
        data={"source": "test-vendor", "basis": "split_adjusted"},
    )
    assert r.status_code == 200
    out = client.get(
        "/technical/GAPPY.NS", headers=h, params={"as_of": "2024-12-31T12:00:00+00:00"}
    ).json()
    app.dependency_overrides.clear()
    assert out["status"] == "data_unusable" and out["score"] is None
    assert "excessive_missing_sessions" in out["warnings"][0]


def test_indicator_series_endpoint(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    s = client.get(
        f"/technical/{REL}/indicators",
        headers=h,
        params={"start": "2024-07-01", "end": "2024-12-31"},
    ).json()
    assert s["points"][0]["session"] >= "2024-07-01"
    assert s["warmup_sessions_excluded"] > 200
    assert all(p["sma_long"] is not None for p in s["points"])  # warm-up made them defined
    assert (s["sma_mid_period"], s["sma_long_period"]) == (50, 200)
    # The Oct 2024 1:1 bonus must not show as a 50% crash in the split-adjusted series.
    closes = [p["close"] for p in s["points"]]
    assert max(abs(b / a - 1) for a, b in pairwise(closes)) < 0.15


def test_unknown_ticker_and_auth(client: TestClient, admin: User) -> None:
    h = auth_header(client, admin.email)
    assert client.get("/technical/INFY.NS", headers=h).status_code == 404
    assert client.get("/technical/AAPL", headers=h).status_code == 422
    assert client.get(f"/technical/{REL}").status_code == 401
    naive = client.get(f"/technical/{REL}", headers=h, params={"as_of": "2024-01-01T00:00:00"})
    assert naive.status_code == 422
