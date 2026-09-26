"""Risk agent and portfolio API (spec §13, §14)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentOutput
from app.agents.portfolio import agent as portfolio_agent
from app.agents.risk import agent as risk_agent
from app.api.deps import CurrentUser, DbSession
from app.api.routes.macro import _aware
from app.api.routes.stocks import Now, _stock, _ticker
from app.market_data.service import ticker_of
from app.models import Portfolio
from app.portfolio import service as ps

router = APIRouter(tags=["risk"])


@router.get("/risk-agent/{ticker}", response_model=AgentOutput)
def risk_analysis(
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
    return risk_agent.run_and_record(db, t, as_of or now, user.id, knowledge_at)


class PortfolioIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(default="model", pattern="^(model|paper)$")
    cash: Decimal = Field(ge=0, max_digits=16, decimal_places=2)


class PositionIn(BaseModel):
    ticker: str
    quantity: int = Field(ge=0)
    avg_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=4)


class CashIn(BaseModel):
    cash: Decimal = Field(ge=0, max_digits=16, decimal_places=2)


def _pf(db: DbSession, pid: int) -> Portfolio:
    pf = db.get(Portfolio, pid)
    if pf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"portfolio {pid} not found")
    return pf


def _summary(db: DbSession, pf: Portfolio) -> dict[str, Any]:
    return {
        "id": pf.id,
        "name": pf.name,
        "kind": pf.kind,
        "currency": pf.base_currency,
        "cash": str(pf.cash),
        "starting_cash": str(pf.starting_cash),
        "positions": [
            {"ticker": str(ticker_of(s)), "quantity": p.quantity, "avg_cost": str(p.avg_cost)}
            for p, s in ps.positions(db, pf)
        ],
    }


@router.get("/portfolios")
def list_portfolios(db: DbSession, _u: CurrentUser) -> list[dict[str, Any]]:
    return [_summary(db, p) for p in db.scalars(select(Portfolio).order_by(Portfolio.id)).all()]


@router.post("/portfolios", status_code=status.HTTP_201_CREATED)
def create_portfolio(body: PortfolioIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    try:
        pf = ps.create(db, name=body.name, kind=body.kind, cash=body.cash, user=user.id)
    except ps.PortfolioError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _summary(db, pf)


@router.get("/portfolios/{pid}")
def get_portfolio(pid: int, db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    return _summary(db, _pf(db, pid))


@router.put("/portfolios/{pid}/positions")
def put_position(pid: int, body: PositionIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    pf = _pf(db, pid)
    stock = _stock(db, body.ticker)
    try:
        ps.set_position(db, pf, stock, body.quantity, body.avg_cost, user.id)
    except ps.PortfolioError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _summary(db, pf)


@router.put("/portfolios/{pid}/cash")
def put_cash(pid: int, body: CashIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    pf = _pf(db, pid)
    try:
        ps.set_cash(db, pf, body.cash, user.id)
    except ps.PortfolioError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _summary(db, pf)


@router.get("/portfolios/{pid}/analysis")
def portfolio_analysis(
    pid: int,
    db: DbSession,
    _u: CurrentUser,
    now: Now,
    as_of: Annotated[datetime | None, Query()] = None,
    knowledge_at: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    _aware("as_of", as_of)
    _aware("knowledge_at", knowledge_at)
    return ps.analyze(db, _pf(db, pid), as_of or now, knowledge_at)


class FitOut(BaseModel):
    analysis: AgentOutput
    details: dict[str, Any]


@router.get("/portfolio-agent/{pid}/{ticker}", response_model=FitOut)
def portfolio_fit(
    pid: int,
    ticker: str,
    db: DbSession,
    user: CurrentUser,
    now: Now,
    weight: Annotated[float, Query(gt=0, le=1)] = 0.05,
    as_of: Annotated[datetime | None, Query()] = None,
    knowledge_at: Annotated[datetime | None, Query()] = None,
) -> FitOut:
    _aware("as_of", as_of)
    _aware("knowledge_at", knowledge_at)
    pf = _pf(db, pid)
    t = _ticker(ticker)
    _stock(db, ticker)
    out, details = portfolio_agent.run_and_record(
        db, pf, t, weight, as_of or now, user.id, knowledge_at
    )
    return FitOut(analysis=out, details=details)
