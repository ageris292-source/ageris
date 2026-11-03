# AEGIS — AI/ML, Multi-Agent Architecture & Reliability Audit

Audit date: 30 October 2026
Repository: https://github.com/ageris292-source/ageris, commit `ad99da5` (main)
Status of this document: **Audit report, Phases 1–6 in depth, Phases 7–9 as a first pass.** No code was modified. Nothing in this report is a proposal that has been implemented.

---

## 0. How to read this report

**What I did.** I cloned the public repository and read the code paths that decide a trade: the agent contract, the orchestrator, all seven agents (calculation level for Technical, structural level for the others), the 24-gate Trade Risk Engine, the walk-forward/LightGBM pipeline, the model registry, monitoring, news/NLP, paper trading, the audit trail, authentication and the scheduler. I then **ran** the backend test suite, ruff and mypy, and wrote three small read-only probes against the real gate engine to confirm suspected weaknesses.

**What I did not do (yet).** I did not read every line of the 20,000-line backend. Not yet examined in detail: the market-data validation/adjustment layer (`market_data/validation.py`, `adjustments.py`), the internals of the Fundamental, Macro, Risk, Valuation and Portfolio agents beyond their scoring structure, the ranking service, the frontend, and the HTTP security layer. I could not inspect the production Railway database, so **I cannot say whether any model has ever been trained or activated in production, or what any real backtest result was.** Where a statement below rests on code reading only (not execution), it is marked *(code reading)*; where I executed something, it is marked *(executed)*.

**Evidence labels used throughout:** Fully implemented · Partially implemented · Present but not integrated · Missing · Implemented but insufficiently tested.

---

## 1. Executive summary

AEGIS is, in the main, an honestly built system. Its core safety design is real and is enforced in code, not only in the README: a non-OK agent cannot carry a score (a pydantic validator enforces this), UNKNOWN fails every gate, the 24 gates are a pure function, the audit table rejects UPDATE/DELETE at the database level, live trading is switched off by a build constant, and paper orders need an admin plus an idempotency key plus a full re-check. The walk-forward code has genuine leakage controls (purging, embargo, point-in-time features with a truncation test).

The weaknesses are mostly **not** in the safety skeleton. They are in four places:

1. **The "intelligence" is thinner than the architecture implies.** Of the seven agents, six are hand-written deterministic rules, and the seventh (News) uses a pretrained FinBERT model that is **not installed in the documented production build** (`AEGIS_ML=0`). The only trained model, a LightGBM classifier, is **not an agent and is not used by the orchestrator at all**; it only feeds the Trade Risk Engine. No threshold or weight in any agent has been validated against outcomes.
2. **The ML model is never compared to a baseline, and no gate requires skill.** The calibration gate checks that probabilities are *honest*, not that they are *informative*. I confirmed that a model with zero skill sails through the calibration and out-of-sample gates (§6.3).
3. **Three gates rest on information the requester supplies or the system cannot obtain**: the spread gate trusts a number typed in the proposal; the research-report freshness gate measures the report's *creation* time, not the time of the data it analysed; and the licensing gate checks the stock's prices but not the unlicensed benchmark feed the model's features use.
4. **The exit path is broken in practice.** Automatic stop-loss/target exit proposals built by the thesis monitor omit the spread, so the engine always rejects them *(executed)*. The test that should catch this accepts either outcome.

**Overall maturity:** a well-engineered research and paper-trading *framework* with strong process discipline, at an early stage as a *predictive system*. There is currently no evidence in the repository that any part of AEGIS predicts returns better than a trivial baseline. That is not a failure; it is the honest state, and the roadmap in §9 is designed to either produce that evidence or show it is absent.

**Verification summary (all executed by me in this session):**

| Check | Result |
|---|---|
| `pytest` (full backend) | 371 passed, **2 failed**, 1 skipped (148 s) |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 191 files already formatted |
| `mypy app` | Success, 146 source files |

The 2 failures are not logic errors; they are **clock-dependent tests** (§9, P0-6).

---

## 2. Phase 1 — Repository architecture map (as implemented)

### 2.1 Layout

| Area | Path | What is really there |
|---|---|---|
| API | `backend/app/api/routes/*` (21 route modules) | FastAPI; JWT bearer; `CurrentUser` / `AdminUser` dependencies |
| Agents | `backend/app/agents/{technical,fundamental,valuation,risk,news,macro,portfolio}` | 7 agents, one common `AgentOutput` contract (`agents/base.py`) |
| Orchestrator | `backend/app/orchestrator/{service,synthesis,narrative,markdown}.py` | Sequential runner, deterministic synthesis, optional LLM narrator |
| Trade Risk Engine | `backend/app/trade/{gates,context,costs,probability,service,schemas}.py` | 24 gates, pure `evaluate()` |
| ML | `backend/app/backtest/{features,data,walkforward,simulate,service,registry}.py` | LightGBM + isotonic calibration, walk-forward, model registry |
| Monitoring | `backend/app/monitoring/service.py` | PSI drift, live calibration decay, auto-retire |
| News/NLP | `backend/app/news/{provider,nlp,events,service}.py` | Google News RSS, FinBERT, MiniLM, pgvector document search |
| Data | `backend/app/market_data/*`, `macro/`, `fundamentals/` | Yahoo (unlicensed), NSE bhavcopy (licensed, via Mac feeder), World Bank |
| Paper trading | `backend/app/paper/*`, `portfolio/`, `risk/` | Simulated broker, theses, monitoring |
| Live | `backend/app/live/broker.py` | Interface plus `UnavailableBroker` only |
| Scheduler | `backend/app/scheduler/celery_app.py` | Celery beat: 11 scheduled jobs |
| Persistence | `backend/app/models/*`, `alembic/versions/0001..0015` | Postgres + pgvector; immutability triggers on key tables |
| Frontend | `frontend/` (Next.js 15) | ~6,100 lines TS/TSX; **not audited in this pass** |
| Tests/CI | `backend/tests/` (24 files, ~6,700 lines), `.github/workflows/ci.yml` | ruff, format-check, mypy, pytest+cov; frontend build+typecheck |

Size: ~20,000 lines of backend application code, ~6,700 lines of backend tests.

### 2.2 The intended data flow versus the real one

Your intended flow: *Market data → validation → individual agents → orchestration → ML predictions → research synthesis → Trade Risk Engine → human approval → paper trading → audit logs.*

The real flow, verified in code:

```
 Yahoo / NSE bhavcopy / World Bank / Google News          (market_data/providers, macro/providers, news/provider)
        │  ingest + validate (market_data/validation.py), stored immutably with data_version
        ▼
 ┌────────────────── orchestrator.run_analysis (orchestrator/service.py) ──────────────────┐
 │ technical → fundamental → valuation → risk → news → macro → [portfolio]   (SEQUENTIAL)  │
 │   each agent: run_and_record() → AgentOutput → agent_runs + agent_outputs (immutable)   │
 │ synthesize()  (orchestrator/synthesis.py): weighted mean of scores, conflicts, bull/bear │
 │ narrative (deterministic text; optional LLM rewrite, guarded)                            │
 │ report hash (sha256 of report JSON) → analysis_reports                                   │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
                                   │ (stance, report_id, hash)
        ┌──────────────────────────┘
        │          ML branch (NOT inside the orchestrator):
        │          backtest/service.run_backtest → ModelVersion(status=candidate)
        │          admin POST /backtest/models/{id}/activate → status=active
        │          registry.estimate() → ProbabilityEstimate  ──┐
        ▼                                                       ▼
 trade/service.submit → trade/context.build → trade/gates.evaluate (24 gates, pure)
        │   decision APPROVED/REJECTED + decision_hash → trade_decisions (immutable)
        ▼
 paper/service.place_order   (admin only, Idempotency-Key, decision ≤ N min old,
        │                      FULL RE-CHECK of all 24 gates at "now", row lock)
        ▼
 simulated fill → PaperExecution, Position, Thesis → audit_logs (append-only triggers)
```

