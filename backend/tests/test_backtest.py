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
    assert s["summary"]["average_turnover"] == pytest.approx(0.25)  # A in, then A out
    assert s["summary"]["profit_factor"] is None  # no losing trade
    assert s["summary"]["sortino"] is None  # no downside periods


# ----------------------------------------------------------- end to end --

CAL = get_calendar()
REASON = "Research only: universe lacks delisted names; accepted for paper testing."
LAST = CAL.latest_completed_session(NOW, timedelta(minutes=60))
DAYS = CAL.sessions(LAST - timedelta(days=1500), LAST)[-900:]


SKILL_TICKERS = ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"]
# Longer history with a real, learnable pattern: each stock follows persistent
# trends that flip at random, so past returns genuinely predict future ones.
SKILL_DAYS = CAL.sessions(LAST - timedelta(days=2200), LAST)[-1300:]


def _trend_returns(rng: np.random.Generator, n: int, market: np.ndarray) -> np.ndarray:
    drift = np.empty(n)
    d = 0.003
    for t in range(n):
        if rng.random() < 1 / 120:
            d = -d
        drift[t] = d
    return drift + 0.9 * market + rng.normal(0, 0.008, n)


def _seed(db: Session, n_stocks: int = 3, skill: bool = False) -> None:
    """Seed the benchmark and stocks. skill=False: pure noise (no model can
    have an edge). skill=True: trending stocks a model can learn."""
    days = SKILL_DAYS if skill else DAYS
    rng = np.random.default_rng(11)
    m = rng.normal(0.0003, 0.009, len(days))
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
            for d, v in zip(days, levels, strict=True)
        ],
        retrieved_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    for k, t in enumerate(SKILL_TICKERS[: 6 if skill else n_stocks]):
        stock = md.add_stock(db, Ticker.parse(t), None)
        rets = (
            _trend_returns(rng, len(days), m) if skill else 0.9 * m + rng.normal(0, 0.01, len(days))
        )
        closes = 1000 * np.cumprod(1 + rets)
        bars = [
            Bar(
                session=s,
                open=Decimal(f"{c:.2f}"),
                high=Decimal(f"{c * 1.004:.2f}"),
                low=Decimal(f"{c * 0.996:.2f}"),
                close=Decimal(f"{c:.2f}"),
                volume=3_000_000 + k,
            )
            for s, c in zip(days, closes, strict=True)
        ]
        batch = ProviderBatch(
            ticker=Ticker.parse(t),
            source="test",
            licensed=True,
            basis=PriceBasis.SPLIT_ADJUSTED,
            retrieved_at=NOW - timedelta(minutes=5),
            bars=bars,
        )
        md.ingest_batch(db, stock, batch, requested=(days[0], days[-1]), now=NOW)
    db.commit()


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()


