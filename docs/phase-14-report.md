# Phase 14 Report: Security Hardening and Deployment

Date: 2026-09-26 · Status: complete, all checks green

## Implemented
- **Global rate limiting** (`app/core/http_security.py`, pure ASGI):
  - Redis fixed windows per client: 300 requests/min for everything, plus 60 writes/min for POST/PUT/DELETE.
  - Over the limit, the API answers 429 with `Retry-After`.
  - **Fails closed:** if Redis is down, requests get 503, as login already did. Only `/health` is exempt.
  - The client address is the socket peer. Behind `AEGIS_TRUSTED_PROXY_HOPS` proxies, it is the `X-Forwarded-For` entry **appended by the proxy**, never a client-sent one.
  - Found while doing this: uvicorn's `--forwarded-allow-ips='*'` takes the left-most, client-controlled entry, so it was deliberately not used.
- **Request body limit:**
  - 6 MiB by default; an oversized request gets 413.
  - Checked both by declared `Content-Length` and by counting streamed chunks.
  - The 413 is still returned when a framework catches the error while parsing a form.
- **Security headers on every API response**, including 401/404/429/413:
  - `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP, `Permissions-Policy`;
  - a deny-all `Content-Security-Policy` for JSON;
  - `Cache-Control: no-store`;
  - HSTS in production.
- **Console headers** (`next.config.mjs`):
  - A CSP where `connect-src` is limited to the console's own origin and the configured API; `eval` is allowed only in the dev server.
  - `frame-ancestors 'none'`, `nosniff`, `no-referrer`, COOP, `Permissions-Policy`.
- **CORS fixes (pre-existing bugs found while hardening):**
  - PUT (portfolio positions and cash) and the `Idempotency-Key` header (paper-order approval) were missing from the CORS allow-lists.
  - The browser blocked both at the preflight, so those UI actions could never have worked cross-origin.
  - Verified in the browser before and after the fix.
- **Trusted hosts:** `AEGIS_ALLOWED_HOSTS`; an unknown `Host` header gets 400.
- **Production configuration checks** (`AEGIS_ENV=production` refuses to start otherwise; messages never contain secret values):
  - https-only CORS origins, not localhost or `*`;
  - explicit allowed hosts;
  - non-default database and Redis passwords (a Redis password is required);
  - token lifetime ≤ 60 minutes;
  - JWT secret ≥ 48 characters.

  In production, `/docs`, `/redoc` and `/openapi.json` are disabled.
- **`python -m app.cli check-deploy`:** runs the same checks plus the Trade Risk Engine self-test, prints `FAIL …` or `OK`, and exits 1 on any problem.
- **Deployment:**
  - `docker-compose.prod.yml`:
    - Caddy with automatic TLS is the only published service.
    - Postgres and Redis publish no ports. Redis gets a password and AOF persistence.
    - The API has a health check (with the right `Host` header) and restart policies.
  - `deploy/Caddyfile`.
  - The production section of `.env.example`.
  - **`docs/deployment.md`**: topology, secrets, the pre-flight check, first start, rate limits behind proxies, backups and restore, upgrades, and an incident runbook.
- New config section `security` (strictly validated).

## Tests
10 new tests; 342 in total (1 optional-NLP skip), plus ruff and mypy all clean.
- Headers are present on 200/401/404 responses; there is no HSTS outside production; docs are exempt from the strict CSP in development.
- **CORS:** preflights for PUT and for POST with `Idempotency-Key` from the UI origin succeed; a foreign origin is refused.
- **Rate limits:**
  - The write budget and then the global budget give 429 with `Retry-After`, and the security headers wrap the 429.
  - `/health` is exempt.
  - A spoofed `X-Forwarded-For` is ignored without a trusted proxy.
  - Behind one trusted proxy, clients are separated by the appended entry, and a client-sent prefix doesn't create a new identity.
  - Redis down gives 503 (fail closed) while health still answers.
- **Body limit:** declared oversize gives 413, streamed chunked oversize gives 413, and small bodies pass.
- **Production:**
  - A safe configuration passes.
  - A weak one lists all six problems without echoing secrets.
  - `Settings()` refuses to start with a default database password.
  - The production app hides the docs, sends HSTS and rejects a foreign `Host`.
  - `check-deploy` exits 1 in the test environment and 0 with safe production settings.

## Not verified here
- `docker compose` could not be run in this environment (Docker is not installed). The production compose file was checked for YAML structure and service merge only; a `docker compose … config` and a TLS smoke test should be done on the target host.
