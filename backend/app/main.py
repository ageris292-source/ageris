"""Aegis API entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import auth, system
from app.core.config_file import get_config
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
    app = FastAPI(title="Aegis", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(system.router)
    app.include_router(auth.router)
    return app


app = create_app()
