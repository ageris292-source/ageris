"""Run a reproducible walk-forward backtest and register the resulting model."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import uuid
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any

from sqlalchemy.orm import Session

from app import __version__
from app.backtest import walkforward as wf
from app.backtest.data import build_dataset, data_hash, load_benchmark, load_stock, universe
from app.backtest.features import FEATURE_VERSION, FEATURES
from app.backtest.simulate import simulate
from app.core.config_file import get_config
from app.market_data.calendar import get_calendar
from app.market_data.service import ticker_of
from app.models import BacktestRun, ModelVersion
from app.monitoring.service import feature_reference
from app.services.audit import record_audit
from app.trade.costs import round_trip

ENGINE_VERSION = "backtest-engine-1.0.0"
SURVIVORSHIP_NOTE = (
    "Universe = stocks currently in the database (today's listings). Delisted and "
    "removed companies are missing, so results are biased upward (survivorship bias: HIGH)."
)


def label_cost(horizon: int) -> float:
    cfg = get_config()
    name = cfg.trade_engine.cost_schedule
    # a typical small order: 0.01% of average daily traded value
    return round_trip(name, cfg.transaction_costs[name], 1e6, 1e10, horizon).round_trip_fraction


def _libs() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for lib in ("lightgbm", "scikit-learn", "numpy", "pandas"):
        out[lib] = version(lib)
    return out


def run_backtest(
    db: Session,
    horizon: int,
    user_id: uuid.UUID | None,
    as_of: datetime | None = None,
    knowledge_at: datetime | None = None,
    tickers: list[str] | None = None,
) -> BacktestRun:
    cfg = get_config()
    rules = cfg.backtest
    at = as_of or datetime.now(UTC)
    k_at = knowledge_at or datetime.now(UTC)
    t0 = time.perf_counter()
    stocks = universe(db, tickers)
    cost = label_cost(horizon)
    params: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "feature_version": FEATURE_VERSION,
        "features": FEATURES,
        "horizon": horizon,
        "label": "entry at next session close, exit horizon sessions later",
        "label_round_trip_cost": cost,
        "min_p_profit": cfg.trade_gates.minimum_probability_of_profit,
        **rules.model_dump(),
    }
    run = BacktestRun(
        requested_by=user_id,
        status="running",
        horizon=horizon,
        as_of=at,
        knowledge_at=k_at,
        universe=[str(ticker_of(s)) for s in stocks],
        params=params,
        reproducibility={},
        config_fingerprint=cfg.fingerprint(),
        survivorship_bias="HIGH",
        warnings=[SURVIVORSHIP_NOTE],
    )
    db.add(run)
    db.commit()
    try:
        data = [load_stock(db, s, at, k_at) for s in stocks]
        data = [d for d in data if len(d.close)]
        bench = load_benchmark(db, at, k_at)
        if bench.empty:
            raise wf.InsufficientDataError("no benchmark (NIFTY 50) history: run macro ingest")
        run.data_hash = data_hash(data, bench)
        warnings = list(run.warnings)
        if any(d.licensed is False for d in data):
            warnings.append("Some prices are from unlicensed sources: research use only")
        ds = build_dataset(data, bench, horizon, cost)
        if ds.empty:
            raise wf.InsufficientDataError("not enough history to build features")
        res = wf.walk_forward(ds, rules)
        pred = res.predictions
        bins = rules.calibration_bins
        m_profit = wf.metrics(pred["p_profit"].to_numpy(), pred["y_profit"].to_numpy(), bins)
        m_out = wf.metrics(pred["p_outperform"].to_numpy(), pred["y_outperform"].to_numpy(), bins)
        sim = simulate(
            pred,
            horizon,
            rules.top_k,
            cfg.trade_gates.minimum_probability_of_profit,
            cost,
            cfg.valuation.risk_free_rate,
        )
        er_map = wf.expected_return_map(pred, bins)
        run.metrics = {
            "profit": m_profit,
            "outperform": m_out,
            "calibration_curve_profit": wf.calibration_curve(
                pred["p_profit"].to_numpy(), pred["y_profit"].to_numpy(), bins
            ),
            "calibration_curve_outperform": wf.calibration_curve(
                pred["p_outperform"].to_numpy(), pred["y_outperform"].to_numpy(), bins
            ),
            "expected_return_map": er_map,
            "oos_rows": len(pred),
            "oos_start": str(pred["date"].min().date()),
            "oos_end": str(wf.last_date(pred["date"])),
            "folds_trained": len(res.folds),
            "folds_skipped": len(res.skipped_folds),
            "rows_total": len(ds),
        }
        run.folds = [*res.folds, *[{**f, "skipped": True} for f in res.skipped_folds]]
        run.simulation = sim
        if (
            m_profit["ece"] is not None
            and m_profit["ece"] > cfg.trade_gates.maximum_calibration_error
        ):
            warnings.append(
                f"OOS calibration error {m_profit['ece']:.3f} exceeds the trade-gate maximum "
                f"{cfg.trade_gates.maximum_calibration_error:.3f}: the model cannot pass gate 12"
            )
        if len(res.folds) < cfg.trade_gates.minimum_out_of_sample_periods:
            warnings.append("Fewer OOS folds than the trade-gate minimum")

        # Final model on everything labelled by the cut-off.
        labelled = ds.dropna(subset=[*FEATURES, *wf.TARGETS])
        final = {t: wf.fit_calibrated(labelled, t, rules) for t in wf.TARGETS}
        blob = json.dumps({t: m.dump() for t, m in final.items()}, sort_keys=True).encode()
        cal = get_calendar(cfg.market_data.calendar)
        valid_from = cal.session_close_utc(wf.last_date(labelled["label_end_date"])) + timedelta(
            minutes=cfg.market_data.eod_availability_lag_minutes
        )
        db.add(
            ModelVersion(
                backtest_run_id=run.id,
                name=f"lgbm-h{horizon}-run{run.id}",
                horizon=horizon,
                feature_version=FEATURE_VERSION,
                features=FEATURES,
                status="candidate",
                valid_from=valid_from,
                trained_rows=len(labelled),
                calibration_error=float(m_profit["ece"] or 1.0),
                oos_periods=len(res.folds),
                auc=m_profit["auc"],
                expected_return_map=er_map,
                artifact=blob,
                artifact_sha256=hashlib.sha256(blob).hexdigest(),
                feature_reference=feature_reference(
                    labelled, cfg.monitoring.psi_bins, cfg.monitoring.drift_window_sessions
                ),
            )
        )
        run.reproducibility = {
            "app_version": __version__,
            "engine_version": ENGINE_VERSION,
            "feature_version": FEATURE_VERSION,
            "seed": rules.seed,
            "libraries": _libs(),
            "data_hash": run.data_hash,
            "config_fingerprint": run.config_fingerprint,
            "as_of": at.isoformat(),
            "knowledge_at": k_at.isoformat(),
            "deterministic": "LightGBM deterministic=True, num_threads=1, fixed seed",
        }
        run.warnings = warnings
        run.status = "completed"
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        run.status = "failed"
        run.error = f"{exc.__class__.__name__}: {exc}"[:2000]
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    record_audit(
        db,
        action="backtest.run",
        actor_user_id=user_id,
        entity_type="backtest_run",
        entity_id=str(run.id),
        details={"status": run.status, "horizon": horizon, "data_hash": run.data_hash},
    )
    db.commit()
    return run


def set_status(db: Session, mv: ModelVersion, status: str, user_id: uuid.UUID | None) -> None:
    before = mv.status
    if status == "active":
        for other in db.query(ModelVersion).filter(
            ModelVersion.horizon == mv.horizon, ModelVersion.status == "active"
        ):
            if other.id != mv.id:
                other.status = "retired"
        mv.activated_by, mv.activated_at = user_id, datetime.now(UTC)
    mv.status = status
    record_audit(
        db,
        action=f"model.{status}",
        actor_user_id=user_id,
        entity_type="model_version",
        entity_id=str(mv.id),
        details={"before": before, "after": status, "horizon": mv.horizon},
    )
    db.commit()


__all__ = ["run_backtest", "set_status"]
