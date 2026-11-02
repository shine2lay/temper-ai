"""Additive private custody metadata. No content, content hash or provider text."""
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class PrivateFenceRow(SQLModel, table=True):
    __tablename__ = "private_context_fences"
    id: int = Field(primary_key=True)
    revision: int = 0


class PrivateContextRow(SQLModel, table=True):
    __tablename__ = "private_context_metadata"
    __table_args__ = (UniqueConstraint("owner_principal", "namespace", "profile", "application_attempt_id"),)
    context_ref: str = Field(primary_key=True)
    context_version: int = 1
    owner_principal: str
    namespace: str
    profile: str
    profile_revision: str
    context_schema: str
    result_schema: str
    schema_revision: str
    workflow: str
    workflow_revision: str
    node_path: str
    application_attempt_id: str
    expires_at: str
    execution_id: str | None = Field(default=None, index=True)
    deadline_at: str | None = None
    runner_generation: int | None = None
    revoked: bool = False
    state: str = "registered"
    draft_ref: str | None = None
    failure_code: str | None = None
    replacement_ref: str | None = None


class PrivateInvocationRow(SQLModel, table=True):
    __tablename__ = "private_context_invocations"
    execution_id: str = Field(primary_key=True)
    invocation_id: str = Field(unique=True)
    context_ref: str
    attempt_id: str
    state: str = "reserved"


class PrivateAttemptRow(SQLModel, table=True):
    __tablename__ = "private_context_attempts"
    attempt_id: str = Field(primary_key=True)
    invocation_id: str = Field(index=True)
    execution_id: str
    lease_id: str
    runner_generation: int
    selected_slot: int
    deadline_at: str
    # Closed AttemptOutcome JSON only, never provider response JSON.
    outcome_metadata: str | None = None


class PrivateRefusalRow(SQLModel, table=True):
    __tablename__ = "private_context_refusals"
    id: str = Field(primary_key=True)
    operation: str
    owner_principal: str
    namespace: str
    profile: str
    code: str
    occurred_at: str
