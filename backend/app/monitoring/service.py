"""Model monitoring (spec §27): feature drift against the model's own
training data (population stability index), calibration decay on the
realised outcomes of its own logged predictions, and auto-disable.

Fail closed: a model that cannot be monitored (no training reference) is a
FAIL, never a PASS. Too little current data or too few matured outcomes is
UNKNOWN, and UNKNOWN is never reported as healthy.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.alerts.service import raise_alert
from app.backtest import registry
from app.backtest import walkforward as wf
from app.backtest.data import load_benchmark, load_stock, universe
from app.backtest.features import FEATURES, build_features, forward_labels
from app.core.config_file import MonitoringRules, get_config
from app.models import ModelMonitorRun, ModelPrediction, ModelVersion, Stock
from app.risk.service import ist_date
from app.services.audit import record_audit

REFERENCE_VERSION = "psi-quantiles-null-1"
MIN_NULL_WINDOWS = 20  # training windows needed to calibrate a drift threshold
_EPS = 1e-4  # floor for empty bins so PSI stays finite
_ORDER = {"PASS": 0, "WARN": 1, "UNKNOWN": 2, "FAIL": 3}


# ------------------------------------------------------------------ drift (PSI) --


def _proportions(v: np.ndarray, edges: list[float]) -> np.ndarray:
    idx = np.searchsorted(np.asarray(edges, dtype=float), v, side="right")
    counts: np.ndarray = np.bincount(idx, minlength=len(edges) + 1).astype(float)
    total = counts.sum()
    return counts / total if total else counts


def feature_reference(x: pd.DataFrame, bins: int, window: int) -> dict[str, Any]:
    """Quantile bin edges and proportions of every feature in the training
    data, plus the null distribution of PSI: the PSI of every `window`-session
    stretch of the training data itself against the whole. Slow features
    (200-day distance, 120-day beta, benchmark regime) are strongly
    autocorrelated, so a short window differs from the full history even when
    nothing has changed; drift is only flagged beyond that normal variation."""
    dates = pd.Index(sorted(pd.unique(x["date"]))) if "date" in x else pd.Index([])
    stride = max(1, window // 4)
    starts = range(0, max(0, len(dates) - window + 1), stride)
    windows = [x["date"].isin(dates[i : i + window]).to_numpy() for i in starts]
    feats: dict[str, Any] = {}
    for f in FEATURES:
        v = x[f].to_numpy(dtype=float)
        ok = np.isfinite(v)
        if not ok.any():
            continue
        inner = np.quantile(v[ok], np.linspace(0, 1, bins + 1)[1:-1])
        edges = [float(e) for e in np.unique(inner)]
        props = _proportions(v[ok], edges)
        null = [psi(props, _proportions(v[m & ok], edges)) for m in windows if (m & ok).any()]
        feats[f] = {
            "edges": edges,
            "props": [float(p) for p in props],
            "null_psi_q95": float(np.quantile(null, 0.95)) if null else None,
            "null_psi_q99": float(np.quantile(null, 0.99)) if null else None,
            "null_windows": len(null),
        }
    return {
        "version": REFERENCE_VERSION,
        "bins": bins,
        "window_sessions": window,
        "rows": len(x),
        "features": feats,
    }


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    """Population stability index: sum((a - e) * ln(a / e))."""
    e = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), _EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def current_features(db: Session, as_of: datetime, window: int) -> pd.DataFrame:
    """Features of the last `window` sessions of every stock, from data known
    at as_of, pooled across the universe."""
    bench = load_benchmark(db, as_of, None)
    if bench.empty:
        return pd.DataFrame(columns=FEATURES)
    frames = []
    for stock in universe(db, None):
        s = load_stock(db, stock, as_of, None, years=2)
        if s.close.empty:
            continue
        frames.append(build_features(s.close, s.volume, bench).tail(window).dropna())
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames) if frames else pd.DataFrame(columns=FEATURES)


def drift(mv: ModelVersion, cur: pd.DataFrame, rules: MonitoringRules) -> dict[str, Any]:
    ref = mv.feature_reference
    if not ref or ref.get("version") != REFERENCE_VERSION:
        return {
            "status": "FAIL",
            "reasons": ["model has no training feature reference: it cannot be monitored"],
            "samples": len(cur),
            "features": [],
        }
    if len(cur) < rules.min_drift_samples:
        return {
            "status": "UNKNOWN",
            "reasons": [
                f"only {len(cur)} current feature rows (need {rules.min_drift_samples}): "
                "drift cannot be measured"
            ],
            "samples": len(cur),
            "features": [],
        }
    rows: list[dict[str, Any]] = []
    for f in FEATURES:
        r = ref["features"].get(f)
        if r is None:
            rows.append({"feature": f, "psi": None, "status": "UNKNOWN"})
            continue
        v = pd.to_numeric(cur[f], errors="coerce").to_numpy(dtype=float)
        value = psi(np.array(r["props"]), _proportions(v[np.isfinite(v)], r["edges"]))
        q95, q99 = r.get("null_psi_q95"), r.get("null_psi_q99")
        if q95 is None or q99 is None or r.get("null_windows", 0) < MIN_NULL_WINDOWS:
            rows.append({"feature": f, "psi": value, "status": "UNKNOWN"})
            continue
        fail_at, warn_at = max(rules.psi_fail, q99), max(rules.psi_warn, q95)
        st = "FAIL" if value >= fail_at else "WARN" if value >= warn_at else "PASS"
        rows.append(
            {"feature": f, "psi": value, "status": st, "warn_at": warn_at, "fail_at": fail_at}
        )
    fails = [r["feature"] for r in rows if r["status"] == "FAIL"]
    warns = [r["feature"] for r in rows if r["status"] == "WARN"]
    unknown = [r["feature"] for r in rows if r["status"] == "UNKNOWN"]
    reasons: list[str] = []
    if len(fails) >= rules.min_drifted_features_to_fail:
        status = "FAIL"
        reasons.append(
            f"{len(fails)} features drifted beyond their normal variation: {', '.join(fails)}"
        )
    elif unknown:
        status = "UNKNOWN"
        reasons.append(
            f"no calibrated drift threshold for {', '.join(unknown)} "
            f"(training history shorter than {MIN_NULL_WINDOWS} windows)"
        )
    elif fails or len(warns) >= rules.min_drifted_features_to_fail:
        # A single feature above its 95th percentile happens by chance most
        # days across 18 features; only flag what is unusual for the model.
        status = "WARN"
        reasons.append(f"moderate drift in {', '.join(fails + warns)}")
    else:
        status = "PASS"
    return {
        "status": status,
        "reasons": reasons,
        "samples": len(cur),
        "max_psi": max((r["psi"] for r in rows if r["psi"] is not None), default=None),
        "features": sorted(rows, key=lambda r: -(r["psi"] or 0)),
    }


# ------------------------------------------------------------ predictions log --


def record_predictions(db: Session, mv: ModelVersion, as_of: datetime) -> int:
    """Log the model's prediction for every stock at as_of (once per stock
    and feature session). Returns the number of new rows."""
    n = 0
    for stock in universe(db, None):
        pred = registry.predict(db, mv, stock, as_of)
        if pred is None:
            continue
        session, p_profit, p_out = pred
        ids = db.scalars(
            insert(ModelPrediction)
            .values(
                model_id=mv.id,
                stock_id=stock.id,
                session=session,
                predicted_at=as_of,
                horizon=mv.horizon,
                p_profit=p_profit,
                p_outperform=p_out,
            )
            .on_conflict_do_nothing(constraint="uq_model_prediction")
            .returning(ModelPrediction.id)
        ).all()
        n += len(ids)
    db.flush()
    return n


# -------------------------------------------------------------- calibration --


def realised_outcomes(
    db: Session, mv: ModelVersion, now: datetime
) -> tuple[list[tuple[date, float, float]], int]:
    """(session, P(profit), realised y_profit) for every logged prediction
    whose label window has closed by `now`, newest first; plus the number
    still pending. Labels use the exact training definition and costs."""
    from app.backtest.service import label_cost

    preds = db.scalars(
        select(ModelPrediction).where(
            ModelPrediction.model_id == mv.id, ModelPrediction.predicted_at <= now
        )
    ).all()
    by_stock: dict[int, list[ModelPrediction]] = defaultdict(list)
    for p in preds:
        by_stock[p.stock_id].append(p)
    bench = load_benchmark(db, now, None)
    cost = label_cost(mv.horizon)
    matured: list[tuple[date, float, float]] = []
    pending = 0
    for stock_id, ps in by_stock.items():
        stock = db.get(Stock, stock_id)
        assert stock is not None
        oldest = min(p.session for p in ps)
        years = max(1, math.ceil((ist_date(now) - oldest).days / 365) + 1)
        s = load_stock(db, stock, now, None, years=years)
        lab = forward_labels(s.close, bench, mv.horizon, cost) if not s.close.empty else None
        for p in ps:
            ts = pd.Timestamp(p.session)
            y = lab["y_profit"].get(ts) if lab is not None else None
            if y is None or pd.isna(y):
                pending += 1
                continue
            matured.append((p.session, p.p_profit, float(y)))
    matured.sort(key=lambda m: m[0], reverse=True)
    return matured, pending


def calibration(
    db: Session, mv: ModelVersion, now: datetime, rules: MonitoringRules
) -> dict[str, Any]:
    cfg = get_config()
    matured, pending = realised_outcomes(db, mv, now)
    window = matured[: rules.calibration_window_predictions]
    base: dict[str, Any] = {
        "matured": len(matured),
        "pending": pending,
        "evaluated": len(window),
        "backtest_ece": mv.calibration_error,
    }
    if len(window) < rules.min_matured_predictions:
        return {
            **base,
            "status": "UNKNOWN",
            "reasons": [
                f"{len(window)} matured predictions (need {rules.min_matured_predictions}): "
                "awaiting realised outcomes"
            ],
        }
    p = np.array([m[1] for m in window])
    y = np.array([m[2] for m in window])
    bins = cfg.backtest.calibration_bins
    m = wf.metrics(p, y, bins)
    live = float(m["ece"] or 0.0)
    decay = live - mv.calibration_error
    reasons: list[str] = []
    if live > rules.max_live_calibration_error:
        reasons.append(
            f"live calibration error {live:.3f} exceeds {rules.max_live_calibration_error:.3f}"
        )
    if decay > rules.max_calibration_decay:
        reasons.append(
            f"calibration decayed by {decay:.3f} vs the backtest "
            f"({mv.calibration_error:.3f} -> {live:.3f}; max {rules.max_calibration_decay:.3f})"
        )
    if reasons:
        status = "FAIL"
    elif live > cfg.trade_gates.maximum_calibration_error:
        status = "WARN"
        reasons.append(
            f"live calibration error {live:.3f} is above the trade-gate maximum "
            f"{cfg.trade_gates.maximum_calibration_error:.3f}"
        )
    else:
        status = "PASS"
    return {
        **base,
        "status": status,
        "reasons": reasons,
        "live_ece": live,
        "decay": decay,
        "brier": m["brier"],
        "auc": m["auc"],
        "base_rate": m["base_rate"],
        "mean_predicted": float(p.mean()),
        "window_start": str(window[-1][0]),
        "window_end": str(window[0][0]),
        "curve": wf.calibration_curve(p, y, bins),
    }


# ---------------------------------------------------------------------- run --


def active_models(db: Session, as_of: datetime) -> list[ModelVersion]:
    return list(
        db.scalars(
            select(ModelVersion)
            .where(ModelVersion.status == "active", ModelVersion.valid_from <= as_of)
            .order_by(ModelVersion.horizon, ModelVersion.id)
        )
    )


def monitor_model(
    db: Session,
    mv: ModelVersion,
    now: datetime,
    user_id: uuid.UUID | None,
    current: pd.DataFrame | None = None,
) -> ModelMonitorRun:
    from app.backtest.service import set_status

    cfg = get_config()
    rules = cfg.monitoring
    logged = record_predictions(db, mv, now)
    cur = current if current is not None else current_features(db, now, rules.drift_window_sessions)
    d = drift(mv, cur, rules)
    c = calibration(db, mv, now, rules)
    status = max(d["status"], c["status"], key=_ORDER.__getitem__)
    reasons = [f"drift: {r}" for r in d["reasons"]] + [f"calibration: {r}" for r in c["reasons"]]
    retire = status == "FAIL" and rules.auto_disable
    run = ModelMonitorRun(
        as_of=now,
        model_id=mv.id,
        status=status,
        drift=d,
        calibration={k: v for k, v in c.items()},
        predictions_logged=logged,
        reasons=reasons,
        action="retired" if retire else "none",
        config_fingerprint=cfg.fingerprint(),
    )
    db.add(run)
    db.flush()
    record_audit(
        db,
        action="model.monitor",
        actor_user_id=user_id,
        entity_type="model_version",
        entity_id=str(mv.id),
        details={"run": run.id, "status": status, "action": run.action, "reasons": reasons},
    )
    day = ist_date(now).isoformat()
    if status == "FAIL":
        what = "retired automatically" if retire else "FAILED monitoring (not usable)"
        raise_alert(
            db,
            kind="model.monitor_fail",
            severity="critical",
            title=f"Model {mv.name} {what}",
            body="; ".join(reasons)
            + ". Until a healthy model is activated by an admin, the engine has no "
            "probability for this horizon and rejects every entry.",
            dedupe_key=f"monitor:{mv.id}:fail:{day}",
            link="/monitoring",
        )
    elif status == "WARN" or d["status"] == "UNKNOWN":
        raise_alert(
            db,
            kind="model.monitor_warn",
            severity="warning",
            title=f"Model {mv.name}: monitoring {status}",
            body="; ".join(reasons) or "see the monitoring page",
            dedupe_key=f"monitor:{mv.id}:{status.lower()}:{day}",
            link="/monitoring",
        )
    if retire:
        record_audit(
            db,
            action="model.auto_disabled",
            actor_user_id=None,
            entity_type="model_version",
            entity_id=str(mv.id),
            details={"monitor_run": run.id, "reasons": reasons},
        )
        set_status(db, mv, "retired", None)  # audits and commits
    db.commit()
    return run


def run_monitoring(
    db: Session, now: datetime, user_id: uuid.UUID | None = None
) -> list[ModelMonitorRun]:
    """Check every active model. Current features are computed once."""
    models = active_models(db, now)
    if not models:
        return []
    cur = current_features(db, now, get_config().monitoring.drift_window_sessions)
    return [monitor_model(db, mv, now, user_id, cur) for mv in models]


__all__ = [
    "REFERENCE_VERSION",
    "calibration",
    "current_features",
    "drift",
    "feature_reference",
    "monitor_model",
    "psi",
    "record_predictions",
    "run_monitoring",
]
