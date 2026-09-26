"""Backtests and the model registry (spec §22-§27)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.macro import _aware
from app.api.routes.stocks import Now, _stock
from app.backtest import registry
from app.backtest import service as bs
from app.core.config_file import get_config
from app.models import BacktestRun, ModelVersion

router = APIRouter(tags=["backtest"])


class BacktestIn(BaseModel):
    horizon: int = Field(default=20, ge=1, le=250)
    tickers: list[str] | None = Field(default=None, max_length=500)
    as_of: datetime | None = None


def _run_out(r: BacktestRun, full: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "status": r.status,
        "horizon": r.horizon,
        "as_of": r.as_of.isoformat(),
        "universe_size": len(r.universe),
        "survivorship_bias": r.survivorship_bias,
        "duration_ms": r.duration_ms,
        "error": r.error,
        "headline": {
            "auc_profit": (r.metrics or {}).get("profit", {}).get("auc"),
            "ece_profit": (r.metrics or {}).get("profit", {}).get("ece"),
            "folds": (r.metrics or {}).get("folds_trained"),
            "total_return": (r.simulation or {}).get("summary", {}).get("total_return"),
            "benchmark_total_return": (r.simulation or {})
            .get("summary", {})
            .get("benchmark_total_return"),
        },
    }
    if full:
        out.update(
            universe=r.universe,
            params=r.params,
            reproducibility=r.reproducibility,
            data_hash=r.data_hash,
            config_fingerprint=r.config_fingerprint,
            metrics=r.metrics,
            folds=r.folds,
            simulation=r.simulation,
            warnings=r.warnings,
            knowledge_at=r.knowledge_at.isoformat(),
        )
    return out


@router.post("/backtests", status_code=status.HTTP_201_CREATED)
def create_backtest(body: BacktestIn, db: DbSession, user: AdminUser, now: Now) -> dict[str, Any]:
    _aware("as_of", body.as_of)
    if body.as_of is not None and body.as_of > now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "as_of cannot be in the future")
    if body.tickers:
        for t in body.tickers:
            _stock(db, t)
    run = bs.run_backtest(db, body.horizon, user.id, body.as_of or now, None, body.tickers)
    return _run_out(run, True)


@router.get("/backtests")
def list_backtests(db: DbSession, _u: CurrentUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(50)).all()
    return [_run_out(r, False) for r in rows]


@router.get("/backtests/{rid}")
def get_backtest(rid: int, db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    r = db.get(BacktestRun, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"backtest {rid} not found")
    return _run_out(r, True)


def _model_out(m: ModelVersion) -> dict[str, Any]:
    cfg = get_config().trade_gates
    return {
        "id": m.id,
        "name": m.name,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "backtest_run_id": m.backtest_run_id,
        "horizon": m.horizon,
        "status": m.status,
        "valid_from": m.valid_from.isoformat(),
        "trained_rows": m.trained_rows,
        "calibration_error": m.calibration_error,
        "oos_periods": m.oos_periods,
        "auc": m.auc,
        "artifact_sha256": m.artifact_sha256,
        "activated_at": m.activated_at.isoformat() if m.activated_at else None,
        "passes_calibration_gate": m.calibration_error <= cfg.maximum_calibration_error,
        "passes_oos_gate": m.oos_periods >= cfg.minimum_out_of_sample_periods,
    }


@router.get("/models")
def list_models(db: DbSession, _u: CurrentUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()).limit(100)).all()
    return [_model_out(m) for m in rows]


def _model(db: DbSession, mid: int) -> ModelVersion:
    m = db.get(ModelVersion, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"model {mid} not found")
    return m


@router.post("/models/{mid}/activate")
def activate(mid: int, db: DbSession, user: AdminUser) -> dict[str, Any]:
    m = _model(db, mid)
    if m.status == "retired":
        raise HTTPException(status.HTTP_409_CONFLICT, "a retired model cannot be re-activated")
    bs.set_status(db, m, "active", user.id)
    return _model_out(m)


@router.post("/models/{mid}/retire")
def retire(mid: int, db: DbSession, user: AdminUser) -> dict[str, Any]:
    m = _model(db, mid)
    bs.set_status(db, m, "retired", user.id)
    return _model_out(m)


@router.get("/models/estimate/{ticker}")
def estimate(
    ticker: str,
    db: DbSession,
    _u: CurrentUser,
    now: Now,
    horizon: int = Query(default=20, ge=1, le=250),
    as_of: datetime | None = None,
) -> dict[str, Any]:
    _aware("as_of", as_of)
    stock = _stock(db, ticker)
    at = as_of or now
    e = registry.estimate(db, stock, at, horizon)
    if e is None:
        m = registry.active_model(db, horizon, at)
        return {
            "available": False,
            "reason": "no active model for this horizon and date"
            if m is None
            else "the active model cannot produce an estimate for this stock/date",
        }
    return {"available": True, **asdict(e), "as_of_date": e.as_of_date.isoformat()}