### 2.3 Differences between intended and actual architecture

| # | Intended | Actual | Evidence |
|---|---|---|---|
| D1 | ML predictions flow *through* agents/orchestration into the synthesis | ML is a **separate branch**. The orchestrator never calls the model; the report's stance is built only from rule-based agent scores. The two meet only at the gate engine. | `orchestrator/service.py` imports no `backtest`/`registry`; `trade/context.py:97` calls `probability.estimate` |
| D2 | Agents run (conceptually) independently | Run **sequentially** in one DB session, one commit per agent | `orchestrator/service.py:run_analysis` |
| D3 | News agent contributes sentiment | In the documented production build (`AEGIS_ML=0`, `docs/deployment.md` lines 125–143) FinBERT is **not installed**, so the News agent returns `INSUFFICIENT_DATA` and its 10 % weight is renormalised away | `news/nlp.py:FinBert`, `agents/news/agent.py:run_news`, `docker/backend.Dockerfile` |
| D4 | A document-retrieval (RAG) layer informs research | Retrieval exists (`news/service.py:search_documents`, pgvector) but **no agent or orchestrator step calls it**. It is a search endpoint, not part of any decision. | grep: no agent imports `search_documents` |
| D5 | One research report fully determines the research gate | The gate uses the report's *stance* and *creation time*; it does not check what `as_of` the report analysed | `trade/context.py:86–94`, `gates.py:_research_report` |
| D6 | Live broker health from the adapter | Always UNKNOWN by construction | `live/broker.py` |

---

## 3. Phase 2 — Agent-by-agent audit

### 3.0 Facts true of all seven agents

* **Shared contract** (`agents/base.py:AgentOutput`): fields `status, score, confidence, confidence_basis, signals, evidence, risks, invalidation_conditions, metrics, data_quality, data_snapshot_id, config_fingerprint, warnings`. A pydantic `model_validator` raises if a non-OK output carries a score, signals or non-zero confidence, or lacks warnings. **Fully implemented and well designed.** Status enum is `OK / INSUFFICIENT_DATA / DATA_UNUSABLE / FAILED`; there is no separate `UNKNOWN`, but the three non-OK states serve the same purpose.
* **Shared scoring** (`agents/common.py:composite`): per category, net = mean(direction × strength); composite = weighted mean over categories present; **score = 50 + 50 × composite**. Weights are hand-set in `config/aegis.yaml`.
* **Confidence is a heuristic everywhere** and is labelled `heuristic_uncalibrated` in every agent. Technical: `agreement × breadth × data_quality` (halved if stale). Nothing maps confidence to a real hit rate. Good that it is labelled; it must therefore never be read as a probability.
* **None of the seven agents contains a trained model.** Six are deterministic rules. News uses a *pretrained, not fine-tuned* FinBERT.
* **Reproducibility.** Each run stores `data_snapshot_id` (content hash of input bars), `config_fingerprint`, `knowledge_at` and the output JSON. A replay with the same `as_of`/`knowledge_at` can reproduce scores. **But** the report hash includes each output's `generated_at = now()` *(code reading, `agents/technical/agent.py`, `AgentOutput.generated_at`)*, so re-running an analysis never reproduces the hash. The hash is therefore **tamper-evidence, not a reproducibility check** (see §5).
* **Failure handling.** Each `run_and_record` catches all exceptions, rolls back, and records a `FAILED` output. Fail-closed is real.
* **Cross-agent finding: the data-quality and licensing information is in warnings, not in `status`.** An agent that analyses unlicensed Yahoo prices returns `OK` with a warning. That is acceptable only because the gate engine enforces licensing separately (§6).

### 3.1 Technical Agent — `agents/technical/{agent,analysis}.py`, `analysis/indicators.py`

| Component | Current implementation | Evidence in code | Weakness | Recommended improvement |
|---|---|---|---|---|
| Responsibility | Descriptive technical composite, 0–100 | `agent.py` `SCORE_BASIS` | Score is labelled "not a probability" but feeds a stance that gates trades | Keep label; add an empirical test (see §7 ablation) |
| Input | Split-adjusted daily bars, ≥260 sessions, point-in-time via `md.get_series(as_of, knowledge_at)` | `agent.py:run_technical` | Needs 260 sessions; new listings are excluded | Fine |
| Algorithms | SMA 20/50/200, RSI(14), MACD(12,26,9), Bollinger(20,2), ATR, ADX(14), ROC [21,63,126,252], 55-day breakout with volume ×1.5, squeeze, pivots / support-resistance clustering, divergence | `analysis.py`, `config/aegis.yaml` `technical:` | Classical rules with textbook thresholds; no evidence they carry edge on NSE data | Evaluate each signal family out-of-sample before weighting |
| Scoring | Category weights trend 0.35, momentum 0.30, breakout 0.15, volume 0.10, mean-reversion 0.10 | `aegis.yaml:104-109` | Weights are asserted, not fitted. Trend and mean-reversion signals can cancel arbitrarily | Fit/validate weights walk-forward; or drop to 2–3 evidence-backed families |
| Model type | **Deterministic rules. No ML.** | whole module | — | — |
| Missing/stale data | No bars → `INSUFFICIENT_DATA`; failed validation → `DATA_UNUSABLE`; <260 bars → `INSUFFICIENT_DATA`; stale → warning + confidence ×0.5 | `agent.py:78-120` | Staleness lowers confidence but status stays OK | Acceptable; gate 6 enforces freshness |
| Reproducible | Yes (snapshot hash + config fingerprint); `generated_at` is non-deterministic | `snapshot_id()` | — | Exclude `generated_at` from hashes |
| Tests | `tests/test_indicators.py` (8), `tests/test_technical_agent.py` (14) | executed, passing | Tests verify *calculations*, not predictive value | Add the §7 ablation |

### 3.2 Fundamental Agent — `agents/fundamental/agent.py`, `fundamentals/{providers,ratios,service}.py`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Responsibility | Growth, profitability, balance sheet, cash quality, valuation ratios; history and peer comparison | `agent.py` docstring | — | — |
| Input | Yahoo `fundamentals-timeseries` (**unlicensed, unofficial**) or CSV import with real `published_at` | `fundamentals/providers.py:1-10` | Yahoo gives period-end but **not publication date**; availability is *estimated* from SEBI deadlines (45 d quarterly, 60 d annual) and flagged | Prefer CSV/filing-sourced data with true publication dates for anything beyond demonstration |
| Point-in-time | `facts_as_of` excludes estimated-availability facts unless Aegis had retrieved them by `as_of` | `fundamentals/service.py:167-190` | Good design; but a fixed 45-day lag can be wrong for early/late filers and restatements are not modelled | Store actual filing dates; keep restated versions |
| Scoring | `composite()` with config category weights | `agent.py:324` | Hand-set weights; peer groups only for 4 hard-coded groups | Validate or simplify |
| Model type | **Deterministic ratios + rules. No ML.** | | | |
| Missing data | `INSUFFICIENT_DATA` when facts absent; lenders skip industrial ratios | `agent.py:288`, `aegis.yaml:135` | Peer comparison silently unavailable for most stocks | Surface coverage in the UI |
| Tests | `tests/test_fundamentals.py` (15) | **1 failing: clock-dependent** (`test_agent_ok_now_but_blind_in_the_past`) | Time-bomb test | Freeze the clock (P0-6) |

