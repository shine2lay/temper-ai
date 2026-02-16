"""Add attribution and lineage columns (Phase 3)

Revision ID: c4d8e2f1a789
Revises: b7e3f1a2c456
Create Date: 2026-02-15 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d8e2f1a789"
down_revision: Union[str, None] = "b7e3f1a2c456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 3 observability columns."""
    # WI-1: Cost Attribution
    op.add_column(
        "workflow_executions",
        sa.Column("cost_attribution_tags", sa.JSON(), nullable=True),
    )

    # WI-2: Data Lineage
    op.add_column(
        "stage_executions",
        sa.Column("output_lineage", sa.JSON(), nullable=True),
    )

    # WI-3: Failover Tracking
    op.add_column(
        "llm_calls",
        sa.Column("failover_sequence", sa.JSON(), nullable=True),
    )
    op.add_column(
        "llm_calls",
        sa.Column("failover_from_provider", sa.String(), nullable=True),
    )

    # WI-4: Prompt Versioning
    op.add_column(
        "llm_calls",
        sa.Column("prompt_template_hash", sa.String(16), nullable=True),  # noqa: duplicate
    )
    op.add_column(
        "llm_calls",
        sa.Column("prompt_template_source", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove Phase 3 observability columns."""
    op.drop_column("llm_calls", "prompt_template_source")
    op.drop_column("llm_calls", "prompt_template_hash")
    op.drop_column("llm_calls", "failover_from_provider")
    op.drop_column("llm_calls", "failover_sequence")
    op.drop_column("stage_executions", "output_lineage")
    op.drop_column("workflow_executions", "cost_attribution_tags")
