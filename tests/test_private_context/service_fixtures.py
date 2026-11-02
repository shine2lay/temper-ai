"""Explicit synthetic authority adapter, real stores, fixed clock; no defaults."""
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, select

from temper_ai.database import get_database
from temper_ai.private_context.authority import ProfileAuthority, RunAuthority
from temper_ai.private_context.contracts import (
    AttemptOutcome,
    CallerPrincipal,
    NullableUsage,
    RunPrincipal,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.migration import install_metadata
from temper_ai.private_context.models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateInvocationRow,
    PrivateRefusalRow,
)
from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.service import PrivateContextService
from temper_ai.private_context.store import MetadataStore, instant, timestamp
from temper_ai.private_context.wire import ContextRead, RegisterContext, ResultRead

from . import ipd1


class SyntheticAuthorityRow(SQLModel, table=True):
    __tablename__ = "synthetic_private_authority"
    id: int = Field(default=1, primary_key=True)
    enabled: bool = True
    generation: int = 1
    revoked: bool = False
    queued: int = 0
    key_generation: int = 0
    deadline: str = "2098-01-01T00:00:00Z"


class SyntheticAuthority:
    def __init__(self) -> None:
        self.claim_enabled = True
        self.require_queued = False
        self.canonical_lifecycle = False
        self.caller = CallerPrincipal(principal_id="owner-1", namespace="scope-1", profile="synthetic-reply-v1", provenance="verified_named_key")
        self.principal = RunPrincipal(execution_id=ipd1.RUN, runner_generation=1, provenance="verified_private_worker_key")
        self.profile = ProfileAuthority(owner_principal="owner-1", namespace="scope-1", profile="synthetic-reply-v1", profile_revision="profile-v1", workflow="synthetic-reply", workflow_revision="workflow-v1", node_path="writer", schema=ipd1.schemas(), credential_deadline=datetime(2099, 1, 1, tzinfo=UTC))

    def state(self, session):
        state = session.exec(select(SyntheticAuthorityRow).where(SyntheticAuthorityRow.id == 1).with_for_update()).one()
        if not state.enabled:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        return state

    def caller_in(self, session, caller):
        if caller is not self.caller:
            raise PrivateDraftFailure(Code.UNAUTHENTICATED)
        self.state(session)
        return self.profile

    def binding_in(self, session, caller, execution_id):
        self.caller_in(session, caller)
        if self.require_queued and self.state(session).queued != 1:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        if execution_id != self.principal.execution_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return self.run_in(session, self.principal)

    def bootstrap_in(self, session, execution_id):
        if not self.claim_enabled:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        if execution_id != self.principal.execution_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return self.run_in(session, self.principal)

    def run_in(self, session, principal):
        if principal is not self.principal:
            raise PrivateDraftFailure(Code.UNAUTHENTICATED)
        state = self.state(session)
        generation, revoked = state.generation, state.revoked
        if self.canonical_lifecycle:
            binding = session.exec(select(PrivateContextRow).where(PrivateContextRow.execution_id == principal.execution_id)).first()
            if binding is not None:
                generation, revoked = binding.runner_generation, binding.revoked or state.revoked
        return RunAuthority(self.profile, self.principal.execution_id, generation, instant(state.deadline), revoked)


class Harness:
    def __init__(self, engine):
        self.engine = engine
        install_metadata(engine)
        SyntheticAuthorityRow.__table__.create(engine, checkfirst=True)
        with Session(engine) as session, session.begin():
            session.add(SyntheticAuthorityRow())
        self.store = MetadataStore(engine)
        self.authority = SyntheticAuthority()
        self.now = datetime(2090, 1, 1, tzinfo=UTC)
        self.service = PrivateContextService(store=self.store, authority=self.authority, clock=lambda: self.now)
        self.caller = self.authority.caller
        self.principal = self.authority.principal

    def context(self, **changes):
        value = ipd1.registration().open_private()
        value.update(changes)
        return RegisterContext(encode_private(value))

    def bound(self):
        receipt = self.service.register(self.caller, self.context())
        binding = self.service.bind(self.caller, receipt.context_ref, receipt.context_version, ipd1.RUN, "profile-v1")
        return receipt, binding

    def lease(self):
        return self.service.resolve(self.principal, ipd1.RUN, 1, "writer")

    def complete(self):
        receipt, _ = self.bound()
        lease = self.lease()
        invocation = str(uuid4())
        reservation = self.service.reserve_send(lease, invocation, str(uuid4()), 0)
        self.service.finish_attempt(reservation, outcome("complete"))
        draft = self.service.publish(lease, invocation, self.authority.profile.schema.validate_draft(ipd1.draft().to_private_json()))
        return receipt, lease, ResultRead(context_ref=receipt.context_ref, execution_id=ipd1.RUN, draft_ref=draft.draft_ref)

    def change(self, **values):
        with Session(self.engine) as session, session.begin():
            self.store.fence_in(session)
            row = session.get(SyntheticAuthorityRow, 1)
            for key, value in values.items():
                setattr(row, key, value)
            session.add(row)

    def rows(self, model):
        with Session(self.engine) as session:
            return session.exec(select(model)).all()

    def status(self, receipt):
        return self.service.status(self.caller, ContextRead(context_ref=receipt.context_ref, context_version=receipt.context_version))


def outcome(phase, status=None):
    transmission = {"reserved": "ambiguous", "streaming": "ambiguous", "http_refused": "refused", "complete": "complete", "before_reserve": "not_sent"}[phase]
    values = dict(phase=phase, transmission=transmission, request_started=phase in {"streaming", "http_refused", "complete"}, usage=NullableUsage(input_tokens=None, output_tokens=None, total_tokens=None, cache_read_input_tokens=None, cache_creation_input_tokens=None), usage_state="missing", unknown_usage_fields=0)
    if status is not None:
        values["http_status"] = status
    return AttemptOutcome(**values)


def refused(call, code):
    actual = None
    try:
        call()
    except PrivateDraftFailure as failure:
        actual = failure.code
        ipd1.require(failure.__context__ is None and failure.__cause__ is None)
    ipd1.require(actual == code)


@pytest.fixture
def harness(tmp_path):
    base = get_database().engine
    engine = base if base.dialect.name == "postgresql" else create_engine(f"sqlite:///{tmp_path / 'private.sqlite'}", connect_args={"check_same_thread": False, "timeout": 20}, hide_parameters=True)
    value = Harness(engine)
    yield value
    value.service.close()
    if engine is not base:
        engine.dispose()


__all__ = ["harness", "Harness", "SyntheticAuthorityRow", "Code", "outcome", "refused", "replace", "timestamp", "PrivateContextRow", "PrivateInvocationRow", "PrivateAttemptRow", "PrivateRefusalRow"]
