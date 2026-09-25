"""Market-data tables (Phase 2).

Provenance rule (spec §31): every stored data point carries source,
retrieved_at, effective_at, available_at, published_at (nullable when the
source does not state it) and data_version. Revisions never overwrite: a
changed value is inserted as a new data_version and the disagreement is
preserved in data_conflicts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

PRICE = Numeric(18, 4)
BASES = "('raw','split_adjusted','total_return')"


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", name="uq_stocks_symbol_exchange"),
        CheckConstraint("exchange IN ('NSE','BSE')", name="ck_stocks_exchange"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20))
    exchange: Mapped[str] = mapped_column(String(3))
    name: Mapped[str | None] = mapped_column(String(200))
    isin: Mapped[str | None] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    sector: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    listed_on: Mapped[date | None] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataIngestionRun(Base):
    __tablename__ = "data_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','succeeded_with_warnings','rejected','failed')",
            name="ck_ingestion_status",
        ),
        Index("ix_ingestion_stock_started", "stock_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    provider: Mapped[str] = mapped_column(String(60))
    licensed: Mapped[bool] = mapped_column(Boolean)
    basis: Mapped[str | None] = mapped_column(String(20))
    requested_start: Mapped[date] = mapped_column(Date)
    requested_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    rows_revised: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float | None] = mapped_column(Float)
    usable: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class Price(Base):
    """Daily bar. Table name per spec §62 (`prices`)."""

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "interval",
            "basis",
            "source",
            "session_date",
            "data_version",
            name="uq_prices_version",
        ),
        CheckConstraint(f"basis IN {BASES}", name="ck_prices_basis"),
        CheckConstraint("interval = '1d'", name="ck_prices_interval"),
        CheckConstraint(
            "low > 0 AND high >= low AND open BETWEEN low AND high "
            "AND close BETWEEN low AND high AND volume >= 0",
            name="ck_prices_ohlcv",
        ),
        CheckConstraint("available_at >= effective_at", name="ck_prices_availability"),
        Index("ix_prices_lookup", "stock_id", "basis", "session_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    interval: Mapped[str] = mapped_column(String(4), default="1d")
    basis: Mapped[str] = mapped_column(String(20))
    session_date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(60))
    licensed: Mapped[bool] = mapped_column(Boolean)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # session close
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # close + lag
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("data_ingestion_runs.id"))


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "stock_id", "kind", "ex_date", "source", "data_version", name="uq_corp_action_version"
        ),
        CheckConstraint("kind IN ('split','dividend')", name="ck_corp_action_kind"),
        CheckConstraint(
            "(kind = 'split' AND numerator > 0 AND denominator > 0 AND amount IS NULL) OR "
            "(kind = 'dividend' AND amount > 0 AND numerator IS NULL AND denominator IS NULL)",
            name="ck_corp_action_fields",
        ),
        CheckConstraint(f"amount_basis IS NULL OR amount_basis IN {BASES}", name="ck_amount_basis"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    kind: Mapped[str] = mapped_column(String(10))
    ex_date: Mapped[date] = mapped_column(Date)
    numerator: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    denominator: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount_basis: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(60))
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("data_ingestion_runs.id"))


class DataConflict(Base):
    """A source changed a value it previously reported. Both are kept."""

    __tablename__ = "data_conflicts"
    __table_args__ = (Index("ix_data_conflicts_stock", "stock_id", "detected_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    entity: Mapped[str] = mapped_column(String(30))  # price | corporate_action
    key: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(60))
    previous_version: Mapped[int] = mapped_column(Integer)
    new_version: Mapped[int] = mapped_column(Integer)
    previous_value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("data_ingestion_runs.id"))
