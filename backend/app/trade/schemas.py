"""Trade Risk Engine schemas (spec §17-§19)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GateStatus = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]


class TradeProposal(BaseModel):
    """A request to trade. Whoever writes it (user, agent, LLM) is NOT trusted:
    every number that matters is re-derived or checked by the engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=10_000_000)
    entry_price: Decimal = Field(gt=0, max_digits=14, decimal_places=4)  # limit price
    stop_loss: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    target: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    horizon_days: int = Field(default=20, ge=1, le=2520)  # TRADING days (sessions)
    portfolio_id: int
    mode: Literal["paper", "live"] = "paper"
    quoted_spread_bps: float | None = Field(default=None, ge=0, le=10_000)
    report_id: int | None = None
    rationale: str = Field(default="", max_length=2000)


class GateResult(BaseModel):
    order: int
    name: str
    status: GateStatus
    value: float | str | None = None
    threshold: float | str | None = None
    reason: str


class CostBreakdown(BaseModel):
    schedule: str
    buy_bps: float
    sell_bps: float
    impact_bps_each_side: float
    financing_fraction: float
    round_trip_fraction: float
    order_value: float
    participation_pct_of_adv: float | None
    items_bps: dict[str, float]


class TradeRiskDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    engine_version: str
    evaluated_at: datetime
    as_of: datetime
    proposal: TradeProposal
    gates: list[GateResult]
    failed_gates: list[str]
    first_failure: str | None
    requires_human_approval: bool
    costs: CostBreakdown | None
    metrics: dict[str, float | None]
    context: dict[str, Any]
    config_fingerprint: str
    decision_hash: str = ""
