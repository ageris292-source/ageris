"""CSV exports of your own records. Values are exported as stored; a missing
value is an empty cell, never a zero."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.alerts import price_rules
from app.api.deps import CurrentUser, DbSession
from app.api.routes.activity import activity_query
from app.api.routes.stocks import Now
from app.api.routes.watchlist import _own_list
from app.market_data import service
from app.models import (
    JournalEntry,
    PaperExecution,
    PaperOrder,
    Portfolio,
    PortfolioSnapshot,
    PriceAlert,
    Stock,
    User,
    WatchlistItem,
)
from app.paper import service as paper
from app.portfolio import service as ps
from app.services.audit import record_audit

router = APIRouter(prefix="/export", tags=["export"])

Kind = Literal[
    "orders", "fills", "positions", "equity", "watchlist", "journal", "price-alerts", "activity"
]
_FORMULA = ("=", "+", "@", "\t", "\r")


def _cell(v: Any) -> Any:
    """Neutralise spreadsheet formula injection in text cells."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str) and (v.startswith(_FORMULA) or (v.startswith("-") and not _numeric(v))):
        return "'" + v
    return v


def _numeric(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return buf.getvalue()


def _paper_pf(db: DbSession, pid: int | None) -> Portfolio | None:
    if pid is None:
        return None
    pf = db.get(Portfolio, pid)
    if pf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"portfolio {pid} not found")
    return pf


