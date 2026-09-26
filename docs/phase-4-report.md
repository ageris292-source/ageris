# Phase 4 Report: Fundamental Agent

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **`financials` table** (migration 0004; records can't be changed or deleted). Each figure is stored by period and line item, with its data version, source, licence flag, `retrieved_at`, `published_at`, `available_at` and `availability_estimated`. Revisions are stored as new versions, and the differences are kept in `data_conflicts`.
- **Providers:**
  - **Yahoo fundamentals-timeseries** (unlicensed). It gives 4 annual and 5 quarterly periods per company, with period-end dates only. Availability is **estimated from SEBI LODR deadlines**: 45 days after the quarter, 60 after the year, at the end of that day in IST.
  - **CSV import** for licensed data. Every row must include a timezone-aware `published_at`.
- **Point-in-time rule.** A figure with an estimated publication date is only used if Aegis had actually retrieved it by `as_of`. Analyses of past dates therefore never rely on a guessed date. Licensed rows with real publication times *are* usable for past dates.
- **Deterministic ratios:**
  - growth: revenue, EPS, net income
  - margins: gross, operating, net
  - FCF (from operating cash flow + capex if not reported), FCF conversion, operating cash flow / net income
  - ROE on average equity, ROCE = EBIT / (assets − current liabilities)
  - debt/equity, interest coverage
  - valuation: market cap, EV, P/E, P/B, EV/EBITDA, PEG, earnings yield and FCF yield

  Missing inputs give "not available", never 0. Growth isn't calculated from a zero or negative starting value.
- **Fundamental agent** (`GET /fundamental/{ticker}`). It produces signals in five categories: growth (including acceleration), profitability (margin trend, ROE, ROCE), balance sheet, cash quality and valuation (P/E band, P/E vs peer median, PEG). It flags risks (debt stress, weak interest coverage, margin deterioration, weak cash conversion) and gives invalidation conditions. It uses the same documented scoring and uncalibrated agreement heuristic as the technical agent.
  - **Peer comparison** uses peer groups set in config.
  - **Banks:** industrial leverage and cash-flow tests are skipped, with a warning that bank-specific metrics aren't available.
  - **PEG** is only shown when EPS growth is at least 5%.
- **API:**
  - `GET /financials/{ticker}` (point-in-time `as_of`)
  - `POST /financials/{ticker}/ingest`
  - `POST /financials/{ticker}/import-csv` (admin)
  - `GET /fundamental/{ticker}`
- **UI:** a Fundamental analysis panel on the stock page, with a 4-year table (revenue, growth, net income, EPS, margin, ROE, ROCE, D/E, coverage, FCF conversion) and the agent's signals.

## Tests
14 new tests.
- Hand-worked ratios, including ones that must come out "not available"
- Valuation arithmetic
- The SEBI deadline estimate
- Parsing the real recorded payload; empty or broken payloads
- CSV rules: timezone required, no publication before the period ends, only known line items
- Distress flags
- Bank and PEG handling
- Ingestion is idempotent and the stored figures can't be changed
- Financials endpoint
- The agent works today but refuses a past date when it would need estimated publication dates
- Licensed CSV figures become visible exactly at their publication time
- A provider outage fails safely
- Login and role checks

## Live run (real data, 2026-09-26)
| Stock | Score | Notes |
|---|---|---|
| TCS | 72, bullish tilt | ROE 48.7%, ROCE 54.9%, D/E 0.11, FCF 97% of net income, P/E 15.3 (peer median 13.1) |
| Reliance | 62 | Revenue +9.6%, EPS +16%, but ROE 9.2% |
| HDFC Bank | 48 | Revenue growth slowed from 14.6% to 4.7%; industrial ratios skipped for a bank |
| INFY | failed | Yahoo returned no data; recorded as a failed run, not guessed |

## Limitations
- Only about 4 years of annual history from Yahoo, and the data is unlicensed.
- Bank-specific metrics (NIM, GNPA, CASA, capital adequacy) aren't available.
- Sector classification is manual, through peer groups in config.
