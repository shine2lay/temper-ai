"""Shared private admission guard for HTTP/MCP/internal/worker entry points.

This module owns orchestration, NOT custody or generation. Only C1's fenced
composition can authorize its exact-session queue callback. E installs the real
profile/config/dispatch join; missing components never become a legacy run.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import TypeAdapter, ValidationError
from sqlmodel import Session, select

from temper_ai.private_context.contracts import PrivateBinding
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.runtime import (
    authorize_scope,
    caller_boundary,
    get_private_boundary,
)
from temper_ai.private_context.wire import (
    PrivateRunInputs,
    PrivateRunStart,
    UTCTimestamp,
    decode_wire,
)
from temper_ai.runner.models import WorkflowRun


def private_start_requested(workflow: str | None, inputs: dict | None) -> bool:
    boundary = get_private_boundary()
    return (isinstance(inputs, dict) and "private_context" in inputs) or bool(
        type(workflow) is str and workflow and boundary is not None and boundary.designates(workflow))


def _private_row(row: WorkflowRun | None) -> bool:
    return row is not None and private_start_requested(row.workflow_name, row.inputs)


def private_run_requested(execution_id: str) -> bool:
    from temper_ai.database import get_session

    with get_session() as session:
        return _private_row(session.get(WorkflowRun, execution_id))


@dataclass(frozen=True, repr=False)
class _QueuePermission:
    session: Session
    execution_id: str
    workflow: str
    inputs: dict
    start: str | None


_queue_permission: ContextVar[_QueuePermission | None] = ContextVar("private_queue_permission", default=None)


def check_private_queue_in(session: Session, execution_id: str, workflow: str,
                           workspace: str | None, inputs: dict | None,
                           start: str | None, extra: dict | None) -> None:
    """Before any write/row lock: existing private rows cannot lose their marker.

    An ordinary row read is not a lock. C1 takes its fence before invoking the
    permitted callback, which then acquires the ordinary queue's run lock.
    """
    row = session.get(WorkflowRun, execution_id)
    if not (private_start_requested(workflow, inputs) or _private_row(row)):
        return
    permit = _queue_permission.get()
    if (permit is None or permit.session is not session or permit.execution_id != execution_id
            or permit.workflow != workflow or permit.inputs != inputs or permit.start != start
            or workspace is not None or extra):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    decode_wire(encode_private(inputs), PrivateRunInputs)


def _queue_in(session: Session, execution_id: str, workflow: str, inputs: dict,
              start: str | None = None) -> None:
    from temper_ai.runner.queue import queue_run_in

    permit = _QueuePermission(session, execution_id, workflow, inputs, start)
    token = _queue_permission.set(permit)
    try:
        queue_run_in(session, execution_id, workflow, None, inputs, start=start, lane=None)
        session.flush()
    finally:
        _queue_permission.reset(token)


def _binding_time(value: str) -> datetime:
    """Reuse A's strict UTC wire validator, then convert its validated string."""
    try:
        validated = TypeAdapter(UTCTimestamp).validate_python(value, strict=True)
        return datetime.fromisoformat(validated)
    except (ValidationError, TypeError, ValueError):
        pass
    raise PrivateDraftFailure(Code.CONTEXT_INVALID)


