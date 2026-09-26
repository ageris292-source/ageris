"""Return statistics shared by valuation (beta) and risk (Phase 7)."""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import numpy as np


def weekly_returns(series: list[tuple[date, float]]) -> dict[tuple[int, int], float]:
    """ISO-week -> simple return from the last close of the previous week to
    the last close of this week."""
    last: dict[tuple[int, int], float] = {}
    for d, v in series:
        iso = d.isocalendar()
        last[(iso.year, iso.week)] = v
    keys = sorted(last)
    return {k: last[k] / last[p] - 1 for p, k in pairwise(keys) if last[p] > 0}


def beta(
    stock: list[tuple[date, float]], market: list[tuple[date, float]], weeks: int
) -> tuple[float | None, int]:
    """OLS beta of weekly stock returns on weekly market returns over the last
    `weeks` common weeks. Returns (beta, n_obs); None if < 26 observations."""
    rs, rm = weekly_returns(stock), weekly_returns(market)
    common = sorted(set(rs) & set(rm))[-weeks:]
    if len(common) < 26:
        return None, len(common)
    x = np.array([rm[k] for k in common])
    y = np.array([rs[k] for k in common])
    var = float(np.var(x, ddof=1))
    if var == 0:
        return None, len(common)
    return float(np.cov(x, y, ddof=1)[0, 1] / var), len(common)


def change_over(series: list[tuple[date, float]], sessions: int) -> float | None:
    if len(series) <= sessions or series[-sessions - 1][1] == 0:
        return None
    return series[-1][1] / series[-sessions - 1][1] - 1
