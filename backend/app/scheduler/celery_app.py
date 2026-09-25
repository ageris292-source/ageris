"""Celery application (spec §67).

Jobs: heartbeat (Phase 1) and daily NSE/BSE end-of-day price refresh
(Phase 2). Analysis and ranking jobs are added by the phases that implement
them; nothing here fabricates work.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery import Celery
from celery.schedules import crontab

from app.core.settings import get_settings

_settings = get_settings()

celery_app = Celery("aegis", broker=_settings.redis_url, backend=_settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "heartbeat": {"task": "aegis.heartbeat", "schedule": 300.0},
        # 17:15 IST (11:45 UTC) Mon-Fri: after the 15:30 close plus the
        # configured availability lag. Holidays are skipped by the calendar.
        "refresh-eod-prices": {
            "task": "aegis.refresh_eod_prices",
            "schedule": crontab(minute=45, hour=11, day_of_week="mon-fri"),
        },
    },
)


@celery_app.task(name="aegis.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> dict[str, object]:
    from app.db.session import database_healthy

    return {"at": datetime.now(UTC).isoformat(), "database": database_healthy()}


@celery_app.task(name="aegis.refresh_eod_prices")  # type: ignore[untyped-decorator]
def refresh_eod_prices() -> dict[str, object]:
    """Incrementally refresh every active stock. Each stock is independent:
    one failure is recorded on its ingestion run and does not stop others."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.db.session import _session_factory
    from app.market_data import service
    from app.models import Stock

    now = datetime.now(UTC)
    provider = service.build_provider("yahoo")
    results: dict[str, str] = {}
    with _session_factory()() as db:
        for stock in db.scalars(select(Stock).where(Stock.is_active)).all():
            last = service.latest_session(db, stock)
            start = (last - timedelta(days=10)) if last else now.date() - timedelta(days=5 * 365)
            try:
                res = service.ingest_from_provider(db, stock, provider, start, now.date(), now=now)
                results[str(service.ticker_of(stock))] = res.run.status
            except Exception as exc:  # isolate per-stock failures; run is still audited
                db.rollback()
                results[str(service.ticker_of(stock))] = f"error: {exc.__class__.__name__}"
    return {"at": now.isoformat(), "results": results}
