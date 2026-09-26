"""The live order path (spec §29-§31) — present so that its safeguards are
real and tested, and disabled in this build.

A live order would need, in this order: an APPROVED *live* decision that is
fresh and unused, a human approver with the configured role, execution
readiness (build switch, live mode + flag, kill switch off, healthy broker,
risk engine), and finally the broker adapter. In this build the build switch
is off and the only adapter is `UnavailableBroker`, so every attempt is
refused, audited and alerted. Nothing is ever sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.alerts.service import raise_alert
from app.core.config_file import get_config
from app.core.modes import LIVE_TRADING_AVAILABLE
from app.core.settings import get_settings
from app.live.broker import (
    BrokerUnavailableError,
    LiveOrderRequest,
    get_broker,
    readiness_status,
)
from app.models import Stock, TradeDecisionRecord, TradeProposalRecord, User
from app.services.audit import record_audit
from app.services.trading_controls import evaluate_execution_readiness, read_kill_switch
from app.trade.gates import self_test


class LiveOrderRefusedError(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class LiveStatus:
    available: bool
    broker: str
    broker_reason: str
    live_orders_permitted: bool
    blocking_reasons: list[str]


def status(db: Session) -> LiveStatus:
    broker = get_broker()
    bs = broker.status()
    ok, _ = self_test(get_config())
    r = evaluate_execution_readiness(
        get_settings(),
        read_kill_switch(db),
        broker_status=readiness_status(broker),
        risk_engine_status="PASS" if ok else "FAIL",
    )
    return LiveStatus(
        available=LIVE_TRADING_AVAILABLE and bs.available,
        broker=bs.name,
        broker_reason=bs.reason,
        live_orders_permitted=r.live_orders_permitted,
        blocking_reasons=r.blocking_reasons,
    )


def submit_live_order(
    db: Session, decision_id: int, idempotency_key: str, approver: User, now: datetime
) -> None:
    """Never returns in this build: raises LiveOrderRefusedError (or
    LookupError for an unknown decision). Every attempt is audited."""
    cfg = get_config()
    dec = db.get(TradeDecisionRecord, decision_id)
    if dec is None:
        raise LookupError(f"decision {decision_id} not found")
    prop = db.get(TradeProposalRecord, dec.proposal_id)
    assert prop is not None
    reasons: list[str] = []
    if approver.role.value != cfg.paper_trading.approver_role or not approver.is_active:
        reasons.append("the approver does not hold the approver role")
    if prop.mode != "live":
        reasons.append(f"decision {decision_id} is for a {prop.mode} proposal, not live")
    if dec.decision != "APPROVED":
        reasons.append(f"decision {decision_id} is {dec.decision}")
    age = now - dec.decided_at
    if age > timedelta(minutes=cfg.paper_trading.max_decision_age_minutes) or age < timedelta(0):
        reasons.append("decision is stale; submit a new proposal")
    st = status(db)
    reasons += st.blocking_reasons
    if not reasons:  # unreachable in this build (live_build always blocks)
        stock = db.get(Stock, prop.stock_id) if prop.stock_id else None
        try:
            get_broker().place_order(
                LiveOrderRequest(
                    decision_id=decision_id,
                    idempotency_key=idempotency_key,
                    approved_by=approver.id,
                    ticker=prop.ticker,
                    exchange="BSE" if stock is not None and stock.exchange == "BSE" else "NSE",
                    side="sell" if prop.side == "sell" else "buy",
                    quantity=prop.quantity,
                    limit_price=prop.entry_price,
                )
            )
            reasons.append("broker accepted an order although live trading is disabled")
        except BrokerUnavailableError as exc:
            reasons.append(f"broker: {exc}")
    record_audit(
        db,
        action="live.order.refused",
        actor_user_id=approver.id,
        entity_type="trade_decision",
        entity_id=str(decision_id),
        details={"idempotency_key": idempotency_key, "reasons": reasons},
    )
    raise_alert(
        db,
        kind="live.order_refused",
        severity="warning",
        title=f"Live order refused for decision #{decision_id}",
        body="Live trading is disabled in this build. " + "; ".join(reasons),
        dedupe_key=f"live:{decision_id}:{idempotency_key}",
        link="/trade",
    )
    db.commit()
    raise LiveOrderRefusedError(reasons)
