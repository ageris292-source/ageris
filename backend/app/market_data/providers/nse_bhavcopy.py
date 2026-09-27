"""NSE provider: the exchange's own end-of-day files and corporate actions
(spec §39-§41).

Prices: the capital-market bhavcopy NSE publishes after every session, one
file per day covering every listed security:
  * from 2024-07-08: UDiFF  .../content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  * before:          legacy .../content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
Only the `EQ` series is used; prices are RAW (as traded). The files' previous
close is NOT adjusted on ex-dates, so actions cannot be inferred from them.

Corporate actions: NSE's corporate-actions feed for the symbol. Face-value
splits / consolidations and bonuses become split actions; cash dividends
(per share, as of the ex-date) become dividend actions. Anything else that
changes the price basis (rights, demergers, schemes) is reported as a
warning, never guessed. If a stock's actions cannot be fetched its batch
fails: prices without their splits would be silently wrong.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

import httpx

from app.core.config_file import ProviderSettings
from app.market_data.calendar import IndiaCalendar
from app.market_data.providers.base import ProviderError, ProviderStatus, ProviderUnavailableError
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

UDIFF_FROM = date(2024, 7, 8)
BASE = "https://nsearchives.nseindia.com/content"
# NSE refuses clients without a browser-like user agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) Aegis-research", "Accept": "*/*"}
CA_URL = "https://www.nseindia.com/api/corporates-corporateActions"
CA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}
_RS = r"R[se]\.?\s*(\d+(?:\.\d+)?)"
_SPLIT = re.compile(
    r"(?:Split|Sub-Division|Consolidation).*?From\s*" + _RS + r".*?To\s*" + _RS, re.I
)
_BONUS = re.compile(r"Bonus\s*(\d+)\s*:\s*(\d+)", re.I)
_DIVIDEND = re.compile(r"Div(?:idend)?[^R/]{0,25}?" + _RS, re.I)
_BASIS_CHANGING = re.compile(r"Rights|Demerger|Scheme|Capital Reduction|Arrangement", re.I)


@dataclass(frozen=True)
class DayRow:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    prev_close: Decimal
    volume: int
    name: str | None


def url_for(session: date) -> str:
    if session >= UDIFF_FROM:
        return f"{BASE}/cm/BhavCopy_NSE_CM_0_0_0_{session:%Y%m%d}_F_0000.csv.zip"
    mon = session.strftime("%b").upper()
    name = f"cm{session:%d}{mon}{session:%Y}bhav.csv.zip"
    return f"{BASE}/historical/EQUITIES/{session:%Y}/{mon}/{name}"


def _dec(v: str) -> Decimal:
    try:
        return Decimal(v.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ProviderError(f"bad number {v!r}") from exc


def parse(content: bytes, session: date) -> dict[str, DayRow]:
    """EQ rows of one bhavcopy zip, keyed by NSE symbol."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
        raise ProviderError(f"bhavcopy for {session} is not a valid zip/csv") from exc
    rows = csv.DictReader(io.StringIO(text))
    out: dict[str, DayRow] = {}
    udiff = session >= UDIFF_FROM
    for r in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if udiff:
            if r.get("SctySrs") != "EQ":
                continue
            if r.get("TradDt") != session.isoformat():
                raise ProviderError(f"bhavcopy for {session} is dated {r.get('TradDt')}")
            sym, o, h, lo, c, p = (
                r["TckrSymb"],
                r["OpnPric"],
                r["HghPric"],
                r["LwPric"],
                r["ClsPric"],
                r["PrvsClsgPric"],
            )
            vol, name = r["TtlTradgVol"], r.get("FinInstrmNm") or None
        else:
            if r.get("SERIES") != "EQ":
                continue
            stamp = datetime.strptime(r["TIMESTAMP"], "%d-%b-%Y").date()
            if stamp != session:
                raise ProviderError(f"bhavcopy for {session} is dated {stamp}")
            sym, o, h, lo, c, p = (
                r["SYMBOL"],
                r["OPEN"],
                r["HIGH"],
                r["LOW"],
                r["CLOSE"],
                r["PREVCLOSE"],
            )
            vol, name = r["TOTTRDQTY"], None
        out[sym] = DayRow(_dec(o), _dec(h), _dec(lo), _dec(c), _dec(p), int(_dec(vol)), name)
    if not out:
        raise ProviderError(f"bhavcopy for {session} has no EQ rows")
    return out


