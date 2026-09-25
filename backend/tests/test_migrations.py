"""Migrations must round-trip and match the ORM models."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from alembic import command
from app.db.session import Base, get_engine
from tests.conftest import alembic_config


def test_models_match_migrations() -> None:
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"ORM models and migrations have drifted: {diff}"


def test_downgrade_and_upgrade_round_trip() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
