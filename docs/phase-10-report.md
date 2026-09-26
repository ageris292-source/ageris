# Phase 10 Report: Walk-Forward Backtesting and the Calibrated Probability Model

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Point-in-time features** (`features-1.0.0`):
  - 18 features: returns, volatility, RSI, MACD, distance from moving averages, 252-day drawdown, volume ratio, relative strength against NIFTY, rolling beta, and benchmark regime features.
  - Each one uses only data up to date t. A property test checks that features computed on the series cut at t match those from the full series, and that changing prices after t changes nothing.
- **Labels** run from the **next session's close** to `horizon` trading days later. There is no same-bar fill.
  - `y_profit`: return after round-trip costs > 0.
  - `y_outperform`: return > NIFTY 50 over the same window.
- **Walk-forward training** (LightGBM set to deterministic, single-threaded, seed 42):
  - Expanding training windows with quarterly test folds.
  - **Purging:** a training row is used only if its label ends before the fold starts minus a 5-session embargo.
  - **Isotonic calibration** on the newest 25% of each training window, itself purged against the fitting slice.
  - Out-of-sample metrics: AUC, Brier, log loss, **expected calibration error (ECE)**, calibration curve, and the mean realised return per probability bin.
- **Strategy simulation** on out-of-sample predictions only:
  - Non-overlapping 20-day periods, top 3 names with P(profit) ≥ 0.65 and P(outperform) > 0.5, equal weight, cash for empty slots.
  - Round-trip costs from the NSE schedule are deducted. Periods with no qualifying stock count as NO-TRADE.
  - Reports CAGR, volatility, Sharpe, max drawdown and win rate, each against NIFTY 50.
- **Reproducibility record** (`backtest_runs`):
  - Stores the parameters, universe, SHA-256 of every input price, volume and benchmark value, config fingerprint, seed, library versions, and as-of / knowledge-at times.
  - Two identical runs give **bit-for-bit identical** metrics (tested).
- **Survivorship bias is flagged HIGH on every run.** The universe is today's listings only.
- **Model registry** (`model_versions`):
  - Each run registers a **candidate** trained on all labelled data. Only an admin can **activate** it (audited); activating one retires the previous active model.
  - `valid_from` is the availability time of the newest label used in training, so **a model is never applied to an earlier `as_of`**.
  - The artifact's SHA-256 is checked on every use; a tampered model is refused.
- **Trade Risk Engine integration:** the probability source defaults to the registry.
  - Gates 12–16 now use real out-of-sample calibration error, fold count, P(profit), and expected return from the empirical return per probability bin.
  - No active model for that horizon, or a sparse bin, still gives UNKNOWN (reject).
- **API:**
  - `POST /backtests` (admin), `GET /backtests`, `GET /backtests/{id}`.
  - `GET /models`, `POST /models/{id}/activate|retire` (admin), `GET /models/estimate/{ticker}`.
- **Scheduled job:** weekly retrain on Sunday, producing **candidates only**.
- Duplicate NSE/BSE listings of the same company are counted once.
- **UI:** a new **Backtests** page with headline metrics, an equity curve against NIFTY 50, a calibration scatter, the fold table, the reproducibility block, run history and the model registry with activate/retire.
- Dependencies: `lightgbm` and `scikit-learn`; the Docker image gains `libgomp1`. Trade horizons are now consistently in **trading days**.

## Tests
13 new tests; 309 in total, plus ruff and mypy all clean.
- **No look-ahead** (property test, 40 cases); labels start at t+1.
- Purging: every fold's training labels end before its test window.
- A planted signal is found (AUC > 0.75, ECE < 0.06) while pure noise stays near AUC 0.5.
- Walk-forward is deterministic; too little history is refused.
- Hand-worked ECE, return-per-bin map and portfolio simulation (including NO-TRADE periods).
- End-to-end:
  - Only admins can run backtests; runs are reproducible; survivorship is flagged.
  - Candidate models are never used; activation is admin-only; an estimate is refused before `valid_from`; activation rotates the active model.
  - The trade engine queries the active model; a wrong horizon or a tampered artifact gives no estimate.
  - A missing benchmark fails cleanly.

## Live run (real data, 24 NSE large caps, horizon 20, out of sample 2024-10-23 → 2026-08-26)
| | Result |
|---|---|
| AUC, P(profit) | **0.501 (no skill)** |
| ECE, P(profit) | 0.098 (gate maximum 0.050, **fails**) |
| AUC / ECE, P(outperform) | 0.505 / 0.034 |
| Folds | 8 |
| Strategy | −10.5% total (15 trades, 18 of 23 periods NO-TRADE, win rate 27%) |
| NIFTY 50 | −2.5% total |

**Conclusion: this price-only model has no edge on this universe and period.** It stays a candidate. Even if activated, gate 12 would reject every proposal. The system is doing its job: it will not trade on a model that cannot demonstrate calibrated skill.

## Limitations
- Features are price-based only. Point-in-time fundamentals and news features are future work.
- Benchmark history is about 5 years, which limits the number of folds.
- Survivorship bias is HIGH, and there's no point-in-time index membership.
- Isotonic calibration on small slices can be overconfident at the extremes, which the ECE reflects.
