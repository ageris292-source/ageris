"""Per-user watchlist. A view preference only: it never affects analysis,
ranking or any trade decision."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.stocks import Now, _stock
from app.market_data import service
from app.market_data.snapshot import price_snapshot
from app.models import AnalysisReport, Stock, WatchlistItem
from app.services.audit import record_audit

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

MAX_ITEMS = 100


class WatchlistAdd(BaseModel):
    ticker: str = Field(min_length=3, max_length=30)
    note: str | None = Field(default=None, max_length=200)


class WatchlistRow(BaseModel):
    ticker: str
    name: str | None
    exchange: str
    note: str | None
    added_at: datetime
    latest_session: date | None
    last_close: float | None
    prev_close: float | None
    change_pct: float | None
    sparkline: list[float]
    freshness: str
    stance: str | None
    composite: float | None
    report_at: datetime | None


def _row(db: DbSession, item: WatchlistItem, stock: Stock, now: datetime) -> WatchlistRow:
    snap = price_snapshot(db, stock, now)
    rep = db.scalar(
        select(AnalysisReport)
        .where(AnalysisReport.stock_id == stock.id)
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )
    return WatchlistRow(
        ticker=str(service.ticker_of(stock)),
        name=stock.name,
        exchange=stock.exchange,
        note=item.note,
        added_at=item.added_at,
        latest_session=snap.latest_session,
        last_close=snap.last_close,
        prev_close=snap.prev_close,
        change_pct=snap.change_pct,
        sparkline=snap.sparkline,
        freshness=service.freshness_for(db, stock, now).status,
        stance=rep.stance if rep else None,
        composite=rep.composite_score if rep else None,
        report_at=rep.created_at if rep else None,
    )


@router.get("", response_model=list[WatchlistRow])
def list_watchlist(db: DbSession, user: CurrentUser, now: Now) -> list[WatchlistRow]:
    rows = db.execute(
        select(WatchlistItem, Stock)
        .join(Stock, Stock.id == WatchlistItem.stock_id)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.added_at)
    ).all()
    return [_row(db, item, stock, now) for item, stock in rows]


@router.post("", response_model=WatchlistRow, status_code=status.HTTP_201_CREATED)
def add_to_watchlist(
    body: WatchlistAdd, db: DbSession, user: CurrentUser, now: Now
) -> WatchlistRow:
    stock = _stock(db, body.ticker)
    existing = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.stock_id == stock.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already on your watchlist")
    count = len(db.scalars(select(WatchlistItem.id).where(WatchlistItem.user_id == user.id)).all())
    if count >= MAX_ITEMS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"watchlist is limited to {MAX_ITEMS} stocks")
    item = WatchlistItem(user_id=user.id, stock_id=stock.id, note=body.note)
    db.add(item)
    db.flush()
    record_audit(
        db,
        action="watchlist.add",
        actor_user_id=user.id,
        entity_type="stock",
        entity_id=str(stock.id),
        details={"ticker": str(service.ticker_of(stock))},
    )
    db.commit()
    db.refresh(item)
    return _row(db, item, stock, now)


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_watchlist(ticker: str, db: DbSession, user: CurrentUser) -> Response:
    stock = _stock(db, ticker)
    item = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.stock_id == stock.id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not on your watchlist")
    db.delete(item)
    record_audit(
        db,
        action="watchlist.remove",
        actor_user_id=user.id,
        entity_type="stock",
        entity_id=str(stock.id),
        details={"ticker": str(service.ticker_of(stock))},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
