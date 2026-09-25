"""Environment-driven settings, validated at startup (spec §5, §68, §74)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.modes import Environment, SystemMode

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INSECURE_SECRETS = {"change-me", "changeme", "secret", "dev", "development"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Environment = Field(default=Environment.DEVELOPMENT, alias="AEGIS_ENV")

    # Safe defaults: research mode, live trading off (spec §5, §32).
    system_mode: SystemMode = Field(default=SystemMode.RESEARCH, alias="AEGIS_SYSTEM_MODE")
    live_trading_enabled: bool = Field(default=False, alias="AEGIS_LIVE_TRADING_ENABLED")
    demo_data: bool = Field(default=False, alias="AEGIS_DEMO_DATA")

    config_path: Path = Field(
        default=_REPO_ROOT / "config" / "aegis.yaml", alias="AEGIS_CONFIG_PATH"
    )

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: SecretStr = Field(alias="AEGIS_JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=60, ge=5, le=24 * 60, alias="AEGIS_TOKEN_MINUTES")

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"], alias="AEGIS_CORS_ORIGINS"
    )

    @model_validator(mode="after")
    def _validate_safety(self) -> Self:
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret.lower() in _INSECURE_SECRETS:
            raise ValueError("AEGIS_JWT_SECRET must be at least 32 characters and not a default")

        # The live flag only means something in live mode; a mismatch is a
        # misconfiguration we refuse to guess about.
        if self.live_trading_enabled and self.system_mode is not SystemMode.LIVE:
            raise ValueError("AEGIS_LIVE_TRADING_ENABLED=true requires AEGIS_SYSTEM_MODE=live")
        # Demo data must never be able to reach a live broker (spec §74).
        if self.demo_data and self.system_mode is SystemMode.LIVE:
            raise ValueError("AEGIS_DEMO_DATA=true cannot be combined with live mode")
        if self.demo_data and self.environment is Environment.PRODUCTION:
            raise ValueError("AEGIS_DEMO_DATA=true is not allowed in production")
        return self


class SettingsError(RuntimeError):
    """Invalid environment. The message never contains input values (secrets)."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()  # values come from the environment
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'settings'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise SettingsError(f"invalid environment configuration: {problems}") from None
