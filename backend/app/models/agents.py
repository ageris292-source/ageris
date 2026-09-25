"""Agent run records and the feature store (Phase 3; spec §61, §62, §77)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','insufficient_data','data_unusable','failed')", name="ck_agent_status"
        ),
        Index("ix_agent_runs_stock_asof", "stock_id", "agent", "as_of"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent: Mapped[str] = mapped_column(String(40))
    agent_version: Mapped[str] = mapped_column(String(40))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    knowledge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    data_snapshot_id: Mapped[str | None] = mapped_column(String(64))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class AgentOutputRecord(Base):
    """The full, typed AgentOutput as produced. Immutable (trigger)."""

    __tablename__ = "agent_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TechnicalIndicator(Base):
    """Feature store row (spec §77): one value of one feature for one session,
    tied to the exact input snapshot and calculation version that produced it."""

    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "feature_name",
            "session_date",
            "calculation_version",
            "data_snapshot_id",
            name="uq_feature_value",
        ),
        Index("ix_features_lookup", "stock_id", "feature_name", "session_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    feature_name: Mapped[str] = mapped_column(String(60))
    session_date: Mapped[date] = mapped_column(Date)  # the "timestamp" of the feature
    value: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(60))
    basis: Mapped[str] = mapped_column(String(20))
    calculation_version: Mapped[str] = mapped_column(String(40))
    availability_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_snapshot_id: Mapped[str] = mapped_column(String(64))
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
