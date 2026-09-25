# Phase 3 Report: Technical Analysis Agent

Date: 2026-09-25 · Status: complete, all checks green · Scope: NSE/BSE

## 1. What was implemented

- **Indicator library** (`app/analysis/indicators.py`), all deterministic Python and never computed by the LLM:
  - SMA, EMA, Wilder RSI, MACD, Bollinger (with %B and bandwidth), Wilder ATR, Wilder ADX with ±DI, OBV
  - annualised realised volatility, rate of change, rolling max/min and percentile rank
  - swing points, support/resistance clustering, cross detection
  - Values that aren't defined yet are NaN, never 0 and never back-filled. Each value at time *t* uses only data up to *t*.
- **Agent contract** (`app/agents/base.py`, spec §19): `AgentInput` and `AgentOutput`, with status `ok`, `insufficient_data`, `data_unusable` or `failed`. The contract enforces fail-closed behaviour: a non-OK output **can't** carry a score, signals or confidence, and it must say why.
- **Technical agent.** It reads **point-in-time** split-adjusted prices, then applies gates in order:
  1. The data must pass validation, otherwise `data_unusable`.
  2. It needs at least 260 sessions of history, otherwise `insufficient_data`.
  3. Stale data, unlicensed data and data below the quality minimum each produce a warning.

  It then detects signals in five categories:
  - trend: price vs the 200-day average, 50/200 alignment, golden/death cross, ADX
  - momentum: MACD position or cross, RSI level, 63-day change, RSI divergence
  - mean reversion: RSI overbought/oversold, price outside the Bollinger bands
  - breakout: close beyond the prior 55-day high/low with a volume check, Bollinger squeeze
  - volume: expansion or contraction, OBV divergence

  Each output also lists risks (high volatility, low liquidity, wide daily range) and **invalidation conditions** in rupees.
- **Score:** 0–100, where 50 means no tilt. It's a fixed weighted composite with its formula in the code, and the output says explicitly that it is **not a probability of profit**.
- **"Confidence"** = signal agreement × breadth across categories × data quality, halved when data is stale. It's labelled `heuristic_uncalibrated`, shown in the UI as "Signal agreement — heuristic, not calibrated", and never presented as a probability (§27/§43). Real calibration needs the backtester (Phase 10).
- **Two separate time cut-offs:**
  - `as_of`: what the market had available at that time (§33).
  - `knowledge_at`: which data versions Aegis had retrieved by then. Each run records it, so **passing a run's `knowledge_at` back reproduces it exactly**, even after a provider revises its data (§37).
- **Storage** (migration `0003`):
  - `agent_runs`: agent version, as_of, knowledge_at, a content hash of the exact input prices (`data_snapshot_id`), the config fingerprint, duration and error.
  - `agent_outputs`: the full typed output; can't be changed or deleted.
  - `technical_indicators`: the feature store (§77) with feature_name, session, value, source, basis, calculation_version, availability_timestamp and snapshot; can't be changed or deleted.
- **API:**
  - `GET /technical/{ticker}?as_of&knowledge_at` runs the agent and records the run.
  - `GET /technical/{ticker}/indicators?start&end` returns chart series. Indicators are computed with extra earlier history (warm-up), so the first plotted values are accurate.
- **UI:** the stock page chart now shows **SMA 50/200 overlays** in dashed lines with a legend (colours checked for colour-blind readers) and an **RSI chart** with overbought/oversold lines. A new **Technical analysis** panel shows the score, tilt, signal agreement, each signal with direction and strength, invalidation, risks and warnings, plus as-of, version and snapshot. Stocks without enough data show a clear "no score produced" box.
- **Config:** new strictly validated `technical:` section in `config/aegis.yaml` (periods, thresholds, category weights that must sum to 1). Config version is now 2026.09.3.

## 2. Files

New:
- `app/analysis/indicators.py`
- `app/agents/base.py`
- `app/agents/technical/{analysis,agent}.py`
- `app/models/agents.py`
- `app/api/routes/technical.py`
- `alembic/versions/0003_agents.py`
- `tests/test_indicators.py`, `tests/test_technical_agent.py`
- `tests/fixtures/yahoo_reliance_ns_2023_2024.json`
- `frontend/components/TechnicalPanel.tsx`

Changed:
- `config/aegis.yaml`
- `app/core/config_file.py`, `app/main.py`, `app/models/__init__.py`
- `app/market_data/service.py` (`knowledge_at`, actions filtered by as_of, point-in-time freshness)
- `app/api/routes/stocks.py`, `app/schemas/market.py`
- `tests/conftest.py`, `tests/test_market_api.py`, `pyproject.toml`
- `frontend/components/PriceChart.tsx`, `frontend/app/stocks/[ticker]/page.tsx`, `frontend/lib/api.ts`

## 3. Architecture decisions

