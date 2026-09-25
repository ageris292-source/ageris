"""Kill switch and execution-readiness evaluation (spec §5, §28, §48, §51).

Design rule: every function here fails CLOSED. Any exception, missing row or
unknown dependency state is treated as "trading blocked". UNKNOWN never
counts as PASS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.modes import SystemMode
from app.core.settings import Settings
from app.models import RiskEvent, RiskEventSeverity, TradingControl, User, UserRole
from app.services.audit import record_audit

log = logging.getLogger(__name__)

CheckStatus = Literal["PASS", "FAIL", "UNKNOWN"]


class NotAuthorizedError(PermissionError):
    pass


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: str
    known: bool  # False when the state could not be read (treated as active)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: CheckStatus
    reason: str


@dataclass(frozen=True)
class ExecutionReadiness:
    mode: SystemMode
    live_orders_permitted: bool
    paper_orders_permitted: bool
    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def blocking_reasons(self) -> list[str]:
        return [f"{c.name}: {c.reason}" for c in self.checks if c.status != "PASS"]


def read_kill_switch(db: Session) -> KillSwitchState:
    try:
        row = db.get(TradingControl, 1)
    except Exception:
        log.exception("kill switch state unreadable; failing closed")
        db.rollback()
        return KillSwitchState(active=True, reason="kill switch state unreadable", known=False)
    if row is None:
        return KillSwitchState(active=True, reason="kill switch row missing", known=False)
    return KillSwitchState(active=row.kill_switch_active, reason=row.reason, known=True)


def activate_kill_switch(db: Session, actor: User, reason: str) -> KillSwitchState:
    """Any authenticated active user may halt trading. Halting is always allowed."""
    row = db.execute(select(TradingControl).where(TradingControl.id == 1).with_for_update())
    control = row.scalar_one_or_none()
    if control is None:
        control = TradingControl(id=1, kill_switch_active=True, reason=reason, changed_by=actor.id)
        db.add(control)
    else:
        control.kill_switch_active = True
        control.reason = reason
        control.changed_by = actor.id
    db.add(
        RiskEvent(
            event_type="kill_switch_activated",
            severity=RiskEventSeverity.CRITICAL,
            message=reason,
            details={"actor": str(actor.id)},
            requires_review=True,
        )
    )
    record_audit(
        db,
        action="kill_switch.activate",
        actor_user_id=actor.id,
        entity_type="trading_controls",
        entity_id="1",
        details={"reason": reason},
    )
    db.commit()
    log.critical("KILL SWITCH ACTIVATED by %s: %s", actor.email, reason)
    return KillSwitchState(active=True, reason=reason, known=True)


def deactivate_kill_switch(db: Session, actor: User, reason: str) -> KillSwitchState:
    """Only an admin may resume. Resuming does NOT enable live trading by itself."""
    if actor.role is not UserRole.ADMIN or not actor.is_active:
        record_audit(
            db,
            action="kill_switch.deactivate_denied",
            actor_user_id=actor.id,
            details={"reason": reason, "role": actor.role.value},
        )
        db.commit()
        raise NotAuthorizedError("only an active admin may deactivate the kill switch")

    control = db.execute(
        select(TradingControl).where(TradingControl.id == 1).with_for_update()
    ).scalar_one_or_none()
    if control is None:
        control = TradingControl(id=1, kill_switch_active=False, reason=reason, changed_by=actor.id)
        db.add(control)
    else:
        control.kill_switch_active = False
        control.reason = reason
        control.changed_by = actor.id
    db.add(
        RiskEvent(
            event_type="kill_switch_deactivated",
            severity=RiskEventSeverity.WARNING,
            message=reason,
            details={"actor": str(actor.id)},
        )
    )
    record_audit(
        db,
        action="kill_switch.deactivate",
        actor_user_id=actor.id,
        entity_type="trading_controls",
        entity_id="1",
        details={"reason": reason},
    )
    db.commit()
    log.warning("kill switch deactivated by %s: %s", actor.email, reason)
    return KillSwitchState(active=False, reason=reason, known=True)


def evaluate_execution_readiness(
    settings: Settings,
    kill_switch: KillSwitchState,
    *,
    broker_status: CheckStatus = "UNKNOWN",
    risk_engine_status: CheckStatus = "UNKNOWN",
) -> ExecutionReadiness:
    """System-level preconditions for order submission.

    This is NOT the per-trade gate evaluation (that is the Trade Risk Engine,
    Phase 9). It answers only: "could any order be submitted at all right now?"
    Broker and risk engine default to UNKNOWN because neither exists yet, which
    keeps live AND paper execution blocked in this build.
    """
    mode = settings.system_mode
    checks = [
        ReadinessCheck(
            "kill_switch",
            "FAIL" if kill_switch.active else "PASS",
            kill_switch.reason if kill_switch.active else "inactive",
        ),
        ReadinessCheck(
            "risk_engine",
            risk_engine_status,
            "trade risk engine health" if risk_engine_status == "PASS" else "not available",
        ),
    ]
    paper_ok = mode is SystemMode.PAPER and all(c.status == "PASS" for c in checks)

    checks += [
        ReadinessCheck(
            "system_mode",
            "PASS" if mode is SystemMode.LIVE else "FAIL",
            f"mode is {mode.value}",
        ),
        ReadinessCheck(
            "live_trading_flag",
            "PASS" if settings.live_trading_enabled else "FAIL",
            "AEGIS_LIVE_TRADING_ENABLED=" + ("true" if settings.live_trading_enabled else "false"),
        ),
        ReadinessCheck(
            "broker_health",
            broker_status,
            "broker reachable" if broker_status == "PASS" else "no healthy broker",
        ),
    ]
    live_ok = mode is SystemMode.LIVE and all(c.status == "PASS" for c in checks)

    return ExecutionReadiness(
        mode=mode,
        live_orders_permitted=live_ok,
        paper_orders_permitted=paper_ok,
        checks=checks,
    )
