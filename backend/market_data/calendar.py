"""Indian exchange trading calendar (NSE/BSE share holidays; XBOM calendar).

Outside the calendar's published range we do not guess: CalendarRangeError is
raised and callers must treat the result as UNKNOWN.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


class CalendarRangeError(RuntimeError):
    pass


class IndiaCalendar:
    def __init__(self, code: str = "XBOM") -> None:
        self._cal = xcals.get_calendar(code)
        self.code = code
        self.first_session: date = self._cal.first_session.date()
        self.last_session: date = self._cal.last_session.date()

    def _check(self, d: date) -> None:
        if d < self.first_session or d > self.last_session:
            raise CalendarRangeError(
                f"{d} is outside the {self.code} calendar range "
                f"{self.first_session}..{self.last_session}; update exchange-calendars"
            )

    def is_session(self, d: date) -> bool:
        self._check(d)
        return bool(self._cal.is_session(pd.Timestamp(d)))

    def sessions(self, start: date, end: date) -> list[date]:
        if end < start:
            return []
        self._check(start)
        self._check(end)
        return [
            ts.date() for ts in self._cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        ]

    def session_close_utc(self, d: date) -> datetime:
        self._check(d)
        close: pd.Timestamp = self._cal.session_close(pd.Timestamp(d))
        return close.to_pydatetime().astimezone(UTC)

    def latest_completed_session(self, now: datetime, lag: timedelta) -> date:
        """Latest session whose close + publication lag is at or before `now`."""
        utc_today = now.astimezone(UTC).date()
        self._check(utc_today)
        end = min(utc_today + timedelta(days=1), self.last_session)  # IST is ahead of UTC
        start = max(self.first_session, end - timedelta(days=20))
        for d in reversed(self.sessions(start, end)):
            if self.session_close_utc(d) + lag <= now:
                return d
        raise CalendarRangeError("no completed session found in the last 20 days")


@lru_cache(maxsize=4)
def get_calendar(code: str = "XBOM") -> IndiaCalendar:
    return IndiaCalendar(code)