### 3.3 News Agent — `agents/news/agent.py`, `news/*`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Responsibility | Headline sentiment score | `SCORE_BASIS` | Headlines only; article bodies never read | Acceptable scope; state it |
| Model | **Pretrained `ProsusAI/finbert`** loaded via `transformers.pipeline("text-classification", top_k=None)`; **not fine-tuned** | `news/nlp.py:FinBert`, `aegis.yaml:148` | General English financial text (US-centric); not validated on Indian headlines | Evaluate on a labelled Indian sample before trusting |
| Score | `50 + 50 × Σ(w·s)/Σw`, `s = P(pos) − P(neg)`, `w = event importance × recency decay (half-life 5 d)` | `agent.py:98-101` | Weights `importance` (config) hand-set | Validate |
| Availability | Needs ≥3 dated, de-duplicated, scored headlines in 30 days | `aegis.yaml:153,155` | **In the documented Railway build FinBERT is absent → always `INSUFFICIENT_DATA`** *(code reading)* | Decide: ship the ML build, or remove the agent's weight and say so |
| Data quality | **Hard-coded `data_quality=0.8`** | `agent.py` (return statement) | Not measured | Compute from coverage/recency/source diversity |
| Confidence | `agreement × min(1, n/10) × (0.5 if conflicts)` | `agent.py:160` | Heuristic | Label retained; do not use as a probability |
| Failure mode | Model load failure → `ModelUnavailableError` → sentiment `None` → item excluded, not scored neutral | `nlp.py`, `service.py:_optional_models` | **Correct fail-closed behaviour** | Keep |
| Tests | `tests/test_news.py` (12) | **1 failing: clock-dependent** | News fixtures dated Sep 2026 + 30-day lookback ⇒ test now fails | P0-6 |

### 3.4 Macro Agent — `agents/macro/agent.py`, `macro/*`, `analysis/regime.py`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Responsibility | Each macro driver's recent change mapped through a **hand-set sector sensitivity** (+1 benefits, −1 hurt) | `aegis.yaml:196-201` | Sensitivities are assertions (e.g. `IT_SERVICES: usd_inr +1.0`). Only 4 sectors configured; others get market-wide drivers only | Estimate sensitivities from data or mark as priors |
| Inputs | World Bank (CPI, GDP, annual; licensed CC-BY), Yahoo for NIFTY/VIX/USDINR/Brent/sector indices (**unlicensed**) | `macro/providers.py`, `aegis.yaml:175-189` | `repo_rate` appears in the model but has **no automated source** (manual import only) | Add an official RBI source or drop the driver |
| Model type | Deterministic | | | |
| Regime | `analysis/regime.py` rule-based (trend band 2 %, VIX 13/20) | `aegis.yaml:192-194` | Fixed thresholds | Fine as a label; do not use as a gate without validation |

### 3.5 Valuation Agent — `agents/valuation/agent.py`, `valuation/dcf.py`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Calculation | 3-scenario DCF: FCF = revenue × margin, 5 years, Gordon terminal value; `score = 50 + 50·tanh(margin_of_safety/0.30)` | `dcf.py`, `aegis.yaml:204-215` | Output is hypersensitive to WACC and terminal growth (terminal value is typically most of EV; the code records `terminal_share_of_ev`) | The sensitivity grid is already produced — good; make confidence fall when terminal share is high |
| Inputs | Risk-free 6.5 %, ERP 7 % (**manually set assumptions**, flagged "verify"), beta from 104 weeks of returns, bounds [0.3, 2.5] | `aegis.yaml:205-214` | Static `risk_free_rate`; goes stale silently | Add an "assumption age" check |
| Model type | Deterministic; honest labelling ("configured assumptions, not live market data") | | | |

### 3.6 Risk Agent — `agents/risk/agent.py`, `analysis/risk.py`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Calculation | Annualised volatility, historical (non-parametric) VaR/CVaR 95/99, max drawdown, beta, return quality, liquidity (ADTV) | `analysis/risk.py`, `aegis.yaml:219-236` | Backward-looking; 252-session window | Fine for description |
| **Conceptual issue** | "Higher score = **lower** measured risk" and it is the only `required_agents` member | `agents/risk/agent.py` docstring, `aegis.yaml:256` | A low-risk, directionless stock earns a high score, and risk carries 20 % weight, so **the research stance can turn POSITIVE because a stock is calm, not because it is expected to rise** | Split "risk acceptability" (a constraint) from "return tilt" (a signal); do not average them |

### 3.7 Portfolio Agent — `agents/portfolio/agent.py`, `portfolio/service.py`

| Component | Current implementation | Evidence | Weakness | Recommended improvement |
|---|---|---|---|---|
| Calculation | Portfolio before/after a candidate buy: limit checks, correlation, marginal volatility, sector room | `agents/portfolio/agent.py` | Weight 5 %; only runs when a `portfolio_id` is supplied | — |
| Duplication | The same post-trade limits are re-evaluated by gate 23 (`portfolio_limits`) via `ps.analyze` | `trade/context.py:100-121` | Two evaluations of the same rules could in principle drift | Single source of truth already (`ps.analyze`) — keep |

### 3.8 Answer to "which agents use real ML?"

| Agent | Deterministic | Traditional ML | Deep learning | LLM | Trained for AEGIS |
|---|---|---|---|---|---|
| Technical | ✔ | | | | no |
| Fundamental | ✔ | | | | no |
| Valuation | ✔ | | | | no |
| Risk | ✔ | | | | no |
| Macro | ✔ | | | | no |
| Portfolio | ✔ | | | | no |
| News | partly (weights) | | ✔ pretrained FinBERT (not fine-tuned) | | no |
| *(LightGBM — not an agent)* | | ✔ | | | **yes**, trained in-app |
| *(Orchestrator narrator)* | | | | optional Claude call, prose only | no |

---

## 4. Phase 3 — ML model lifecycle audit

### 4.1 Answers to your 15 questions

