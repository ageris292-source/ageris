"""Per-user named watchlists. A view preference only: they never affect
analysis, ranking or any trade decision."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.api.routes.stocks import Now, _stock
from app.market_data import service
from app.market_data.snapshot import price_snapshot
from app.models import AnalysisReport, Stock, Watchlist, WatchlistItem
from app.services.audit import record_audit

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
lists_router = APIRouter(prefix="/watchlists", tags=["watchlist"])

MAX_ITEMS = 100
MAX_LISTS = 20
DEFAULT_NAME = "My watchlist"


# ------------------------------------------------------------------ schemas


class WatchlistAdd(BaseModel):
    ticker: str = Field(min_length=3, max_length=30)
    note: str | None = Field(default=None, max_length=200)
    list_id: int | None = None


class WatchlistRow(BaseModel):
    ticker: str
    name: str | None
    exchange: str
    note: str | None
    added_at: datetime
    list_id: int
    latest_session: date | None
    last_close: float | None
    prev_close: float | None
    change_pct: float | None
    sparkline: list[float]
    freshness: str
    stance: str | None
    composite: float | None
    report_at: datetime | None


class ListOut(BaseModel):
    id: int
    name: str
    position: int
    count: int
    created_at: datetime


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ListPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    position: int | None = Field(default=None, ge=0, le=1000)


# ------------------------------------------------------------------ helpers


def ensure_default(db: Session, user_id: uuid.UUID) -> Watchlist:
    """Every user has at least one list; the first (lowest position) is the default."""
    first = db.scalar(
        select(Watchlist)
        .where(Watchlist.user_id == user_id)
        .order_by(Watchlist.position, Watchlist.id)
        .limit(1)
    )
    if first is None:
        first = Watchlist(user_id=user_id, name=DEFAULT_NAME, position=0)
        db.add(first)
        db.flush()
    return first


def _own_list(db: Session, user_id: uuid.UUID, list_id: int | None) -> Watchlist:
    if list_id is None:
        return ensure_default(db, user_id)
    wl = db.get(Watchlist, list_id)
    if wl is None or wl.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"watchlist {list_id} not found")
    return wl


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be blank")
    return name


def _row(db: Session, item: WatchlistItem, stock: Stock, now: datetime) -> WatchlistRow:
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
        list_id=item.watchlist_id,
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


def _list_out(db: Session, wl: Watchlist) -> ListOut:
    n = db.scalar(
        select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
    )
    return ListOut(
        id=wl.id, name=wl.name, position=wl.position, count=n or 0, created_at=wl.created_at
    )


# ------------------------------------------------------------------ lists


@lists_router.get("", response_model=list[ListOut])
def my_lists(db: DbSession, user: CurrentUser) -> list[ListOut]:
    ensure_default(db, user.id)
    db.commit()
    rows = db.scalars(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.position, Watchlist.id)
    ).all()
    return [_list_out(db, w) for w in rows]


@lists_router.post("", response_model=ListOut, status_code=status.HTTP_201_CREATED)
def create_list(body: ListIn, db: DbSession, user: CurrentUser) -> ListOut:
    ensure_default(db, user.id)
    name = _clean_name(body.name)
    existing = db.scalars(select(Watchlist).where(Watchlist.user_id == user.id)).all()
    if len(existing) >= MAX_LISTS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"limited to {MAX_LISTS} watchlists")
    if any(w.name.lower() == name.lower() for w in existing):
        raise HTTPException(status.HTTP_409_CONFLICT, "you already have a list with that name")
    wl = Watchlist(
        user_id=user.id, name=name, position=max((w.position for w in existing), default=0) + 1
    )
    db.add(wl)
    db.flush()
    record_audit(
        db,
        action="watchlist.list_create",
        actor_user_id=user.id,
        entity_type="watchlist",
        entity_id=str(wl.id),
        details={"name": name},
    )
    db.commit()
    db.refresh(wl)
    return _list_out(db, wl)


@lists_router.patch("/{list_id}", response_model=ListOut)
def update_list(list_id: int, body: ListPatch, db: DbSession, user: CurrentUser) -> ListOut:
    wl = _own_list(db, user.id, list_id)
    if body.name is not None:
        name = _clean_name(body.name)
        clash = db.scalar(
            select(Watchlist).where(
                Watchlist.user_id == user.id,
                func.lower(Watchlist.name) == name.lower(),
                Watchlist.id != wl.id,
            )
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "you already have a list with that name")
        wl.name = name
    if body.position is not None:
        wl.position = body.position
    record_audit(
        db,
        action="watchlist.list_update",
        actor_user_id=user.id,
        entity_type="watchlist",
        entity_id=str(wl.id),
        details=body.model_dump(exclude_none=True),
    )
    db.commit()
    return _list_out(db, wl)


@lists_router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list(list_id: int, db: DbSession, user: CurrentUser) -> Response:
    wl = _own_list(db, user.id, list_id)
    count = db.scalar(
        select(func.count()).select_from(Watchlist).where(Watchlist.user_id == user.id)
    )
    if (count or 0) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "you need at least one watchlist")
    record_audit(
        db,
        action="watchlist.list_delete",
        actor_user_id=user.id,
        entity_type="watchlist",
        entity_id=str(wl.id),
        details={"name": wl.name},
    )
    db.delete(wl)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ items


@router.get("", response_model=list[WatchlistRow])
def list_watchlist(
    db: DbSession, user: CurrentUser, now: Now, list_id: int | None = None
) -> list[WatchlistRow]:
    wl = _own_list(db, user.id, list_id)
    db.commit()
    rows = db.execute(
        select(WatchlistItem, Stock)
        .join(Stock, Stock.id == WatchlistItem.stock_id)
        .where(WatchlistItem.watchlist_id == wl.id)
        .order_by(WatchlistItem.added_at, WatchlistItem.id)
    ).all()
    return [_row(db, item, stock, now) for item, stock in rows]


@router.get("/membership/{ticker}", response_model=list[int])
def membership(ticker: str, db: DbSession, user: CurrentUser) -> list[int]:
    """Ids of the caller's lists that contain this stock."""
    stock = _stock(db, ticker)
    return list(
        db.scalars(
            select(WatchlistItem.watchlist_id).where(
                WatchlistItem.user_id == user.id, WatchlistItem.stock_id == stock.id
            )
        ).all()
    )


