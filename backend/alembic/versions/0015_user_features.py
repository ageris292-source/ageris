"""user features: named watchlists, price alerts, journal, personal alerts

Existing watchlist items move into a list called "My watchlist" per user.

Revision ID: 0015_user_features
Revises: 0014_web_app
Create Date: 2026-09-30 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_user_features"
down_revision: str | Sequence[str] | None = "0014_web_app"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- named watchlists
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),
    )
    op.create_index(op.f("ix_watchlists_user_id"), "watchlists", ["user_id"], unique=False)
    op.execute(
        "INSERT INTO watchlists (user_id, name, position) "
        "SELECT DISTINCT user_id, 'My watchlist', 0 FROM watchlist_items"
    )
    op.add_column("watchlist_items", sa.Column("watchlist_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE watchlist_items i SET watchlist_id = w.id FROM watchlists w "
        "WHERE w.user_id = i.user_id AND w.name = 'My watchlist'"
    )
    op.alter_column("watchlist_items", "watchlist_id", nullable=False)
    op.create_foreign_key(
        "fk_watchlist_items_watchlist",
        "watchlist_items",
        "watchlists",
        ["watchlist_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_watchlist_items_watchlist_id"), "watchlist_items", ["watchlist_id"], unique=False
    )
    op.drop_constraint("uq_watchlist_user_stock", "watchlist_items", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_list_stock", "watchlist_items", ["watchlist_id", "stock_id"]
    )

    # ---- personal alerts
    op.add_column("alerts", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_alerts_user", "alerts", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"], unique=False)

    # ---- price alert rules
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=20), nullable=False),
        sa.Column("threshold", sa.Numeric(18, 4), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("repeat", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("importance", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("armed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_session", sa.Date(), nullable=True),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_status", sa.String(length=120), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "condition IN ('price_above','price_below','day_change_up','day_change_down',"
            "'rsi_above','rsi_below')",
            name="ck_price_alert_condition",
        ),
        sa.CheckConstraint("threshold > 0", name="ck_price_alert_threshold_pos"),
        sa.CheckConstraint("importance IN ('normal','high')", name="ck_price_alert_importance"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_price_alerts_user_id"), "price_alerts", ["user_id"], unique=False)
    op.create_index("ix_price_alerts_active", "price_alerts", ["is_active"], unique=False)

    # ---- journal
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("kind IN ('note','entry','exit','review')", name="ck_journal_kind"),
        sa.ForeignKeyConstraint(["order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_user_created", "journal_entries", ["user_id", "created_at"])
    op.create_index("ix_journal_user_stock", "journal_entries", ["user_id", "stock_id"])


def downgrade() -> None:
    op.drop_index("ix_journal_user_stock", table_name="journal_entries")
    op.drop_index("ix_journal_user_created", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_price_alerts_active", table_name="price_alerts")
    op.drop_index(op.f("ix_price_alerts_user_id"), table_name="price_alerts")
    op.drop_table("price_alerts")
    op.drop_index(op.f("ix_alerts_user_id"), table_name="alerts")
    op.drop_constraint("fk_alerts_user", "alerts", type_="foreignkey")
    op.drop_column("alerts", "user_id")
    # Collapse lists back into one per user (duplicates across lists dropped).
    op.execute(
        "DELETE FROM watchlist_items a USING watchlist_items b "
        "WHERE a.user_id = b.user_id AND a.stock_id = b.stock_id AND a.id > b.id"
    )
    op.drop_constraint("uq_watchlist_list_stock", "watchlist_items", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_user_stock", "watchlist_items", ["user_id", "stock_id"]
    )
    op.drop_index(op.f("ix_watchlist_items_watchlist_id"), table_name="watchlist_items")
    op.drop_constraint("fk_watchlist_items_watchlist", "watchlist_items", type_="foreignkey")
    op.drop_column("watchlist_items", "watchlist_id")
    op.drop_index(op.f("ix_watchlists_user_id"), table_name="watchlists")
    op.drop_table("watchlists")
