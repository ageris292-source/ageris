"""Phase 10: point-in-time features, leakage controls, walk-forward
calibration, simulation, reproducibility and the model registry."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_now
from app.backtest import walkforward as wf
from app.backtest.features import FEATURES, WARMUP_SESSIONS, build_features, forward_labels
from app.backtest.simulate import simulate
from app.core.config_file import get_config
from app.macro import service as ms
from app.macro.providers import Obs
from app.main import app
from app.market_data import service as md
from app.market_data.calendar import get_calendar
from app.market_data.types import Bar, PriceBasis, ProviderBatch, Ticker
from app.models import ModelVersion, User
from app.trade import context as trade_context
from app.trade.schemas import TradeProposal
from tests.conftest import auth_header
from tests.market_helpers import NOW

CFG = get_config()
RULES = CFG.backtest


def _walk(n: int, seed: int, drift: float = 0.0003, vol: float = 0.015) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(drift, vol, n)), index=idx)


# ------------------------------------------------------ point-in-time rules --


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 10_000), cut=st.integers(WARMUP_SESSIONS + 5, 590))
def test_features_never_look_ahead(seed: int, cut: int) -> None:
    close = _walk(600, seed)
    vol = pd.Series(np.random.default_rng(seed + 1).integers(1e5, 1e6, 600), index=close.index)
    bench = _walk(600, seed + 2, vol=0.01)
    full = build_features(close, vol, bench)
    truncated = build_features(close.iloc[: cut + 1], vol.iloc[: cut + 1], bench.iloc[: cut + 1])
    pd.testing.assert_series_equal(full.iloc[cut], truncated.iloc[-1], check_names=False)
    # changing the future does not change features at `cut`
    future = close.copy()
    future.iloc[cut + 1 :] *= 3
    pd.testing.assert_series_equal(
        build_features(future, vol, bench).iloc[cut], full.iloc[cut], check_names=False
    )


def test_labels_start_at_the_next_session() -> None:
    close = pd.Series(
        [100.0, 101, 102, 103, 104, 105], index=pd.bdate_range("2024-01-01", periods=6)
    )
    lab = forward_labels(close, close, horizon=2, round_trip_cost=0.0)
    assert lab["fwd_return"].iloc[0] == pytest.approx(103 / 101 - 1)  # entry t+1, exit t+3
    assert lab["fwd_return"].iloc[-3:].isna().all()
    assert lab["label_end_pos"].iloc[0] == 3
    changed = close.copy()
    changed.iloc[0] = 50  # the signal-day close does not enter the label
    assert forward_labels(changed, close, 2, 0.0)["fwd_return"].iloc[0] == lab["fwd_return"].iloc[0]


# ------------------------------------------------------ walk-forward & ECE --


def _synthetic(n_dates: int, tickers: int, signal: float, seed: int = 0) -> pd.DataFrame:
    """Pooled dataset where feature ret_20 predicts y with strength `signal`."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_dates)
    rows = []
    for k in range(tickers):
        x = rng.normal(size=(n_dates, len(FEATURES)))
        logit = signal * x[:, 1]
        y = (rng.random(n_dates) < 1 / (1 + np.exp(-logit))).astype(float)
        yo = (rng.random(n_dates) < 1 / (1 + np.exp(-logit))).astype(float)
        df = pd.DataFrame(x, columns=FEATURES)
        df["date"] = dates
        df["ticker"] = f"S{k}.NS"
        df["y_profit"], df["y_outperform"] = y, yo
        df["fwd_return"] = np.where(y == 1, 0.03, -0.02)
        df["bench_fwd_return"] = 0.0
        df["label_end_date"] = [dates[min(i + 21, n_dates - 1)] for i in range(n_dates)]
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def test_walk_forward_purges_overlapping_labels() -> None:
    res = wf.walk_forward(_synthetic(760, 3, 1.5), RULES)
    assert len(res.folds) >= 3
    for f in res.folds:
        assert f["train_last_label_end"] < f["test_start"]
    # OOS predictions come only from test windows, one fold per date
    assert res.predictions.groupby(["date", "ticker"]).size().max() == 1


def test_walk_forward_finds_real_signal_and_not_noise() -> None:
    sig = wf.walk_forward(_synthetic(760, 4, 2.0), RULES).predictions
    noise = wf.walk_forward(_synthetic(760, 4, 0.0, seed=1), RULES).predictions
    m_sig = wf.metrics(sig["p_profit"].to_numpy(), sig["y_profit"].to_numpy(), 10)
    m_noise = wf.metrics(noise["p_profit"].to_numpy(), noise["y_profit"].to_numpy(), 10)
    assert m_sig["auc"] > 0.75 and m_sig["ece"] < 0.06
    assert 0.44 < m_noise["auc"] < 0.56


