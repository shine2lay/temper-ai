"""Add tenant_id to agent_evaluation_results and agent_registry.

Security fix H-S06: Add multi-tenant isolation columns.

Revision ID: sec_001
Revises: opt_001
Create Date: 2026-02-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "sec_001"
down_revision: str | None = "opt_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add tenant_id to agent_evaluation_results
    op.add_column(
        "agent_evaluation_results",
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"),
    )
    op.create_index(
        "ix_agent_evaluation_results_tenant_id",
        "agent_evaluation_results",
        ["tenant_id"],
    )

    # Add tenant_id to agent_registry
    op.add_column(
        "agent_registry",
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"),
    )
    op.create_index("ix_agent_registry_tenant_id", "agent_registry", ["tenant_id"])

    # Update unique constraint on agent_registry
    op.drop_constraint("uq_agent_registry_name", "agent_registry", type_="unique")
    op.create_unique_constraint(
        "uq_agent_registry_tenant_name", "agent_registry", ["tenant_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_registry_tenant_name", "agent_registry", type_="unique"
    )
    op.create_unique_constraint("uq_agent_registry_name", "agent_registry", ["name"])
    op.drop_index("ix_agent_registry_tenant_id", table_name="agent_registry")
    op.drop_column("agent_registry", "tenant_id")
    op.drop_index(
        "ix_agent_evaluation_results_tenant_id",
        table_name="agent_evaluation_results",
    )
    op.drop_column("agent_evaluation_results", "tenant_id")
