"""Market regime detection (spec §42). Deterministic and documented:

  trend      : bull if NIFTY > 200d SMA * (1 + band) and 50d > 200d;
               bear if NIFTY < 200d SMA * (1 - band) and 50d < 200d; else sideways
  volatility : high if India VIX >= vix_high (or 20d realised vol >= 25% when
               VIX is missing); low if VIX <= vix_low; else normal
  risk       : risk_off if trend == bear or volatility == high; risk_on if
               trend == bull and volatility != high; else neutral

UNKNOWN when inputs are insufficient — never defaulted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.analysis import indicators as ind


@dataclass(frozen=True)
class Regime:
    trend: str  # bull | bear | sideways | unknown
    volatility: str  # high | normal | low | unknown
    risk: str  # risk_on | risk_off | neutral | unknown
    label: str
    evidence: dict[str, float | None]

    @property
    def known(self) -> bool:
        return "unknown" not in (self.trend, self.volatility)


def detect(
    nifty: list[float], vix: list[float] | None, *, vix_high: float, vix_low: float, band: float
) -> Regime:
    ev: dict[str, float | None] = {}
    trend = "unknown"
    if len(nifty) >= 200:
        c = np.array(nifty, dtype=float)
        s50, s200 = ind.sma(c, 50)[-1], ind.sma(c, 200)[-1]
        ev.update(nifty=float(c[-1]), sma50=float(s50), sma200=float(s200))
        if c[-1] > s200 * (1 + band) and s50 > s200:
            trend = "bull"
        elif c[-1] < s200 * (1 - band) and s50 < s200:
            trend = "bear"
        else:
            trend = "sideways"
    volatility = "unknown"
    if vix:
        v = float(vix[-1])
        ev["india_vix"] = v
        volatility = "high" if v >= vix_high else "low" if v <= vix_low else "normal"
    elif len(nifty) >= 21:
        rv = float(ind.realized_volatility(np.array(nifty, dtype=float), 20)[-1])
        ev["realised_vol_20d"] = rv
        volatility = "high" if rv >= 0.25 else "low" if rv <= 0.10 else "normal"
    if trend == "unknown" or volatility == "unknown":
        risk = "unknown"
    elif trend == "bear" or volatility == "high":
        risk = "risk_off"
    elif trend == "bull":
        risk = "risk_on"
    else:
        risk = "neutral"
    label = "UNKNOWN" if risk == "unknown" else f"{trend.upper()}_{volatility.upper()}_VOL"
    return Regime(trend, volatility, risk, label, ev)
