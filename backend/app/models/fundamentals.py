"""Company financial statement facts (Phase 4; spec §9, §31, §33).

One row per (company, period, line item, source, version). `available_at` is
when the figure became public: the stated publication time when the source
gives one, otherwise a conservative estimate from filing deadlines
(`availability_estimated = true`). Estimated rows are excluded from
historical point-in-time use.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FinancialFact(Base):
    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "period_type",
            "period_end",
            "line_item",
            "source",
            "data_version",
            name="uq_financials_version",
        ),
        CheckConstraint("period_type IN ('annual','quarterly')", name="ck_fin_period_type"),
        CheckConstraint("available_at::date >= period_end", name="ck_fin_available_after_period"),
        Index("ix_financials_lookup", "stock_id", "line_item", "period_type", "period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    period_type: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[date] = mapped_column(Date)  # effective date of the figure
    line_item: Mapped[str] = mapped_column(String(60))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(60))
    licensed: Mapped[bool] = mapped_column(Boolean)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    availability_estimated: Mapped[bool] = mapped_column(Boolean)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("data_ingestion_runs.id"))
