"""Per-user web-app features: named watchlists, personal price alerts and the
research / trade journal.

None of these affect analysis, ranking or any trade decision. A price alert
only informs; it never proposes or places an order.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


PRICE_CONDITIONS = (
    "price_above",
    "price_below",
    "day_change_up",
    "day_change_down",
    "rsi_above",
    "rsi_below",
)


class PriceAlert(Base):
    """A personal rule checked against each NEW end-of-day close.

    One-shot rules switch themselves off after firing. Repeating rules re-arm
    once the condition stops being true, so a price that stays above a level
    fires once, not every day."""

    __tablename__ = "price_alerts"
    __table_args__ = (
        CheckConstraint(
            "condition IN ('price_above','price_below','day_change_up','day_change_down',"
            "'rsi_above','rsi_below')",
            name="ck_price_alert_condition",
        ),
        CheckConstraint("threshold > 0", name="ck_price_alert_threshold_pos"),
        CheckConstraint("importance IN ('normal','high')", name="ck_price_alert_importance"),
        Index("ix_price_alerts_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id", ondelete="CASCADE"))
    condition: Mapped[str] = mapped_column(String(20))
    # Rupees for price rules; percent (e.g. 3 = 3%) for day-change rules; RSI points.
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    repeat: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    importance: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    armed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_session: Mapped[date | None] = mapped_column(Date)
    last_value: Mapped[float | None] = mapped_column(Float)
    last_status: Mapped[str | None] = mapped_column(String(120))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


JOURNAL_KINDS = ("note", "entry", "exit", "review")


class JournalEntry(Base):
    """Private research note or trade-journal entry. Optional links to a stock
    and to a paper order; the text is the user's own, never generated."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('note','entry','exit','review')", name="ck_journal_kind"),
        Index("ix_journal_user_created", "user_id", "created_at"),
        Index("ix_journal_user_stock", "user_id", "stock_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10), default="note")
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
