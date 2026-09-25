"""Yahoo Finance chart endpoint adapter for NSE (.NS) and BSE (.BO) daily bars.

IMPORTANT — licensing: this is an unofficial, unlicensed endpoint. Its data is
tagged `licensed=False` and may only feed RESEARCH. Later trade gates must
refuse to act on unlicensed data in paper or live mode.

Facts about the payload this adapter relies on (verified against recorded
responses in tests/fixtures):
  * bar timestamps are the session OPEN in UTC epoch seconds; `gmtoffset` is
    19800 (IST) for Indian listings
  * `indicators.quote` OHLC is back-adjusted for splits/bonuses, NOT for
    dividends => basis SPLIT_ADJUSTED
  * `events.dividends[].amount` is expressed in the same split-adjusted basis
  * the in-progress session appears as a live, incomplete bar
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.core.config_file import ProviderSettings
from app.market_data.cache import NullCache, ResponseCache
from app.market_data.calendar import IndiaCalendar
from app.market_data.providers.base import (
    ProviderError,
    ProviderStatus,
    ProviderUnavailableError,
)
from app.market_data.types import (
    Bar,
    CorporateActionIn,
    DroppedRow,
    Exchange,
    PriceBasis,
    ProviderBatch,
    Ticker,
)

log = logging.getLogger(__name__)

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
IST_OFFSET_SECONDS = 19_800
_EXPECTED_EXCHANGE = {Exchange.NSE: "NSE", Exchange.BSE: "BSE"}


class YahooDailyProvider:
    name = "yahoo"

    def __init__(
        self,
        settings: ProviderSettings,
        calendar: IndiaCalendar,
        availability_lag: timedelta,
        cache: ResponseCache | None = None,
        cache_seconds: int = 0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.licensed = settings.licensed
        self.calendar = calendar
        self.lag = availability_lag
        self.cache = cache or NullCache()
        self.cache_seconds = cache_seconds
        self._transport = transport

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            enabled=self.settings.enabled,
            licensed=self.licensed,
            available=self.settings.enabled,
            reason="enabled (unlicensed: research use only)"
            if self.settings.enabled
            else "disabled in configuration",
        )

    # -- fetching -------------------------------------------------------------

    def _request(self, ticker: Ticker, start: date, end: date) -> tuple[dict[str, Any], datetime]:
        if not self.settings.enabled:
            raise ProviderUnavailableError("yahoo provider is disabled in configuration")
        ist = timedelta(seconds=IST_OFFSET_SECONDS)
        p1 = int((datetime.combine(start, datetime.min.time(), UTC) - ist).timestamp())
        p2 = int(
            (datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC) - ist).timestamp()
        )
        key = f"yahoo:{ticker}:{p1}:{p2}"
        cached = self.cache.get(key)
        if cached is not None:
            blob = json.loads(cached)
            return blob["payload"], datetime.fromisoformat(blob["retrieved_at"])

        params: dict[str, str | int] = {
            "period1": p1,
            "period2": p2,
            "interval": "1d",
            "events": "div,split",
            "includeAdjustedClose": "false",
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self.settings.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 (Aegis research)"},
            ) as client:
                resp = client.get(BASE_URL + str(ticker), params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"yahoo unreachable: {exc.__class__.__name__}") from exc
        retrieved_at = datetime.now(UTC)

        if resp.status_code == 429:
            raise ProviderUnavailableError("yahoo rate limited the request (429)")
        if resp.status_code not in (200, 404):
            raise ProviderUnavailableError(f"yahoo returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("yahoo returned a non-JSON body") from exc
        if resp.status_code == 200:
            self.cache.set(
                key,
                json.dumps({"payload": payload, "retrieved_at": retrieved_at.isoformat()}),
                self.cache_seconds,
            )
        return payload, retrieved_at

    def fetch_daily(self, ticker: Ticker, start: date, end: date, now: datetime) -> ProviderBatch:
        payload, retrieved_at = self._request(ticker, start, end)
        return self.parse(payload, ticker, start, end, now, retrieved_at)

    # -- parsing (pure; unit-tested against recorded payloads) ----------------

    def parse(
        self,
        payload: dict[str, Any],
        ticker: Ticker,
        start: date,
        end: date,
        now: datetime,
        retrieved_at: datetime,
    ) -> ProviderBatch:
        try:
            chart = payload["chart"]
            results = chart.get("result")
            if not results:
                err = chart.get("error") or {}
                raise ProviderError(f"yahoo: {err.get('description') or 'no result'} ({ticker})")
            r = results[0]
            meta = r["meta"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("yahoo payload has an unexpected structure") from exc

        if meta.get("currency") != "INR":
            raise ProviderError(f"expected INR prices for {ticker}, got {meta.get('currency')!r}")
        exch = meta.get("fullExchangeName")
        if exch != _EXPECTED_EXCHANGE[ticker.exchange]:
            raise ProviderError(f"{ticker} resolved to exchange {exch!r}")
        if meta.get("gmtoffset") != IST_OFFSET_SECONDS:
            raise ProviderError(f"unexpected gmtoffset {meta.get('gmtoffset')!r} for {ticker}")
        hint = int(meta.get("priceHint", 2))

        timestamps: list[int] = r.get("timestamp") or []
        quote = (r.get("indicators", {}).get("quote") or [{}])[0]
        cols = {k: quote.get(k) or [] for k in ("open", "high", "low", "close", "volume")}
        if any(len(v) != len(timestamps) for v in cols.values()):
            raise ProviderError("yahoo quote arrays have inconsistent lengths")

        bars: list[Bar] = []
        dropped: list[DroppedRow] = []
        for i, ts in enumerate(timestamps):
            session = _ist_date(ts)
            values = [cols[k][i] for k in ("open", "high", "low", "close", "volume")]
            if session < start or session > end:
                continue
            if any(v is None for v in values):
                dropped.append(DroppedRow(session, "provider returned null OHLCV"))
                continue
            if (
                self.calendar.is_session(session)
                and self.calendar.session_close_utc(session) + self.lag > now
            ):
                dropped.append(DroppedRow(session, "session not complete at retrieval"))
                continue
            o, h, low, c, vol = values
            bars.append(
                Bar(
                    session=session,
                    open=_dec(o, hint),
                    high=_dec(h, hint),
                    low=_dec(low, hint),
                    close=_dec(c, hint),
                    volume=int(vol),
                )
            )

        actions: list[CorporateActionIn] = []
        events = r.get("events") or {}
        for s in (events.get("splits") or {}).values():
            ex = _ist_date(int(s["date"]))
            if start <= ex <= end:
                actions.append(
                    CorporateActionIn(
                        kind="split",
                        ex_date=ex,
                        numerator=Decimal(str(s["numerator"])),
                        denominator=Decimal(str(s["denominator"])),
                    )
                )
        for d in (events.get("dividends") or {}).values():
            ex = _ist_date(int(d["date"]))
            if start <= ex <= end:
                actions.append(
                    CorporateActionIn(kind="dividend", ex_date=ex, amount=_dec(d["amount"], 4))
                )

        return ProviderBatch(
            ticker=ticker,
            source=self.name,
            licensed=self.licensed,
            basis=PriceBasis.SPLIT_ADJUSTED,
            retrieved_at=retrieved_at,
            bars=bars,
            actions=sorted(actions, key=lambda a: (a.ex_date, a.kind)),
            dropped=dropped,
            instrument_name=meta.get("longName") or meta.get("shortName"),
            currency="INR",
        )


def _ist_date(epoch_seconds: int) -> date:
    return datetime.fromtimestamp(epoch_seconds + IST_OFFSET_SECONDS, UTC).date()


def _dec(value: float | int, places: int) -> Decimal:
    # Yahoo serialises float32-ish values (1908.949951171875); round to the
    # instrument's declared price precision before converting.
    return Decimal(str(round(float(value), places)))
