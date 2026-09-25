# Phase 2 Report: Market Data (Indian equities)

Date: 2026-09-25 · Status: complete, all checks green · Scope: NSE and BSE only

## 1. What was implemented

- **Tickers:** Indian tickers only, written as `TCS.NS` (NSE) or `RELIANCE.BO` (BSE). Anything else, such as `AAPL`, is rejected.
- **Exchange calendar:** trading days, holidays and the 15:30 IST close come from the `exchange-calendars` XBOM calendar (NSE and BSE share holidays).
  - A date outside the calendar's published range raises an error. Freshness then reports **UNKNOWN**, never PASS.
- **Provider interface** (`DailyBarProvider`), so each data source can be replaced independently:
  - **Yahoo adapter.** This source is **unlicensed**, so it is tagged research-only everywhere. The UI shows a banner saying so, and later gates must reject it for paper or live trading. The adapter:
    - converts timestamps to IST session dates
    - rounds float noise to the instrument's price precision
    - rejects responses whose currency, exchange or timezone doesn't match
    - **drops the in-progress session** until its close plus the availability lag has passed
    - drops null rows (never zero-filled)
    - treats timeouts, 429s and 5xx responses as *unavailable* (fail closed)
  - **CSV import** for data from licensed or official sources. The operator must declare the source and the price basis. A malformed row rejects the whole file and names the line.
- **Validation** (deterministic):
  - These row problems reject the row and mark the whole series **unusable**:
    - non-positive prices
    - high below low
    - open or close outside the high–low range
    - negative volume
    - conflicting duplicates
    - an incomplete session
  - These series problems are warnings:
    - missing sessions (above the configured share, the series becomes unusable)
    - large moves with no corporate action to explain them
    - zero volume
    - frozen prices
    - history that starts later than requested
  - Bars on dates the calendar doesn't list as trading days are **excluded with a warning**. Live data showed two real cases: Diwali *Muhurat* sessions, and Yahoo placeholder bars with zero volume on 2026 holidays.
  - **Quality score** = min(1 − 5·missing ratio − 0.01·warnings, coverage of the requested window). Any critical issue sets it to 0.
- **Price bases (adjustments)** are never mixed. There are three: RAW, SPLIT_ADJUSTED and TOTAL_RETURN, and every conversion is deterministic Decimal arithmetic.
  - Allowed: raw → split-adjusted, split-adjusted → total return, and raw → total return.
  - Conversions that can't be reversed, such as adjusted → raw, return 422.
