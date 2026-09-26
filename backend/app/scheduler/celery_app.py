"""Celery application (spec §67).

Jobs: heartbeat, EOD prices, news, fundamentals, macro, weekly retrain
(candidates only), paper EOD and the daily ranking. Failed ingestions raise
an alert. Nothing here places an order.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

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
        # After paper-eod: rank the universe through the Trade Risk Engine.
        # Produces a record + alert only; it never proposes or places orders.
        "daily-ranking": {
            "task": "aegis.daily_ranking",
            "schedule": crontab(minute=30, hour=12, day_of_week="mon-fri"),
        },
        # After the ranking: log the active models' predictions, check drift
        # and calibration decay, retire a failing model and alert.
        "model-monitor": {
            "task": "aegis.model_monitor",
            "schedule": crontab(minute=45, hour=12, day_of_week="mon-fri"),
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
        _alert_failures(db, "EOD prices", results, now)
    return {"at": now.isoformat(), "results": results}


def _alert_failures(db: Any, job: str, results: dict[str, str], now: datetime) -> None:
    """Raise (at most one per job per day) an alert for failed ingestions.
    An alerting problem never breaks the ingestion job itself."""
    from app.alerts.service import alert_ingestion_failures
    from app.risk.service import ist_date

    try:
        alert_ingestion_failures(db, job, results, ist_date(now))
        db.commit()
    except Exception:  # pragma: no cover - defensive
        db.rollback()
        logging.getLogger(__name__).exception("could not record ingestion alert for %s", job)


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
        _alert_failures(db, label, results, datetime.now(UTC))
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
        _alert_failures(db, "macro", results, datetime.now(UTC))
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


@celery_app.task(name="aegis.daily_ranking")  # type: ignore[untyped-decorator]
def daily_ranking() -> dict[str, object]:
    from app.db.session import _session_factory
    from app.ranking.service import run_ranking

    now = datetime.now(UTC)
    with _session_factory()() as db:
        run = run_ranking(db, now, None)
        return {
            "job": "daily_ranking",
            "at": now.isoformat(),
            "run": run.id,
            "headline": run.headline,
            "qualified": run.qualified,
            "evaluated": run.evaluated,
        }


@celery_app.task(name="aegis.model_monitor")  # type: ignore[untyped-decorator]
def model_monitor() -> dict[str, object]:
    from app.db.session import _session_factory
    from app.monitoring.service import run_monitoring

    now = datetime.now(UTC)
    with _session_factory()() as db:
        runs = run_monitoring(db, now)
        return {
            "job": "model_monitor",
            "at": now.isoformat(),
            "results": {str(r.model_id): f"{r.status} ({r.action})" for r in runs},
        }
