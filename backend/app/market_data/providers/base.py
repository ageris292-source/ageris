"""Provider adapter interface. Every data source is replaceable behind this."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.market_data.types import ProviderBatch, Ticker


class ProviderError(RuntimeError):
    """The provider responded, but the response is unusable (bad payload, not found)."""


class ProviderUnavailableError(RuntimeError):
    """The provider is disabled, unconfigured or unreachable. Never silently continue."""


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    enabled: bool
    licensed: bool
    available: bool
    reason: str


class DailyBarProvider(Protocol):
    name: str
    licensed: bool

    def status(self) -> ProviderStatus: ...

    def fetch_daily(self, ticker: Ticker, start: date, end: date, now: datetime) -> ProviderBatch:
        """Completed daily sessions in [start, end]. Sessions not yet complete at
        `now` (close + availability lag) are excluded and reported in `dropped`."""
        ...
