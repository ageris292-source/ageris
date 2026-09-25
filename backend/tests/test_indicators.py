"""Indicators: independent oracle (the `ta` library), hand-worked values,
invariants, and look-ahead freedom."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import ta
from hypothesis import given, settings
from hypothesis import strategies as st

from app.analysis import indicators as ind
from tests.market_helpers import load

RNG = np.random.default_rng(7)
N = 500
C = 100 * np.exp(np.cumsum(RNG.normal(0, 0.02, N)))
H = C * (1 + np.abs(RNG.normal(0, 0.01, N)))
L = C * (1 - np.abs(RNG.normal(0, 0.01, N)))
V = RNG.integers(100_000, 1_000_000, N).astype(float)


def _real() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    q = load("yahoo_reliance_ns_2023_2024.json")["chart"]["result"][0]["indicators"]["quote"][0]
    return (np.array(q["high"], float), np.array(q["low"], float), np.array(q["close"], float))


def same(a: np.ndarray, b: np.ndarray, tol: float = 1e-9) -> None:
    assert np.array_equal(np.isnan(a), np.isnan(b)), "undefined regions differ"
    m = ~np.isnan(a)
    assert np.max(np.abs(a[m] - b[m])) < tol


# ------------------------------------------------------------------ oracle --


@pytest.mark.parametrize("data", ["synthetic", "reliance"])
def test_matches_independent_implementation(data: str) -> None:
    h, lo, c = (H, L, C) if data == "synthetic" else _real()
    cs, hs, ls = pd.Series(c), pd.Series(h), pd.Series(lo)
    same(ind.sma(c, 20), ta.trend.SMAIndicator(cs, 20).sma_indicator().to_numpy())
    same(ind.ema(c, 12), ta.trend.EMAIndicator(cs, 12).ema_indicator().to_numpy())
    m, ref = ind.macd(c), ta.trend.MACD(cs)
    same(m.line, ref.macd().to_numpy())
    same(m.signal, ref.macd_signal().to_numpy())
    same(m.histogram, ref.macd_diff().to_numpy())
    bb, rb = ind.bollinger(c, 20, 2.0), ta.volatility.BollingerBands(cs, 20, 2)
    same(bb.upper, rb.bollinger_hband().to_numpy())
    same(bb.lower, rb.bollinger_lband().to_numpy())
    same(bb.percent_b, rb.bollinger_pband().to_numpy())
    atr_ref = ta.volatility.AverageTrueRange(hs, ls, cs, 14).average_true_range()
    same(ind.atr(h, lo, c, 14), atr_ref.replace(0, np.nan).to_numpy())
    adx_ref = ta.trend.ADXIndicator(hs, ls, cs, 14).adx()
    same(ind.adx(h, lo, c, 14).adx, adx_ref.replace(0, np.nan).to_numpy(), 1e-9)


def test_rsi_converges_to_reference_and_starts_at_n() -> None:
    """`ta` seeds Wilder smoothing differently (a phantom first change). Ours is
    the classic seed; the two must converge once the seed has decayed."""
    ours = ind.rsi(C, 14)
    ref = ta.momentum.RSIIndicator(pd.Series(C), 14).rsi().to_numpy()
    assert np.isnan(ours[13]) and not np.isnan(ours[14])
    assert np.max(np.abs(ours[300:] - ref[300:])) < 1e-6


# ------------------------------------------------------------ hand-worked --


def test_hand_values() -> None:
    x = np.array([1.0, 2, 3, 4, 5])
    assert list(ind.sma(x, 3)[2:]) == [2.0, 3.0, 4.0]
    assert ind.rsi(np.arange(1.0, 20.0), 14)[-1] == 100.0  # only gains
    assert ind.rsi(np.arange(20.0, 1.0, -1), 14)[-1] == 0.0  # only losses
    assert ind.rsi(np.full(20, 5.0), 14)[-1] == 50.0  # flat
    # Wilder first value: mean of first n gains/losses (n=2): changes +2, -1
    assert ind.rsi(np.array([10.0, 12, 11]), 2)[2] == pytest.approx(100 * 1 / 1.5)
    assert list(ind.obv(np.array([10.0, 11, 11, 10]), np.array([5.0, 7, 9, 4]))) == [0, 7, 7, 3]
    tr_const = ind.atr(np.full(30, 11.0), np.full(30, 9.0), np.full(30, 10.0), 14)
    assert tr_const[-1] == pytest.approx(2.0)
    assert ind.rate_of_change(np.array([100.0, 110, 121]), 2)[-1] == pytest.approx(0.21)
    flat_bb = ind.bollinger(np.full(30, 7.0), 20, 2)
    assert flat_bb.upper[-1] == flat_bb.lower[-1] == 7.0 and np.isnan(flat_bb.percent_b[-1])


def test_last_cross() -> None:
    a = np.array([1.0, 1, 1, 3, 3])
    b = np.array([2.0, 2, 2, 2, 2])
    assert ind.last_cross(a, b, 5) == ("up", 1)
    assert ind.last_cross(b, a, 5) == ("down", 1)
    assert ind.last_cross(a, b, 1) is None


def test_support_and_resistance_levels() -> None:
    # Oscillate between ~90 and ~110 then settle at 100.
    wave = 100 + 10 * np.sin(np.linspace(0, 8 * np.pi, 200))
    c = np.concatenate([wave, np.full(10, 100.0)])
    sup, res = ind.support_resistance(
        c + 0.5, c - 0.5, c, lookback=250, window=5, tolerance=0.015, max_levels=3
    )
    assert sup and res
    assert sup[0].price == pytest.approx(89.5, abs=0.6) and sup[0].touches >= 3
    assert res[0].price == pytest.approx(110.5, abs=0.6) and res[0].touches >= 3


# ------------------------------------------------------------- invariants --


def test_bounds() -> None:
    r = ind.rsi(C, 14)
    a = ind.adx(H, L, C, 14)
    for arr in (r, a.adx, a.plus_di, a.minus_di):
        v = arr[~np.isnan(arr)]
        assert v.min() >= 0 and v.max() <= 100
    assert np.nanmin(ind.atr(H, L, C, 14)) >= 0
    assert np.nanmin(ind.realized_volatility(C, 20)) >= 0


# ------------------------------------------------------------- look-ahead --

FNS = {
    "sma": lambda h, lo, c, v: ind.sma(c, 20),
    "ema": lambda h, lo, c, v: ind.ema(c, 12),
    "rsi": lambda h, lo, c, v: ind.rsi(c, 14),
    "macd": lambda h, lo, c, v: ind.macd(c).histogram,
    "bb_pctb": lambda h, lo, c, v: ind.bollinger(c).percent_b,
    "atr": lambda h, lo, c, v: ind.atr(h, lo, c, 14),
    "adx": lambda h, lo, c, v: ind.adx(h, lo, c, 14).adx,
    "obv": lambda h, lo, c, v: ind.obv(c, v),
    "vol": lambda h, lo, c, v: ind.realized_volatility(c, 20),
    "roc": lambda h, lo, c, v: ind.rate_of_change(c, 21),
    "pct_rank": lambda h, lo, c, v: ind.rolling_percentile_rank(c, 30),
}


@settings(max_examples=40, deadline=None)
@given(t=st.integers(min_value=40, max_value=N - 2), name=st.sampled_from(sorted(FNS)))
def test_no_lookahead(t: int, name: str) -> None:
    """value[t] computed on the full history == value[t] computed on history
    truncated at t. Any future leakage breaks this equality."""
    f = FNS[name]
    full = f(H, L, C, V)[t]
    cut = f(H[: t + 1], L[: t + 1], C[: t + 1], V[: t + 1])[t]
    assert (np.isnan(full) and np.isnan(cut)) or full == pytest.approx(cut, rel=1e-12, abs=1e-12)


@settings(max_examples=30, deadline=None)
@given(t=st.integers(min_value=30, max_value=N - 1))
def test_swing_points_only_use_the_past(t: int) -> None:
    w = 5
    truncated = ind.swing_points(H[: t + 1], w, "high")
    assert all(i <= t - w for i in truncated)  # confirmation needs w later sessions
    full = set(ind.swing_points(H, w, "high"))
    assert set(truncated) <= full  # a confirmed point never disappears later
