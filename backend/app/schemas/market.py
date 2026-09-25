"""Market-data API schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.market_data.types import PriceBasis

UNLICENSED_NOTICE = (
    "Source is unlicensed: usable for research only. It will never be accepted "
    "for paper or live trading decisions."
)


class AddStockRequest(BaseModel):
    ticker: str = Field(examples=["TCS.NS"], min_length=4, max_length=24)


class IngestRequest(BaseModel):
    start: date | None = None
    end: date | None = None


class FreshnessOut(BaseModel):
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    latest_session: date | None
    expected_session: date | None
    sessions_behind: int | None
    reason: str


class IngestionRunOut(BaseModel):
    id: int
    provider: str
    licensed: bool
    basis: str | None
    status: str
    requested_start: date
    requested_end: date
    started_at: datetime
    finished_at: datetime | None
    retrieved_at: datetime | None
    rows_received: int
    rows_inserted: int
    rows_unchanged: int
    rows_revised: int
    rows_rejected: int
    quality_score: float | None
    usable: bool
    error: str | None
    validation_report: dict[str, Any]


class StockSummary(BaseModel):
    ticker: str
    symbol: str
    exchange: str
    name: str | None
    currency: str
    latest_session: date | None
    freshness: FreshnessOut
    last_run_status: str | None


class BarOut(BaseModel):
    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str
    data_version: int
    retrieved_at: datetime
    effective_at: datetime
    available_at: datetime


class CorporateActionOut(BaseModel):
    kind: str
    ex_date: date
    numerator: Decimal | None
    denominator: Decimal | None
    amount: Decimal | None


class DataQualityOut(BaseModel):
    window_start: date | None
    window_end: date | None
    usable: bool
    quality_score: float
    expected_sessions: int
    missing_session_count: int
    coverage: float
    minimum_score_required: float  # trade_gates.minimum_data_quality_score
    issues: list[dict[str, Any]]


class StockDetail(StockSummary):
    latest_bar: BarOut | None
    stored_basis: str | None
    source: str | None
    licensed: bool | None
    licensing_notice: str | None
    data_quality: DataQualityOut | None
    corporate_actions: list[CorporateActionOut]
    recent_runs: list[IngestionRunOut]
    open_conflicts: int


class PriceSeriesOut(BaseModel):
    ticker: str
    basis: PriceBasis
    stored_basis: PriceBasis | None
    derived: bool
    source: str | None
    licensed: bool | None
    licensing_notice: str | None
    as_of: datetime | None
    knowledge_at: datetime | None = None
    currency: str = "INR"
    bars: list[BarOut]


class ProviderStatusOut(BaseModel):
    name: str
    enabled: bool
    licensed: bool
    available: bool
    reason: str
