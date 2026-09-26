# AEGIS — handoff notes (for continuing in Claude Code)

Date: 2026-09-26

## Where things stand
Phases 1–10 are **done and committed** (see `docs/phase-N-report.md` and the README status table).
Last clean commit: *"Phase 10: walk-forward backtesting…"*.

The latest commit is a **work-in-progress** checkpoint:

- **Phase 11, paper trading.** The code is complete. `tests/test_paper.py` passed (6 tests) before one final test assertion was added: the recheck-decision guard. The report is written: `docs/phase-11-report.md`.
  - `app/models/paper.py`, `app/paper/{broker,service}.py`, `app/api/routes/paper.py`
  - `alembic/versions/0011_paper.py`
  - UI: `frontend/app/paper/page.tsx`
- **Phase 12, ranking + alerts.** In progress. Written so far:
  - Config sections `ranking` and `alerts` (`config/aegis.yaml`, `app/core/config_file.py`), plus alert settings in `app/core/settings.py` (Telegram, SMTP).
  - `app/models/ranking.py` (tables `RankingRun`, `Alert`)
  - `app/alerts/service.py`: in-app alerts, plus Telegram and email channels
  - `app/ranking/service.py`: `run_ranking` (standardised candidate per stock, evaluated by the real Trade Risk Engine; outputs `NO QUALIFIED OPPORTUNITIES TODAY` when nothing passes) and `counterfactuals`

## Next steps for Phase 12
1. Run `ruff format` / `ruff check --fix` / `mypy app` and fix anything they report.
2. Generate migration `0012_ranking`: `alembic revision --autogenerate --rev-id 0012_ranking`. Add an immutability trigger on `ranking_runs` using `market_data_immutable()`, the same way `0011_paper.py` does.
3. In `tests/conftest.py` cleanup, delete from `alerts` and `ranking_runs`. Disable the trigger first for `ranking_runs`.
4. Add `app/api/routes/ranking.py`:
   - `POST /ranking/run` (admin), `GET /ranking/latest`, `GET /ranking/history`, `GET /ranking/counterfactuals`
   - `GET /alerts`, `POST /alerts/{id}/read`, `POST /alerts/read-all`, `GET /alerts/channels`
   - Register it in `app/main.py`.
5. Raise alerts from these places:
   - `paper.monitor` thesis events (STOP_HIT is critical)
   - kill-switch changes (route in `app/api/routes/system.py`)
   - failed ingestions in Celery jobs
6. Add a Celery `daily-ranking` task after `paper-eod`.
7. Write the tests: standardised candidate levels; NO QUALIFIED headline; operational gates vs opportunity gates; alert dedupe; a Telegram channel with an httpx MockTransport where a failure is still stored; counterfactual grouping; auth.
8. UI: `/ranking` page (headline, table, blocking-gate histogram, counterfactuals), an alerts bell with unread count in `Nav`, and an alerts page.
9. Write `docs/phase-12-report.md`, update the README, commit.

## Remaining after Phase 12
- **Phase 13, monitoring:** PSI feature drift against the model's training data, calibration decay on realised outcomes, auto-disable (retire the model and alert), and an admin monitoring page.
- **Phase 14, security + deployment:** global rate limiting, security headers, production config checks, deploy docs.
- **Phase 15, live-trading scaffolding (stays disabled):** a broker adapter interface that reports unavailable, and tests proving live orders can't be placed.
- **Final:** full verification, then upload to GitHub.

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
