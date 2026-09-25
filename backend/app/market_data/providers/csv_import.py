"""Import daily bars from a CSV file the operator obtained from a licensed or
official source (e.g. an exchange download or a licensed vendor export).

Required header: date,open,high,low,close,volume  (date = YYYY-MM-DD, IST
session date). The operator must declare the source name and the price basis;
nothing is inferred. Any malformed row fails the whole import with its line
number — rows are never silently skipped.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from app.core.config_file import ProviderSettings
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.types import Bar, PriceBasis, ProviderBatch, Ticker

REQUIRED = ("date", "open", "high", "low", "close", "volume")


def parse_csv_bars(
    text: str,
    ticker: Ticker,
    source: str,
    basis: PriceBasis,
    settings: ProviderSettings,
) -> ProviderBatch:
    if not settings.enabled:
        raise ProviderUnavailableError("csv_import is disabled in configuration")
    if not source.strip() or len(source) > 60:
        raise ProviderError("a source name (1-60 chars) is required for CSV imports")

    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ProviderError(f"CSV is missing required columns: {', '.join(missing)}")
    reader.fieldnames = header

    bars: list[Bar] = []
    errors: list[str] = []
    for lineno, row in enumerate(reader, start=2):
        try:
            session = date.fromisoformat((row["date"] or "").strip())
            prices = {k: Decimal((row[k] or "").strip()) for k in ("open", "high", "low", "close")}
            if any(not p.is_finite() for p in prices.values()):
                raise InvalidOperation
            vol_raw = (row["volume"] or "").strip()
            volume = int(Decimal(vol_raw))
            if Decimal(vol_raw) != volume:
                raise ValueError("fractional volume")
        except (ValueError, InvalidOperation, TypeError):
            errors.append(f"line {lineno}: unparseable row")
            continue
        bars.append(Bar(session=session, volume=volume, **prices))
    if errors:
        raise ProviderError("CSV import rejected: " + "; ".join(errors[:20]))
    if not bars:
        raise ProviderError("CSV contains no data rows")

    return ProviderBatch(
        ticker=ticker,
        source=f"csv:{source.strip()}",
        licensed=settings.licensed,
        basis=basis,
        retrieved_at=datetime.now(UTC),
        bars=bars,
        currency="INR",
    )
