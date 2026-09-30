"""Personal price alerts. They inform only; nothing here trades."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.alerts import price_rules
from app.api.deps import CurrentUser, DbSession
from app.api.routes.stocks import Now, _stock
from app.market_data import service
from app.models import PriceAlert, Stock
from app.services.audit import record_audit

router = APIRouter(prefix="/price-alerts", tags=["alerts"])

MAX_RULES = 50
Condition = Literal[
    "price_above", "price_below", "day_change_up", "day_change_down", "rsi_above", "rsi_below"
]


class RuleIn(BaseModel):
    ticker: str = Field(min_length=3, max_length=30)
    condition: Condition
    threshold: Decimal = Field(gt=0, le=Decimal("100000000"))
    note: str | None = Field(default=None, max_length=200)
    repeat: bool = False
    importance: Literal["normal", "high"] = "normal"


class RulePatch(BaseModel):
    threshold: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    note: str | None = Field(default=None, max_length=200)
    repeat: bool | None = None
    importance: Literal["normal", "high"] | None = None
    is_active: bool | None = None


class RuleOut(BaseModel):
    id: int
    ticker: str
    name: str | None
    condition: str
    threshold: float
    description: str
    note: str | None
    repeat: bool
    importance: str
    is_active: bool
    armed: bool
    created_at: datetime
    last_checked_at: datetime | None
    last_session: date | None
    last_value: float | None
    last_status: str | None
    last_triggered_at: datetime | None
    trigger_count: int


def _validate(condition: str, threshold: Decimal) -> None:
    if condition.startswith("rsi") and not (0 < threshold < 100):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "RSI level must be between 0 and 100"
        )
    if condition.startswith("day_change") and threshold > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a daily move is at most 100%")


def _out(db: DbSession, r: PriceAlert) -> RuleOut:
    stock = db.get(Stock, r.stock_id)
    assert stock is not None
    return RuleOut(
        id=r.id,
        ticker=str(service.ticker_of(stock)),
        name=stock.name,
        condition=r.condition,
        threshold=float(r.threshold),
        description=price_rules.describe(r.condition, r.threshold),
        note=r.note,
        repeat=r.repeat,
        importance=r.importance,
        is_active=r.is_active,
        armed=r.armed,
        created_at=r.created_at,
        last_checked_at=r.last_checked_at,
        last_session=r.last_session,
        last_value=r.last_value,
        last_status=r.last_status,
        last_triggered_at=r.last_triggered_at,
        trigger_count=r.trigger_count,
    )


def _own(db: DbSession, user_id: object, rid: int) -> PriceAlert:
    r = db.get(PriceAlert, rid)
    if r is None or r.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"price alert {rid} not found")
    return r


@router.get("", response_model=list[RuleOut])
def my_rules(db: DbSession, user: CurrentUser, ticker: str | None = None) -> list[RuleOut]:
    q = select(PriceAlert).where(PriceAlert.user_id == user.id)
    if ticker:
        q = q.where(PriceAlert.stock_id == _stock(db, ticker).id)
    rows = db.scalars(q.order_by(PriceAlert.is_active.desc(), PriceAlert.id.desc())).all()
    return [_out(db, r) for r in rows]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleIn, db: DbSession, user: CurrentUser, now: Now) -> RuleOut:
    stock = _stock(db, body.ticker)
    _validate(body.condition, body.threshold)
    n = db.scalar(
        select(func.count())
        .select_from(PriceAlert)
        .where(PriceAlert.user_id == user.id, PriceAlert.is_active.is_(True))
    )
    if (n or 0) >= MAX_RULES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"limited to {MAX_RULES} active price alerts")
    r = PriceAlert(
        user_id=user.id,
        stock_id=stock.id,
        condition=body.condition,
        threshold=body.threshold,
        note=body.note,
        repeat=body.repeat,
        importance=body.importance,
    )
    db.add(r)
    db.flush()
    record_audit(
        db,
        action="price_alert.create",
        actor_user_id=user.id,
        entity_type="price_alert",
        entity_id=str(r.id),
        details={
            "ticker": str(service.ticker_of(stock)),
            "condition": body.condition,
            "threshold": str(body.threshold),
        },
    )
    db.commit()
    db.refresh(r)
    return _out(db, r)


@router.patch("/{rid}", response_model=RuleOut)
def update_rule(rid: int, body: RulePatch, db: DbSession, user: CurrentUser) -> RuleOut:
    r = _own(db, user.id, rid)
    if body.threshold is not None:
        _validate(r.condition, body.threshold)
        r.threshold = body.threshold
        r.armed = True
        r.last_session = None  # re-check the latest close against the new level
    if body.note is not None:
        r.note = body.note or None
    if body.repeat is not None:
        r.repeat = body.repeat
    if body.importance is not None:
        r.importance = body.importance
    if body.is_active is not None:
        r.is_active = body.is_active
        if body.is_active:
            r.armed = True
            r.last_session = None
    record_audit(
        db,
        action="price_alert.update",
        actor_user_id=user.id,
        entity_type="price_alert",
        entity_id=str(r.id),
        details={k: str(v) for k, v in body.model_dump(exclude_none=True).items()},
    )
    db.commit()
    db.refresh(r)
    return _out(db, r)


@router.delete("/{rid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rid: int, db: DbSession, user: CurrentUser) -> Response:
    r = _own(db, user.id, rid)
    record_audit(
        db,
        action="price_alert.delete",
        actor_user_id=user.id,
        entity_type="price_alert",
        entity_id=str(r.id),
    )
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/check")
def check_now(db: DbSession, user: CurrentUser, now: Now) -> dict[str, object]:
    """Check your active rules against the latest stored close right now."""
    results = price_rules.check_all(db, now, user.id)
    return {
        "checked": len(results),
        "fired": sum(1 for r in results if r.fired),
        "results": [
            {"id": r.rule_id, "status": r.status, "fired": r.fired, "value": r.value}
            for r in results
        ],
    }
