# Phase 11 Report: Paper Trading

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Order flow** (the only path to a paper position): proposal → Trade Risk Engine **APPROVED** → **human approval** → **pre-order re-check** → simulated fill.
  - `POST /paper/orders` takes `{decision_id}` plus a required **`Idempotency-Key`** header (8–128 characters, `[A-Za-z0-9_-]`).
  - The approver must have the configured role (`admin`), and every approval is audited.
  - **Refused (409)** when the decision:
    - is REJECTED;
    - is older than `max_decision_age_minutes` (60);
    - was already executed;
    - is itself a pre-order re-check.
  - The same key sent for a different request is also refused (409).
  - **Idempotency:** replaying the same key returns the original order (HTTP 200, `replayed: true`) with no second fill. A unique constraint catches concurrent duplicates.
  - **Pre-order re-check:** the engine re-evaluates all 24 gates on fresh data and records a new decision linked to the order. If anything changed (for example, the kill switch was pulled), the order is stored as REJECTED with the failing gates.
  - The portfolio row is **locked** (`SELECT … FOR UPDATE`), and "decision already used" is checked again under the lock, so concurrent orders can't double-spend or double-fill.
- **Simulated broker** (`reference_close_plus_costs`):
  - The fill is the latest available close moved **against** the order by slippage + half the spread (the quoted spread if supplied) + size-based market impact. It is never better than the reference price.
  - Immediate-or-cancel: if the fill would be worse than the limit, the order is rejected.
  - Fees are charged in rupees and broken down: brokerage, exchange, regulatory, GST, securities transaction tax, and stamp duty on buys.
- **Positions and P&L:**
  - Buys use weighted-average cost. Sells book **realised P&L** = (fill − average cost) × quantity − fees.
  - Cash is updated to the paisa; long-only is enforced.
  - Every fill records an **immutable execution** (trigger) and an equity snapshot, which feeds the loss-limit gate.
- **Theses:** every entry opens a thesis with stop, target, horizon end (trading days on the XBOM calendar) and the invalidation conditions from its research report.
- **Thesis monitoring** (`POST /paper/monitor`, and daily in `paper_eod`):
  - Flags STOP_HIT, TARGET_HIT, HORIZON_EXPIRED, and STANCE_DETERIORATED (a newer report is negative or insufficient). Each event fires once per session.
  - For stop, target and horizon events it creates an **engine-evaluated exit proposal**. **A human still approves the exit.** Nothing trades automatically.
- **EOD job:** snapshots every paper portfolio and runs the monitor after the price refresh.
- **API:** `POST /paper/orders`, `GET /paper/orders`, `GET /paper/portfolios/{id}` (account, positions, executions, theses, equity curve), `POST /paper/monitor`.
- **UI:** a new **Paper trading** page with the account summary and equity curve, an "awaiting human approval" queue with an **Approve & place paper order** button (admin only; a random idempotency key is generated per click), positions, theses with their events, and orders with fill details. A banner explains that orders are rejected unless the system is in paper mode.
- Migration 0011: `paper_orders`, `paper_executions` (immutable), `theses`, `thesis_events`.

## Tests
7 new tests; 317 in total, plus ruff and mypy all clean.
- Approved → filled, all checked:
  - Only the approver role may order; a missing or malformed key gives 422.
  - The fill is at least the reference and within the limit.
  - Fees add up to the breakdown; cash is exact to the paisa; average cost is correct.
  - A thesis opens with its invalidations, and a snapshot is recorded.
- Idempotency and immutability:
  - A replay returns the same order with no second fill; a second key on an executed decision gives 409; a reused key for another decision gives 409.
  - A re-check decision can't be ordered.
  - Executions can't be UPDATEd.
- **Re-check blocks a change of conditions** (kill switch pulled after approval): the order is REJECTED and no position is opened.
- Rejected decisions and stale decisions (2 hours old) give 409; a missing decision gives 404.
- Exit: the sell passes with entry-only gates marked N/A; the realised-P&L formula and cash are checked; the thesis closes; overselling is rejected at the instrument gate.
- Monitoring: a next-session gap below the stop raises STOP_HIT with an engine-evaluated exit proposal; no duplicate event in the same session; the thesis stays open until a human acts.
- Every endpoint requires authentication.

## Live status (real data)
The sandbox runs in **research mode** with **unlicensed Yahoo prices** and no calibrated model, so real proposals are rejected before approval (gates 1, 2, 5, 10–16). The complete buy → re-check → fill → P&L → monitor → exit cycle is proven end to end on licensed test data in paper mode.

## To run paper trading for real
1. Import **licensed** EOD prices via the CSV endpoint, and set `AEGIS_SYSTEM_MODE=paper`.
2. An admin releases the kill switch.
3. Run a backtest, and activate a model only if it passes calibration and has enough out-of-sample folds.
4. Evaluate proposals on the Trade risk page (include a live quoted spread), then approve them on the Paper trading page.

## Limitations
- Fills use EOD closes; there are no intraday quotes or partial fills.
- Depository charges per sell are not modelled.
- Theses are checked once a day.
