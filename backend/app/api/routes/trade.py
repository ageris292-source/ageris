"""Trade Risk Engine API (spec §17-§19)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis import risk as rk
from app.api.deps import CurrentUser, DbSession
from app.api.routes.macro import _aware
from app.api.routes.stocks import Now, _stock
from app.core.config_file import get_config
from app.models import TradeDecisionRecord, TradeProposalRecord
from app.risk import service as rs
from app.trade import service as ts
from app.trade.costs import CostError, round_trip
from app.trade.gates import ENGINE_VERSION, GATE_DESCRIPTIONS, GATES, decision_hash, self_test
from app.trade.schemas import TradeProposal, TradeRiskDecision

router = APIRouter(prefix="/trade", tags=["trade"])


class ProposalIn(TradeProposal):
    as_of: datetime | None = None


@router.post("/proposals", status_code=status.HTTP_201_CREATED)
def submit(body: ProposalIn, db: DbSession, user: CurrentUser, now: Now) -> dict[str, Any]:
    _aware("as_of", body.as_of)
    if body.as_of is not None and body.as_of > now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "as_of cannot be in the future")
    proposal = TradeProposal(**body.model_dump(exclude={"as_of"}))
    d, pid, did = ts.submit(db, proposal, user.id, now, body.as_of)
    return {"proposal_id": pid, "decision_id": did, **d.model_dump(mode="json")}


@router.get("/proposals")
def list_proposals(
    db: DbSession,
    _u: CurrentUser,
    portfolio_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    q = select(TradeProposalRecord, TradeDecisionRecord).join(
        TradeDecisionRecord, TradeDecisionRecord.proposal_id == TradeProposalRecord.id
    )
    if portfolio_id is not None:
        q = q.where(TradeProposalRecord.portfolio_id == portfolio_id)
    rows = db.execute(q.order_by(TradeProposalRecord.id.desc()).limit(limit)).all()
    return [
        {
            "proposal_id": p.id,
            "decision_id": d.id,
            "created_at": p.created_at.isoformat(),
            "ticker": p.ticker,
            "side": p.side,
            "mode": p.mode,
            "quantity": p.quantity,
            "entry_price": str(p.entry_price),
            "portfolio_id": p.portfolio_id,
            "decision": d.decision,
            "first_failure": d.first_failure,
            "failed_gates": d.failed_gates,
            "rationale": p.rationale,
        }
        for p, d in rows
    ]


@router.get("/decisions/{did}")
def get_decision(did: int, db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    d = db.get(TradeDecisionRecord, did)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"decision {did} not found")
    p = db.get(TradeProposalRecord, d.proposal_id)
    assert p is not None
    rebuilt = TradeRiskDecision(
        decision=d.decision,
        engine_version=d.engine_version,
        evaluated_at=d.decided_at,
        as_of=d.as_of,
        proposal=TradeProposal(**p.payload),
        gates=d.gates,
        failed_gates=d.failed_gates,
        first_failure=d.first_failure,
        requires_human_approval=True,
        costs=d.costs,
        metrics=d.metrics,
        context=d.context,
        config_fingerprint=d.config_fingerprint,
    )
    return {
        "proposal_id": p.id,
        "decision_id": d.id,
        **rebuilt.model_dump(mode="json"),
        "decision_hash": d.decision_hash,
        "hash_verified": decision_hash(rebuilt) == d.decision_hash,
    }


@router.get("/gates")
def gates(_u: CurrentUser) -> dict[str, Any]:
    cfg = get_config()
    ok, msg = self_test(cfg)
    return {
        "engine_version": ENGINE_VERSION,
        "self_test": {"passed": ok, "detail": msg},
        "rule": "APPROVED only if every applicable gate is PASS; FAIL and UNKNOWN reject.",
        "gates": [
            {"order": i, "name": n, "applies_to_exits": ex, "description": GATE_DESCRIPTIONS[n]}
            for i, (n, ex, _fn) in enumerate(GATES, start=1)
        ],
        "thresholds": {
            "trade_gates": cfg.trade_gates.model_dump(),
            "trade_engine": cfg.trade_engine.model_dump(),
            "liquidity": cfg.liquidity.model_dump(),
            "risk_controls": cfg.risk_controls.model_dump(),
            "position_sizing": cfg.position_sizing.model_dump(),
            "execution": cfg.execution.model_dump(),
        },
    }


class CostIn(BaseModel):
    ticker: str
    quantity: int = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    horizon_days: int = Field(default=20, ge=1, le=3650)
    quoted_spread_bps: float | None = Field(default=None, ge=0)
    as_of: datetime | None = None


@router.post("/costs")
def costs(body: CostIn, db: DbSession, _u: CurrentUser, now: Now) -> dict[str, Any]:
    _aware("as_of", body.as_of)
    cfg = get_config()
    stock = _stock(db, body.ticker)
    h = rs.load_history(db, stock, body.as_of or now, None, cfg.risk_analysis.lookback_sessions)
    adtv = rk.average_daily_traded_value(
        [c for _, c, _ in h.traded],
        [v for _, _, v in h.traded],
        cfg.risk_analysis.adv_window_sessions,
    )
    name = cfg.trade_engine.cost_schedule
    try:
        c = round_trip(
            name,
            cfg.transaction_costs[name],
            float(body.entry_price) * body.quantity,
            adtv,
            body.horizon_days,
            body.quoted_spread_bps,
        )
    except CostError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        **c.model_dump(),
        "adtv": adtv,
        "notice": "Schedule must be checked against current "
        "exchange / SEBI / broker charges before any paper or live use.",
    }
