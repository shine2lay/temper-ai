"""Concrete transactional C1/C2 join; no transport, identity registry or defaults.

Use PrivateContextComposition(service) as C2's composition dependency. All writes
use the service fence first. Caller-owned operations never commit/rollback or
publish keys/dispatch work; the outer owner must roll back on any failure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlmodel import Session, col, select

from .authority import ProfileAuthority, RunAuthority
from .contracts import (
    CallerPrincipal,
    PrivateBinding,
    PrivateLease,
    RunPrincipal,
    SendReservation,
)
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .models import PrivateContextRow
from .scope import current_run, live, row_scope, run_scope
from .store import instant

if TYPE_CHECKING:
    from .composition import (
        BindingAdmission,
        LifecycleEffect,
        QueueBound,
        ScopeAuthorizer,
        WorkerKeyEffect,
    )
    from .service import PrivateContextService


class PrivateContextComposition:
    def __init__(self, service: PrivateContextService) -> None:
        self.service = service

    def caller_for_context(self, context_ref: str, authorize: ScopeAuthorizer) -> CallerPrincipal:
        service = self.service
        found: list[tuple[PrivateContextRow, CallerPrincipal]] = []

        def authenticate(session: Session) -> ProfileAuthority:
            row = service.store.context_in(session, context_ref)
            caller = authorize(row.owner_principal, row.namespace, row.profile)
            profile = service._caller(session, caller)
            found.append((row, caller))
            return profile

        def effect(session: Session, profile: ProfileAuthority) -> CallerPrincipal:
            row, caller = found[0]
            row_scope(row, profile)
            return caller

        return service._perform("caller_lookup", authenticate, effect)

    def binding_for_run(self, execution_id: str, authorize: ScopeAuthorizer) -> PrivateBinding:
        service = self.service
        found: list[tuple[PrivateContextRow, CallerPrincipal]] = []

        def authenticate(session: Session) -> ProfileAuthority:
            row = service.store.execution_in(session, execution_id)
            caller = authorize(row.owner_principal, row.namespace, row.profile)
            profile = service._caller(session, caller)
            found.append((row, caller))
            return profile

        def effect(session: Session, profile: ProfileAuthority) -> PrivateBinding:
            row, caller = found[0]
            row_scope(row, profile)
            service._bound_run(session, caller, row)
            return service.store.binding_in(session, row)

        return service._perform("binding_lookup", authenticate, effect)

    def bind_and_queue_in(self, session: Session, caller: CallerPrincipal,
                          context_ref: str, context_version: int, execution_id: str,
                          profile_revision: str, queue: QueueBound) -> BindingAdmission:
        # Imported only when used; declaration belongs to C2, never duplicated.
        from .composition import BindingAdmission

        service = self.service

        def effect() -> BindingAdmission:
            profile = service._caller(session, caller)
            row = service.store.context_in(session, context_ref)
            row_scope(row, profile)
            if row.context_version != context_version or row.profile_revision != profile_revision:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            live(row, service.clock())
            if row.execution_id is not None:
                # Exact authorized retry, including ready/lost send history. No
                # callback, second run, dispatch or fresh payload is authorized.
                run = service._bound_run(session, caller, row)
                live(row, service.clock(), run)
                return BindingAdmission(service.store.binding_in(session, row), False)
            service.mailbox.context(row.context_ref)
            other = session.exec(select(PrivateContextRow).where(
                PrivateContextRow.execution_id == execution_id,
                col(PrivateContextRow.replacement_ref).is_(None),
            )).first()
            if other is not None:
                raise PrivateDraftFailure(Code.CONTEXT_CONFLICT)
            # The callback stages the actual normal run. Its success is not
            # authority; _bind independently checks the staged current run.
            queue(session, execution_id)
            binding = service._bind(session, caller, profile, context_ref,
                                    context_version, execution_id, profile_revision)
            return BindingAdmission(binding, True)

        return service._in_session(session, effect)

    def lifecycle_in(self, session: Session, caller: CallerPrincipal,
                     execution_id: str, action: Literal["resume", "fork", "cancel"],
                     effect: LifecycleEffect) -> PrivateBinding:
        service = self.service

        def transition() -> PrivateBinding:
            profile = service._caller(session, caller)
            row = service.store.execution_in(session, execution_id)
            row_scope(row, profile)
            before = service._bound_run(session, caller, row)
            if before is None or action not in {"cancel", "resume"}:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            if action == "resume":
                # Never reset terminal/lost state or allow a new invocation.
                # Possible-send evidence may be resumed only as that SAME
                # evidence. resolve/reserve independently forbid regeneration.
                live(row, service.clock(), before)
                if row.context_ref not in service.mailbox.results:
                    service.mailbox.context(row.context_ref)
            # C1 owns the canonical private lifecycle fields, never normal run
            # retry counters. Freeze all other metadata before calling C2; its
            # normal-run/key effect cannot rewrite private send/loss history.
            if action == "resume":
                row.runner_generation = before.runner_generation + 1
            else:
                row.revoked = True
            expected_row = row.model_dump()
            session.add(row)
            session.flush()
            expected_binding = service.store.binding_in(session, row)
            effect(session, expected_binding)
            session.flush()
            session.refresh(row)
            # Independent configured authority + actual run + provenance are
            # still required. Reading our own staged generation is not identity.
            after = service._adapter().binding_in(session, caller, execution_id)
            run_scope(after, None, service.clock())
            row_scope(row, after.profile)
            if (row.model_dump() != expected_row
                    or service.store.binding_in(session, row) != expected_binding
                    or after.execution_id != execution_id
                    or after.deadline_at != before.deadline_at
                    or after.runner_generation != expected_binding.runner_generation):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            if action == "cancel":
                if not after.revoked:
                    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
                service.mailbox.drop(row.context_ref)
            else:
                if after.revoked:
                    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
                if service.clock() >= after.deadline_at:
                    raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
                service.mailbox.drop_leases(row.context_ref)
            return expected_binding

        return service._in_session(session, transition)

    def worker_bootstrap_in(self, session: Session, execution_id: str,
                            effect: WorkerKeyEffect) -> RunAuthority:
        service = self.service

        def bootstrap() -> RunAuthority:
            authority = service._adapter().bootstrap_in(session, execution_id)
            run_scope(authority, None, service.clock())
            row = service.store.execution_in(session, execution_id)
            current_run(row, authority)
            live(row, service.clock(), authority)
            effect(session, authority)
            # A key callback cannot silently mutate scope/generation/revocation.
            after = service._adapter().bootstrap_in(session, execution_id)
            run_scope(after, None, service.clock())
            current_run(row, after)
            live(row, service.clock(), after)
            if after != authority:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            return after

        return service._in_session(session, bootstrap)

    def worker_current_in(self, session: Session, principal: RunPrincipal) -> RunAuthority:
        service = self.service

        def current() -> RunAuthority:
            authority = service._run(session, principal)
            row = service.store.execution_in(session, authority.execution_id)
            current_run(row, authority)
            live(row, service.clock(), authority)
            return authority

        return service._in_session(session, current)

    def worker_lease(self, principal: RunPrincipal, lease_id: str) -> PrivateLease:
        service = self.service

        def effect(session: Session, run: RunAuthority) -> PrivateLease:
            held = next((record for record in service.mailbox.leases.values()
                         if record.lease_id == lease_id), None)
            if held is None:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            service._lease_row(session, held.lease, run)
            service.mailbox.refresh_principal(held, principal)
            return held.lease

        return service._perform("worker_lease", lambda session: service._run(session, principal), effect)

    def worker_reservation(self, principal: RunPrincipal, invocation_id: str,
                           attempt_id: str) -> SendReservation:
        service = self.service

        def effect(session: Session, run: RunAuthority) -> SendReservation:
            record = next(((reservation, held) for reservation, held in service.mailbox.reservations.values()
                           if (reservation.invocation_id, reservation.attempt_id,
                               reservation.execution_id, reservation.runner_generation)
                           == (invocation_id, attempt_id, run.execution_id, run.runner_generation)), None)
            if record is None:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            reservation, held = record
            service._lease_row(session, held.lease, run)
            if service.clock() >= instant(reservation.deadline_at):
                raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
            service.mailbox.refresh_principal(held, principal)
            return reservation

        return service._perform("worker_reservation", lambda session: service._run(session, principal), effect)
