"""Freshness of stored daily bars (spec §32). UNKNOWN never passes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from app.market_data.calendar import CalendarRangeError, IndiaCalendar

FreshStatus = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True)
class FreshnessResult:
    status: FreshStatus
    latest_session: date | None
    expected_session: date | None
    sessions_behind: int | None
    reason: str


def evaluate_daily_freshness(
    latest_session: date | None,
    *,
    now: datetime,
    calendar: IndiaCalendar,
    availability_lag: timedelta,
    max_sessions_behind: int,
) -> FreshnessResult:
    try:
        expected = calendar.latest_completed_session(now, availability_lag)
    except CalendarRangeError as exc:
        return FreshnessResult("UNKNOWN", latest_session, None, None, str(exc))
    if latest_session is None:
        return FreshnessResult("FAIL", None, expected, None, "no price data stored")
    if latest_session >= expected:
        return FreshnessResult(
            "PASS", latest_session, expected, 0, "latest completed session stored"
        )
    try:
        behind = len(calendar.sessions(latest_session, expected)) - 1
    except CalendarRangeError as exc:
        return FreshnessResult("UNKNOWN", latest_session, expected, None, str(exc))
    status: FreshStatus = "PASS" if behind <= max_sessions_behind else "FAIL"
    return FreshnessResult(
        status,
        latest_session,
        expected,
        behind,
        f"{behind} session(s) behind (limit {max_sessions_behind})",
    )
