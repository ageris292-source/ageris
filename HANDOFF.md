# AEGIS — handoff notes (for continuing in Claude Code)

Date: 2026-09-26 (updated after Phases 12–15)

## Where things stand
Phases 1–15 are **done and committed** (see `docs/phase-N-report.md` and the README status table). Deployment guide: `docs/deployment.md`.

- Phase 11 (paper trading): the WIP checkpoint's tests were re-run and pass, including the recheck-decision guard.
- Phase 12: ranking + alerts, finished as planned. The ranking now refreshes stale reports before evaluating, so new reports are visible to the gates.
- Phase 13: model monitoring. PSI drift is judged against the model's own training windows, because fixed PSI thresholds retire healthy models on autocorrelated features. Calibration decay is measured on logged predictions, with auto-disable.
- Phase 14: rate limits, headers, body limit, trusted hosts, production checks (`python -m app.cli check-deploy`), and the Caddy/TLS production compose. Two CORS bugs from earlier phases were fixed: PUT and `Idempotency-Key` were blocked at preflight.
- Phase 15: the broker adapter interface. `UnavailableBroker` plus the `LIVE_TRADING_AVAILABLE = False` build switch keep live trading disabled; tests prove it.

## Remaining
- **Final:** verify on a host with Docker (`docker compose -f docker-compose.yml -f docker-compose.prod.yml config`, then a TLS smoke test). Then upload to GitHub; that hasn't been done, and no remote is configured.

## Local dev
```bash
service postgresql start; service redis-server start   # or docker compose up db redis
cd backend
export DATABASE_URL=postgresql+psycopg://aegis:aegis@localhost:5432/aegis
export REDIS_URL=redis://localhost:6379/1
export AEGIS_JWT_SECRET=<32+ random chars>
alembic upgrade head
pytest -q            # tests always use the *_test database (enforced in conftest)
ruff check . && mypy app
python -m app.cli ingest TCS.NS RELIANCE.NS …   # real data (Yahoo, research only)
python -m app.cli ingest-macro
cd ../frontend && npm run build
```

## Rules that must not be broken (from the master spec)
- Never invent data. UNKNOWN never passes.
- Point in time throughout: `as_of` and `knowledge_at`.
- The LLM is never the authority on trades; only the 24-gate Trade Risk Engine is.
- Live trading stays disabled. Human approval is required for every order.
- Everything is auditable and reproducible.
- Indian market only (NSE/BSE).
