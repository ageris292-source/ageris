"""Stocks & prices API (spec §63). Indian equities only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config_file import get_config
from app.market_data import service
from app.market_data.adjustments import AdjustmentError
from app.market_data.providers.base import DailyBarProvider, ProviderError, ProviderUnavailableError
from app.market_data.providers.csv_import import parse_csv_bars
from app.market_data.types import InvalidTickerError, PriceBasis, Ticker
from app.models import DataConflict, DataIngestionRun, Stock
from app.schemas.market import (
    UNLICENSED_NOTICE,
    AddStockRequest,
    BarOut,
    CorporateActionOut,
    DataQualityOut,
    FreshnessOut,
    IngestionRunOut,
    IngestRequest,
    PriceSeriesOut,
    ProviderStatusOut,
    StockDetail,
    StockSummary,
)

router = APIRouter(tags=["market-data"])

DEFAULT_HISTORY_DAYS = 5 * 365  # first ingest: five years of history
REVISION_OVERLAP_DAYS = 10  # re-fetch recent sessions to detect provider revisions
QUALITY_WINDOW_DAYS = 365
MAX_CSV_BYTES = 5 * 1024 * 1024


def get_now() -> datetime:
    return datetime.now(UTC)


def get_daily_provider() -> DailyBarProvider:
    return service.build_provider("yahoo")


Now = Annotated[datetime, Depends(get_now)]
Provider = Annotated[DailyBarProvider, Depends(get_daily_provider)]


def _ticker(raw: str) -> Ticker:
    try:
        return Ticker.parse(raw)
    except InvalidTickerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _stock(db: DbSession, raw: str) -> Stock:
    try:
        return service.get_stock(db, _ticker(raw))
    except service.StockNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _run_out(run: DataIngestionRun) -> IngestionRunOut:
    return IngestionRunOut.model_validate(run, from_attributes=True)


def _summary(db: DbSession, stock: Stock, now: datetime) -> StockSummary:
    f = service.freshness_for(db, stock, now)
    last = db.scalar(
        select(DataIngestionRun.status)
        .where(DataIngestionRun.stock_id == stock.id)
        .order_by(DataIngestionRun.id.desc())
        .limit(1)
    )
    return StockSummary(
        ticker=str(service.ticker_of(stock)),
        symbol=stock.symbol,
        exchange=stock.exchange,
        name=stock.name,
        currency=stock.currency,
        latest_session=f.latest_session,
        freshness=FreshnessOut(**f.__dict__),
        last_run_status=last,
    )


@router.get("/stocks", response_model=list[StockSummary])
def list_stocks(db: DbSession, _u: CurrentUser, now: Now) -> list[StockSummary]:
    stocks = db.scalars(select(Stock).where(Stock.is_active).order_by(Stock.symbol))
    return [_summary(db, s, now) for s in stocks]


@router.post("/stocks", response_model=StockSummary, status_code=status.HTTP_201_CREATED)
def add_stock(body: AddStockRequest, db: DbSession, user: AdminUser, now: Now) -> StockSummary:
    stock = service.add_stock(db, _ticker(body.ticker), user.id)
    return _summary(db, stock, now)


@router.get("/stocks/{ticker}", response_model=StockDetail)
def stock_detail(ticker: str, db: DbSession, _u: CurrentUser, now: Now) -> StockDetail:
    stock = _stock(db, ticker)
    summary = _summary(db, stock, now)
    end = summary.latest_session or now.date()
    start = end - timedelta(days=QUALITY_WINDOW_DAYS)
    series = (
        service.get_series(db, stock, PriceBasis.SPLIT_ADJUSTED, start, end)
        if (summary.latest_session)
        else None
    )
    if series is not None and series.stored_basis == PriceBasis.RAW:
        series = service.get_series(db, stock, PriceBasis.RAW, start, end)

    quality = None
    latest_bar = None
    if series and series.bars:
        report = service.validate_stored(series, now, (start, end))
        s = report.summary()
        quality = DataQualityOut(
            window_start=series.bars[0].bar.session,
            window_end=series.bars[-1].bar.session,
            usable=report.usable,
            quality_score=report.quality_score,
            expected_sessions=report.expected_sessions,
            missing_session_count=len(report.missing_sessions),
            coverage=report.coverage,
            minimum_score_required=get_config().trade_gates.minimum_data_quality_score,
            issues=s["issues"],
        )
        latest_bar = _bar_out(series.bars[-1])

    runs = db.scalars(
        select(DataIngestionRun)
        .where(DataIngestionRun.stock_id == stock.id)
        .order_by(DataIngestionRun.id.desc())
        .limit(5)
    )
    conflicts = db.scalar(
        select(func.count()).select_from(DataConflict).where(DataConflict.stock_id == stock.id)
    )
    licensed = series.licensed if series else None
    return StockDetail(
        **summary.model_dump(),
        latest_bar=latest_bar,
        stored_basis=series.stored_basis.value if series and series.stored_basis else None,
        source=series.source if series else None,
        licensed=licensed,
        licensing_notice=UNLICENSED_NOTICE if licensed is False else None,
        data_quality=quality,
        corporate_actions=[
            CorporateActionOut(**a.model_dump()) for a in (series.actions if series else [])
        ],
        recent_runs=[_run_out(r) for r in runs],
        open_conflicts=conflicts or 0,
    )


def _bar_out(sb: service.StoredBar) -> BarOut:
    b = sb.bar
    return BarOut(
        session=b.session,
        open=b.open,
        high=b.high,
        low=b.low,
        close=b.close,
        volume=b.volume,
        source=sb.source,
        data_version=sb.data_version,
        retrieved_at=sb.retrieved_at,
        effective_at=sb.effective_at,
        available_at=sb.available_at,
    )


@router.get("/stocks/{ticker}/prices", response_model=PriceSeriesOut)
def prices(
    ticker: str,
    db: DbSession,
    _u: CurrentUser,
    now: Now,
    basis: PriceBasis = PriceBasis.SPLIT_ADJUSTED,
    start: date | None = None,
    end: date | None = None,
    as_of: Annotated[
        datetime | None,
        Query(description="Point-in-time cut-off: only data available at this instant"),
    ] = None,
) -> PriceSeriesOut:
    stock = _stock(db, ticker)
    end = end or now.date()
    start = start or end - timedelta(days=QUALITY_WINDOW_DAYS)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start must be <= end")
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "as_of must include a timezone")
    try:
        series = service.get_series(db, stock, basis, start, end, as_of=as_of)
    except AdjustmentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return PriceSeriesOut(
        ticker=str(series.ticker),
        basis=series.basis,
        stored_basis=series.stored_basis,
        derived=series.derived,
        source=series.source,
        licensed=series.licensed,
        licensing_notice=UNLICENSED_NOTICE if series.licensed is False else None,
        as_of=as_of,
        bars=[_bar_out(b) for b in series.bars],
    )


@router.post("/stocks/{ticker}/ingest", response_model=IngestionRunOut)
def ingest(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    provider: Provider,
    body: IngestRequest | None = None,
) -> IngestionRunOut:
    stock = _stock(db, ticker)
    body = body or IngestRequest()
    end = body.end or now.date()
    if body.start is not None:
        start = body.start
    else:
        last = service.latest_session(db, stock)
        start = (
            last - timedelta(days=REVISION_OVERLAP_DAYS)
            if last
            else end - timedelta(days=DEFAULT_HISTORY_DAYS)
        )
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start must be <= end")
    result = service.ingest_from_provider(
        db, stock, provider, start, end, now=now, actor_id=user.id
    )
    return _run_out(result.run)


@router.post("/stocks/{ticker}/import-csv", response_model=IngestionRunOut)
async def import_csv(
    ticker: str,
    db: DbSession,
    user: AdminUser,
    now: Now,
    file: Annotated[UploadFile, File()],
    source: Annotated[str, Form(min_length=1, max_length=60)],
    basis: Annotated[PriceBasis, Form()],
) -> IngestionRunOut:
    stock = _stock(db, ticker)
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV larger than 5 MB")
    try:
        batch = parse_csv_bars(
            raw.decode("utf-8-sig"),
            service.ticker_of(stock),
            source,
            basis,
            get_config().market_data.providers["csv_import"],
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "CSV must be UTF-8") from exc
    except (ProviderError, ProviderUnavailableError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    sessions = [b.session for b in batch.bars]
    result = service.ingest_batch(
        db, stock, batch, requested=(min(sessions), max(sessions)), now=now, actor_id=user.id
    )
    return _run_out(result.run)


@router.get("/data/providers", response_model=list[ProviderStatusOut])
def providers(_u: CurrentUser) -> list[ProviderStatusOut]:
    return [ProviderStatusOut(**p.__dict__) for p in service.provider_statuses()]
