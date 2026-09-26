"""Paper order placement, execution, positions, theses and monitoring."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.service import raise_alert
from app.core.config_file import get_config
from app.market_data import service as md
from app.market_data.calendar import get_calendar
from app.models import (
    AnalysisReport,
    PaperExecution,
    PaperOrder,
    Portfolio,
    Position,
    Stock,
    Thesis,
    ThesisEvent,
    TradeDecisionRecord,
    TradeProposalRecord,
    User,
)
from app.paper.broker import PAISE, simulate_fill
from app.portfolio import service as ps
from app.risk import service as rs
from app.services.audit import record_audit
from app.trade import service as ts
from app.trade.schemas import TradeProposal

THESIS_ALERT_SEVERITY = {
    "STOP_HIT": "critical",
    "TARGET_HIT": "warning",
    "HORIZON_EXPIRED": "warning",
    "STANCE_DETERIORATED": "warning",
}


class OrderRefusedError(ValueError):
    """The request is not allowed (stale, rejected decision, wrong mode...)."""


class IdempotencyConflictError(ValueError):
    """Same idempotency key reused for a different request."""


def _request_hash(decision_id: int, approver: uuid.UUID) -> str:
    return hashlib.sha256(f"paper-order|{decision_id}|{approver}".encode()).hexdigest()


def place_order(
    db: Session, decision_id: int, idempotency_key: str, approver: User, now: datetime
) -> tuple[PaperOrder, bool]:
    """Returns (order, replayed). A replay of the same key returns the
    original order without doing anything again."""
    cfg = get_config()
    h = _request_hash(decision_id, approver.id)
    prior = db.scalar(select(PaperOrder).where(PaperOrder.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.request_hash != h:
            raise IdempotencyConflictError("idempotency key already used for a different request")
        return prior, True

    dec = db.get(TradeDecisionRecord, decision_id)
    if dec is None:
        raise LookupError(f"decision {decision_id} not found")
    prop = db.get(TradeProposalRecord, dec.proposal_id)
    assert prop is not None
    if db.scalar(select(PaperOrder).where(PaperOrder.recheck_decision_id == decision_id)):
        raise OrderRefusedError(
            "this decision is a pre-order re-check and cannot be ordered itself"
        )
    if dec.decision != "APPROVED":
        raise OrderRefusedError(
            f"decision {decision_id} is {dec.decision}; only APPROVED can be ordered"
        )
    if prop.mode != "paper":
        raise OrderRefusedError("only paper orders are supported")
    age = now - dec.decided_at
    if (
        age > timedelta(minutes=cfg.paper_trading.max_decision_age_minutes)
        or age.total_seconds() < 0
    ):
        raise OrderRefusedError(
            f"decision is {age.total_seconds() / 60:.0f} min old (max "
            f"{cfg.paper_trading.max_decision_age_minutes}); submit a new proposal"
        )
    used = db.scalar(
        select(PaperOrder).where(
            PaperOrder.decision_id == decision_id, PaperOrder.status == "FILLED"
        )
    )
    if used is not None:
        raise OrderRefusedError(f"decision {decision_id} was already executed by order {used.id}")

    proposal = TradeProposal(
        **{**prop.payload, "rationale": f"pre-order re-check of decision #{decision_id}"}
    )
    re, _, re_id = ts.submit(db, proposal, approver.id, now)
    order = PaperOrder(
        idempotency_key=idempotency_key,
        request_hash=h,
        approved_by=approver.id,
        decision_id=decision_id,
        recheck_decision_id=re_id,
        portfolio_id=prop.portfolio_id,
        stock_id=prop.stock_id,
        ticker=prop.ticker,
        side=prop.side,
        quantity=prop.quantity,
        limit_price=prop.entry_price,
        status="REJECTED",
    )
    # Serialise orders per portfolio (no double spend / double fill under
    # concurrency): lock, then re-check that the decision is still unused.
    pf = db.scalar(select(Portfolio).where(Portfolio.id == prop.portfolio_id).with_for_update())
    assert pf is not None
    used = db.scalar(
        select(PaperOrder).where(
            PaperOrder.decision_id == decision_id, PaperOrder.status == "FILLED"
        )
    )
    if used is not None:
        order.reason = f"Decision {decision_id} was executed concurrently by order {used.id}"
        return _finish(db, order, approver, None), False
    if re.decision != "APPROVED":
        order.reason = (
            f"Pre-order re-check rejected at {re.first_failure}: "
            + "; ".join(g.reason for g in re.gates if g.status in ("FAIL", "UNKNOWN"))[:1500]
        )
        return _finish(db, order, approver, None), False

    ctx = re.context
    ref = Decimal(str(ctx["reference_price"]))
    name = cfg.trade_engine.cost_schedule
    fill = simulate_fill(
        prop.side,
        prop.quantity,
        ref,
        cfg.transaction_costs[name],
        ctx.get("adtv"),
        proposal.quoted_spread_bps,
    )
    limit = prop.entry_price
    if (prop.side == "buy" and fill.fill_price > limit) or (
        prop.side == "sell" and fill.fill_price < limit
    ):
        order.reason = (
            f"Simulated fill ₹{fill.fill_price} is worse than the limit ₹{limit} "
            "(immediate-or-cancel)"
        )
        return _finish(db, order, approver, None), False

    pos = db.scalar(
        select(Position).where(Position.portfolio_id == pf.id, Position.stock_id == prop.stock_id)
    )
    realised: Decimal | None = None
    if prop.side == "buy":
        cost = fill.notional + fill.fees
        if pf.cash < cost:
            order.reason = f"Insufficient cash: need ₹{cost}, have ₹{pf.cash}"
            return _finish(db, order, approver, None), False
        pf.cash = (pf.cash - cost).quantize(PAISE)
        if pos is None:
            pos = Position(
                portfolio_id=pf.id,
                stock_id=prop.stock_id,
                quantity=prop.quantity,
                avg_cost=fill.fill_price,
            )
            db.add(pos)
        else:
            total = pos.quantity + prop.quantity
            pos.avg_cost = (
                (pos.avg_cost * pos.quantity + fill.fill_price * prop.quantity) / total
            ).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            pos.quantity = total
    else:
        if pos is None or pos.quantity < prop.quantity:
            order.reason = "Position no longer large enough to sell"
            return _finish(db, order, approver, None), False
        realised = ((fill.fill_price - pos.avg_cost) * prop.quantity - fill.fees).quantize(PAISE)
        pf.cash = (pf.cash + fill.notional - fill.fees).quantize(PAISE)
        pos.quantity -= prop.quantity
        if pos.quantity == 0:
            db.delete(pos)
    order.status = "FILLED"
    order.reason = (
        f"Filled at ₹{fill.fill_price} (reference ₹{ref}, {fill.adverse_bps:.1f} bps adverse)"
    )
    db.add(order)
    db.flush()
    db.add(
        PaperExecution(
            order_id=order.id,
            executed_at=now,
            portfolio_id=pf.id,
            stock_id=prop.stock_id,
            side=prop.side,
            quantity=prop.quantity,
            reference_price=ref,
            fill_price=fill.fill_price,
            notional=fill.notional,
            fees=fill.fees,
            fee_breakdown=fill.fee_breakdown,
            realised_pnl=realised,
            cash_after=pf.cash,
            fill_model=cfg.paper_trading.fill_model,
        )
    )
    stock = db.get(Stock, prop.stock_id)
    assert stock is not None
    if prop.side == "buy":
        _open_thesis(db, order, prop, fill.fill_price, stock, ctx, now)
    elif pos is None or pos.quantity == 0:
        for th in db.scalars(
            select(Thesis).where(
                Thesis.portfolio_id == pf.id, Thesis.stock_id == stock.id, Thesis.status == "OPEN"
            )
        ):
            th.status, th.closed_at = "CLOSED", now
    db.flush()
    ps.record_snapshot(db, pf, now, source="execution")
    return _finish(db, order, approver, fill.fill_price), False


def _finish(db: Session, order: PaperOrder, approver: User, price: Decimal | None) -> PaperOrder:
    if order.id is None:
        db.add(order)
        db.flush()
    record_audit(
        db,
        action=f"paper.order.{order.status.lower()}",
        actor_user_id=approver.id,
        entity_type="paper_order",
        entity_id=str(order.id),
        details={
            "decision_id": order.decision_id,
            "recheck_decision_id": order.recheck_decision_id,
            "ticker": order.ticker,
            "side": order.side,
            "quantity": order.quantity,
            "fill_price": str(price) if price is not None else None,
            "reason": order.reason,
        },
    )
    db.commit()
    return order


def _open_thesis(
    db: Session,
    order: PaperOrder,
    prop: TradeProposalRecord,
    price: Decimal,
    stock: Stock,
    ctx: dict[str, Any],
    now: datetime,
) -> None:
    cfg = get_config()
    cal = get_calendar(cfg.market_data.calendar)
    start = rs.ist_date(now)
    sessions = cal.sessions(start, start + timedelta(days=int(prop.horizon_days * 1.6) + 10))
    end = sessions[min(prop.horizon_days, len(sessions) - 1)]
    inval: list[str] = []
    rid = ctx.get("report_id")
    if rid is not None:
        rep = db.get(AnalysisReport, rid)
        if rep is not None:
            inval = [
                f"({i['agent']}) {i['condition']}"
                for i in rep.report.get("synthesis", {}).get("invalidation", [])
            ][:10]
    assert prop.stop_loss is not None and prop.target is not None
    db.add(
        Thesis(
            opened_at=now,
            portfolio_id=order.portfolio_id,
            stock_id=stock.id,
            ticker=order.ticker,
            entry_order_id=order.id,
            entry_price=price,
            stop_loss=prop.stop_loss,
            target=prop.target,
            horizon_end=end,
            report_id=rid,
            invalidation=inval,
            status="OPEN",
        )
    )


def monitor(db: Session, now: datetime, user_id: uuid.UUID | None = None) -> list[ThesisEvent]:
    """Check every open thesis. Stop / target / horizon events create an
    engine-evaluated EXIT proposal that a human must still approve."""
    out: list[ThesisEvent] = []
    for th in db.scalars(select(Thesis).where(Thesis.status == "OPEN")).all():
        stock = db.get(Stock, th.stock_id)
        pf = db.get(Portfolio, th.portfolio_id)
        assert stock is not None and pf is not None
        pos = db.scalar(
            select(Position).where(Position.portfolio_id == pf.id, Position.stock_id == stock.id)
        )
        if pos is None:
            th.status, th.closed_at = "CLOSED", now
            continue
        h = rs.load_history(db, stock, now, None, 5)
        if not h.traded:
            continue
        session, close, _ = h.traded[-1]
        kinds: list[tuple[str, str]] = []
        if Decimal(str(close)) <= th.stop_loss:
            kinds.append(("STOP_HIT", f"Close ₹{close:,.2f} at or below stop ₹{th.stop_loss}"))
        if Decimal(str(close)) >= th.target:
            kinds.append(("TARGET_HIT", f"Close ₹{close:,.2f} at or above target ₹{th.target}"))
        if session >= th.horizon_end:
            kinds.append(("HORIZON_EXPIRED", f"Holding period ended {th.horizon_end}"))
        rep = db.scalar(
            select(AnalysisReport)
            .where(
                AnalysisReport.stock_id == stock.id,
                AnalysisReport.created_at > th.opened_at,
                AnalysisReport.created_at <= now,
            )
            .order_by(AnalysisReport.created_at.desc())
            .limit(1)
        )
        if rep is not None and rep.stance in ("NEGATIVE_TILT", "INSUFFICIENT_DATA"):
            kinds.append(("STANCE_DETERIORATED", f"Report #{rep.id} stance is {rep.stance}"))
        for kind, detail in kinds:
            exists = db.scalar(
                select(ThesisEvent).where(
                    ThesisEvent.thesis_id == th.id,
                    ThesisEvent.kind == kind,
                    ThesisEvent.session == session,
                )
            )
            if exists is not None:
                continue
            ev = ThesisEvent(thesis_id=th.id, session=session, kind=kind, detail=detail)
            if kind != "STANCE_DETERIORATED":
                exit_p = TradeProposal(
                    ticker=th.ticker,
                    side="sell",
                    quantity=pos.quantity,
                    entry_price=Decimal(f"{close:.4f}"),
                    portfolio_id=pf.id,
                    mode="paper",
                    rationale=f"Exit suggested by thesis #{th.id}: {kind}",
                )
                d, pid, _ = ts.submit(db, exit_p, user_id, now)
                ev.exit_proposal_id, ev.exit_decision = pid, d.decision
            db.add(ev)
            out.append(ev)
            exit_note = (
                f" Exit proposal #{ev.exit_proposal_id} is {ev.exit_decision} by the engine; "
                "a human must still approve any order."
                if ev.exit_proposal_id is not None
                else " Review the thesis; nothing is traded automatically."
            )
            raise_alert(
                db,
                kind=f"thesis.{kind.lower()}",
                severity=THESIS_ALERT_SEVERITY[kind],
                title=f"{th.ticker}: {kind.replace('_', ' ').lower()} (thesis #{th.id})",
                body=detail + "." + exit_note,
                dedupe_key=f"thesis:{th.id}:{kind}:{session.isoformat()}",
                link="/paper",
            )
            record_audit(
                db,
                action="paper.thesis.event",
                actor_user_id=user_id,
                entity_type="thesis",
                entity_id=str(th.id),
                details={"kind": kind, "detail": detail, "session": str(session)},
            )
    db.commit()
    return out


def snapshot_all(db: Session, now: datetime) -> int:
    n = 0
    for pf in db.scalars(select(Portfolio).where(Portfolio.kind == "paper", Portfolio.is_active)):
        if ps.record_snapshot(db, pf, now, source="eod") is not None:
            n += 1
    db.commit()
    return n


def ticker_for(db: Session, stock_id: int) -> str:
    s = db.get(Stock, stock_id)
    return str(md.ticker_of(s)) if s else "?"


__all__ = [
    "IdempotencyConflictError",
    "OrderRefusedError",
    "monitor",
    "place_order",
    "snapshot_all",
]
