"""Ticker parsing, the India exchange calendar and freshness rules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.market_data.calendar import CalendarRangeError, get_calendar
from app.market_data.freshness import evaluate_daily_freshness
from app.market_data.types import Exchange, InvalidTickerError, Ticker

LAG = timedelta(minutes=60)


@pytest.mark.parametrize(
    ("raw", "symbol", "exchange"),
    [
        ("TCS.NS", "TCS", Exchange.NSE),
        ("reliance.bo", "RELIANCE", Exchange.BSE),
        ("M&M.NS", "M&M", Exchange.NSE),
        ("BAJAJ-AUTO.NS", "BAJAJ-AUTO", Exchange.NSE),
    ],
)
def test_ticker_parse(raw: str, symbol: str, exchange: Exchange) -> None:
    t = Ticker.parse(raw)
    assert (t.symbol, t.exchange) == (symbol, exchange)
    assert Ticker.parse(str(t)) == t


@pytest.mark.parametrize("raw", ["TCS", "AAPL", "AAPL.US", ".NS", "TC S.NS", "X" * 21 + ".NS"])
def test_ticker_rejects_non_indian_or_malformed(raw: str) -> None:
    with pytest.raises(InvalidTickerError):
        Ticker.parse(raw)


def test_calendar_sessions_and_holidays() -> None:
    cal = get_calendar()
    assert cal.is_session(date(2026, 9, 25))  # Friday
    assert not cal.is_session(date(2026, 9, 26))  # Saturday
    assert not cal.is_session(date(2026, 10, 2))  # Gandhi Jayanti
    # 15:30 IST close == 10:00 UTC
    assert cal.session_close_utc(date(2026, 9, 25)) == datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 25, 10, 59, tzinfo=UTC), date(2026, 9, 24)),  # close+lag not reached
        (datetime(2026, 9, 25, 11, 0, tzinfo=UTC), date(2026, 9, 25)),  # exactly close+lag
        (datetime(2026, 9, 27, 8, 0, tzinfo=UTC), date(2026, 9, 25)),  # Sunday
        (datetime(2026, 10, 2, 12, 0, tzinfo=UTC), date(2026, 10, 1)),  # holiday
        (datetime(2026, 9, 28, 1, 0, tzinfo=UTC), date(2026, 9, 25)),  # Monday pre-open IST
    ],
)
def test_latest_completed_session(now: datetime, expected: date) -> None:
    assert get_calendar().latest_completed_session(now, LAG) == expected


def test_calendar_out_of_range_raises() -> None:
    cal = get_calendar()
    beyond = cal.last_session + timedelta(days=10)
    with pytest.raises(CalendarRangeError):
        cal.is_session(beyond)
    with pytest.raises(CalendarRangeError):
        cal.latest_completed_session(datetime.combine(beyond, datetime.min.time(), UTC), LAG)


def _fresh(latest: date | None, now: datetime, max_behind: int = 1) -> str:
    return evaluate_daily_freshness(
        latest,
        now=now,
        calendar=get_calendar(),
        availability_lag=LAG,
        max_sessions_behind=max_behind,
    ).status


def test_freshness_rules() -> None:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # after Friday close + lag
    assert _fresh(date(2026, 9, 25), now) == "PASS"
    assert _fresh(date(2026, 9, 24), now) == "PASS"  # 1 behind, limit 1
    assert _fresh(date(2026, 9, 24), now, max_behind=0) == "FAIL"
    assert _fresh(date(2026, 9, 23), now) == "FAIL"  # 2 behind
    assert _fresh(None, now) == "FAIL"
    # Across a weekend + holiday: Thu 1 Oct is the latest completed on Fri 2 Oct (holiday).
    assert _fresh(date(2026, 10, 1), datetime(2026, 10, 4, 6, 0, tzinfo=UTC), 0) == "PASS"


def test_freshness_unknown_outside_calendar_never_passes() -> None:
    cal = get_calendar()
    far = datetime.combine(cal.last_session + timedelta(days=30), datetime.min.time(), UTC)
    result = evaluate_daily_freshness(
        cal.last_session, now=far, calendar=cal, availability_lag=LAG, max_sessions_behind=5
    )
    assert result.status == "UNKNOWN"
