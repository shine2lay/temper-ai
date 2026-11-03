"""Explicit opt-in launch observation and child registration adapters for P3 T4.

Provides narrowly named adapters for existing Temper launch seams:
1. ``DockerLaunchObservationAdapter``: opt-in pre/post container spawn hook for
   ``DockerSpawner.spawn``.
2. ``EarlyBootstrapObservationHook``: opt-in post-delivery hook for
   ``take_box_delivery_first`` in ``temper_ai.cli.main`` (after stdin delivery is
   consumed, preserving stdlib-only imports before ``take_box_delivery_first``).
3. ``RunnerBootstrapObservationHook``: opt-in hook for
   ``bootstrap_runner_context_from_env`` in ``temper_ai.runner.bootstrap``.
4. ``BashChildLaunchAdapter``: opt-in protected subprocess lifecycle hook for
   ``Bash.execute`` / ``Bash._run_subprocess``.
5. ``ScriptLaunchObservationAdapter``: opt-in hook for ``ScriptAgent.run`` forwarding
   protected child registration to ``Bash.execute``.

No production factory or config installs any of these adapters. Ordinary
uninvolved routes remain unchanged when no adapter is passed. When a caller
requests a protected launch without a verified provider, the adapter refuses
before spawning any child process or container.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from p3_source_closure import ProcessInstance as ClosureProcessInstance
from temper_ai.p3_authority.child_registration import (
    NON_PROVIDER_REGISTRATION_SOURCES,
    VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
    ChildRegistrationTicket,
    ProcessKey,
    RegisteredChildEntry,
    refuse_surrogate_child_registration,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    Boundary,
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
    WorkerObservation,
)
from temper_ai.p3_authority.coverage_bookkeeping import make_refusal
from temper_ai.p3_authority.worker_closure_capture import (
    ObservedLoad,
    WorkerClosureCollector,
)
from temper_ai.p3_authority.worker_observation import WorkerObservationAdapter


class P3ObservationRefusedError(RuntimeError):
    """Raised when an opt-in protected launch is refused by P3 observation/registration."""

    def __init__(self, refusal: Refusal) -> None:
        self.refusal = refusal
        super().__init__(
            f"P3 observation refused [{refusal.code.value}] at phase={refusal.phase.value}"
        )


def refuse_missing_launch_provider(
    *,
    boundary: Boundary = "C_PRE_EXECUTION",
) -> Refusal:
    """Return a canonical Refusal when a protected launch has no verified provider."""
    return make_refusal(
        RefusalCode.AUTHORITY_UNAVAILABLE,
        boundary,
        retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        admission_state=AdmissionState.NOT_ADMITTED,
        effect_state=EffectState.NONE,
        sequence_use=SequenceUse.UNUSED,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DockerSpawnObservationRecord:
    """Immutable record of an observed DockerSpawner container launch."""

    execution_id: str
    container_id: str
    worker_observation: WorkerObservation


class DockerLaunchObservationAdapter:
    """Opt-in launch observation hook for ``DockerSpawner.spawn``."""

    def __init__(
        self,
        *,
        worker_observer: WorkerObservationAdapter | None = None,
        grant: ObservationGrant | None = None,
        selected_job: SelectedJob | None = None,
        closure_collector: WorkerClosureCollector | None = None,
        runtime_loads: tuple[ObservedLoad, ...] = (),
        boundary: Boundary = "A_PRE_CREATE",
    ) -> None:
        self._worker_observer = worker_observer
        self._grant = grant
        self._selected_job = selected_job
        self._closure_collector = closure_collector
        self._runtime_loads = runtime_loads
        self._boundary = boundary
        self._pre_spawn_checked = False
        self._records: list[DockerSpawnObservationRecord] = []
        self._cleanup_callbacks: list[str] = []

    @property
    def records(self) -> tuple[DockerSpawnObservationRecord, ...]:
        return tuple(self._records)

    @property
    def cleanup_callbacks(self) -> tuple[str, ...]:
        return tuple(self._cleanup_callbacks)

    def before_container_create(
        self,
        *,
        execution_id: str,
    ) -> Result[ObservationGrant]:
        """Verify provider and observation grant BEFORE ``docker create``."""
        if (
            self._worker_observer is None
            or not self._worker_observer.is_configured
            or self._grant is None
            or self._selected_job is None
        ):
            return refuse_missing_launch_provider(boundary=self._boundary)
        job_exec_uuid = (
            self._selected_job.pre_dispatch_or_running_job.execution_uuid
            if hasattr(self._selected_job.pre_dispatch_or_running_job, "execution_uuid")
            else self._selected_job.pre_dispatch_or_running_job.dispatch.execution_uuid
        )
        if execution_id != job_exec_uuid:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                self._boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        obs_res = self._worker_observer.observe(
            self._grant,
            self._selected_job,
            self._boundary,
        )
        if isinstance(obs_res, Refusal):
            return obs_res
        self._pre_spawn_checked = True
        return AcceptedData(data=self._grant, evidence=obs_res.evidence)

    def after_container_start(
        self,
        *,
        execution_id: str,
        container_id: str,
    ) -> Result[DockerSpawnObservationRecord]:
        """Bind started container identity after ``docker start``."""
        if not self._pre_spawn_checked or self._worker_observer is None:
            return make_refusal(RefusalCode.PRIOR_MISSING, self._boundary)
        if self._grant is None or self._selected_job is None:
            return refuse_missing_launch_provider(boundary=self._boundary)
        obs_res = self._worker_observer.observe(
            self._grant,
            self._selected_job,
            self._boundary,
        )
        if isinstance(obs_res, Refusal):
            return obs_res
        obs = obs_res.data
        container_inst = obs.worker_instance.container_instance
        if container_inst is None or container_inst.full_container_id != container_id:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                self._boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                admission_state=AdmissionState.ALREADY_ADMITTED,
                effect_state=EffectState.PARTIAL,
                sequence_use=SequenceUse.USED,
            )
        if self._closure_collector is not None:
            cap_res = self._closure_collector.record_docker_launch(
                execution_id=execution_id,
                container_id=container_id,
                worker_observation=obs,
                runtime_loads=self._runtime_loads,
                boundary=self._boundary,
            )
            if isinstance(cap_res, Refusal):
                return cap_res
        rec = DockerSpawnObservationRecord(
            execution_id=execution_id,
            container_id=container_id,
            worker_observation=obs,
        )
        self._records.append(rec)
        return AcceptedData(data=rec, evidence=obs_res.evidence)

    def on_spawn_cleanup(self, container_id: str) -> None:
        """Record container cleanup when post-start registration fails."""
        self._cleanup_callbacks.append(container_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class BootstrapObservationRecord:
    """Immutable record of an observed early CLI or runner bootstrap boundary."""

    stage: str
    execution_id: str
    worker_observation: WorkerObservation


class EarlyBootstrapObservationHook:
    """Opt-in hook invoked at the end of ``take_box_delivery_first`` in ``cli/main.py``."""

    def __init__(
        self,
        *,
        worker_observer: WorkerObservationAdapter | None = None,
        grant: ObservationGrant | None = None,
        selected_job: SelectedJob | None = None,
        closure_collector: WorkerClosureCollector | None = None,
        bootstrap_loads: tuple[ObservedLoad, ...] = (),
        use_box_profile_closure_as_complete: bool = False,
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> None:
        self._worker_observer = worker_observer
        self._grant = grant
        self._selected_job = selected_job
        self._closure_collector = closure_collector
        self._bootstrap_loads = bootstrap_loads
        self._use_box_profile_closure_as_complete = use_box_profile_closure_as_complete
        self._boundary = boundary
        self._records: list[BootstrapObservationRecord] = []

    @property
    def records(self) -> tuple[BootstrapObservationRecord, ...]:
        return tuple(self._records)

    def on_delivery_taken(
        self,
        *,
        had_box_profile: bool,
    ) -> Result[BootstrapObservationRecord]:
        if (
            self._worker_observer is None
            or not self._worker_observer.is_configured
            or self._grant is None
            or self._selected_job is None
        ):
            return refuse_missing_launch_provider(boundary=self._boundary)
        obs_res = self._worker_observer.observe(
            self._grant,
            self._selected_job,
            self._boundary,
        )
        if isinstance(obs_res, Refusal):
            return obs_res
        job_exec_uuid = (
            self._selected_job.pre_dispatch_or_running_job.execution_uuid
            if hasattr(self._selected_job.pre_dispatch_or_running_job, "execution_uuid")
            else self._selected_job.pre_dispatch_or_running_job.dispatch.execution_uuid
        )
        if self._closure_collector is not None:
            cap_res = self._closure_collector.record_early_bootstrap(
                execution_id=job_exec_uuid,
                had_box_profile=had_box_profile,
                bootstrap_loads=self._bootstrap_loads,
                use_box_profile_closure_as_complete=self._use_box_profile_closure_as_complete,
                boundary=self._boundary,
            )
            if isinstance(cap_res, Refusal):
                return cap_res
        rec = BootstrapObservationRecord(
            stage="cli_box_delivery" if had_box_profile else "cli_no_box_profile",
            execution_id=job_exec_uuid,
            worker_observation=obs_res.data,
        )
        self._records.append(rec)
        return AcceptedData(data=rec, evidence=obs_res.evidence)


class RunnerBootstrapObservationHook:
    """Opt-in hook for ``bootstrap_runner_context_from_env``."""

    def __init__(
        self,
        *,
        worker_observer: WorkerObservationAdapter | None = None,
        grant: ObservationGrant | None = None,
        selected_job: SelectedJob | None = None,
        closure_collector: WorkerClosureCollector | None = None,
        loads: tuple[ObservedLoad, ...] = (),
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> None:
        self._worker_observer = worker_observer
        self._grant = grant
        self._selected_job = selected_job
        self._closure_collector = closure_collector
        self._loads = loads
        self._boundary = boundary
        self._records: list[BootstrapObservationRecord] = []

    @property
    def records(self) -> tuple[BootstrapObservationRecord, ...]:
        return tuple(self._records)

    def on_runner_context_bootstrapped(
        self,
        *,
        execution_id: str,
    ) -> Result[BootstrapObservationRecord]:
        if (
            self._worker_observer is None
            or not self._worker_observer.is_configured
            or self._grant is None
            or self._selected_job is None
        ):
            return refuse_missing_launch_provider(boundary=self._boundary)
        job_exec_uuid = (
            self._selected_job.pre_dispatch_or_running_job.execution_uuid
            if hasattr(self._selected_job.pre_dispatch_or_running_job, "execution_uuid")
            else self._selected_job.pre_dispatch_or_running_job.dispatch.execution_uuid
        )
        if execution_id != job_exec_uuid:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                self._boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        obs_res = self._worker_observer.observe(
            self._grant,
            self._selected_job,
            self._boundary,
        )
        if isinstance(obs_res, Refusal):
            return obs_res
        if self._closure_collector is not None:
            cap_res = self._closure_collector.record_runner_bootstrap(
                execution_id=execution_id,
                loads=self._loads,
                boundary=self._boundary,
            )
            if isinstance(cap_res, Refusal):
                return cap_res
        rec = BootstrapObservationRecord(
            stage="runner_bootstrap",
            execution_id=execution_id,
            worker_observation=obs_res.data,
        )
        self._records.append(rec)
        return AcceptedData(data=rec, evidence=obs_res.evidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class BashChildTerminationRecord:
    """Immutable record of a registered child process termination in Bash."""

    child_key: ProcessKey
    returncode: int
    aborted: bool
    stop_reason: str | None


ChildIdentityResolver = Callable[
    [int],
    Result[tuple[ProcessInstance, ClosureProcessInstance]],
]


class BashChildLaunchAdapter:
    """Opt-in protected child launch adapter for ``Bash.execute`` / ``_run_subprocess``.

    Enforces pre-spawn provider & permission checks before ``subprocess.Popen``,
    registers the child birth through ``WorkerObservationAdapter`` immediately
    after spawn using ``child_identity_resolver``, and records termination/cleanup
    in ``finally`` without leaking child stdout/stderr/argv into refusal payloads.
    """

    def __init__(
        self,
        *,
        worker_observer: WorkerObservationAdapter | None = None,
        grant: ObservationGrant | None = None,
        selected_job: SelectedJob | None = None,
        parent_instance: ProcessInstance | None = None,
        intended_effect: SelectedOperation | None = None,
        child_identity_resolver: ChildIdentityResolver | None = None,
        registration_source: str = VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
        closure_collector: WorkerClosureCollector | None = None,
        child_profile_id: str = "child",
        child_entrypoint_ids: tuple[str, ...] = (),
        child_runtime_nodes: tuple[str, ...] = (),
        child_runtime_loads: tuple[ObservedLoad, ...] = (),
        child_loads: tuple[ObservedLoad, ...] = (),
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> None:
        self._worker_observer = worker_observer
        self._grant = grant
        self._selected_job = selected_job
        self._parent_instance = parent_instance
        self._intended_effect = intended_effect
        self._child_identity_resolver = child_identity_resolver
        self._registration_source = registration_source
        self._closure_collector = closure_collector
        self._child_profile_id = child_profile_id
        self._child_entrypoint_ids = child_entrypoint_ids
        self._child_runtime_nodes = child_runtime_nodes
        self._child_runtime_loads = child_runtime_loads
        self._child_loads = child_loads
        self._boundary = boundary
        self._pre_spawn_checks: int = 0
        self._spawn_registrations: int = 0
        self._registrations: list[RegisteredChildEntry] = []
        self._terminations: list[BashChildTerminationRecord] = []

    @property
    def pre_spawn_checks(self) -> int:
        return self._pre_spawn_checks

    @property
    def spawn_registrations(self) -> int:
        return self._spawn_registrations

    @property
    def registrations(self) -> tuple[RegisteredChildEntry, ...]:
        return tuple(self._registrations)

    @property
    def terminations(self) -> tuple[BashChildTerminationRecord, ...]:
        return tuple(self._terminations)

    def before_spawn(self) -> Result[ObservationGrant]:
        """Check provider, registration source, and parent permission BEFORE ``Popen``."""
        self._pre_spawn_checks += 1
        if (
            self._registration_source in NON_PROVIDER_REGISTRATION_SOURCES
            or self._registration_source != VERIFIED_LAUNCHER_REGISTRATION_SOURCE
        ):
            if self._closure_collector is not None:
                self._closure_collector.record_surrogate_registration_attempt(
                    surrogate_kind=self._registration_source,
                    boundary=self._boundary,
                )
            return refuse_surrogate_child_registration(
                surrogate_kind=self._registration_source,
                boundary=self._boundary,
            )
        if (
            self._worker_observer is None
            or not self._worker_observer.is_configured
            or self._grant is None
            or self._selected_job is None
            or self._parent_instance is None
            or self._intended_effect is None
            or self._child_identity_resolver is None
        ):
            return refuse_missing_launch_provider(boundary=self._boundary)
        return self._worker_observer.verify_pre_spawn(
            grant=self._grant,
            selected_job=self._selected_job,
            ticket_effect_domain=self._intended_effect.domain,
            ticket_effect_op=self._intended_effect.operation,
            ticket_effect_rev=self._intended_effect.revision,
            boundary=self._boundary,
            registration_source=self._registration_source,
        )

    def on_spawned(
        self,
        *,
        os_pid: int,
    ) -> Result[RegisteredChildEntry]:
        """Resolve synthetic child identity and register birth right after ``Popen``."""
        if (
            self._worker_observer is None
            or self._grant is None
            or self._selected_job is None
            or self._parent_instance is None
            or self._intended_effect is None
            or self._child_identity_resolver is None
        ):
            return refuse_missing_launch_provider(boundary=self._boundary)

        resolved = self._child_identity_resolver(os_pid)
        if isinstance(resolved, Refusal):
            return resolved
        child_host, child_closure = resolved.data

        ticket = ChildRegistrationTicket(
            selected_job=self._selected_job,
            grant=self._grant,
            parent_instance=self._parent_instance,
            child_instance=child_host,
            closure_instance=child_closure,
            boundary=self._boundary,
            intended_effect=self._intended_effect,
            registration_source=self._registration_source,
        )
        reg_res = self._worker_observer.register_child_ticket(ticket)
        if isinstance(reg_res, Refusal):
            return reg_res
        entry, _ = reg_res.data
        if self._closure_collector is not None:
            cap_res = self._closure_collector.record_verified_child_spawn(
                entry=entry,
                registration_source=self._registration_source,
                child_profile_id=self._child_profile_id,
                child_entrypoint_ids=self._child_entrypoint_ids,
                child_runtime_nodes=self._child_runtime_nodes,
                child_runtime_loads=self._child_runtime_loads,
                child_loads=self._child_loads,
                boundary=self._boundary,
            )
            if isinstance(cap_res, Refusal):
                return cap_res
        self._spawn_registrations += 1
        self._registrations.append(entry)
        return AcceptedData(data=entry, evidence=reg_res.evidence)

    def on_terminated(
        self,
        *,
        child_key: ProcessKey | None,
        os_pid: int,
        returncode: int,
        aborted: bool,
        stop_reason: str | None,
    ) -> None:
        """Record child termination and release active PID slot in registry."""
        resolved_key = child_key or ProcessKey(
            boot_id="unregistered",
            pid_namespace_id="unregistered",
            pid=os_pid,
            start_witness_ref="unregistered",
            exec_epoch=1,
        )
        if (
            child_key is not None
            and self._worker_observer is not None
            and self._selected_job is not None
        ):
            self._worker_observer.terminate_child(
                self._selected_job,
                child_key,
                exit_code=returncode,
                boundary=self._boundary,
            )
        if self._closure_collector is not None and child_key is not None:
            for reg_entry in self._registrations:
                if reg_entry.key == child_key:
                    self._closure_collector.record_child_termination(
                        child_instance_id=reg_entry.closure_instance.instance_id,
                        boundary=self._boundary,
                    )
                    break
        self._terminations.append(
            BashChildTerminationRecord(
                child_key=resolved_key,
                returncode=returncode,
                aborted=aborted,
                stop_reason=stop_reason,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScriptLaunchBinding:
    """Bound ScriptAgent execution metadata forwarded to Bash.execute."""

    agent_name: str
    run_id: str
    cwd: str | None
    timeout_seconds: int | float


class ScriptLaunchObservationAdapter:
    """Opt-in launch adapter for ``ScriptAgent.run``."""

    def __init__(
        self,
        *,
        bash_adapter: BashChildLaunchAdapter | None = None,
        selected_job: SelectedJob | None = None,
        expected_agent_name: str | None = None,
        cwd: str | None = None,
        timeout_seconds: int | float = 600,
        closure_collector: WorkerClosureCollector | None = None,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> None:
        self._bash_adapter = bash_adapter
        self._selected_job = selected_job
        self._expected_agent_name = expected_agent_name
        self._cwd = cwd
        self._timeout_seconds = timeout_seconds
        self._closure_collector = closure_collector
        self._boundary = boundary
        self._bindings: list[ScriptLaunchBinding] = []

    @property
    def bindings(self) -> tuple[ScriptLaunchBinding, ...]:
        return tuple(self._bindings)

    @property
    def bash_adapter(self) -> BashChildLaunchAdapter | None:
        return self._bash_adapter

    def prepare_bash_kwargs(
        self,
        *,
        agent_name: str,
        run_id: str,
        base_kwargs: dict[str, Any],
    ) -> Result[dict[str, Any]]:
        """Validate ScriptAgent identity and attach ``_p3_launch_adapter`` to Bash kwargs."""
        if self._bash_adapter is None or self._selected_job is None:
            return refuse_missing_launch_provider(boundary=self._boundary)
        job_exec_uuid = (
            self._selected_job.pre_dispatch_or_running_job.execution_uuid
            if hasattr(self._selected_job.pre_dispatch_or_running_job, "execution_uuid")
            else self._selected_job.pre_dispatch_or_running_job.dispatch.execution_uuid
        )
        if (
            self._expected_agent_name is not None
            and agent_name != self._expected_agent_name
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                self._boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if run_id != job_exec_uuid:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                self._boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        pre_res = self._bash_adapter.before_spawn()
        if isinstance(pre_res, Refusal):
            return pre_res
        if self._closure_collector is not None:
            cap_res = self._closure_collector.record_script_launch(
                agent_name=agent_name,
                run_id=run_id,
                boundary=self._boundary,
            )
            if isinstance(cap_res, Refusal):
                return cap_res
        self._bindings.append(
            ScriptLaunchBinding(
                agent_name=agent_name,
                run_id=run_id,
                cwd=self._cwd,
                timeout_seconds=self._timeout_seconds,
            )
        )
        merged = dict(base_kwargs)
        merged["_p3_launch_adapter"] = self._bash_adapter
        merged["_p3_protected_launch"] = True
        return AcceptedData(data=merged, evidence=pre_res.evidence)
