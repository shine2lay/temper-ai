"""Add portfolio tables for portfolio management (M7.3)

Revision ID: j1e2f3456789
Revises: h9c0d1234567
Create Date: 2026-02-16 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j1e2f3456789"
down_revision: Union[str, None] = "h9c0d1234567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "product_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), nullable=False, index=True),
        sa.Column("product_type", sa.String(), nullable=False, index=True),
        sa.Column("workflow_id", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running", index=True),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("duration_s", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "shared_components",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_stage", sa.String(), nullable=False, index=True),
        sa.Column("target_stage", sa.String(), nullable=False, index=True),
        sa.Column("similarity", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("shared_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("differing_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="detected"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "kg_concepts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("concept_type", sa.String(), nullable=False, index=True),
        sa.Column("properties", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "kg_edges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), nullable=False, index=True),
        sa.Column("target_id", sa.String(), nullable=False, index=True),
        sa.Column("relation", sa.String(), nullable=False, index=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("properties", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "tech_compatibility",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tech_a", sa.String(), nullable=False, index=True),
        sa.Column("tech_b", sa.String(), nullable=False, index=True),
        sa.Column("compatibility_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("notes", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), nullable=False, index=True),
        sa.Column("product_type", sa.String(), nullable=False, index=True),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("cost_efficiency", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("trend", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("utilization", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("composite_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("tech_compatibility")
    op.drop_table("kg_edges")
    op.drop_table("kg_concepts")
    op.drop_table("shared_components")
    op.drop_table("product_runs")
    op.drop_table("portfolios")
