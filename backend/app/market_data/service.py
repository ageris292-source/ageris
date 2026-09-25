"""MarketDataService: the ONLY path by which agents and APIs obtain prices
(spec §78). Ingestion validates, versions and audits; reads return typed,
provenance-tagged series in an explicitly requested basis."""

from __future__ import annotations

import logging
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config_file import AegisConfig, get_config
from app.market_data.adjustments import AdjustmentError, convert
from app.market_data.cache import RedisResponseCache
from app.market_data.calendar import IndiaCalendar, get_calendar
from app.market_data.freshness import FreshnessResult, evaluate_daily_freshness
from app.market_data.providers.base import (
    DailyBarProvider,
    ProviderError,
    ProviderStatus,
    ProviderUnavailableError,
)
from app.market_data.providers.yahoo import YahooDailyProvider
from app.market_data.types import Bar, CorporateActionIn, PriceBasis, ProviderBatch, Ticker
from app.market_data.validation import Issue, ValidationReport, validate_bars
from app.models import CorporateAction, DataConflict, DataIngestionRun, Price, Stock
from app.services.audit import record_audit

log = logging.getLogger(__name__)


class StockNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------- providers --


def build_provider(name: str, config: AegisConfig | None = None) -> DailyBarProvider:
    cfg = config or get_config()
    md = cfg.market_data
    if name == "yahoo":
        return YahooDailyProvider(
            md.providers["yahoo"],
            get_calendar(md.calendar),
            timedelta(minutes=md.eod_availability_lag_minutes),
            cache=RedisResponseCache(),
            cache_seconds=md.provider_cache_seconds,
        )
    raise ProviderUnavailableError(f"unknown provider {name!r}")


def provider_statuses(config: AegisConfig | None = None) -> list[ProviderStatus]:
    cfg = config or get_config()
    out = [build_provider("yahoo", cfg).status()]
    csv = cfg.market_data.providers["csv_import"]
    out.append(
        ProviderStatus(
            name="csv_import",
            enabled=csv.enabled,
            licensed=csv.licensed,
            available=csv.enabled,
            reason="operator-supplied files from licensed/official sources"
            if csv.enabled
            else "disabled in configuration",
        )
    )
    return out


# ------------------------------------------------------------------- stocks --


def get_stock(db: Session, ticker: Ticker) -> Stock:
    stock = db.scalar(
        select(Stock).where(Stock.symbol == ticker.symbol, Stock.exchange == ticker.exchange.value)
    )
    if stock is None:
        raise StockNotFoundError(f"{ticker} is not in the universe")
    return stock


def add_stock(db: Session, ticker: Ticker, actor_id: uuid.UUID | None) -> Stock:
    existing = db.scalar(
        select(Stock).where(Stock.symbol == ticker.symbol, Stock.exchange == ticker.exchange.value)
    )
    if existing is not None:
        return existing
    stock = Stock(symbol=ticker.symbol, exchange=ticker.exchange.value, added_by=actor_id)
    db.add(stock)
    db.flush()
    record_audit(
        db,
        action="stock.add",
        actor_user_id=actor_id,
        entity_type="stock",
        entity_id=str(ticker),
        details={},
    )
    db.commit()
    return stock


def ticker_of(stock: Stock) -> Ticker:
    from app.market_data.types import Exchange

    return Ticker(stock.symbol, Exchange(stock.exchange))


# ---------------------------------------------------------------- ingestion --


@dataclass
class IngestResult:
    run: DataIngestionRun
    report: ValidationReport | None


def _bar_value(b: Bar | Price) -> dict[str, str | int]:
    return {
        "open": str(Decimal(b.open).normalize()),
        "high": str(Decimal(b.high).normalize()),
        "low": str(Decimal(b.low).normalize()),
        "close": str(Decimal(b.close).normalize()),
        "volume": int(b.volume),
    }


def _action_value(a: CorporateActionIn | CorporateAction) -> dict[str, str | None]:
    def n(v: Decimal | None) -> str | None:
        return None if v is None else str(Decimal(v).normalize())

    return {"numerator": n(a.numerator), "denominator": n(a.denominator), "amount": n(a.amount)}


