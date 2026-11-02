"""Inert C1/C2 composition ports; no concrete custody or authority is installed.

C1 implements these ports. C2 supplies verified edge identity and normal queue,
key and lifecycle callbacks. E joins real components and proves their atomicity.
Public v1 wire and the original PrivateContextService remain unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlmodel import Session

from .authority import RunAuthority
from .contracts import (
    CallerPrincipal,
    PrivateBinding,
    PrivateLease,
    RunPrincipal,
    SendReservation,
)

ScopeAuthorizer = Callable[[str, str, str], CallerPrincipal]
QueueBound = Callable[[Session, str], None]
LifecycleEffect = Callable[[Session, PrivateBinding], None]
WorkerKeyEffect = Callable[[Session, RunAuthority], None]


@dataclass(frozen=True, repr=False)
class BindingAdmission:
    binding: PrivateBinding
    created: bool


class PrivateComposition(Protocol):
    """All effects share C1's fence BEFORE authority/run locks, in caller's session.

    No callback commits, rolls back, dispatches or closes the supplied session.
    Refusals propagate; the outer owner rolls back all earlier effects. Missing
    current authority/transaction proof is unavailable, never a fallback store.
    """

    def caller_for_context(self, context_ref: str, authorize: ScopeAuthorizer) -> CallerPrincipal:
        """Read metadata only; authorize before exposing it; independently verify caller."""
        ...

    def binding_for_run(self, execution_id: str, authorize: ScopeAuthorizer) -> PrivateBinding: ...

    def bind_and_queue_in(self, session: Session, caller: CallerPrincipal,
                          context_ref: str, context_version: int, execution_id: str,
                          profile_revision: str, queue: QueueBound) -> BindingAdmission:
        """Fenced new/retry choice. Retry returns original binding, no callback.

        New invokes queue once with the allocated execution_id, then independently verifies the actual staged run
        through authority.binding_in. Final-check failure rolls back binding AND
        queue. Dispatch occurs only after the outer commit. Never infer created
        from a separate read or assume callback success proves staged-run scope.
        """
        ...

    def lifecycle_in(self, session: Session, caller: CallerPrincipal,
                     execution_id: str, action: Literal["resume", "fork", "cancel"],
                     effect: LifecycleEffect) -> PrivateBinding:
        """Fork always refuses before effect. Cancel revokes without a payload lease.

        Resume keeps execution/scope and all invocation/send/loss history; advances
        a separately maintained generation and revokes old credentials under this
        fence. WorkflowRun.attempts is NOT authority. Possible-send state never
        authorizes regeneration. No content cloning into a successor run.
        """
        ...

    def worker_bootstrap_in(self, session: Session, execution_id: str,
                            effect: WorkerKeyEffect) -> RunAuthority:
        """Verify independent runner claim via authority.bootstrap_in, then stage key.

        Verify returned current state against binding. ID/metadata possession is
        not runner provenance; absent claim/fence is unavailable. No usable key
        escapes before outer commit; failed effect/verification/commit issues none.
        """
        ...

    def worker_current_in(self, session: Session, principal: RunPrincipal) -> RunAuthority: ...

    def worker_lease(self, principal: RunPrincipal, lease_id: str) -> PrivateLease:
        """Authenticate current exact scope, then resolve authoritative opaque custody."""
        ...

    def worker_reservation(self, principal: RunPrincipal, invocation_id: str,
                           attempt_id: str) -> SendReservation:
        """Bind handle to execution+current generation+invocation+attempt; no reconstruction."""
        ...
