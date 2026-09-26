"""Model monitoring: logged predictions and monitor runs (spec §27, §62)."""

from __future__ import annotations

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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelPrediction(Base):
    """What an active model predicted for a stock at a session, logged at the
    time (point in time). Immutable: realised outcomes are compared with it
    later to measure calibration decay."""

    __tablename__ = "model_predictions"
    __table_args__ = (
        UniqueConstraint("model_id", "stock_id", "session", name="uq_model_prediction"),
        Index("ix_model_predictions_model_session", "model_id", "session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    session: Mapped[date] = mapped_column(Date)  # feature date (last close used)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon: Mapped[int] = mapped_column(Integer)
    p_profit: Mapped[float] = mapped_column(Float)
    p_outperform: Mapped[float] = mapped_column(Float)


class ModelMonitorRun(Base):
    """One monitoring check of one model. Immutable record."""

    __tablename__ = "model_monitor_runs"
    __table_args__ = (
        CheckConstraint("status IN ('PASS','WARN','FAIL','UNKNOWN')", name="ck_monitor_status"),
        CheckConstraint("action IN ('none','retired')", name="ck_monitor_action"),
        Index("ix_model_monitor_runs_model_asof", "model_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    status: Mapped[str] = mapped_column(String(10))
    drift: Mapped[dict[str, Any]] = mapped_column(JSONB)
    calibration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    predictions_logged: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(String(10))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
