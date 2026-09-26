# Phase 8 Report: Bull/Bear Synthesis, Orchestrator, Research Reports

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Orchestrator** (`POST /analysis/{ticker}`):
  - Runs the technical, fundamental, valuation, risk, news and macro agents, plus the portfolio agent when a `portfolio_id` is given.
  - All agents use **one shared `as_of` and `knowledge_at`**, so the report is a consistent point-in-time snapshot and can be replayed.
  - One agent failing never aborts the others; the failure is recorded in the report.
  - Each report links to the exact agent-run ids it used.
- **Deterministic bull/bear synthesis** (`app/orchestrator/synthesis.py`, a pure function):
  - **Composite:** a weighted mean of the usable agent scores, with weights re-normalised over the agents that produced a result. Weights live in the config (`orchestrator.agent_weights`) and must sum to 1.
  - **Research stance:** POSITIVE_TILT (≥ 60), NEGATIVE_TILT (≤ 40), or NO_CLEAR_TILT. It is **INSUFFICIENT_DATA** when a required agent (risk) has no result or fewer than 4 agents are usable.
  - **Bull and bear cases:** directional signals ranked by strength × agent weight, each with its evidence reference.
  - **Conflicts:** two agents more than ±12.5 points either side of 50. Each conflict costs a 15% multiplicative confidence penalty.
  - Also lists de-duplicated key risks, what would change the view (invalidation conditions), and data and licensing warnings.
  - **The decision is always "NO TRADE".** The stance is a research summary. Only the Phase 9 Trade Risk Engine can approve a trade.
- **Narrative:**
  - The default is a deterministic template.
  - An optional **LLM narrator** (Anthropic Messages API, enabled by `AEGIS_LLM_API_KEY`) may only rephrase the finished report, at temperature 0.
  - Its output is **rejected** if it contains any number not in the facts, uses buy/sell/target language, or is empty. The deterministic text is used instead, with a warning.
  - No key is configured, so `/narrator/status` reports it as unavailable.
- **Immutable reports** (migration 0008, table `analysis_reports`, protected by an UPDATE/DELETE trigger):
  - The full JSON is stored with a SHA-256 content hash, and reads report `hash_verified`.
  - Every report is audited (`analysis.report`).
  - Endpoints: `GET /analysis/{t}/latest`, `/analysis/{t}/history`, `/reports/{id}`, and `/reports/{id}/markdown`.
  - The markdown download has 13 sections: decision, stance, agents, bull, bear, conflicts, valuation, risk, regime, risks, invalidation, data provenance, summary.
- **UI:** a **Research report** panel at the top of each stock page. It shows the decision, stance, composite and confidence; the agent table; bull and bear columns; conflicts; key risks; the summary; and a hash/verification footer. Includes a "Download .md" button.

## Tests
10 new tests; 242 in total, plus ruff and mypy all clean.
- Stance thresholds; INSUFFICIENT_DATA when a required agent is missing or too few agents are usable.
- Weight re-normalisation matches a hand calculation; coverage.
- Bull/bear ordering and evidence references; conflict detection and the confidence penalty; risk de-duplication.
- **Property test** (100 cases): the synthesis is deterministic, the composite stays in [0, 100], the stance matches the composite, the decision is always NO TRADE, and a missing risk agent always gives INSUFFICIENT_DATA.
- Narrative guard: invented numbers and buy/sell language are rejected. With a mocked LLM, valid text is accepted; an invented "30% gains" and an HTTP 500 both fall back to the deterministic text.
- End-to-end:
  - All agents share one point in time and are linked to their runs.
  - Missing financials fail closed.
  - The hash is verified; latest, history and markdown endpoints work.
  - **UPDATE on a stored report is rejected by the database.**
  - A portfolio-fit run; a missing portfolio gives 404; a timestamp without a timezone gives 422; every endpoint requires authentication.

## Live run (real data, 2026-09-26)
| Stock | Stance | Composite | Confidence | Conflicts |
|---|---|---|---|---|
| TCS | No clear tilt | 47.0 | 0.37 | fundamental 72 vs technical 30; fundamental 72 vs valuation 27 |
| Reliance | No clear tilt | 46.8 | 0.38 | — (valuation: insufficient data) |
| HDFC Bank (with portfolio fit) | No clear tilt | 46.2 | 0.19 | — |

All three: **NO TRADE**. The whole run of every agent takes about 1 second per stock.

## Limitations
- Stance thresholds and agent weights are starting defaults, not calibrated. Calibration comes in Phase 10.
- The LLM narrator is untested against the live API because no key is configured.
- Evidence links point to snapshots and runs, not to rendered source documents.
