"""Phase 13: model monitoring — PSI drift against training data, calibration
decay on realised outcomes, auto-disable, admin API."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_now
from app.backtest.data import load_stock
from app.backtest.features import FEATURES
from app.backtest.service import label_cost, run_backtest, set_status
from app.core.config_file import get_config
from app.main import app
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import Alert, AuditLog, ModelMonitorRun, ModelPrediction, ModelVersion, User
from app.monitoring import service as mon
from app.trade import context as trade_context
from app.trade.schemas import TradeProposal
from tests.conftest import auth_header
from tests.market_helpers import NOW
from tests.test_backtest import CAL, _seed

CFG = get_config()
RULES = CFG.monitoring
H = 20


# ---------------------------------------------------------------------- PSI --


def test_psi_hand_worked_and_reference_bins() -> None:
    assert mon.psi(np.array([0.25] * 4), np.array([0.25] * 4)) == 0.0
    # 0.4 * ln(1.8) + (-0.4) * ln(0.2)
    assert mon.psi(np.array([0.5, 0.5]), np.array([0.9, 0.1])) == pytest.approx(
        0.4 * np.log(1.8) + 0.4 * np.log(5), rel=1e-12
    )
    assert np.isfinite(mon.psi(np.array([0.5, 0.5]), np.array([1.0, 0.0])))  # empty bin
    rng = np.random.default_rng(3)
    df = pd.DataFrame(rng.uniform(size=(5000, len(FEATURES))), columns=FEATURES)
    df["date"] = np.repeat(pd.bdate_range("2020-01-01", periods=1000), 5)
    ref = mon.feature_reference(df, 10, 60)
    r = ref["features"]["ret_5"]
    assert len(r["edges"]) == 9 and np.allclose(r["props"], 0.1, atol=0.002)
    assert r["null_windows"] >= mon.MIN_NULL_WINDOWS
    assert 0 < r["null_psi_q95"] <= r["null_psi_q99"]


def _synthetic(shift: float, n_dates: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(rng.normal(size=(n_dates * 4, len(FEATURES))) + shift, columns=FEATURES)
    df["date"] = np.repeat(pd.bdate_range("2019-01-01", periods=n_dates), 4)
    return df


def test_drift_is_judged_against_normal_variation() -> None:
    mv = ModelVersion(feature_reference=mon.feature_reference(_synthetic(0, 800, 1), 10, 60))
    same = mon.drift(mv, _synthetic(0, 60, 2)[FEATURES], RULES)
    assert same["status"] == "PASS" and same["samples"] == 240
    moved = mon.drift(mv, _synthetic(1.5, 60, 3)[FEATURES], RULES)
    assert (
        moved["status"] == "FAIL" and "drifted beyond their normal variation" in moved["reasons"][0]
    )
    assert all(f["status"] == "FAIL" for f in moved["features"])
    one = _synthetic(0, 60, 4)[FEATURES]
    one["ret_5"] += 3
    single = mon.drift(mv, one, RULES)
    assert single["status"] == "WARN" and single["features"][0]["feature"] == "ret_5"
    few = mon.drift(mv, _synthetic(0, 10, 5)[FEATURES], RULES)
    assert few["status"] == "UNKNOWN"  # too little current data: never a PASS
    assert mon.drift(ModelVersion(feature_reference=None), one, RULES)["status"] == "FAIL"
    short = ModelVersion(feature_reference=mon.feature_reference(_synthetic(0, 80, 6), 10, 60))
    assert mon.drift(short, one, RULES)["status"] == "UNKNOWN"  # threshold not calibratable


# ---------------------------------------------------------------- end to end --


@pytest.fixture
def model(db: Session) -> Iterator[ModelVersion]:
    _seed(db)
    run_backtest(db, H, None, as_of=NOW)
    mv = db.scalars(select(ModelVersion)).one()
    set_status(db, mv, "active", None)
    yield mv


def _log_past_predictions(db: Session, mv: ModelVersion, p: float | None) -> float:
    """Simulate predictions logged at past sessions (60 per stock, all with
    closed label windows). p=None: predict each stock's realised base rate.
    Returns the realised base rate, computed independently."""
    cost = label_cost(H)
    ys: list[float] = []
    rows: list[tuple[int, Any]] = []
    for t in ("TCS.NS", "INFY.NS", "WIPRO.NS"):
        stock = md.get_stock(db, Ticker.parse(t))
        close = load_stock(db, stock, NOW, None).close.to_numpy()
        dates = load_stock(db, stock, NOW, None).close.index
        for i in range(len(close) - 100, len(close) - 40):
            y = close[i + 1 + H] / close[i + 1] - 1 - cost > 0  # entry next close
            ys.append(float(y))
            rows.append((stock.id, dates[i].date()))
    base = float(np.mean(ys))
    for sid, session in rows:
        db.add(
            ModelPrediction(
                model_id=mv.id,
                stock_id=sid,
                session=session,
                predicted_at=CAL.session_close_utc(session) + timedelta(hours=1),
                horizon=H,
                p_profit=base if p is None else p,
                p_outperform=0.5,
            )
        )
    db.commit()
    return base


def test_healthy_model_passes_and_logs_predictions_point_in_time(
    db: Session, model: ModelVersion
) -> None:
    ref = model.feature_reference
    assert ref is not None and ref["window_sessions"] == RULES.drift_window_sessions
    assert set(ref["features"]) == set(FEATURES)
    base = _log_past_predictions(db, model, None)
    run = mon.run_monitoring(db, NOW)[0]
    assert run.predictions_logged == 3  # one per stock, today
    today = db.scalars(select(ModelPrediction).where(ModelPrediction.predicted_at == NOW)).all()
    assert {p.session for p in today} == {CAL.latest_completed_session(NOW, timedelta(hours=1))}
    c = run.calibration
    assert c["status"] == "PASS" and c["evaluated"] == 180 and c["pending"] == 3
    assert c["live_ece"] == pytest.approx(0.0, abs=1e-9)  # predicted exactly the realised rate
    assert c["base_rate"] == pytest.approx(base)
    assert run.drift["status"] in ("PASS", "WARN")  # stationary market: no FAIL
    assert run.status != "FAIL" and run.action == "none"
    db.refresh(model)
    assert model.status == "active"
    again = mon.run_monitoring(db, NOW)[0]
    assert again.predictions_logged == 0  # once per stock and session
    with pytest.raises(DBAPIError):  # evidence is immutable
        db.execute(text("UPDATE model_predictions SET p_profit = 0.99"))
        db.flush()
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE model_monitor_runs SET status = 'PASS'"))
        db.flush()
    db.rollback()


def test_calibration_decay_retires_the_model_and_blocks_the_engine(
    db: Session, model: ModelVersion
) -> None:
    base = _log_past_predictions(db, model, 0.95)  # confidently wrong
    run = mon.run_monitoring(db, NOW)[0]
    c = run.calibration
    assert c["status"] == "FAIL" and c["live_ece"] == pytest.approx(0.95 - base, abs=1e-9)
    assert c["decay"] == pytest.approx(c["live_ece"] - model.calibration_error)
    assert run.status == "FAIL" and run.action == "retired"
    db.refresh(model)
    assert model.status == "retired"
    alert = db.scalars(select(Alert).where(Alert.kind == "model.monitor_fail")).one()
    assert alert.severity == "critical" and "retired automatically" in alert.title
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"model.monitor", "model.auto_disabled", "model.retired"} <= actions
    p = TradeProposal(
        ticker="TCS.NS",
        side="buy",
        quantity=1,
        entry_price=Decimal("1000"),
        stop_loss=Decimal("900"),
        target=Decimal("1300"),
        horizon_days=H,
        portfolio_id=0,
    )
    ctx, _ = trade_context.build(db, p, NOW)
    assert ctx.probability is None  # no model -> UNKNOWN at gates 12-16 -> reject
    assert mon.run_monitoring(db, NOW) == []  # nothing active left to monitor


def test_failed_model_is_unusable_even_without_auto_disable(
    db: Session, model: ModelVersion, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = CFG.model_copy(update={"monitoring": RULES.model_copy(update={"auto_disable": False})})
    monkeypatch.setattr(mon, "get_config", lambda: keep)
    _log_past_predictions(db, model, 0.95)
    p = TradeProposal(
        ticker="TCS.NS",
        side="buy",
        quantity=1,
        entry_price=Decimal("1000"),
        stop_loss=Decimal("900"),
        target=Decimal("1300"),
        horizon_days=H,
        portfolio_id=0,
    )
    assert trade_context.build(db, p, NOW)[0].probability is not None
    run = mon.run_monitoring(db, NOW)[0]
    assert run.status == "FAIL" and run.action == "none"
    db.refresh(model)
    assert model.status == "active"
    assert trade_context.build(db, p, NOW)[0].probability is None  # fail closed
    # point in time: before the failing check, the model was still usable
    assert trade_context.build(db, p, NOW - timedelta(minutes=1))[0].probability is not None
    assert "FAILED monitoring" in db.scalars(select(Alert)).one().title


def test_model_without_training_reference_cannot_pass(db: Session, model: ModelVersion) -> None:
    db.execute(text("UPDATE model_versions SET feature_reference = NULL"))
    db.commit()
    db.refresh(model)
    run = mon.run_monitoring(db, NOW)[0]
    assert run.drift["status"] == "FAIL" and run.status == "FAIL" and run.action == "retired"
    assert run.calibration["status"] == "UNKNOWN"  # no matured outcomes yet


# ----------------------------------------------------------------------- API --


def test_monitoring_api_is_admin_only(
    client: TestClient, admin: User, analyst: User, db: Session, model: ModelVersion
) -> None:
    for method, path in (
        ("post", "/monitoring/run"),
        ("get", "/monitoring/overview"),
        ("get", "/monitoring/runs"),
        ("get", "/monitoring/runs/1"),
    ):
        assert getattr(client, method)(path).status_code == 401, path
        r = getattr(client, method)(path, headers=auth_header(client, analyst.email))
        assert r.status_code == 403, path
    app.dependency_overrides[get_now] = lambda: NOW
    try:
        h = auth_header(client, admin.email)
        _log_past_predictions(db, model, 0.95)
        runs = client.post("/monitoring/run", headers=h)
        assert runs.status_code == 201, runs.text
        (r,) = runs.json()
        assert r["status"] == "FAIL" and r["action"] == "retired" and r["model_status"] == "retired"
        ov = client.get("/monitoring/overview", headers=h).json()
        (m,) = ov["models"]
        assert m["model_id"] == model.id and m["monitorable"] and m["predictions"] == 183
        assert m["latest"]["id"] == r["id"] and ov["rules"]["auto_disable"] is True
        detail = client.get(f"/monitoring/runs/{r['id']}", headers=h).json()
        assert len(detail["drift"]["features"]) == len(FEATURES)
        assert detail["calibration"]["curve"]
        assert [x["id"] for x in client.get("/monitoring/runs", headers=h).json()] == [r["id"]]
        assert client.get("/monitoring/runs/999999", headers=h).status_code == 404
        assert db.query(ModelMonitorRun).count() == 1
    finally:
        app.dependency_overrides.clear()
