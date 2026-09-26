"""Backtest runs and model versions (spec §22-§27, §62).

A backtest run is a reproducibility record: parameters, universe, input data
hash, config fingerprint, seed and library versions, plus every fold's
metrics. A model version is the calibrated model trained on all data
available at the run's cut-off; it becomes usable by the Trade Risk Engine
only after an admin activates it, and only for as_of dates on or after
`valid_from` (no model trained on the future is ever applied to the past).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_backtest_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    status: Mapped[str] = mapped_column(String(10))
    horizon: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    knowledge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    universe: Mapped[list[str]] = mapped_column(JSONB)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reproducibility: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_hash: Mapped[str | None] = mapped_column(String(64))
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    survivorship_bias: Mapped[str] = mapped_column(String(10))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    folds: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    simulation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint("status IN ('candidate','active','retired')", name="ck_model_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    name: Mapped[str] = mapped_column(String(80))
    horizon: Mapped[int] = mapped_column(Integer)
    feature_version: Mapped[str] = mapped_column(String(40))
    features: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    # availability of the newest label used in training (session close + lag)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trained_rows: Mapped[int] = mapped_column(Integer)
    calibration_error: Mapped[float] = mapped_column(Float)  # OOS ECE of P(profit)
    oos_periods: Mapped[int] = mapped_column(Integer)
    auc: Mapped[float | None] = mapped_column(Float)
    expected_return_map: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    artifact: Mapped[bytes] = mapped_column(LargeBinary)  # JSON: both calibrated models
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    # Training feature distribution (decile edges + proportions) that live
    # data is compared with for drift (Phase 13). None = cannot be monitored.
    feature_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
