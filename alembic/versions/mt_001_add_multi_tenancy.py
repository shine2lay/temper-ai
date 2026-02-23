"""Add multi-tenancy tables and tenant_id columns.

Revision ID: mt_001
Revises: opt_001
Create Date: 2026-02-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "mt_001"
down_revision: str | None = "opt_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default tenant ID used for backfilling existing rows
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    # ── 1. Core tenancy tables ────────────────────────────────────

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("plan", sa.String(64), nullable=False, server_default="free"),
        sa.Column("max_workflows", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_is_active", "tenants", ["is_active"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(256), nullable=False, server_default=""),
        sa.Column("oauth_provider", sa.String(64), nullable=True),
        sa.Column("oauth_subject", sa.String(256), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name="membership_valid_role",
        ),
    )
    op.create_index(
        "ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"]
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])
    op.create_index(
        "idx_membership_tenant_role", "tenant_memberships", ["tenant_id", "role"]
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(128), nullable=False, server_default="default"),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_is_active", "api_keys", ["is_active"])
    op.create_index("idx_api_keys_hash_active", "api_keys", ["key_hash", "is_active"])

    # ── 2. DB-backed config storage tables ────────────────────────

    for table_name, uq_name, version_ck in [
        (
            "workflow_configs",
            "uq_workflow_configs_tenant_name",
            "workflow_configs_valid_version",
        ),
        (
            "stage_configs",
            "uq_stage_configs_tenant_name",
            "stage_configs_valid_version",
        ),
        (
            "agent_configs",
            "uq_agent_configs_tenant_name",
            "agent_configs_valid_version",
        ),
    ]:
        op.create_table(
            table_name,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(256), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("config_data", sa.JSON(), nullable=False),
            sa.Column(
                "created_by",
                sa.String(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "updated_by",
                sa.String(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "name", name=uq_name),
            sa.CheckConstraint("version >= 1", name=version_ck),
        )
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
        op.create_index(f"ix_{table_name}_name", table_name, ["name"])
        op.create_index(f"idx_{table_name}_tenant", table_name, ["tenant_id", "name"])

    # ── 3. Add tenant_id to existing execution tables ─────────────

    _EXISTING_TABLES = [
        "workflow_executions",
        "stage_executions",
        "agent_executions",
        "agent_registry",
        "event_log",
        "event_subscriptions",
    ]
    for table in _EXISTING_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.String(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # ── 4. Insert default tenant ──────────────────────────────────

    tenants = sa.table(
        "tenants",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("plan", sa.String),
        sa.column("max_workflows", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.execute(
        tenants.insert().values(
            id=DEFAULT_TENANT_ID,
            name="Default",
            slug="default",
            is_active=True,
            plan="free",
            max_workflows=100,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # ── 5. Backfill existing rows with default tenant_id ──────────

    for table in _EXISTING_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
            ).bindparams(
                tid=DEFAULT_TENANT_ID,
            )
        )


def downgrade() -> None:
    _EXISTING_TABLES = [
        "workflow_executions",
        "stage_executions",
        "agent_executions",
        "agent_registry",
        "event_log",
        "event_subscriptions",
    ]
    for table in _EXISTING_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")

    for table_name in ["agent_configs", "stage_configs", "workflow_configs"]:
        op.drop_table(table_name)

    op.drop_table("api_keys")
    op.drop_table("tenant_memberships")
    op.drop_table("users")
    op.drop_table("tenants")
