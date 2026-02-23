"""Add tenant_id to remaining observability tables.

Adds tenant_id (nullable, indexed) to llm_calls, tool_executions, and
server_runs.  The workflow_executions, stage_executions, and agent_executions
tables were already updated in mt_001.

Revision ID: p1_001
Revises: mt_001
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p1_001"
down_revision: str | None = "mt_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that still need tenant_id (not covered by mt_001)
_TABLES = [
    "llm_calls",
    "tool_executions",
    "server_runs",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