@router.post("", response_model=WatchlistRow, status_code=status.HTTP_201_CREATED)
def add_to_watchlist(
    body: WatchlistAdd, db: DbSession, user: CurrentUser, now: Now
) -> WatchlistRow:
    stock = _stock(db, body.ticker)
    wl = _own_list(db, user.id, body.list_id)
    existing = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id, WatchlistItem.stock_id == stock.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"already on {wl.name}")
    count = db.scalar(
        select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
    )
    if (count or 0) >= MAX_ITEMS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a watchlist is limited to {MAX_ITEMS} stocks"
        )
    item = WatchlistItem(user_id=user.id, watchlist_id=wl.id, stock_id=stock.id, note=body.note)
    db.add(item)
    db.flush()
    record_audit(
        db,
        action="watchlist.add",
        actor_user_id=user.id,
        entity_type="stock",
        entity_id=str(stock.id),
        details={"ticker": str(service.ticker_of(stock)), "list": wl.name},
    )
    db.commit()
    db.refresh(item)
    return _row(db, item, stock, now)


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_watchlist(
    ticker: str, db: DbSession, user: CurrentUser, list_id: int | None = None
) -> Response:
    stock = _stock(db, ticker)
    wl = _own_list(db, user.id, list_id)
    item = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id, WatchlistItem.stock_id == stock.id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"not on {wl.name}")
    db.delete(item)
    record_audit(
        db,
        action="watchlist.remove",
        actor_user_id=user.id,
        entity_type="stock",
        entity_id=str(stock.id),
        details={"ticker": str(service.ticker_of(stock)), "list": wl.name},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