def parse_actions(
    items: list[dict[str, object]],
) -> tuple[list[CorporateActionIn], list[DroppedRow]]:
    """Corporate actions from NSE's feed. Returns (actions, warnings)."""
    actions: list[CorporateActionIn] = []
    warnings: list[DroppedRow] = []
    for it in items:
        if str(it.get("series") or "EQ").strip() != "EQ":
            continue
        subject = " ".join(str(it.get("subject") or "").split())
        try:
            ex = datetime.strptime(str(it.get("exDate")), "%d-%b-%Y").date()
        except ValueError:
            if subject:
                warnings.append(DroppedRow(None, f"corporate action without ex-date: {subject}"))
            continue
        if m := _SPLIT.search(subject):
            ratio = Fraction(Decimal(m.group(1))) / Fraction(Decimal(m.group(2)))
            actions.append(
                CorporateActionIn(
                    kind="split",
                    ex_date=ex,
                    numerator=Decimal(ratio.numerator),
                    denominator=Decimal(ratio.denominator),
                )
            )
        elif m := _BONUS.search(subject):
            new, held = int(m.group(1)), int(m.group(2))
            ratio = Fraction(new + held, held)
            actions.append(
                CorporateActionIn(
                    kind="split",
                    ex_date=ex,
                    numerator=Decimal(ratio.numerator),
                    denominator=Decimal(ratio.denominator),
                )
            )
        amounts = [Decimal(x) for x in _DIVIDEND.findall(subject)]
        if amounts and sum(amounts) > 0:
            actions.append(CorporateActionIn(kind="dividend", ex_date=ex, amount=sum(amounts)))
        if _BASIS_CHANGING.search(subject):
            warnings.append(
                DroppedRow(ex, f"price-basis change not adjusted (review manually): {subject}")
            )
    return actions, warnings


