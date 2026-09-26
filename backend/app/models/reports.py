"""Immutable analysis reports (spec §15, §81).

A report is the orchestrator's synthesis of every agent run for one stock at
one (as_of, knowledge_at). It stores the full JSON, the ids of the agent runs
it used and a content hash, so it can be audited and replayed. UPDATE and
DELETE are rejected by a database trigger.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"
    __table_args__ = (Index("ix_reports_stock_created", "stock_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    knowledge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    stance: Mapped[str] = mapped_column(String(30))
    composite_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    agent_run_ids: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report_hash: Mapped[str] = mapped_column(String(64))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
