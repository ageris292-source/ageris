# Aegis

A multi-agent stock research, backtesting and risk-gated trading platform.

Aegis is built to answer one question: *is there enough validated evidence
that this opportunity has positive risk-adjusted expected value after costs,
uncertainty and portfolio constraints?* If the answer is no or unknown, the
answer is **NO TRADE**. Aegis produces model-based estimates, not guarantees
of profit.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Foundation: API, DB, migrations, config, auth, kill switch, Docker, CI, UI shell | **Done** ([report](docs/phase-1-report.md)) |
| 2 | Market data (NSE/BSE): providers, validation, versioned storage, stock pages | **Done** ([report](docs/phase-2-report.md)) |
| 3 | Technical analysis agent (indicators, signals, feature store) | **Done** ([report](docs/phase-3-report.md)) |
| 4 | Fundamental agent (statements, ratios, bank-aware scoring) | **Done** ([report](docs/phase-4-report.md)) |
| 5 | News agent, FinBERT sentiment, document search (RAG) | **Done** ([report](docs/phase-5-report.md)) |
| 6 | Macro agent, market regime, valuation agent (DCF scenarios) | **Done** ([report](docs/phase-6-report.md)) |
| 7 | Risk agent, portfolios, exposure/correlation checks, portfolio-fit agent | **Done** ([report](docs/phase-7-report.md)) |
| 8 | Orchestrator, bull/bear synthesis, immutable research reports | **Done** ([report](docs/phase-8-report.md)) |
| 9 | Trade Risk Engine: 24 ordered gates, cost model, sizing, immutable decisions | **Done** ([report](docs/phase-9-report.md)) |
| 10 | Walk-forward backtesting, calibrated LightGBM, reproducibility, model registry | **Done** ([report](docs/phase-10-report.md)) |
| 11 | Paper trading: human approval, pre-order re-check, idempotent orders, fills, theses | **Done** ([report](docs/phase-11-report.md)) |
| 12 | Daily ranking through the engine, no-trade analytics, counterfactuals, alerts (in-app, Telegram, email) | **Done** ([report](docs/phase-12-report.md)) |
| 13 | Model monitoring: PSI drift vs training data (null-calibrated), calibration decay on realised outcomes, auto-disable | **Done** ([report](docs/phase-13-report.md)) |
| 14 | Security: global rate limits, request size limit, security headers, CORS fixes, production config checks; deployment (Caddy/TLS compose, runbook) | **Done** ([report](docs/phase-14-report.md), [deployment guide](docs/deployment.md)) |
| 15 | Live-trading scaffolding: broker adapter interface, disabled by a build switch; tests prove live orders cannot be placed | **Done** ([report](docs/phase-15-report.md)) |
| Web app | Redesigned console: light/dark themes, sidebar + ⌘K search, dashboard, watchlist, tabbed stock research, guided trade flow, team invites with forced password change | **Done** ([guide](docs/web-app.md)) |

Market scope: **Indian equities only** (NSE `.NS`, BSE `.BO`).

Live trading is **not available** in this build: a code-level switch
(`LIVE_TRADING_AVAILABLE = False`) and the only broker adapter
(`UnavailableBroker`) both refuse, so execution readiness reports `live_build`
FAIL and `broker_health` UNKNOWN, and `POST /live/orders` always answers 503. Every trade
proposal must pass all 24 gates of the deterministic Trade Risk Engine.

## Safety defaults

- `AEGIS_SYSTEM_MODE=research` by default. Research mode can never place orders.
- `AEGIS_LIVE_TRADING_ENABLED=true` is rejected at startup unless mode is `live`.
- Demo data is rejected with live mode and in production.
- A fresh install starts with the **kill switch active**. Any user may halt;
  only an admin may resume, and resuming never enables trading on its own.
- Every threshold lives in [`config/aegis.yaml`](config/aegis.yaml), is strictly
  validated at boot (unknown keys, bad ranges and inconsistent limits abort),
  and its SHA-256 fingerprint is written to every audit record.
- `audit_logs` is append-only, enforced by a database trigger.

## Quick start (Docker)

```bash
cp .env.example .env
# set POSTGRES_PASSWORD and AEGIS_JWT_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
docker compose exec backend python -m app.cli create-user --email you@example.com --role admin
```

- API: http://localhost:8000 (OpenAPI docs at `/docs`)
- UI: http://localhost:3000

## Production

