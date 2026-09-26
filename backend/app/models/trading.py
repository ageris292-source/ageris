"""Trade proposals, risk decisions and portfolio equity snapshots (spec §17-§19, §62).

Proposals and decisions are immutable: UPDATE/DELETE are rejected by
triggers. A decision stores every gate result, the input context snapshot,
the config fingerprint and a content hash, so it can be audited and
replayed exactly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TradeProposalRecord(Base):
    __tablename__ = "trade_proposals"
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_proposal_side"),
        CheckConstraint("mode IN ('paper','live')", name="ck_proposal_mode"),
        CheckConstraint("quantity > 0", name="ck_proposal_qty"),
        Index("ix_proposals_portfolio_created", "portfolio_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.id"))
    ticker: Mapped[str] = mapped_column(String(30))
    side: Mapped[str] = mapped_column(String(4))
    mode: Mapped[str] = mapped_column(String(5))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    target: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    horizon_days: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TradeDecisionRecord(Base):
    __tablename__ = "trade_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVED','REJECTED')", name="ck_decision_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("trade_proposals.id"), unique=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str] = mapped_column(String(10))
    first_failure: Mapped[str | None] = mapped_column(String(40))
    failed_gates: Mapped[list[str]] = mapped_column(JSONB)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    costs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(40))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    decision_hash: Mapped[str] = mapped_column(String(64))


class PortfolioSnapshot(Base):
    """End-of-day (or post-execution) equity marks used by the loss-limit gate."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_snapshots_portfolio_taken", "portfolio_id", "taken_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    invested: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))
