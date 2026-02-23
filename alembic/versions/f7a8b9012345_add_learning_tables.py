"""Add learning tables for continuous learning (M5.3)

Revision ID: f7a8b9012345
Revises: e6f7a8b90123
Create Date: 2026-02-16 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9012345"
down_revision: str | None = "e6f7a8b90123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create learned_patterns, mining_runs, tune_recommendations tables."""
    op.create_table(
        "learned_patterns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pattern_type", sa.String(), nullable=False, index=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("source_workflow_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "mining_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("patterns_found", sa.Integer(), nullable=False),
        sa.Column("patterns_new", sa.Integer(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("miner_stats", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
    )

    op.create_table(
        "tune_recommendations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pattern_id", sa.String(), nullable=False, index=True),
        sa.Column("config_path", sa.String(), nullable=False),
        sa.Column("field_path", sa.String(), nullable=False),
        sa.Column("current_value", sa.String(), nullable=False),
        sa.Column("recommended_value", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Drop learning tables."""
    op.drop_table("tune_recommendations")
    op.drop_table("mining_runs")
    op.drop_table("learned_patterns")
