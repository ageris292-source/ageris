"""Daily ranking, counterfactuals and alerts (spec §32-§35)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.alerts import service as alerts
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.stocks import Now
from app.models import Alert, Portfolio, RankingRun
from app.ranking import service as ranking
from app.services.audit import record_audit

router = APIRouter(tags=["ranking"])


class RankingIn(BaseModel):
    portfolio_id: int | None = None
    refresh: bool | None = None  # None = config ranking.refresh_reports


def _run_out(r: RankingRun, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "as_of": r.as_of.isoformat(),
        "horizon": r.horizon,
        "portfolio_id": r.portfolio_id,
        "headline": r.headline,
        "qualified": r.qualified,
        "evaluated": r.evaluated,
        "gate_failure_counts": r.gate_failure_counts,
        "operational_blockers": r.operational_blockers,
        "config_fingerprint": r.config_fingerprint,
    }
    if full:
        out["rows"] = r.rows
    return out


@router.post("/ranking/run", status_code=status.HTTP_201_CREATED)
def run(body: RankingIn, db: DbSession, user: AdminUser, now: Now) -> dict[str, Any]:
    """Evaluate a standardised candidate for every stock through the Trade
    Risk Engine. Places and proposes nothing."""
    if body.portfolio_id is not None:
        pf = db.get(Portfolio, body.portfolio_id)
        if pf is None or pf.kind != "paper":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"paper portfolio {body.portfolio_id} not found"
            )
    r = ranking.run_ranking(db, now, user.id, body.portfolio_id, body.refresh)
    return _run_out(r)


@router.get("/ranking/latest")
def latest(db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    r = db.scalar(select(RankingRun).order_by(RankingRun.as_of.desc(), RankingRun.id.desc()))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no ranking has been run yet")
    return _run_out(r)


@router.get("/ranking/history")
def history(
    db: DbSession, _u: CurrentUser, limit: int = Query(default=30, ge=1, le=365)
) -> list[dict[str, Any]]:
    runs = db.scalars(
        select(RankingRun).order_by(RankingRun.as_of.desc(), RankingRun.id.desc()).limit(limit)
    )
    return [_run_out(r, full=False) for r in runs]


@router.get("/ranking/counterfactuals")
def counterfactuals(db: DbSession, _u: CurrentUser, now: Now) -> dict[str, Any]:
    return ranking.counterfactuals(db, now)


def _alert_out(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "kind": a.kind,
        "severity": a.severity,
        "title": a.title,
        "body": a.body,
        "link": a.link,
        "deliveries": a.deliveries,
        "read_at": a.read_at.isoformat() if a.read_at else None,
    }


@router.get("/alerts", tags=["alerts"])
def list_alerts(
    db: DbSession,
    _u: CurrentUser,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    q = select(Alert)
    if unread_only:
        q = q.where(Alert.read_at.is_(None))
    rows = db.scalars(q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit))
    unread = db.scalar(select(func.count()).select_from(Alert).where(Alert.read_at.is_(None)))
    return {"unread": unread or 0, "alerts": [_alert_out(a) for a in rows]}


@router.post("/alerts/{alert_id}/read", tags=["alerts"])
def mark_read(alert_id: int, db: DbSession, user: CurrentUser, now: Now) -> dict[str, Any]:
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alert {alert_id} not found")
    if a.read_at is None:
        a.read_at = now
        record_audit(
            db, action="alert.read", actor_user_id=user.id, entity_type="alert", entity_id=str(a.id)
        )
        db.commit()
    return _alert_out(a)


@router.post("/alerts/read-all", tags=["alerts"])
def mark_all_read(db: DbSession, user: CurrentUser, now: Now) -> dict[str, int]:
    ids = db.scalars(
        update(Alert).where(Alert.read_at.is_(None)).values(read_at=now).returning(Alert.id)
    ).all()
    n = len(ids)
    record_audit(db, action="alert.read_all", actor_user_id=user.id, details={"count": n})
    db.commit()
    return {"marked": n}


@router.get("/alerts/channels", tags=["alerts"])
def channels(_u: CurrentUser) -> dict[str, Any]:
    return alerts.channel_status()
