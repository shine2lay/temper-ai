"""Exact-scope process credentials using the existing run-key machinery.

Creation and revocation join C1's fence/session. Authentication never uses a
fallback table, generic guard mode, serialized principal, or WorkflowRun.attempts.
Raw keys remain process-held; neither a context object nor environment carries one.
"""
from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from temper_ai.api import run_tokens
from temper_ai.api.guard_models import RunPrivateKey
from temper_ai.private_context.contracts import RunPrincipal
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure

if TYPE_CHECKING:
    from temper_ai.private_context.authority import RunAuthority
    from temper_ai.private_context.composition import PrivateComposition

KIND = run_tokens.PRIVATE_CONTEXT


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scope(authority: RunAuthority) -> dict:
    p = authority.profile
    return dict(execution_id=authority.execution_id, owner_principal=p.owner_principal,
                namespace=p.namespace, profile=p.profile, profile_revision=p.profile_revision,
                workflow_name=p.workflow, workflow_revision=p.workflow_revision,
                node_path=p.node_path, use="draft", runner_generation=authority.runner_generation)


def stage_private_key_in(session: Session, authority: RunAuthority) -> str:
    """Trusted bootstrap callback only; caller owns fence+commit and raw-key lifetime."""
    deadline = min(authority.deadline_at, authority.profile.credential_deadline)
    if authority.revoked or deadline <= datetime.now(UTC) or authority.runner_generation < 1:
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    raw = KIND.prefix + secrets.token_urlsafe(32)
    old = session.get(run_tokens._model(KIND), authority.execution_id)
    if old is not None:
        session.delete(old)
        session.flush()
    session.add(RunPrivateKey(**_scope(authority), token_hash=run_tokens._digest(raw),
                              expires_at=deadline))
    session.flush()
    return raw


def revoke_private_key_in(session: Session, execution_id: str) -> None:
    """Caller already holds C1 fence; participates in its lifecycle transaction."""
    row = session.get(run_tokens._model(KIND), execution_id)
    if row is not None:
        session.delete(row)
        session.flush()


def open_private_key(execution_id: str, composition: PrivateComposition) -> None:
    """Verify independent runner claim, stage, commit, THEN make key process-held.

    C1 invokes the key effect under its fence and verifies current binding. An
    exception anywhere (including commit) produces no held key. Missing table is
    unavailable, never a successful best-effort issue like legacy start keys.
    """
    from temper_ai.database import get_session

    staged: list[str] = []
    issued: list[RunAuthority] = []

    def issue(given: Session, authority: RunAuthority) -> None:
        if given is not session or staged or authority.execution_id != execution_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        staged.append(stage_private_key_in(given, authority))
        issued.append(authority)

    try:
        with get_session() as session:
            authority = composition.worker_bootstrap_in(session, execution_id, issue)
            if (len(staged) != 1 or issued != [authority]
                    or authority.execution_id != execution_id):
                raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        with run_tokens._lock:
            run_tokens._held[(KIND.table, execution_id)] = staged[0]
    except Exception:
        staged.clear()
        # Fixed error, no traceback/exception prose or bound row values.
        pass
    else:
        staged.clear()
        return
    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)


def close_private_key(execution_id: str) -> None:
    """Forget this process's credential and conditionally retire its exact hash.

    Does not retire a successor's key. Revocation that also changes generation is
    lifecycle_in + revoke_private_key_in, not this terminal credential cleanup.
    """
    from temper_ai.database import get_session

    with run_tokens._lock:
        raw = run_tokens._held.pop((KIND.table, execution_id), None)
    if raw is None:
        return
    try:
        with get_session() as session:
            row = session.get(run_tokens._model(KIND), execution_id)
            if row is not None and row.token_hash == run_tokens._digest(raw):
                session.delete(row)
    except Exception:
        pass
    else:
        return
    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)


def identify_private_key_in(session: Session, raw: str | None) -> RunPrivateKey:
    """Credential row only, not current-run authority; the latter is checked under C1 fence."""
    if not raw or not raw.startswith(KIND.prefix):
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)
    row = session.exec(select(run_tokens._model(KIND)).where(
        RunPrivateKey.token_hash == run_tokens._digest(raw))).first()
    if row is None or _utc(row.expires_at) <= datetime.now(UTC):
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)
    return row


class _WorkerRequest:
    __slots__ = ("principal", "raw")

    def __init__(self, principal: RunPrincipal, raw: str) -> None:
        self.principal, self.raw = principal, raw

    def __repr__(self) -> str:
        return "<verified private worker>"

    def __reduce_ex__(self, protocol):
        raise TypeError("private serialization forbidden")


_worker: ContextVar[_WorkerRequest | None] = ContextVar("private_worker_request", default=None)


@contextmanager
def verified_worker_request(raw: str | None) -> Iterator[RunPrincipal]:
    """Authenticate header before body read; C1 must recheck current scope in its transaction."""
    from temper_ai.database import get_session

    try:
        with get_session() as session:
            row = identify_private_key_in(session, raw)
            principal = RunPrincipal(execution_id=row.execution_id,
                                     runner_generation=row.runner_generation,
                                     provenance="verified_private_worker_key")
    except PrivateDraftFailure:
        raise
    except Exception:
        pass
    else:
        assert raw is not None
        verified = _WorkerRequest(principal, raw)
        token = _worker.set(verified)
        try:
            yield principal
        finally:
            verified.raw = ""
            _worker.reset(token)
        return
    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)


def require_worker_provenance_in(session: Session, principal: RunPrincipal,
                                 authority: RunAuthority) -> None:
    """C1 authority adapter hook: exact issued object, key still current, full scope equal."""
    current = _worker.get()
    if current is None or current.principal is not principal:
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)
    row = identify_private_key_in(session, current.raw)
    if (principal.execution_id != authority.execution_id
            or principal.runner_generation != authority.runner_generation
            or authority.revoked or authority.deadline_at <= datetime.now(UTC)
            or authority.profile.credential_deadline <= datetime.now(UTC)
            or _utc(row.expires_at) != min(authority.deadline_at, authority.profile.credential_deadline)
            or any(getattr(row, key) != value for key, value in _scope(authority).items())):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
