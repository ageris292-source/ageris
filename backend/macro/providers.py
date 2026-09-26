"""Macro data providers.

* World Bank API (official; CC BY 4.0). Annual values. `lastupdated` is the
  vintage date; first availability of each annual value is ESTIMATED as
  year end + configured lag.
* Yahoo chart endpoint for market series (indices, VIX, FX, Brent): daily
  closes, unlicensed. Incomplete current sessions are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from app.market_data.providers.base import ProviderError, ProviderUnavailableError


@dataclass(frozen=True)
class Obs:
    series: str
    frequency: str
    period_date: date
    value: float
    unit: str
    source: str
    licensed: bool
    published_at: datetime | None
    available_at: datetime
    availability_estimated: bool


def _get(url: str, params: dict[str, Any], transport: httpx.BaseTransport | None) -> Any:
    try:
        with httpx.Client(
            transport=transport, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Aegis research)"}
        ) as c:
            r = c.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(f"{url} unreachable: {exc.__class__.__name__}") from exc
    if r.status_code != 200:
        raise ProviderUnavailableError(f"{url} returned HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as exc:
        raise ProviderError("non-JSON response") from exc


class WorldBankProvider:
    URL = "https://api.worldbank.org/v2/country/IN/indicator/{}"

    def __init__(self, lag_days: int, transport: httpx.BaseTransport | None = None) -> None:
        self.lag_days, self._t = lag_days, transport

    def fetch(self, series: str, indicator: str) -> list[Obs]:
        payload = _get(self.URL.format(indicator), {"format": "json", "per_page": 30}, self._t)
        return self.parse(series, indicator, payload)

    def parse(self, series: str, indicator: str, payload: Any) -> list[Obs]:
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            raise ProviderError(f"World Bank returned no data for {indicator}")
        meta, rows = payload[0], payload[1]
        vintage = None
        if meta.get("lastupdated"):
            vintage = datetime.combine(date.fromisoformat(meta["lastupdated"]), time(), UTC)
        out: list[Obs] = []
        for row in rows:
            if row.get("value") is None:
                continue  # missing years are skipped, never zero-filled
            year = int(row["date"])
            end = date(year, 12, 31)
            unit = "percent" if "ZG" in indicator else "INR per USD"
            value = float(row["value"]) / 100 if unit == "percent" else float(row["value"])
            out.append(
                Obs(
                    series=series,
                    frequency="annual",
                    period_date=end,
                    value=value,
                    unit="fraction" if unit == "percent" else unit,
                    source=f"World Bank {indicator}",
                    licensed=True,
                    published_at=vintage,
                    available_at=datetime.combine(
                        end + timedelta(days=self.lag_days), time(23, 59), UTC
                    ),
                    availability_estimated=True,
                )
            )
        return out


class YahooSeriesProvider:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._t = transport

    def fetch(self, series: str, symbol: str, start: date, now: datetime) -> list[Obs]:
        p1 = int(datetime.combine(start, time(), UTC).timestamp())
        payload = _get(
            self.URL + symbol,
            {"period1": p1, "period2": int(now.timestamp()) + 86400, "interval": "1d"},
            self._t,
        )
        return self.parse(series, symbol, payload, now)

    def parse(self, series: str, symbol: str, payload: Any, now: datetime) -> list[Obs]:
        try:
            r = payload["chart"]["result"][0]
            meta = r["meta"]
            ts = r.get("timestamp") or []
            closes = r["indicators"]["quote"][0]["close"]
        except (KeyError, TypeError, IndexError) as exc:
            raise ProviderError(f"no data for {symbol}") from exc
        offset = timedelta(seconds=int(meta.get("gmtoffset", 0)))
        trading_period = meta.get("currentTradingPeriod", {}).get("regular", {})
        session_len = timedelta(
            seconds=max(0, int(trading_period.get("end", 0)) - int(trading_period.get("start", 0)))
        )
        unit = meta.get("currency") or "points"
        out: list[Obs] = []
        for t, c in zip(ts, closes, strict=False):
            if c is None:
                continue
            opened = datetime.fromtimestamp(t, UTC)
            # Available once that session has closed; +1h publication margin.
            available = opened + (session_len or timedelta(hours=24)) + timedelta(hours=1)
            if available > now:
                continue  # incomplete session
            out.append(
                Obs(
                    series=series,
                    frequency="daily",
                    period_date=(opened + offset).date(),
                    value=float(c),
                    unit=unit,
                    source=f"yahoo:{symbol}",
                    licensed=False,
                    published_at=None,
                    available_at=available,
                    availability_estimated=False,
                )
            )
        if not out:
            raise ProviderError(f"no completed sessions for {symbol}")
        return out
