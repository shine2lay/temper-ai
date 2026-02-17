"""Add lifecycle tables for self-modifying lifecycle (M7.1)

Revision ID: h9c0d1234567
Revises: g8b9c0123456
Create Date: 2026-02-16 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h9c0d1234567"
down_revision: Union[str, None] = "g8b9c0123456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_adaptations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workflow_id", sa.String(), nullable=False, index=True),
        sa.Column("profile_name", sa.String(), nullable=False, index=True),
        sa.Column("characteristics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rules_applied", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stages_original", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stages_adapted", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("experiment_id", sa.String(), nullable=True),
        sa.Column("experiment_variant", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "lifecycle_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("version", sa.String(), nullable=False, server_default="1.0"),
        sa.Column("product_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("min_autonomy_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("lifecycle_profiles")
    op.drop_table("lifecycle_adaptations")