@pytest.fixture
def lenient_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small synthetic markets give noisy calibration (ECE ~0.05-0.10 even
    for a model with real skill). To exercise the activation path, these
    tests allow ECE up to 0.12; production keeps the configured 0.05."""
    from app.backtest import service as bsvc

    cfg = get_config()
    loose = cfg.model_copy(
        update={
            "trade_gates": cfg.trade_gates.model_copy(update={"maximum_calibration_error": 0.12})
        }
    )
    monkeypatch.setattr(bsvc, "get_config", lambda: loose)


@pytest.mark.usefixtures("lenient_calibration")
def test_backtest_run_is_reproducible_and_registers_a_model(
    api: tuple[TestClient, dict[str, str]], db: Session, analyst: User
) -> None:
    client, h = api
    _seed(db, skill=True)
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
    # It shows real skill but the universe has survivorship bias: activation
    # needs a written reason, which is recorded (audit P1-2).
    m0 = next(m for m in models if m["id"] == mid)
    assert m0["validation"]["failed"] == ["survivorship"], m0["validation"]["failed"]
    assert m0["needs_override"] is True and m0["can_activate"] is False
    assert m0["skill"]["ci"]["brier_skill_vs_base_rate"][0] > 0
    assert client.post(f"/models/{mid}/activate", headers=h).status_code == 422
    assert (
        client.post(
            f"/models/{mid}/activate", headers=h, json={"override_reason": "too short"}
        ).status_code
        == 422
    )
    act = client.post(f"/models/{mid}/activate", headers=h, json={"override_reason": REASON})
    assert act.status_code == 200, act.text
    act = act.json()
    assert act["status"] == "active" and act["activation_override"] == REASON
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
    client.post(f"/models/{other}/activate", headers=h, json={"override_reason": REASON})
    status = {m["id"]: m["status"] for m in client.get("/models", headers=h).json()}
    assert status == {other: "active", mid: "retired"}
    assert client.post(f"/models/{mid}/activate", headers=h).status_code == 409


@pytest.mark.usefixtures("lenient_calibration")
def test_trade_engine_uses_the_active_model(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed(db, skill=True)
    run = client.post("/backtests", headers=h, json={"horizon": 20}).json()
    mid = client.get("/models", headers=h).json()[0]["id"]
    client.post(f"/models/{mid}/activate", headers=h, json={"override_reason": REASON})
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
    assert ctx.probability.inputs_licensed is True  # licensed stock and benchmark
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


def test_benchmark_licence_is_reported_per_window(db: Session) -> None:
    """An unlicensed benchmark observation inside the window makes the model's
    inputs unlicensed; licensed rows win when both versions exist (audit P0-4)."""
    _seed(db, n_stocks=1)
    start = DAYS[-30]
    assert ms.series_licensed(db, "nifty50", NOW, None, start) is True
    extra = DAYS[-1] + timedelta(days=1)
    while not CAL.is_session(extra):
        extra += timedelta(days=1)
    ms.store(
        db,
        [
            Obs(
                "nifty50",
                "daily",
                extra,
                20000.0,
                "points",
                "yahoo",
                False,
                None,
                CAL.session_close_utc(extra) + timedelta(hours=1),
                False,
            )
        ],
        retrieved_at=CAL.session_close_utc(extra) + timedelta(hours=1),
    )
    db.commit()
    later = CAL.session_close_utc(extra) + timedelta(hours=2)
    assert ms.series_licensed(db, "nifty50", later, None, start) is False
    assert ms.series_licensed(db, "nifty50", NOW, None, start) is True  # point in time
    assert ms.series_licensed(db, "nifty50", NOW, None, extra + timedelta(days=400)) is None


def test_a_model_without_skill_can_never_be_used(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    """Pure-noise market: the model may look calibrated but has no edge over
    the base rate. It is refused at activation, even with an override reason,
    and the engine ignores it even if forced active (audit P1-1/P1-2)."""
    from app.backtest.service import set_status

    client, h = api
    _seed(db)
    client.post("/backtests", headers=h, json={"horizon": 20})
    m = client.get("/models", headers=h).json()[0]
    v = m["validation"]
    assert v["passed"] is False and "beats_base_rate" in v["failed"]
    assert m["can_activate"] is False and m["needs_override"] is False
    r = client.post(f"/models/{m['id']}/activate", headers=h, json={"override_reason": REASON})
    assert r.status_code == 409 and "failed validation" in r.json()["detail"]
    mv = db.get(ModelVersion, m["id"])
    assert mv is not None
    set_status(db, mv, "active", None)  # bypass the API on purpose
    assert client.get("/models/estimate/TCS.NS", headers=h).json()["available"] is False


def test_skill_scores_hand_checked() -> None:
    from app.backtest.skill import brier_skill, validate

    y = np.array([0, 1, 1, 0, 1, 0, 1, 1])
    base = np.full(len(y), y.mean())
    assert brier_skill(base, base, y) == pytest.approx(0.0)
    perfect = y.astype(float)
    assert brier_skill(perfect, base, y) == pytest.approx(1.0)
    v = validate(
        None,
        calibration_error=0.01,
        max_calibration_error=0.05,
        oos_periods=6,
        min_oos_periods=4,
        survivorship_bias="LOW",
        min_brier_skill_lower=0.0,
        min_auc_lower=0.5,
        min_fold_skill_share=0.6,
    )
    assert v["passed"] is False and v["failed"] == ["skill_measured"]
