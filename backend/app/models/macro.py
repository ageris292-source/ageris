"""Macro observations (spec §11, §62 `macro_data`).

Covers annual official statistics (World Bank), daily market series (index
levels, VIX, FX, oil) and manual entries (e.g. RBI repo rate) with their
stated source and publication time. Versioned and immutable like prices.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MacroObservation(Base):
    __tablename__ = "macro_data"
    __table_args__ = (
        UniqueConstraint(
            "series", "period_date", "source", "data_version", name="uq_macro_version"
        ),
        CheckConstraint("frequency IN ('daily','annual','event')", name="ck_macro_frequency"),
        Index("ix_macro_series_date", "series", "period_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series: Mapped[str] = mapped_column(String(60))
    frequency: Mapped[str] = mapped_column(String(10))
    period_date: Mapped[date] = mapped_column(Date)  # effective date
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(120))
    licensed: Mapped[bool] = mapped_column(Boolean)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    availability_estimated: Mapped[bool] = mapped_column(Boolean)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    entered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
