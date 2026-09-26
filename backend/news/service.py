"""NewsDataService + DocumentService (spec §60, §78)."""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.market_data.providers.base import ProviderError, ProviderUnavailableError
from app.market_data.service import ticker_of
from app.models import DataIngestionRun, Document, DocumentChunk, NewsItem, Stock
from app.news.events import build_aliases, classify, mentioned
from app.news.nlp import (
    Embedder,
    ModelUnavailableError,
    SentimentModel,
    get_embedder,
    get_sentiment_model,
)
from app.news.provider import GoogleNewsProvider, RawNews, query_for
from app.services.audit import record_audit


def build_news_provider() -> GoogleNewsProvider:
    cfg = get_config().news
    return GoogleNewsProvider(cfg.provider_enabled, cfg.max_items_per_fetch)


def _optional_models() -> tuple[SentimentModel | None, Embedder | None, list[str]]:
    warnings: list[str] = []
    try:
        sentiment: SentimentModel | None = get_sentiment_model()
    except ModelUnavailableError as exc:
        sentiment = None
        warnings.append(f"sentiment unavailable: {exc}")
    try:
        embedder: Embedder | None = get_embedder()
    except ModelUnavailableError as exc:
        embedder = None
        warnings.append(f"embeddings unavailable: {exc}")
    return sentiment, embedder, warnings


def ingest_news(
    db: Session, stock: Stock, provider: GoogleNewsProvider, actor_id: uuid.UUID | None
) -> DataIngestionRun:
    cfg = get_config().news
    today = datetime.now(UTC).date()
    run = DataIngestionRun(
        stock_id=stock.id,
        provider=provider.name,
        licensed=provider.licensed,
        basis=None,
        requested_start=today,
        requested_end=today,
        status="running",
        rows_received=0,
        rows_inserted=0,
        rows_unchanged=0,
        rows_revised=0,
        rows_rejected=0,
        usable=False,
        validation_report={"kind": "news"},
        triggered_by=actor_id,
    )
    db.add(run)
    db.flush()
    try:
        items, retrieved_at = provider.fetch(query_for(stock.symbol, stock.name))
    except (ProviderError, ProviderUnavailableError) as exc:
        run.status, run.error, run.finished_at = "failed", str(exc)[:2000], datetime.now(UTC)
        record_audit(
            db,
            action="news.ingest_failed",
            actor_user_id=actor_id,
            entity_type="stock",
            entity_id=str(ticker_of(stock)),
            details={"run_id": run.id, "error": run.error},
        )
        db.commit()
        return run

    run.retrieved_at, run.rows_received = retrieved_at, len(items)
    sentiment, embedder, warnings = _optional_models()
    universe = db.scalars(select(Stock)).all()
    aliases = build_aliases([(str(ticker_of(s)), s.symbol, s.name) for s in universe])
    me = str(ticker_of(stock))

    existing = {
        k for (k,) in db.execute(select(NewsItem.title_key).where(NewsItem.stock_id == stock.id))
    }
    fresh: list[RawNews] = []
    seen: set[str] = set()
    for it in items:
        if it.title_key in existing or it.title_key in seen:
            run.rows_unchanged += 1
            continue
        seen.add(it.title_key)
        fresh.append(it)

    titles = [it.title for it in fresh]
    sents = sentiment.predict(titles) if sentiment and titles else [None] * len(fresh)
    vecs = embedder.encode(titles) if embedder and titles else None

    # Near-duplicate detection against recent stored items for this stock.
    recent = db.scalars(
        select(NewsItem).where(
            NewsItem.stock_id == stock.id,
            NewsItem.embedding.is_not(None),
            NewsItem.retrieved_at >= datetime.now(UTC) - timedelta(days=30),
        )
    ).all()
    pool: list[tuple[NewsItem, Any, datetime | None]] = [
        (n, np.asarray(n.embedding, dtype=np.float32), n.published_at) for n in recent
    ]
    window = timedelta(hours=cfg.duplicate_window_hours)

    rows: list[NewsItem] = []
    for i, it in enumerate(fresh):
        event = classify(it.title)
        s = sents[i]
        row = NewsItem(
            stock_id=stock.id,
            title=it.title,
            title_key=it.title_key,
            publisher=it.publisher,
            url=it.url,
            provider=provider.name,
            licensed=provider.licensed,
            published_at=it.published_at,
            retrieved_at=retrieved_at,
            historical_use=it.published_at is not None,
            event_type=event,
            importance=cfg.importance[event],
            mentions=sorted(set(mentioned(it.title, aliases)) | {me}),
            sentiment_label=s.label if s else None,
            sentiment_score=s.score if s else None,
            sentiment_probs=(
                {"positive": s.positive, "negative": s.negative, "neutral": s.neutral}
                if s
                else None
            ),
            sentiment_model=sentiment.name if s and sentiment else None,
            embedding=vecs[i].tolist() if vecs is not None else None,
            ingestion_run_id=run.id,
        )
        if vecs is not None:
            v = vecs[i]
            for other, ov, opub in pool:  # earlier stored or earlier in this batch
                near = (
                    it.published_at is None or opub is None or abs(it.published_at - opub) <= window
                )
                if near and float(np.dot(v, ov)) >= cfg.duplicate_similarity:
                    row.duplicate_of = other.id
                    break
        db.add(row)
        db.flush()  # assigns row.id so later items can point at it
        if vecs is not None:
            pool.append((row, vecs[i], it.published_at))
        rows.append(row)

    run.rows_inserted = len(rows)
    run.usable = bool(sentiment)
    run.validation_report = {
        "kind": "news",
        "warnings": warnings,
        "undated": sum(1 for r in rows if r.published_at is None),
        "duplicates": sum(1 for r in rows if r.duplicate_of is not None),
    }
    run.status = "succeeded" if not warnings else "succeeded_with_warnings"
    run.finished_at = datetime.now(UTC)
    record_audit(
        db,
        action="news.ingest",
        actor_user_id=actor_id,
        entity_type="stock",
        entity_id=me,
        details={"run_id": run.id, "inserted": len(rows), "warnings": warnings},
    )
    db.commit()
    return run