def test_walk_forward_is_deterministic() -> None:
    d = _synthetic(700, 3, 1.0)
    a = wf.walk_forward(d, RULES).predictions
    b = wf.walk_forward(d, RULES).predictions
    pd.testing.assert_frame_equal(a, b)


def test_insufficient_history_is_refused() -> None:
    with pytest.raises(wf.InsufficientDataError):
        wf.walk_forward(_synthetic(300, 3, 1.0), RULES)


def test_ece_and_expected_return_map() -> None:
    p = np.array([0.05, 0.05, 0.95, 0.95])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    assert wf.ece(p, y, 10) == pytest.approx(0.05)
    assert wf.ece(np.full(4, 0.5), y, 10) == pytest.approx(0.0)
    pred = pd.DataFrame(
        {"p_profit": [0.72] * 40 + [0.15] * 10, "fwd_return": [0.05] * 40 + [-0.1] * 10}
    )
    m = wf.expected_return_map(pred, 10)
    assert len(m) == 1 and m[0]["mean_forward_return"] == pytest.approx(0.05)  # sparse bin dropped
    assert wf.lookup_expected(m, 0.75) == pytest.approx(0.05)
    assert wf.lookup_expected(m, 0.15) is None


def test_simulation_hand_worked() -> None:
    d = pd.bdate_range("2024-01-01", periods=4)
    pred = pd.DataFrame(
        {
            "date": [d[0], d[0], d[1], d[2], d[2], d[3]],
            "ticker": ["A", "B", "A", "A", "B", "A"],
            "p_profit": [0.9, 0.5, 0.99, 0.4, 0.3, 0.99],  # d1/d3 are not rebalance days
            "p_outperform": [0.8] * 6,
            "fwd_return": [0.10, 0.50, 9.9, 0.2, 0.2, 9.9],
            "bench_fwd_return": [0.01, 0.01, 0.0, 0.02, 0.02, 0.0],
        }
    )
    s = simulate(pred, horizon=2, top_k=2, min_p_profit=0.65, round_trip_cost=0.01, risk_free=0.0)
    p = s["periods"]
    assert p[0]["names"] == ["A"] and p[0]["strategy_return"] == pytest.approx((0.10 - 0.01) / 2)
    assert p[1]["names"] == [] and p[1]["strategy_return"] == 0.0  # NO TRADE period
    assert s["summary"]["no_trade_periods"] == 1 and s["summary"]["trades"] == 1
    assert s["summary"]["total_return"] == pytest.approx(0.045)
    assert s["summary"]["benchmark_total_return"] == pytest.approx(1.01 * 1.02 - 1)


# ----------------------------------------------------------- end to end --

CAL = get_calendar()
LAST = CAL.latest_completed_session(NOW, timedelta(minutes=60))
DAYS = CAL.sessions(LAST - timedelta(days=1500), LAST)[-900:]


