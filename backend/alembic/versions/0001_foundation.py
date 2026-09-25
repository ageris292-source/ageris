"""Phase 1 foundation: users, audit_logs, risk_events, trading_controls.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

user_role = postgresql.ENUM("admin", "analyst", name="user_role", create_type=False)
severity = postgresql.ENUM(
    "info", "warning", "critical", name="risk_event_severity", create_type=False
)


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)
    severity.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100)),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("system_mode", sa.String(20), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # Audit trail is append-only: reject UPDATE and DELETE at the database level.
    op.execute(
        """
        CREATE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only (% not permitted)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_append_only();
        """
    )

    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", severity, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("requires_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_risk_events_type_time", "risk_events", ["event_type", "occurred_at"])

    op.create_table(
        "trading_controls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kill_switch_active", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_trading_controls_singleton"),
    )
    # A fresh install starts HALTED. An admin must consciously resume.
    op.execute(
        "INSERT INTO trading_controls (id, kill_switch_active, reason) "
        "VALUES (1, true, 'initial state: trading halted until an admin reviews and resumes')"
    )


def downgrade() -> None:
    op.drop_table("trading_controls")
    op.drop_index("ix_risk_events_type_time", table_name="risk_events")
    op.drop_table("risk_events")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_table("audit_logs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    severity.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
