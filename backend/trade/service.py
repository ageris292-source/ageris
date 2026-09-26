"""Evaluate a proposal, persist proposal + decision immutably, audit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.models import TradeDecisionRecord, TradeProposalRecord
from app.services.audit import record_audit
from app.trade import context
from app.trade.gates import evaluate
from app.trade.schemas import TradeProposal, TradeRiskDecision


def submit(
    db: Session,
    proposal: TradeProposal,
    user_id: uuid.UUID | None,
    now: datetime,
    as_of: datetime | None = None,
    *,
    broker_healthy: bool | None = None,
) -> tuple[TradeRiskDecision, int, int]:
    at = as_of or now
    ctx, stock = context.build(db, proposal, at, broker_healthy=broker_healthy)
    d = evaluate(proposal, ctx, get_config(), now)
    prop = TradeProposalRecord(
        created_by=user_id,
        portfolio_id=proposal.portfolio_id,
        stock_id=stock.id if stock else None,
        ticker=proposal.ticker,
        side=proposal.side,
        mode=proposal.mode,
        quantity=proposal.quantity,
        entry_price=proposal.entry_price,
        stop_loss=proposal.stop_loss,
        target=proposal.target,
        horizon_days=proposal.horizon_days,
        rationale=proposal.rationale,
        payload=proposal.model_dump(mode="json"),
    )
    db.add(prop)
    db.flush()
    dec = TradeDecisionRecord(
        proposal_id=prop.id,
        decided_at=d.evaluated_at,
        as_of=d.as_of,
        decision=d.decision,
        first_failure=d.first_failure,
        failed_gates=d.failed_gates,
        gates=[g.model_dump(mode="json") for g in d.gates],
        metrics=d.metrics,
        costs=d.costs.model_dump(mode="json") if d.costs else None,
        context=d.context,
        engine_version=d.engine_version,
        config_fingerprint=d.config_fingerprint,
        decision_hash=d.decision_hash,
    )
    db.add(dec)
    db.flush()
    record_audit(
        db,
        action="trade.proposal.evaluated",
        actor_user_id=user_id,
        entity_type="trade_proposal",
        entity_id=str(prop.id),
        details={
            "ticker": proposal.ticker,
            "side": proposal.side,
            "quantity": proposal.quantity,
            "mode": proposal.mode,
            "decision": d.decision,
            "first_failure": d.first_failure,
            "hash": d.decision_hash,
        },
    )
    db.commit()
    return d, prop.id, dec.id
