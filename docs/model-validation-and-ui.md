# Model validation, agent changes and the GridNova-style UI (Nov 2026)

This round finishes the open items of the audit roadmap (`docs/audit-report.md`)
and redesigns the web app. No risk threshold was loosened.

## The model must prove it knows something

A backtest now measures the model against three baselines on the same
out-of-sample rows, each fitted only on that fold's training data:

| Baseline | What it predicts |
|---|---|
| Base rate | Always the training average (no information) |
| Momentum | Logistic regression on the 60-session return |
| Logistic | Logistic regression on all 18 features |

Stored on every model (`model_versions.skill`, `validation`):

* Brier skill score against each baseline, AUC, and 90% moving-block bootstrap
  intervals (blocks of `horizon` sessions, because forward labels overlap);
* per-fold skill, the share of folds with positive skill, the worst fold;
* skill per market regime (benchmark rising vs falling).

**Activation rules** (`backtest.validation` in `config/aegis.yaml`). A model can
be activated only if all of these pass:

1. lower 90% bound of Brier skill vs the base rate > 0;
2. lower 90% bound of AUC > 0.5;
3. positive skill in at least 60% of folds;
4. out-of-sample calibration error within the trade-gate maximum;
5. enough out-of-sample folds;
6. the universe includes delisted stocks (survivorship).

Only check 6 can be overridden, with a written reason of 30+ characters that is
stored on the model and in the audit log. The engine itself also refuses to use
any model whose validation does not allow it, however it was activated.
Backtest summaries now include Sortino, profit factor and turnover.

## Other engine changes

* **Licensing covers model inputs (P0-4).** Gate 5 fails an entry when the model
  read unlicensed data, including the NIFTY 50 benchmark.
* **Risk is a veto (P2-2).** Risk is left out of the composite score; a risk
  score below 40 rules out a positive tilt (`orchestrator.veto_agents`).
* **News agent honest off-state (P1-6).** Without the ML build it reports
  `not_active`, carries zero weight and costs no coverage. Data quality is now
  measured, and headlines dated after retrieval are excluded.
* **Replayable reports (P2-1).** Each report stores a `replay_fingerprint`;
  `GET /reports/{id}/replay` re-runs every agent at the report's original
  point in time (nothing recorded) and checks the result is identical.
* **Paper orders.** The portfolio lock is taken before the final 24-gate
  re-check, so concurrent orders cannot jointly break portfolio limits. A
  claimed tight spread can no longer improve a simulated fill.
* **Watchlists.** Two first requests no longer race to create the default list.

## UI (inspired by GridNova)

* Warm stone and verdigris palette, frosted-glass panels, Plus Jakarta Sans,
  an animated grid backdrop with travelling "market pulses" and a candlestick
  skyline. Light and dark themes are tuned separately. Chart colours were
  validated for colour-blind separation and contrast in both themes.
* Floating glass sidebar and top bar; floating bottom bar on phones.
* Home: greeting, a single "Right now" hero that says what matters today in
  one sentence with one action, then four number tiles.
* **Ask Aegis**: a helper that answers common questions from Aegis's own guide
  and live status (for example the real reasons nothing qualified today). It
  never invents answers and never gives investment advice.
* Plain-English names for all 24 checks (`frontend/lib/plain.ts`) and simpler
  page descriptions throughout.
* Backtests page shows each model's checks and model-vs-baseline table; the
  research card shows risk vetoes, "not active" agents and a reproducibility
  check.