See **[docs/deployment.md](docs/deployment.md)**: `docker-compose.prod.yml` (Caddy with
automatic TLS; database and Redis not exposed), the startup safety checks for
`AEGIS_ENV=production`, and `python -m app.cli check-deploy`.

## Local development

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
cd backend
export DATABASE_URL=postgresql+psycopg://aegis:aegis@localhost:5432/aegis
export AEGIS_JWT_SECRET=...   # 32+ chars
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --reload
../.venv/bin/celery -A app.scheduler.celery_app worker --beat

cd ../frontend && npm install && npm run dev
```

### Tests

Tests run against real PostgreSQL and Redis (defaults: `aegis_test` database,
Redis DB 15):

```bash
cd backend
../.venv/bin/pytest            # 350 tests
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/mypy app
```

## Layout

```
backend/     FastAPI app, SQLAlchemy models, Alembic migrations, Celery, tests
config/      aegis.yaml: trade gates, freshness, risk limits, sizing, costs
frontend/    Next.js + Tailwind web app (see docs/web-app.md)
docker/      Dockerfiles
docs/        Phase reports and design notes
```

Directories for agents, pipelines, models and backtesting are created by the
phase that first implements them, not as empty placeholders.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | DB/Redis health, mode, version |
| POST | `/auth/token` | none | Login (rate limited, audited) |
| GET | `/auth/me` | user | Current user (also reachable with a temporary password) |
| POST | `/auth/change-password` | user | Replace your password; revokes older sessions, returns a fresh token |
| GET, POST | `/users` | admin | List users; invite one (returns a one-time temporary password) |
| PATCH | `/users/{id}` | admin | Change role or deactivate/reactivate (never the last admin, never yourself) |
| POST | `/users/{id}/reset-password` | admin | Issue a new temporary password; signs the user out |
| GET, POST | `/watchlist` | user | Your watchlist with last close, day change, sparkline, latest stance |
| DELETE | `/watchlist/{ticker}` | user | Remove from your watchlist |
| GET | `/risk/status` | user | Execution readiness, kill switch, config fingerprint |
| POST | `/trading/kill-switch` | user / admin | Halt (any user) or resume (admin only) |
| GET | `/stocks` | user | Universe with freshness, last close, day change and 30-session sparkline |
| POST | `/stocks` | admin | Add `TCS.NS` / `RELIANCE.BO` |
| GET | `/stocks/{ticker}` | user | Latest bar, provenance, data quality, corporate actions, runs |
| GET | `/stocks/{ticker}/prices` | user | `basis`, `start`, `end`, point-in-time `as_of` |
| POST | `/stocks/{ticker}/ingest` | user | Fetch/refresh daily bars (validated, versioned, audited) |
| POST | `/stocks/{ticker}/import-csv` | admin | Import licensed/official CSV with declared source + basis |
| GET | `/data/providers` | user | Provider availability and licensing |
| GET | `/technical/{ticker}` | user | Run + record the technical agent (`as_of`, `knowledge_at` for exact replay) |
| GET | `/technical/{ticker}/indicators` | user | SMA/RSI/MACD/Bollinger chart series (with warm-up) |
| POST | `/ranking/run` | admin | Rank the universe through the Trade Risk Engine (records only, never orders) |
| GET | `/ranking/latest`, `/ranking/history` | user | Latest ranking with rows; ranking history |
| GET | `/ranking/counterfactuals` | user | Realised forward returns by qualified / first blocking gate |
| GET | `/alerts` | user | Alerts with unread count (`unread_only`, `limit`) |
| POST | `/alerts/{id}/read`, `/alerts/read-all` | user | Mark alerts read (audited) |
| GET | `/alerts/channels` | user | In-app / Telegram / email availability |
| POST | `/monitoring/run` | admin | Log predictions, check drift + calibration decay, retire a failing model |
| GET | `/monitoring/overview`, `/monitoring/runs`, `/monitoring/runs/{id}` | admin | Latest check per model, history, full detail |
| GET | `/live/status` | user | Why live trading is unavailable (build switch, adapter, readiness) |
| POST | `/live/orders` | admin | Always refused (503) in this build; audited and alerted |

Data from the Yahoo adapter is **unlicensed and research-only**; it is tagged as
such on every stored bar.

The technical score (0–100, 50 = no tilt) is a descriptive composite, **not a
probability of profit**, and its "signal agreement" is an uncalibrated heuristic
until the backtester (Phase 10) can calibrate it.
