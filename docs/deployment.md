# Deploying Aegis

Aegis is a research and paper-trading platform. **Live trading is not available in this build**, and a production deployment does not change that. What "production" means here is a hardened, internet-facing deployment of the research console and API.

## Topology

```
Internet ──443──▶ Caddy (TLS, HTTP/2, 6 MB body cap)
                    ├──▶ frontend:3000   Next.js console (static + SSR shell)
                    └──▶ backend:8000    FastAPI (rate limits, headers, host check)
                                ├──▶ postgres:5432  (pgvector, not published)
                                └──▶ redis:6379     (password, AOF, not published)
                         worker          Celery worker + beat (EOD jobs, ranking, monitoring)
```

Only Caddy publishes ports (80/443). It obtains certificates automatically for both host names, which must resolve to the server.

## 1. Prerequisites
- A Linux host with Docker Engine and Compose **v2.24+** (the production override uses `!reset`).
- Two DNS names pointing at the host, for example `aegis.example.in` (UI) and `api.aegis.example.in` (API).
- Ports 80 and 443 open. Nothing else needs to be reachable.

## 2. Secrets and environment
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # AEGIS_JWT_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # REDIS_PASSWORD
```
Fill in the **Production** section of `.env`. With `AEGIS_ENV=production`, startup is **refused** unless all of these hold:

| Check | Requirement |
|---|---|
| `AEGIS_CORS_ORIGINS` | https origins only; no localhost and no `*` |
| `AEGIS_ALLOWED_HOSTS` | explicit API host names; no `*` |
| `DATABASE_URL` | a password that is present and not a default |
| `REDIS_URL` | a password that is present and not a default (the prod compose builds it from `REDIS_PASSWORD`) |
| `AEGIS_TOKEN_MINUTES` | ≤ 60 |
| `AEGIS_JWT_SECRET` | ≥ 48 characters |
| `AEGIS_DEMO_DATA` | must be false |
| Live flag | `AEGIS_LIVE_TRADING_ENABLED=true` is refused unless the mode is `live`, which this build cannot trade in |

Error messages name the problem, never the secret value. Keep `.env` out of version control (it is in `.gitignore` and `.dockerignore`).

In production the API also:
- disables `/docs`, `/redoc` and `/openapi.json`;
- sends HSTS;
- rejects unknown `Host` headers.

## 3. Review the configuration
Every threshold is in `config/aegis.yaml`, strictly validated at boot and fingerprinted into every audit record. Before going live:
- `security`: rate limits (per client, 300 requests/min, 60 writes/min), body size, HSTS.
- `alerts`: enable Telegram or email if wanted (`AEGIS_TELEGRAM_*`, `AEGIS_SMTP_URL`, `AEGIS_ALERT_EMAIL_TO`).
- `monitoring`: keep `auto_disable: true`.

## 4. Pre-flight check
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend python -m app.cli check-deploy
```
`check-deploy` prints `FAIL …` for each problem (exit 1) or `OK production checks passed`. It also runs the Trade Risk Engine self-test.

## 5. Start
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
  python -m app.cli create-user --email you@example.in --role admin
```
Migrations run automatically when the backend starts (`alembic upgrade head`).

A fresh install starts in **research mode** with the **kill switch active**. Resuming requires an admin and never enables trading on its own.

## 6. After starting
- `https://api…/health` should report `ok` for the database and Redis. The API container's health check uses the same endpoint.
- Sign in to the UI and check that **Execution readiness** shows research mode and live orders not permitted.
- Load data:
  - `python -m app.cli ingest TCS.NS …`
  - `python -m app.cli ingest-macro`
  - or import licensed CSVs through the API.
- Only licensed data can pass the gates for paper trading.

## Rate limits and client addresses
Limits are per client address. Behind Caddy, the backend sets `AEGIS_TRUSTED_PROXY_HOPS=1` and uses the `X-Forwarded-For` entry **appended by Caddy**. A value supplied by the client is never trusted, so it can't be used to dodge limits.

