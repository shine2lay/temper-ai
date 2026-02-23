"""Add tenant_id to secondary observability tables.

Adds tenant_id (nullable, indexed) to collaboration_events, agent_merit_scores,
decision_outcomes, system_metrics, error_fingerprints, alert_records,
rollback_snapshots, and rollback_events.  The primary observability tables were
covered by mt_001 (workflow_executions, stage_executions, agent_executions) and
p1_001 (llm_calls, tool_executions, server_runs).

Revision ID: p1_002
Revises: p1_001
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p1_002"
down_revision: str | None = "p1_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Secondary observability tables that still need tenant_id
_TABLES = [
    "collaboration_events",
    "agent_merit_scores",
    "decision_outcomes",
    "system_metrics",
    "error_fingerprints",
    "alert_records",
    "rollback_snapshots",
    "rollback_events",
]

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(
            f"UPDATE {table} SET tenant_id = '{_DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL"  # noqa: S608
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
