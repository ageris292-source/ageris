"""Private research notes and trade journal. Each person sees only their own
entries. The text is theirs: Aegis never writes or edits it."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.stocks import _stock
from app.market_data import service
from app.models import JournalEntry, PaperOrder, Stock
from app.services.audit import record_audit

router = APIRouter(prefix="/journal", tags=["journal"])

Kind = Literal["note", "entry", "exit", "review"]
MAX_TAGS = 8


def _clean_tags(v: list[str]) -> list[str]:
    out: list[str] = []
    for t in v:
        t = " ".join(t.split()).lower()[:30]
        if t and t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return out


class EntryIn(BaseModel):
    ticker: str | None = Field(default=None, min_length=3, max_length=30)
    order_id: int | None = None
    kind: Kind = "note"
    title: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list)

    _tags = field_validator("tags")(_clean_tags)


class EntryPatch(BaseModel):
    kind: Kind | None = None
    title: str | None = Field(default=None, max_length=160)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _t(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_tags(v)


def _out(db: DbSession, e: JournalEntry) -> dict[str, Any]:
    stock = db.get(Stock, e.stock_id) if e.stock_id else None
    order = db.get(PaperOrder, e.order_id) if e.order_id else None
    return {
        "id": e.id,
        "kind": e.kind,
        "title": e.title,
        "body": e.body,
        "tags": e.tags or [],
        "ticker": str(service.ticker_of(stock)) if stock else None,
        "stock_name": stock.name if stock else None,
        "order": (
            {
                "id": order.id,
                "side": order.side,
                "quantity": order.quantity,
                "limit_price": str(order.limit_price),
                "status": order.status,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            if order
            else None
        ),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _own(db: DbSession, user_id: object, eid: int) -> JournalEntry:
    e = db.get(JournalEntry, eid)
    if e is None or e.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"journal entry {eid} not found")
    return e


@router.get("")
def list_entries(
    db: DbSession,
    user: CurrentUser,
    ticker: str | None = None,
    kind: Kind | None = None,
    order_id: int | None = None,
    tag: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    stmt = select(JournalEntry).where(JournalEntry.user_id == user.id)
    if ticker:
        stmt = stmt.where(JournalEntry.stock_id == _stock(db, ticker).id)
    if kind:
        stmt = stmt.where(JournalEntry.kind == kind)
    if order_id is not None:
        stmt = stmt.where(JournalEntry.order_id == order_id)
    if tag:
        stmt = stmt.where(JournalEntry.tags.contains([tag.lower()]))
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(JournalEntry.body.ilike(like), JournalEntry.title.ilike(like)))
    rows = db.scalars(
        stmt.order_by(JournalEntry.created_at.desc(), JournalEntry.id.desc()).limit(limit)
    ).all()
    return [_out(db, e) for e in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    stock_id: int | None = None
    if body.ticker:
        stock_id = _stock(db, body.ticker).id
    if body.order_id is not None:
        order = db.get(PaperOrder, body.order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper order {body.order_id} not found")
        if stock_id is not None and stock_id != order.stock_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "order is for a different stock"
            )
        stock_id = order.stock_id
    e = JournalEntry(
        user_id=user.id,
        stock_id=stock_id,
        order_id=body.order_id,
        kind=body.kind,
        title=(body.title or "").strip() or None,
        body=body.body.strip(),
        tags=body.tags,
    )
    db.add(e)
    db.flush()
    # The audit row records that an entry exists, never its private text.
    record_audit(
        db,
        action="journal.create",
        actor_user_id=user.id,
        entity_type="journal_entry",
        entity_id=str(e.id),
        details={"kind": body.kind, "stock_id": stock_id, "order_id": body.order_id},
    )
    db.commit()
    db.refresh(e)
    return _out(db, e)


@router.patch("/{eid}")
def update_entry(eid: int, body: EntryPatch, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    e = _own(db, user.id, eid)
    if body.kind is not None:
        e.kind = body.kind
    if body.title is not None:
        e.title = body.title.strip() or None
    if body.body is not None:
        e.body = body.body.strip()
    if body.tags is not None:
        e.tags = body.tags
    e.updated_at = datetime.now(e.created_at.tzinfo) if e.created_at else e.updated_at
    record_audit(
        db,
        action="journal.update",
        actor_user_id=user.id,
        entity_type="journal_entry",
        entity_id=str(e.id),
    )
    db.commit()
    db.refresh(e)
    return _out(db, e)


@router.delete("/{eid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(eid: int, db: DbSession, user: CurrentUser) -> Response:
    e = _own(db, user.id, eid)
    record_audit(
        db,
        action="journal.delete",
        actor_user_id=user.id,
        entity_type="journal_entry",
        entity_id=str(e.id),
    )
    db.delete(e)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
