"""Orchestrated analysis reports (spec §15, §81)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.macro import _aware
from app.api.routes.stocks import Now, _stock, _ticker
from app.models import AnalysisReport
from app.orchestrator import narrative as nv
from app.orchestrator import service as orch
from app.orchestrator.markdown import render

router = APIRouter(tags=["analysis"])


class AnalysisIn(BaseModel):
    as_of: datetime | None = None
    knowledge_at: datetime | None = None
    portfolio_id: int | None = None
    weight: float = Field(default=0.05, gt=0, le=1)


@router.post("/analysis/{ticker}", status_code=status.HTTP_201_CREATED)
def run_analysis(
    ticker: str, db: DbSession, user: CurrentUser, now: Now, body: AnalysisIn | None = None
) -> dict[str, Any]:
    b = body or AnalysisIn()
    _aware("as_of", b.as_of)
    _aware("knowledge_at", b.knowledge_at)
    t = _ticker(ticker)
    _stock(db, ticker)
    try:
        return orch.run_analysis(
            db, t, b.as_of or now, user.id, b.knowledge_at, b.portfolio_id, b.weight
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _latest(db: DbSession, ticker: str) -> AnalysisReport:
    stock = _stock(db, ticker)
    row = db.scalar(
        select(AnalysisReport)
        .where(AnalysisReport.stock_id == stock.id)
        .order_by(AnalysisReport.created_at.desc(), AnalysisReport.id.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no analysis report for {ticker}")
    return row


@router.get("/analysis/{ticker}/latest")
def latest(ticker: str, db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    row = _latest(db, ticker)
    return {**orch.stored(row), "hash_verified": orch.verify(row)}


@router.get("/analysis/{ticker}/history")
def history(ticker: str, db: DbSession, _u: CurrentUser) -> list[dict[str, Any]]:
    stock = _stock(db, ticker)
    rows = db.scalars(
        select(AnalysisReport)
        .where(AnalysisReport.stock_id == stock.id)
        .order_by(AnalysisReport.created_at.desc(), AnalysisReport.id.desc())
        .limit(50)
    ).all()
    return [
        {
            "report_id": r.id,
            "created_at": r.created_at.isoformat(),
            "as_of": r.as_of.isoformat(),
            "stance": r.stance,
            "composite_score": r.composite_score,
            "confidence": r.confidence,
        }
        for r in rows
    ]


def _report(db: DbSession, rid: int) -> AnalysisReport:
    row = db.get(AnalysisReport, rid)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"report {rid} not found")
    return row


@router.get("/reports/{rid}")
def get_report(rid: int, db: DbSession, _u: CurrentUser) -> dict[str, Any]:
    row = _report(db, rid)
    return {**orch.stored(row), "hash_verified": orch.verify(row)}


@router.get("/reports/{rid}/markdown", response_class=PlainTextResponse)
def report_markdown(rid: int, db: DbSession, _u: CurrentUser) -> PlainTextResponse:
    row = _report(db, rid)
    text = render(orch.stored(row))
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="aegis-report-{rid}.md"'},
    )


@router.get("/narrator/status")
def narrator_status(_u: CurrentUser) -> dict[str, Any]:
    return nv.narrator_status()
