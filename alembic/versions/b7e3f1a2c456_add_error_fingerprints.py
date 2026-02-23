"""Add error fingerprints table and columns

Revision ID: b7e3f1a2c456
Revises: 99c79410e449
Create Date: 2026-02-15 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3f1a2c456"
down_revision: str | Sequence[str] | None = "99c79410e449"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add error_fingerprints table and error_fingerprint columns."""
    # New table for aggregated error fingerprints
    op.create_table(
        "error_fingerprints",
        sa.Column("fingerprint", sa.String(16), primary_key=True),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False, index=True),
        sa.Column("normalized_message", sa.Text(), nullable=False),
        sa.Column("sample_message", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False, index=True),
        sa.Column("recent_workflow_ids", sa.JSON(), server_default="[]"),
        sa.Column("recent_agent_names", sa.JSON(), server_default="[]"),
        sa.Column("resolved", sa.Boolean(), server_default="0"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )

    # Add error_fingerprint column to 5 existing execution tables
    for table in [
        "workflow_executions",
        "stage_executions",
        "agent_executions",
        "llm_calls",
        "tool_executions",
    ]:
        op.add_column(
            table,
            sa.Column("error_fingerprint", sa.String(16), nullable=True, index=True),
        )


def downgrade() -> None:
    """Remove error fingerprints table and columns."""
    for table in [
        "tool_executions",
        "llm_calls",
        "agent_executions",
        "stage_executions",
        "workflow_executions",
    ]:
        op.drop_column(table, "error_fingerprint")

    op.drop_table("error_fingerprints")
