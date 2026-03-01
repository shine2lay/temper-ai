"""Multi-tenant access control database models.

Tables for tenant isolation, user accounts, RBAC memberships,
API key authentication, and DB-backed config storage.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlmodel import Column, Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow

# ── Constants ────────────────────────────────────────────────────────

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
_ROLE_CHECK = f"role IN ('{ROLE_OWNER}', '{ROLE_EDITOR}', '{ROLE_VIEWER}')"

CONFIG_TYPE_WORKFLOW = "workflow"
CONFIG_TYPE_STAGE = "stage"
CONFIG_TYPE_AGENT = "agent"
CONFIG_TYPE_TOOL = "tool"
VALID_CONFIG_TYPES = frozenset(
    {CONFIG_TYPE_WORKFLOW, CONFIG_TYPE_STAGE, CONFIG_TYPE_AGENT, CONFIG_TYPE_TOOL}
)

PROFILE_TYPE_LLM = "llm"
PROFILE_TYPE_SAFETY = "safety"
PROFILE_TYPE_ERROR_HANDLING = "error_handling"
PROFILE_TYPE_OBSERVABILITY = "observability"
PROFILE_TYPE_MEMORY = "memory"
PROFILE_TYPE_BUDGET = "budget"

VALID_PROFILE_TYPES = frozenset(
    {
        PROFILE_TYPE_LLM,
        PROFILE_TYPE_SAFETY,
        PROFILE_TYPE_ERROR_HANDLING,
        PROFILE_TYPE_OBSERVABILITY,
        PROFILE_TYPE_MEMORY,
        PROFILE_TYPE_BUDGET,
    }
)

# Column length constants
_MAX_NAME_LENGTH = 256
_MAX_SLUG_LENGTH = 128
_MAX_PLAN_LENGTH = 64
_MAX_EMAIL_LENGTH = 320
_MAX_ROLE_LENGTH = 32
_MAX_LABEL_LENGTH = 128
_MAX_KEY_PREFIX_LENGTH = 16
_MAX_KEY_HASH_LENGTH = 64
_MAX_OAUTH_PROVIDER_LENGTH = 64
_MAX_OAUTH_SUBJECT_LENGTH = 256

# Foreign key reference constants
_FK_SET_NULL = "SET NULL"
_FK_TENANTS_ID = "tenants.id"
_FK_USERS_ID = "users.id"

# Check constraint constants
_CHECK_VERSION_GTE_1 = "version >= 1"


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


# ── Tenant ───────────────────────────────────────────────────────────


class Tenant(SQLModel, table=True):
    """Organization or workspace for tenant isolation."""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("slug", name="uq_tenants_slug"),)

    id: str = Field(default_factory=_new_id, primary_key=True)
    name: str = Field(max_length=_MAX_NAME_LENGTH)
    slug: str = Field(max_length=_MAX_SLUG_LENGTH, index=True)
    is_active: bool = Field(default=True, index=True)
    plan: str = Field(default="free", max_length=_MAX_PLAN_LENGTH)
    max_workflows: int = Field(default=100)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


# ── User ─────────────────────────────────────────────────────────────


class UserDB(SQLModel, table=True):
    """User account (replaces in-memory UserStore)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: str = Field(default_factory=_new_id, primary_key=True)
    email: str = Field(max_length=_MAX_EMAIL_LENGTH, index=True)
    name: str = Field(default="", max_length=_MAX_NAME_LENGTH)
    oauth_provider: str | None = Field(
        default=None, max_length=_MAX_OAUTH_PROVIDER_LENGTH
    )
    oauth_subject: str | None = Field(
        default=None, max_length=_MAX_OAUTH_SUBJECT_LENGTH
    )
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── Tenant Membership ────────────────────────────────────────────────


