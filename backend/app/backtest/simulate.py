"""Portfolio simulation on out-of-sample predictions (spec §24, §25).

Non-overlapping holding periods of `horizon` trading days. At each rebalance
date the strategy buys (equal weight, at most top_k names) the stocks whose
calibrated P(profit) clears the trade-gate minimum and whose P(outperform)
is above 0.5; unfilled slots stay in cash (0% return). Entry at the next
session's close, exit `horizon` sessions later, round-trip costs deducted
per trade. A period with no qualifying stock is a NO-TRADE period.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.analysis import risk as rk


def simulate(
    pred: pd.DataFrame,
    horizon: int,
    top_k: int,
    min_p_profit: float,
    round_trip_cost: float,
    risk_free: float,
) -> dict[str, Any]:
    dates = np.sort(pred["date"].unique())
    rebal = dates[::horizon]
    periods: list[dict[str, Any]] = []
    trades = 0
    wins = 0
    for d in rebal:
        day = pred[pred["date"] == d]
        if day["fwd_return"].isna().all():
            continue
        pick = day[(day["p_profit"] >= min_p_profit) & (day["p_outperform"] > 0.5)]
        pick = pick.dropna(subset=["fwd_return"]).sort_values(
            ["p_profit", "ticker"], ascending=[False, True]
        )
        pick = pick.head(top_k)
        net = pick["fwd_return"] - round_trip_cost
        port = float(net.sum() / top_k) if len(pick) else 0.0
        bench = (
            float(day["bench_fwd_return"].dropna().iloc[0])
            if day["bench_fwd_return"].notna().any()
            else 0.0
        )
        trades += len(pick)
        wins += int((net > 0).sum())
        periods.append(
            {
                "date": str(pd.Timestamp(d).date()),
                "names": list(pick["ticker"]),
                "strategy_return": port,
                "benchmark_return": bench,
                "exposure": len(pick) / top_k,
            }
        )
    if not periods:
        return {"periods": [], "summary": {}}
    s = np.array([p["strategy_return"] for p in periods])
    b = np.array([p["benchmark_return"] for p in periods])
    eq, beq = np.cumprod(1 + s), np.cumprod(1 + b)
    years = len(periods) * horizon / 252
    per_year = 252 / horizon
    dd = rk.max_drawdown(list(zip(range(len(eq)), eq.tolist(), strict=True)))  # type: ignore[arg-type]
    bdd = rk.max_drawdown(list(zip(range(len(beq)), beq.tolist(), strict=True)))  # type: ignore[arg-type]
    vol = float(np.std(s, ddof=1) * math.sqrt(per_year)) if len(s) > 1 else None
    summary = {
        "periods": len(periods),
        "years": years,
        "no_trade_periods": sum(1 for p in periods if not p["names"]),
        "trades": trades,
        "win_rate": wins / trades if trades else None,
        "average_exposure": float(np.mean([p["exposure"] for p in periods])),
        "total_return": float(eq[-1] - 1),
        "cagr": float(eq[-1] ** (1 / years) - 1) if years > 0 else None,
        "volatility": vol,
        "sharpe": ((float(np.mean(s)) * per_year - risk_free) / vol) if vol else None,
        "max_drawdown": dd.max_drawdown,
        "benchmark_total_return": float(beq[-1] - 1),
        "benchmark_cagr": float(beq[-1] ** (1 / years) - 1) if years > 0 else None,
        "benchmark_max_drawdown": bdd.max_drawdown,
        "excess_total_return": float(eq[-1] - beq[-1]),
        "round_trip_cost_assumed": round_trip_cost,
    }
    for i, p in enumerate(periods):
        p["equity"] = float(eq[i])
        p["benchmark_equity"] = float(beq[i])
    return {"periods": periods, "summary": summary}
