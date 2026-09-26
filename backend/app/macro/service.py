"""MacroDataService (spec §78): ingestion with versioning, manual entries,
and point-in-time reads."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.macro.providers import Obs, WorldBankProvider, YahooSeriesProvider
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.models.macro import MacroObservation
from app.services.audit import record_audit


def store(
    db: Session, obs: list[Obs], retrieved_at: datetime, user: uuid.UUID | None = None
) -> int:
    inserted = 0
    latest = {
        (r.series, r.period_date, r.source): r
        for r in db.scalars(
            select(MacroObservation)
            .where(
                MacroObservation.series.in_({o.series for o in obs}),
                MacroObservation.period_date.in_({o.period_date for o in obs}),
            )
            .order_by(MacroObservation.data_version)
        )
    }
    for o in obs:
        cur = latest.get((o.series, o.period_date, o.source))
        if cur is not None and abs(cur.value - o.value) <= 1e-9 * max(1.0, abs(o.value)):
            continue
        db.add(
            MacroObservation(
                series=o.series,
                frequency=o.frequency,
                period_date=o.period_date,
                value=o.value,
                unit=o.unit,
                source=o.source,
                licensed=o.licensed,
                retrieved_at=retrieved_at,
                published_at=o.published_at,
                available_at=o.available_at,
                availability_estimated=o.availability_estimated,
                data_version=1 if cur is None else cur.data_version + 1,
                entered_by=user,
            )
        )
        inserted += 1
    return inserted


def ingest_all(
    db: Session,
    user: uuid.UUID | None,
    world_bank: WorldBankProvider | None = None,
    yahoo: YahooSeriesProvider | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    cfg = get_config().macro
    now = now or datetime.now(UTC)
    wb = world_bank or WorldBankProvider(cfg.world_bank_publication_lag_days)
    yh = yahoo or YahooSeriesProvider()
    results: dict[str, str] = {}
    for series, indicator in cfg.world_bank_indicators.items():
        try:
            n = store(db, wb.fetch(series, indicator), datetime.now(UTC), user)
            results[series] = f"ok (+{n})"
        except (ProviderError, ProviderUnavailableError) as exc:
            results[series] = f"failed: {exc}"
    start = now.date() - timedelta(days=cfg.history_days)
    for series, symbol in cfg.market_series.items():
        try:
            n = store(db, yh.fetch(series, symbol, start, now), datetime.now(UTC), user)
            results[series] = f"ok (+{n})"
        except (ProviderError, ProviderUnavailableError) as exc:
            results[series] = f"failed: {exc}"
    record_audit(db, action="macro.ingest", actor_user_id=user, details=results)
    db.commit()
    return results


def add_manual(
    db: Session,
    *,
    series: str,
    period_date: date,
    value: float,
    unit: str,
    source: str,
    published_at: datetime,
    user: uuid.UUID,
) -> MacroObservation:
    """Hand-entered official figure (e.g. RBI repo rate) with its real source
    and publication time. Never estimated."""
    now = datetime.now(UTC)
    store(
        db,
        [
            Obs(
                series,
                "event",
                period_date,
                value,
                unit,
                f"manual: {source}",
                True,
                published_at,
                published_at,
                False,
            )
        ],
        now,
        user,
    )
    record_audit(
        db,
        action="macro.manual_entry",
        actor_user_id=user,
        details={
            "series": series,
            "date": period_date.isoformat(),
            "value": value,
            "source": source,
        },
    )
    db.commit()
    row = db.scalar(
        select(MacroObservation)
        .where(
            MacroObservation.series == series,
            MacroObservation.period_date == period_date,
        )
        .order_by(MacroObservation.data_version.desc())
        .limit(1)
    )
    assert row is not None
    return row


def series_as_of(
    db: Session,
    series: str,
    as_of: datetime | None,
    knowledge_at: datetime | None = None,
    start: date | None = None,
) -> list[tuple[date, float]]:
    """Latest version per date, visible at as_of. Estimated-availability rows
    are only visible if Aegis had retrieved them by as_of."""
    filters = [MacroObservation.series == series]
    if start is not None:
        filters.append(MacroObservation.period_date >= start)
    if as_of is not None:
        filters.append(MacroObservation.available_at <= as_of)
        filters.append(
            or_(
                MacroObservation.availability_estimated.is_(False),
                and_(
                    MacroObservation.availability_estimated.is_(True),
                    MacroObservation.retrieved_at <= as_of,
                ),
            )
        )
    if knowledge_at is not None:
        filters.append(MacroObservation.retrieved_at <= knowledge_at)
    ranked = (
        select(
            MacroObservation.id,
            func.row_number()
            .over(
                partition_by=MacroObservation.period_date,
                order_by=(MacroObservation.licensed.desc(), MacroObservation.data_version.desc()),
            )
            .label("rn"),
        )
        .where(*filters)
        .subquery()
    )
    rows = db.execute(
        select(MacroObservation.period_date, MacroObservation.value)
        .join(ranked, ranked.c.id == MacroObservation.id)
        .where(ranked.c.rn == 1)
        .order_by(MacroObservation.period_date)
    ).all()
    return [(d, v) for d, v in rows]


def latest_summary(db: Session) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            MacroObservation.series,
            func.max(MacroObservation.period_date),
            func.count(),
            func.bool_and(MacroObservation.licensed),
            func.max(MacroObservation.retrieved_at),
        )
        .group_by(MacroObservation.series)
        .order_by(MacroObservation.series)
    ).all()
    out: list[dict[str, object]] = []
    for series, last, n, licensed, retrieved in rows:
        vals = series_as_of(db, series, None)
        out.append(
            {
                "series": series,
                "latest_date": last,
                "latest_value": vals[-1][1] if vals else None,
                "observations": n,
                "licensed": licensed,
                "retrieved_at": retrieved,
            }
        )
    return out
