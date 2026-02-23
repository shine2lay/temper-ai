"""Add alert_records table for persistent alert history

Revision ID: k2f3g4567890
Revises: j1e2f3456789
Create Date: 2026-02-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k2f3g4567890"
down_revision: str | None = "j1e2f3456789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("rule_name", sa.String(), nullable=False, index=True),
        sa.Column("severity", sa.String(), nullable=False, index=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, index=True),
        sa.Column("context", sa.JSON(), nullable=True),
    )
    op.create_index(
        "idx_alert_rule_time",
        "alert_records",
        ["rule_name", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("idx_alert_rule_time", table_name="alert_records")
    op.drop_table("alert_records")
