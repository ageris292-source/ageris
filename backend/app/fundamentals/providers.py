"""Financial-statement providers.

Yahoo `fundamentals-timeseries` (unofficial, UNLICENSED): gives period-end
dates (`asOfDate`) but NOT publication dates, so availability is estimated
from SEBI filing deadlines and flagged. CSV import requires a real
`published_at` for every row.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx

from app.core.config_file import FundamentalRules, ProviderSettings
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.types import Ticker

PeriodType = Literal["annual", "quarterly"]

# Canonical line items (snake_case) <- Yahoo type suffix.
LINE_ITEMS: dict[str, str] = {
    "TotalRevenue": "revenue",
    "CostOfRevenue": "cost_of_revenue",
    "GrossProfit": "gross_profit",
    "OperatingIncome": "operating_income",
    "EBIT": "ebit",
    "EBITDA": "ebitda",
    "PretaxIncome": "pretax_income",
    "TaxProvision": "tax",
    "NetIncome": "net_income",
    "DilutedEPS": "eps_diluted",
    "DilutedAverageShares": "shares_diluted",
    "InterestExpense": "interest_expense",
    "OperatingCashFlow": "operating_cash_flow",
    "CapitalExpenditure": "capex",
    "FreeCashFlow": "free_cash_flow",
    "TotalDebt": "total_debt",
    "CashAndCashEquivalents": "cash",
    "StockholdersEquity": "equity",
    "TotalAssets": "total_assets",
    "CurrentLiabilities": "current_liabilities",
}
CANONICAL = set(LINE_ITEMS.values())

IST = timedelta(hours=5, minutes=30)


@dataclass(frozen=True)
class Fact:
    period_type: PeriodType
    period_end: date
    line_item: str
    value: Decimal
    currency: str
    published_at: datetime | None
    available_at: datetime
    availability_estimated: bool


@dataclass
class FundamentalsBatch:
    ticker: Ticker
    source: str
    licensed: bool
    retrieved_at: datetime
    facts: list[Fact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def estimated_availability(
    period_type: PeriodType, period_end: date, rules: FundamentalRules
) -> datetime:
    """Latest date the filing deadline allows, at end of that IST day (conservative)."""
    lag = (
        rules.quarterly_publication_lag_days
        if period_type == "quarterly"
        else rules.annual_publication_lag_days
    )
    day = period_end + timedelta(days=lag)
    return datetime.combine(day, time(23, 59), UTC) - IST


class YahooFundamentalsProvider:
    name = "yahoo_fundamentals"
    URL = "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"

    def __init__(
        self,
        settings: ProviderSettings,
        rules: FundamentalRules,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings, self.rules, self._transport = settings, rules, transport
        self.licensed = settings.licensed

    def fetch(self, ticker: Ticker) -> FundamentalsBatch:
        if not self.settings.enabled:
            raise ProviderUnavailableError("yahoo fundamentals provider is disabled")
        types = ",".join(f"{p}{k}" for k in LINE_ITEMS for p in ("annual", "quarterly"))
        # NB: Yahoo returns empty series when period2 is far in the future.
        now = int(datetime.now(UTC).timestamp())
        params: dict[str, str | int] = {"type": types, "period1": 946684800, "period2": now + 86400}
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self.settings.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 (Aegis research)"},
            ) as c:
                resp = c.get(self.URL + str(ticker), params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"yahoo unreachable: {exc.__class__.__name__}") from exc
        if resp.status_code == 429:
            raise ProviderUnavailableError("yahoo rate limited the request (429)")
        if resp.status_code != 200:
            raise ProviderUnavailableError(f"yahoo returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("yahoo returned a non-JSON body") from exc
        return self.parse(payload, ticker, datetime.now(UTC))

    def parse(
        self, payload: dict[str, Any], ticker: Ticker, retrieved_at: datetime
    ) -> FundamentalsBatch:
        try:
            results = payload["timeseries"]["result"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("unexpected fundamentals payload structure") from exc
        batch = FundamentalsBatch(ticker, self.name, self.licensed, retrieved_at)
        for r in results or []:
            key = (r.get("meta", {}).get("type") or [None])[0]
            if not key:
                continue
            period: PeriodType
            if key.startswith("annual"):
                period, suffix = "annual", key[len("annual") :]
            elif key.startswith("quarterly"):
                period, suffix = "quarterly", key[len("quarterly") :]
            else:
                continue
            item = LINE_ITEMS.get(suffix)
            if item is None:
                continue
            for row in r.get(key) or []:
                if not row:
                    continue  # Yahoo emits nulls for missing periods: skipped, never zero-filled
                try:
                    period_end = date.fromisoformat(row["asOfDate"])
                    value = Decimal(str(row["reportedValue"]["raw"]))
                    currency = row.get("currencyCode") or ""
                except (KeyError, ValueError, InvalidOperation):
                    batch.warnings.append(f"unparseable {key} row skipped")
                    continue
                if currency != "INR":
                    batch.warnings.append(f"{key} {period_end} in {currency!r}, not INR: skipped")
                    continue
                batch.facts.append(
                    Fact(
                        period_type=period,
                        period_end=period_end,
                        line_item=item,
                        value=value,
                        currency="INR",
                        published_at=None,
                        available_at=estimated_availability(period, period_end, self.rules),
                        availability_estimated=True,
                    )
                )
        if not batch.facts:
            raise ProviderError(f"no fundamentals returned for {ticker}")
        return batch


REQUIRED_CSV = ("period_type", "period_end", "line_item", "value", "published_at")


def parse_fundamentals_csv(
    text: str, ticker: Ticker, source: str, settings: ProviderSettings
) -> FundamentalsBatch:
    """Operator-supplied licensed/official data. `published_at` (ISO datetime
    with timezone) is mandatory, so availability is never estimated."""
    if not settings.enabled:
        raise ProviderUnavailableError("csv_import is disabled in configuration")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_CSV if c not in header]
    if missing:
        raise ProviderError(f"CSV is missing required columns: {', '.join(missing)}")
    reader.fieldnames = header
    batch = FundamentalsBatch(ticker, f"csv:{source.strip()}", settings.licensed, datetime.now(UTC))
    errors: list[str] = []
    for lineno, row in enumerate(reader, start=2):
        try:
            period = (row["period_type"] or "").strip().lower()
            if period not in ("annual", "quarterly"):
                raise ValueError("period_type")
            item = (row["line_item"] or "").strip().lower()
            if item not in CANONICAL:
                raise ValueError("line_item")
            period_end = date.fromisoformat((row["period_end"] or "").strip())
            published = datetime.fromisoformat((row["published_at"] or "").strip())
            if published.tzinfo is None:
                raise ValueError("published_at needs a timezone")
            if published.date() < period_end:
                raise ValueError("published before period end")
            value = Decimal((row["value"] or "").strip())
            if not value.is_finite():
                raise ValueError("value")
        except (ValueError, InvalidOperation) as exc:
            errors.append(f"line {lineno}: {exc}")
            continue
        pt: PeriodType = "annual" if period == "annual" else "quarterly"
        batch.facts.append(Fact(pt, period_end, item, value, "INR", published, published, False))
    if errors:
        raise ProviderError("CSV import rejected: " + "; ".join(errors[:20]))
    if not batch.facts:
        raise ProviderError("CSV contains no data rows")
    return batch
