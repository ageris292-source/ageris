"""Deterministic technical indicators (spec §8, §50).

Conventions:
  * inputs are 1-D float64 arrays ordered oldest -> newest, one value per session
  * outputs have the same length; values that are not yet defined are NaN
    (never 0, never back-filled)
  * value[t] depends ONLY on inputs[0..t] — enforced by look-ahead tests
  * definitions are the common textbook ones; where several exist the choice
    is stated in the docstring so results are reproducible

The LLM never computes any of these.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

Array = npt.NDArray[np.float64]

CALCULATION_VERSION = "tech-1.0.0"
TRADING_DAYS_PER_YEAR = 252


def _s(x: Array) -> pd.Series:
    return pd.Series(np.asarray(x, dtype=np.float64))


def sma(x: Array, n: int) -> Array:
    return _s(x).rolling(n, min_periods=n).mean().to_numpy()


def ema(x: Array, n: int) -> Array:
    """alpha = 2/(n+1), recursive (adjust=False) and seeded from the first
    value; undefined until n observations exist."""
    return _s(x).ewm(span=n, min_periods=n, adjust=False).mean().to_numpy()


def rsi(close: Array, n: int = 14) -> Array:
    """Wilder RSI (1978): the first average gain/loss is the simple mean of the
    first n price changes; thereafter avg_t = (avg_{t-1} * (n-1) + x_t) / n.
    First value at index n. 100 if there were no losses, 50 if flat."""
    c = np.asarray(close, dtype=np.float64)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gains, losses = np.clip(d, 0, None), np.clip(-d, 0, None)
    g, lo = gains[:n].mean(), losses[:n].mean()

    def value(g: float, lo: float) -> float:
        if g + lo == 0:
            return 50.0
        return 100.0 * g / (g + lo)

    out[n] = value(g, lo)
    for i in range(n + 1, len(c)):
        g = (g * (n - 1) + gains[i - 1]) / n
        lo = (lo * (n - 1) + losses[i - 1]) / n
        out[i] = value(g, lo)
    return out


@dataclass(frozen=True)
class Macd:
    line: Array
    signal: Array
    histogram: Array


def macd(close: Array, fast: int = 12, slow: int = 26, signal: int = 9) -> Macd:
    line = ema(close, fast) - ema(close, slow)
    sig = _s(line).ewm(span=signal, min_periods=signal, adjust=False).mean().to_numpy()
    return Macd(line=line, signal=sig, histogram=line - sig)


@dataclass(frozen=True)
class Bollinger:
    middle: Array
    upper: Array
    lower: Array
    percent_b: Array
    bandwidth: Array


def bollinger(close: Array, n: int = 20, k: float = 2.0) -> Bollinger:
    """Population standard deviation (ddof=0), as in Bollinger's definition."""
    s = _s(close)
    mid = s.rolling(n, min_periods=n).mean()
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    width = upper - lower
    pct_b = (s - lower) / width.where(width != 0)
    bw = width / mid.where(mid != 0)
    return Bollinger(
        mid.to_numpy(), upper.to_numpy(), lower.to_numpy(), pct_b.to_numpy(), bw.to_numpy()
    )


