"""Deterministic risk statistics (spec §13) on daily data.

All functions are pure and take plain sequences so they can be verified
against hand calculations. Returns are simple daily returns; annualisation
uses sqrt(trading days). VaR/CVaR are historical (non-parametric) and are
reported as positive loss fractions of position value for one day.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np


def returns(closes: Sequence[float]) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    if len(c) < 2:
        return np.array([])
    if np.any(c <= 0):
        raise ValueError("prices must be positive")
    out: np.ndarray = c[1:] / c[:-1] - 1
    return out


def annual_volatility(r: np.ndarray, days: int = 252) -> float | None:
    return float(np.std(r, ddof=1) * math.sqrt(days)) if len(r) >= 2 else None


@dataclass(frozen=True)
class Drawdown:
    max_drawdown: float  # positive fraction, 0 = never below a prior peak
    peak: date | None
    trough: date | None
    current: float  # drawdown of the last point from the running peak


def max_drawdown(points: Sequence[tuple[date, float]]) -> Drawdown:
    peak_v, peak_d = -math.inf, None
    best = Drawdown(0.0, None, None, 0.0)
    worst, w_peak, w_trough = 0.0, None, None
    for d, v in points:
        if v > peak_v:
            peak_v, peak_d = v, d
        dd = 1 - v / peak_v if peak_v > 0 else 0.0
        if dd > worst:
            worst, w_peak, w_trough = dd, peak_d, d
    if not points:
        return best
    current = 1 - points[-1][1] / peak_v if peak_v > 0 else 0.0
    return Drawdown(worst, w_peak, w_trough, current)


def sharpe(r: np.ndarray, rf_annual: float, days: int = 252) -> float | None:
    vol = annual_volatility(r, days)
    if vol is None or vol == 0:
        return None
    return float((np.mean(r) * days - rf_annual) / vol)


def sortino(r: np.ndarray, rf_annual: float, days: int = 252) -> float | None:
    """Downside deviation measured against the daily risk-free target, over
    all observations (the standard 'target downside deviation')."""
    if len(r) < 2:
        return None
    target = rf_annual / days
    downside = np.minimum(r - target, 0.0)
    dd = float(np.sqrt(np.mean(downside**2)) * math.sqrt(days))
    if dd == 0:
        return None
    return float((np.mean(r) * days - rf_annual) / dd)


def var_cvar(r: np.ndarray, confidence: float) -> tuple[float | None, float | None]:
    """Historical one-day VaR and CVaR (expected shortfall) as positive losses."""
    if len(r) < 20:
        return None, None
    q = float(np.quantile(r, 1 - confidence, method="lower"))
    tail = r[r <= q]
    return max(0.0, -q), max(0.0, -float(np.mean(tail)))


def aligned_returns(
    a: Sequence[tuple[date, float]], b: Sequence[tuple[date, float]]
) -> tuple[np.ndarray, np.ndarray, list[date]]:
    """Daily returns of two series over their common dates only (returns are
    computed between consecutive COMMON dates, so a holiday in one market
    never produces a spurious multi-day return in the other)."""
    da, db_ = dict(a), dict(b)
    common = sorted(set(da) & set(db_))
    if len(common) < 2:
        return np.array([]), np.array([]), []
    ra = returns([da[d] for d in common])
    rb = returns([db_[d] for d in common])
    return ra, rb, common[1:]


def beta_daily(stock: np.ndarray, market: np.ndarray) -> float | None:
    if len(stock) < 30 or len(stock) != len(market):
        return None
    var = float(np.var(market, ddof=1))
    if var == 0:
        return None
    return float(np.cov(market, stock, ddof=1)[0, 1] / var)


def average_daily_traded_value(
    closes: Sequence[float], volumes: Sequence[int], window: int
) -> float | None:
    if len(closes) < window or len(volumes) < window:
        return None
    c = np.asarray(closes[-window:], dtype=float)
    v = np.asarray(volumes[-window:], dtype=float)
    return float(np.mean(c * v))


def correlation_matrix(rets: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    keys = sorted(rets)
    if not keys:
        return {}
    m = np.corrcoef(np.vstack([rets[k] for k in keys])) if len(keys) > 1 else np.array([[1.0]])
    return {
        a: {b: round(float(m[i, j]), 4) for j, b in enumerate(keys)} for i, a in enumerate(keys)
    }


def herfindahl(weights: Sequence[float]) -> float:
    total = sum(abs(w) for w in weights)
    if total == 0:
        return 0.0
    return float(sum((abs(w) / total) ** 2 for w in weights))