def ingest_batch(
    db: Session,
    stock: Stock,
    batch: ProviderBatch,
    *,
    requested: tuple[date, date],
    now: datetime,
    actor_id: uuid.UUID | None = None,
    run: DataIngestionRun | None = None,
    config: AegisConfig | None = None,
) -> IngestResult:
    cfg = config or get_config()
    md = cfg.market_data
    calendar = get_calendar(md.calendar)
    lag = timedelta(minutes=md.eod_availability_lag_minutes)

    # One ingestion per stock at a time.
    db.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": zlib.crc32(f"ingest:{stock.id}".encode())}
    )

    if run is None:
        run = _new_run(db, stock, batch.source, batch.licensed, requested, actor_id)
    run.basis = batch.basis.value
    run.retrieved_at = batch.retrieved_at
    run.rows_received = len(batch.bars)

    report = validate_bars(
        batch.bars, calendar, md, now=now, window=requested, actions=batch.actions
    )
    for d in batch.dropped:
        report.issues.append(Issue("provider_dropped_row", "info", d.session, d.reason))
    run.rows_rejected = len(report.rejected)
    run.quality_score = report.quality_score
    run.usable = report.usable
    run.validation_report = report.summary()
    if batch.instrument_name and not stock.name:
        stock.name = batch.instrument_name[:200]

    inserted = unchanged = revised = 0
    for b in report.accepted:
        current = db.scalar(
            select(Price)
            .where(
                Price.stock_id == stock.id,
                Price.basis == batch.basis.value,
                Price.source == batch.source,
                Price.session_date == b.session,
            )
            .order_by(Price.data_version.desc())
            .limit(1)
        )
        if current is not None and _bar_value(current) == _bar_value(b):
            unchanged += 1
            continue
        version = 1 if current is None else current.data_version + 1
        effective = calendar.session_close_utc(b.session)
        db.add(
            Price(
                stock_id=stock.id,
                interval="1d",
                basis=batch.basis.value,
                session_date=b.session,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                source=batch.source,
                licensed=batch.licensed,
                data_version=version,
                retrieved_at=batch.retrieved_at,
                effective_at=effective,
                available_at=effective + lag,
                published_at=None,
                ingestion_run_id=run.id,
            )
        )
        if current is None:
            inserted += 1
        else:
            revised += 1
            db.add(
                DataConflict(
                    stock_id=stock.id,
                    entity="price",
                    key=f"{batch.basis.value}:{b.session.isoformat()}",
                    source=batch.source,
                    previous_version=current.data_version,
                    new_version=version,
                    previous_value=_bar_value(current),
                    new_value=_bar_value(b),
                    ingestion_run_id=run.id,
                )
            )

    amount_basis = batch.basis.value
    for a in batch.actions:
        current_a = db.scalar(
            select(CorporateAction)
            .where(
                CorporateAction.stock_id == stock.id,
                CorporateAction.kind == a.kind,
                CorporateAction.ex_date == a.ex_date,
                CorporateAction.source == batch.source,
            )
            .order_by(CorporateAction.data_version.desc())
            .limit(1)
        )
        if current_a is not None and _action_value(current_a) == _action_value(a):
            continue
        version = 1 if current_a is None else current_a.data_version + 1
        db.add(
            CorporateAction(
                stock_id=stock.id,
                kind=a.kind,
                ex_date=a.ex_date,
                numerator=a.numerator,
                denominator=a.denominator,
                amount=a.amount,
                amount_basis=amount_basis if a.kind == "dividend" else None,
                source=batch.source,
                data_version=version,
                retrieved_at=batch.retrieved_at,
                ingestion_run_id=run.id,
            )
        )
        if current_a is not None:
            db.add(
                DataConflict(
                    stock_id=stock.id,
                    entity="corporate_action",
                    key=f"{a.kind}:{a.ex_date.isoformat()}",
                    source=batch.source,
                    previous_version=current_a.data_version,
                    new_version=version,
                    previous_value=_action_value(current_a),
                    new_value=_action_value(a),
                    ingestion_run_id=run.id,
                )
            )

    run.rows_inserted, run.rows_unchanged, run.rows_revised = inserted, unchanged, revised
    if not report.accepted:
        run.status = "rejected"
    elif report.usable and not report.warnings:
        run.status = "succeeded"
    else:
        run.status = "succeeded_with_warnings"
    run.finished_at = datetime.now(UTC)
    record_audit(
        db,
        action="market_data.ingest",
        actor_user_id=actor_id,
        entity_type="stock",
        entity_id=str(ticker_of(stock)),
        details={
            "run_id": run.id,
            "source": batch.source,
            "status": run.status,
            "inserted": inserted,
            "revised": revised,
            "rejected": run.rows_rejected,
            "quality_score": run.quality_score,
            "usable": run.usable,
        },
    )
    db.commit()
    return IngestResult(run=run, report=report)


