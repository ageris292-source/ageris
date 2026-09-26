# Phase 9 Report: Trade Risk Engine

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **The engine** (`app/trade/gates.py`):
  - A **pure function** of (proposal, context, config): no database, clock or model inside it.
  - **24 gates run in a fixed order.** A proposal is **APPROVED only if every applicable gate is PASS**; FAIL and UNKNOWN both reject.
  - A gate that crashes counts as FAIL.
  - Every decision carries the full context snapshot, the config fingerprint and a SHA-256 hash, and is deterministic.

  | # | Gate | # | Gate |
  |---|---|---|---|
  | 1 | kill_switch | 13 | out_of_sample |
  | 2 | execution_mode | 14 | probability_of_profit (≥ 0.65) |
  | 3 | portfolio_match | 15 | expected_net_return (≥ 5% after costs) |
  | 4 | instrument (NSE/BSE, INR, long-only) | 16 | edge_vs_benchmark (≥ 3%) |
  | 5 | data_licensed | 17 | trade_plan (stop < entry < target, horizon) |
  | 6 | data_freshness | 18 | reward_risk (≥ 2, net of costs) |
  | 7 | data_quality (≥ 0.90) | 19 | liquidity (average daily traded value ≥ ₹5 cr) |
  | 8 | entry_deviation (≤ 0.5%) | 20 | participation (≤ 1% of that value) |
  | 9 | research_report (hash-verified, ≤ 24h old) | 21 | spread (≤ 25 bps, must be known) |
  | 10 | research_stance (POSITIVE_TILT) | 22 | position_sizing |
  | 11 | agent_conflicts (0) | 23 | portfolio_limits (after the trade) |
  | 12 | model_calibration (error ≤ 0.05) | 24 | loss_limits (day 2%, week 5%, drawdown 15%) |

- **Exits:** sells of an existing long skip the entry-only gates (marked NOT_APPLICABLE), so profitability rules never block a risk-reducing trade. The kill switch, mode, data, execution and liquidity-participation gates still apply, and selling more than you hold fails.
- **Probability comes only from a registered model**, never from the proposal. No model is registered until Phase 10, so gates 12–16 are UNKNOWN and every entry is rejected. That is fail-closed by design.
- **Cost model** from the configured NSE delivery schedule:
  - Covers brokerage, exchange and regulatory fees, GST on those fees, securities transaction tax on both sides, stamp duty on the buy, slippage, half the spread (the quoted spread if known), market impact that rises with order size relative to average daily traded value, and financing.
  - A real TCS order came to **0.43% round trip**.
- **Position sizing:**
  - `fixed_fractional`: 0.5% of equity at risk against the stop.
  - `volatility_target`, and `fractional_kelly` capped at 0.25× Kelly.
  - Plus a cap of 10% of equity per order.
- **Portfolio limits** are checked after the trade using the Phase 7 analytics.
- **Loss limits** are measured against IST day/week baselines from immutable `portfolio_snapshots`.
- **Storage** (migration 0009): immutable `trade_proposals`, `trade_decisions` and `portfolio_snapshots`. Every evaluation is audited.
- **API:**
  - `POST /trade/proposals` rejects unknown fields and future `as_of`.
  - `GET /trade/proposals`, and `GET /trade/decisions/{id}` which re-verifies the hash.
  - `GET /trade/gates` lists the catalogue with a self-test; `POST /trade/costs` previews costs.
- **Execution readiness:** `risk_engine` is now **PASS** when the engine self-test passes. Paper orders still need paper mode and a released kill switch; live orders remain blocked.
- **UI:** a new **Trade risk** page with a proposal form, the table of 24 gate results, recent proposals and the gate catalogue.
- **CLI:**
  - `python -m app.cli ingest TCS.NS RELIANCE.NS …` adds stocks and fetches prices, financials and news.
  - `python -m app.cli ingest-macro` fetches the macro series.
- **Safety fix in the test suite:** tests now **refuse to run against any database whose name doesn't end in `_test`**. Before, a shell `DATABASE_URL` could point the table-wiping fixtures at a real database. It happened to the sandbox development database here, which was rebuilt with the new CLI.

## Tests
55 new tests; 297 in total, plus ruff and mypy all clean.
- The baseline proposal is approved with all 24 gates PASS.
- **41 single-change cases** each reject at the expected first gate, and every gate is covered.
- Exit rules; a hand-worked cost check; costs positive and rising with order size (property test).
- **Properties from spec §72**, over hundreds of random proposals and contexts:
  - Approved if and only if every applicable gate passes.
  - Every approval satisfies the kill-switch, licensing, mode, risk-budget, probability and net-return invariants.
  - Decisions are deterministic.
  - Tightening any threshold never approves more.
  - An active kill switch rejects everything.
- **End-to-end approval from real database state:** licensed fresh prices, a recent POSITIVE_TILT report, a registered calibrated estimate, paper mode, the kill switch released by an admin, and a paper portfolio. Oversizing the same trade is rejected on sizing and portfolio limits.
- Research mode rejects and records the proposal.
- A stored decision can't be UPDATEd; the hash verifies on read.
- The gate catalogue self-test passes; risk_engine reads PASS; every endpoint requires authentication.

## Live run (real data, 2026-09-26)
Proposal: buy 20 TCS at ₹2,082 in the paper portfolio. Result: **REJECTED**.
- First failure is the kill switch.
- Also failed: research mode, unlicensed Yahoo prices, stance NO_CLEAR_TILT, 2 agent conflicts, and no calibrated model (5 gates UNKNOWN).
- Passed: instrument, freshness, quality, entry deviation, report age, trade plan, reward/risk 2.8, liquidity, participation 0.001%, spread, sizing (20 ≤ 48), portfolio limits and loss limits.

## Limitations
- The cost schedule is an example and must be checked against current exchange, SEBI and broker charges. Fixed per-order depository charges are not modelled.
- Spread must come from a live quote, which arrives with the Phase 11 paper broker; until then the spread gate is UNKNOWN unless a quote is supplied.
- Yahoo data is unlicensed, so paper trading needs licensed prices imported via CSV.