class TenantMembership(SQLModel, table=True):
    """User-to-tenant M:N relationship with RBAC role."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
        CheckConstraint(_ROLE_CHECK, name="membership_valid_role"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    role: str = Field(default=ROLE_VIEWER, max_length=_MAX_ROLE_LENGTH)
    created_at: datetime = Field(default_factory=utcnow)


# ── API Key ──────────────────────────────────────────────────────────


class APIKey(SQLModel, table=True):
    """Per-user API key for Bearer token authentication."""

    __tablename__ = "api_keys"

    id: str = Field(default_factory=_new_id, primary_key=True)
    user_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    label: str = Field(default="default", max_length=_MAX_LABEL_LENGTH)
    key_prefix: str = Field(max_length=_MAX_KEY_PREFIX_LENGTH)
    key_hash: str = Field(max_length=_MAX_KEY_HASH_LENGTH, index=True)
    is_active: bool = Field(default=True, index=True)
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    total_requests: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)


# ── DB-backed Config Storage ─────────────────────────────────────────


class WorkflowConfigDB(SQLModel, table=True):
    """Workflow YAML stored as JSONB in the database."""

    __tablename__ = "workflow_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_workflow_configs_tenant_name"),
        CheckConstraint(_CHECK_VERSION_GTE_1, name="workflow_configs_valid_version"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    version: int = Field(default=1)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StageConfigDB(SQLModel, table=True):
    """Stage YAML stored as JSONB in the database."""

    __tablename__ = "stage_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_stage_configs_tenant_name"),
        CheckConstraint(_CHECK_VERSION_GTE_1, name="stage_configs_valid_version"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    version: int = Field(default=1)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentConfigDB(SQLModel, table=True):
    """Agent YAML stored as JSONB in the database."""

    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_configs_tenant_name"),
        CheckConstraint(_CHECK_VERSION_GTE_1, name="agent_configs_valid_version"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    version: int = Field(default=1)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ToolConfigDB(SQLModel, table=True):
    """Tool config stored as JSONB in the database."""

    __tablename__ = "tool_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tool_configs_tenant_name"),
        CheckConstraint(_CHECK_VERSION_GTE_1, name="tool_configs_valid_version"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    version: int = Field(default=1)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── Profile Tables ───────────────────────────────────────────────────


class LLMProfileDB(SQLModel, table=True):
    """LLM/inference profile — provider, model, temperature, context management."""

    __tablename__ = "llm_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_llm_profiles_tenant_name"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SafetyProfileDB(SQLModel, table=True):
    """Safety profile — content filters, guardrails, thresholds."""

    __tablename__ = "safety_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_safety_profiles_tenant_name"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ErrorHandlingProfileDB(SQLModel, table=True):
    """Error handling profile — retry policies, fallbacks, circuit breakers."""

    __tablename__ = "error_handling_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_error_handling_profiles_tenant_name"
        ),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ObservabilityProfileDB(SQLModel, table=True):
    """Observability profile — logging, metrics, tracing configuration."""

    __tablename__ = "observability_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_observability_profiles_tenant_name"
        ),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MemoryProfileDB(SQLModel, table=True):
    """Memory profile — context window, history, retrieval settings."""

    __tablename__ = "memory_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_memory_profiles_tenant_name"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BudgetProfileDB(SQLModel, table=True):
    """Budget profile — cost limits, token budgets, usage quotas."""

    __tablename__ = "budget_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_budget_profiles_tenant_name"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(_FK_TENANTS_ID, ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = Field(default="")
    config_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    updated_by: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(_FK_USERS_ID, ondelete=_FK_SET_NULL),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


PROFILE_DB_MAP: dict[str, type] = {
    "llm": LLMProfileDB,
    "safety": SafetyProfileDB,
    "error_handling": ErrorHandlingProfileDB,
    "observability": ObservabilityProfileDB,
    "memory": MemoryProfileDB,
    "budget": BudgetProfileDB,
}


# ── Indexes ──────────────────────────────────────────────────────────

Index("idx_membership_tenant_role", TenantMembership.tenant_id, TenantMembership.role)
Index("idx_api_keys_hash_active", APIKey.key_hash, APIKey.is_active)  # type: ignore[arg-type]
Index("idx_workflow_configs_tenant", WorkflowConfigDB.tenant_id, WorkflowConfigDB.name)
Index("idx_stage_configs_tenant", StageConfigDB.tenant_id, StageConfigDB.name)
Index("idx_agent_configs_tenant", AgentConfigDB.tenant_id, AgentConfigDB.name)
Index("idx_tool_configs_tenant", ToolConfigDB.tenant_id, ToolConfigDB.name)
Index("idx_llm_profiles_tenant", LLMProfileDB.tenant_id, LLMProfileDB.name)
Index("idx_safety_profiles_tenant", SafetyProfileDB.tenant_id, SafetyProfileDB.name)
Index(
    "idx_error_handling_profiles_tenant",
    ErrorHandlingProfileDB.tenant_id,
    ErrorHandlingProfileDB.name,
)
Index(
    "idx_observability_profiles_tenant",
    ObservabilityProfileDB.tenant_id,
    ObservabilityProfileDB.name,
)
Index("idx_memory_profiles_tenant", MemoryProfileDB.tenant_id, MemoryProfileDB.name)
Index("idx_budget_profiles_tenant", BudgetProfileDB.tenant_id, BudgetProfileDB.name)
