"""Environment validation and safe defaults (spec §5, §32, §74)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.modes import SystemMode
from app.core.settings import Settings

BASE = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost/db",
    "AEGIS_JWT_SECRET": "s" * 48,
}


def make(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for k in ("AEGIS_SYSTEM_MODE", "AEGIS_LIVE_TRADING_ENABLED", "AEGIS_DEMO_DATA", "AEGIS_ENV"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**BASE, **env}.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_are_research_with_live_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    assert s.system_mode is SystemMode.RESEARCH
    assert s.live_trading_enabled is False
    assert s.demo_data is False


@pytest.mark.parametrize("secret", ["short", "change-me", "x" * 31])
def test_weak_jwt_secret_rejected(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    with pytest.raises(ValidationError, match="AEGIS_JWT_SECRET"):
        make(monkeypatch, AEGIS_JWT_SECRET=secret)


@pytest.mark.parametrize("mode", ["research", "paper"])
def test_live_flag_outside_live_mode_rejected(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    with pytest.raises(ValidationError, match="requires AEGIS_SYSTEM_MODE=live"):
        make(monkeypatch, AEGIS_SYSTEM_MODE=mode, AEGIS_LIVE_TRADING_ENABLED="true")


def test_demo_data_never_with_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="DEMO_DATA"):
        make(monkeypatch, AEGIS_SYSTEM_MODE="live", AEGIS_DEMO_DATA="true")


def test_demo_data_never_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="production"):
        make(monkeypatch, AEGIS_ENV="production", AEGIS_DEMO_DATA="true")


def test_invalid_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, AEGIS_SYSTEM_MODE="yolo")


def test_database_url_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AEGIS_JWT_SECRET", "s" * 48)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_errors_never_echo_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import SettingsError, get_settings

    leaked = "super-secret-value-that-must-not-leak-" + "z" * 10
    monkeypatch.setenv("AEGIS_JWT_SECRET", leaked)
    monkeypatch.setenv("AEGIS_SYSTEM_MODE", "paper")
    monkeypatch.setenv("AEGIS_LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsError) as info:
            get_settings()
        assert leaked not in str(info.value)
        assert "requires AEGIS_SYSTEM_MODE=live" in str(info.value)
    finally:
        get_settings.cache_clear()
