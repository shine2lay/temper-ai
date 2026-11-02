"""Exact private scope and validity checks, independent of generic guard mode."""
from datetime import datetime

from .authority import ProfileAuthority, RunAuthority
from .contracts import CallerPrincipal, RunPrincipal
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .models import PrivateContextRow
from .schema import SchemaArtifact
from .store import instant


def profile_fields(profile: ProfileAuthority) -> dict[str, str]:
    if type(profile) is not ProfileAuthority or type(profile.schema) is not SchemaArtifact:
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    return dict(owner_principal=profile.owner_principal, namespace=profile.namespace, profile=profile.profile, profile_revision=profile.profile_revision, context_schema=profile.schema.identity.context_schema, result_schema=profile.schema.identity.result_schema, schema_revision=profile.schema.identity.revision, workflow=profile.workflow, workflow_revision=profile.workflow_revision, node_path=profile.node_path)


def caller_scope(caller: CallerPrincipal, profile: ProfileAuthority, now: datetime) -> None:
    profile_fields(profile)
    if type(caller) is not CallerPrincipal or (caller.principal_id, caller.namespace, caller.profile) != (profile.owner_principal, profile.namespace, profile.profile):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    credential_live(profile, now)


def credential_live(profile: ProfileAuthority, now: datetime) -> None:
    if now >= profile.credential_deadline:
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)


def row_scope(row: PrivateContextRow, profile: ProfileAuthority) -> None:
    if any(getattr(row, name) != value for name, value in profile_fields(profile).items()):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)


def run_scope(run: RunAuthority, principal: RunPrincipal | None, now: datetime) -> None:
    if type(run) is not RunAuthority or type(run.runner_generation) is not int or run.runner_generation < 1:
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    credential_live(run.profile, now)
    if principal is not None and (type(principal) is not RunPrincipal or principal.execution_id != run.execution_id or principal.runner_generation != run.runner_generation):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)


def current_run(row: PrivateContextRow, run: RunAuthority) -> None:
    row_scope(row, run.profile)
    if row.execution_id != run.execution_id or row.runner_generation != run.runner_generation or (row.deadline_at is not None and instant(row.deadline_at) != run.deadline_at):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)


def live(row: PrivateContextRow, now: datetime, run: RunAuthority | None = None, *, acknowledge_retry: bool = False) -> None:
    if row.revoked or (run is not None and run.revoked):
        raise PrivateDraftFailure(Code.CANCELLED)
    if now >= instant(row.expires_at) or (row.deadline_at is not None and now >= instant(row.deadline_at)) or (run is not None and now >= run.deadline_at):
        raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
    if row.state in {"failed", "lost"} or (row.state == "acknowledged" and not acknowledge_retry):
        raise PrivateDraftFailure(Code(row.failure_code) if row.failure_code else Code.RESULT_LOST)
