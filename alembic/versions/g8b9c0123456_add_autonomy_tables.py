"""Add autonomy tables for progressive autonomy (M6.1)

Revision ID: g8b9c0123456
Revises: f7a8b9012345
Create Date: 2026-02-16 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g8b9c0123456"
down_revision: str | None = "f7a8b9012345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "autonomy_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_name", sa.String(), nullable=False, index=True),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("current_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shadow_level", sa.Integer(), nullable=True),
        sa.Column("shadow_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "shadow_agreements", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_escalation", sa.DateTime(), nullable=True),
        sa.Column("last_de_escalation", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "autonomy_transitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_name", sa.String(), nullable=False, index=True),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("from_level", sa.Integer(), nullable=False),
        sa.Column("to_level", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("merit_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "budget_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False, unique=True),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("budget_usd", sa.Float(), nullable=False),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("action_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="'active'"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "emergency_stop_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("agents_halted", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("halt_duration_ms", sa.Float(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("emergency_stop_events")
    op.drop_table("budget_records")
    op.drop_table("autonomy_transitions")
    op.drop_table("autonomy_states")