def submit_private_start(request: dict, *, mode: str, execution_id: str | None = None) -> str:
    """Strict pre-persistence preparation for every normal start transport/mode."""
    from temper_ai.database import get_session

    boundary = caller_boundary(get_private_boundary())
    wanted = decode_wire(encode_private(request), PrivateRunStart)
    descriptor = wanted.inputs.private_context
    def authorize(owner, namespace, profile):
        return authorize_scope(boundary, owner, namespace, profile)

    caller = boundary.composition.caller_for_context(descriptor.context_ref, authorize)
    profile = boundary.profile(caller)
    if wanted.workflow != profile.workflow or not boundary.designates(wanted.workflow):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    # Capability/config validation precedes binding/queue/notify/event effects.
    dispatch = boundary.prepare_dispatch(mode)
    if not callable(dispatch):
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    allocated = execution_id or str(uuid.uuid4())
    inputs = wanted.inputs.model_dump(mode="json")
    callbacks = 0
    with get_session() as session:
        def queue(given: Session, chosen: str) -> None:
            nonlocal callbacks
            if given is not session or chosen != allocated or callbacks:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            callbacks += 1
            _queue_in(given, chosen, profile.workflow, inputs)

        admitted = boundary.composition.bind_and_queue_in(
            session, caller, descriptor.context_ref, descriptor.context_version,
            allocated, profile.profile_revision, queue)
        binding = admitted.binding
        if (callbacks != int(admitted.created)
                or (admitted.created and binding.execution_id != allocated)
                or binding.context_ref != descriptor.context_ref
                or binding.context_version != descriptor.context_version
                or binding.owner_principal != caller.principal_id
                or binding.namespace != caller.namespace or binding.profile != caller.profile
                or binding.profile_revision != profile.profile_revision
                or binding.workflow != profile.workflow
                or binding.workflow_revision != profile.workflow_revision
                or binding.node_path != profile.node_path or binding.use != "draft"
                or binding.context_schema != profile.schema.identity.context_schema
                or binding.result_schema != profile.schema.identity.result_schema
                or binding.schema_revision != profile.schema.identity.revision
                or _binding_time(binding.expires_at) <= datetime.now(UTC)
                or _binding_time(binding.deadline_at) <= datetime.now(UTC)
                or profile.credential_deadline <= datetime.now(UTC)
                or binding.revoked):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
    if admitted.created:
        dispatch(binding)
    return binding.execution_id


def private_lifecycle(execution_id: str, action: Literal["resume", "fork", "cancel"],
                      overrides: dict, *, mode: str) -> PrivateBinding:
    """Pre-read cancellation/resume under C1 fence; never reconstruct checkpoints."""
    from temper_ai.api.private_worker_keys import revoke_private_key_in
    from temper_ai.database import get_session

    boundary = caller_boundary(get_private_boundary())
    if overrides:
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    def authorize(owner, namespace, profile):
        return authorize_scope(boundary, owner, namespace, profile)

    previous = boundary.composition.binding_for_run(execution_id, authorize)
    caller = authorize(previous.owner_principal, previous.namespace, previous.profile)
    dispatch = boundary.prepare_dispatch(mode) if action == "resume" else None
    if action == "resume" and not callable(dispatch):
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    calls = 0
    effected: list[PrivateBinding] = []
    stable = ("execution_id", "context_ref", "context_version", "owner_principal", "namespace",
              "profile", "profile_revision", "workflow", "workflow_revision", "node_path", "use",
              "context_schema", "result_schema", "schema_revision", "expires_at", "deadline_at",
              "attempt_state", "outcome")
    with get_session() as session:
        def effect(given: Session, binding: PrivateBinding) -> None:
            nonlocal calls
            # Even a faulty composition cannot make a fork queue/copy anything.
            if (action == "fork" or given is not session or calls
                    or binding.execution_id != execution_id
                    or any(getattr(binding, name) != getattr(previous, name) for name in stable)
                    or (action == "resume" and (
                        binding.runner_generation != previous.runner_generation + 1 or binding.revoked))
                    or (action == "cancel" and (
                        binding.runner_generation != previous.runner_generation or not binding.revoked))):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            calls += 1
            effected.append(binding)
            row = given.exec(select(WorkflowRun).where(
                WorkflowRun.execution_id == execution_id).with_for_update()
                .execution_options(populate_existing=True)).first()
            if row is None or row.workflow_name != binding.workflow:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            wanted = decode_wire(encode_private(row.inputs), PrivateRunInputs).private_context
            if (wanted.context_ref != binding.context_ref or wanted.context_version != binding.context_version):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            revoke_private_key_in(given, execution_id)
            if action == "cancel":
                row.cancel_requested = True
                if row.status == "queued" and row.spawner_kind is None:
                    row.status = "cancelled"
                given.add(row)
            else:
                _queue_in(given, execution_id, row.workflow_name, row.inputs, start="resume")

        current = boundary.composition.lifecycle_in(session, caller, execution_id, action, effect)
        if calls != 1 or current.execution_id != execution_id or effected != [current]:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
    if dispatch is not None:
        dispatch(current)
    return current


def refuse_private_legacy(execution_id: str | None = None, workflow: str | None = None,
                          inputs: dict | None = None) -> None:
    """No legacy loader/checkpoint/env/tool executor for a private run.

    C2 provides the authenticated process client/key lifecycle; E alone joins
    the real private graph/context executor. A missing join is not fake success.
    """
    if private_start_requested(workflow, inputs) or (execution_id and private_run_requested(execution_id)):
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
