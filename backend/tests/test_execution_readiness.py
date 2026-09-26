"""System-level execution preconditions: fail closed, UNKNOWN never passes.

Property tests encode spec §72 invariants:
  * kill switch active  => no order may be permitted
  * any UNKNOWN          => no order may be permitted
  * mode != LIVE         => no live order may be permitted
  * this build (no live broker adapter) => no live order, whatever else holds
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.modes import SystemMode
from app.core.settings import Settings
from app.services.trading_controls import (
    KillSwitchState,
    evaluate_execution_readiness,
    read_kill_switch,
)

statuses = st.sampled_from(["PASS", "FAIL", "UNKNOWN"])


def settings(mode: SystemMode, live_flag: bool) -> Settings:
    # model_construct bypasses validators on purpose: even an inconsistent
    # configuration that slipped past startup must not permit live orders.
    return Settings.model_construct(system_mode=mode, live_trading_enabled=live_flag)


def ks(active: bool) -> KillSwitchState:
    return KillSwitchState(active=active, reason="test", known=True)


@given(
    mode=st.sampled_from(list(SystemMode)),
    live_flag=st.booleans(),
    kill=st.booleans(),
    broker=statuses,
    risk=statuses,
)
def test_live_permitted_iff_every_precondition_passes(
    mode: SystemMode, live_flag: bool, kill: bool, broker: Any, risk: Any
) -> None:
    # The precondition logic, as it would apply to a build WITH a live adapter.
    r = evaluate_execution_readiness(
        settings(mode, live_flag),
        ks(kill),
        broker_status=broker,
        risk_engine_status=risk,
        live_available=True,
    )
    # This build: never, whatever else is true.
    assert (
        evaluate_execution_readiness(
            settings(mode, live_flag), ks(kill), broker_status=broker, risk_engine_status=risk
        ).live_orders_permitted
        is False
    )
    expected = (
        mode is SystemMode.LIVE and live_flag and not kill and broker == "PASS" and risk == "PASS"
    )
    assert r.live_orders_permitted is expected
    if kill or broker == "UNKNOWN" or risk == "UNKNOWN" or mode is not SystemMode.LIVE:
        assert r.live_orders_permitted is False
    if r.live_orders_permitted:
        assert r.blocking_reasons == []


@given(mode=st.sampled_from(list(SystemMode)), kill=st.booleans(), risk=statuses)
def test_paper_orders_only_in_paper_mode(mode: SystemMode, kill: bool, risk: Any) -> None:
    r = evaluate_execution_readiness(settings(mode, False), ks(kill), risk_engine_status=risk)
    assert r.paper_orders_permitted is (mode is SystemMode.PAPER and not kill and risk == "PASS")
    # Paper mode can never permit live orders, whatever else is true.
    if mode is SystemMode.PAPER:
        assert r.live_orders_permitted is False


def test_research_mode_never_permits_any_order() -> None:
    r = evaluate_execution_readiness(
        settings(SystemMode.RESEARCH, True),
        ks(False),
        broker_status="PASS",
        risk_engine_status="PASS",
    )
    assert not r.live_orders_permitted
    assert not r.paper_orders_permitted


def test_current_build_blocks_everything_by_default() -> None:
    """No broker adapter and no trade risk engine exist yet => UNKNOWN => blocked."""
    r = evaluate_execution_readiness(settings(SystemMode.LIVE, True), ks(False))
    assert not r.live_orders_permitted
    assert {c.name for c in r.checks if c.status == "UNKNOWN"} == {"broker_health", "risk_engine"}


def test_fresh_install_starts_halted(db: Session) -> None:
    state = read_kill_switch(db)
    assert state.active and state.known


def test_missing_kill_switch_row_fails_closed(db: Session) -> None:
    db.execute(text("DELETE FROM trading_controls"))
    try:
        state = read_kill_switch(db)
        assert state.active is True
        assert state.known is False
    finally:
        db.rollback()


def test_unreadable_kill_switch_fails_closed() -> None:
    class BrokenSession:
        def get(self, *_: object) -> None:
            raise ConnectionError("database down")

        def rollback(self) -> None:
            pass

    state = read_kill_switch(BrokenSession())  # type: ignore[arg-type]
    assert state.active is True
    assert state.known is False
