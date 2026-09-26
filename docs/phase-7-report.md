# Phase 7 Report: Risk Agent, Portfolios, Portfolio Agent

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Risk statistics** (`app/analysis/risk.py`): pure functions, each checked against a hand calculation.
  - Daily returns and annualised volatility.
  - Maximum drawdown with its peak and trough dates, plus the current drawdown.
  - Sharpe, and Sortino using target downside deviation.
  - Historical one-day **VaR and CVaR** at 95% and 99%.
  - Daily beta, with returns aligned on common dates only, so a holiday in one market doesn't create a false multi-day return.
  - Average daily traded value; correlation matrix; Herfindahl index.
- **Risk agent** (`GET /risk-agent/{ticker}`):
  - Uses the trailing 252 sessions of total-return closes, with beta measured against NIFTY 50.
  - Score is **risk suitability**, where higher means lower measured risk. It combines volatility (level and 20-day expansion), drawdown, beta, Sharpe and liquidity.
  - A stock below the ₹5 crore/day traded-value minimum gets a maximal bearish signal and a risk line saying it is not tradable under current rules.
  - Point-in-time: the same `as_of` and `knowledge_at` rules as the other agents.
- **Portfolios** (migration 0007: tables `portfolios` and `positions`):
  - Portfolios are long-only.
  - **Model** portfolios hold holdings entered by users. **Paper** portfolios reject manual edits with a 409; only the Phase 11 paper broker will change them.
  - Every create, position change and cash change is audited.
- **Portfolio analysis** (`GET /portfolios/{id}/analysis`):
  - **Limit checks** mirror `risk_controls` and `liquidity`: position weight ≤ 10%, sector weight ≤ 30%, gross exposure ≤ 100%, cash ≥ 0, and minimum traded value.
  - **Advisory checks:** simulated drawdown ≤ 15%, highly correlated pairs (≥ 0.70), and concentration (effective number of positions ≥ 5).
  - An unpriced holding, or unclassified holdings large enough to breach the sector limit, make the result **UNKNOWN**, never PASS.
  - Also reports portfolio volatility, VaR, CVaR, beta and Sharpe for the current weights (described as a simulation, not a track record), plus the correlation matrix.
- **Portfolio agent** (`GET /portfolio-agent/{id}/{ticker}?weight=`):
  - Tests a what-if purchase funded from cash and compares the portfolio before and after.
  - Scores limit breaches **caused by the trade**. Breaches that already existed are reported as warnings and not blamed on the candidate.
  - Also scores diversification (correlation with the existing portfolio), marginal volatility and room left in the sector.
  - Any limit that is UNKNOWN after the trade gives `insufficient_data`.
- **Config:** new `risk_analysis` section, with category weights validated to sum to 1. New sectors OIL_GAS_UPSTREAM and REFINING_MARKETING, each with macro sensitivities.
- **UI:**
  - The stock page gains a **Risk** panel.
  - A new **Portfolios** page lets you create a portfolio, edit holdings, see limit and advisory checks, see the risk metrics, and run a what-if fit check.

## Tests
15 new tests; 232 in total, plus ruff and mypy all clean.
- Hand-worked checks for returns, volatility, drawdown, VaR/CVaR, Sharpe/Sortino, beta, date alignment and HHI.
- Property tests: drawdown stays in [0, 1) and doesn't change when prices are scaled; CVaR ≥ VaR.
- Risk agent: a calm stock scores above a volatile one, and the recovered betas are about 0.6 and 1.8.
- A liquidity failure produces a hard bearish signal.
- Point-in-time history lengths; insufficient history.
- Portfolio limits, sector weights and the audit trail.
- Paper portfolios can only be changed by the broker; an unpriced holding gives UNKNOWN and an insufficient fit.
- Fit behaviour:
  - A correlated twin is scored below an independent stock.
  - An oversized weight is flagged as the trade's breach.
  - A purchase beyond available cash fails the cash check.
  - A pre-existing breach is not blamed on the new trade.

## Live run (real data, 2026-09-26)
| Stock | Risk score | Volatility | Beta | Max drawdown | VaR95 (1 day) |
|---|---|---|---|---|---|
| TCS | 46.9 | 28.5% | 0.82 | 38.5% | 3.0% |
| Reliance | 61.4 | 20.6% | 0.92 | 23.1% | 2.1% |
| HDFC Bank | 55.8 | 21.4% | 1.25 | 30.8% | 2.2% |
| Infosys | 47.6 | 30.1% | 0.75 | 40.4% | 3.1% |

**Demo model portfolio** (TCS and Reliance plus ₹5 lakh cash):
- The position-weight limit **fails**, since both holdings are above 10%. Effective number of positions is 2.
- Volatility 8.4%, simulated max drawdown 13.4%.
- What-if of adding HDFC Bank at 8%: fit 64. It causes no new breach, has correlation 0.35 with the portfolio, and raises volatility by 0.75 points. The existing breach is flagged as a warning.

## Limitations
- Statistics are historical and don't predict the future.
- Beta uses the NIFTY price index rather than a total-return index.
- Model-portfolio quantities aren't adjusted for later splits.
- A holding's sector comes from the configured peer groups; anything else is "unclassified".