1. **What does it predict?** Two binary targets from one pooled model per target: `y_profit` = 1 if the forward return net of a fixed round-trip cost is > 0; `y_outperform` = 1 if forward return > NIFTY 50 forward return. *(`backtest/features.py:forward_labels`)*
2. **Input features.** 18 features: returns over 5/20/60/120 sessions, 20/60-day volatility, RSI(14), normalised MACD histogram, distance to SMA50/SMA200, 252-day drawdown, volume ratio (20d/60d), relative strength vs benchmark (20/60d), 120-day beta, and three benchmark-state features. *(`FEATURES`, `FEATURE_VERSION = "features-1.0.0"`)* **All are price/volume-derived. No fundamentals, news, or macro agent output enters the model.**
3. **Target.** Entry at the **next** session's close, exit `horizon` (20) sessions later; cost = a constant computed once for a ₹10 lakh order on ₹1,000 cr ADTV (`backtest/service.py:label_cost`).
4. **Dataset construction.** Pooled (date, ticker) rows over `universe()` = all currently active stocks (NSE listing preferred); first 253 rows per stock dropped as warm-up. *(`backtest/data.py:build_dataset`)*
5. **Look-ahead bias.** *Features:* none found; each is a rolling/EWM function of the past, and `test_features_never_look_ahead` checks truncation equals full-series values *(executed, passing)*. *Labels:* correctly start at t+1. *Residual risk:* split/total-return adjusted prices are rebased using later corporate actions, which is standard and ratio-neutral for these features; I found no leak but did not audit `market_data/adjustments.py` in depth.
6. **Data leakage.** Training rows enter a fold only if their **label window ends before the test start minus a 5-session embargo** (`walkforward.py:walk_forward`); calibration uses the newest 25 % of the training window, with the fit set purged against it. `test_walk_forward_purges_overlapping_labels` checks `train_last_label_end < test_start` *(executed, passing)*. This is good practice. **Caveat:** rows are daily with 20-day overlapping labels, so effective sample size is far below row count; metrics derived from row counts overstate certainty.
7. **Survivorship bias.** **Present, acknowledged, and not blocking.** `SURVIVORSHIP_NOTE` in `backtest/service.py` sets `survivorship_bias="HIGH"` ("today's listings … biased upward"). It is a warning only; nothing prevents activation of such a model.
8. **Train/test separation.** Yes, by walk-forward (504-session minimum training, 63-session test folds). The **final deployed model is trained on all labelled data and has never itself been tested out of sample**; its reported metrics come from the fold models. This is standard but should be stated on the model card.
9. **Costs/slippage.** Included in the *label* (constant `label_cost`) and in the *gates* (per-order cost model with participation-based impact, `trade/costs.py`). The label uses a fixed typical-order cost, while the gate uses the real order's cost; reasonable. Costs are **config assumptions** ("MUST be checked against current schedules", `aegis.yaml`), not measured fills.
10. **Calibrated?** Yes — isotonic regression fit on a held-back slice, clipped to [0,1] (`fit_calibrated`). Out-of-sample ECE (10 equal-width bins) is stored as `ModelVersion.calibration_error`.
11. **Outperforms a baseline?** **Unknown, and structurally untested.** There is no baseline comparison anywhere in the code or tests (searched `baseline|naive|buy.and.hold|skill`). The strategy simulation compares to the NIFTY benchmark only; the *predictions* are never compared with "always predict the base rate", a momentum rule, or a linear model. `ModelVersion.auc` is stored but **not passed to the gate engine** (`ProbabilityEstimate` has no AUC/Brier/skill field).
12. **Regime generalisation.** Not measured. Fold metrics are stored per fold (`run.folds`), but nothing aggregates them by regime, and nothing requires stability across folds.
13. **How the engine uses predictions.** Gates 12–16 and the `fractional_kelly` sizing option (§6). The `expected_return` fed to the gate is the **mean realised return in the OOS p_profit bin** (`expected_return_map` / `lookup_expected`), i.e. an empirical bin average, not a model output.
14. **When the model is unavailable/stale/uncalibrated/drifting.** `registry.estimate()` returns `None` → gates 12–16 are UNKNOWN → REJECTED. Hash of the stored artifact is re-verified on every use. A model whose **latest monitor result is `FAIL`** is blocked even if auto-disable is off. **But `UNKNOWN` and `WARN` monitor results do not block** (`registry.monitor_blocked` tests only `== "FAIL"`), and a newly activated model with **no monitor run yet** is used. This is the one place where "UNKNOWN is never PASS" is softened *(code reading)*.
15. **Can an unvalidated candidate influence a decision?** **No** — `active_model()` selects only `status == "active"`, candidates need an admin POST to activate (`api/routes/backtest.py:activate`), and retraining (`aegis.retrain_models`, Sundays 04:00 UTC) only creates candidates. **But activation has no quality criteria**: an admin can activate a candidate whose ECE exceeds the gate maximum (the code only appends a warning), whose survivorship bias is HIGH, or whose AUC is 0.50.

### 4.2 Confirmed weakness: the model gates do not require skill *(executed)*

I built the pure-engine scenario in which the model always predicts the training base rate (62 %) on a sample with a 62 % hit rate. Result: **ECE = 0.0037** (gate maximum 0.05), and the gates read:

```
model_calibration: PASS      out_of_sample: PASS      probability_of_profit: FAIL
```

It fails only because 0.62 < 0.65. **If the pooled base rate of "net profit over 20 days" reaches 0.65 — plausible in a strong market on a survivor-only universe — a model with no ability to rank stocks would pass all three.** The `probability_of_profit` gate is, in that case, a base-rate gate. A skill requirement (AUC, Brier skill score versus the base-rate predictor, with a confidence interval, stable across folds) is missing.

### 4.3 Other ML observations

