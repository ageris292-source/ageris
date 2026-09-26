"""Probability source backed by the model registry (used by the Trade Risk
Engine). Returns None — i.e. UNKNOWN at the gates — whenever it cannot give
an honest, point-in-time, calibrated estimate."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest import walkforward as wf
from app.backtest.data import load_benchmark, load_stock
from app.backtest.features import FEATURE_VERSION, FEATURES, build_features
from app.models import ModelMonitorRun, ModelVersion, Stock
from app.trade.probability import ProbabilityEstimate

log = logging.getLogger(__name__)
_cache: dict[tuple[int, str], dict[str, wf.CalibratedModel]] = {}


def active_model(db: Session, horizon: int, as_of: datetime) -> ModelVersion | None:
    return db.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.status == "active",
            ModelVersion.horizon == horizon,
            ModelVersion.valid_from <= as_of,
        )
        .order_by(ModelVersion.valid_from.desc(), ModelVersion.id.desc())
        .limit(1)
    )


def _models(mv: ModelVersion) -> dict[str, wf.CalibratedModel] | None:
    digest = hashlib.sha256(mv.artifact).hexdigest()
    if digest != mv.artifact_sha256:  # checked on every use, cache or not
        log.error("model %s artifact hash mismatch: refusing to use it", mv.id)
        return None
    key = (mv.id, digest)
    if key not in _cache:
        raw = json.loads(mv.artifact)
        _cache[key] = {t: wf.CalibratedModel.load(raw[t]) for t in wf.TARGETS}
    return _cache[key]


def monitor_blocked(db: Session, mv: ModelVersion, as_of: datetime) -> bool:
    """True if the model's latest monitoring result at as_of is FAIL. Such a
    model is never used, even if auto-disable is switched off (fail closed)."""
    status = db.scalar(
        select(ModelMonitorRun.status)
        .where(ModelMonitorRun.model_id == mv.id, ModelMonitorRun.as_of <= as_of)
        .order_by(ModelMonitorRun.as_of.desc(), ModelMonitorRun.id.desc())
        .limit(1)
    )
    return status == "FAIL"


def predict(
    db: Session, mv: ModelVersion, stock: Stock, as_of: datetime
) -> tuple[date, float, float] | None:
    """(feature session, P(profit), P(outperform)) from data known at as_of."""
    if mv.feature_version != FEATURE_VERSION or mv.features != FEATURES:
        return None
    models = _models(mv)
    if models is None:
        return None
    s = load_stock(db, stock, as_of, None, years=3)
    bench = load_benchmark(db, as_of, None)
    if s.close.empty or bench.empty:
        return None
    feats = build_features(s.close, s.volume, bench)
    last = feats.iloc[[-1]]
    if last.isna().any(axis=None):
        return None
    p_profit = float(models["y_profit"].predict(last)[0])
    p_out = float(models["y_outperform"].predict(last)[0])
    return last.index[-1].date(), p_profit, p_out


def estimate(
    db: Session, stock: Stock, as_of: datetime, horizon: int
) -> ProbabilityEstimate | None:
    mv = active_model(db, horizon, as_of)
    if mv is None or monitor_blocked(db, mv, as_of):
        return None
    pred = predict(db, mv, stock, as_of)
    if pred is None:
        return None
    session, p_profit, p_out = pred
    expected = wf.lookup_expected(mv.expected_return_map, p_profit)
    if expected is None:
        return None
    return ProbabilityEstimate(
        model_id=mv.name,
        horizon_days=horizon,
        as_of_date=session,
        p_profit=p_profit,
        p_outperform=p_out,
        expected_return=expected,
        calibrated=True,
        calibration_error=mv.calibration_error,
        oos_periods=mv.oos_periods,
    )
