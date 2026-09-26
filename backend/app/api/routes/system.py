from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app import __version__
from app.api.deps import CurrentUser, DbSession
from app.core.config_file import get_config
from app.core.rate_limit import redis_healthy
from app.core.settings import get_settings
from app.db.session import database_healthy
from app.live.broker import get_broker, readiness_status
from app.schemas import (
    ComponentHealth,
    HealthResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    ReadinessCheckOut,
    RiskStatusResponse,
)
from app.services.trading_controls import (
    NotAuthorizedError,
    activate_kill_switch,
    deactivate_kill_switch,
    evaluate_execution_readiness,
    read_kill_switch,
)
from app.trade.gates import self_test as engine_self_test

router = APIRouter()

DISCLAIMER = (
    "Aegis produces model-based estimates, not guarantees of profit. "
    "No trade is ever certain to make money."
)


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    s = get_settings()
    components = [
        ComponentHealth(name="database", healthy=database_healthy()),
        ComponentHealth(name="redis", healthy=redis_healthy()),
    ]
    return HealthResponse(
        status="ok" if all(c.healthy for c in components) else "degraded",
        version=__version__,
        environment=s.environment.value,
        system_mode=s.system_mode.value,
        demo_data=s.demo_data,
        components=components,
    )


@router.get("/risk/status", response_model=RiskStatusResponse, tags=["risk"])
def risk_status(db: DbSession, _user: CurrentUser) -> RiskStatusResponse:
    s = get_settings()
    cfg = get_config()
    ks = read_kill_switch(db)
    engine_ok, _ = engine_self_test(cfg)
    readiness = evaluate_execution_readiness(
        s,
        ks,
        broker_status=readiness_status(get_broker()),
        risk_engine_status="PASS" if engine_ok else "FAIL",
    )
    return RiskStatusResponse(
        generated_at=datetime.now(UTC),
        system_mode=s.system_mode.value,
        live_trading_enabled_flag=s.live_trading_enabled,
        kill_switch=KillSwitchResponse(active=ks.active, reason=ks.reason, state_known=ks.known),
        live_orders_permitted=readiness.live_orders_permitted,
        paper_orders_permitted=readiness.paper_orders_permitted,
        checks=[
            ReadinessCheckOut(name=c.name, status=c.status, reason=c.reason)
            for c in readiness.checks
        ],
        blocking_reasons=readiness.blocking_reasons,
        config_version=cfg.config_version,
        config_fingerprint=cfg.fingerprint(),
        disclaimer=DISCLAIMER,
    )


@router.post("/trading/kill-switch", response_model=KillSwitchResponse, tags=["risk"])
def kill_switch(body: KillSwitchRequest, db: DbSession, user: CurrentUser) -> KillSwitchResponse:
    if body.active:
        state = activate_kill_switch(db, user, body.reason)
    else:
        try:
            state = deactivate_kill_switch(db, user, body.reason)
        except NotAuthorizedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return KillSwitchResponse(active=state.active, reason=state.reason, state_known=state.known)