def ingest_from_provider(
    db: Session,
    stock: Stock,
    provider: DailyBarProvider,
    start: date,
    end: date,
    *,
    now: datetime | None = None,
    actor_id: uuid.UUID | None = None,
) -> IngestResult:
    now = now or datetime.now(UTC)
    if end < start:
        raise ValueError("end must not be before start")
    run = _new_run(db, stock, provider.name, provider.licensed, (start, end), actor_id)
    try:
        batch = provider.fetch_daily(ticker_of(stock), start, end, now)
    except (ProviderUnavailableError, ProviderError) as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        record_audit(
            db,
            action="market_data.ingest_failed",
            actor_user_id=actor_id,
            entity_type="stock",
            entity_id=str(ticker_of(stock)),
            details={"run_id": run.id, "error": run.error},
        )
        db.commit()
        log.warning("ingestion failed for %s: %s", ticker_of(stock), exc)
        return IngestResult(run=run, report=None)
    return ingest_batch(
        db, stock, batch, requested=(start, end), now=now, actor_id=actor_id, run=run
    )


def _new_run(
    db: Session,
    stock: Stock,
    provider: str,
    licensed: bool,
    requested: tuple[date, date],
    actor_id: uuid.UUID | None,
) -> DataIngestionRun:
    run = DataIngestionRun(
        stock_id=stock.id,
        provider=provider,
        licensed=licensed,
        requested_start=requested[0],
        requested_end=requested[1],
        status="running",
        rows_received=0,
        rows_inserted=0,
        rows_unchanged=0,
        rows_revised=0,
        rows_rejected=0,
        usable=False,
        validation_report={},
        triggered_by=actor_id,
    )
    db.add(run)
    db.flush()
    return run


# -------------------------------------------------------------------- reads --


@dataclass
class StoredBar:
    bar: Bar
    source: str
    licensed: bool
    data_version: int
    retrieved_at: datetime
    effective_at: datetime
    available_at: datetime


@dataclass
class PriceSeries:
    ticker: Ticker
    basis: PriceBasis
    stored_basis: PriceBasis | None
    derived: bool
    source: str | None
    licensed: bool | None
    bars: list[StoredBar]
    actions: list[CorporateActionIn]
    as_of: datetime | None  # point-in-time cut-off applied (available_at <= as_of)


def _latest_versions(
    db: Session,
    stock: Stock,
    basis: str,
    source: str,
    start: date,
    end: date,
    as_of: datetime | None,
) -> list[Price]:
    ranked = select(
        Price.id,
        func.row_number()
        .over(partition_by=Price.session_date, order_by=Price.data_version.desc())
        .label("rn"),
    ).where(
        Price.stock_id == stock.id,
        Price.basis == basis,
        Price.source == source,
        Price.session_date.between(start, end),
    )
    if as_of is not None:
        # Point-in-time: only versions we had actually retrieved AND that the
        # market had available by as_of.
        ranked = ranked.where(Price.available_at <= as_of, Price.retrieved_at <= as_of)
    sub = ranked.subquery()
    return list(
        db.scalars(
            select(Price)
            .join(sub, sub.c.id == Price.id)
            .where(sub.c.rn == 1)
            .order_by(Price.session_date)
        )
    )


