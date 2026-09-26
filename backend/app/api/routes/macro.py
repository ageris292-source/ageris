"""Macro, regime and valuation API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.agents.base import AgentOutput
from app.agents.macro import agent as macro_agent
from app.agents.valuation import agent as valuation_agent
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.stocks import Now, _stock, _ticker
from app.macro import service as ms

router = APIRouter(tags=["macro"])


def _aware(name: str, v: datetime | None) -> None:
    if v is not None and v.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must include a timezone")


@router.get("/macro")
def macro_summary(db: DbSession, _u: CurrentUser) -> list[dict[str, Any]]:
    return ms.latest_summary(db)


@router.post("/macro/ingest")
def macro_ingest(db: DbSession, user: AdminUser) -> dict[str, str]:
    return ms.ingest_all(db, user.id)


class ManualEntry(BaseModel):
    series: str = Field(pattern=r"^[a-z0-9_]{2,60}$", examples=["repo_rate"])
    period_date: date
    value: float
    unit: str = Field(min_length=1, max_length=30, examples=["fraction"])
    source: str = Field(min_length=5, max_length=110, examples=["RBI MPC statement"])
    published_at: datetime


@router.post("/macro/manual", status_code=status.HTTP_201_CREATED)
def macro_manual(body: ManualEntry, db: DbSession, user: AdminUser) -> dict[str, Any]:
    _aware("published_at", body.published_at)
    row = ms.add_manual(
        db,
        series=body.series,
        period_date=body.period_date,
        value=body.value,
        unit=body.unit,
        source=body.source,
        published_at=body.published_at,
        user=user.id,
    )
    return {"id": row.id, "series": row.series, "version": row.data_version}


@router.get("/regime")
def regime(
    db: DbSession, _u: CurrentUser, now: Now, as_of: Annotated[datetime | None, Query()] = None
) -> dict[str, Any]:
    _aware("as_of", as_of)
    r = macro_agent.current_regime(db, as_of or now)
    return {
        "label": r.label,
        "trend": r.trend,
        "volatility": r.volatility,
        "risk": r.risk,
        "known": r.known,
        "evidence": r.evidence,
    }


@router.get("/macro-agent/{ticker}", response_model=AgentOutput)
def macro_analysis(
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
    return macro_agent.run_and_record(db, t, as_of or now, user.id, knowledge_at)


class ValuationOut(BaseModel):
    analysis: AgentOutput
    details: dict[str, Any]


@router.get("/valuation/{ticker}", response_model=ValuationOut)
def valuation(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    as_of: Annotated[datetime | None, Query()] = None,
    knowledge_at: Annotated[datetime | None, Query()] = None,
) -> ValuationOut:
    _aware("as_of", as_of)
    _aware("knowledge_at", knowledge_at)
    t = _ticker(ticker)
    _stock(db, ticker)
    out, details = valuation_agent.run_and_record(db, t, as_of or now, user.id, knowledge_at)
    return ValuationOut(analysis=out, details=details)
