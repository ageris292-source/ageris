"""FinancialDataService (spec §78): ingestion with versioning + conflict
preservation, and point-in-time reads."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.fundamentals.providers import FundamentalsBatch, YahooFundamentalsProvider
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.service import ticker_of
from app.models import DataConflict, DataIngestionRun, Stock
from app.models.fundamentals import FinancialFact
from app.services.audit import record_audit


def build_provider() -> YahooFundamentalsProvider:
    cfg = get_config()
    return YahooFundamentalsProvider(cfg.market_data.providers["yahoo"], cfg.fundamentals)


def ingest_fundamentals(
    db: Session, stock: Stock, batch: FundamentalsBatch, actor_id: uuid.UUID | None
) -> DataIngestionRun:
    periods = [f.period_end for f in batch.facts]
    run = DataIngestionRun(
        stock_id=stock.id,
        provider=batch.source,
        licensed=batch.licensed,
        basis=None,
        requested_start=min(periods),
        requested_end=max(periods),
        status="running",
        rows_received=len(batch.facts),
        rows_inserted=0,
        rows_unchanged=0,
        rows_revised=0,
        rows_rejected=0,
        usable=True,
        validation_report={"warnings": batch.warnings, "kind": "fundamentals"},
        triggered_by=actor_id,
        retrieved_at=batch.retrieved_at,
    )
    db.add(run)
    db.flush()
    ins = same = rev = 0
    for f in batch.facts:
        cur = db.scalar(
            select(FinancialFact)
            .where(
                FinancialFact.stock_id == stock.id,
                FinancialFact.period_type == f.period_type,
                FinancialFact.period_end == f.period_end,
                FinancialFact.line_item == f.line_item,
                FinancialFact.source == batch.source,
            )
            .order_by(FinancialFact.data_version.desc())
            .limit(1)
        )
        if cur is not None and Decimal(cur.value) == f.value:
            same += 1
            continue
        version = 1 if cur is None else cur.data_version + 1
        db.add(
            FinancialFact(
                stock_id=stock.id,
                period_type=f.period_type,
                period_end=f.period_end,
                line_item=f.line_item,
                value=f.value,
                currency=f.currency,
                source=batch.source,
                licensed=batch.licensed,
                retrieved_at=batch.retrieved_at,
                published_at=f.published_at,
                available_at=f.available_at,
                availability_estimated=f.availability_estimated,
                data_version=version,
                ingestion_run_id=run.id,
            )
        )
        if cur is None:
            ins += 1
        else:
            rev += 1
            db.add(
                DataConflict(
                    stock_id=stock.id,
                    entity="financial",
                    key=f"{f.period_type}:{f.period_end}:{f.line_item}",
                    source=batch.source,
                    previous_version=cur.data_version,
                    new_version=version,
                    previous_value={"value": str(cur.value)},
                    new_value={"value": str(f.value)},
                    ingestion_run_id=run.id,
                )
            )
    run.rows_inserted, run.rows_unchanged, run.rows_revised = ins, same, rev
    run.status = "succeeded_with_warnings" if batch.warnings else "succeeded"
    run.quality_score = 1.0
    run.finished_at = datetime.now(UTC)
    record_audit(
        db,
        action="fundamentals.ingest",
        actor_user_id=actor_id,
        entity_type="stock",
        entity_id=str(ticker_of(stock)),
        details={
            "run_id": run.id,
            "source": batch.source,
            "inserted": ins,
            "revised": rev,
            "licensed": batch.licensed,
        },
    )
    db.commit()
    return run


def ingest_from_yahoo(
    db: Session, stock: Stock, provider: YahooFundamentalsProvider, actor_id: uuid.UUID | None
) -> DataIngestionRun:
    try:
        batch = provider.fetch(ticker_of(stock))
    except (ProviderError, ProviderUnavailableError) as exc:
        today = datetime.now(UTC).date()
        run = DataIngestionRun(
            stock_id=stock.id,
            provider=provider.name,
            licensed=provider.licensed,
            basis=None,
            requested_start=today,
            requested_end=today,
            status="failed",
            rows_received=0,
            rows_inserted=0,
            rows_unchanged=0,
            rows_revised=0,
            rows_rejected=0,
            usable=False,
            validation_report={"kind": "fundamentals"},
            error=str(exc)[:2000],
            triggered_by=actor_id,
            finished_at=datetime.now(UTC),
        )
        db.add(run)
        db.flush()
        record_audit(
            db,
            action="fundamentals.ingest_failed",
            actor_user_id=actor_id,
            entity_type="stock",
            entity_id=str(ticker_of(stock)),
            details={"run_id": run.id, "error": run.error},
        )
        db.commit()
        return run
    return ingest_fundamentals(db, stock, batch, actor_id)


def facts_as_of(
    db: Session,
    stock: Stock,
    as_of: datetime | None,
    knowledge_at: datetime | None,
) -> list[FinancialFact]:
    """Latest version of each (period, item) visible at as_of.

    A figure with an ESTIMATED publication date is only visible if Aegis had
    actually retrieved it by as_of: we never assume what the market knew in
    the past from a guessed date (spec §33).
    """
    filters = [FinancialFact.stock_id == stock.id]
    if as_of is not None:
        filters.append(FinancialFact.available_at <= as_of)
        filters.append(
            or_(
                FinancialFact.availability_estimated.is_(False),
                and_(
                    FinancialFact.availability_estimated.is_(True),
                    FinancialFact.retrieved_at <= as_of,
                ),
            )
        )
    if knowledge_at is not None:
        filters.append(FinancialFact.retrieved_at <= knowledge_at)
    # Prefer licensed sources for each (period, item), then latest version.
    ranked = (
        select(
            FinancialFact.id,
            func.row_number()
            .over(
                partition_by=(
                    FinancialFact.period_type,
                    FinancialFact.period_end,
                    FinancialFact.line_item,
                ),
                order_by=(FinancialFact.licensed.desc(), FinancialFact.data_version.desc()),
            )
            .label("rn"),
        )
        .where(*filters)
        .subquery()
    )
    return list(
        db.scalars(
            select(FinancialFact)
            .join(ranked, ranked.c.id == FinancialFact.id)
            .where(ranked.c.rn == 1)
            .order_by(FinancialFact.period_end)
        )
    )


def periods_of(facts: list[FinancialFact], period_type: str) -> dict[date, dict[str, float]]:
    out: dict[date, dict[str, float]] = {}
    for f in facts:
        if f.period_type == period_type:
            out.setdefault(f.period_end, {})[f.line_item] = float(f.value)
    return out
