"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in_seconds: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    role: str


class ComponentHealth(BaseModel):
    name: str
    healthy: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    system_mode: str
    demo_data: bool
    components: list[ComponentHealth]


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str = Field(min_length=5, max_length=1000)


class KillSwitchResponse(BaseModel):
    active: bool
    reason: str
    state_known: bool


class ReadinessCheckOut(BaseModel):
    name: str
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reason: str


class RiskStatusResponse(BaseModel):
    generated_at: datetime
    system_mode: str
    live_trading_enabled_flag: bool
    kill_switch: KillSwitchResponse
    live_orders_permitted: bool
    paper_orders_permitted: bool
    checks: list[ReadinessCheckOut]
    blocking_reasons: list[str]
    config_version: str
    config_fingerprint: str
    disclaimer: str
