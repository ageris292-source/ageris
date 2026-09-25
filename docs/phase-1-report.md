# Phase 1 Report: Foundation

Date: 2026-09-25 · Status: complete, all checks green

## 1. What was implemented

- **FastAPI backend** with startup validation that stops boot on an invalid environment or configuration.
- **Settings**, read from environment variables with safe defaults: research mode, live trading off, demo data off.
  - A live-trading flag set outside live mode is rejected.
  - Demo data is rejected with live mode and in production.
  - A weak or default JWT secret is rejected.
  - Error messages never repeat input values, so secrets cannot leak into logs.
- **Strict YAML config** (`config/aegis.yaml`) for:
  - trade gates
  - freshness
  - risk controls
  - position sizing
  - liquidity
  - execution
  - per-market transaction-cost schedules

  Validation rules:
  - Unknown keys are rejected, which catches typos.
  - Values are range-checked.
  - Daily ≤ weekly ≤ strategy ≤ portfolio loss limits.
  - Kelly is capped at ≤ 0.5.
  - No leverage.
  - Human approval for live trading cannot be switched off.
  - The config is fingerprinted (SHA-256), and the fingerprint is stored on every audit row.
- **PostgreSQL schema + Alembic migration `0001_foundation`** with these tables: `users`, `audit_logs`, `risk_events`, `trading_controls`.
  - `audit_logs` is append-only: database triggers block UPDATE, DELETE and TRUNCATE.
  - `trading_controls` holds a single row, and a fresh install starts with the kill switch **active**.
- **Auth.** Passwords are hashed with Argon2id and sessions use JWT access tokens (audience-bound, expiring). Login is rate limited through Redis and fails closed if Redis is down. Every login success and failure is audited. There is no public sign-up; users are created with the operator CLI.
- **Kill switch** (`POST /trading/kill-switch`).
  - Any user can halt. Only an admin can resume, and a denied resume is itself audited.
  - Every change writes both an audit row and a risk event. Activation is flagged `requires_review`.
- **Execution readiness** (`GET /risk/status`). This is a system-level precondition check that fails closed:
  - A missing or unreadable kill-switch row counts as active.
  - UNKNOWN never counts as PASS.
  - Broker and risk engine report UNKNOWN until Phases 9 and 15, so **paper and live orders are both blocked in this build**.
- **Celery + Redis**, with a heartbeat task that tests the worker → broker → database path.
- **Next.js console** with login, execution readiness (every check with PASS/FAIL/UNKNOWN), kill switch controls, infrastructure health and the config fingerprint. It shows a "DEMO DATA — NOT FOR TRADING" banner when demo mode is on.
- **Docker setup**: backend and frontend images, and a compose stack with Postgres (pgvector image, ready for Phase 5), Redis, API, worker and UI.
- **GitHub Actions CI**: backend lint, format, mypy (strict) and tests against real Postgres and Redis; frontend build and typecheck.

## 2. Files created

```
.env.example  .gitignore  .dockerignore  README.md  docker-compose.yml
.github/workflows/ci.yml
config/aegis.yaml
docker/backend.Dockerfile  docker/frontend.Dockerfile
backend/pyproject.toml  backend/alembic.ini
backend/alembic/{env.py, script.py.mako, versions/0001_foundation.py}
backend/app/{__init__.py, main.py, cli.py}
backend/app/core/{modes.py, settings.py, config_file.py, security.py, rate_limit.py}
backend/app/db/session.py
backend/app/models/__init__.py
backend/app/schemas/__init__.py
backend/app/api/{deps.py, routes/auth.py, routes/system.py}
backend/app/services/{audit.py, users.py, trading_controls.py}
backend/app/scheduler/celery_app.py
backend/tests/{conftest.py, test_config.py, test_settings.py,
               test_execution_readiness.py, test_api.py, test_migrations.py}
frontend/{package.json, package-lock.json, tsconfig.json, next.config.mjs, postcss.config.mjs}
frontend/app/{layout.tsx, page.tsx, globals.css}  frontend/lib/api.ts
```

## 3. Architecture decisions

