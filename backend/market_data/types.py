"""Core market-data types. Prices are Decimal end to end; never float."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


# Yahoo-style suffixes are the de-facto convention for Indian tickers (TCS.NS).
_SUFFIX = {Exchange.NSE: "NS", Exchange.BSE: "BO"}
_SUFFIX_TO_EXCHANGE = {v: k for k, v in _SUFFIX.items()}
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")


class InvalidTickerError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Ticker:
    symbol: str
    exchange: Exchange

    def __post_init__(self) -> None:
        if not _SYMBOL_RE.match(self.symbol):
            raise InvalidTickerError(f"invalid symbol {self.symbol!r}")

    @classmethod
    def parse(cls, raw: str) -> Ticker:
        """Accepts 'TCS.NS' or 'RELIANCE.BO'. Indian exchanges only."""
        value = raw.strip().upper()
        symbol, dot, suffix = value.rpartition(".")
        if not dot or suffix not in _SUFFIX_TO_EXCHANGE:
            raise InvalidTickerError(
                f"ticker {raw!r} must end in .NS (NSE) or .BO (BSE); "
                "only Indian markets are supported"
            )
        return cls(symbol=symbol, exchange=_SUFFIX_TO_EXCHANGE[suffix])

    def __str__(self) -> str:
        return f"{self.symbol}.{_SUFFIX[self.exchange]}"


class PriceBasis(StrEnum):
    """How a price series is adjusted. Series of different bases are never mixed."""

    RAW = "raw"  # as traded on the day
    SPLIT_ADJUSTED = "split_adjusted"  # back-adjusted for splits/bonuses only
    TOTAL_RETURN = "total_return"  # split-adjusted and dividends reinvested


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)

    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class CorporateActionIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["split", "dividend"]
    ex_date: date
    # split: `numerator` new shares for every `denominator` old (bonus 1:1 => 2/1)
    numerator: Decimal | None = Field(default=None, gt=0)
    denominator: Decimal | None = Field(default=None, gt=0)
    # dividend: cash per share, expressed in the same basis as the price series
    amount: Decimal | None = Field(default=None, gt=0)


@dataclass(frozen=True)
class DroppedRow:
    session: date | None
    reason: str


@dataclass
class ProviderBatch:
    """Everything a provider returned for one request, with provenance."""

    ticker: Ticker
    source: str
    licensed: bool
    basis: PriceBasis
    retrieved_at: datetime
    bars: list[Bar]
    actions: list[CorporateActionIn] = field(default_factory=list)
    dropped: list[DroppedRow] = field(default_factory=list)
    instrument_name: str | None = None
    currency: str | None = None