def true_range(high: Array, low: Array, close: Array) -> Array:
    prev = _s(close).shift(1)
    h, lo = _s(high), _s(low)
    tr = pd.concat([h - lo, (h - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
    return tr.to_numpy()


def atr(high: Array, low: Array, close: Array, n: int = 14) -> Array:
    """Wilder ATR: first value is the mean of the first n true ranges, then
    ATR_t = (ATR_{t-1} * (n-1) + TR_t) / n."""
    tr = true_range(high, low, close)
    out = np.full(len(tr), np.nan)
    if len(tr) < n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


@dataclass(frozen=True)
class Adx:
    adx: Array
    plus_di: Array
    minus_di: Array


def adx(high: Array, low: Array, close: Array, n: int = 14) -> Adx:
    """Wilder's ADX. DM/TR are smoothed with Wilder running sums (first value =
    sum of the first n); ADX's first value is the mean of the first n DX."""
    size = len(close)
    plus_di = np.full(size, np.nan)
    minus_di = np.full(size, np.nan)
    adx_out = np.full(size, np.nan)
    if size < 2 * n + 1:
        return Adx(adx_out, plus_di, minus_di)

    up = np.diff(high)
    down = -np.diff(low)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(high, low, close)[1:]

    s_tr, s_p, s_m = tr[:n].sum(), plus_dm[:n].sum(), minus_dm[:n].sum()
    dx = np.full(size, np.nan)
    for j in range(n - 1, size - 1):  # j indexes the diff arrays; bar index = j + 1
        if j >= n:
            s_tr = s_tr - s_tr / n + tr[j]
            s_p = s_p - s_p / n + plus_dm[j]
            s_m = s_m - s_m / n + minus_dm[j]
        i = j + 1
        if s_tr == 0:
            plus_di[i] = minus_di[i] = 0.0
        else:
            plus_di[i] = 100 * s_p / s_tr
            minus_di[i] = 100 * s_m / s_tr
        denom = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if denom == 0 else 100 * abs(plus_di[i] - minus_di[i]) / denom

    first = 2 * n - 1  # n DX values available at bar indices n..2n-1
    adx_out[first] = np.nanmean(dx[n : first + 1])
    for i in range(first + 1, size):
        adx_out[i] = (adx_out[i - 1] * (n - 1) + dx[i]) / n
    return Adx(adx_out, plus_di, minus_di)


def obv(close: Array, volume: Array) -> Array:
    """On-balance volume starting at 0; unchanged closes add nothing."""
    direction = np.sign(np.diff(close, prepend=np.nan))
    direction[0] = 0.0
    return np.cumsum(np.nan_to_num(direction) * volume).astype(np.float64)


def realized_volatility(close: Array, n: int = 20) -> Array:
    """Annualised standard deviation (ddof=1) of daily log returns."""
    lr = _s(np.log(np.asarray(close, dtype=np.float64))).diff()
    out = lr.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return np.asarray(out.to_numpy(), dtype=np.float64)


def rate_of_change(close: Array, n: int) -> Array:
    s = _s(close)
    return (s / s.shift(n) - 1).to_numpy()


def rolling_max(x: Array, n: int) -> Array:
    return _s(x).rolling(n, min_periods=n).max().to_numpy()


def rolling_min(x: Array, n: int) -> Array:
    return _s(x).rolling(n, min_periods=n).min().to_numpy()


def rolling_percentile_rank(x: Array, n: int) -> Array:
    """Share of the last n values (including today) that are <= today's value."""
    s = _s(x)
    return (
        s.rolling(n, min_periods=n).apply(lambda w: float((w <= w[-1]).mean()), raw=True).to_numpy()
    )


# --------------------------------------------------------- swing structure --


def swing_points(values: Array, window: int, kind: str) -> list[int]:
    """Indices i confirmed as a swing high/low: values[i] is the strict extreme
    of [i-window, i+window]. A point is only confirmed once `window` later
    sessions exist, so the most recent `window` sessions never contain one —
    this is what keeps the detection free of look-ahead."""
    out: list[int] = []
    for i in range(window, len(values) - window):
        seg = values[i - window : i + window + 1]
        centre = values[i]
        if np.isnan(centre):
            continue
        others = np.delete(seg, window)
        is_high = kind == "high" and centre > np.nanmax(others)
        is_low = kind == "low" and centre < np.nanmin(others)
        if is_high or is_low:
            out.append(i)
    return out


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    last_index: int


def support_resistance(
    high: Array,
    low: Array,
    close: Array,
    *,
    lookback: int,
    window: int,
    tolerance: float,
    max_levels: int,
) -> tuple[list[Level], list[Level]]:
    """Cluster confirmed swing highs/lows within `tolerance` (relative) over the
    last `lookback` sessions. Returns (supports below the last close, nearest
    first; resistances above it, nearest first)."""
    start = max(0, len(close) - lookback)
    hi, lo = high[start:], low[start:]
    points = [(hi[i], i + start) for i in swing_points(hi, window, "high")]
    points += [(lo[i], i + start) for i in swing_points(lo, window, "low")]
    points.sort()
    clusters: list[list[tuple[float, int]]] = []
    for price, idx in points:
        if clusters and price <= clusters[-1][0][0] * (1 + tolerance):
            clusters[-1].append((price, idx))
        else:
            clusters.append([(price, idx)])
    levels = [
        Level(
            price=float(np.mean([p for p, _ in c])),
            touches=len(c),
            last_index=max(i for _, i in c),
        )
        for c in clusters
    ]
    last = float(close[-1])
    supports = sorted((lv for lv in levels if lv.price < last), key=lambda lv: -lv.price)
    resistances = sorted((lv for lv in levels if lv.price > last), key=lambda lv: lv.price)
    return supports[:max_levels], resistances[:max_levels]


def last_cross(a: Array, b: Array, lookback: int) -> tuple[str, int] | None:
    """Most recent sign change of (a - b) within the last `lookback` sessions:
    ("up", sessions_ago) or ("down", sessions_ago)."""
    d = a - b
    n = len(d)
    for i in range(n - 1, max(0, n - 1 - lookback), -1):
        if np.isnan(d[i]) or np.isnan(d[i - 1]):
            return None
        if d[i - 1] <= 0 < d[i]:
            return ("up", n - 1 - i)
        if d[i - 1] >= 0 > d[i]:
            return ("down", n - 1 - i)
    return None