def news_as_of(
    db: Session,
    stock: Stock,
    as_of: datetime,
    knowledge_at: datetime | None,
    lookback_days: int,
) -> list[NewsItem]:
    """Dated, non-duplicate items published in (as_of - lookback, as_of] and
    retrieved by knowledge_at."""
    q = select(NewsItem).where(
        NewsItem.stock_id == stock.id,
        NewsItem.historical_use.is_(True),
        NewsItem.duplicate_of.is_(None),
        NewsItem.published_at <= as_of,
        NewsItem.published_at > as_of - timedelta(days=lookback_days),
    )
    if knowledge_at is not None:
        q = q.where(NewsItem.retrieved_at <= knowledge_at)
    return list(db.scalars(q.order_by(NewsItem.published_at.desc())))


# ----------------------------------------------------------------- documents --


class DocumentError(ValueError):
    pass


def _extract(raw: bytes, filename: str) -> list[tuple[int | None, str]]:
    if filename.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(raw))
            return [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        except PdfReadError as exc:
            raise DocumentError(f"unreadable PDF: {exc}") from exc
    try:
        return [(None, raw.decode("utf-8-sig"))]
    except UnicodeDecodeError as exc:
        raise DocumentError("text documents must be UTF-8") from exc


def chunk_pages(
    pages: list[tuple[int | None, str]], size: int, overlap: int
) -> list[tuple[int | None, str]]:
    chunks: list[tuple[int | None, str]] = []
    for page, text in pages:
        text = " ".join(text.split())
        start = 0
        while start < len(text):
            piece = text[start : start + size]
            if piece.strip():
                chunks.append((page, piece))
            if start + size >= len(text):
                break
            start += size - overlap
    return chunks


def ingest_document(
    db: Session,
    stock: Stock,
    raw: bytes,
    filename: str,
    *,
    title: str,
    doc_type: str,
    source: str,
    source_url: str | None,
    published_at: datetime,
    actor_id: uuid.UUID | None,
) -> Document:
    cfg = get_config().news
    digest = hashlib.sha256(raw).hexdigest()
    dup = db.scalar(select(Document).where(Document.sha256 == digest))
    if dup is not None:
        raise DocumentError(f"document already stored (id {dup.id})")
    pages = _extract(raw, filename)
    chunks = chunk_pages(pages, cfg.chunk_chars, cfg.chunk_overlap)
    if not chunks:
        raise DocumentError("no extractable text (scanned PDF? OCR is not supported)")
    embedder = get_embedder()  # raises ModelUnavailableError -> caller returns 503
    vecs = embedder.encode([c[1] for c in chunks])
    doc = Document(
        stock_id=stock.id,
        title=title,
        doc_type=doc_type,
        source=source,
        source_url=source_url,
        published_at=published_at,
        sha256=digest,
        pages=len(pages),
        chunk_count=len(chunks),
        embedding_model=embedder.name,
        uploaded_by=actor_id,
    )
    db.add(doc)
    db.flush()
    for i, ((page, text), v) in enumerate(zip(chunks, vecs, strict=True)):
        db.add(
            DocumentChunk(
                document_id=doc.id, chunk_index=i, page=page, text=text, embedding=v.tolist()
            )
        )
    record_audit(
        db,
        action="document.ingest",
        actor_user_id=actor_id,
        entity_type="document",
        entity_id=str(doc.id),
        details={"title": title, "chunks": len(chunks)},
    )
    db.commit()
    return doc


@dataclass
class Hit:
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


def search_documents(
    db: Session,
    query: str,
    *,
    stock: Stock | None,
    as_of: datetime | None,
    top_k: int,
) -> list[Hit]:
    """Semantic retrieval; every hit carries its source (spec §60). Only
    documents published at or before as_of are searchable."""
    vec = get_embedder().encode([query])[0].tolist()
    dist = DocumentChunk.embedding.cosine_distance(vec)
    q = select(DocumentChunk, Document, dist.label("d")).join(
        Document, Document.id == DocumentChunk.document_id
    )
    if stock is not None:
        q = q.where(Document.stock_id == stock.id)
    if as_of is not None:
        q = q.where(Document.published_at <= as_of)
    rows = db.execute(q.order_by(dist).limit(top_k)).all()
    return [
        Hit(
            document_id=d.id,
            title=d.title,
            doc_type=d.doc_type,
            source=d.source,
            source_url=d.source_url,
            published_at=d.published_at,
            page=c.page,
            chunk_index=c.chunk_index,
            text=c.text,
            similarity=round(1 - float(dist_), 4),
        )
        for c, d, dist_ in rows
    ]
