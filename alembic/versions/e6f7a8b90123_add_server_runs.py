"""Add server_runs table for persistent run history

Revision ID: e6f7a8b90123
Revises: d5e6f7a8b901
Create Date: 2026-02-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b90123"
down_revision: str | None = "d5e6f7a8b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create server_runs table."""
    op.create_table(
        "server_runs",
        sa.Column("execution_id", sa.String(), primary_key=True),
        sa.Column("workflow_id", sa.String(), nullable=True, index=True),
        sa.Column("workflow_path", sa.String(), nullable=False),
        sa.Column("workflow_name", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("workspace", sa.String(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Drop server_runs table."""
    op.drop_table("server_runs")
