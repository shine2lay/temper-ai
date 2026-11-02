"""Inactive authenticated private service. No routes, providers, timers or defaults.

All effects use the same durable fence and independently verified authority.
Only explicit composition supplies an engine, authority adapter and schema.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlmodel import Session, col, select

from . import invocations
from .authority import PrivateAuthority, ProfileAuthority, RunAuthority
from .contracts import (
    AttemptOutcome,
    CallerPrincipal,
    PrivateBinding,
    PrivateLease,
    ReleaseDisposition,
    RunPrincipal,
    SendReservation,
)
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .mailbox import LeaseCustody, VolatileMailbox
from .models import PrivateContextRow, PrivateInvocationRow
from .private_json import encode_private
from .schema import ValidatedDraft
from .scope import caller_scope, current_run, live, profile_fields, row_scope, run_scope
from .store import MetadataStore, instant, timestamp
from .wire import (
    VERSION,
    AcknowledgedReceipt,
    ContextRead,
    ContextReceipt,
    ContextStatus,
    DraftReceipt,
    FailureReceipt,
    PrivateResult,
    RegisterContext,
    ResultRead,
    RevokedReceipt,
    decode_wire,
)


class PrivateContextService:
    """Concrete implementation of contracts.PrivateContextService.

    This instance owns volatile buffers. Sharing requires explicitly sharing the
    same mailbox, engine and authority adapter. Unknown transaction outcomes drop
    buffers and deny the operation; durable reserved rows still prevent resends.
    """

    def __init__(self, *, store: MetadataStore, authority: PrivateAuthority | None, mailbox: VolatileMailbox | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.authority = authority
        self.mailbox = mailbox if mailbox is not None else VolatileMailbox()
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)

    def __repr__(self) -> str:
        return "<PrivateContextService>"

    def _adapter(self) -> PrivateAuthority:
        if self.authority is None:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        return self.authority

    def _caller(self, session: Session, caller: CallerPrincipal) -> ProfileAuthority:
        profile = self._adapter().caller_in(session, caller)
        caller_scope(caller, profile, self.clock())
        return profile

    def _run(self, session: Session, principal: RunPrincipal) -> RunAuthority:
        run = self._adapter().run_in(session, principal)
        run_scope(run, principal, self.clock())
        return run

    def _perform(self, operation: str, authenticate: Callable[[Session], ProfileAuthority | RunAuthority], effect: Callable[[Session, Any], Any]) -> Any:
        # Raise only outside handlers: DB/adapter exceptions may carry private
        # locals/SQL values. Never chain, log or keep their text.
        code: Code | None = None
        result: Any = None
        try:
            self._adapter()
            with Session(self.store.engine) as session, session.begin():
                self.store.fence_in(session)
                with self.mailbox.lock:
                    authority = authenticate(session)
                    profile = authority.profile if isinstance(authority, RunAuthority) else authority
                    try:
                        with session.begin_nested():
                            result = effect(session, authority)
                    except PrivateDraftFailure as failure:
                        code = failure.code
                    if code is not None:
                        self.store.refusal_in(session, profile, operation, code, self.clock())
        except PrivateDraftFailure as failure:
            code = failure.code
        except Exception:
            # Commit outcome is unknown. Losing buffers is honest; rollback
            # cannot certify that a possible send never happened.
            self.mailbox.close()
            code = Code.CONTEXT_UNAVAILABLE
        if code is not None:
            raise PrivateDraftFailure(code)
        return result

    def _in_session(self, session: Session, effect: Callable[[], Any]) -> Any:
        """Caller owns transaction; fixed failures without commit/rollback/dispatch.

        Always take DB fence before volatile mutex. Caller must roll back the
        entire transaction on refusal, including its prior queue/key writes.
        """
        code: Code | None = None
        result: Any = None
        try:
            self._adapter()
            self.store.fence_in(session)
            with self.mailbox.lock, session.no_autoflush:
                result = effect()
        except PrivateDraftFailure as failure:
            code = failure.code
        except Exception:
            self.mailbox.close()
            code = Code.CONTEXT_UNAVAILABLE
        if code is not None:
            raise PrivateDraftFailure(code)
        return result

    def _receipt(self, row: PrivateContextRow) -> ContextReceipt:
        return ContextReceipt(context_ref=row.context_ref, context_version=row.context_version, expires_at=row.expires_at, profile=row.profile)

    def _draft_receipt(self, row: PrivateContextRow) -> DraftReceipt:
        return DraftReceipt.model_validate(dict(version=VERSION, execution_id=row.execution_id, draft_ref=row.draft_ref, state="ready", expires_at=row.expires_at))

    def _new_registration(self, session: Session, profile: ProfileAuthority, context: RegisterContext, *, version: int = 1) -> PrivateContextRow:
        if type(context) is not RegisterContext:
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)
        value = context.open_private()
        if (value["profile"], value["namespace"], value["context_schema"]) != (profile.profile, profile.namespace, profile.schema.identity.context_schema):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        profile.schema.validate_registration(context)
        if self.clock() >= instant(value["expires_at"]):
            raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
        row = PrivateContextRow(context_ref=str(uuid4()), context_version=version, **profile_fields(profile), application_attempt_id=value["application_attempt_id"], expires_at=timestamp(instant(value["expires_at"])))
        session.add(row)
        self.mailbox.contexts[row.context_ref] = RegisterContext(context.to_private_json())
        return row

    def register(self, caller: CallerPrincipal, context: RegisterContext) -> ContextReceipt:
        def effect(session: Session, profile: ProfileAuthority) -> ContextReceipt:
            if type(context) is not RegisterContext:
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            value = context.open_private()
            existing = self.store.registration_in(session, profile, value["application_attempt_id"])
            if existing is not None:
                row_scope(existing, profile)
                live(existing, self.clock())
                old = self.mailbox.context(existing.context_ref)
                if old.to_private_json() != context.to_private_json():
                    raise PrivateDraftFailure(Code.CONTEXT_CONFLICT)
                return self._receipt(existing)
            return self._receipt(self._new_registration(session, profile, context))
        return self._perform("register", lambda session: self._caller(session, caller), effect)

    def _bound_run(self, session: Session, caller: CallerPrincipal, row: PrivateContextRow) -> RunAuthority | None:
        if row.execution_id is None:
            return None
        run = self._adapter().binding_in(session, caller, row.execution_id)
        run_scope(run, None, self.clock())
        current_run(row, run)
        return run

    def _bind(self, session: Session, caller: CallerPrincipal, profile: ProfileAuthority, context_ref: str, context_version: int, execution_id: str, profile_revision: str) -> PrivateBinding:
        row = self.store.context_in(session, context_ref)
        row_scope(row, profile)
        if row.context_version != context_version or row.profile_revision != profile_revision:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        run = self._adapter().binding_in(session, caller, row.execution_id or execution_id)
        run_scope(run, None, self.clock())
        row_scope(row, run.profile)
        if run.execution_id != (row.execution_id or execution_id):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        live(row, self.clock(), run)
        self.mailbox.context(row.context_ref)
        if row.execution_id is not None:
            current_run(row, run)
            return self.store.binding_in(session, row)
        other = session.exec(select(PrivateContextRow).where(PrivateContextRow.execution_id == run.execution_id, col(PrivateContextRow.replacement_ref).is_(None))).first()
        if other is not None:
            raise PrivateDraftFailure(Code.CONTEXT_CONFLICT)
        row.execution_id = run.execution_id
        row.runner_generation = run.runner_generation
        row.deadline_at = timestamp(run.deadline_at)
        row.state = "bound"
        session.add(row)
        return self.store.binding_in(session, row)

    def bind_in(self, session: Session, caller: CallerPrincipal, context_ref: str, context_version: int, execution_id: str, profile_revision: str) -> PrivateBinding:
        """Compose queue writes; caller owns commit/rollback and dispatch-after-commit.

        Take fence BEFORE normal run writes. This method never commits, rolls back
        or flushes earlier unrelated writes on refusal. Caller must roll back its
        queue transaction on refusal. For durable refusal audit after that rollback,
        use record_binding_refusal; it reauthenticates in its own transaction.
        """
        return self._in_session(session, lambda: self._bind(session, caller, self._caller(session, caller), context_ref, context_version, execution_id, profile_revision))

    def record_binding_refusal(self, caller: CallerPrincipal, code: Code) -> None:
        if type(code) is not Code:
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)
        self._perform("bind_refusal", lambda session: self._caller(session, caller), lambda session, profile: self.store.refusal_in(session, profile, "bind", code, self.clock()))

    def bind(self, caller: CallerPrincipal, context_ref: str, context_version: int, execution_id: str, profile_revision: str) -> PrivateBinding:
        return self._perform("bind", lambda session: self._caller(session, caller), lambda session, profile: self._bind(session, caller, profile, context_ref, context_version, execution_id, profile_revision))

    def resolve(self, run_principal: RunPrincipal, execution_id: str, running_attempt: int, node_path: str, use: Literal["draft"] = "draft") -> PrivateLease:
        def effect(session: Session, run: RunAuthority) -> PrivateLease:
            if (execution_id, running_attempt, node_path, use) != (run.execution_id, run.runner_generation, run.profile.node_path, "draft"):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            row = self.store.execution_in(session, execution_id)
            current_run(row, run)
            live(row, self.clock(), run)
            invocation = session.get(PrivateInvocationRow, execution_id)
            if invocation is not None and invocation.state != "refused":
                raise PrivateDraftFailure(Code.RESULT_LOST if invocation.state == "complete" else Code.SEND_AMBIGUOUS)
            binding = self.store.binding_in(session, row)
            context = RegisterContext(self.mailbox.context(row.context_ref).to_private_json())
            lease = PrivateLease(lease_id=str(uuid4()), binding=binding, context=context)
            self.mailbox.leases[id(lease)] = LeaseCustody(lease, binding, run_principal, lease.lease_id)
            return lease
        return self._perform("resolve", lambda session: self._run(session, run_principal), effect)

    def _lease_authority(self, session: Session, lease: PrivateLease) -> RunAuthority:
        return self._run(session, self.mailbox.lease(lease).principal)

    def _lease_row(self, session: Session, lease: PrivateLease, run: RunAuthority) -> PrivateContextRow:
        held = self.mailbox.lease(lease)
        row = self.store.context_in(session, held.binding.context_ref)
        current_run(row, run)
        if row.context_version != held.binding.context_version or held.binding.runner_generation != run.runner_generation:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        live(row, self.clock(), run)
        return row

    def reserve_send(self, lease: PrivateLease, invocation_id: str, attempt_id: str, selected_slot: int) -> SendReservation:
        def effect(session: Session, run: RunAuthority) -> SendReservation:
            row = self._lease_row(session, lease, run)
            held = self.mailbox.lease(lease)
            # Build from the captured binding, never mutable public lease fields.
            reservation = SendReservation(lease_id=held.lease_id, execution_id=run.execution_id, invocation_id=invocation_id, attempt_id=attempt_id, runner_generation=run.runner_generation, selected_slot=selected_slot, deadline_at=timestamp(run.deadline_at))
            invocations.reserve_in(session, row, reservation)
            self.mailbox.reservations[id(reservation)] = (reservation, held)
            return reservation
        return self._perform("reserve", lambda session: self._lease_authority(session, lease), effect)

    def finish_attempt(self, reservation: SendReservation, outcome_metadata: AttemptOutcome) -> None:
        def effect(session: Session, run: RunAuthority) -> None:
            held = self.mailbox.reservation(reservation)
            self._lease_row(session, held.lease, run)
            if type(outcome_metadata) is not AttemptOutcome:
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            checked = decode_wire(outcome_metadata.model_dump_json(warnings=False).encode(), AttemptOutcome)
            invocations.finish_in(session, reservation, checked)
        self._perform("finish", lambda session: self._run(session, self.mailbox.reservation(reservation).principal), effect)

    def publish(self, lease: PrivateLease, invocation_id: str, validated_result: ValidatedDraft) -> DraftReceipt:
        def effect(session: Session, run: RunAuthority) -> DraftReceipt:
            row = self._lease_row(session, lease, run)
            invocations.require_complete(session, row, invocation_id)
            if type(validated_result) is not ValidatedDraft:
                raise PrivateDraftFailure(Code.OUTPUT_INVALID)
            draft = run.profile.schema.validate_draft(validated_result.to_private_json())
            if row.draft_ref is not None:
                old = self.mailbox.result(row.context_ref).open_private()
                if old["draft"] != draft.open_private():
                    raise PrivateDraftFailure(Code.OUTPUT_INVALID)
                return self._draft_receipt(row)
            row.draft_ref = str(uuid4())
            self.mailbox.results[row.context_ref] = PrivateResult(encode_private(dict(version=VERSION, execution_id=row.execution_id, draft_ref=row.draft_ref, result_schema=row.result_schema, draft=draft.open_private())))
            row.state = "ready"
            session.add(row)
            return self._draft_receipt(row)
        return self._perform("publish", lambda session: self._lease_authority(session, lease), effect)

    def _read_row(self, session: Session, caller: CallerPrincipal, profile: ProfileAuthority, read: ResultRead) -> tuple[PrivateContextRow, RunAuthority | None]:
        row = self.store.context_in(session, read.context_ref)
        row_scope(row, profile)
        if (row.execution_id, row.draft_ref) != (read.execution_id, read.draft_ref):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return row, self._bound_run(session, caller, row)

    def result(self, caller: CallerPrincipal, read: ResultRead) -> PrivateResult:
        def effect(session: Session, profile: ProfileAuthority) -> PrivateResult:
            row, run = self._read_row(session, caller, profile, read)
            live(row, self.clock(), run)
            return PrivateResult(self.mailbox.result(row.context_ref).to_private_json())
        return self._perform("result", lambda session: self._caller(session, caller), effect)

    def ack(self, caller: CallerPrincipal, read: ResultRead) -> AcknowledgedReceipt:
        def effect(session: Session, profile: ProfileAuthority) -> AcknowledgedReceipt:
            row, run = self._read_row(session, caller, profile, read)
            live(row, self.clock(), run, acknowledge_retry=True)
            if row.state != "acknowledged":
                self.mailbox.result(row.context_ref)
                row.state = "acknowledged"
                session.add(row)
            self.mailbox.drop(row.context_ref)
            return AcknowledgedReceipt.model_validate(dict(version=VERSION, draft_ref=read.draft_ref, state="acknowledged"))
        return self._perform("ack", lambda session: self._caller(session, caller), effect)

    def delete(self, caller: CallerPrincipal, context_ref: str) -> RevokedReceipt:
        def effect(session: Session, profile: ProfileAuthority) -> RevokedReceipt:
            row = self.store.context_in(session, context_ref)
            row_scope(row, profile)
            self._bound_run(session, caller, row)
            row.revoked = True
            row.state = "cancelled"
            row.failure_code = Code.CANCELLED.value
            session.add(row)
            self.mailbox.drop(row.context_ref)
            return RevokedReceipt(context_ref=context_ref, state="revoked")
        return self._perform("delete", lambda session: self._caller(session, caller), effect)

    def status(self, caller: CallerPrincipal, context: ContextRead) -> ContextStatus:
        def effect(session: Session, profile: ProfileAuthority) -> ContextStatus:
            row = self.store.context_in(session, context.context_ref)
            row_scope(row, profile)
            if row.context_version != context.context_version:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            run = self._bound_run(session, caller, row)
            if row.state != "acknowledged":
                if row.revoked or (run and run.revoked):
                    row.state, row.failure_code = "cancelled", Code.CANCELLED.value
                elif self.clock() >= instant(row.expires_at) or (run and self.clock() >= run.deadline_at):
                    row.state, row.failure_code = "expired", Code.CONTEXT_EXPIRED.value
                elif row.draft_ref and row.context_ref not in self.mailbox.results:
                    row.state, row.failure_code = "lost", Code.RESULT_LOST.value
                elif row.context_ref not in self.mailbox.contexts and row.state != "ready":
                    invocation = session.get(PrivateInvocationRow, row.execution_id) if row.execution_id else None
                    if invocation is None or invocation.state == "refused":
                        code = Code.CONTEXT_LOST
                    elif invocation.state == "complete":
                        code = Code.RESULT_LOST
                    else:
                        code = Code.SEND_AMBIGUOUS
                    row.state, row.failure_code = "lost", code.value
                if row.state in {"cancelled", "expired", "lost"}:
                    self.mailbox.drop(row.context_ref)
                session.add(row)
            extra: dict[str, Any] = {}
            if row.state == "ready":
                extra["receipt"] = self._draft_receipt(row)
            elif row.state in {"cancelled", "expired", "failed", "lost"}:
                invocation = session.get(PrivateInvocationRow, row.execution_id) if row.execution_id else None
                transmission = "not_sent" if invocation is None else "complete" if invocation.state == "complete" else "refused" if invocation.state == "refused" else "ambiguous"
                if row.failure_code is None:
                    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
                extra["failure"] = FailureReceipt.model_validate(dict(version=VERSION, code=Code(row.failure_code), retry_class="terminal", transmission=transmission))
            return ContextStatus.model_validate(dict(context_ref=row.context_ref, context_version=row.context_version, execution_id=row.execution_id, state=row.state, **extra))
        return self._perform("status", lambda session: self._caller(session, caller), effect)

    def release(self, lease: PrivateLease, disposition: ReleaseDisposition) -> None:
        def effect(session: Session, run: RunAuthority) -> None:
            held = self.mailbox.lease(lease)
            row = self.store.context_in(session, held.binding.context_ref)
            current_run(row, run)
            if disposition not in {"completed", "failed", "cancelled", "expired", "revoked", "lost"}:
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            if disposition == "completed":
                if row.state != "ready":
                    raise PrivateDraftFailure(Code.RESULT_LOST)
            else:
                row.revoked = True
                row.state = "expired" if disposition == "expired" else "lost" if disposition == "lost" else "failed" if disposition == "failed" else "cancelled"
                row.failure_code = (Code.CONTEXT_EXPIRED if disposition == "expired" else Code.RESULT_LOST if disposition == "lost" else Code.CANCELLED).value
                session.add(row)
            self.mailbox.drop(row.context_ref, keep_result=disposition == "completed")
        self._perform("release", lambda session: self._lease_authority(session, lease), effect)

    def replace(self, caller: CallerPrincipal, old: ContextRead, context: RegisterContext) -> ContextReceipt:
        """Explicit pre-send recovery only; new application attempt/ref/version.

        The old binding is revoked atomically. An invocation row of ANY outcome
        permanently forbids replacement; refusal is not a new-context allowance.
        """
        def effect(session: Session, profile: ProfileAuthority) -> ContextReceipt:
            row = self.store.context_in(session, old.context_ref)
            row_scope(row, profile)
            if row.context_version != old.context_version or row.revoked:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            run = self._bound_run(session, caller, row)
            # Explicit context-loss recovery is allowed, but no other terminal
            # state or deadline/revocation is silently reset.
            if row.state not in {"registered", "bound", "lost"} or (row.state == "lost" and row.failure_code != Code.CONTEXT_LOST.value):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            if self.clock() >= instant(row.expires_at) or (run and (run.revoked or self.clock() >= run.deadline_at)):
                raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
            if row.execution_id and session.get(PrivateInvocationRow, row.execution_id) is not None:
                raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
            if type(context) is not RegisterContext:
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            value = context.open_private()
            if self.store.registration_in(session, profile, value["application_attempt_id"]) is not None:
                raise PrivateDraftFailure(Code.CONTEXT_CONFLICT)
            replacement = self._new_registration(session, profile, context, version=row.context_version + 1)
            replacement.execution_id = row.execution_id
            replacement.runner_generation = row.runner_generation
            replacement.deadline_at = row.deadline_at
            replacement.state = "bound" if row.execution_id else "registered"
            row.revoked = True
            row.replacement_ref = replacement.context_ref
            row.state, row.failure_code = "cancelled", Code.CANCELLED.value
            session.add(row)
            session.add(replacement)
            self.mailbox.drop(row.context_ref)
            return self._receipt(replacement)
        return self._perform("replace", lambda session: self._caller(session, caller), effect)

    def cancel(self, principal: RunPrincipal) -> None:
        """Authenticated lifecycle callback; shares the publication fence."""
        def effect(session: Session, run: RunAuthority) -> None:
            row = self.store.execution_in(session, run.execution_id)
            current_run(row, run)
            row.revoked = True
            row.state, row.failure_code = "cancelled", Code.CANCELLED.value
            session.add(row)
            self.mailbox.drop(row.context_ref)
        self._perform("cancel", lambda session: self._run(session, principal), effect)

    def expire(self) -> int:
        """Trusted local-clock housekeeping only; never scheduled by this module.

        No caller content is read. Expiry only reduces access. External run/key
        revocation still requires C2's authority writer to share fence_in.
        """
        code: Code | None = None
        count = 0
        try:
            with Session(self.store.engine) as session, session.begin():
                self.store.fence_in(session)
                with self.mailbox.lock:
                    for row in session.exec(select(PrivateContextRow)).all():
                        if row.state not in {"acknowledged", "expired", "cancelled"} and (self.clock() >= instant(row.expires_at) or (row.deadline_at and self.clock() >= instant(row.deadline_at))):
                            row.state, row.failure_code = "expired", Code.CONTEXT_EXPIRED.value
                            session.add(row)
                            self.mailbox.drop(row.context_ref)
                            count += 1
        except Exception:
            self.mailbox.close()
            code = Code.CONTEXT_UNAVAILABLE
        if code is not None:
            raise PrivateDraftFailure(code)
        return count

    def close(self) -> None:
        """Normal server shutdown: drop buffers; metadata explicitly survives."""
        self.mailbox.close()