def _seed(db: Session, n_stocks: int = 3) -> None:
    rng = np.random.default_rng(11)
    m = rng.normal(0.0003, 0.009, len(DAYS))
    levels = 20000 * np.cumprod(1 + m)
    ms.store(
        db,
        [
            Obs(
                "nifty50",
                "daily",
                d,
                float(v),
                "points",
                "test",
                True,
                None,
                CAL.session_close_utc(d) + timedelta(hours=1),
                False,
            )
            for d, v in zip(DAYS, levels, strict=True)
        ],
        retrieved_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    for k, t in enumerate(["TCS.NS", "INFY.NS", "WIPRO.NS"][:n_stocks]):
        stock = md.add_stock(db, Ticker.parse(t), None)
        closes = 1000 * np.cumprod(1 + 0.9 * m + rng.normal(0, 0.01, len(DAYS)))
        bars = [
            Bar(
                session=s,
                open=Decimal(f"{c:.2f}"),
                high=Decimal(f"{c * 1.004:.2f}"),
                low=Decimal(f"{c * 0.996:.2f}"),
                close=Decimal(f"{c:.2f}"),
                volume=3_000_000 + k,
            )
            for s, c in zip(DAYS, closes, strict=True)
        ]
        batch = ProviderBatch(
            ticker=Ticker.parse(t),
            source="test",
            licensed=True,
            basis=PriceBasis.SPLIT_ADJUSTED,
            retrieved_at=NOW - timedelta(minutes=5),
            bars=bars,
        )
        md.ingest_batch(db, stock, batch, requested=(DAYS[0], DAYS[-1]), now=NOW)
    db.commit()


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()


def test_backtest_run_is_reproducible_and_registers_a_model(
    api: tuple[TestClient, dict[str, str]], db: Session, analyst: User
) -> None:
    client, h = api
    _seed(db)
    assert (
        client.post("/backtests", headers=auth_header(client, analyst.email), json={}).status_code
        == 403
    )
    r1 = client.post("/backtests", headers=h, json={"horizon": 20})
    assert r1.status_code == 201, r1.text
    a = r1.json()
    assert a["status"] == "completed", a["error"]
    assert a["survivorship_bias"] == "HIGH" and any("survivorship" in w for w in a["warnings"])
    rep = a["reproducibility"]
    assert rep["seed"] == RULES.seed and "lightgbm" in rep["libraries"] and rep["data_hash"]
    assert a["metrics"]["folds_trained"] >= 1
    for f in a["folds"]:
        if not f.get("skipped"):
            assert f["train_last_label_end"] < f["test_start"]  # purged
    b = client.post("/backtests", headers=h, json={"horizon": 20}).json()
    assert b["data_hash"] == a["data_hash"]
    assert b["metrics"]["profit"] == a["metrics"]["profit"]  # bit-for-bit reproducible
    assert b["simulation"]["summary"] == a["simulation"]["summary"]
    assert (
        client.post(
            "/backtests", headers=h, json={"as_of": (NOW + timedelta(days=2)).isoformat()}
        ).status_code
        == 422
    )

    models = client.get("/models", headers=h).json()
    assert len(models) == 2 and all(m["status"] == "candidate" for m in models)
    mid = models[-1]["id"]
    # candidates are never used
    assert client.get("/models/estimate/TCS.NS", headers=h).json()["available"] is False
    assert (
        client.post(
            f"/models/{mid}/activate", headers=auth_header(client, analyst.email)
        ).status_code
        == 403
    )
    act = client.post(f"/models/{mid}/activate", headers=h).json()
    assert act["status"] == "active"
    est = client.get("/models/estimate/TCS.NS", headers=h).json()
    assert est["available"] is True and 0 <= est["p_profit"] <= 1
    assert est["oos_periods"] == a["metrics"]["folds_trained"]
    # point in time: a model is never applied before its valid_from date
    early = (datetime.fromisoformat(act["valid_from"]) - timedelta(days=30)).replace(tzinfo=UTC)
    assert (
        client.get(
            "/models/estimate/TCS.NS", headers=h, params={"as_of": early.isoformat()}
        ).json()["available"]
        is False
    )
    # activating the other model retires this one
    other = models[0]["id"]
    client.post(f"/models/{other}/activate", headers=h)
    status = {m["id"]: m["status"] for m in client.get("/models", headers=h).json()}
    assert status == {other: "active", mid: "retired"}
    assert client.post(f"/models/{mid}/activate", headers=h).status_code == 409


def test_trade_engine_uses_the_active_model(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed(db)
    run = client.post("/backtests", headers=h, json={"horizon": 20}).json()
    mid = client.get("/models", headers=h).json()[0]["id"]
    client.post(f"/models/{mid}/activate", headers=h)
    pid = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "1000000"}
    ).json()["id"]
    p = TradeProposal(
        ticker="TCS.NS",
        side="buy",
        quantity=1,
        entry_price=Decimal("1000"),
        stop_loss=Decimal("900"),
        target=Decimal("1300"),
        horizon_days=20,
        portfolio_id=pid,
    )
    ctx, _ = trade_context.build(db, p, NOW)
    assert ctx.probability is not None and ctx.probability.model_id.endswith(f"run{run['id']}")
    wrong_h, _ = trade_context.build(db, p.model_copy(update={"horizon_days": 10}), NOW)
    assert wrong_h.probability is None  # no model for that horizon -> UNKNOWN at the gates
    # a tampered artifact is refused
    db.execute(text("UPDATE model_versions SET artifact = artifact || '\\x00'::bytea"))
    db.commit()
    tampered, _ = trade_context.build(db, p, NOW)
    assert tampered.probability is None


def test_backtest_fails_cleanly_without_benchmark(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    client.post("/stocks", headers=h, json={"ticker": "TCS.NS"})
    r = client.post("/backtests", headers=h, json={}).json()
    assert r["status"] == "failed" and "benchmark" in r["error"]
    assert db.query(ModelVersion).count() == 0


def test_backtest_endpoints_need_auth(client: TestClient) -> None:
    assert client.post("/backtests", json={}).status_code == 401
    for p in ("/backtests", "/backtests/1", "/models", "/models/estimate/TCS.NS"):
        assert client.get(p).status_code == 401


def test_universe_counts_each_company_once(db: Session) -> None:
    from app.backtest.data import universe

    for t in ("INFY.BO", "INFY.NS", "TCS.BO"):
        md.add_stock(db, Ticker.parse(t), None)
    got = [(s.symbol, s.exchange) for s in universe(db, None)]
    assert got == [("INFY", "NSE"), ("TCS", "BSE")]
