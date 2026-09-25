"""Pure technical analysis: bars in, typed result out. No I/O, no LLM.

Score (documented, deterministic — NOT a probability):
    each signal contributes direction (+1 / -1 / 0) x strength (0..1)
    category net   = mean of its signal contributions            in [-1, 1]
    composite      = sum(weight_c * net_c) / sum(weight_c present)
    score          = 50 + 50 * composite                         in [0, 100]
50 means no technical tilt; it says nothing about the probability of profit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from app.agents.base import Signal
from app.analysis import indicators as ind
from app.core.config_file import LiquidityRules, TechnicalRules
from app.market_data.types import Bar

Direction = str


def _f(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def _last(a: np.ndarray) -> float | None:
    return _f(float(a[-1])) if len(a) else None


def _dir(x: float) -> str:
    """Sign -> direction; exactly zero is neutral, never silently bearish."""
    return "bullish" if x > 0 else "bearish" if x < 0 else "neutral"


def _levels_in(conditions: list[str]) -> list[float]:
    """First rupee amount in each condition (for the side-of-close check)."""
    out = []
    for c in conditions:
        m = re.search(r"₹([\d,]+\.\d{2})", c)
        if m:
            out.append(float(m.group(1).replace(",", "")))
    return out


def _inr(x: float) -> str:
    return f"₹{x:,.2f}"


@dataclass
class TechnicalResult:
    metrics: dict[str, float | None]
    signals: list[Signal]
    score: float
    agreement: float
    breadth: float
    risks: list[str]
    invalidation_conditions: list[str]
    supports: list[ind.Level]
    resistances: list[ind.Level]
    warnings: list[str] = field(default_factory=list)


def analyze(bars: list[Bar], rules: TechnicalRules, liquidity: LiquidityRules) -> TechnicalResult:
    c = np.array([float(b.close) for b in bars])
    h = np.array([float(b.high) for b in bars])
    lo = np.array([float(b.low) for b in bars])
    v = np.array([float(b.volume) for b in bars])
    close = float(c[-1])

    smas = {n: ind.sma(c, n) for n in rules.sma_periods}
    rsi = ind.rsi(c, rules.rsi_period)
    macd = ind.macd(c, rules.macd_fast, rules.macd_slow, rules.macd_signal)
    bb = ind.bollinger(c, rules.bollinger_period, rules.bollinger_std_devs)
    atr = ind.atr(h, lo, c, rules.atr_period)
    adx = ind.adx(h, lo, c, rules.adx_period)
    obv = ind.obv(c, v)
    vol = ind.realized_volatility(c, rules.volatility_window)
    roc = {n: ind.rate_of_change(c, n) for n in rules.momentum_windows}
    vol20, vol60 = ind.sma(v, 20), ind.sma(v, 60)
    traded_value = ind.sma(c * v, 20)
    bw_rank = ind.rolling_percentile_rank(bb.bandwidth, rules.squeeze_lookback)
    supports, resistances = ind.support_resistance(
        h,
        lo,
        c,
        lookback=rules.sr_lookback,
        window=rules.pivot_window,
        tolerance=rules.sr_cluster_tolerance,
        max_levels=rules.sr_max_levels,
    )

    metrics: dict[str, float | None] = {"close": close}
    for n, a in smas.items():
        metrics[f"sma_{n}"] = _last(a)
    metrics.update(
        rsi=_last(rsi),
        macd=_last(macd.line),
        macd_signal=_last(macd.signal),
        macd_histogram=_last(macd.histogram),
        bb_upper=_last(bb.upper),
        bb_lower=_last(bb.lower),
        bb_percent_b=_last(bb.percent_b),
        bb_bandwidth=_last(bb.bandwidth),
        atr=_last(atr),
        atr_pct=(_last(atr) or 0) / close if _last(atr) is not None else None,
        adx=_last(adx.adx),
        plus_di=_last(adx.plus_di),
        minus_di=_last(adx.minus_di),
        obv=_last(obv),
        volatility_annualised=_last(vol),
        volume_avg_20=_last(vol20),
        volume_avg_60=_last(vol60),
        avg_traded_value_20=_last(traded_value),
    )
    for n, a in roc.items():
        metrics[f"roc_{n}"] = _last(a)

    signals: list[Signal] = []
    warnings: list[str] = []
    risks: list[str] = []

    def sig(
        name: str,
        cat: str,
        direction: Direction,
        strength: float,
        detail: str,
        **values: float | str | None,
    ) -> None:
        signals.append(
            Signal(
                name=name,
                category=cat,
                direction=direction,
                strength=max(0.0, min(1.0, strength)),
                detail=detail,
                values=values,
            )
        )

    # ---- trend --------------------------------------------------------------
    long_n, mid_n = max(rules.sma_periods), sorted(rules.sma_periods)[len(rules.sma_periods) // 2]
    s_long, s_mid = metrics[f"sma_{long_n}"], metrics[f"sma_{mid_n}"]
    if s_long is not None:
        gap = close / s_long - 1
        sig(
            "price_vs_sma_long",
            "trend",
            _dir(gap),
            min(1.0, abs(gap) / 0.10),
            f"Close {_inr(close)} is {abs(gap):.1%} {'above' if gap > 0 else 'below'} "
            f"the {long_n}-day average {_inr(s_long)}",
            close=close,
            sma=s_long,
        )
    if s_long is not None and s_mid is not None:
        up = s_mid > s_long
        cross = ind.last_cross(smas[mid_n], smas[long_n], rules.cross_lookback_sessions)
        if cross:
            name = "golden_cross" if cross[0] == "up" else "death_cross"
            sig(
                name,
                "trend",
                "bullish" if cross[0] == "up" else "bearish",
                0.8,
                f"{mid_n}-day average crossed {'above' if cross[0] == 'up' else 'below'} the "
                f"{long_n}-day average {cross[1]} session(s) ago",
                sessions_ago=cross[1],
            )
        else:
            sig(
                "sma_alignment",
                "trend",
                _dir(s_mid - s_long),
                0.5,
                f"{mid_n}-day average {_inr(s_mid)} is {'above' if up else 'below'} the "
                f"{long_n}-day average {_inr(s_long)}",
            )
    a_now = metrics["adx"]
    if a_now is not None and metrics["plus_di"] is not None and metrics["minus_di"] is not None:
        if a_now >= rules.adx_trend_threshold:
            bull = metrics["plus_di"] > metrics["minus_di"]
            sig(
                "strong_trend",
                "trend",
                "bullish" if bull else "bearish",
                min(1.0, a_now / 50),
                f"ADX {a_now:.1f} ≥ {rules.adx_trend_threshold:g} with "
                f"{'+DI above -DI' if bull else '-DI above +DI'}",
                adx=a_now,
            )
        else:
            sig(
                "weak_trend",
                "trend",
                "neutral",
                0.3,
                f"ADX {a_now:.1f} < {rules.adx_trend_threshold:g}: no strong trend",
                adx=a_now,
            )

    # ---- momentum -----------------------------------------------------------
    if metrics["macd"] is not None and metrics["macd_signal"] is not None:
        cross = ind.last_cross(macd.line, macd.signal, rules.cross_lookback_sessions)
        above = metrics["macd"] > metrics["macd_signal"]
        if cross:
            sig(
                "macd_cross",
                "momentum",
                "bullish" if cross[0] == "up" else "bearish",
                0.7,
                f"MACD crossed {'above' if cross[0] == 'up' else 'below'} its signal line "
                f"{cross[1]} session(s) ago",
                sessions_ago=cross[1],
            )
        else:
            sig(
                "macd_position",
                "momentum",
                _dir(metrics["macd"] - metrics["macd_signal"]),
                0.4,
                f"MACD {metrics['macd']:.2f} is {'above' if above else 'below'} its signal "
                f"{metrics['macd_signal']:.2f}",
            )
    r = metrics["rsi"]
    if r is not None:
        sig(
            "rsi_level",
            "momentum",
            "bullish" if r > 50 else "bearish" if r < 50 else "neutral",
            abs(r - 50) / 50,
            f"RSI({rules.rsi_period}) {r:.1f}",
            rsi=r,
        )
    mid_roc = sorted(rules.momentum_windows)[len(rules.momentum_windows) // 2 - 1]
    rv = metrics.get(f"roc_{mid_roc}")
    if rv is not None:
        sig(
            f"return_{mid_roc}d",
            "momentum",
            _dir(rv),
            min(1.0, abs(rv) / 0.20),
            f"{mid_roc}-session price change {rv:+.1%}",
            change=rv,
        )

    # ---- mean reversion (stretched conditions) ------------------------------
    if r is not None and r >= rules.rsi_overbought:
        sig(
            "rsi_overbought",
            "mean_reversion",
            "bearish",
            (r - rules.rsi_overbought) / (100 - rules.rsi_overbought) * 0.5 + 0.5,
            f"RSI {r:.1f} ≥ {rules.rsi_overbought:g}: overbought, pullback risk",
            rsi=r,
        )
        risks.append(f"Overbought: RSI {r:.1f}")
    elif r is not None and r <= rules.rsi_oversold:
        sig(
            "rsi_oversold",
            "mean_reversion",
            "bullish",
            (rules.rsi_oversold - r) / rules.rsi_oversold * 0.5 + 0.5,
            f"RSI {r:.1f} ≤ {rules.rsi_oversold:g}: oversold, rebound possible",
            rsi=r,
        )
    pb = metrics["bb_percent_b"]
    if pb is not None and (pb > 1 or pb < 0):
        sig(
            "bollinger_extreme",
            "mean_reversion",
            "bearish" if pb > 1 else "bullish",
            0.5,
            f"Close outside the {'upper' if pb > 1 else 'lower'} Bollinger band (%B {pb:.2f})",
            percent_b=pb,
        )

    # ---- breakout -----------------------------------------------------------
    n = rules.breakout_lookback
    if len(c) > n + 1 and metrics["volume_avg_20"]:
        prior_high = float(np.max(h[-n - 1 : -1]))
        prior_low = float(np.min(lo[-n - 1 : -1]))
        vol_ratio = float(v[-1]) / metrics["volume_avg_20"]
        confirmed = vol_ratio >= rules.breakout_volume_multiple
        if close > prior_high:
            sig(
                "breakout_high",
                "breakout",
                "bullish",
                0.9 if confirmed else 0.5,
                f"Close above the prior {n}-session high {_inr(prior_high)}; volume "
                f"{vol_ratio:.1f}x 20-day average{'' if confirmed else ' (unconfirmed)'}",
                level=prior_high,
                volume_ratio=vol_ratio,
            )
        elif close < prior_low:
            sig(
                "breakdown_low",
                "breakout",
                "bearish",
                0.9 if confirmed else 0.5,
                f"Close below the prior {n}-session low {_inr(prior_low)}; volume "
                f"{vol_ratio:.1f}x 20-day average{'' if confirmed else ' (unconfirmed)'}",
                level=prior_low,
                volume_ratio=vol_ratio,
            )
    rank = _last(bw_rank)
    if rank is not None and rank <= 0.10:
        sig(
            "bollinger_squeeze",
            "breakout",
            "neutral",
            0.5,
            f"Bollinger bandwidth in the lowest decile of {rules.squeeze_lookback} sessions: "
            "volatility contraction, direction undetermined",
            percentile=rank,
        )

    # ---- volume -------------------------------------------------------------
    if metrics["volume_avg_20"] and metrics["volume_avg_60"] and len(c) > 21:
        ratio = metrics["volume_avg_20"] / metrics["volume_avg_60"]
        chg20 = close / float(c[-21]) - 1
        obv_chg = float(obv[-1] - obv[-21])
        if ratio >= 1.2:
            bull = chg20 > 0
            sig(
                "volume_expansion",
                "volume",
                "bullish" if bull else "bearish",
                min(1.0, (ratio - 1)),
                f"20-day volume {ratio:.2f}x the 60-day average while price "
                f"moved {chg20:+.1%} ({'accumulation' if bull else 'distribution'})",
                volume_ratio=ratio,
            )
        if (obv_chg > 0) != (chg20 > 0) and abs(chg20) > 0.02:
            sig(
                "obv_divergence",
                "volume",
                "bullish" if obv_chg > 0 else "bearish",
                0.4,
                f"On-balance volume {'rising' if obv_chg > 0 else 'falling'} while price "
                f"{'fell' if chg20 < 0 else 'rose'} {abs(chg20):.1%} over 20 sessions",
            )

    # ---- RSI divergence (confirmed swing points only) -----------------------
    lb = rules.divergence_lookback
    seg_start = max(0, len(c) - lb)
    for kind, name, direction in (
        ("high", "bearish_divergence", "bearish"),
        ("low", "bullish_divergence", "bullish"),
    ):
        series = h if kind == "high" else lo
        pts = [
            i + seg_start for i in ind.swing_points(series[seg_start:], rules.pivot_window, kind)
        ]
        if len(pts) >= 2 and not np.isnan(rsi[pts[-2]]) and not np.isnan(rsi[pts[-1]]):
            p1, p2 = pts[-2], pts[-1]
            price_up = series[p2] > series[p1]
            rsi_up = rsi[p2] > rsi[p1]
            if (kind == "high" and price_up and not rsi_up) or (
                kind == "low" and not price_up and rsi_up
            ):
                sig(
                    name,
                    "momentum",
                    direction,
                    0.6,
                    f"Price made a {'higher high' if kind == 'high' else 'lower low'} "
                    f"({_inr(series[p1])} → {_inr(series[p2])}) but RSI did not "
                    f"({rsi[p1]:.1f} → {rsi[p2]:.1f})",
                )

    # ---- score --------------------------------------------------------------
    nets: dict[str, float] = {}
    for cat in rules.category_weights:
        contribs = [
            (1 if s.direction == "bullish" else -1 if s.direction == "bearish" else 0) * s.strength
            for s in signals
            if s.category == cat
        ]
        if contribs:
            nets[cat] = sum(contribs) / len(contribs)
    weights: dict[str, float] = {str(k): w for k, w in rules.category_weights.items()}
    wsum = sum(weights[c_] for c_ in nets)
    composite = sum(weights[c_] * nets[c_] for c_ in nets) / wsum if wsum else 0.0
    score = round(50 + 50 * composite, 2)

    directional = [s for s in signals if s.direction != "neutral"]
    total = sum(s.strength for s in directional)
    net = sum((1 if s.direction == "bullish" else -1) * s.strength for s in directional)
    agreement = abs(net) / total if total else 0.0
    # Breadth: weighted share of categories that produced a directional view.
    # Agreement between two categories is weaker evidence than across five.
    covered = {s.category for s in directional}
    breadth = sum(w for c_, w in weights.items() if c_ in covered)

    # ---- risks --------------------------------------------------------------
    vol_now = metrics["volatility_annualised"]
    vol_hist = vol[~np.isnan(vol)][-252:]
    if vol_now is not None and len(vol_hist) >= 60:
        med = float(np.median(vol_hist))
        if vol_now > rules.high_volatility_ratio * med:
            risks.append(
                f"High volatility: 20-day annualised {vol_now:.0%} vs 1-year median {med:.0%}"
            )
    atv = metrics["avg_traded_value_20"]
    if atv is not None and atv < liquidity.minimum_average_daily_traded_value:
        risks.append(
            f"Low liquidity: average daily traded value {_inr(atv)} below "
            f"{_inr(liquidity.minimum_average_daily_traded_value)}"
        )
    if metrics["atr_pct"] is not None and metrics["atr_pct"] > 0.04:
        risks.append(f"Wide daily range: ATR is {metrics['atr_pct']:.1%} of price")

    # ---- invalidation -------------------------------------------------------
    # Every level must lie on the far side of the current close: a condition
    # that is already true would invalidate the thesis the moment it is made.
    inval: list[str] = []
    a_val = metrics["atr"]
    if composite > 0:
        if supports:
            inval.append(f"Daily close below nearest support {_inr(supports[0].price)}")
        if s_mid is not None and s_mid < close:
            inval.append(f"Daily close below the {mid_n}-day average {_inr(s_mid)}")
        if a_val:
            stop = close - rules.invalidation_atr_multiple * a_val
            inval.append(
                f"Close below {_inr(stop)} "
                f"({rules.invalidation_atr_multiple:g}x ATR under the last close)"
            )
    elif composite < 0:
        if resistances:
            inval.append(f"Daily close above nearest resistance {_inr(resistances[0].price)}")
        if s_mid is not None and s_mid > close:
            inval.append(f"Daily close above the {mid_n}-day average {_inr(s_mid)}")
        if a_val:
            stop = close + rules.invalidation_atr_multiple * a_val
            inval.append(
                f"Close above {_inr(stop)} "
                f"({rules.invalidation_atr_multiple:g}x ATR over the last close)"
            )
    else:
        inval.append("No directional thesis: nothing to invalidate")
    levels_ok = all((lv < close) if composite > 0 else (lv > close) for lv in _levels_in(inval))
    if not levels_ok:  # defensive: never ship a self-contradicting condition
        raise AssertionError("invalidation level on the wrong side of the close")

    return TechnicalResult(
        metrics=metrics,
        signals=signals,
        score=score,
        agreement=agreement,
        breadth=breadth,
        risks=risks,
        invalidation_conditions=inval,
        supports=supports,
        resistances=resistances,
        warnings=warnings,
    )
