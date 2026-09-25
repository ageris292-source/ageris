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
| 3 | Technical analysis agent | Next |
| 4–15 | Agents, trade risk engine, backtesting, paper trading, … | Planned |

Market scope: **Indian equities only** (NSE `.NS`, BSE `.BO`).

Live trading is **not available** in this build. Execution readiness reports
`broker_health` and `risk_engine` as `UNKNOWN`, which blocks both paper and
live orders by design.

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
../.venv/bin/pytest            # 119 tests
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/mypy app
```

## Layout

```
backend/     FastAPI app, SQLAlchemy models, Alembic migrations, Celery, tests
config/      aegis.yaml: trade gates, freshness, risk limits, sizing, costs
frontend/    Next.js + Tailwind console
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
| GET | `/auth/me` | user | Current user |
| GET | `/risk/status` | user | Execution readiness, kill switch, config fingerprint |
| POST | `/trading/kill-switch` | user / admin | Halt (any user) or resume (admin only) |
| GET | `/stocks` | user | Universe with freshness |
| POST | `/stocks` | admin | Add `TCS.NS` / `RELIANCE.BO` |
| GET | `/stocks/{ticker}` | user | Latest bar, provenance, data quality, corporate actions, runs |
| GET | `/stocks/{ticker}/prices` | user | `basis`, `start`, `end`, point-in-time `as_of` |
| POST | `/stocks/{ticker}/ingest` | user | Fetch/refresh daily bars (validated, versioned, audited) |
| POST | `/stocks/{ticker}/import-csv` | admin | Import licensed/official CSV with declared source + basis |
| GET | `/data/providers` | user | Provider availability and licensing |

Data from the Yahoo adapter is **unlicensed and research-only**; it is tagged as
such on every stored bar.
