"""Paper trading API (spec §28-§31)."""

from __future__ import annotations

from datetime import timedelta
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


@router.get("/portfolios/{pid}/performance")
def performance(pid: int, db: DbSession, _u: CurrentUser, now: Now) -> dict[str, Any]:
    """Paper-trading scorecard from stored fills and equity snapshots, with the
    benchmark (config macro.benchmark, NIFTY 50) over the same dates when it is
    stored. Anything that cannot be computed is null, never zero."""
    from app.core.config_file import get_config
    from app.macro.service import series_as_of

    pf = db.get(Portfolio, pid)
    if pf is None or pf.kind != "paper":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper portfolio {pid} not found")
    execs = db.scalars(
        select(PaperExecution).where(PaperExecution.portfolio_id == pid).order_by(PaperExecution.id)
    ).all()
    closed = [
        float(e.realised_pnl) for e in execs if e.side == "sell" and e.realised_pnl is not None
    ]
    wins = [p for p in closed if p > 0]
    losses = [p for p in closed if p < 0]
    by_ticker: dict[str, dict[str, Any]] = {}
    for e in execs:
        if e.side != "sell" or e.realised_pnl is None:
            continue
        t = paper.ticker_for(db, e.stock_id)
        row = by_ticker.setdefault(t, {"ticker": t, "trades": 0, "wins": 0, "realised_pnl": 0.0})
        row["trades"] += 1
        row["wins"] += 1 if e.realised_pnl > 0 else 0
        row["realised_pnl"] += float(e.realised_pnl)

    start_cash = float(pf.starting_cash)
    snaps = db.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == pid)
        .order_by(PortfolioSnapshot.taken_at)
    ).all()
    curve: list[tuple[Any, float]] = []
    if pf.created_at is not None:
        curve.append((pf.created_at.date(), start_cash))
    for s in snaps:
        d = s.taken_at.date()
        if curve and curve[-1][0] == d:
            curve[-1] = (d, s.equity)  # keep the day's last mark
        else:
            curve.append((d, s.equity))

    peak, max_dd = None, None
    for _, eq in curve:
        peak = eq if peak is None else max(peak, eq)
        if peak and peak > 0:
            dd = eq / peak - 1
            max_dd = dd if max_dd is None else min(max_dd, dd)
    last_equity = curve[-1][1] if len(curve) > 1 else None
    total_return = (
        (last_equity / start_cash - 1) if last_equity is not None and start_cash else None
    )

    bench_name = get_config().macro.benchmark
    bench: list[tuple[Any, float]] = []
    if len(curve) > 1:
        bench = series_as_of(db, bench_name, now, start=curve[0][0] - timedelta(days=10))
    points: list[dict[str, Any]] = []
    base_eq: float | None = None
    base_b: float | None = None
    j, last_b = 0, None
    for d, eq in curve:
        while j < len(bench) and bench[j][0] <= d:
            last_b = bench[j][1]
            j += 1
        if base_eq is None:
            base_eq = eq
        if base_b is None and last_b is not None:
            base_b = last_b
        points.append(
            {
                "date": d.isoformat(),
                "equity": eq,
                "portfolio_index": (eq / base_eq * 100) if base_eq else None,
                "benchmark_index": (last_b / base_b * 100) if base_b and last_b else None,
            }
        )
    bench_return = None
    first_b = next((p for p in points if p["benchmark_index"] is not None), None)
    if first_b is not None and points[-1]["benchmark_index"] is not None and len(points) > 1:
        bench_return = points[-1]["benchmark_index"] / first_b["benchmark_index"] - 1

    return {
        "portfolio": {"id": pf.id, "name": pf.name, "starting_cash": start_cash},
        "as_of": now.isoformat(),
        "trades": {
            "fills": len(execs),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(closed)) if closed else None,
            "avg_win": (sum(wins) / len(wins)) if wins else None,
            "avg_loss": (sum(losses) / len(losses)) if losses else None,
            "profit_factor": (sum(wins) / -sum(losses)) if wins and losses else None,
            "best": max(closed) if closed else None,
            "worst": min(closed) if closed else None,
            "realised_pnl": sum(closed) if closed else 0.0,
            "fees_paid": float(sum((e.fees for e in execs), start=0)),
        },
        "equity": {
            "points": len(curve),
            "last_equity": last_equity,
            "total_return": total_return,
            "max_drawdown": max_dd if len(curve) > 1 else None,
        },
        "benchmark": {
            "series": bench_name,
            "available": first_b is not None,
            "return": bench_return,
            "excess_return": (total_return - bench_return)
            if total_return is not None and bench_return is not None
            else None,
        },
        "curve": points,
        "by_ticker": sorted(by_ticker.values(), key=lambda r: -r["realised_pnl"]),
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
