"""HTTP hardening (spec §68-§70): global rate limiting, request size limit
and security headers. Pure ASGI middleware, so they also cover error
responses (429, 413, 500) produced further in."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.config_file import SecurityRules
from app.core.rate_limit import RateLimitUnavailableError, hit

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


async def _json(
    send: Send, status: int, detail: str, headers: dict[str, str] | None = None
) -> None:
    body = json.dumps({"detail": detail}).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    hdrs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": body})


def client_id(scope: Scope, trusted_proxy_hops: int) -> str:
    """The socket peer, or — only behind a configured number of trusted
    proxies — the matching X-Forwarded-For entry (never client-chosen)."""
    peer = scope.get("client")
    host = str(peer[0]) if peer else "unknown"
    if trusted_proxy_hops <= 0:
        return host
    for k, v in scope.get("headers", []):
        if k == b"x-forwarded-for":
            hops = [h.strip() for h in v.decode("latin-1").split(",") if h.strip()]
            if len(hops) >= trusted_proxy_hops:
                return str(hops[-trusted_proxy_hops])
    return host


class RateLimitMiddleware:
    """Fixed-window limits per client: every request, plus a tighter budget
    for writes (non-GET). Fails closed (503) if Redis is unavailable, like
    the login limiter; only exempt paths (health) bypass it."""

    def __init__(self, app: ASGIApp, rules: SecurityRules, trusted_proxy_hops: int = 0) -> None:
        self.app, self.rules, self.hops = app, rules, trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.rules.rate_limit_exempt_paths:
            await self.app(scope, receive, send)
            return
        r = self.rules
        who = client_id(scope, self.hops)
        method = scope.get("method", "GET")
        buckets = [("all", r.rate_limit_requests)]
        if method not in ("GET", "HEAD", "OPTIONS"):
            buckets.append(("write", r.rate_limit_writes))
        try:
            for name, limit in buckets:
                ok = await run_in_threadpool(
                    hit, f"api:{name}:{who}", limit, r.rate_limit_window_seconds
                )
                if not ok:
                    await _json(
                        send,
                        429,
                        "rate limit exceeded; slow down",
                        {"Retry-After": str(r.rate_limit_window_seconds)},
                    )
                    return
        except RateLimitUnavailableError:
            await _json(send, 503, "rate limiter unavailable; request refused")
            return
        await self.app(scope, receive, send)


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    """Refuse request bodies above the limit (413), by declared length and
    by counting streamed chunks, before the application reads them."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    too_big = int(v) > self.max_bytes
                except ValueError:
                    await _json(send, 400, "invalid Content-Length")
                    return
                if too_big:
                    await _json(send, 413, f"request body larger than {self.max_bytes} bytes")
                    return
        seen = 0
        overflow = False
        replaced = False

        async def counted() -> Message:
            nonlocal seen, overflow
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    overflow = True
                    raise _BodyTooLargeError
            return msg

        async def guarded(msg: Message) -> None:
            # Frameworks may catch the error while parsing (e.g. a form) and
            # answer 400; the client gets the true reason instead.
            nonlocal replaced
            if overflow:
                if msg["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await _json(send, 413, f"request body larger than {self.max_bytes} bytes")
                return
            await send(msg)

        try:
            await self.app(scope, counted, guarded)
        except _BodyTooLargeError:
            if not replaced:
                await _json(send, 413, f"request body larger than {self.max_bytes} bytes")


class SecurityHeadersMiddleware:
    """Defensive headers on every API response. The API serves JSON only:
    nothing may be framed, sniffed, cached or run as a document."""

    def __init__(self, app: ASGIApp, rules: SecurityRules, *, hsts: bool) -> None:
        self.app = app
        base = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "cross-origin-opener-policy": "same-origin",
            "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
        }
        if hsts:
            base["strict-transport-security"] = (
                f"max-age={rules.hsts_max_age_seconds}; includeSubDomains"
            )
        self.headers = [(k.encode(), v.encode()) for k, v in base.items()]
        self.csp = (
            b"content-security-policy",
            b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = scope["path"].startswith(_DOCS_PATHS)  # Swagger UI (never in production)

        async def with_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                existing = {k.lower() for k, _ in msg.get("headers", [])}
                extra = [h for h in self.headers if h[0] not in existing]
                if not docs:
                    extra.append(self.csp)
                    if b"cache-control" not in existing:
                        extra.append((b"cache-control", b"no-store"))
                msg["headers"] = [*msg.get("headers", []), *extra]
            await send(msg)

        await self.app(scope, receive, with_headers)
