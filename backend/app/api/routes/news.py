"""News, news agent and document retrieval API (spec §63: GET /news/{ticker})."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentOutput
from app.agents.news import agent as news_agent
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.routes.stocks import Now, _run_out, _stock, _ticker
from app.core.config_file import get_config
from app.models import NewsItem
from app.news import service as ns
from app.news.nlp import ModelUnavailableError, model_status
from app.news.provider import GoogleNewsProvider
from app.schemas.market import IngestionRunOut

router = APIRouter(tags=["news"])
MAX_DOC_BYTES = 25 * 1024 * 1024


def get_news_provider() -> GoogleNewsProvider:
    return ns.build_news_provider()


NProvider = Annotated[GoogleNewsProvider, Depends(get_news_provider)]


class NewsOut(BaseModel):
    id: int
    title: str
    publisher: str | None
    url: str
    published_at: datetime | None
    retrieved_at: datetime
    event_type: str
    importance: float
    sentiment_label: str | None
    sentiment_score: float | None
    sentiment_model: str | None
    duplicate_of: int | None
    historical_use: bool
    mentions: list[str]


def _aware(name: str, v: datetime | None) -> None:
    if v is not None and v.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must include a timezone")


@router.get("/news/{ticker}", response_model=list[NewsOut])
def list_news(
    ticker: str, db: DbSession, _u: CurrentUser, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[NewsOut]:
    stock = _stock(db, ticker)
    rows = db.scalars(
        select(NewsItem)
        .where(NewsItem.stock_id == stock.id)
        .order_by(NewsItem.published_at.desc().nulls_last())
        .limit(limit)
    )
    return [NewsOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/news/{ticker}/ingest", response_model=IngestionRunOut)
def ingest_news(
    ticker: str, db: DbSession, user: CurrentUser, provider: NProvider
) -> IngestionRunOut:
    return _run_out(ns.ingest_news(db, _stock(db, ticker), provider, user.id))


@router.get("/news-agent/{ticker}", response_model=AgentOutput)
def news_analysis(
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
    return news_agent.run_and_record(db, t, as_of or now, user.id, knowledge_at)


class DocumentOut(BaseModel):
    id: int
    title: str
    doc_type: str
    source: str
    source_url: str | None
    published_at: datetime
    pages: int
    chunk_count: int
    embedding_model: str


@router.post("/documents/{ticker}", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    ticker: str,
    db: DbSession,
    user: AdminUser,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=3, max_length=300)],
    doc_type: Annotated[
        Literal[
            "annual_report",
            "quarterly_report",
            "transcript",
            "filing",
            "presentation",
            "announcement",
            "other",
        ],
        Form(),
    ],
    source: Annotated[str, Form(min_length=2, max_length=200)],
    published_at: Annotated[datetime, Form()],
    source_url: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    _aware("published_at", published_at)
    stock = _stock(db, ticker)
    raw = await file.read(MAX_DOC_BYTES + 1)
    if len(raw) > MAX_DOC_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "document larger than 25 MB")
    try:
        doc = ns.ingest_document(
            db,
            stock,
            raw,
            file.filename or "upload.txt",
            title=title,
            doc_type=doc_type,
            source=source,
            source_url=source_url,
            published_at=published_at,
            actor_id=user.id,
        )
    except ns.DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return DocumentOut.model_validate(doc, from_attributes=True)


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    ticker: str | None = None
    as_of: datetime | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)


class HitOut(BaseModel):
    document_id: int
    title: str
    doc_type: str
    source: str
    source_url: str | None
    published_at: datetime
    page: int | None
    chunk_index: int
    text: str
    similarity: float


@router.post("/search/documents", response_model=list[HitOut])
def search(body: SearchRequest, db: DbSession, _u: CurrentUser) -> list[HitOut]:
    _aware("as_of", body.as_of)
    stock = _stock(db, body.ticker) if body.ticker else None
    try:
        hits = ns.search_documents(
            db,
            body.query,
            stock=stock,
            as_of=body.as_of,
            top_k=body.top_k or get_config().news.retrieval_top_k,
        )
    except ModelUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return [HitOut(**h.__dict__) for h in hits]


@router.get("/nlp/status")
def nlp_status(_u: CurrentUser) -> dict[str, str]:
    return model_status()
