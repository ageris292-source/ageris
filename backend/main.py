"""Aegis API entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.routes import (
    analysis,
    auth,
    backtest,
    fundamentals,
    live,
    macro,
    monitoring,
    news,
    paper,
    ranking,
    risk,
    stocks,
    system,
    technical,
    trade,
)
from app.core.config_file import get_config
from app.core.http_security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.modes import Environment
from app.core.settings import get_settings

log = logging.getLogger("aegis")


def validate_startup() -> None:
    """Abort boot on any invalid environment or configuration (spec §73, §82)."""
    settings = get_settings()
    config = get_config()
    log.info(
        "Aegis %s starting: env=%s mode=%s live_flag=%s demo=%s config=%s (%s)",
        __version__,
        settings.environment.value,
        settings.system_mode.value,
        settings.live_trading_enabled,
        settings.demo_data,
        config.config_version,
        config.fingerprint()[:12],
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_startup()
    yield


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    rules = get_config().security
    docs = settings.expose_api_docs  # no interactive docs or schema in production
    app = FastAPI(
        title="Aegis",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # Added innermost first: headers wrap everything, so 429/413 carry them too.
    app.add_middleware(
        RateLimitMiddleware, rules=rules, trusted_proxy_hops=settings.trusted_proxy_hops
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=rules.max_request_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        rules=rules,
        hsts=settings.environment is Environment.PRODUCTION,
    )
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(stocks.router)
    app.include_router(technical.router)
    app.include_router(fundamentals.router)
    app.include_router(news.router)
    app.include_router(macro.router)
    app.include_router(risk.router)
    app.include_router(analysis.router)
    app.include_router(trade.router)
    app.include_router(backtest.router)
    app.include_router(paper.router)
    app.include_router(ranking.router)
    app.include_router(monitoring.router)
    app.include_router(live.router)
    return app


app = create_app()