class NseBhavcopyProvider:
    name = "nse_bhavcopy"

    def __init__(
        self,
        settings: ProviderSettings,
        calendar: IndiaCalendar,
        availability_lag: timedelta,
        cache_dir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.licensed = settings.licensed
        self.calendar = calendar
        self.lag = availability_lag
        self.cache_dir = cache_dir
        self._transport = transport
        self._sleep = sleep
        self._memo: dict[date, dict[str, DayRow] | None] = {}
        self._ca_memo: dict[tuple[str, int], list[dict[str, object]]] = {}

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            enabled=self.settings.enabled,
            licensed=self.licensed,
            available=self.settings.enabled,
            reason="official NSE end-of-day bhavcopy (EQ series, raw prices)"
            if self.settings.enabled
            else "disabled in configuration",
        )

    # -- files ----------------------------------------------------------------

    def _cache_path(self, session: date) -> Path | None:
        return self.cache_dir / f"{session:%Y%m%d}.json" if self.cache_dir else None

    def _download(self, session: date) -> bytes | None:
        url = url_for(session)
        last: Exception | None = None
        with httpx.Client(
            timeout=self.settings.timeout_seconds,
            transport=self._transport,
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            for attempt in range(3):
                try:
                    r = client.get(url)
                except httpx.HTTPError as exc:
                    last = exc
                else:
                    if r.status_code == 404:
                        return None
                    if r.status_code == 200:
                        return r.content
                    last = ProviderUnavailableError(f"NSE answered {r.status_code} for {session}")
                self._sleep(1.5 * (attempt + 1))
        raise ProviderUnavailableError(f"NSE bhavcopy for {session} unreachable: {last}")

    def day(self, session: date) -> dict[str, DayRow] | None:
        """EQ rows for one session; None if NSE has not published the file."""
        if session in self._memo:
            return self._memo[session]
        path = self._cache_path(session)
        if path is not None and path.is_file():
            raw = json.loads(path.read_text())
            rows = {
                s: DayRow(
                    Decimal(v[0]),
                    Decimal(v[1]),
                    Decimal(v[2]),
                    Decimal(v[3]),
                    Decimal(v[4]),
                    int(v[5]),
                    v[6],
                )
                for s, v in raw.items()
            }
        else:
            content = self._download(session)
            if self.settings.request_interval_seconds:
                self._sleep(self.settings.request_interval_seconds)
            if content is None:
                self._memo[session] = None
                return None
            rows = parse(content, session)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            s: [
                                str(r.open),
                                str(r.high),
                                str(r.low),
                                str(r.close),
                                str(r.prev_close),
                                r.volume,
                                r.name,
                            ]
                            for s, r in rows.items()
                        }
                    )
                )
        if len(self._memo) > 40:  # keep memory bounded on small hosts
            self._memo.clear()
        self._memo[session] = rows
        return rows

    # -- batches ----------------------------------------------------------------

    def _actions_year(self, symbol: str, year: int, today: date) -> list[dict[str, object]]:
        key = (symbol, year)
        if key in self._ca_memo:
            return self._ca_memo[key]
        closed = date(year, 12, 31) < today - timedelta(days=30)  # past years don't change
        path = (
            self.cache_dir / "actions" / f"{symbol}_{year}.json"
            if self.cache_dir and closed
            else None
        )
        if path is not None and path.is_file():
            items: list[dict[str, object]] = json.loads(path.read_text())
        else:
            params = {
                "index": "equities",
                "symbol": symbol,
                "from_date": f"01-01-{year}",
                "to_date": min(date(year, 12, 31), today).strftime("%d-%m-%Y"),
            }
            last: Exception | None = None
            items = []
            for attempt in range(3):
                try:
                    with httpx.Client(
                        timeout=self.settings.timeout_seconds,
                        transport=self._transport,
                        headers=CA_HEADERS,
                    ) as client:
                        r = client.get(CA_URL, params=params)
                    if r.status_code == 200:
                        data = r.json()
                        if not isinstance(data, list):
                            raise ProviderError(f"bad corporate-actions payload for {symbol}")
                        items, last = data, None
                        break
                    last = ProviderUnavailableError(f"NSE answered {r.status_code}")
                except (httpx.HTTPError, ValueError) as exc:
                    last = exc
                self._sleep(1.5 * (attempt + 1))
            if last is not None:
                raise ProviderUnavailableError(
                    f"NSE corporate actions for {symbol} {year} unavailable: {last}"
                )
            if self.settings.request_interval_seconds:
                self._sleep(self.settings.request_interval_seconds)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(items))
        self._ca_memo[key] = items
        return items

    def actions_for(
        self, symbol: str, start: date, today: date
    ) -> tuple[list[CorporateActionIn], list[DroppedRow]]:
        """Every action from `start` up to today (later splits re-base earlier bars)."""
        items: list[dict[str, object]] = []
        for year in range(start.year, today.year + 1):
            items += self._actions_year(symbol, year, today)
        acts, warns = parse_actions(items)
        acts = [a for a in acts if start <= a.ex_date <= today]
        return sorted(acts, key=lambda a: (a.ex_date, a.kind)), warns

    def fetch_daily(self, ticker: Ticker, start: date, end: date, now: datetime) -> ProviderBatch:
        out = self.fetch_many([ticker], start, end, now)[ticker]
        if isinstance(out, Exception):
            raise out
        return out

    def fetch_many(
        self, tickers: Iterable[Ticker], start: date, end: date, now: datetime
    ) -> dict[Ticker, ProviderBatch | ProviderError | ProviderUnavailableError]:
        """One pass over the daily files for many stocks at once. A stock whose
        corporate actions cannot be fetched gets an error instead of a batch."""
        if not self.settings.enabled:
            raise ProviderUnavailableError("nse_bhavcopy provider is disabled")
        wanted = list(tickers)
        for t in wanted:
            if t.exchange is not Exchange.NSE:
                raise ProviderError(f"{t} is not an NSE listing (bhavcopy covers NSE only)")
        today = (now + timedelta(hours=5, minutes=30)).date()  # IST
        results: dict[Ticker, ProviderBatch | ProviderError | ProviderUnavailableError] = {}
        acts: dict[Ticker, tuple[list[CorporateActionIn], list[DroppedRow]]] = {}
        for t in wanted:
            try:
                acts[t] = self.actions_for(t.symbol, start, today)
            except (ProviderError, ProviderUnavailableError) as exc:
                results[t] = exc
        ok = [t for t in wanted if t not in results]
        sessions = [
            s
            for s in self.calendar.sessions(start, end)
            if self.calendar.session_close_utc(s) + self.lag <= now
        ]
        latest = sessions[-1] if sessions else None
        bars: dict[Ticker, list[Bar]] = {t: [] for t in ok}
        dropped: dict[Ticker, list[DroppedRow]] = {t: [] for t in ok}
        names: dict[Ticker, str | None] = {t: None for t in ok}
        for s in sessions if ok else []:
            rows = self.day(s)
            if rows is None:
                reason = (
                    "bhavcopy not yet published"
                    if s == latest
                    else "bhavcopy missing on NSE for this session"
                )
                for t in ok:
                    dropped[t].append(DroppedRow(s, reason))
                continue
            for t in ok:
                row = rows.get(t.symbol)
                if row is None:
                    dropped[t].append(DroppedRow(s, "no EQ-series row (not traded / other series)"))
                    continue
                bars[t].append(
                    Bar(
                        session=s,
                        open=row.open,
                        high=row.high,
                        low=row.low,
                        close=row.close,
                        volume=row.volume,
                    )
                )
                names[t] = row.name or names[t]
        for t in ok:
            actions, warnings = acts[t]
            results[t] = ProviderBatch(
                ticker=t,
                source=self.name,
                licensed=self.licensed,
                basis=PriceBasis.RAW,
                retrieved_at=now,
                bars=bars[t],
                actions=actions,
                dropped=dropped[t],
                warnings=warnings,
                instrument_name=names[t],
                currency="INR",
            )
        return results


NIFTY50_URL = f"{BASE}/indices/ind_nifty50list.csv"


def nifty50_symbols(transport: httpx.BaseTransport | None = None) -> list[str]:
    """Current NIFTY 50 constituents as published by NSE (today's list only:
    using it for history carries survivorship bias, which backtests flag)."""
    with httpx.Client(timeout=20, transport=transport, headers=HEADERS) as client:
        r = client.get(NIFTY50_URL)
    if r.status_code != 200:
        raise ProviderUnavailableError(f"NSE NIFTY 50 list unavailable ({r.status_code})")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    syms = [x["Symbol"].strip() for x in rows if (x.get("Series") or "").strip() == "EQ"]
    if len(syms) < 40:
        raise ProviderError(f"NIFTY 50 list has only {len(syms)} EQ symbols")
    return syms