* **Tiny effective universe.** The previous deployment tracked roughly five stocks. Pooled over five names with 20-day overlapping labels, there are very few independent observations. With licensed NSE bhavcopy history starting 2021-09 (feeder argument), expect on the order of ~8 quarterly folds. Statistical power to detect modest skill is very low. *(estimate from config: 504-session minimum train + 63-session folds; exact counts depend on loaded history, which I could not see.)*
* **Mixed data licensing.** Training may use Yahoo (unlicensed) history; the feeder adds licensed bars from 2021 onwards.
* **The benchmark feed is unlicensed Yahoo `^NSEI`** (`aegis.yaml:182-188`, `registry.predict` → `load_benchmark`). Six of the 18 features depend on it (`rs_*`, `beta_120`, `bench_*`). The licensing gate checks only the **stock's** price source (`trade/context.py`: `ctx.price_licensed = h.licensed`). A trade can therefore be approved with licensed stock prices while the model's inputs include unlicensed data. This contradicts the rule "unlicensed data cannot qualify a trade".
* **ECE weakness.** Ten equal-width bins; if predictions cluster in one or two bins, ECE reduces to roughly |mean prediction − base rate|, which is nearly zero for any base-rate predictor (as shown above). Add Brier skill and reliability by quantile.
* **Monitoring is well designed** (PSI against the model's own training windows with a null-distribution threshold; live calibration from logged predictions; auto-retire on FAIL; alerts). Its limitation: needs ≥100 matured predictions (`min_matured_predictions`), which at a 20-day horizon on a handful of stocks takes a long time, during which calibration status is `UNKNOWN` and — per above — the model is still usable.
* **Passing tests do not prove predictive skill.** `test_walk_forward_finds_real_signal_and_not_noise` uses **synthetic data with a planted signal** and checks that the pipeline recovers it (AUC > 0.75) and that pure noise gives AUC ≈ 0.5. That validates the *machinery*, which is valuable, and says nothing about NSE returns.

---

## 5. Phase 5 — Orchestrator and multi-agent reliability *(Phase 4 follows in §5b)*

| Question | Finding | Evidence |
|---|---|---|
| Which agents run? | technical, fundamental, valuation, risk, news, macro; portfolio only if `portfolio_id` given | `orchestrator/service.py` |
| Parallel or sequential? | **Sequential**, one DB session | same |
| Error handling | Each agent catches everything and returns `FAILED`; others continue. A failure inside `record_run`'s DB writes would not be caught per-agent | `agents/*/agent.py:run_and_record` |
| Output validation | Strong: `AgentOutput` pydantic model with the fail-closed validator | `agents/base.py` |
| Disagreement detection | Pairwise: two agents conflict if one ≥ 50+12.5 and another ≤ 50−12.5 (`conflict_gap` 25). Gate 11 requires 0 conflicts | `synthesis.py`, `aegis.yaml:259` |
| Is confidence calibrated? | **No.** `heuristic_uncalibrated`, composed as base × coverage × (1 − 0.15)^conflicts | `synthesis.py` |
| Bull/bear synthesis | Deterministic ranking of signals by `strength × agent_weight` | `synthesis.py:synthesize` |
| Can an LLM influence a decision? | **No.** The narrator receives the finished report and rewrites prose; output is validated by `narrative.validate` and falls back to deterministic text. `synthesis["decision"]` is the constant `"NO TRADE"`. The stance, which gate 10 uses, is computed before and independent of the narrator | `orchestrator/narrative.py`, `synthesis.py` |
| Can any agent bypass the risk engine? | **No path found.** `paper.place_order` requires an APPROVED decision and re-runs `ts.submit`; the only code that creates a `PaperOrder` is `place_order` *(code reading)* | `paper/service.py` |
| Reproducible from stored inputs? | Partially. Inputs are pinned (`as_of`, `knowledge_at`, snapshot hash, config fingerprint), so *scores* can be recomputed, but the report hash includes `generated_at` and the narrative, so **the hash cannot be reproduced** | `orchestrator/service.py:_hash`, `AgentOutput.generated_at` |

### 5.1 Finding: the research gate measures the wrong time *(code reading)*

`POST /analysis/{ticker}` accepts any timezone-aware `as_of` (`api/routes/analysis.py`: `_aware` only checks the timezone). The gate computes `report_age_hours = as_of − rep.created_at` (`trade/context.py:94`), where `created_at` is the wall-clock moment the report was *stored*. A report generated now **with a past `as_of`** therefore appears 0 hours old and can satisfy gates 9–10 (`research_report`, `research_stance`) while describing a stale market. Mitigations that exist: price freshness/licensing/quality gates use current data, and the pre-order re-check re-evaluates at "now". The gap remains for the *research stance* specifically. The fix is small: compare the report's own `as_of` and `knowledge_at` to the proposal time.

### 5.2 Finding: no four-eyes control

`/trade/proposals` is open to any `CurrentUser`; `/paper/orders` requires an `AdminUser` — but the same admin can propose and approve. With a single operator this is the intended "human in the loop", but it is not separation of duties.

---

## 5b. Phase 4 — News, NLP and RAG audit

| Question | Finding | Evidence |
|---|---|---|
| Models | `ProsusAI/finbert` (sentiment) and `sentence-transformers/all-MiniLM-L6-v2` (384-dim embeddings), both pretrained, downloaded from Hugging Face at first use | `aegis.yaml:148-150`, `news/nlp.py` |
| Available in deployment? | Docker build arg `AEGIS_ML=1` default installs CPU torch + transformers; **`docs/deployment.md` instructs `AEGIS_ML=0` for Railway**, so neither model is present in the documented production setup. Even with `AEGIS_ML=1`, models download at runtime to an ephemeral filesystem | `docker/backend.Dockerfile`, `docs/deployment.md:125-143` |
| Collection | Google News RSS search, headline + publisher + link + pubDate only; unofficial and **unlicensed** | `news/provider.py` |
| Deduplication | (1) exact normalised-title hash; (2) near-duplicate via embedding cosine ≥ 0.90 within a 72-hour window **only when the embedder is available** | `news/service.py:ingest_news` |
| Timestamp reliability | Taken from the RSS `published_parsed`; items without one are flagged `historical_use=false` and excluded from the agent. **There is no check that `published_at ≤ retrieved_at`** (a future-dated or mis-parsed timestamp would be accepted) | `provider.py`, `service.py` |
| Sentiment correctness | Standard: `positive − negative` probability from FinBERT. Headline-only; no entity/target resolution — `query_for()` uses `"Company" OR "SYMBOL share"` and the agent does not verify the headline is *about* the company (`mentions` is stored but not used to filter) | `provider.py:query_for`, `agents/news/agent.py` |
| Can duplicates distort sentiment? | Exact duplicates: no. Near-duplicates: **yes if the embedder is missing but FinBERT is present** (the embedder-less case dedups only exact titles). Syndicated rewrites with different wording above/below 0.90 similarity also pass | `service.py` |
| Can old news influence a current decision? | Bounded: 30-day lookback and 5-day half-life; `news_as_of` filters `published_at ≤ as_of` and `retrieved_at ≤ knowledge_at` | `news/service.py:news_as_of` |
| Are embeddings used for retrieval? | Yes, in `search_documents` (pgvector cosine, filtered by `published_at ≤ as_of`, each hit carries source/page/chunk). **But it is not connected to any agent** — it is an endpoint | `news/service.py` |
| Model failure → UNKNOWN? | **Yes, correctly**: no model ⇒ sentiment `None` ⇒ item excluded ⇒ `INSUFFICIENT_DATA` (never neutral) | `agents/news/agent.py:85-96` |

**Improvements that would materially help (in order of value):** (1) decide whether the News agent is in or out in production, and say so; (2) entity relevance filter (is the headline about this company?) before scoring; (3) evaluate FinBERT on a few hundred hand-labelled Indian headlines and report accuracy honestly; (4) event extraction from NSE/BSE corporate announcements (licensed, structured, dated) is a far stronger signal than Google RSS; (5) require `published_at ≤ retrieved_at`; (6) dedupe by story cluster, not only pairwise.

---

## 6. Phase 6 — The 24-gate Trade Risk Engine

### 6.1 Structure verified *(code + executed tests)*

* `GATES` is a list of 24 `(name, applies_to_exits, fn)` tuples; `assert len(GATES) == 24` at import; `self_test()` checks that an all-unknown context is rejected with **all 24 gates failing** and the first failure is `kill_switch`.
* `evaluate()` is a pure function; an exception inside a gate becomes `FAIL` ("a crashing gate never passes").
* APPROVED only if no gate is `FAIL` or `UNKNOWN`; `requires_human_approval=True` is hard-coded.
* `decision_hash` = sha256 of the decision JSON excluding `decision_hash` and `evaluated_at`; the stored context snapshot is part of the hash.
* Live trading: `LIVE_TRADING_AVAILABLE = False` (`core/modes.py`) and `UnavailableBroker`; gate 2 requires `system_mode == "paper"` for paper orders.

### 6.2 Gate table

(Thresholds from `config/aegis.yaml`: P(profit) ≥ 0.65, expected net return ≥ 5 %, edge ≥ 3 %, reward/risk ≥ 2.0, data quality ≥ 0.90, ECE ≤ 0.05, OOS folds ≥ 4.)

| # | Gate | PASS when | FAIL when | UNKNOWN when | Exits? | Weakness |
|---|---|---|---|---|---|---|
| 1 | `kill_switch` | state readable and inactive | active | state unreadable / row missing | yes | Solid; any active user may activate, only admin may release |
| 2 | `execution_mode` | paper order and `system_mode=="paper"` | otherwise; live always fails | broker health unknown | yes | Solid |
| 3 | `portfolio_match` | portfolio kind == order mode | mismatch / not found | — | yes | — |
| 4 | `instrument` | active NSE/BSE INR equity; exit ≤ held qty | not found / outside scope / inactive / oversell | — | yes | Fine |
| 5 | `data_licensed` | stock price source licensed | unlicensed | no prices | yes | **Does not cover the unlicensed benchmark feed the model uses (§4.3)**; blocks exits too when data is unlicensed |
| 6 | `data_freshness` | latest bar within rule | stale | unknown | yes | — |
| 7 | `data_quality` | score ≥ 0.90 | below | not measured | yes | — |
| 8 | `entry_deviation` | limit within configured deviation of last close | beyond | no reference price | yes | Reference is last close (EOD data) |
| 9 | `research_report` | hash verifies and `now − created_at ≤ 24 h` | hash mismatch / future dated / older | no report | no | **Uses creation time, not the report's own `as_of` (§5.1)** |
| 10 | `research_stance` | stance == `POSITIVE_TILT` | otherwise | no stance | no | Stance built from uncalibrated rule scores; risk-agent conflation (§3.6) |
| 11 | `agent_conflicts` | 0 conflicts | >0 | unknown | no | — |
| 12 | `model_calibration` | calibrated and ECE ≤ 0.05 | uncalibrated / above | no estimate | no | **Does not test skill (§4.2)** |
| 13 | `out_of_sample` | OOS folds ≥ 4 | fewer | no estimate | no | Counts folds, not performance or stability |
| 14 | `probability_of_profit` | P ≥ 0.65 | below | no estimate | no | Effectively a base-rate gate if the model has no skill |
| 15 | `expected_net_return` | model bin mean − round-trip cost ≥ 5 % | below | no estimate / costs unknown | no | Bin mean from a tiny pooled sample; 5 % over 20 days is a high bar |
| 16 | `edge_vs_benchmark` | net − benchmark ≥ 3 % | below | net unknown | no | Benchmark return is a **configured 12 % a year constant**, not data |
| 17 | `trade_plan` | stop < entry < target; horizon within bounds | otherwise | — | no | — |
| 18 | `reward_risk` | net-of-cost R:R ≥ 2.0 | below | costs unknown | no | Correct arithmetic |
| 19 | `liquidity` | ADTV ≥ minimum | below | unknown | no | — |
| 20 | `participation` | order ≤ max % of ADTV | above | ADTV unknown | yes | — |
| 21 | `spread` | **quoted spread ≤ max** | above | spread not supplied | yes | **The number comes from the requester (§6.3 A)** |
| 22 | `position_sizing` | qty ≤ min(risk-per-trade cap, 10 % of equity, vol-target/Kelly cap) | above | equity/vol unknown | no | Arithmetic is correct; uses stop distance without a gap allowance |
| 23 | `portfolio_limits` | all post-trade limits pass | any fails | not evaluated | no | Only for buys with known equity |
| 24 | `loss_limits` | daily/weekly/drawdown within limits | breached | history unknown | no | — |

Position-sizing arithmetic verified by reading: `floor(equity × risk_per_trade ÷ (entry − stop))`, `floor(equity × max_order_fraction ÷ entry)`, plus volatility-target or fractional-Kelly caps, minimum taken. Kelly uses `f = p − (1 − p)/rr` with the net R:R and a fraction cap; correct.

### 6.3 Confirmed defects and bypass scenarios

**A. Spread gate trusts the requester *(executed)*.** `TradeProposal.quoted_spread_bps` is supplied in the request. No live quote source exists (broker is `UnavailableBroker`), so this value is always human-typed. I evaluated an otherwise identical approved buy with the spread set to `None / 5 / 1 / 0`:

```
spread=None → REJECTED (spread: UNKNOWN)      round-trip cost 0.4532 %
spread=5    → APPROVED                        round-trip cost 0.4432 %
spread=1    → APPROVED                        round-trip cost 0.4032 %
spread=0    → APPROVED                        round-trip cost 0.3932 %
```

The value both passes gate 21 and **lowers the cost** that gates 15, 16 and 18 use. The class docstring says "every number that matters is re-derived or checked by the engine"; this one is not.

**B. Automatic exit proposals are always rejected *(executed)*.** `paper/service.py:monitor()` builds exit proposals with no `quoted_spread_bps`. Gate 21 applies to exits (`applies_to_exits=True`) and returns UNKNOWN:

```
exit as built by monitor()  → REJECTED  failed=['spread']
exit with spread typed in   → APPROVED
exit, unlicensed prices     → REJECTED  failed=['data_licensed']
```

So a stop-loss "exit suggestion" can never be ordered without a human typing a spread into a fresh proposal, and with unlicensed prices an exit can never be approved at all. The fail-closed rule is applied to *risk-reducing* trades; the design comment ("risk-reducing trades are never blocked by profitability rules") is only half-true. The accompanying test `test_monitor_flags_stop_and_suggests_an_exit` asserts `exit_decision in ("APPROVED", "REJECTED")`, so **it cannot detect this**.

**C. Research report age uses `created_at` (§5.1).** *(code reading)*

**D. Licensing gate omits benchmark inputs (§4.3).** *(code reading)*

**E. Order-time concurrency window (low).** `place_order` re-checks all gates **before** taking the portfolio row lock (`ts.submit(...)` then `select … with_for_update()`). After the lock it re-checks only "decision already used" and cash. Two concurrent orders from *different* decisions on the same portfolio could each pass the sector/position limits computed before the lock. Cash is protected; limit breadth is not. *(code reading)*

**F. Audit trail integrity.** `audit_logs` has `BEFORE UPDATE/DELETE` and `TRUNCATE` triggers (`alembic/versions/0001_foundation.py:62-83`); market data, agent outputs, financials and others have immutability triggers (0002, 0003, 0004, 0005). That blocks the application and ordinary SQL, **but not a database owner who drops the trigger, and there is no hash chain or external anchor**, so deletion by a privileged actor is undetectable. The `decision_hash` is an unkeyed sha256: whoever can write the table can recompute it. Appropriate for a single-operator paper system; insufficient for an independent audit.

**G. What I checked and found sound.** Kill-switch fail-closed reads; UNKNOWN never approved *(executed: all-unknown context rejects 24/24)*; research mode cannot place orders (gate 2 + `place_order` requires `prop.mode == "paper"`); idempotency key + request hash; a re-check decision cannot itself be ordered; stale decisions refused; `AdminUser` required to order; `GateResult` status is a closed Literal (an unexpected status string raises rather than passing).

---

## 7. Phase 7 — Quantitative validation: assessment and design

### 7.1 What exists today

* Prediction metrics computed per fold and pooled: AUC, Brier, log-loss, ECE, base rate, calibration curve (`walkforward.metrics`, `calibration_curve`). **Implemented.**
* Simulation: top-k equal weight, non-overlapping, costs deducted, no-trade periods allowed; CAGR, volatility, Sharpe, max drawdown, win rate vs benchmark (`simulate.py`). **Implemented.** Missing: Sortino, profit factor, turnover, confidence intervals, and a benchmark that is **risk-matched**.
* Reliability: no unsafe-trade-acceptance or gate-bypass measurement; no fault injection.

### 7.2 What can be done with historical data versus what needs live paper trading

| Test | Historical? | Notes |
|---|---|---|
| Walk-forward AUC / Brier / ECE | yes | exists |
| **Baseline comparison** (base rate, momentum rule, logistic regression, buy-and-hold NIFTY) | yes | missing; the single most important addition |
| Brier skill score and bootstrap CI (block bootstrap over dates to respect overlap) | yes | missing |
| Stability across folds / regimes | yes | folds stored; aggregation missing |
| Ablation of each agent in the stance (does removing technical/fundamental change forward returns?) | partly | fundamentals lack true point-in-time history; news cannot be back-tested at all (no historical headlines) |
| Cost sensitivity (cost ×0, ×1, ×2, ×3) | yes | easy |
| Survivorship-bias repair | needs data | requires a delisted-inclusive universe; the licensed bhavcopy archive may allow it |
| Stress tests (2008-style, 2020 crash, 2022 drawdown) | partly | history length limits this (licensed data starts 2021-09) |
| Gate-bypass fuzzing and fault injection | yes | pure engine + hypothesis; a property test file already exists for gates |
| Reproducibility (replay a stored decision, compare hash) | yes | needs the `generated_at` fix |
| Live calibration decay, slippage vs simulated fill | **no — needs weeks/months of paper trading** | monitoring code exists; needs ≥100 matured predictions |
| Real execution quality, spreads, rejections | **no** — needs a broker/live quote feed | outside the current build |

### 7.3 Metrics to add

Prediction: Brier skill score, log-loss improvement over base rate, quantile-bin reliability, AUC with block-bootstrap CI, per-fold dispersion. Trading: net CAGR, Sortino, profit factor, turnover, average cost per trade, benchmark-relative information ratio, beta-adjusted alpha, worst-fold drawdown. Reliability: unsafe-approval rate under perturbed contexts (target 0), gate-bypass rate under fuzzing (target 0), UNKNOWN-handling accuracy, replay-hash match rate (target 100 %), audit-completeness check (every approved order has a proposal, decision, re-check and audit rows).

---

## 8. Phase 8 — Do we need more agents?

**First answer: no new agents until the existing ones are validated.** The current problems are that the existing agents' outputs have not been shown to carry information and that the single trained model sits outside the agent architecture. Adding agents multiplies unvalidated hand-set weights.

| Proposed agent | Problem it solves | Does the current design already cover it? | Verdict |
|---|---|---|---|
| Data Quality / Data Freshness | Detecting bad or stale data | **Yes** — `market_data/validation.py`, `freshness.py`, gates 5–7 | Don't add. Possibly add benchmark-feed licensing/freshness to the existing checks |
| Corporate Actions | Splits, bonuses, dividends | **Yes** — `market_data/adjustments.py`, NSE corporate-action ingestion | Don't add; audit the adjustment code instead |
| Market Regime | Context | Partly — `analysis/regime.py`, `macro.current_regime`; used only as a label | A function, not an agent. Use it as a *conditioning variable in the validation*, not as a new voter |
| Anomaly Detection | Price/volume outliers | Partly — validation flags bad bars | Function inside validation, if needed |
| Adversarial Research Critic (LLM) | Challenge the bull case | Not covered | **Optional and low priority.** If built: LLM may only *annotate* and *lower* confidence/raise warnings, never raise a stance or touch a gate; deterministic checks must be the authority |
| Independent Portfolio Risk | Second opinion on limits | Covered by gate 23 / `portfolio/service.py` | Don't add; two implementations drift |
| Execution Simulation | Fill realism | Partly — `paper/broker.py` with adverse-fill model | Improve the function; no new agent |
| Model Monitoring | Drift and decay | **Yes** — `monitoring/service.py`, scheduled daily | Don't add; tighten the UNKNOWN handling |

Net: **zero new agents recommended now.** The measurable gains are in validation and in correcting the gates.

---

## 9. Phase 9 — Prioritised roadmap (proposal only; nothing approved or implemented)

Each task: files, why, approach, benefit, risk, tests, acceptance. I am keeping changes small and targeted. **No threshold is loosened by any item below.**

### P0 — Correctness, safety, integrity

**P0-1. Make the spread gate not trust the requester.**
Files: `trade/gates.py` (`_spread`, `_ensure_costs`), `trade/context.py`, `trade/schemas.py`.
Why: §6.3-A. Approach: treat `quoted_spread_bps` as *untrusted input*; the engine uses `max(supplied, configured_half_spread×2)` for costs, and gate 21 stays UNKNOWN unless a spread comes from a recorded, timestamped source (a stored quote record or an explicitly attested field with the attester's user id and a maximum age). Benefit: cost model and gate can no longer be lowered by typing. Risk: until a quote source exists, entries still need a human attestation — that is honest. Tests: hypothesis test that costs are non-decreasing in "claimed tightness"; spread 0/1/5 cannot reduce cost below the configured schedule. Acceptance: probe in §6.3-A no longer lowers cost below the configured floor.

**P0-2. Make exit proposals evaluable.**
Files: `trade/gates.py` (`applies_to_exits` for `spread`; `data_licensed` for exits), `paper/service.py:monitor`.
Why: §6.3-B. Approach: for **risk-reducing exits** replace the spread hard-gate with the configured conservative spread assumption, labelled in the decision, keeping kill switch, mode, instrument, freshness, quality and the **licensing** rule as they are *or* documenting a separate paper-only exception — this needs your decision because it changes a safety rule. Tests: replace the `in ("APPROVED","REJECTED")` assertion with an exact expectation; add a test that a monitor-built stop exit is APPROVED under licensed fresh data. Acceptance: a stop-hit thesis yields a reviewable APPROVED exit.

**P0-3. Research-report gate must use the report's own `as_of`/`knowledge_at`.**
Files: `trade/context.py`, `trade/gates.py:_research_report`, `orchestrator/service.py`. Approach: add `report_as_of` to the context and gate; FAIL if `proposal_as_of − report.as_of > max_report_age_hours` or `knowledge_at` is later than the report's creation. Tests: report created now with a month-old `as_of` must FAIL gate 9. Acceptance: that case rejected.

**P0-4. Extend the licensing gate to model inputs.**
Files: `backtest/registry.py:predict`, `trade/probability.py`, `trade/context.py`, `trade/gates.py:_data_licensed`. Approach: have `predict` return the licence status of every input series (stock and benchmark); gate 5 fails if any is unlicensed. Tests: licensed stock + unlicensed benchmark ⇒ FAIL. Acceptance: that case rejected. (Dependency: a licensed NIFTY 50 index source, or accept that the model is research-only until one exists.)

**P0-5. Fail closed on monitor UNKNOWN and on never-monitored models.**
Files: `backtest/registry.py:monitor_blocked/estimate`, `monitoring/service.py`. Approach: an active model with no monitor run, or whose latest run is UNKNOWN for more than N days, yields no estimate (UNKNOWN at gates 12–16). Risk: a freshly activated model is unusable until the first monitor run — acceptable and explicit (run monitoring on activation). Tests: new model without monitor run ⇒ `estimate() is None`.

**P0-6. Fix clock-dependent tests.**
Files: `tests/test_news.py`, `tests/test_fundamentals.py`, plus a shared clock fixture. Approach: freeze "now" (e.g. `freezegun`/dependency override of `get_now`) instead of `datetime.now`. Acceptance: full suite green on any date. *(Executed finding: 2 failures today.)*

**P0-7. Replace the weak exit test assertion** (part of P0-2).

### P1 — ML validity and data reliability

**P1-1. Baseline and skill requirement.** Files: `backtest/walkforward.py`, `backtest/service.py`, `models/backtest.py` (+ migration), `trade/probability.py`, `trade/gates.py`. Add base-rate, momentum and logistic baselines; Brier skill score and block-bootstrap AUC CI per fold; store them on `ModelVersion`; add a gate (or activation criterion) requiring skill > 0 with CI excluding 0 and stability across folds. *Acceptance: the §4.2 no-skill model is rejected.*

**P1-2. Activation criteria.** `api/routes/backtest.py:activate`, `backtest/service.set_status`: refuse activation when OOS ECE > gate maximum, skill criteria unmet, folds < minimum, or `survivorship_bias == "HIGH"` unless an explicit, audited override with a written reason is supplied.

**P1-3. Survivorship repair.** Build the universe point-in-time (include delisted names from the licensed archive); mark `survivorship_bias` accordingly. Requires data.

**P1-4. Universe breadth.** The model is trained on a handful of names. Widen the research universe (licensed, liquid NSE names) before drawing any conclusion about skill.

**P1-5. Regime and fold-stability report.** Aggregate fold metrics by market regime (`analysis/regime.py`) and report the worst fold.

**P1-6. News agent decision.** Either ship the ML build for the News agent (memory/size implications on Railway's 1 GB plan, which is why `AEGIS_ML=0` was recommended) or set its weight to 0 and show it as "not active" in the UI; replace hard-coded `data_quality=0.8`; add entity-relevance filtering and the `published_at ≤ retrieved_at` check.

### P2 — Agent quality and orchestration

**P2-1. Remove `generated_at` from report hashing** (or hash a canonical subset) and add a *replay* endpoint that recomputes a stored report from its `knowledge_at` and compares scores. Files: `orchestrator/service.py:_hash`, `agents/base.py`.
**P2-2. Separate "risk acceptability" from "return tilt"** in the stance: risk becomes a constraint (veto), not a score averaged into a tilt. Needs your decision, since it changes the stance semantics.
**P2-3. Ablation harness** to test each agent's marginal predictive value on historical data where point-in-time data exists (technical, risk, macro market series).
**P2-4. Run agents with a per-agent timeout and a structured `UNKNOWN`-equivalent status;** keep the current four statuses but document `UNKNOWN ≡ non-OK`.
**P2-5. Place the order-time lock before the re-check** (§6.3-E).
**P2-6. Audit hardening:** add a hash chain over `audit_logs` and `trade_decisions` (each row stores the previous row's hash) and a periodic export of the head hash; key the `decision_hash` with an HMAC held outside the database.

### P3 — Advanced intelligence and optimisation
Fit (not assert) agent weights and category weights walk-forward; learn sector sensitivities; event extraction from NSE/BSE announcements; calibrated agent confidence by mapping confidence to realised hit rates.

### P4 — Optional research
Sentiment fine-tuning on Indian headlines; LLM "critic" that can only add warnings; regime-conditional models; cross-sectional ranking objective instead of binary profit.

---

## 10. Exact test plan (what I would run, and what "pass" means)

1. **Green baseline:** `pytest -q` = 0 failures on any date (needs P0-6).
2. **Gate properties (hypothesis, pure engine):** for random contexts, if any input is `None` then decision is REJECTED; adding information never turns FAIL into PASS; spread claim cannot reduce total cost; exits obey the rules decided in P0-2.
3. **Gate mutation tests:** for each of the 24 gates, flip its input to FAIL and to UNKNOWN and assert REJECTED with that gate named.
4. **Replay test:** store a report and a decision, re-run from stored inputs, assert identical scores and identical canonical hash.
5. **ML baselines (historical):** compare to base rate, momentum, logistic regression; require Brier skill > 0 with block-bootstrap CI excluding 0 on pooled OOS and on ≥ 70 % of folds.
6. **Cost sensitivity:** repeat the simulation at cost ×0/×1/×2/×3; the strategy must keep positive net edge at ×2 to be considered robust.
7. **Fault injection:** kill Redis, drop the benchmark series, corrupt a model artifact byte, stale-date a bar, return malformed RSS; assert fail-closed behaviour each time.
8. **Paper-trading validation (live, weeks):** log every prediction; after ≥100 matured predictions compare live ECE/Brier skill with backtest; compare simulated fills with next-day actual prices.

---

## 11. Security and reliability findings (summary)

Sound: Argon2id password hashing; JWT with audience, expiry and a server-side `ver` revocation counter; forced password change gating; admin-only order approval and model activation; rate limiting that fails closed; append-only audit triggers; kill switch that reads fail-closed; live trading impossible by build constant.
To address: no MFA; no four-eyes separation; unkeyed hashes and no hash chain (§6.3-F); in-process model cache keyed by artifact hash (fine) but `FinBert`/`MiniLM` download from the internet at runtime; unlicensed data sources (Yahoo, Google RSS) are research-only by design but are the **default** feed on the current deployment; **HTTP-layer security and the frontend were not audited in this pass.**

## 12. Missing capabilities (honest list)

Baselines and skill tests; survivorship-free universe; licensed index data; a quote/spread source; real news archive for back-testing; true point-in-time fundamentals; confidence calibration for agents; regime-aware validation; any evidence of out-of-sample profitability; a replay tool; an ablation harness.

## 13. Overall project maturity assessment

| Dimension | Assessment |
|---|---|
| Engineering quality (typing, lint, tests, migrations, CI) | **High** — ruff/mypy clean; 371/374 tests pass; CI exists |
| Safety architecture | **High** — fail-closed pervasive; live trading off; human approval enforced |
| Gate correctness | **Medium-high** — three real defects (spread trust, report time, licensing scope) plus broken exits |
| Data reliability | **Low-medium** — default feeds are unlicensed Yahoo/Google; fundamentals have estimated availability |
| ML validity | **Low-medium** — leakage controls are good; no baseline, no skill gate, tiny universe, survivorship HIGH |
| Agent intelligence | **Low** — six rule-based agents with unvalidated hand-set weights; one pretrained model, absent in the documented deploy |
| Evidence of predictive skill | **None in the repository.** Absence of evidence, not evidence of absence |
| Explainability/auditability | **High** — bull/bear points, evidence refs, per-gate reasons, snapshot hashes (hash-chain and replay are the gaps) |

**Bottom line:** AEGIS can credibly be presented today as *a rigorous, safety-first research and paper-trading platform*. It cannot yet be presented as *an AI system that finds profitable trades*, because nothing in the repository demonstrates that. The roadmap above (P0 correctness first, then baselines and skill gates in P1) is the shortest path to being able to either show that evidence or show clearly that it is absent.

---

## Appendix A — Commands and results (all executed 30 Oct 2026)

```
pytest -q                       → 2 failed, 371 passed, 1 skipped in 148.14s
   FAILED tests/test_fundamentals.py::test_agent_ok_now_but_blind_in_the_past   (KeyError 'pe')
   FAILED tests/test_news.py::test_news_agent_is_sourced_and_point_in_time      (insufficient_data)
   cause: both call datetime.now() against fixtures dated Sep 2026; news lookback is 30 days
ruff check .                    → All checks passed!
ruff format --check .           → 191 files already formatted
mypy app                        → Success: no issues found in 146 source files
```

Probe script (read-only, outside the repo): `/tmp/claude-0/audit/exp/probe.py` — evaluates the pure gate engine with the repository's own test context. Environment: Python 3.13, Postgres 16 + pgvector, Redis, dependencies from `pyproject.toml` `[dev]`.

## Appendix B — Not yet audited

`market_data/validation.py`, `adjustments.py`, `service.py` (705 lines); internals of Fundamental/Macro/Valuation/Portfolio/Risk scoring beyond structure; `ranking/service.py`; `core/http_security.py`, `core/rate_limit.py`; all of `frontend/`; Alembic migration correctness beyond the passing migration test; the production database and any real backtest/model records.

## Decision requested

Nothing has been implemented. Before Phase 10, please tell me:

1. **Approve / reorder the roadmap** (or strike items).
2. **P0-2:** may exits use a configured conservative spread assumption (a change to a safety rule), or do you want exits to stay fully manual?
3. **P2-2:** do you want risk to become a veto rather than a scored vote in the stance?
4. **P1-6:** News agent — enable the ML build in production, or switch the agent off and show that honestly?
5. Do you want me to continue the audit into Appendix B first (about one more pass), or start on P0?
