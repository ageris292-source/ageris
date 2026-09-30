"""Activity log (read-only view of the append-only audit trail), your own
sign-in history, and "sign out everywhere".

Admins can see everyone's activity; analysts see only their own."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token
from app.core.settings import get_settings
from app.models import AuditLog, User, UserRole
from app.schemas import TokenResponse
from app.services.audit import record_audit

router = APIRouter(tags=["activity"])

# Action prefixes shown as filter groups in the UI.
GROUPS = {
    "auth": "Sign-ins",
    "user": "Team & passwords",
    "trade": "Trade proposals",
    "paper": "Paper orders",
    "kill_switch": "Kill switch",
    "portfolio": "Portfolios",
    "ranking": "Rankings",
    "analysis": "Research reports",
    "model": "Models",
    "watchlist": "Watchlists",
    "price_alert": "Price alerts",
    "journal": "Journal",
    "alert": "Alerts",
}


def _row(a: AuditLog, emails: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": a.id,
        "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
        "action": a.action,
        "actor_id": str(a.actor_user_id) if a.actor_user_id else None,
        "actor_email": emails.get(a.actor_user_id) if a.actor_user_id else None,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "system_mode": a.system_mode,
        "details": a.details or {},
    }


def _emails(db: DbSession, rows: list[AuditLog]) -> dict[uuid.UUID, str]:
    ids = {a.actor_user_id for a in rows if a.actor_user_id}
    if not ids:
        return {}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))}


def activity_query(
    user: User,
    actor: str | None,
    action: str | None,
    before_id: int | None,
) -> Select[tuple[AuditLog]]:
    q = select(AuditLog)
    if user.role is not UserRole.ADMIN or actor == "me":
        q = q.where(AuditLog.actor_user_id == user.id)
    elif actor:
        try:
            q = q.where(AuditLog.actor_user_id == uuid.UUID(actor))
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "actor must be 'me' or a user id"
            ) from None
    if action:
        prefix = action.replace("%", "").replace("_", r"\_")
        q = q.where(or_(AuditLog.action == action, AuditLog.action.like(f"{prefix}.%")))
    if before_id is not None:
        q = q.where(AuditLog.id < before_id)
    return q.order_by(AuditLog.id.desc())


@router.get("/activity")
def activity(
    db: DbSession,
    user: CurrentUser,
    actor: str | None = None,
    action: str | None = Query(default=None, max_length=60),
    before_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = list(db.scalars(activity_query(user, actor, action, before_id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    emails = _emails(db, rows)
    return {
        "scope": "all" if user.role is UserRole.ADMIN and actor != "me" else "me",
        "items": [_row(a, emails) for a in rows],
        "next_before_id": rows[-1].id if more and rows else None,
        "groups": GROUPS,
    }


@router.get("/auth/sessions")
def my_sign_ins(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Your recent sign-ins and failed attempts on your email, newest first."""
    rows = db.scalars(
        select(AuditLog)
        .where(
            or_(
                (AuditLog.action.in_(["auth.login", "auth.logout_all", "user.change_password"]))
                & (AuditLog.actor_user_id == user.id),
                (AuditLog.action == "auth.login_failed")
                & (AuditLog.details["email"].astext == user.email.lower()),
            )
        )
        .order_by(AuditLog.id.desc())
        .limit(30)
    ).all()
    failed = sum(1 for a in rows if a.action == "auth.login_failed")
    return {
        "items": [
            {
                "id": a.id,
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "action": a.action,
                "client": (a.details or {}).get("client"),
                "agent": (a.details or {}).get("agent"),
            }
            for a in rows
        ],
        "failed_recent": failed,
        "token_version": user.token_version,
    }


@router.post("/auth/logout-all", response_model=TokenResponse)
def logout_everywhere(db: DbSession, user: CurrentUser) -> TokenResponse:
    """End every session for your account (all devices), then return a fresh
    token so this device stays signed in."""
    user.token_version = (user.token_version or 0) + 1
    record_audit(db, action="auth.logout_all", actor_user_id=user.id)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.token_version),
        expires_in_seconds=get_settings().access_token_minutes * 60,
    )


@router.get("/activity/summary")
def activity_summary(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Counts per action group over everything visible to you."""
    q = select(AuditLog.action, func.count()).group_by(AuditLog.action)
    if user.role is not UserRole.ADMIN:
        q = q.where(AuditLog.actor_user_id == user.id)
    counts: dict[str, int] = {}
    for action, n in db.execute(q).all():
        g = action.split(".", 1)[0]
        counts[g] = counts.get(g, 0) + int(n)
    return {"counts": counts, "groups": GROUPS}
