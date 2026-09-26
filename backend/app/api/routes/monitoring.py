"""Model monitoring (spec §27). Admin only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.api.routes.stocks import Now
from app.core.config_file import get_config
from app.models import ModelMonitorRun, ModelPrediction, ModelVersion
from app.monitoring import service as mon

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _run_out(r: ModelMonitorRun, mv: ModelVersion | None, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "as_of": r.as_of.isoformat(),
        "model_id": r.model_id,
        "model_name": mv.name if mv else None,
        "model_status": mv.status if mv else None,
        "horizon": mv.horizon if mv else None,
        "status": r.status,
        "action": r.action,
        "reasons": r.reasons,
        "predictions_logged": r.predictions_logged,
        "max_psi": r.drift.get("max_psi"),
        "drift_status": r.drift.get("status"),
        "calibration_status": r.calibration.get("status"),
        "live_ece": r.calibration.get("live_ece"),
        "backtest_ece": r.calibration.get("backtest_ece"),
        "config_fingerprint": r.config_fingerprint,
    }
    if full:
        out["drift"] = r.drift
        out["calibration"] = r.calibration
    return out


@router.post("/run", status_code=status.HTTP_201_CREATED)
def run(db: DbSession, user: AdminUser, now: Now) -> list[dict[str, Any]]:
    """Check every active model now: log predictions, measure drift and
    calibration decay, retire on FAIL (if auto_disable)."""
    runs = mon.run_monitoring(db, now, user.id)
    return [_run_out(r, db.get(ModelVersion, r.model_id)) for r in runs]


@router.get("/overview")
def overview(db: DbSession, _u: AdminUser, now: Now) -> dict[str, Any]:
    """Latest check per model (active models first), plus the rules."""
    latest_ids = select(func.max(ModelMonitorRun.id)).group_by(ModelMonitorRun.model_id)
    latest = {
        r.model_id: r
        for r in db.scalars(select(ModelMonitorRun).where(ModelMonitorRun.id.in_(latest_ids)))
    }
    models = db.scalars(
        select(ModelVersion)
        .where((ModelVersion.status == "active") | ModelVersion.id.in_(latest.keys()))
        .order_by(ModelVersion.status != "active", ModelVersion.id.desc())
        .limit(20)
    ).all()
    counts: dict[int, int] = {
        mid: n
        for mid, n in db.execute(
            select(ModelPrediction.model_id, func.count()).group_by(ModelPrediction.model_id)
        ).tuples()
    }
    out = []
    for mv in models:
        r = latest.get(mv.id)
        out.append(
            {
                "model_id": mv.id,
                "name": mv.name,
                "status": mv.status,
                "horizon": mv.horizon,
                "valid_from": mv.valid_from.isoformat(),
                "monitorable": bool(mv.feature_reference),
                "predictions": counts.get(mv.id, 0),
                "latest": _run_out(r, mv) if r else None,
            }
        )
    return {"as_of": now.isoformat(), "rules": get_config().monitoring.model_dump(), "models": out}


@router.get("/runs")
def runs(
    db: DbSession,
    _u: AdminUser,
    model_id: int | None = None,
    limit: int = Query(default=60, ge=1, le=500),
) -> list[dict[str, Any]]:
    q = select(ModelMonitorRun)
    if model_id is not None:
        q = q.where(ModelMonitorRun.model_id == model_id)
    q = q.order_by(ModelMonitorRun.as_of.desc(), ModelMonitorRun.id.desc()).limit(limit)
    rows = db.scalars(q)
    return [_run_out(r, db.get(ModelVersion, r.model_id), full=False) for r in rows]


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: DbSession, _u: AdminUser) -> dict[str, Any]:
    r = db.get(ModelMonitorRun, run_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"monitor run {run_id} not found")
    return _run_out(r, db.get(ModelVersion, r.model_id))
