"""Add agent_evaluation_results table for per-agent evaluations.

Revision ID: opt_001
Revises: m9_001
Create Date: 2026-02-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "opt_001"
down_revision: str | None = "m9_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_evaluation_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_execution_id",
            sa.String(),
            sa.ForeignKey("agent_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluation_name", sa.String(), nullable=False),
        sa.Column("evaluator_type", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "agent_execution_id",
            "evaluation_name",
            name="uq_eval_agent_exec_name",
        ),
    )
    op.create_index(
        "ix_agent_evaluation_results_agent_execution_id",
        "agent_evaluation_results",
        ["agent_execution_id"],
    )
    op.create_index(
        "ix_agent_evaluation_results_evaluation_name",
        "agent_evaluation_results",
        ["evaluation_name"],
    )
    op.create_index(
        "idx_eval_name_score",
        "agent_evaluation_results",
        ["evaluation_name", "score"],
    )


def downgrade() -> None:
    op.drop_index("idx_eval_name_score", table_name="agent_evaluation_results")
    op.drop_index(
        "ix_agent_evaluation_results_evaluation_name",
        table_name="agent_evaluation_results",
    )
    op.drop_index(
        "ix_agent_evaluation_results_agent_execution_id",
        table_name="agent_evaluation_results",
    )
    op.drop_table("agent_evaluation_results")
