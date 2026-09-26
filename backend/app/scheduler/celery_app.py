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
        # Every 2 hours, 08:30-18:30 IST on weekdays.
        "refresh-news": {
            "task": "aegis.refresh_news",
            "schedule": crontab(minute=0, hour="3,5,7,9,11,13", day_of_week="mon-fri"),
        },
        # Financial statements change quarterly; weekly is plenty.
        "refresh-fundamentals": {
            "task": "aegis.refresh_fundamentals",
            "schedule": crontab(minute=30, hour=2, day_of_week="sat"),
        },
        # Index levels / VIX / FX / oil after the close; World Bank annual
        # data is re-checked in the same job (idempotent, versioned).
        "refresh-macro": {
            "task": "aegis.refresh_macro",
            "schedule": crontab(minute=0, hour=12, day_of_week="mon-fri"),
        },
        # Weekly walk-forward retrain -> CANDIDATE models only. Activation is
        # always a human (admin) decision.
        "retrain-models": {
            "task": "aegis.retrain_models",
            "schedule": crontab(minute=0, hour=4, day_of_week="sun"),
        },
        # After the EOD price refresh: mark paper portfolios, check theses.
        "paper-eod": {
            "task": "aegis.paper_eod",
            "schedule": crontab(minute=15, hour=12, day_of_week="mon-fri"),
        },
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


def _for_each_stock(label: str, fn: object) -> dict[str, object]:
    from sqlalchemy import select

    from app.db.session import _session_factory
    from app.market_data.service import ticker_of
    from app.models import Stock

    results: dict[str, str] = {}
    with _session_factory()() as db:
        for stock in db.scalars(select(Stock).where(Stock.is_active)).all():
            try:
                run = fn(db, stock)  # type: ignore[operator]
                results[str(ticker_of(stock))] = run.status
            except Exception as exc:  # isolate per-stock failures
                db.rollback()
                results[str(ticker_of(stock))] = f"error: {exc.__class__.__name__}"
    return {"job": label, "at": datetime.now(UTC).isoformat(), "results": results}


@celery_app.task(name="aegis.refresh_news")  # type: ignore[untyped-decorator]
def refresh_news() -> dict[str, object]:
    from app.news import service as ns

    provider = ns.build_news_provider()
    return _for_each_stock("news", lambda db, s: ns.ingest_news(db, s, provider, None))


@celery_app.task(name="aegis.refresh_fundamentals")  # type: ignore[untyped-decorator]
def refresh_fundamentals() -> dict[str, object]:
    from app.fundamentals import service as fs

    provider = fs.build_provider()
    return _for_each_stock(
        "fundamentals", lambda db, s: fs.ingest_from_yahoo(db, s, provider, None)
    )


@celery_app.task(name="aegis.refresh_macro")  # type: ignore[untyped-decorator]
def refresh_macro() -> dict[str, object]:
    from app.db.session import _session_factory
    from app.macro import service as ms

    with _session_factory()() as db:
        results = ms.ingest_all(db, None)
    return {"job": "macro", "at": datetime.now(UTC).isoformat(), "results": results}


@celery_app.task(name="aegis.retrain_models")  # type: ignore[untyped-decorator]
def retrain_models() -> dict[str, object]:
    from app.backtest.service import run_backtest
    from app.core.config_file import get_config
    from app.db.session import _session_factory

    out: dict[str, object] = {}
    with _session_factory()() as db:
        for h in get_config().backtest.horizons:
            run = run_backtest(db, h, None)
            out[f"h{h}"] = {"run": run.id, "status": run.status}
    return {"job": "retrain", "at": datetime.now(UTC).isoformat(), "results": out}


@celery_app.task(name="aegis.paper_eod")  # type: ignore[untyped-decorator]
def paper_eod() -> dict[str, object]:
    from app.db.session import _session_factory
    from app.paper import service as paper

    now = datetime.now(UTC)
    with _session_factory()() as db:
        n = paper.snapshot_all(db, now)
        events = paper.monitor(db, now)
    return {
        "job": "paper_eod",
        "at": now.isoformat(),
        "snapshots": n,
        "events": [f"{e.thesis_id}:{e.kind}" for e in events],
    }