- **Synchronous SQLAlchemy 2.0 + psycopg3.** It is simpler to reason about for control-plane code. FastAPI runs sync endpoints in a threadpool. Async can come later for high-fan-out data ingestion.
- **All Python lives in one installable `app` package under `backend/`.** Agents, pipelines and the backtester will be subpackages (`app/agents/...`) instead of separate top-level folders. This avoids `sys.path` tricks and keeps one import root. The spec's top-level folders are created when they get real code.
- **Kill-switch state is kept in Postgres**, not Redis. The database is the durable source of truth, row-locked on change.
- **"Execution readiness" is kept separate from the Trade Risk Engine.** The readiness check answers "could any order be submitted right now?" The per-trade 24-gate engine (Phase 9) answers "may *this* trade proceed?" Both must pass.
- **Rate limiting fails closed.** If Redis is down, login returns 503 instead of letting unthrottled attempts through.

## 4–6. Tests

53 tests, run against real PostgreSQL 16 and Redis:

| File | Covers |
|---|---|
| `test_config.py` (19) | repo config valid; fingerprint stable and change-sensitive; missing, malformed or partial files; 10 out-of-range values; unknown keys; nested loss limits; position vs sector weight |
| `test_settings.py` (11) | safe defaults; weak secrets; live flag outside live mode; demo + live; demo + production; bad mode; missing DB URL; errors never echo secrets |
| `test_execution_readiness.py` (7) | **property tests (Hypothesis)**: live orders are permitted *only if* mode = live, the flag is on, the kill switch is off, broker = PASS and risk engine = PASS; kill switch or any UNKNOWN always blocks; paper mode never permits live orders; research mode never permits anything; fail-closed on a missing or unreadable kill-switch row |
| `test_api.py` (14) | health; 401s; login audit; rate limit (10 then 429); analyst halts but cannot resume; audit and risk-event sequence; resume does not enable trading; empty reason rejected; audit UPDATE/DELETE/TRUNCATE rejected |
| `test_migrations.py` (2) | ORM models match migrations (autogenerate diff is empty); downgrade and upgrade round-trip |

Results: **53 passed**. `ruff check`: clean. `ruff format --check`: clean. `mypy --strict app`: clean. `next build` and `tsc --noEmit`: clean.

Mutation check: removing the `mode is LIVE` requirement and ignoring the kill switch in `trading_controls.py` made the property tests fail, as expected.

End-to-end manual run:
- Migrations ran against a fresh database.
- The operator created an admin user.
- `uvicorn` booted and `/health` was OK.
- Login, then `/risk/status`, showed every order blocked.
- The Celery heartbeat round-tripped through Redis to the database.
- The UI rendered logged in.
- A bad config and a live-flag-in-paper-mode setup each stopped boot.

## 7. Known limitations

- The Docker images and compose stack were **not built** in the development sandbox because no Docker daemon was available. `docker compose config` validates, and the first CI run or local `docker compose up` is the real test.
- No market data yet, so the dashboard has no opportunities, watchlist or regime (Phase 2+).
- The transaction-cost schedule in `aegis.yaml` is an **example** and must be checked against current NSE, SEBI and broker schedules before any paper use.
- No token revocation list. Tokens stay valid until they expire (default 60 min).
- No LICENSE file. The license choice is left to the repo owner.

## 8. Security concerns

- The frontend keeps the JWT in `sessionStorage`. For production, move to httpOnly cookies with CSRF protection (Phase 14).
- CORS is restricted to configured origins, GET/POST only.
- Login rate limiting is keyed by client IP + email. Rate limits on the other endpoints are not in place yet.
- Test cleanup is the only place that disables the audit trigger. It runs only against the `aegis_test` database.

## 9. Data-quality concerns

None yet, because nothing is ingested. Phase 2 must set up `source`, `retrieved_at`, `effective_at`, `published_at` and `data_version` on every stored data point from day one.

## 10. Next phase

**Phase 2: Market Data.**
- A provider adapter interface, with providers marked unavailable when unconfigured.
- An OHLCV + corporate-actions schema that labels series as raw, split-adjusted or total-return.
- Validation for missing candles, duplicates, invalid prices and timestamp errors.
- Freshness tracking and Redis caching.
- `GET /stocks`, `GET /stocks/{ticker}`, and a stock page with a price chart.
