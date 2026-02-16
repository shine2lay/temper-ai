"""Drop M5 self-improvement tables

Revision ID: d5e6f7a8b901
Revises: c4d8e2f1a789
Create Date: 2026-02-15 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b901"
down_revision: Union[str, None] = "c4d8e2f1a789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop M5 self-improvement tables."""
    op.drop_table("m5_experiment_results")
    op.drop_table("m5_loop_state")
    op.drop_table("m5_experiments")


def downgrade() -> None:
    """Recreate M5 tables (schema only, no data recovery)."""
    op.create_table(
        "m5_experiments",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("control_config", sa.JSON(), nullable=True),
        sa.Column("variant_configs", sa.JSON(), nullable=True),
        sa.Column("target_samples_per_variant", sa.Integer(), nullable=True),
        sa.Column("winner_variant_id", sa.String(), nullable=True),
        sa.Column("analysis_results", sa.JSON(), nullable=True),
        sa.Column("proposal_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
    )
    op.create_index("idx_m5_exp_agent", "m5_experiments", ["agent_name"])
    op.create_index("idx_m5_exp_status", "m5_experiments", ["status"])

    op.create_table(
        "m5_loop_state",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("agent_name", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=True),
        sa.Column("error_log", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "m5_experiment_results",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("experiment_id", sa.String(), nullable=False),
        sa.Column("variant_id", sa.String(), nullable=False),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("speed_seconds", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.Column("extra_metrics", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["m5_experiments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "idx_m5_result_experiment", "m5_experiment_results", ["experiment_id"]
    )
    op.create_index(
        "idx_m5_result_variant", "m5_experiment_results", ["variant_id"]
    )
