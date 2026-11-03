"""model validation (skill vs baselines, activation checks) and the not_active agent status

Revision ID: 0016_model_validation
Revises: 0015_user_features
Create Date: 2026-11-03 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_model_validation"
down_revision: str | Sequence[str] | None = "0015_user_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("skill", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("model_versions", sa.Column("activation_override", sa.Text(), nullable=True))
    # An agent switched off in a deployment (e.g. news sentiment without ML)
    # reports `not_active` instead of pretending to lack data.
    op.drop_constraint("ck_agent_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_status",
        "agent_runs",
        "status IN ('ok','insufficient_data','data_unusable','failed','not_active')",
    )


def downgrade() -> None:
    # agent_runs is immutable, so existing not_active rows stay; the old
    # constraint is restored for new rows only (NOT VALID).
    op.drop_constraint("ck_agent_status", "agent_runs", type_="check")
    op.execute(
        "ALTER TABLE agent_runs ADD CONSTRAINT ck_agent_status "
        "CHECK (status IN ('ok','insufficient_data','data_unusable','failed')) NOT VALID"
    )
    op.drop_column("model_versions", "activation_override")
    op.drop_column("model_versions", "validation")
    op.drop_column("model_versions", "skill")
