"""Phase 5: news ingestion, event classification, de-duplication, the news
agent, and document retrieval. Deterministic fake models are used for most
tests; one test exercises the real FinBERT model when it is installed."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.news import get_news_provider
from app.api.routes.stocks import get_now
from app.main import app
from app.models import NewsItem, User
from app.news import nlp
from app.news.events import build_aliases, classify, mentioned
from app.news.provider import GoogleNewsProvider, parse_rss
from app.news.service import chunk_pages
from tests.conftest import auth_header
from tests.market_helpers import NOW

XML = (Path(__file__).parent / "fixtures" / "google_news_tcs.xml").read_text()
POS = re.compile(r"\b(surge|soar|beats?|record|rises?|gains?|jumps?|rall(y|ies))\b", re.I)
NEG = re.compile(r"\b(falls?|plunge|miss(es)?|probe|battle|bleeding|down|slump|drops?)\b", re.I)


class FakeSentiment:
    name = "fake-finbert"

    def predict(self, texts: list[str]) -> list[nlp.Sentiment]:
        out = []
        for t in texts:
            if NEG.search(t):
                out.append(nlp.Sentiment("negative", 0.05, 0.9, 0.05))
            elif POS.search(t):
                out.append(nlp.Sentiment("positive", 0.9, 0.05, 0.05))
            else:
                out.append(nlp.Sentiment("neutral", 0.1, 0.1, 0.8))
        return out


class FakeEmbedder:
    name, dim = "fake-minilm", 384

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1  # noqa: S324
            n = np.linalg.norm(out[i])
            out[i] /= n if n else 1
        return out


def provider(xml: str = XML, status: int = 200) -> GoogleNewsProvider:
    return GoogleNewsProvider(
        True, 60, transport=httpx.MockTransport(lambda _: httpx.Response(status, text=xml))
    )


@pytest.fixture(autouse=True)
def _models() -> Iterator[None]:
    nlp.set_models(FakeSentiment(), FakeEmbedder())
    yield
    nlp.set_models(None, None)


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_news_provider] = lambda: provider()
    h = auth_header(client, admin.email)
    client.post("/stocks", headers=h, json={"ticker": "TCS.NS"})
    yield client, h
    app.dependency_overrides.clear()


# --------------------------------------------------------------------- units --


def test_parse_real_feed() -> None:
    items = parse_rss(XML, 100)
    assert len(items) == 100
    first = items[0]
    assert not first.title.endswith(" - Univest")  # publisher suffix stripped
    assert first.publisher == "Univest"
    assert first.published_at == datetime(2026, 9, 25, 10, 51, tzinfo=UTC)


@pytest.mark.parametrize(
    ("title", "event"),
    [
        ("TCS Q2 results beat street estimates, net profit rises 8%", "earnings_beat"),
        ("Infosys profit falls 5% as deal wins slow", "earnings_miss"),
        ("TCS Q2 Results: Date, Time, Dividend News", "results"),
        ("SEBI issues show-cause notice to company", "regulatory"),
        ("TCS Share Price Falls As Tata Sons Boardroom Battle Deepens", "lawsuit"),
        ("TCS stock falls after MHP acquisition", "acquisition"),
        ("Wipro CEO steps down with immediate effect", "management_change"),
        ("Citi downgrades HDFC Bank, cuts target price", "rating_change"),
        ("Why are IT stocks down today?", "sector"),
        ("A completely ordinary headline", "other"),
    ],
)
def test_event_classification(title: str, event: str) -> None:
    assert classify(title) == event


def test_entity_linking() -> None:
    aliases = build_aliases(
        [
            ("TCS.NS", "TCS", "Tata Consultancy Services Limited"),
            ("INFY.NS", "INFY", "Infosys Limited"),
        ]
    )
    assert mentioned("TCS, Infosys and Wipro fall", aliases) == ["TCS.NS", "INFY.NS"]
    assert mentioned("Tata Consultancy Services wins deal", aliases) == ["TCS.NS"]
    assert mentioned("TCSL is something else", aliases) == []


def test_chunking_overlap() -> None:
    chunks = chunk_pages([(1, "a" * 2500)], 1200, 200)
    assert [len(c[1]) for c in chunks] == [1200, 1200, 500]
    assert all(c[0] == 1 for c in chunks)


# --------------------------------------------------------------- ingestion --


def test_ingest_dedupes_and_enriches(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    run = client.post("/news/TCS.NS/ingest", headers=h).json()
    assert run["status"] == "succeeded" and run["licensed"] is False
    assert run["rows_inserted"] + run["rows_unchanged"] == run["rows_received"]
    assert run["rows_unchanged"] >= 1  # exact repeated headlines in the real feed
    rows = db.scalars(select(NewsItem)).all()
    assert all(r.sentiment_model == "fake-finbert" and r.embedding is not None for r in rows)
    assert all(r.historical_use == (r.published_at is not None) for r in rows)
    assert any(r.duplicate_of is not None for r in rows)  # near-duplicate headlines linked
    assert all("TCS.NS" in r.mentions for r in rows)
    again = client.post("/news/TCS.NS/ingest", headers=h).json()
    assert again["rows_inserted"] == 0
    listed = client.get("/news/TCS.NS", headers=h).json()
    assert listed and listed[0]["url"].startswith("https://news.google.com/")


def test_models_unavailable_means_unknown_not_neutral(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    nlp.mark_unavailable("offline")
    run = client.post("/news/TCS.NS/ingest", headers=h).json()
    assert run["status"] == "succeeded_with_warnings" and run["usable"] is False
    assert all(
        r.sentiment_label is None and r.sentiment_score is None
        for r in db.scalars(select(NewsItem))
    )
    out = client.get(
        "/news-agent/TCS.NS", headers=h, params={"as_of": "2026-09-25T13:00:00+00:00"}
    ).json()
    assert out["status"] == "insufficient_data" and out["score"] is None
    assert any("no sentiment" in w for w in out["warnings"])


def test_provider_outage(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    app.dependency_overrides[get_news_provider] = lambda: provider(status=503)
    run = client.post("/news/TCS.NS/ingest", headers=h).json()
    assert run["status"] == "failed" and "503" in run["error"]


# -------------------------------------------------------------------- agent --


def test_news_agent_is_sourced_and_point_in_time(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    client.post("/news/TCS.NS/ingest", headers=h)
    as_of = datetime.now(UTC)
    out = client.get("/news-agent/TCS.NS", headers=h, params={"as_of": as_of.isoformat()}).json()
    assert out["status"] == "ok", out["warnings"]
    assert 0 <= out["score"] <= 100 and out["confidence_basis"] == "heuristic_uncalibrated"
    assert out["signals"] and all(s["values"]["url"].startswith("https://") for s in out["signals"])
    assert all(e["ref"].startswith("news:") for e in out["evidence"])
    assert any("Unlicensed" in w for w in out["warnings"])
    # Before any of these headlines were published: nothing to score.
    early = client.get(
        "/news-agent/TCS.NS", headers=h, params={"as_of": "2025-01-01T00:00:00+00:00"}
    ).json()
    assert early["status"] == "insufficient_data"
    # Knowledge before retrieval: the stored headlines were unknown then.
    blind = client.get(
        "/news-agent/TCS.NS",
        headers=h,
        params={
            "as_of": as_of.isoformat(),
            "knowledge_at": (as_of - timedelta(days=1)).isoformat(),
        },
    ).json()
    assert blind["status"] == "insufficient_data"


def test_contradictions_detected() -> None:
    from app.agents.news.agent import contradictions

    t = datetime(2026, 9, 20, tzinfo=UTC)

    def item(title: str, label: str, event: str) -> NewsItem:
        return NewsItem(
            title=title,
            publisher="P",
            sentiment_label=label,
            event_type=event,
            published_at=t,
            retrieved_at=t,
        )

    found = contradictions(
        [
            item("Q2 beats estimates", "positive", "earnings_beat"),
            item("Q2 misses estimates", "negative", "earnings_miss"),
        ],
        7,
    )
    assert any("Opposite earnings" in c for c in found)
    assert (
        contradictions(
            [item("A", "positive", "acquisition"), item("B", "positive", "acquisition")], 7
        )
        == []
    )


# ---------------------------------------------------------------- documents --

DOC = (
    "Tata Consultancy Services annual report. Our order book reached a record "
    "USD 42 billion. "
    * 5
    + "Attrition fell to 12.4 percent this year. " * 5
    + "Management expects margins between 24 and 26 percent. " * 5
)


def upload(
    client: TestClient,
    h: dict[str, str],
    body: str = DOC,
    published: str = "2026-05-15T18:00:00+05:30",
) -> httpx.Response:
    return client.post(
        "/documents/TCS.NS",
        headers=h,
        files={"file": ("ar.txt", body, "text/plain")},
        data={
            "title": "Annual Report FY26",
            "doc_type": "annual_report",
            "source": "company website",
            "published_at": published,
        },
    )


def test_document_rag_with_sources(api: tuple[TestClient, dict[str, str]]) -> None:
    client, h = api
    r = upload(client, h)
    assert r.status_code == 201 and r.json()["chunk_count"] >= 1
    assert upload(client, h).status_code == 422  # same bytes: duplicate
    hits = client.post(
        "/search/documents", headers=h, json={"query": "what was attrition", "ticker": "TCS.NS"}
    ).json()
    assert hits and "attrition" in hits[0]["text"].lower()
    assert hits[0]["title"] == "Annual Report FY26" and hits[0]["source"] == "company website"
    before = client.post(
        "/search/documents",
        headers=h,
        json={"query": "attrition", "as_of": "2026-05-01T00:00:00+00:00"},
    ).json()
    assert before == []  # not yet published at as_of


def test_document_upload_needs_embeddings_and_admin(
    api: tuple[TestClient, dict[str, str]], analyst: User
) -> None:
    client, h = api
    a = auth_header(client, analyst.email)
    assert upload(client, a).status_code == 403
    nlp.mark_unavailable("offline")
    assert upload(client, h, body=DOC + "x").status_code == 503
    assert client.post("/search/documents", headers=h, json={"query": "margins"}).status_code == 503


# ------------------------------------------------------------ real FinBERT --


def test_real_finbert_if_installed() -> None:
    pytest.importorskip("transformers")
    try:
        model = nlp.FinBert("ProsusAI/finbert")
    except nlp.ModelUnavailableError:
        pytest.skip("FinBERT weights not available offline")
    pos, neg = model.predict(
        [
            "Company reports record profit, beats estimates",
            "Shares plunge after weak guidance and profit warning",
        ]
    )
    assert pos.label == "positive" and neg.label == "negative"
    assert pos.score > 0.5 > -0.5 > neg.score
