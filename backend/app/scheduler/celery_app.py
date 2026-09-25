"""Celery application (spec §67).

Phase 1 registers only a heartbeat task that proves the worker, broker and
database path work end to end. Data-refresh, analysis and ranking jobs are
added by the phases that implement them; nothing here fabricates work.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery import Celery

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
    },
)


@celery_app.task(name="aegis.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> dict[str, object]:
    from app.db.session import database_healthy

    return {"at": datetime.now(UTC).isoformat(), "database": database_healthy()}
