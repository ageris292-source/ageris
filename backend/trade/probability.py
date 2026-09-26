"""Where the engine gets its probability estimate (spec §21, §26).

The proposal never supplies its own probability. The engine asks the
registered source, which in production is the calibrated walk-forward model
(Phase 10). With no active model (or no honest estimate), the estimate is None
and every gate that needs it is UNKNOWN, i.e. the proposal is rejected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Stock


@dataclass(frozen=True)
class ProbabilityEstimate:
    model_id: str
    horizon_days: int
    as_of_date: date
    p_profit: float  # calibrated P(net return > 0 over the horizon)
    p_outperform: float  # calibrated P(return > benchmark over the horizon)
    expected_return: float  # model-implied gross return over the horizon
    calibrated: bool
    calibration_error: float  # expected calibration error on out-of-sample folds
    oos_periods: int  # walk-forward folds evaluated out of sample


ProbabilitySource = Callable[[Session, Stock, datetime, int], ProbabilityEstimate | None]


def _registry(db: Session, s: Stock, as_of: datetime, h: int) -> ProbabilityEstimate | None:
    """Default source: the active calibrated model in the registry (Phase 10)."""
    from app.backtest.registry import estimate as registry_estimate

    return registry_estimate(db, s, as_of, h)


_source: ProbabilitySource = _registry


def set_source(fn: ProbabilitySource | None) -> None:
    """Override the source (tests); None restores the model registry."""
    global _source
    _source = fn or _registry


def estimate(
    db: Session, stock: Stock, as_of: datetime, horizon: int
) -> ProbabilityEstimate | None:
    return _source(db, stock, as_of, horizon)
