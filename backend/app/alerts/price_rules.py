"""Personal price alerts, checked against each NEW end-of-day close.

Rules:
- Only fresh data is used. If the stock's stored prices are stale or their
  freshness is UNKNOWN, the rule is not checked (and says so); it never fires
  on data Aegis cannot vouch for.
- Each stored session is evaluated at most once per rule.
- A missing input (e.g. too little history for RSI) is reported, never
  treated as a value.
- A rule only informs. Nothing here proposes or places an order.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.service import raise_alert
from app.analysis.indicators import rsi
from app.market_data import service
from app.market_data.types import PriceBasis
from app.models import PriceAlert, Stock

log = logging.getLogger(__name__)

RSI_LOOKBACK_DAYS = 400  # ~270 sessions: Wilder smoothing has converged

LABELS = {
    "price_above": "closes above",
    "price_below": "closes below",
    "day_change_up": "rises by at least",
    "day_change_down": "falls by at least",
    "rsi_above": "RSI(14) above",
    "rsi_below": "RSI(14) below",
}


@dataclass(frozen=True)
class CheckResult:
    rule_id: int
    status: str
    fired: bool
    session: date | None
    value: float | None


def describe(condition: str, threshold: Decimal | float) -> str:
    t = float(threshold)
    if condition in ("price_above", "price_below"):
        return f"{LABELS[condition]} ₹{t:,.2f}"
    if condition in ("day_change_up", "day_change_down"):
        return f"{LABELS[condition]} {t:g}% in a day"
    return f"{LABELS[condition]} {t:g}"


def _fmt_value(condition: str, v: float) -> str:
    if condition.startswith("price"):
        return f"₹{v:,.2f}"
    if condition.startswith("day_change"):
        return f"{v:+.2f}%"
    return f"{v:.1f}"


def _met(condition: str, value: float, threshold: float) -> bool:
    if condition in ("price_above", "rsi_above"):
        return value > threshold
    if condition in ("price_below", "rsi_below"):
        return value < threshold
    if condition == "day_change_up":
        return value >= threshold
    return value <= -threshold  # day_change_down: threshold is a positive size


def _observe(
    db: Session, stock: Stock, condition: str, now: datetime
) -> tuple[date | None, float | None, str]:
    """(session, value, status). value is None when it cannot be computed."""
    fresh = service.freshness_for(db, stock, now)
    if fresh.status != "PASS":
        return None, None, f"not checked: price data {fresh.status.lower()} ({fresh.reason})"
    latest = fresh.latest_session
    assert latest is not None
    end = min(latest, now.date())
    days = RSI_LOOKBACK_DAYS if condition.startswith("rsi") else 20
    series = service.get_series(
        db, stock, PriceBasis.SPLIT_ADJUSTED, end - timedelta(days=days), end, as_of=now
    )
    bars = series.bars
    if not bars:
        return None, None, "not checked: no stored bars"
    session = bars[-1].bar.session
    closes = [float(b.bar.close) for b in bars]
    if condition.startswith("price"):
        return session, closes[-1], "checked"
    if condition.startswith("day_change"):
        if len(closes) < 2 or closes[-2] <= 0:
            return session, None, "not checked: no previous close"
        return session, (closes[-1] / closes[-2] - 1) * 100, "checked"
    r = rsi(np.asarray(closes))
    last = float(r[-1]) if len(r) else math.nan
    if math.isnan(last):
        return session, None, "not checked: not enough history for RSI(14)"
    return session, last, "checked"


def check_rule(db: Session, rule: PriceAlert, now: datetime) -> CheckResult:
    """Evaluate one rule (flushes; caller commits)."""
    stock = db.get(Stock, rule.stock_id)
    rule.last_checked_at = now
    if stock is None or not rule.is_active:
        rule.last_status = "not checked: rule inactive"
        return CheckResult(rule.id, rule.last_status, False, None, None)
    session, value, status = _observe(db, stock, rule.condition, now)
    if session is not None and session == rule.last_session and value is not None:
        rule.last_status = "waiting for the next close"
        return CheckResult(rule.id, rule.last_status, False, session, rule.last_value)
    rule.last_status = status[:120]
    if value is None or session is None:
        return CheckResult(rule.id, rule.last_status, False, session, None)

    rule.last_session, rule.last_value = session, value
    met = _met(rule.condition, value, float(rule.threshold))
    fired = False
    if met and rule.armed:
        ticker = str(service.ticker_of(stock))
        cond = describe(rule.condition, rule.threshold)
        title = f"{ticker} {cond}"
        body = (
            f"{stock.name or ticker} {cond}: {_fmt_value(rule.condition, value)} "
            f"on the {session.isoformat()} close."
            + (f"\nYour note: {rule.note}" if rule.note else "")
            + "\nThis is an information alert only. Aegis does not trade on it."
        )
        raise_alert(
            db,
            kind="price_alert",
            severity="warning" if rule.importance == "high" else "info",
            title=title,
            body=body,
            link=f"/stocks/{ticker}",
            dedupe_key=f"price_alert:{rule.id}:{session.isoformat()}",
            user_id=rule.user_id,
        )
        fired = True
        rule.trigger_count += 1
        rule.last_triggered_at = now
        rule.armed = False
        rule.last_status = "triggered"
        if not rule.repeat:
            rule.is_active = False
    elif not met:
        rule.armed = True  # a repeating rule re-arms once the condition clears
    db.flush()
    return CheckResult(rule.id, rule.last_status, fired, session, value)


def check_all(db: Session, now: datetime, user_id: object | None = None) -> list[CheckResult]:
    """Check every active rule (optionally one user's). One failing rule never
    stops the others. Commits per rule."""
    q = select(PriceAlert).where(PriceAlert.is_active.is_(True))
    if user_id is not None:
        q = q.where(PriceAlert.user_id == user_id)
    out: list[CheckResult] = []
    for rule in db.scalars(q.order_by(PriceAlert.id)).all():
        try:
            out.append(check_rule(db, rule, now))
            db.commit()
        except Exception as exc:  # isolate per-rule failures
            db.rollback()
            log.warning("price alert %s failed: %s", rule.id, exc.__class__.__name__)
            out.append(CheckResult(rule.id, f"error: {exc.__class__.__name__}", False, None, None))
    return out
