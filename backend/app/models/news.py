"""News items, documents and document chunks (Phase 5; spec §10, §60, §62).

Embeddings use pgvector. News rows are append-only; enrichment (sentiment,
event type, duplicate link) is computed once at ingestion with the model
name recorded, so a later model change never silently rewrites history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

EMBED_DIM = 384  # must match news.embedding_dim (validated at startup)


class NewsItem(Base):
    __tablename__ = "news"
    __table_args__ = (
        UniqueConstraint("stock_id", "title_key", name="uq_news_stock_title"),
        CheckConstraint(
            "sentiment_label IS NULL OR sentiment_label IN ('positive','negative','neutral')",
            name="ck_news_sentiment",
        ),
        Index("ix_news_stock_published", "stock_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    title: Mapped[str] = mapped_column(Text)
    title_key: Mapped[str] = mapped_column(String(32))
    publisher: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(60))
    licensed: Mapped[bool] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    historical_use: Mapped[bool] = mapped_column(Boolean)
    event_type: Mapped[str] = mapped_column(String(30))
    importance: Mapped[float] = mapped_column(Float)
    mentions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sentiment_label: Mapped[str | None] = mapped_column(String(10))
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    sentiment_probs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sentiment_model: Mapped[str | None] = mapped_column(String(120))
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM), nullable=True)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("news.id"))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("data_ingestion_runs.id"))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_documents_sha256"),
        CheckConstraint(
            "doc_type IN ('annual_report','quarterly_report','transcript','filing',"
            "'presentation','announcement','other')",
            name="ck_document_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(String(120))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_document", "document_id", "chunk_index"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM))
