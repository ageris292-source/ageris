# Phase 15 Report: Live-Trading Scaffolding (Disabled)

Date: 2026-09-26 · Status: complete, all checks green

Live trading **stays disabled**. This phase adds the structure a future live integration would have to fit into. Each safeguard is tested on its own, including when all the others are bypassed.

## Implemented
- **Build switch:** `LIVE_TRADING_AVAILABLE = False` in `app/core/modes.py`.
  - This is code, not configuration; no environment variable or YAML key can change it.
  - Execution readiness has a new **`live_build`** check that always FAILs in this build, so `live_orders_permitted` is always false (and shows on the dashboard).
- **Broker adapter interface** (`app/live/broker.py`):
  - `BrokerAdapter` (status, place/cancel limit orders, order status, positions).
  - `LiveOrderRequest` carries exchange (NSE/BSE), side, quantity, a limit price (no market orders), an idempotency key, the decision and the approving human.
  - The only implementation, **`UnavailableBroker`**:
    - holds no credentials and opens no connections;
    - reports `available: false, healthy: unknown`;
    - raises `BrokerUnavailableError` on every order call.
  - `get_broker()` always returns it; there is no registry or environment selector.
- **Wiring:** the adapter's status feeds `/risk/status` (`broker_health: UNKNOWN`) and the Trade Risk Engine's context. A live proposal therefore gets **UNKNOWN** at gate 2 (`execution_mode`) even in live mode with the flag set.
  - A live proposal also fails `portfolio_match`: the database only allows `model` and `paper` portfolios.
- **The live order path** (`app/live/service.py`, `POST /live/orders`, admin only, `Idempotency-Key` required). It checks:
  - an APPROVED **live** decision that is fresh;
  - an approver with the configured role (**human approval**);
  - execution readiness;
  - only then the adapter.

  In this build every attempt is **refused with 503**, listing every reason. Each refusal is **audited** (`live.order.refused`) and raises an alert. `GET /live/status` explains why live trading is unavailable.
- The earlier safeguards remain:
  - `AEGIS_LIVE_TRADING_ENABLED=true` is rejected outside live mode;
  - demo data is never allowed with live mode;
  - `require_human_approval_for_live=false` is rejected at boot;
  - the paper order path refuses non-paper decisions.

## Tests
8 new tests, plus the readiness property test extended; 350 in total (1 optional-NLP skip), plus ruff and mypy all clean.
- The build switch is off.
- `get_broker()` is the unavailable adapter even with broker environment variables set; every adapter call raises.
- No broker SDK is among the dependencies. A source scan shows only `app/live` reaches a broker (`.place_order(` appears only there and in the paper route, which calls the paper service).
- **Readiness property test (Hypothesis):**
  - For every combination of mode, flag, kill switch, broker and risk-engine status, this build **never** permits a live order.
  - The precondition logic is still checked for a hypothetical build that has an adapter.
  - Even with live mode, the flag, the kill switch off and a healthy broker and engine, the only blocker is `live_build`.
- **Engine:** a live proposal in live mode is REJECTED; `execution_mode` is UNKNOWN because the broker's health is unknown, and `portfolio_match` fails.
- **A live portfolio can't be created,** neither through the API (422) nor by direct SQL (check constraint).
- **Worst case, a forged APPROVED live decision** (simulating an engine defect):
  - `POST /live/orders` gives 503 with the `live_build` and `broker_health` reasons, an audit record and an alert.
  - The paper path refuses it (409), and no order or execution exists.
  - An analyst gets 403, a missing idempotency key gives 422, and an unknown decision gives 404.
- **Every other safeguard bypassed** (readiness forced clear and the build check skipped): the order reaches the adapter exactly once, is refused, and **no network connection is attempted** (socket connect is trapped).
- Both live endpoints require authentication.

## Enabling live trading later (not in scope)
It would require all of the following:
- a reviewed adapter implementation for a licensed broker;
- changing the build switch in code;
- allowing a `live` portfolio kind (a migration);
- a live-quote source for the spread gate;
- a new security review.

Configuration alone can never do it.
