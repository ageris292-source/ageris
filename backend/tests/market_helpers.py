"""Shared helpers for market-data tests: fixture-backed Yahoo provider."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config_file import get_config
from app.market_data.cache import NullCache, ResponseCache
from app.market_data.calendar import get_calendar
from app.market_data.providers.yahoo import YahooDailyProvider

FIXTURES = Path(__file__).parent / "fixtures"
# All recorded fixtures were captured before this instant.
NOW = datetime(2026, 9, 25, 13, 35, tzinfo=UTC)


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def with_close(payload: dict[str, Any], index: int, new_close: float) -> dict[str, Any]:
    p = copy.deepcopy(payload)
    q = p["chart"]["result"][0]["indicators"]["quote"][0]
    q["close"][index] = new_close
    q["high"][index] = max(q["high"][index], new_close)
    q["low"][index] = min(q["low"][index], new_close)
    return p


def provider_for(
    payload: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    exc: Exception | None = None,
    cache: ResponseCache | None = None,
    calls: list[httpx.Request] | None = None,
) -> YahooDailyProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if exc is not None:
            raise exc
        return httpx.Response(status_code, json=payload if payload is not None else {})

    md = get_config().market_data
    return YahooDailyProvider(
        md.providers["yahoo"],
        get_calendar(),
        timedelta(minutes=md.eod_availability_lag_minutes),
        cache=cache or NullCache(),
        cache_seconds=600,
        transport=httpx.MockTransport(handler),
    )