If you add another proxy layer (a CDN or load balancer), raise the hop count to match. Don't use uvicorn's `--forwarded-allow-ips='*'`: it takes the left-most, client-controlled entry.

The limiter **fails closed**: if Redis is unreachable, API requests get 503 (only `/health` is exempt), in the same way as login.

## Backups and restore
```bash
# nightly (cron on the host)
docker compose exec -T postgres pg_dump -U aegis -Fc aegis > aegis-$(date +%F).dump
# restore into an empty database
docker compose exec -T postgres pg_restore -U aegis -d aegis --clean < aegis-YYYY-MM-DD.dump
```
Most evidence tables are append-only and protected by database triggers (audit log, prices, reports, decisions, executions, rankings, predictions, monitor runs), so a restore is the only way to roll them back. Keep dumps encrypted and off the host.

## Upgrades
1. `git pull`
2. Build (`docker compose … build`).
3. Run `check-deploy`.
4. `docker compose … up -d`. Migrations apply on start; they are forward-only in production.

After an upgrade, read the config fingerprint on the dashboard: every decision records the fingerprint it was made with.

## Incident runbook
- **Stop everything:** any signed-in user can activate the kill switch (dashboard or `POST /trading/kill-switch`). It is audited and raises a critical alert. Only an admin can resume.
- **A model fails monitoring:** it is retired automatically and a critical alert is raised. The engine then rejects every entry for that horizon until an admin activates a healthy model.
- **Ingestion failures:** one alert per job per day lists the failed items. Stale data fails the freshness gate, so nothing trades on it.
- **Rotating a secret:** update `.env` and `up -d`. Rotating `AEGIS_JWT_SECRET` signs everyone out.

## What is not included
- No live broker. The live execution path is permanently unavailable in this build.
- No horizontal scaling of the worker. Run exactly one `worker` (it also runs beat, the scheduler).
- No managed secret store. Use your platform's (for example Docker secrets or Vault) if required.

## Railway

The same production rules apply; Railway provides TLS and the public domains. The layout is five services in one project:

| Service | Source | Key settings |
|---|---|---|
| `pgvector` | Railway pgvector template (Postgres 16 + pgvector) | – |
| `Redis` | Railway Redis | – |
| `backend` | this repo | variable `RAILWAY_DOCKERFILE_PATH=docker/backend.Dockerfile`, `AEGIS_ML=0` (build arg), public domain, healthcheck path `/health` |
| `worker` | this repo | same Dockerfile and `AEGIS_ML=0`; start command `celery -A app.scheduler.celery_app worker --beat --loglevel=info`; no domain; exactly one replica |
| `frontend` | this repo | `RAILWAY_DOCKERFILE_PATH=docker/frontend.Dockerfile`, `NEXT_PUBLIC_AEGIS_API_URL=https://<backend domain>` (build arg), public domain |

Variables for `backend` and `worker` (Railway reference syntax):

```
AEGIS_ENV=production
DATABASE_URL=postgresql+psycopg://${{pgvector.PGUSER}}:${{pgvector.PGPASSWORD}}@${{pgvector.PGHOST}}:${{pgvector.PGPORT}}/${{pgvector.PGDATABASE}}
REDIS_URL=${{Redis.REDIS_URL}}
AEGIS_CORS_ORIGINS=["https://<frontend domain>"]
AEGIS_ALLOWED_HOSTS=["<backend domain>","healthcheck.railway.app"]
AEGIS_TRUSTED_PROXY_HOPS=1
AEGIS_TOKEN_MINUTES=30
AEGIS_ML=0
AEGIS_JWT_SECRET=<set it yourself; 48+ random characters>
```

`healthcheck.railway.app` is the `Host` header that Railway's deploy health check sends. `AEGIS_ML=0` skips torch and FinBERT: the image stays small enough for 1 GB plans, and news sentiment reports "unavailable". The backend listens on Railway's `$PORT`, and migrations run on every start.

Create the first admin from the backend service's shell:

```
python -m app.cli create-user --email you@example.in --role admin
```
