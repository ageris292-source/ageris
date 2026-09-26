"""Point-in-time features and forward labels (spec §22-§24).

Every feature at date t is a function of data up to and including t only
(rolling windows and recursive EMAs over the past). This is enforced by a
truncation test: features computed on the series cut at t equal those
computed on the full series. Labels look forward from the NEXT session's
close (a signal formed at close t cannot be filled at close t).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "features-1.0.0"
FEATURES = [
    "ret_5",
    "ret_20",
    "ret_60",
    "ret_120",
    "vol_20",
    "vol_60",
    "rsi_14",
    "macd_hist_norm",
    "dist_sma50",
    "dist_sma200",
    "drawdown_252",
    "volume_ratio",
    "rs_20",
    "rs_60",
    "beta_120",
    "bench_ret_20",
    "bench_vol_20",
    "bench_dist_sma200",
]
WARMUP_SESSIONS = 253  # longest lookback (252-day high) + 1


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0).where(dn.notna())


def build_features(close: pd.Series, volume: pd.Series, bench: pd.Series) -> pd.DataFrame:
    """close/volume indexed by session date (ascending); bench = benchmark
    level on (a superset of) those dates. Returns one row per session."""
    close = close.astype(float)
    b = bench.astype(float).reindex(close.index).ffill()
    r = close.pct_change()
    br = b.pct_change()
    f = pd.DataFrame(index=close.index)
    for n in (5, 20, 60, 120):
        f[f"ret_{n}"] = close / close.shift(n) - 1
    f["vol_20"] = r.rolling(20).std() * np.sqrt(252)
    f["vol_60"] = r.rolling(60).std() * np.sqrt(252)
    f["rsi_14"] = _rsi(close) / 100
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    f["macd_hist_norm"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / close
    f["dist_sma50"] = close / close.rolling(50).mean() - 1
    f["dist_sma200"] = close / close.rolling(200).mean() - 1
    f["drawdown_252"] = close / close.rolling(252).max() - 1
    v = volume.astype(float).reindex(close.index)
    f["volume_ratio"] = v.rolling(20).mean() / v.rolling(60).mean().replace(0, np.nan)
    f["rs_20"] = f["ret_20"] - (b / b.shift(20) - 1)
    f["rs_60"] = f["ret_60"] - (b / b.shift(60) - 1)
    f["beta_120"] = r.rolling(120).cov(br) / br.rolling(120).var()
    f["bench_ret_20"] = b / b.shift(20) - 1
    f["bench_vol_20"] = br.rolling(20).std() * np.sqrt(252)
    f["bench_dist_sma200"] = b / b.rolling(200).mean() - 1
    return f[FEATURES]


def forward_labels(
    close: pd.Series, bench: pd.Series, horizon: int, round_trip_cost: float
) -> pd.DataFrame:
    """Entry at close t+1, exit at close t+1+horizon."""
    close = close.astype(float)
    b = bench.astype(float).reindex(close.index).ffill()
    fwd = close.shift(-(horizon + 1)) / close.shift(-1) - 1
    bfwd = b.shift(-(horizon + 1)) / b.shift(-1) - 1
    idx = pd.Series(np.arange(len(close)), index=close.index)
    out = pd.DataFrame(index=close.index)
    out["fwd_return"] = fwd
    out["bench_fwd_return"] = bfwd
    out["y_profit"] = (fwd - round_trip_cost > 0).astype(float).where(fwd.notna())
    out["y_outperform"] = (fwd > bfwd).astype(float).where(fwd.notna() & bfwd.notna())
    # position (in this stock's sessions) of the last close the label uses
    out["label_end_pos"] = idx + horizon + 1
    return out
