"""Typed child-birth and exec-generation registration for P3 T4 worker observation.

Enforces that:
- Merely constructing ``ProcessInstance``, ``p3_source_closure.ProcessInstance``,
  or ``ChildRegistrationTicket`` never registers a process or grants authority.
- Child registration requires an independently verified parent/launcher provider,
  never env UUID, file owner, UID alone, serialized object, peer path, or profile bool.
- Parent observation permission (``ObservationGrant``) precedes child registration.
- Actual supplied synthetic birth, start, exec-generation, namespace, mount, and
  job identities are checked against the verified parent lineage.
- PID reuse and ``exec_epoch`` / ``exec_generation`` reuse or skipping are rejected.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Final, Protocol

from p3_source_closure import ProcessInstance as ClosureProcessInstance
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    Boundary,
    DecisionEvidence,
    EffectState,
    ObservationGrant,
    ProcessInstance,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    SelectedJob,
    SelectedOperation,
    SequenceUse,
)
from temper_ai.p3_authority.coverage_bookkeeping import make_refusal

VERIFIED_LAUNCHER_REGISTRATION_SOURCE: Final[str] = "verified_parent_launcher_provider"

NON_PROVIDER_REGISTRATION_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "env_uuid",
        "file_owner",
        "uid_alone",
        "serialized_object",
        "peer_path",
        "profile_bool",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessKey:
    """Unique process-generation key preventing PID reuse and exec-epoch collision."""

    boot_id: str
    pid_namespace_id: str
    pid: int
    start_witness_ref: str
    exec_epoch: int


def process_key_for(
    host_proc: ProcessInstance,
    closure_proc: ClosureProcessInstance,
) -> ProcessKey:
    """Build the canonical ProcessKey for a paired host/closure ProcessInstance."""
    return ProcessKey(
        boot_id=host_proc.boot_id,
        pid_namespace_id=host_proc.pid_namespace_id,
        pid=host_proc.pid,
        start_witness_ref=host_proc.start_identity.birth_witness.witness_reference,
        exec_epoch=closure_proc.exec_epoch,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ChildRegistrationTicket:
    """Ticket submitted by a verified launcher adapter for child birth or execve.

    Constructing this dataclass has zero side effects and registers nothing.
    """

    selected_job: SelectedJob
    grant: ObservationGrant
    parent_instance: ProcessInstance
    child_instance: ProcessInstance
    closure_instance: ClosureProcessInstance
    boundary: Boundary
    intended_effect: SelectedOperation
    registration_source: str = VERIFIED_LAUNCHER_REGISTRATION_SOURCE
    exec_from_generation: int | None = None
    allow_namespace_unshare: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisteredChildEntry:
    """Immutable record of an accepted child or exec generation in the registry."""

    key: ProcessKey
    host_instance: ProcessInstance
    closure_instance: ClosureProcessInstance
    parent_key: ProcessKey
    active: bool = True
    exit_code: int | None = None


class ChildLaunchVerificationPort(Protocol):
    """Port verifying observation grant, parent-child birth proof, and effect fence."""

    @abstractmethod
    def verify_child_launch(
        self,
        ticket: ChildRegistrationTicket,
    ) -> Result[DecisionEvidence]: ...


def refuse_surrogate_child_registration(
    *,
    surrogate_kind: str,
    boundary: Boundary,
) -> Refusal:
    """Return the canonical PEER_UNVERIFIED refusal for non-provider registration."""
    _ = surrogate_kind
    return make_refusal(
        RefusalCode.PEER_UNVERIFIED,
        boundary,
        retry_kind=RetryKind.NEW_BINDING_REQUIRED,
    )


class ChildRegistrationRegistry:
    """Per-job registry of verified worker, checker, and child process generations."""

    def __init__(
        self,
        *,
        selected_job: SelectedJob,
        worker_instance: ProcessInstance,
        worker_closure_instance: ClosureProcessInstance,
    ) -> None:
        self._selected_job = selected_job
        self._worker_instance = worker_instance
        self._worker_closure_instance = worker_closure_instance
        self._worker_key = process_key_for(worker_instance, worker_closure_instance)
        self._entries: dict[ProcessKey, RegisteredChildEntry] = {}
        self._active_by_pid: dict[tuple[str, str, int], ProcessKey] = {
            (
                self._worker_key.boot_id,
                self._worker_key.pid_namespace_id,
                self._worker_key.pid,
            ): self._worker_key
        }
        self._instance_id_to_key: dict[str, ProcessKey] = {
            worker_closure_instance.instance_id: self._worker_key,
            worker_instance.native_identity.witness_reference: self._worker_key,
        }
        self._unpermitted_read_attempted = False

    @property
    def worker_key(self) -> ProcessKey:
        return self._worker_key

    @property
    def registered_children(self) -> tuple[ProcessInstance, ...]:
        return tuple(e.host_instance for e in self._entries.values())

    @property
    def registered_closure_children(self) -> tuple[ClosureProcessInstance, ...]:
        return tuple(e.closure_instance for e in self._entries.values())

    def record_unpermitted_read_attempt(self) -> None:
        """Poison the registry if any caller attempted to read before permission."""
        self._unpermitted_read_attempted = True

    def verify_pre_spawn(
        self,
        *,
        grant: ObservationGrant | None,
        selected_job: SelectedJob,
        intended_effect: SelectedOperation,
        boundary: Boundary,
        verification_port: ChildLaunchVerificationPort | None,
        registration_source: str = VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
    ) -> Result[ObservationGrant]:
        """Check provider availability, registration source, and grant before Popen."""
        if self._unpermitted_read_attempted:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if (
            registration_source in NON_PROVIDER_REGISTRATION_SOURCES
            or registration_source != VERIFIED_LAUNCHER_REGISTRATION_SOURCE
        ):
            return refuse_surrogate_child_registration(
                surrogate_kind=registration_source,
                boundary=boundary,
            )
        if verification_port is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)
        if grant is None:
            self._unpermitted_read_attempted = True
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if selected_job != self._selected_job:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if not grant.permission.observation_permission:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if intended_effect not in selected_job.authorized_operations:
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if intended_effect not in grant.authority.operations:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        # Dummy pre-spawn verification using worker self-identity to obtain DecisionEvidence
        dummy_ticket = ChildRegistrationTicket(
            selected_job=selected_job,
            grant=grant,
            parent_instance=self._worker_instance,
            child_instance=self._worker_instance,
            closure_instance=self._worker_closure_instance,
            boundary=boundary,
            intended_effect=intended_effect,
            registration_source=registration_source,
        )
        ver_res = verification_port.verify_child_launch(dummy_ticket)
        if isinstance(ver_res, Refusal):
            return ver_res
        return AcceptedData(data=grant, evidence=ver_res.evidence)

    def register_child(
        self,
        ticket: ChildRegistrationTicket,
        *,
        verification_port: ChildLaunchVerificationPort | None,
    ) -> Result[RegisteredChildEntry]:
        """Validate and register a child birth or in-place exec generation."""
        boundary = ticket.boundary
        if self._unpermitted_read_attempted:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if (
            ticket.registration_source in NON_PROVIDER_REGISTRATION_SOURCES
            or ticket.registration_source != VERIFIED_LAUNCHER_REGISTRATION_SOURCE
        ):
            return refuse_surrogate_child_registration(
                surrogate_kind=ticket.registration_source,
                boundary=boundary,
            )
        if verification_port is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)

        # 1. Verify selected job & revision match
        if ticket.selected_job != self._selected_job:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if ticket.selected_job.selection_revision != self._selected_job.selection_revision:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # 2. Verify grant permission and authorized operation BEFORE reading child state
        if not ticket.grant.permission.observation_permission:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if ticket.intended_effect not in ticket.selected_job.authorized_operations:
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if ticket.intended_effect not in ticket.grant.authority.operations:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)

        ver_res = verification_port.verify_child_launch(ticket)
        if isinstance(ver_res, Refusal):
            return ver_res
        evidence = ver_res.evidence

        host_child = ticket.child_instance
        closure_child = ticket.closure_instance

        # 3. Verify paired host_child and closure_child agree on pid/boot/namespaces
        if (
            host_child.pid != closure_child.pid
            or host_child.boot_id != closure_child.host_boot
            or host_child.pid_namespace_id != closure_child.pid_namespace
            or host_child.mount_namespace_id != closure_child.mount_namespace
            or host_child.user_namespace_id != closure_child.user_namespace
            or host_child.launch_id != closure_child.launch_identity
        ):
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # 4. Verify parent process lineage (must be worker or active registered child)
        parent_ref = host_child.parent_instance
        closure_parent_id = closure_child.parent_instance
        if parent_ref is None or closure_parent_id is None:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        parent_key = self._instance_id_to_key.get(closure_parent_id)
        if parent_key is None or parent_ref.process_registration != closure_parent_id:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        if parent_key == self._worker_key:
            parent_host = self._worker_instance
        else:
            parent_entry = self._entries.get(parent_key)
            if parent_entry is None or not parent_entry.active:
                return make_refusal(
                    RefusalCode.SUBJECT_MISMATCH,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            parent_host = parent_entry.host_instance

        if ticket.parent_instance != parent_host:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # 5. Verify boot_id and namespaces against parent
        if host_child.boot_id != parent_host.boot_id:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if not ticket.allow_namespace_unshare and (
            host_child.pid_namespace_id != parent_host.pid_namespace_id
            or host_child.mount_namespace_id != parent_host.mount_namespace_id
            or host_child.user_namespace_id != parent_host.user_namespace_id
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # 6. Prevent duplicate registration, PID reuse, and exec_epoch skip/reuse
        child_key = process_key_for(host_child, closure_child)
        if child_key == self._worker_key or child_key in self._entries:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                admission_state=AdmissionState.ALREADY_ADMITTED,
                effect_state=EffectState.UNCERTAIN,
                sequence_use=SequenceUse.USED,
            )

        pid_slot = (
            child_key.boot_id,
            child_key.pid_namespace_id,
            child_key.pid,
        )
        existing_active_key = self._active_by_pid.get(pid_slot)

        if closure_child.exec_epoch == 1:
            if ticket.exec_from_generation is not None:
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            if existing_active_key is not None:
                # Active PID reused while previous process in same PID namespace is still active!
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
        else:
            expected_prior = closure_child.exec_epoch - 1
            if ticket.exec_from_generation != expected_prior:
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            if existing_active_key is None:
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            if (
                existing_active_key.start_witness_ref != child_key.start_witness_ref
                or existing_active_key.exec_epoch != expected_prior
            ):
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            prior_entry = self._entries[existing_active_key]
            self._entries[existing_active_key] = RegisteredChildEntry(
                key=prior_entry.key,
                host_instance=prior_entry.host_instance,
                closure_instance=prior_entry.closure_instance,
                parent_key=prior_entry.parent_key,
                active=False,
                exit_code=0,
            )

        entry = RegisteredChildEntry(
            key=child_key,
            host_instance=host_child,
            closure_instance=closure_child,
            parent_key=parent_key,
            active=True,
        )
        self._entries[child_key] = entry
        self._active_by_pid[pid_slot] = child_key
        self._instance_id_to_key[closure_child.instance_id] = child_key
        self._instance_id_to_key[host_child.native_identity.witness_reference] = child_key
        return AcceptedData(data=entry, evidence=evidence)

    def terminate_child(
        self,
        key: ProcessKey,
        *,
        exit_code: int,
        boundary: Boundary,
        evidence: DecisionEvidence,
    ) -> Result[RegisteredChildEntry]:
        """Mark a registered child generation as terminated and free its active PID slot."""
        entry = self._entries.get(key)
        if entry is None:
            return make_refusal(RefusalCode.PRIOR_MISSING, boundary)
        updated = RegisteredChildEntry(
            key=entry.key,
            host_instance=entry.host_instance,
            closure_instance=entry.closure_instance,
            parent_key=entry.parent_key,
            active=False,
            exit_code=exit_code,
        )
        self._entries[key] = updated
        pid_slot = (key.boot_id, key.pid_namespace_id, key.pid)
        if self._active_by_pid.get(pid_slot) == key:
            del self._active_by_pid[pid_slot]
        return AcceptedData(data=updated, evidence=evidence)
