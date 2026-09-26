"""Paper trading: orders, executions, trade theses (spec §28-§31, §62).

Orders are created only from an APPROVED trade decision, by a human with the
approver role, with an idempotency key, after a fresh pre-order re-check by
the Trade Risk Engine. Executions are immutable (trigger). Every thesis
(stop, target, horizon, invalidation) is monitored after entry.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_paper_order_idem"),
        CheckConstraint("side IN ('buy','sell')", name="ck_paper_order_side"),
        CheckConstraint("status IN ('FILLED','REJECTED')", name="ck_paper_order_status"),
        Index("ix_paper_orders_portfolio", "portfolio_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision_id: Mapped[int] = mapped_column(ForeignKey("trade_decisions.id"))
    recheck_decision_id: Mapped[int | None] = mapped_column(ForeignKey("trade_decisions.id"))
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    ticker: Mapped[str] = mapped_column(String(30))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperExecution(Base):
    __tablename__ = "paper_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), unique=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    fill_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    notional: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fee_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB)
    realised_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cash_after: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fill_model: Mapped[str] = mapped_column(String(60))


class Thesis(Base):
    __tablename__ = "theses"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','CLOSED')", name="ck_thesis_status"),
        Index("ix_theses_portfolio_status", "portfolio_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    ticker: Mapped[str] = mapped_column(String(30))
    entry_order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    target: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    horizon_end: Mapped[date] = mapped_column(Date)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_reports.id"))
    invalidation: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ThesisEvent(Base):
    __tablename__ = "thesis_events"
    __table_args__ = (
        UniqueConstraint("thesis_id", "kind", "session", name="uq_thesis_event_once"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text)
    exit_proposal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_proposals.id"))
    exit_decision: Mapped[str | None] = mapped_column(String(10))
