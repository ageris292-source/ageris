"""Financials + fundamental agent API (spec §63: GET /financials/{ticker})."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.agents.base import AgentOutput
from app.agents.fundamental import agent as fundamental
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.stocks import MAX_CSV_BYTES, Now, _run_out, _stock, _ticker
from app.core.config_file import get_config
from app.fundamentals import service as fs
from app.fundamentals.providers import YahooFundamentalsProvider, parse_fundamentals_csv
from app.fundamentals.ratios import annual_ratios
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.schemas.market import IngestionRunOut

router = APIRouter(tags=["fundamentals"])


def get_fundamentals_provider() -> YahooFundamentalsProvider:
    return fs.build_provider()


FProvider = Annotated[YahooFundamentalsProvider, Depends(get_fundamentals_provider)]


class PeriodOut(BaseModel):
    period_end: date
    values: dict[str, float]
    ratios: dict[str, float | None]


class FinancialsOut(BaseModel):
    ticker: str
    currency: str = "INR"
    sources: list[str]
    licensed: bool | None
    availability_estimated: bool
    annual: list[PeriodOut]
    quarterly: list[PeriodOut]
    notice: str | None


def _aware(name: str, v: datetime | None) -> None:
    if v is not None and v.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must include a timezone")


@router.get("/financials/{ticker}", response_model=FinancialsOut)
def financials(
    ticker: str,
    db: DbSession,
    _u: CurrentUser,
    as_of: Annotated[datetime | None, Query()] = None,
) -> FinancialsOut:
    _aware("as_of", as_of)
    stock = _stock(db, ticker)
    facts = fs.facts_as_of(db, stock, as_of, None)
    annual = annual_ratios(fs.periods_of(facts, "annual"))
    quarterly = fs.periods_of(facts, "quarterly")
    licensed = None if not facts else all(f.licensed for f in facts)
    estimated = any(f.availability_estimated for f in facts)
    return FinancialsOut(
        ticker=str(_ticker(ticker)),
        sources=sorted({f.source for f in facts}),
        licensed=licensed,
        availability_estimated=estimated,
        annual=[
            PeriodOut(period_end=r.period_end, values=r.values, ratios=r.ratios) for r in annual
        ],
        quarterly=[
            PeriodOut(period_end=d, values=v, ratios={}) for d, v in sorted(quarterly.items())
        ],
        notice=(
            "Unlicensed source with estimated publication dates: research only."
            if licensed is False
            else None
        ),
    )


@router.post("/financials/{ticker}/ingest", response_model=IngestionRunOut)
def ingest_financials(
    ticker: str, db: DbSession, user: CurrentUser, provider: FProvider
) -> IngestionRunOut:
    stock = _stock(db, ticker)
    return _run_out(fs.ingest_from_yahoo(db, stock, provider, user.id))


@router.post("/financials/{ticker}/import-csv", response_model=IngestionRunOut)
async def import_financials_csv(
    ticker: str,
    db: DbSession,
    user: AdminUser,
    file: Annotated[UploadFile, File()],
    source: Annotated[str, Form(min_length=1, max_length=60)],
) -> IngestionRunOut:
    stock = _stock(db, ticker)
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV larger than 5 MB")
    try:
        batch = parse_fundamentals_csv(
            raw.decode("utf-8-sig"),
            _ticker(ticker),
            source,
            get_config().market_data.providers["csv_import"],
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "CSV must be UTF-8") from exc
    except (ProviderError, ProviderUnavailableError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _run_out(fs.ingest_fundamentals(db, stock, batch, user.id))


@router.get("/fundamental/{ticker}", response_model=AgentOutput)
def fundamental_analysis(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    as_of: Annotated[datetime | None, Query()] = None,
    knowledge_at: Annotated[datetime | None, Query()] = None,
) -> AgentOutput:
    _aware("as_of", as_of)
    _aware("knowledge_at", knowledge_at)
    t = _ticker(ticker)
    _stock(db, ticker)
    return fundamental.run_and_record(db, t, as_of or now, user.id, knowledge_at)
