"""Yahoo adapter against REAL recorded responses (tests/fixtures), plus
failure modes. No live network access in tests."""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.types import PriceBasis, Ticker
from tests.market_helpers import NOW, load, provider_for

TCS = Ticker.parse("TCS.NS")
Y2018 = (date(2018, 1, 1), date(2018, 12, 31))


def test_parses_2018_history_with_split_and_dividends() -> None:
    batch = provider_for(load("yahoo_tcs_ns_2018.json")).fetch_daily(TCS, *Y2018, NOW)
    assert batch.source == "yahoo" and batch.licensed is False
    assert batch.basis is PriceBasis.SPLIT_ADJUSTED
    assert batch.instrument_name == "Tata Consultancy Services Limited"
    assert len(batch.bars) == 246
    first = batch.bars[0]
    # Timestamps are session opens in UTC; the IST session date must be used.
    assert first.session == date(2018, 1, 1)
    assert first.close == Decimal("1322.8")  # float32 noise rounded to priceHint
    splits = [a for a in batch.actions if a.kind == "split"]
    assert len(splits) == 1
    assert (splits[0].ex_date, splits[0].numerator, splits[0].denominator) == (
        date(2018, 5, 31),
        Decimal("2.0"),
        Decimal("1.0"),
    )
    divs = {a.ex_date: a.amount for a in batch.actions if a.kind == "dividend"}
    assert divs[date(2018, 1, 22)] == Decimal("3.5")  # split-adjusted amount


def test_incomplete_current_session_is_dropped() -> None:
    payload = load("yahoo_tcs_ns_recent.json")
    during_session = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)  # 13:30 IST, market open
    batch = provider_for(payload).fetch_daily(
        TCS, date(2026, 8, 1), date(2026, 9, 25), during_session
    )
    assert batch.bars[-1].session == date(2026, 9, 24)
    assert [(d.session, d.reason) for d in batch.dropped] == [
        (date(2026, 9, 25), "session not complete at retrieval")
    ]
    after = provider_for(payload).fetch_daily(TCS, date(2026, 8, 1), date(2026, 9, 25), NOW)
    assert after.bars[-1].session == date(2026, 9, 25)


def test_null_rows_are_dropped_not_zero_filled() -> None:
    payload = copy.deepcopy(load("yahoo_tcs_ns_2018.json"))
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][10] = None
    batch = provider_for(payload).fetch_daily(TCS, *Y2018, NOW)
    assert len(batch.bars) == 245
    assert batch.dropped[0].reason == "provider returned null OHLCV"
    assert all(b.close > 0 for b in batch.bars)


def test_not_found_symbol_is_an_error() -> None:
    with pytest.raises(ProviderError, match="No data found"):
        provider_for(load("yahoo_not_found.json"), status_code=404).fetch_daily(
            Ticker.parse("NOTAREALTICKERXYZ.NS"), date(2026, 9, 1), date(2026, 9, 25), NOW
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("currency", "USD", "expected INR"),
        ("fullExchangeName", "NasdaqGS", "resolved to exchange"),
        ("gmtoffset", -14400, "gmtoffset"),
    ],
)
def test_wrong_market_metadata_rejected(field: str, value: object, match: str) -> None:
    payload = copy.deepcopy(load("yahoo_tcs_ns_2018.json"))
    payload["chart"]["result"][0]["meta"][field] = value
    with pytest.raises(ProviderError, match=match):
        provider_for(payload).fetch_daily(TCS, *Y2018, NOW)


def test_inconsistent_arrays_rejected() -> None:
    payload = copy.deepcopy(load("yahoo_tcs_ns_2018.json"))
    payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"].pop()
    with pytest.raises(ProviderError, match="inconsistent"):
        provider_for(payload).fetch_daily(TCS, *Y2018, NOW)


@pytest.mark.parametrize("code", [429, 500, 503])
def test_http_failures_are_unavailable(code: int) -> None:
    with pytest.raises(ProviderUnavailableError):
        provider_for({}, status_code=code).fetch_daily(TCS, *Y2018, NOW)


def test_network_failure_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="unreachable"):
        provider_for(exc=httpx.ConnectTimeout("boom")).fetch_daily(TCS, *Y2018, NOW)


def test_disabled_provider_refuses() -> None:
    p = provider_for(load("yahoo_tcs_ns_2018.json"))
    p.settings = p.settings.model_copy(update={"enabled": False})
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        p.fetch_daily(TCS, *Y2018, NOW)
    assert p.status().available is False


class DictCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value


def test_cache_hit_keeps_original_retrieval_time() -> None:
    cache, calls = DictCache(), []
    p = provider_for(load("yahoo_tcs_ns_2018.json"), cache=cache, calls=calls)
    first = p.fetch_daily(TCS, *Y2018, NOW)
    second = p.fetch_daily(TCS, *Y2018, NOW)
    assert len(calls) == 1
    assert second.retrieved_at == first.retrieved_at
    assert second.retrieved_at <= datetime.now(UTC)


def test_request_window_is_ist_aligned() -> None:
    calls: list[httpx.Request] = []
    provider_for(load("yahoo_tcs_ns_2018.json"), calls=calls).fetch_daily(TCS, *Y2018, NOW)
    params = calls[0].url.params
    # 2018-01-01 00:00 IST == 2017-12-31 18:30 UTC
    assert int(params["period1"]) == int(datetime(2017, 12, 31, 18, 30, tzinfo=UTC).timestamp())
    assert calls[0].url.path.endswith("/TCS.NS")