@router.get("/{kind}.csv")
def export_csv(
    kind: Kind,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    portfolio_id: int | None = None,
    list_id: int | None = None,
    limit: int = Query(default=5000, ge=1, le=20000),
) -> Response:
    header: list[str]
    rows: list[list[Any]]
    if kind == "orders":
        q = select(PaperOrder)
        if portfolio_id is not None:
            q = q.where(PaperOrder.portfolio_id == portfolio_id)
        header = [
            "id",
            "created_at",
            "portfolio_id",
            "ticker",
            "side",
            "quantity",
            "limit_price",
            "status",
            "decision_id",
            "recheck_decision_id",
            "reason",
        ]
        rows = [
            [
                o.id,
                o.created_at,
                o.portfolio_id,
                o.ticker,
                o.side,
                o.quantity,
                str(o.limit_price),
                o.status,
                o.decision_id,
                o.recheck_decision_id,
                o.reason,
            ]
            for o in db.scalars(q.order_by(PaperOrder.id).limit(limit))
        ]
    elif kind == "fills":
        q2 = select(PaperExecution)
        if portfolio_id is not None:
            q2 = q2.where(PaperExecution.portfolio_id == portfolio_id)
        header = [
            "id",
            "executed_at",
            "order_id",
            "portfolio_id",
            "ticker",
            "side",
            "quantity",
            "reference_price",
            "fill_price",
            "notional",
            "fees",
            "realised_pnl",
            "cash_after",
            "fill_model",
        ]
        rows = [
            [
                e.id,
                e.executed_at,
                e.order_id,
                e.portfolio_id,
                paper.ticker_for(db, e.stock_id),
                e.side,
                e.quantity,
                str(e.reference_price),
                str(e.fill_price),
                str(e.notional),
                str(e.fees),
                None if e.realised_pnl is None else str(e.realised_pnl),
                str(e.cash_after),
                e.fill_model,
            ]
            for e in db.scalars(q2.order_by(PaperExecution.id).limit(limit))
        ]
    elif kind in ("positions", "equity"):
        pf = _paper_pf(db, portfolio_id)
        if pf is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "portfolio_id is required")
        if kind == "positions":
            a = ps.analyze(db, pf, now)
            header = [
                "ticker",
                "quantity",
                "avg_cost",
                "price",
                "price_date",
                "value",
                "weight",
                "unrealised_pnl",
                "sector",
            ]
            rows = [
                [
                    h["ticker"],
                    h["quantity"],
                    h["avg_cost"],
                    h["price"],
                    h["price_date"],
                    h["value"],
                    h["weight"],
                    h["unrealised_pnl"],
                    h["sector"],
                ]
                for h in a["holdings"]
            ]
        else:
            header = ["taken_at", "equity", "cash", "invested", "source"]
            rows = [
                [s.taken_at, s.equity, s.cash, s.invested, s.source]
                for s in db.scalars(
                    select(PortfolioSnapshot)
                    .where(PortfolioSnapshot.portfolio_id == pf.id)
                    .order_by(PortfolioSnapshot.taken_at)
                    .limit(limit)
                )
            ]
    elif kind == "watchlist":
        wl = _own_list(db, user.id, list_id)
        header = ["list", "ticker", "name", "exchange", "note", "added_at"]
        rows = [
            [wl.name, str(service.ticker_of(s)), s.name, s.exchange, i.note, i.added_at]
            for i, s in db.execute(
                select(WatchlistItem, Stock)
                .join(Stock, Stock.id == WatchlistItem.stock_id)
                .where(WatchlistItem.watchlist_id == wl.id)
                .order_by(WatchlistItem.added_at)
            ).all()
        ]
        db.commit()
    elif kind == "journal":
        header = [
            "id",
            "created_at",
            "updated_at",
            "kind",
            "ticker",
            "order_id",
            "title",
            "tags",
            "body",
        ]
        out: list[list[Any]] = []
        for e in db.scalars(
            select(JournalEntry)
            .where(JournalEntry.user_id == user.id)
            .order_by(JournalEntry.created_at)
            .limit(limit)
        ):
            st = db.get(Stock, e.stock_id) if e.stock_id else None
            out.append(
                [
                    e.id,
                    e.created_at,
                    e.updated_at,
                    e.kind,
                    str(service.ticker_of(st)) if st else None,
                    e.order_id,
                    e.title,
                    ";".join(e.tags or []),
                    e.body,
                ]
            )
        rows = out
    elif kind == "price-alerts":
        header = [
            "id",
            "ticker",
            "rule",
            "note",
            "repeat",
            "importance",
            "active",
            "created_at",
            "last_session",
            "last_value",
            "last_status",
            "last_triggered_at",
            "trigger_count",
        ]
        rows = []
        for r in db.scalars(
            select(PriceAlert).where(PriceAlert.user_id == user.id).order_by(PriceAlert.id)
        ):
            st = db.get(Stock, r.stock_id)
            rows.append(
                [
                    r.id,
                    str(service.ticker_of(st)) if st else None,
                    price_rules.describe(r.condition, r.threshold),
                    r.note,
                    r.repeat,
                    r.importance,
                    r.is_active,
                    r.created_at,
                    r.last_session,
                    r.last_value,
                    r.last_status,
                    r.last_triggered_at,
                    r.trigger_count,
                ]
            )
    else:  # activity
        logs = list(db.scalars(activity_query(user, None, None, None).limit(limit)))
        ids = {a.actor_user_id for a in logs if a.actor_user_id}
        emails = (
            {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
        )
        header = [
            "id",
            "occurred_at",
            "actor",
            "action",
            "entity_type",
            "entity_id",
            "system_mode",
            "details",
        ]
        rows = [
            [
                a.id,
                a.occurred_at,
                emails.get(a.actor_user_id) if a.actor_user_id else "system",
                a.action,
                a.entity_type,
                a.entity_id,
                a.system_mode,
                ";".join(f"{k}={v}" for k, v in sorted((a.details or {}).items())),
            ]
            for a in logs
        ]
    record_audit(
        db,
        action="export.csv",
        actor_user_id=user.id,
        entity_type="export",
        entity_id=kind,
        details={"rows": len(rows), "portfolio_id": portfolio_id, "list_id": list_id},
    )
    db.commit()
    stamp = now.strftime("%Y%m%d")
    return Response(
        content=_csv(header, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="aegis-{kind}-{stamp}.csv"'},
    )
