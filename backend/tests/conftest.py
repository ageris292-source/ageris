"""Test fixtures. Tests run against a REAL PostgreSQL and Redis (no mocks for
infrastructure), migrated with the same Alembic scripts used in production."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://aegis:aegis@localhost:5432/aegis_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("AEGIS_JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("AEGIS_ENV", "test")
for var in ("AEGIS_SYSTEM_MODE", "AEGIS_LIVE_TRADING_ENABLED", "AEGIS_DEMO_DATA"):
    os.environ.pop(var, None)

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from app.core.rate_limit import get_redis
from app.db.session import _session_factory, get_engine
from app.models import User, UserRole
from app.services.users import create_user

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = os.environ["DATABASE_URL"]
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        # Test-only cleanup: immutability triggers are bypassed here and nowhere else.
        conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM audit_logs"))
        conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM risk_events"))
        for table in ("data_conflicts", "prices", "corporate_actions"):
            conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
            conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608  (fixed table names)
            conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM data_ingestion_runs"))
        conn.execute(text("DELETE FROM stocks"))
        conn.execute(
            text(
                "UPDATE trading_controls SET kill_switch_active = true, changed_by = NULL, "
                "reason = 'initial state: trading halted until an admin reviews and resumes'"
            )
        )
        conn.execute(text("DELETE FROM users"))
    get_redis().flushdb()


@pytest.fixture
def db() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(db: Session) -> User:
    return create_user(db, "admin@aegis.test", PASSWORD, UserRole.ADMIN)


@pytest.fixture
def analyst(db: Session) -> User:
    return create_user(db, "analyst@aegis.test", PASSWORD, UserRole.ANALYST)


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