- **Pure analysis, thin agent.** `analyze(bars) -> TechnicalResult` has no I/O and is fully unit-tested. The agent wrapper handles only data access, gating and persistence.
- **Split-adjusted basis for indicators.** It keeps series continuous across splits and bonuses. Ratios are unaffected by the adjustment (see limitations).
- **Market time and data vintage are separate controls.** Backtests (Phase 10) will use `as_of` to replay market history. Audits use `knowledge_at` to replay exactly what the system saw.
- **Agents live under `backend/app/agents/<name>/`** instead of a top-level `agents/` folder, which keeps one import root. Later agents follow the same layout.

## 4–6. Tests

**166 tests pass** against real PostgreSQL and Redis; 47 are new in Phase 3.

| File | Covers |
|---|---|
| `test_indicators.py` (9; two are Hypothesis property tests) | **Checked against an independent implementation** (the `ta` library) on synthetic data and real RELIANCE prices: SMA, EMA, MACD line/signal/histogram, Bollinger upper/lower/%B, ATR and ADX match to within 1e-9. RSI matches after the start-up period (our Wilder seeding is the classic one). Hand-worked values; bounds; **look-ahead property: value[t] on the full history equals value[t] on history cut at t, for 11 indicators**; swing points only use confirmed past data |
| `test_technical_agent.py` (38) | Fail-closed contract; uptrend > 60 > 40 > downtrend; a flat market gives exactly 50 with no thesis; deterministic; low-liquidity risk; **25 random series: invalidation levels are never already crossed**; real RELIANCE history gives OK with the run, output and feature rows recorded and immutable; stale data warns and halves confidence; not enough history gives no score; **point-in-time: agent output at T equals analysis of the history cut at T**, and one minute before close + lag the bar isn't visible; **replaying with a recorded `knowledge_at` reproduces the run exactly after a provider revision**; 25%-missing data gives `data_unusable`; the indicator endpoint's warm-up works and the 2024 bonus isn't shown as a crash; 404/422/401 |

- **Mutation check:** giving the SMA a centred window (a look-ahead bug) made 4 tests fail, including the look-ahead property test.
- **Static checks:** `ruff`, `ruff format --check`, `mypy --strict`, `tsc` and `next build` are all clean.

**Live run on real data (2026-09-25 close):**

| Ticker | Status | Score | Agreement | Summary |
|---|---|---|---|---|
| TCS.NS | ok | 30 | 0.65 | Bearish tilt: 18% below the 200-day average, MACD below signal, RSI 32 |
| RELIANCE.NS | ok | 24 | 0.65 | Bearish tilt, strong downtrend (ADX 30) |
| HDFCBANK.NS | ok | 42 | 0.09 | No clear tilt: bearish trend but bullish MACD cross and RSI divergence |
| INFY.BO | insufficient_data | — | — | Only 1 session of BSE history (see Phase 2) |

A run takes about 0.2 seconds.

**Bug found and fixed during the live run.** For HDFC Bank, one bearish invalidation condition ("close above the 50-day average ₹730.15") was already true, because the close was ₹735.60. Levels are now kept on the correct side of the close, bearish theses also get an ATR-based level, a runtime check refuses any condition that contradicts itself, and the new property test above covers it.

## 7. Known limitations

- **The score isn't a forecast.** It describes current technical conditions. Whether it predicts anything is untested until walk-forward backtesting (Phase 10). Don't read 30/100 as "sell".
- **Rupee levels for past `as_of` dates.** Yahoo's split-adjusted history already reflects splits that happened *after* `as_of`. So rupee levels (SMA, support, invalidation) for older dates are in post-split terms. Ratio-based signals (RSI, MACD direction, returns, volatility) are unaffected. Exact historical rupee levels need raw prices from a licensed source.
- **Muhurat sessions are excluded** (Phase 2), so indicators skip them.
- **Weights and thresholds are textbook starting values**, not optimised or validated.
- BSE via Yahoo still has almost no history, so use `.NS` tickers.

## 8. Security concerns

- No new external data sources. The technical endpoint requires login; every run is recorded with the user who asked for it.
- Agent outputs and feature rows can't be changed or deleted, so analyses can't be quietly rewritten.

## 9. Data-quality concerns

- The agent refuses to score data that fails validation or has fewer than 260 sessions.
- Unlicensed data is labelled research-only on every output.

## 10. Next phase

**Phase 4: Fundamental Agent** (revenue, margins, cash flow, ROE/ROCE, leverage, valuation ratios, historical and peer comparison).

This needs a **licensed or official source for Indian company financials with dates that record when each figure was published**, which Aegis doesn't have yet. Options:
- company and exchange filings (official, but must be parsed)
- a licensed vendor's API
- Yahoo fundamentals: unofficial, and it doesn't say when each figure was published, so historical use would risk look-ahead bias

The source should be chosen before Phase 4 starts.
