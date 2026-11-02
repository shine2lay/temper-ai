"""C2 implementation seam for C1's canonical PrivateAuthority protocol.

The three readers are supplied by E over the canonical configured profile,
independent runner generation, and REAL runner handoff. They participate in
C1's already-held fence/session. No metadata/ID-only bootstrap or successful
fake verifier is installed by this module. No private table is guessed here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Session

from temper_ai.api.private_identity import require_private_caller_provenance
from temper_ai.api.private_worker_keys import require_worker_provenance_in
from temper_ai.private_context.contracts import CallerPrincipal, RunPrincipal
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.wire import PrivateRunInputs, decode_wire
from temper_ai.runner.models import WorkflowRun

if TYPE_CHECKING:
    from temper_ai.private_context.authority import ProfileAuthority, RunAuthority


@dataclass(frozen=True, repr=False)
class PrivateAuthorityAdapter:
    # Readers MUST independently verify configured rights/revisions and locked
    # current authority. None refuses. Never a second identity/profile registry.
    profile_reader_in: Callable[[Session, CallerPrincipal], ProfileAuthority] | None = None
    run_reader_in: Callable[[Session, str], RunAuthority] | None = None
    runner_claim_in: Callable[[Session, str], RunAuthority] | None = None

    def caller_in(self, session: Session, caller: CallerPrincipal) -> ProfileAuthority:
        name = require_private_caller_provenance(caller)
        if self.profile_reader_in is None:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        profile = self.profile_reader_in(session, caller)
        if ((profile.owner_principal, profile.namespace, profile.profile)
                != (name, caller.namespace, caller.profile)
                or profile.credential_deadline <= datetime.now(UTC)):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return profile

    def _run_in(self, session: Session, execution_id: str) -> RunAuthority:
        if self.run_reader_in is None:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        authority = self.run_reader_in(session, execution_id)
        row = session.get(WorkflowRun, execution_id)
        if (row is None or authority.execution_id != execution_id
                or row.workflow_name != authority.profile.workflow
                or authority.runner_generation < 1):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        # A normal workflow cannot be claimed private by inserting a key alone.
        decode_wire(encode_private(row.inputs), PrivateRunInputs)
        return authority

    def binding_in(self, session: Session, caller: CallerPrincipal, execution_id: str) -> RunAuthority:
        profile = self.caller_in(session, caller)
        authority = self._run_in(session, execution_id)
        if authority.profile != profile:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        # Owned revoked/terminal state can be inspected by C1 status/delete. C1
        # independently rejects it for payload/effects, never a blanket bypass.
        return authority

    def run_in(self, session: Session, principal: RunPrincipal) -> RunAuthority:
        authority = self._run_in(session, principal.execution_id)
        require_worker_provenance_in(session, principal, authority)
        self._active_in(session, authority)
        return authority

    def bootstrap_in(self, session: Session, execution_id: str) -> RunAuthority:
        if self.runner_claim_in is None:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        # Trusted context adapter must verify the actual claim under this fence;
        # its result cannot come from argv/environment/serialized run metadata.
        claimed = self.runner_claim_in(session, execution_id)
        authority = self._run_in(session, execution_id)
        if claimed != authority:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        self._active_in(session, authority)
        return authority

    @staticmethod
    def _active_in(session: Session, authority: RunAuthority) -> None:
        row = session.get(WorkflowRun, authority.execution_id)
        if (row is None or row.status != "running" or row.cancel_requested or authority.revoked
                or authority.deadline_at <= datetime.now(UTC)
                or authority.profile.credential_deadline <= datetime.now(UTC)):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
