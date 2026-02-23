"""M9: Add agent registry, event log, and event subscription tables.

Also adds source_agent_id column to goal_proposals table.

Revision ID: m9_001
Revises: k2f3g4567890
Create Date: 2026-02-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m9_001"
down_revision: str | None = "k2f3g4567890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Agent registry table
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(), server_default=""),
        sa.Column("version", sa.String(), server_default="1.0"),
        sa.Column("agent_type", sa.String(), server_default="standard"),
        sa.Column("config_path", sa.String(), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("memory_namespace", sa.String(), server_default=""),
        sa.Column("status", sa.String(), server_default="registered"),
        sa.Column("total_invocations", sa.Integer(), server_default="0"),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("name", name="uq_agent_registry_name"),
    )
    op.create_index("ix_agent_registry_name", "agent_registry", ["name"])
    op.create_index("ix_agent_registry_status", "agent_registry", ["status"])

    # Event log table
    op.create_table(
        "event_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("source_workflow_id", sa.String(), nullable=True),
        sa.Column("source_stage_name", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("consumed", sa.Boolean(), server_default="0"),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_by", sa.String(), nullable=True),
    )
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])
    op.create_index("ix_event_log_timestamp", "event_log", ["timestamp"])
    op.create_index(
        "ix_event_log_source_workflow_id", "event_log", ["source_workflow_id"]
    )

    # Event subscriptions table
    op.create_table(
        "event_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("source_workflow_filter", sa.String(), nullable=True),
        sa.Column("payload_filter", sa.JSON(), nullable=True),
        sa.Column("handler_ref", sa.String(), nullable=True),
        sa.Column("workflow_to_trigger", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("last_event_id", sa.String(), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_event_subscriptions_agent_id", "event_subscriptions", ["agent_id"]
    )
    op.create_index(
        "ix_event_subscriptions_event_type", "event_subscriptions", ["event_type"]
    )
    op.create_index("ix_event_subscriptions_active", "event_subscriptions", ["active"])

    # Add source_agent_id to goal_proposals (if table exists)
    try:
        op.add_column(
            "goal_proposals",
            sa.Column("source_agent_id", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_goal_proposals_source_agent_id",
            "goal_proposals",
            ["source_agent_id"],
        )
    except Exception:  # noqa: BLE001 -- table may not exist in all environments
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_goal_proposals_source_agent_id", table_name="goal_proposals")
        op.drop_column("goal_proposals", "source_agent_id")
    except Exception:  # noqa: BLE001 -- column may not exist in all environments
        pass

    op.drop_index("ix_event_subscriptions_active", table_name="event_subscriptions")
    op.drop_index("ix_event_subscriptions_event_type", table_name="event_subscriptions")
    op.drop_index("ix_event_subscriptions_agent_id", table_name="event_subscriptions")
    op.drop_table("event_subscriptions")

    op.drop_index("ix_event_log_source_workflow_id", table_name="event_log")
    op.drop_index("ix_event_log_timestamp", table_name="event_log")
    op.drop_index("ix_event_log_event_type", table_name="event_log")
    op.drop_table("event_log")

    op.drop_index("ix_agent_registry_status", table_name="agent_registry")
    op.drop_index("ix_agent_registry_name", table_name="agent_registry")
    op.drop_table("agent_registry")
