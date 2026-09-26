"""Paper trading API (spec §28-§31)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.stocks import Now
from app.models import (
    PaperExecution,
    PaperOrder,
    Portfolio,
    PortfolioSnapshot,
    Thesis,
    ThesisEvent,
)
from app.paper import service as paper
from app.portfolio import service as ps

router = APIRouter(prefix="/paper", tags=["paper"])

IdemKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")
]


class OrderIn(BaseModel):
    decision_id: int


def _order_out(o: PaperOrder) -> dict[str, Any]:
    return {
        "id": o.id,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "decision_id": o.decision_id,
        "recheck_decision_id": o.recheck_decision_id,
        "portfolio_id": o.portfolio_id,
        "ticker": o.ticker,
        "side": o.side,
        "quantity": o.quantity,
        "limit_price": str(o.limit_price),
        "status": o.status,
        "reason": o.reason,
    }


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def place(
    body: OrderIn, key: IdemKey, response: Response, db: DbSession, user: AdminUser, now: Now
) -> dict[str, Any]:
    """Human approval: an admin turns an APPROVED decision into a paper order.
    The engine re-checks every gate first; a replayed key returns the original."""
    try:
        order, replayed = paper.place_order(db, body.decision_id, key, user, now)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (paper.OrderRefusedError, paper.IdempotencyConflictError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError:  # concurrent request with the same key won the race
        db.rollback()
        winner = db.scalar(select(PaperOrder).where(PaperOrder.idempotency_key == key))
        if winner is None:
            raise
        order, replayed = winner, True
    if replayed:
        response.status_code = status.HTTP_200_OK
    return {**_order_out(order), "replayed": replayed}


@router.get("/orders")
def orders(db: DbSession, _u: CurrentUser, portfolio_id: int | None = None) -> list[dict[str, Any]]:
    q = select(PaperOrder)
    if portfolio_id is not None:
        q = q.where(PaperOrder.portfolio_id == portfolio_id)
    return [_order_out(o) for o in db.scalars(q.order_by(PaperOrder.id.desc()).limit(200))]


@router.get("/portfolios/{pid}")
def portfolio(pid: int, db: DbSession, _u: CurrentUser, now: Now) -> dict[str, Any]:
    pf = db.get(Portfolio, pid)
    if pf is None or pf.kind != "paper":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper portfolio {pid} not found")
    execs = db.scalars(
        select(PaperExecution).where(PaperExecution.portfolio_id == pid).order_by(PaperExecution.id)
    ).all()
    theses = db.scalars(select(Thesis).where(Thesis.portfolio_id == pid).order_by(Thesis.id)).all()
    snaps = db.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == pid)
        .order_by(PortfolioSnapshot.taken_at)
    ).all()
    a = ps.analyze(db, pf, now)
    eq = a["metrics"].get("equity")
    return {
        "analysis": a,
        "starting_cash": str(pf.starting_cash),
        "total_return": (eq / float(pf.starting_cash) - 1) if eq and pf.starting_cash else None,
        "realised_pnl": str(sum((e.realised_pnl or 0 for e in execs), start=0)),
        "fees_paid": str(sum((e.fees for e in execs), start=0)),
        "executions": [
            {
                "id": e.id,
                "order_id": e.order_id,
                "executed_at": e.executed_at.isoformat(),
                "side": e.side,
                "quantity": e.quantity,
                "reference_price": str(e.reference_price),
                "fill_price": str(e.fill_price),
                "notional": str(e.notional),
                "fees": str(e.fees),
                "realised_pnl": str(e.realised_pnl) if e.realised_pnl is not None else None,
                "cash_after": str(e.cash_after),
                "ticker": paper.ticker_for(db, e.stock_id),
            }
            for e in execs
        ],
        "theses": [_thesis_out(db, t) for t in theses],
        "equity_curve": [
            {"taken_at": s.taken_at.isoformat(), "equity": s.equity, "source": s.source}
            for s in snaps
        ],
    }


def _thesis_out(db: DbSession, t: Thesis) -> dict[str, Any]:
    events = db.scalars(select(ThesisEvent).where(ThesisEvent.thesis_id == t.id)).all()
    return {
        "id": t.id,
        "ticker": t.ticker,
        "status": t.status,
        "opened_at": t.opened_at.isoformat(),
        "entry_price": str(t.entry_price),
        "stop_loss": str(t.stop_loss),
        "target": str(t.target),
        "horizon_end": t.horizon_end.isoformat(),
        "invalidation": t.invalidation,
        "events": [
            {
                "session": e.session.isoformat(),
                "kind": e.kind,
                "detail": e.detail,
                "exit_proposal_id": e.exit_proposal_id,
                "exit_decision": e.exit_decision,
            }
            for e in events
        ],
    }


@router.post("/monitor")
def run_monitor(db: DbSession, user: CurrentUser, now: Now) -> dict[str, Any]:
    events = paper.monitor(db, now, user.id)
    return {
        "events": [
            {
                "thesis_id": e.thesis_id,
                "kind": e.kind,
                "detail": e.detail,
                "exit_proposal_id": e.exit_proposal_id,
                "exit_decision": e.exit_decision,
            }
            for e in events
        ]
    }
