# Phase 5 Report: News Agent, FinBERT, Document Search (RAG)

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **News provider.** Google News RSS search for India (unofficial and unlicensed). Only the headline, publisher, link and publication time are stored, and articles aren't scraped. A headline without a publication time is shown but never used for past dates (`historical_use = false`).
- **Enrichment** is done once at ingestion, and the model's name is recorded:
  - **FinBERT sentiment** (`ProsusAI/finbert`) and **MiniLM embeddings** (384-dimensional, stored with pgvector).
  - If either model can't load, sentiment is stored as **unknown**, never as neutral, and document search returns 503.
  - **Event classification** into 12 types (beat, miss, results, regulatory, lawsuit, acquisition, management change, dividend/buyback, rating change, product launch, sector, other). The keyword rules are transparent.
  - **Entity linking** to stocks in the universe.
  - **Duplicate detection:** exact duplicates by normalised headline hash; near-duplicates when similarity is at least 0.90 within 72 hours.
  - **Contradiction detection:** the same event type with opposite sentiment, or an earnings beat and miss reported for the same period.
- **News agent** (`GET /news-agent/{ticker}`):
  - Score = 50 + 50 × the weighted mean of sentiment. Weights combine event importance with a 5-day recency half-life.
  - Only dated, de-duplicated headlines inside the as-of window are used, and only those retrieved by `knowledge_at`.
  - At least 3 scored headlines are required, otherwise `insufficient_data`.
  - Every signal carries its source URL.
  - Contradictions halve the confidence heuristic and are listed as risks.
- **Document search (RAG).** Admins upload PDF or text documents (annual reports, transcripts, filings), each with a **required publication time**. The text is split into chunks (1200 characters, 200 overlapping), embedded, and indexed with pgvector HNSW. `POST /search/documents` returns the best-matching passages, each with document title, type, source, URL, page and similarity, and only from documents published by `as_of`.
- **Storage** (migration 0005): tables `news`, `documents` and `document_chunks`. News items can't be deleted.
- **Scheduled jobs:** news refresh every 2 hours on weekdays (08:30–18:30 IST); fundamentals refresh weekly.
- **UI:** a News panel on the stock page with tone badges (icon plus word), links and event types, alongside the agent's output.
- **Docker:** the backend image installs CPU-only torch and the `[ml]` extra.

## Tests
21 new tests; 202 in total.
- Parsing the real feed (100 items, publisher suffix removed, times in UTC)
- 10 event classification cases; entity linking; chunk overlap
- Ingestion: duplicates removed and linked, enrichment applied, idempotent
- **Models unavailable → sentiment unknown and agent returns `insufficient_data`**
- Provider outage
- Agent: every signal sourced; point-in-time behaviour for both `as_of` and `knowledge_at`
- Contradiction detection
- Document search returns source metadata; documents published after `as_of` are hidden; duplicate uploads are rejected (422); missing embeddings give 503; uploads are admin-only
- **The real FinBERT model** labels a record-profit headline positive and a plunge headline negative. This test is skipped when the model isn't installed.

## Live run (real headlines, real FinBERT)
| Stock | Headlines | News score | Notes |
|---|---|---|---|
| TCS | 58 | 58.8 | Boardroom-battle article flagged as a lawsuit risk |
| Reliance | 60 | 46.6 | Broadly neutral |
| HDFC Bank | 59 | 43.9 | **US securities class-action lawsuits** and CEO succession flagged; 1 contradiction cluster |

## Limitations
- Headlines only. Google News links go through Google's redirect, and the source is unlicensed.
- Matching short tickers can pick up the wrong company: for example, "Jaguar TCS Racing" was linked to TCS.
- Keyword event rules are conservative, so many headlines land in "other".
- Scanned PDFs aren't supported (no OCR).
- The ML models add about 900 MB to the image.
