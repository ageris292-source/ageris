"""Environment-driven settings, validated at startup (spec §5, §68, §74)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

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

    # Optional LLM narrator (Anthropic Messages API). It only rewrites the
    # deterministic report in prose; its output is rejected if it introduces
    # any number not present in the structured facts. Never an authority.
    llm_api_key: SecretStr | None = Field(default=None, alias="AEGIS_LLM_API_KEY")
    llm_model: str = Field(default="claude-sonnet-4-5", alias="AEGIS_LLM_MODEL")

    # Optional alert channels (Phase 12). In-app alerts always work.
    telegram_bot_token: SecretStr | None = Field(default=None, alias="AEGIS_TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="AEGIS_TELEGRAM_CHAT_ID")
    smtp_url: SecretStr | None = Field(
        default=None, alias="AEGIS_SMTP_URL"
    )  # smtp(s)://user:pass@host:port
    alert_email_to: str | None = Field(default=None, alias="AEGIS_ALERT_EMAIL_TO")
    alert_email_from: str = Field(default="aegis@localhost", alias="AEGIS_ALERT_EMAIL_FROM")

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"], alias="AEGIS_CORS_ORIGINS"
    )
    # Host headers the API answers to (Phase 14). "*" is refused in production.
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"], alias="AEGIS_ALLOWED_HOSTS")
    # Reverse proxies in front of the API whose X-Forwarded-For entries are
    # trusted for the client address (0 = use the socket peer). Only the
    # entries the proxies append are used; a client-sent value never is.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5, alias="AEGIS_TRUSTED_PROXY_HOPS")

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
        if self.environment is Environment.PRODUCTION:
            problems = production_problems(self)
            if problems:
                raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def expose_api_docs(self) -> bool:
        return self.environment is not Environment.PRODUCTION


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")  # noqa: S104  (checked, not bound)
_WEAK_PASSWORDS = {"", "aegis", "postgres", "password", "changeme", "change-me", "secret", "redis"}


def production_problems(s: Settings) -> list[str]:
    """Deployment checks for AEGIS_ENV=production. Messages never contain
    secret values (spec §68, §82)."""
    out: list[str] = []
    if not s.cors_origins:
        out.append("AEGIS_CORS_ORIGINS must list the UI origin")
    for o in s.cors_origins:
        u = urlparse(o)
        if o == "*" or u.scheme != "https" or (u.hostname or "") in _LOCAL_HOSTS:
            out.append("AEGIS_CORS_ORIGINS must be https origins, not localhost or '*'")
            break
    if not s.allowed_hosts or "*" in s.allowed_hosts:
        out.append("AEGIS_ALLOWED_HOSTS must list the API host names (no '*')")
    try:
        db = make_url(s.database_url)
        if (db.password or "") in _WEAK_PASSWORDS:
            out.append("DATABASE_URL uses a missing or default password")
    except ArgumentError:
        out.append("DATABASE_URL is not a valid database URL")
    if not (urlparse(s.redis_url).password or ""):
        out.append("REDIS_URL must include a password (redis://:<password>@host:6379/0)")
    elif urlparse(s.redis_url).password in _WEAK_PASSWORDS:
        out.append("REDIS_URL uses a default password")
    if s.access_token_minutes > 60:
        out.append("AEGIS_TOKEN_MINUTES must be <= 60 in production")
    if len(s.jwt_secret.get_secret_value()) < 48:
        out.append("AEGIS_JWT_SECRET must be at least 48 characters in production")
    return out


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