def _stored_choice(db: Session, stock: Stock) -> tuple[str, str] | None:
    """(basis, source) to read from: licensed sources first, then most rows."""
    row = db.execute(
        select(Price.basis, Price.source, Price.licensed, func.count())
        .where(Price.stock_id == stock.id)
        .group_by(Price.basis, Price.source, Price.licensed)
        .order_by(Price.licensed.desc(), func.count().desc())
        .limit(1)
    ).first()
    return None if row is None else (row[0], row[1])


def get_actions(db: Session, stock: Stock, source: str) -> list[CorporateActionIn]:
    ranked = (
        select(
            CorporateAction.id,
            func.row_number()
            .over(
                partition_by=(CorporateAction.kind, CorporateAction.ex_date),
                order_by=CorporateAction.data_version.desc(),
            )
            .label("rn"),
        )
        .where(CorporateAction.stock_id == stock.id, CorporateAction.source == source)
        .subquery()
    )
    rows = db.scalars(
        select(CorporateAction)
        .join(ranked, ranked.c.id == CorporateAction.id)
        .where(ranked.c.rn == 1)
        .order_by(CorporateAction.ex_date)
    )
    return [
        CorporateActionIn(
            kind=r.kind,
            ex_date=r.ex_date,
            numerator=r.numerator,
            denominator=r.denominator,
            amount=r.amount,
        )
        for r in rows
    ]


def get_series(
    db: Session,
    stock: Stock,
    basis: PriceBasis,
    start: date,
    end: date,
    *,
    as_of: datetime | None = None,
) -> PriceSeries:
    ticker = ticker_of(stock)
    choice = _stored_choice(db, stock)
    if choice is None:
        return PriceSeries(ticker, basis, None, False, None, None, [], [], as_of)
    stored_basis, source = PriceBasis(choice[0]), choice[1]
    rows = _latest_versions(db, stock, stored_basis.value, source, start, end, as_of)
    actions = get_actions(db, stock, source)
    bars = [
        Bar(
            session=r.session_date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
        )
        for r in rows
    ]
    converted = convert(bars, stored_basis, basis, actions)  # raises AdjustmentError
    meta = {r.session_date: r for r in rows}
    out = [
        StoredBar(
            bar=b,
            source=meta[b.session].source,
            licensed=meta[b.session].licensed,
            data_version=meta[b.session].data_version,
            retrieved_at=meta[b.session].retrieved_at,
            effective_at=meta[b.session].effective_at,
            available_at=meta[b.session].available_at,
        )
        for b in converted
    ]
    return PriceSeries(
        ticker,
        basis,
        stored_basis,
        stored_basis != basis,
        source,
        rows[0].licensed if rows else None,
        out,
        actions,
        as_of,
    )


def latest_session(db: Session, stock: Stock) -> date | None:
    return db.scalar(select(func.max(Price.session_date)).where(Price.stock_id == stock.id))


def freshness_for(
    db: Session, stock: Stock, now: datetime, config: AegisConfig | None = None
) -> FreshnessResult:
    cfg = config or get_config()
    return evaluate_daily_freshness(
        latest_session(db, stock),
        now=now,
        calendar=get_calendar(cfg.market_data.calendar),
        availability_lag=timedelta(minutes=cfg.market_data.eod_availability_lag_minutes),
        max_sessions_behind=cfg.freshness.daily_bars_max_sessions_behind,
    )


def validate_stored(
    series: PriceSeries,
    now: datetime,
    window: tuple[date, date],
    config: AegisConfig | None = None,
    calendar: IndiaCalendar | None = None,
) -> ValidationReport:
    cfg = config or get_config()
    cal = calendar or get_calendar(cfg.market_data.calendar)
    return validate_bars(
        [s.bar for s in series.bars],
        cal,
        cfg.market_data,
        now=now,
        window=window,
        actions=series.actions,
    )


__all__ = [
    "AdjustmentError",
    "IngestResult",
    "PriceSeries",
    "StockNotFoundError",
    "add_stock",
    "build_provider",
    "freshness_for",
    "get_series",
    "get_stock",
    "ingest_batch",
    "ingest_from_provider",
    "provider_statuses",
    "validate_stored",
]
