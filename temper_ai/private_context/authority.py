"""Canonical, inactive authority ports for private custody.

Implementations belong to the server/worker identity integration, not this store.
A principal model is an assertion, NOT a credential. Adapters must independently
verify its provenance (including exact issued-object/request provenance), resolve
configured rights, and retain database locks until the supplied transaction ends.
No default adapter, profile registry, key lookup or import-time I/O exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlmodel import Session

from .contracts import CallerPrincipal, RunPrincipal
from .schema import SchemaArtifact


@dataclass(frozen=True, repr=False)
class ProfileAuthority:
    """Adapter-owned configured scope, never constructed from request fields.

    credential_deadline is the verified authority's existing validity deadline,
    not a service-imposed TTL. SchemaArtifact is an explicitly supplied snapshot.
    Configuration changes/revocations must participate in the same lock order as
    these lookups; a separate check followed by an unrelated commit is invalid.
    """

    owner_principal: str
    namespace: str
    profile: str
    profile_revision: str
    workflow: str
    workflow_revision: str
    node_path: str
    schema: SchemaArtifact
    credential_deadline: datetime


@dataclass(frozen=True, repr=False)
class RunAuthority:
    """Current, locked run state from the real run store (including revoked state).

    Returning revoked state lets scoped status/deletion remain available. C1 must
    reject private reads/effects when revoked or past either deadline. The adapter
    must deny a foreign run rather than returning its state to a caller.
    """

    profile: ProfileAuthority
    execution_id: str
    runner_generation: int
    deadline_at: datetime
    revoked: bool


class PrivateAuthority(Protocol):
    """Locks current authority in the *caller-owned* SQLModel transaction.

    C1 acquires MetadataStore.fence_in(session) BEFORE invoking these methods.
    Adapters and cancellation/generation/profile/key writers must take that same
    fence first, then their authority/run locks. They never commit/rollback/close
    session. All relevant state must be fenced until its transaction ends.
    An adapter unable to uphold this (including cross-store state) raises fixed
    CONTEXT_UNAVAILABLE. Missing keys/config raise UNAUTHENTICATED/SCOPE_DENIED
    or CONTEXT_UNAVAILABLE, never authorize from a supplied label or boolean.

    Production adapters independently verify issued principal provenance on every
    call. Value-equal forged principal objects do not acquire authority. Caller
    binding verifies the exact configured workflow/node/profile against the real
    run; run_in verifies the exact private worker credential and current scope.
    """

    def caller_in(self, session: Session, caller: CallerPrincipal) -> ProfileAuthority: ...

    def binding_in(self, session: Session, caller: CallerPrincipal, execution_id: str) -> RunAuthority: ...

    def run_in(self, session: Session, principal: RunPrincipal) -> RunAuthority: ...

    def bootstrap_in(self, session: Session, execution_id: str) -> RunAuthority:
        """Independently verify a trusted runner claim for this exact execution.

        The adapter verifies current generation and runner provenance in the same
        transaction. ID possession is never sufficient. Missing claim or shared
        fence raises CONTEXT_UNAVAILABLE; no default runner is supplied here.
        """
        ...
