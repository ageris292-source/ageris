"""ORM models. Phase 1: identity, audit, risk events, control state. Phase 2: market data.

Market, research, backtest and execution tables are added by the phase that
first needs them, each with its own migration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserRole(enum.StrEnum):
    ADMIN = "admin"  # may reactivate trading after a kill switch / circuit breaker
    ANALYST = "analyst"  # research + may activate (never deactivate) the kill switch


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e])
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Append-only. UPDATE/DELETE are rejected by a database trigger."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    system_mode: Mapped[str] = mapped_column(String(20))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RiskEventSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (Index("ix_risk_events_type_time", "event_type", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(100))
    severity: Mapped[RiskEventSeverity] = mapped_column(
        Enum(
            RiskEventSeverity,
            name="risk_event_severity",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TradingControl(Base):
    """Singleton row (id=1) holding the kill switch. Missing row == active (fail closed)."""

    __tablename__ = "trading_controls"
    __table_args__ = (CheckConstraint("id = 1", name="ck_trading_controls_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Phase 2 market-data tables (imported here so they register on Base.metadata).
# Phase 3 agent runs + feature store.
from app.models.agents import AgentOutputRecord, AgentRun, TechnicalIndicator  # noqa: E402
from app.models.market import (  # noqa: E402
    CorporateAction,
    DataConflict,
    DataIngestionRun,
    Price,
    Stock,
)

__all__ = [
    "AgentOutputRecord",
    "AgentRun",
    "AuditLog",
    "CorporateAction",
    "DataConflict",
    "DataIngestionRun",
    "Price",
    "RiskEvent",
    "RiskEventSeverity",
    "Stock",
    "TechnicalIndicator",
    "TradingControl",
    "User",
    "UserRole",
]