- **Storage** (migration `0002`) adds these tables: `stocks`, `prices`, `corporate_actions`, `data_ingestion_runs`, `data_conflicts`.
  - Every stored bar carries `source`, `licensed`, `retrieved_at`, `effective_at` (session close), `available_at` (close + lag), `published_at` (NULL when the source doesn't state it; never invented) and `data_version`.
  - **Stored prices can't be changed or deleted** (database triggers). If a provider later reports a different value, it is stored as a new version and both values are kept in `data_conflicts`.
  - **Point-in-time reads:** `as_of` returns only versions that had been both retrieved and publicly available by that moment.
- **Freshness:** the latest stored session is compared with the latest completed session (close + lag). The allowed lag is set in config.
- **Caching:** provider responses are cached in Redis and keep their original retrieval time. If Redis is down, the system just skips the cache, because caching is not a safety control.
- **Celery job** `refresh_eod_prices` runs Mon–Fri at 17:15 IST. It refreshes each active stock incrementally, re-fetching the last 10 days to catch provider revisions. A failure on one stock doesn't stop the others.
- **API:**
  - `GET /stocks`
  - `POST /stocks` (admin)
  - `GET /stocks/{ticker}`
  - `GET /stocks/{ticker}/prices?basis&start&end&as_of`
  - `POST /stocks/{ticker}/ingest`
  - `POST /stocks/{ticker}/import-csv` (admin)
  - `GET /data/providers`
- **UI:**
  - **Stocks list:** freshness badges, per-stock refresh, admin add.
  - **Stock page:** price/total-return toggle, 1M–5Y ranges, price chart with hover tooltip and a separate volume chart below (no dual axis), a table view, and panels for data quality (with coverage), provenance, corporate actions and ingestion runs.

## 2. Files

New:
- `backend/app/market_data/{types,calendar,cache,validation,adjustments,freshness,service}.py`
- `backend/app/market_data/providers/{base,yahoo,csv_import}.py`
- `backend/app/models/market.py`
- `backend/app/schemas/market.py`
- `backend/app/api/routes/stocks.py`
- `backend/alembic/versions/0002_market_data.py`
- `backend/tests/{market_helpers,test_market_core,test_yahoo_provider,test_validation_adjustments,test_market_api}.py` plus `tests/fixtures/*.json`
- `frontend/app/stocks/page.tsx`, `frontend/app/stocks/[ticker]/page.tsx`
- `frontend/components/{Login,Nav,PriceChart,StatusBadge,useSession}.tsx`
- `frontend/lib/auth.ts`

Changed:
- `config/aegis.yaml` (new `market_data` section; version bumped to 2026.09.2)
- `app/core/config_file.py`, `app/api/deps.py`, `app/main.py`, `app/models/__init__.py`, `app/scheduler/celery_app.py`
- `tests/conftest.py`, `pyproject.toml`
- `frontend/app/page.tsx`, `frontend/lib/api.ts`, `frontend/package.json`

## 3. Architecture decisions

- **One way in.** `MarketDataService` is the only path to prices, so agents (Phase 3+) never call providers directly.
- **Adjustments are computed, not trusted.** Only the provider's declared basis is stored; other bases are derived on read. This avoids stored adjusted series going stale when a new corporate action arrives.
- **Direct HTTP for Yahoo** instead of the `yfinance` library. This gives full control over which field means what, and the parser is tested against real recorded payloads.
- **Unlicensed data is marked at the source.** The `licensed` flag is stored on every bar, so a later gate can refuse unlicensed data per row.

## 4–6. Tests

**119 tests pass** against real PostgreSQL and Redis; 66 of them are new in Phase 2.

| File | Covers |
|---|---|
| `test_market_core.py` (19) | ticker parsing (M&M, BAJAJ-AUTO, rejects non-Indian tickers); holidays; 15:30 IST = 10:00 UTC; latest completed session across close + lag, weekends and holidays; freshness PASS/FAIL, and UNKNOWN outside the calendar |
| `test_yahoo_provider.py` (15) | real recorded TCS 2018 payload (246 bars, 2:1 split on 2018-05-31, split-adjusted dividends); in-progress session dropped; nulls dropped, never zero-filled; not-found symbol; wrong currency, exchange or timezone; 429/5xx/network → unavailable; disabled provider; cache keeps original retrieval time; request window aligned to IST |
| `test_validation_adjustments.py` (21) | every row-corruption type blocks the series; duplicates; weekend bar excluded; missing-session formula and limit; unexplained move vs one explained by a split; zero volume and frozen prices; coverage and late history; **property tests:** no invalid bar is ever accepted, and total-return never raises past prices; split continuity; dividend factor; irreversible conversions refused; the direct and two-step raw → total-return paths match |
| `test_market_api.py` (11) | universe management and roles; ingestion provenance (Muhurat excluded); idempotent re-ingest; **a revised value becomes v2, the conflict is kept, and an as-of read still returns v1**; prices can't be updated or deleted; provider outage → failed run, audited, nothing stored; basis conversion and refusal; freshness PASS on current data; CSV import (roles, line-numbered errors, missing columns); auth required |

Also checked:
- `ruff check`, `ruff format --check` and `mypy --strict` are all clean.
- `next build` and `tsc` are clean.
- The ORM models match the migrations.
- Migration 0002 downgrades and upgrades cleanly.

**Live end-to-end run** against real Yahoo data on 2026-09-25:
- Loaded 5 years each of TCS.NS, RELIANCE.NS and HDFCBANK.NS: 1,232 sessions each stored, and 9 bars excluded per stock (4 Muhurat sessions and 5 zero-volume holiday placeholders).
- All three show fresh through 2026-09-25.
- The incremental refresh re-read 9 recent sessions and found 0 revisions.
- The scheduled job ran successfully for every stock.
- Reliance's October 2024 1:1 bonus appears as a continuous line in both price and total-return views.

## 7. Known limitations

- **BSE (`.BO`) history from Yahoo is almost empty.** For INFY.BO, Yahoo returned a single bar for a 5-year request. Aegis flags this as `history_starts_late` with 0.4% coverage and a quality score of 0.4%, instead of calling it clean. **Use NSE tickers** until a licensed BSE source is connected.
- **Muhurat sessions are excluded.** The exchange calendar doesn't list them, so their prices are left out rather than trusted.
- **The calendar ends on 2026-12-31** (the library's published holidays). After that date, freshness reports UNKNOWN until `exchange-calendars` is upgraded. **Upgrade the library before January.**
- **No licensed source is connected yet.** Only CSV import can bring licensed data in. An official NSE bhavcopy parser was **not** built, because the NSE site blocked automated access from the sandbox and a parser that couldn't be tested against real files would only be a guess.
- Only daily bars. There is no intraday data or live quotes, so `freshness.prices_seconds` isn't used yet.
- Ingestion from the API runs synchronously. It's fine for single stocks; large backfills should go through Celery.

## 8. Security concerns

- CSV uploads are admin-only, capped at 5 MB, must be UTF-8, and are parsed strictly.
- The Yahoo endpoint is unofficial. Its terms restrict use, so it is limited to personal research and tagged as unlicensed.
- **The repo is public and includes about 28 KB of recorded Yahoo responses as test fixtures.** If you're concerned about redistribution under Yahoo's terms, make the repo private or replace the fixtures with synthetic ones.

## 9. Data-quality concerns

- Yahoo produces placeholder bars on holidays (zero volume, flat price). These are excluded.
- Yahoo's close is split-adjusted, not raw. The stored basis is recorded as split-adjusted.
- The provider doesn't give a publication timestamp, so `published_at` is NULL. Point-in-time logic uses `available_at` = close + 60 min, a conservative assumption set in config.

## 10. Next phase

**Phase 3: Technical Analysis Agent.** Deterministic SMA, EMA, RSI, MACD, Bollinger bands, ATR, ADX and OBV; volatility, momentum, volume trends, and support/resistance; signal detection.

- Every indicator will be computed from `MarketDataService` point-in-time series.
- Output follows the §19 agent contract: score, signals, evidence, confidence, data quality, warnings and invalidation conditions.
- Inputs with low coverage or quality will reduce confidence, or block the analysis entirely.
