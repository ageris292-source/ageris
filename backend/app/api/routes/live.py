"""Live trading API (spec §29-§31). Disabled in this build: status reports
why, and every order request is refused (and audited)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.paper import IdemKey
from app.api.routes.stocks import Now
from app.live import service as live

router = APIRouter(prefix="/live", tags=["live"])


class LiveOrderIn(BaseModel):
    decision_id: int


@router.get("/status")
def live_status(db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    return asdict(live.status(db))


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def live_order(
    body: LiveOrderIn, key: IdemKey, db: DbSession, user: AdminUser, now: Now
) -> dict[str, Any]:
    try:
        live.submit_live_order(db, body.decision_id, key, user, now)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except live.LiveOrderRefusedError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"message": "live trading is not available in this build", "reasons": exc.reasons},
        ) from exc
    raise HTTPException(  # pragma: no cover - submit_live_order never returns in this build
        status.HTTP_500_INTERNAL_SERVER_ERROR, "live order path returned unexpectedly"
    )
