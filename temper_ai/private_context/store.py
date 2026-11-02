"""Explicit metadata repository and transaction fence; no default DB lookup.

All cooperating writers (including C2 authority/run lifecycle writers) take the
single private-state fence first. It orders the still-small private service, not
ordinary runs. PostgreSQL row locking and SQLite's write transaction both hold
this UPDATE lock until the caller commits/rolls back. No hidden commit occurs.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from .authority import ProfileAuthority
from .contracts import AttemptOutcome, PrivateBinding
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateFenceRow,
    PrivateInvocationRow,
    PrivateRefusalRow,
)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    return value.astimezone(UTC).isoformat()


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class MetadataStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def fence_in(self, session: Session) -> None:
        """Public composition fence. Never installs missing tables/rows implicitly."""
        if session.get_bind() is not self.engine:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        with session.no_autoflush:
            changed = session.execute(update(PrivateFenceRow).where(col(PrivateFenceRow.id) == 1).values(revision=PrivateFenceRow.revision + 1).returning(col(PrivateFenceRow.id))).scalar_one_or_none()
        if changed != 1:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)

    def context_in(self, session: Session, context_ref: str) -> PrivateContextRow:
        row = session.get(PrivateContextRow, context_ref, populate_existing=True)
        if row is None:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return row

    def execution_in(self, session: Session, execution_id: str) -> PrivateContextRow:
        row = session.exec(select(PrivateContextRow).where(PrivateContextRow.execution_id == execution_id, col(PrivateContextRow.replacement_ref).is_(None))).first()
        if row is None:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return row

    def registration_in(self, session: Session, profile: ProfileAuthority, application_attempt_id: str) -> PrivateContextRow | None:
        return session.exec(select(PrivateContextRow).where(
            PrivateContextRow.owner_principal == profile.owner_principal,
            PrivateContextRow.namespace == profile.namespace,
            PrivateContextRow.profile == profile.profile,
            PrivateContextRow.application_attempt_id == application_attempt_id,
        )).first()

    def refusal_in(self, session: Session, profile: ProfileAuthority, operation: str, code: Code, now: datetime) -> None:
        session.add(PrivateRefusalRow(id=str(uuid4()), operation=operation, owner_principal=profile.owner_principal, namespace=profile.namespace, profile=profile.profile, code=code.value, occurred_at=timestamp(now)))

    def binding_in(self, session: Session, row: PrivateContextRow) -> PrivateBinding:
        if row.execution_id is None or row.deadline_at is None or row.runner_generation is None:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        invocation = session.get(PrivateInvocationRow, row.execution_id)
        attempt = session.get(PrivateAttemptRow, invocation.attempt_id) if invocation else None
        outcome = AttemptOutcome.model_validate_json(attempt.outcome_metadata) if attempt and attempt.outcome_metadata else None
        return PrivateBinding.model_validate(dict(context_ref=row.context_ref, context_version=row.context_version, execution_id=row.execution_id, owner_principal=row.owner_principal, namespace=row.namespace, profile=row.profile, profile_revision=row.profile_revision, context_schema=row.context_schema, result_schema=row.result_schema, schema_revision=row.schema_revision, workflow=row.workflow, workflow_revision=row.workflow_revision, node_path=row.node_path, use="draft", expires_at=row.expires_at, deadline_at=row.deadline_at, runner_generation=row.runner_generation, revoked=row.revoked, attempt_state=invocation.state if invocation else "unreserved", outcome=outcome))
