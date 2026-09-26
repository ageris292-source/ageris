# Phase 6 Report: Macro Agent, Market Regime, Valuation Agent

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Macro data** (`macro_data` table, migration 0006; immutable and versioned like prices):
  - **World Bank** annual indicators for India (GDP growth, CPI inflation, lending rate, and others). Licensed under CC BY. Availability is estimated as the year end plus a configured lag.
  - **Daily market series** from Yahoo (unlicensed, research-only): NIFTY 50, India VIX, USD/INR, Brent, NIFTY IT and NIFTY Bank.
  - **Manual admin entries** for series with no free feed (such as the RBI repo rate). Each entry requires a source and a timezone-aware publication time.
- **Market regime** (`GET /regime`):
  - Trend comes from NIFTY 50 against its 200-day SMA, with a ±2% band: bull, bear or sideways.
  - Volatility comes from India VIX (≥ 22 high, ≤ 13 low). If VIX is missing, it falls back to 20-day realised volatility.
  - Risk-on/off is derived from trend and volatility. If either is missing, the regime is **UNKNOWN**, never guessed.
- **Macro agent** (`GET /macro-agent/{ticker}`):
  - Sector-aware: the config maps sectors to their sensitivity to rates, INR, oil and global growth. IT benefits from a weak rupee; oil and gas is exposed to Brent; banks are sensitive to rates.
  - Adds regime and relative-strength signals: the stock against NIFTY 50 and against its sector index.
  - Score is 50 + 50 × the mean signal direction.
- **Valuation agent** (`GET /valuation/{ticker}`):
  - **DCF** with bear, base and bull scenarios. Each scenario projects revenue growth × FCF margin for 5 years, then applies Gordon terminal growth of 4%, 5% or 6%.
  - **WACC**: cost of equity from CAPM, using a 6.5% risk-free rate and a 7% equity risk premium, both configured assumptions. Beta is estimated weekly against NIFTY 50 and shrunk toward 1. Cost of debt comes from interest expense and is floored at the risk-free rate. Weights use market values.
  - **3×3 sensitivity grid** (WACC ±1pp × terminal growth ±1pp). Every assumption is returned in the response.
  - **Reliability guard:** a year of negative FCF, a mean FCF margin below 5%, or a non-positive scenario value means the DCF is **shown but not scored**.
  - **Relative valuation:** P/E, EV/EBITDA and P/B against the medians of peers in the same sector.
  - **Banks:** FCF DCF is skipped; only relative valuation is used.
  - Score is 50 + 50 × tanh(base-case margin of safety / 0.30). It is a model estimate, not a price target.
- **Scheduled job:** macro refresh daily at 17:30 IST on weekdays.
- **UI:**
  - The stock page gains a **Valuation** panel (scenario table and sensitivity grid) and a **Macro & regime** panel.
  - The dashboard gains a **Market regime** tile with its evidence.

## Tests
15 new tests; 217 in total, plus ruff and mypy all clean.
- DCF arithmetic checked against a hand calculation.
- WACC must exceed g, otherwise an error; the sensitivity grid is monotonic; CAPM/WACC maths.
- Weekly beta recovers a known beta; too few weeks gives None.
- Regime classification for bull, bear and unknown; the VIX-to-realised-volatility fallback.
- Macro point-in-time: future observations are invisible; revisions create a new version.
- Manual entries require a timezone and admin rights.
- The reliability guard blocks scoring for thin-margin companies; banks skip the DCF.

## Live run (real data, 2026-09-26)
| Stock | Macro | Valuation | Notes |
|---|---|---|---|
| TCS | 47.4 | 27.3 | Base DCF ₹1,777 vs price ₹2,082 (about −15%) |
| Reliance | 26.6 | insufficient data | Thin FCF margin, so the DCF was shown but not scored; no peers in the universe |
| HDFC Bank | 41.6 | insufficient data | Bank, so no DCF; no peers in the universe |

Regime: **BEAR_LOW_VOL** (NIFTY below its 200-day SMA, VIX low).

## Limitations
- The risk-free rate and ERP are static config values, not live G-sec yields.
- Peer multiples need several stocks from the same sector in the universe.
- World Bank data is annual and lags by about a year.
- Yahoo market series are unlicensed.
- The sector sensitivity map is a hand-written heuristic and hasn't been calibrated.
