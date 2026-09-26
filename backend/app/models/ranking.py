"""Daily rankings and alerts (spec §32-§35, §62)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RankingRun(Base):
    """One daily ranking. Immutable (trigger): later counterfactual analysis
    compares what the system said then with what happened afterwards."""

    __tablename__ = "ranking_runs"
    __table_args__ = (Index("ix_ranking_runs_as_of", "as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon: Mapped[int] = mapped_column(Integer)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id"))
    headline: Mapped[str] = mapped_column(String(80))
    qualified: Mapped[int] = mapped_column(Integer)
    evaluated: Mapped[int] = mapped_column(Integer)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    gate_failure_counts: Mapped[dict[str, int]] = mapped_column(JSONB)
    operational_blockers: Mapped[list[str]] = mapped_column(JSONB)
    config_fingerprint: Mapped[str] = mapped_column(String(64))


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_alert_dedupe"),
        CheckConstraint("severity IN ('info','warning','critical')", name="ck_alert_severity"),
        Index("ix_alerts_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    deliveries: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
