"""Compact price snapshot for lists (stocks table, watchlist): last close,
day change and a short closing-price sparkline, all as stored at `now`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.market_data import service
from app.market_data.types import PriceBasis
from app.models import Stock

SPARK_SESSIONS = 30


@dataclass(frozen=True)
class PriceSnapshot:
    latest_session: date | None = None
    last_close: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    sparkline: list[float] = field(default_factory=list)


def price_snapshot(db: Session, stock: Stock, now: datetime) -> PriceSnapshot:
    # Anchor on the stock's own latest stored session, so a stale series still
    # shows its last close (freshness is reported separately).
    latest = service.latest_session(db, stock)
    if latest is None:
        return PriceSnapshot()
    end = min(latest, now.date())
    try:
        s = service.get_series(
            db, stock, PriceBasis.SPLIT_ADJUSTED, end - timedelta(days=60), end, as_of=now
        )
    except Exception:
        return PriceSnapshot()
    closes = [float(b.bar.close) for b in s.bars]
    if not closes:
        return PriceSnapshot()
    last = closes[-1]
    prev = closes[-2] if len(closes) > 1 else None
    return PriceSnapshot(
        latest_session=s.bars[-1].bar.session,
        last_close=last,
        prev_close=prev,
        change_pct=(last / prev - 1) if prev else None,
        sparkline=closes[-SPARK_SESSIONS:],
    )
