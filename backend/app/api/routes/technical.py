"""Technical analysis API (spec §63: GET /technical/{ticker})."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Annotated

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.agents.base import AgentOutput
from app.agents.technical import agent as technical
from app.analysis import indicators as ind
from app.api.deps import CurrentUser, DbSession
from app.api.routes.stocks import Now, _stock, _ticker
from app.core.config_file import get_config
from app.market_data import service as md

router = APIRouter(tags=["technical"])


@router.get("/technical/{ticker}", response_model=AgentOutput)
def technical_analysis(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    as_of: Annotated[
        datetime | None,
        Query(description="Market cut-off (timezone required). Defaults to now."),
    ] = None,
    knowledge_at: Annotated[
        datetime | None,
        Query(description="Data vintage to replay a past run exactly. Defaults to now."),
    ] = None,
) -> AgentOutput:
    """Runs the technical agent on data available at `as_of` and records the run."""
    for name, value in (("as_of", as_of), ("knowledge_at", knowledge_at)):
        if value is not None and value.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must include a timezone"
            )
    t = _ticker(ticker)
    _stock(db, ticker)  # 404 if not in the universe
    return technical.run_and_record(db, t, as_of or now, user.id, knowledge_at)


class IndicatorPoint(BaseModel):
    session: date
    close: float
    sma_mid: float | None
    sma_long: float | None
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_lower: float | None


class IndicatorSeries(BaseModel):
    ticker: str
    basis: str
    calculation_version: str
    sma_mid_period: int
    sma_long_period: int
    rsi_overbought: float
    rsi_oversold: float
    warmup_sessions_excluded: int
    points: list[IndicatorPoint]


def _v(x: float) -> float | None:
    return None if math.isnan(x) else round(float(x), 4)


@router.get("/technical/{ticker}/indicators", response_model=IndicatorSeries)
def indicator_series(
    ticker: str,
    db: DbSession,
    _u: CurrentUser,
    now: Now,
    start: date | None = None,
    end: date | None = None,
) -> IndicatorSeries:
    """Chart series. Indicators are computed with extra history before `start`
    (warm-up) so the first plotted values are not artefacts of the window."""
    stock = _stock(db, ticker)
    rules = get_config().technical
    end = end or now.date()
    start = start or end - timedelta(days=365)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start must be <= end")
    warm_start = start - timedelta(days=int(max(rules.sma_periods) * 1.6) + 30)
    series = md.get_series(db, stock, technical.BASIS, warm_start, end)
    bars = [sb.bar for sb in series.bars]
    if not bars:
        return IndicatorSeries(
            ticker=str(series.ticker),
            basis=technical.BASIS.value,
            calculation_version=ind.CALCULATION_VERSION,
            sma_mid_period=0,
            sma_long_period=0,
            rsi_overbought=rules.rsi_overbought,
            rsi_oversold=rules.rsi_oversold,
            warmup_sessions_excluded=0,
            points=[],
        )
    c = np.array([float(b.close) for b in bars])
    periods = sorted(rules.sma_periods)
    mid_n, long_n = periods[len(periods) // 2], periods[-1]
    s_mid, s_long = ind.sma(c, mid_n), ind.sma(c, long_n)
    rsi = ind.rsi(c, rules.rsi_period)
    m = ind.macd(c, rules.macd_fast, rules.macd_slow, rules.macd_signal)
    bb = ind.bollinger(c, rules.bollinger_period, rules.bollinger_std_devs)
    first = next((i for i, b in enumerate(bars) if b.session >= start), len(bars))
    points = [
        IndicatorPoint(
            session=bars[i].session,
            close=float(c[i]),
            sma_mid=_v(s_mid[i]),
            sma_long=_v(s_long[i]),
            rsi=_v(rsi[i]),
            macd=_v(m.line[i]),
            macd_signal=_v(m.signal[i]),
            macd_histogram=_v(m.histogram[i]),
            bb_upper=_v(bb.upper[i]),
            bb_lower=_v(bb.lower[i]),
        )
        for i in range(first, len(bars))
    ]
    return IndicatorSeries(
        ticker=str(series.ticker),
        basis=technical.BASIS.value,
        calculation_version=ind.CALCULATION_VERSION,
        sma_mid_period=mid_n,
        sma_long_period=long_n,
        rsi_overbought=rules.rsi_overbought,
        rsi_oversold=rules.rsi_oversold,
        warmup_sessions_excluded=first,
        points=points,
    )


__all__ = ["router"]
