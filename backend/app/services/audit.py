"""Audit trail writer. Every control-plane action goes through here."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.core.settings import get_settings
from app.models import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row to the current transaction (caller commits)."""
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        system_mode=get_settings().system_mode.value,
        config_fingerprint=get_config().fingerprint(),
        details=details or {},
    )
    db.add(entry)
    return entry
