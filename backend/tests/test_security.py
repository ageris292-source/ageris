"""Phase 14: global rate limiting, request size limit, security headers,
CORS, trusted hosts and production configuration checks."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main as app_main
from app.cli import main as cli
from app.core import http_security
from app.core.config_file import get_config
from app.core.modes import Environment
from app.core.rate_limit import RateLimitUnavailableError
from app.core.settings import Settings, get_settings, production_problems
from app.models import User
from tests.conftest import auth_header

CFG = get_config()
STRONG = "s3cure-" + "x" * 50


def _app(
    monkeypatch: pytest.MonkeyPatch, settings: Settings | None = None, **security: Any
) -> FastAPI:
    cfg = CFG.model_copy(update={"security": CFG.security.model_copy(update=security)})
    monkeypatch.setattr(app_main, "get_config", lambda: cfg)
    if settings is not None:
        monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    return app_main.create_app()


def _prod(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": Environment.PRODUCTION,
        "database_url": "postgresql+psycopg://aegis:Str0ng-db-pass@db:5432/aegis",
        "redis_url": "redis://:Str0ng-redis-pass@redis:6379/0",
        "jwt_secret": SecretStr(STRONG),
        "cors_origins": ["https://aegis.example.in"],
        "allowed_hosts": ["api.aegis.example.in"],
        "access_token_minutes": 30,
    }
    s = get_settings().model_copy(update={**base, **over})
    return s


# ------------------------------------------------------------------ headers --


def test_security_headers_on_every_response(client: TestClient) -> None:
    for r in (
        client.get("/health"),
        client.get("/auth/me"),  # 401
        client.get("/nope"),  # 404
    ):
        h = r.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["cache-control"] == "no-store"
        assert "strict-transport-security" not in h  # only in production (TLS upstream)
    assert client.get("/docs").status_code == 200  # dev: docs, without the strict CSP
    assert "content-security-policy" not in client.get("/docs").headers


def test_cors_allows_what_the_ui_sends(client: TestClient) -> None:
    ui = "http://localhost:3000"
    for method, header in (
        ("PUT", "authorization,content-type"),  # portfolio positions / cash
        ("POST", "authorization,content-type,idempotency-key"),  # paper orders
    ):
        r = client.options(
            "/paper/orders",
            headers={
                "Origin": ui,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": header,
            },
        )
        assert r.status_code == 200, (method, r.text)
        assert r.headers["access-control-allow-origin"] == ui
    evil = client.options(
        "/paper/orders",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert evil.status_code == 400 and "access-control-allow-origin" not in evil.headers


# --------------------------------------------------------------- rate limits --


def test_global_rate_limit_per_client_and_for_writes(
    monkeypatch: pytest.MonkeyPatch, admin: User
) -> None:
    with TestClient(_app(monkeypatch, rate_limit_requests=6, rate_limit_writes=2)) as c:
        h = auth_header(c, admin.email)  # 1 write
        assert (
            c.post(
                "/trading/kill-switch", headers=h, json={"active": True, "reason": "halt for test"}
            ).status_code
            == 200
        )
        blocked = c.post(
            "/trading/kill-switch", headers=h, json={"active": True, "reason": "halt for test"}
        )
        assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
        assert blocked.headers["x-frame-options"] == "DENY"  # headers wrap limiter responses
        assert [c.get("/auth/me", headers=h).status_code for _ in range(4)] == [200] * 3 + [429]
        assert all(c.get("/health").status_code == 200 for _ in range(10))  # exempt
        # a spoofed X-Forwarded-For is ignored when no proxy is trusted
        spoof = c.get("/auth/me", headers={**h, "X-Forwarded-For": "203.0.113.9"})
        assert spoof.status_code == 429


def test_trusted_proxy_separates_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    proxied = get_settings().model_copy(update={"trusted_proxy_hops": 1})
    with TestClient(_app(monkeypatch, proxied, rate_limit_requests=2)) as c:
        a = {"X-Forwarded-For": "198.51.100.7"}
        b = {"X-Forwarded-For": "203.0.113.1, 198.51.100.8"}  # proxy appended the real peer
        assert [c.get("/auth/me", headers=a).status_code for _ in range(3)] == [401, 401, 429]
        assert c.get("/auth/me", headers=b).status_code == 401  # a different client
        spoofed = {"X-Forwarded-For": "192.0.2.99, 198.51.100.7"}  # client-sent prefix
        assert c.get("/auth/me", headers=spoofed).status_code == 429  # same real client
    assert http_security.client_id({"client": ("10.0.0.2", 1), "headers": []}, 1) == "10.0.0.2"


def test_rate_limiter_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*_: Any) -> bool:
        raise RateLimitUnavailableError("redis down")

    monkeypatch.setattr(http_security, "hit", down)
    with TestClient(_app(monkeypatch)) as c:
        r = c.get("/auth/me")
        assert r.status_code == 503 and "unavailable" in r.json()["detail"]
        assert c.get("/health").status_code == 200  # health still reports


# ---------------------------------------------------------------- body size --


def test_request_body_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch, max_request_bytes=2048)) as c:
        big = c.post("/auth/token", content=b"x" * 4096, headers={"Content-Type": "text/plain"})
        assert big.status_code == 413
        streamed = c.post(
            "/auth/token",
            content=iter([b"y" * 1500, b"y" * 1500]),  # chunked, no Content-Length
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert streamed.status_code == 413
        ok = c.post("/auth/token", data={"username": "a@b.c", "password": "x"})
        assert ok.status_code == 401  # small bodies reach the app


# --------------------------------------------------------------- production --


def test_production_settings_are_checked() -> None:
    assert production_problems(_prod()) == []
    weak = _prod(
        database_url="postgresql+psycopg://aegis:aegis@db:5432/aegis",
        redis_url="redis://redis:6379/0",
        cors_origins=["http://localhost:3000"],
        allowed_hosts=["*"],
        access_token_minutes=240,
        jwt_secret=SecretStr("x" * 40),
    )
    problems = " | ".join(production_problems(weak))
    for needle in (
        "AEGIS_CORS_ORIGINS",
        "AEGIS_ALLOWED_HOSTS",
        "DATABASE_URL",
        "REDIS_URL must include a password",
        "AEGIS_TOKEN_MINUTES",
        "48 characters",
    ):
        assert needle in problems
    assert "aegis:aegis" not in problems  # never echo secrets


def test_production_startup_refuses_unsafe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_ENV", "production")
    monkeypatch.setenv("AEGIS_JWT_SECRET", STRONG)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://aegis:aegis@db:5432/aegis")
    with pytest.raises(ValueError) as exc:
        Settings()
    msg = str(exc.value)
    assert "unsafe production configuration" in msg and "DATABASE_URL" in msg
    assert STRONG not in msg


def test_production_app_hides_docs_sends_hsts_and_checks_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(_app(monkeypatch, _prod())) as c:
        ok = c.get("/health", headers={"Host": "api.aegis.example.in"})
        assert ok.status_code == 200
        assert ok.headers["strict-transport-security"].startswith("max-age=31536000")
        for p in ("/docs", "/redoc", "/openapi.json"):
            assert c.get(p, headers={"Host": "api.aegis.example.in"}).status_code == 404
        assert c.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_check_deploy_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(["check-deploy"]) == 1  # the test environment is not production-ready
    out = capsys.readouterr().out
    assert "FAIL AEGIS_ENV is test" in out and "REDIS_URL" in out
    monkeypatch.setattr("app.core.settings.get_settings", _prod)
    assert cli(["check-deploy"]) == 0
    assert "OK production checks passed" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def _restore() -> Iterator[None]:
    yield
    get_settings.cache_clear()
