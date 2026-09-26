# Phase 13 Report: Model Monitoring

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Training reference** (`feature_reference`, stored on every new `ModelVersion`):
  - Per feature: training-decile bin edges and proportions.
  - The **null distribution of PSI**: the PSI of every 60-session stretch of the training data itself (stride 15) against the whole, recorded as the 95th and 99th percentiles.
- **Why the null distribution:** a first version using the textbook fixed PSI thresholds (0.10 / 0.25) was tested on a *stationary* synthetic market.
  - With 60-session windows, four features scored above 1.0 and `beta_120` scored 2.8.
  - Slow, autocorrelated features (120-day beta, 252-day drawdown, 200-day distance, benchmark regime) always look "shifted" in a short window.
  - Those fixed thresholds would have retired every model within days. The implemented rule instead judges drift against the model's own normal variation.
- **Feature drift:**
  - Current features are computed point in time (data known at `as_of`) for the last `drift_window_sessions` sessions of every stock, pooled across the universe.
  - Per feature:
    - FAIL when PSI ≥ max(0.25, its 99th percentile);
    - WARN when PSI ≥ max(0.10, its 95th percentile).
  - Per model:
    - **FAIL** when ≥ 3 features fail;
    - **WARN** when any feature fails or ≥ 3 features warn. A single feature above its 95th percentile happens by chance on most days across 18 features.
  - UNKNOWN and FAIL cases:
    - **No reference:** a model trained before Phase 13, or a tampered one, is a **FAIL**, because it cannot be monitored.
    - **Too little current data (< 100 rows):** UNKNOWN.
    - **Too little training history to calibrate a threshold (< 20 windows):** UNKNOWN.
- **Prediction log** (`model_predictions`, **immutable**):
  - Each day the active model's prediction for every stock is logged, once per (model, stock, feature session). The feature session and `predicted_at` are both recorded.
- **Calibration decay:**
  - Each logged prediction whose label window has closed gets its realised outcome, using the **exact training label**: next session's close to `horizon` sessions later, net of the same round-trip cost.
  - The newest 1,000 matured predictions are scored with ECE, Brier and AUC plus a calibration curve.
  - **FAIL** when:
    - live ECE > 0.08; or
    - live ECE − the backtest ECE > 0.05.
  - **WARN** when live ECE is above the trade gate's 0.05.
  - **UNKNOWN** (awaiting outcomes) with fewer than 100 matured predictions.
- **Auto-disable:**
  - On FAIL (with `monitoring.auto_disable: true`), the model is **retired** (audited as `model.auto_disabled` + `model.retired`) and a **critical alert** is raised.
  - The engine then has no probability source for that horizon, so gates 12–16 are UNKNOWN and every entry is rejected until an admin activates a healthy model.
  - **Fail closed even with auto-disable off:** the registry refuses a model whose latest monitoring result at `as_of` is FAIL (point in time).
- WARN results, and drift that can't be measured, raise a warning alert (once per model per day).
- Every check is stored in `model_monitor_runs` (**immutable**) with the full drift table, calibration and curve, the reasons, the action taken and the config fingerprint. Each check is audited.
- **Scheduler:** a `model-monitor` Celery task at 12:45 UTC, after the daily ranking.
- **API (admin only):** `POST /monitoring/run`, `GET /monitoring/overview`, `GET /monitoring/runs`, `GET /monitoring/runs/{id}`.
- **UI:** a new admin-only **Monitoring** page:
  - a status card per model (FAIL / retired automatically / not monitorable);
  - the drift table with each feature's PSI and its own warn/fail levels;
  - live vs backtest ECE, decay, matured and pending counts, and a calibration scatter against the diagonal;
  - run history and a "Run monitoring now" button.

  The navigation now wraps on narrow screens.
- New config section `monitoring` (strictly validated) and migration 0013: `model_versions.feature_reference`, `model_predictions`, `model_monitor_runs`.

## Tests
7 new tests; 332 in total (1 optional-NLP skip), plus ruff and mypy all clean.
- PSI worked by hand (including an empty bin); decile edges and proportions; the null quantiles exist and are ordered.
- **Drift is judged against normal variation:**
  - Same distribution → PASS.
  - A 1.5σ shift in every feature → FAIL.
  - One shifted feature → WARN, naming that feature.
  - Too few rows → UNKNOWN.
  - No reference → FAIL.
  - Too short a training history → UNKNOWN.
- **End to end with a real trained model** on seeded data:
  - One prediction per stock is logged for the latest completed session, and never twice.
  - Matured and pending predictions are counted correctly.
  - Predicting the realised base rate gives live ECE 0 and PASS.
  - The stationary market does not FAIL on drift.
  - Predictions and monitor runs can't be UPDATEd.
- **Confidently wrong predictions** (0.95):
  - Live ECE equals 0.95 − the base rate (computed independently), and the decay is checked.
  - FAIL → retired, critical alert, audits.
  - The trade engine's probability becomes None; nothing is left to monitor.
- **Auto-disable off:** the model stays active but the engine refuses it after the FAIL, and still accepts it at an `as_of` before the check (point in time).
- A model without a training reference is a FAIL and is retired.
- The API is admin-only (401 / 403); the run, overview, run detail and history endpoints are exercised, and a missing run gives 404.

## Limitations
- Drift uses the pooled universe; per-stock drift is not reported.
- The current window overlaps the end of the training data by up to `horizon` sessions, so drift appears gradually after activation.
- Monitoring checks `y_profit` calibration only; `y_outperform` is logged but not yet scored.
