"""Owned volatile buffers and issued-object custody. No persistence/recovery.

One explicitly shared mailbox per service process; use its lock for every access.
Closing drops owned references, not copies already delivered to a private caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import PrivateBinding, PrivateLease, RunPrincipal, SendReservation
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .wire import PrivateResult, RegisterContext


@dataclass(frozen=True, repr=False)
class LeaseCustody:
    lease: PrivateLease
    binding: PrivateBinding
    principal: RunPrincipal
    lease_id: str


class VolatileMailbox:
    def __init__(self) -> None:
        self.lock = RLock()
        self.contexts: dict[str, RegisterContext] = {}
        self.results: dict[str, PrivateResult] = {}
        self.leases: dict[int, LeaseCustody] = {}
        self.reservations: dict[int, tuple[SendReservation, LeaseCustody]] = {}

    def __repr__(self) -> str:
        return "<VolatileMailbox>"

    def context(self, context_ref: str) -> RegisterContext:
        value = self.contexts.get(context_ref)
        if value is None:
            raise PrivateDraftFailure(Code.CONTEXT_LOST)
        return value

    def result(self, context_ref: str) -> PrivateResult:
        value = self.results.get(context_ref)
        if value is None:
            raise PrivateDraftFailure(Code.RESULT_LOST)
        return value

    def lease(self, lease: PrivateLease) -> LeaseCustody:
        record = self.leases.get(id(lease))
        if record is None or record.lease is not lease:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return record

    def reservation(self, reservation: SendReservation) -> LeaseCustody:
        record = self.reservations.get(id(reservation))
        if record is None or record[0] is not reservation:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return record[1]

    def drop(self, context_ref: str, *, keep_result: bool = False) -> None:
        context = self.contexts.pop(context_ref, None)
        if context is not None:
            context.close()
        if not keep_result:
            result = self.results.pop(context_ref, None)
            if result is not None:
                result.close()
        self.drop_leases(context_ref)

    def drop_leases(self, context_ref: str) -> None:
        """Invalidate worker handles without destroying the registered snapshot."""
        for key, record in list(self.leases.items()):
            if record.binding.context_ref == context_ref:
                record.lease.close()
                del self.leases[key]
        for key, (_, record) in list(self.reservations.items()):
            if record.binding.context_ref == context_ref:
                del self.reservations[key]

    def refresh_principal(self, held: LeaseCustody, principal: RunPrincipal) -> None:
        """After independent current verification, retain this request's provenance.

        C2 principals are request-local. This is not authentication: the service
        has already checked exact scope, generation, deadline and revocation.
        """
        current = LeaseCustody(held.lease, held.binding, principal, held.lease_id)
        self.leases[id(held.lease)] = current
        for key, (reservation, record) in list(self.reservations.items()):
            if record.lease is held.lease:
                self.reservations[key] = (reservation, current)

    def close(self) -> None:
        with self.lock:
            refs = set(self.contexts) | set(self.results) | {record.binding.context_ref for record in self.leases.values()}
            for context_ref in refs:
                self.drop(context_ref)
