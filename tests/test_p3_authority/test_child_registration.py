"""Fixed positive, refusal, lifecycle, canary, and mutation-bite tests for P3 T4 child registration."""

from __future__ import annotations

import os
import signal
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest

from p3_source_closure import (
    LoadedClosureEnvelope,
    N3ObservationEpoch,
    ReviewedSourceGraph,
)
from p3_source_closure import (
    ProcessInstance as ClosureProcessInstance,
)
from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.admission_contract import DispatchIdentity
from temper_ai.p3_authority.child_registration import (
    NON_PROVIDER_REGISTRATION_SOURCES,
    VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
    ChildRegistrationRegistry,
    ChildRegistrationTicket,
    ProcessKey,
    process_key_for,
    refuse_surrogate_child_registration,
)
from temper_ai.p3_authority.contract import (
    DECISION_SCHEMA,
    AcceptedData,
    AdmissionState,
    AuthorityRef,
    BothRootObservations,
    Boundary,
    CompatibilityProfile,
    DecisionEvidence,
    EffectSet,
    EffectState,
    ExistingSubject,
    FutureSubject,
    ImmutableReference,
    JobKey,
    NativeEventRange,
    NativeProcessRef,
    NativeSubject,
    ObservationGrant,
    PermissionHandle,
    Phase,
    ProcessInstance,
    ProjectSelection,
    Refusal,
    RefusalCode,
    Result,
    RootBinding,
    RootObservation,
    RootScope,
    SelectedJob,
    SelectedOperation,
    SelectedSubject,
    SequenceUse,
    TrustedInstant,
    VerifiedAuthority,
)
from temper_ai.p3_authority.coverage_bookkeeping import boundary_to_phase
from temper_ai.p3_authority.launch_adapters import (
    BashChildLaunchAdapter,
    ScriptLaunchObservationAdapter,
)
from temper_ai.p3_authority.worker_observation import (
    WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    RootOwnerVsActorAssertion,
    SuppliedWorkerFrame,
    WorkerObservationAdapter,
    WorkerObservationProviderPort,
)
from temper_ai.shared.types import ExecutionContext
from temper_ai.tools.bash import Bash
from temper_ai.tools.executor import ToolExecutor
from tests.test_architecture.ops_host_n3_cases import clean_world

CANARY_STDOUT = "CANARY_STDOUT_263_9F3A"
CANARY_STDERR = "CANARY_STDERR_263_7B2C"
CANARY_ARGV = "CANARY_ARGV_263_4D1E"


@dataclass(frozen=True)
class _Ref:
    path: str
    digest: str
    length: int
    revision: str


@dataclass(frozen=True)
class _Witness:
    witness_reference: str


@dataclass(frozen=True)
class _ProcessRef:
    process_registration: str


@dataclass(frozen=True)
class _Birth:
    birth_identity: str
    birth_witness: _Witness


@dataclass(frozen=True)
class _Container:
    container_identity: str
    full_container_id: str
    daemon_instance: _ProcessRef
    start_witness: _Witness


@dataclass(frozen=True)
class _RootObj:
    root_object_identity: str
    namespace_identity: _Witness
    mount_identity: _Witness
    filesystem_object: str
    observation_epoch: str


@dataclass(frozen=True)
class _GrantRef:
    grant_reference: str


@dataclass(frozen=True)
class _Interval:
    interval_reference: str
    clock_domain: str
    interval_witness: _Witness


@dataclass(frozen=True)
class _EventRange:
    event_range_reference: str
    first_sequence: int
    last_sequence: int
    lost_events: int
    continuity_witness: _Witness


@dataclass(frozen=True)
class _Permission:
    observation_permission: str


@dataclass(frozen=True)
class _ExistingScope:
    identity: _RootObj
    subject_kind: Literal["existing"] = "existing"


@dataclass(frozen=True)
class _FutureScope:
    selected_scope_reference: str
    subject_kind: Literal["future"] = "future"


@dataclass(frozen=True)
class _ObservationGrant:
    authority: VerifiedAuthority
    permission: PermissionHandle
    subject: ExistingSubject | FutureSubject
    operations: EffectSet
    boundary: Boundary
    valid_until: TrustedInstant


@dataclass(frozen=True)
class _Evidence:
    selected_job: SelectedJob
    authority_revisions: tuple[AuthorityRef, ...]
    window: NativeSubject | None
    processes: tuple[NativeProcessRef, ...]
    effect: SelectedOperation
    phase: Phase
    boundary: Boundary
    source: ImmutableReference
    closure: ImmutableReference
    compatibility: CompatibilityProfile
    receiving: tuple[ImmutableReference, ...]
    schema: Literal["p3-native-decision/1"] = "p3-native-decision/1"


def make_witness(ref: str = "wit-1") -> _Witness:
    return _Witness(witness_reference=ref)


def make_root_obj(label: str) -> _RootObj:
    w = make_witness(f"wit:{label}")
    return _RootObj(
        root_object_identity=label,
        namespace_identity=w,
        mount_identity=w,
        filesystem_object=f"fs:{label}",
        observation_epoch="epoch-1",
    )


def make_event_range(
    first_sequence: int = 0,
    last_sequence: int = 8,
    lost_events: int = 0,
) -> _EventRange:
    return _EventRange(
        event_range_reference=f"stream:{first_sequence}..{last_sequence}",
        first_sequence=first_sequence,
        last_sequence=last_sequence,
        lost_events=lost_events,
        continuity_witness=make_witness("wit-stream"),
    )


def make_selected_op(
    domain: str = "worker-child",
    operation: str = "spawn",
    revision: str = "o1",
) -> SelectedOperation:
    return SelectedOperation(domain=domain, operation=operation, revision=revision)


def make_selected_job(
    *,
    execution_uuid: str = "00000000-0000-4000-8000-000000000263",
    selection_revision: str = "sel-263-1",
    corpus: str = WORKER_OBSERVATION_COMPAT_CORPUS_ID,
) -> SelectedJob:
    dispatch = DispatchIdentity(
        execution_uuid=execution_uuid,
        dispatch_nonce="00000000-0000-4000-8000-000000000264",
        running_attempt=1,
    )
    reference = _Ref("synthetic/publication", "0" * 64, 17, "publication-r1")
    authority = AuthorityRef(
        issuer_id="issuer-263",
        record_id="record-263",
        authority_revision="a1",
    )
    project = ProjectSelection(
        project_id="project-263",
        run_id="domain-run-263",
        kit_id="kit-263",
        kit_sha256="1" * 64,
        build_sums_sha256="2" * 64,
        publication_ref=reference,
        publication_revision="publication-r1",
        build_ref=reference,
    )
    profile = CompatibilityProfile(
        decision=DECISION_SCHEMA,
        reviewed_graph="p3-reviewed-source-graph/1",
        loaded_envelope="p3-reviewed-loaded-closure/1",
        comparator="p3-source-closure/1",
        observation="p3-worker-observation/1",
        inspect="/2",
        caller="p3-caller/1",
        corpus=corpus,  # type: ignore[arg-type]
        receiving="p3-receiving/1",
    )
    op = make_selected_op()
    return SelectedJob(
        pre_dispatch_or_running_job=JobKey(dispatch=dispatch, job_revision="j1"),
        selector_issuer=authority,
        selection_revision=selection_revision,
        selection=project,
        approved_descriptor_digest="3" * 64,
        expected_source_digest="4" * 64,
        reviewed_closure_ref=reference,
        compatibility_profile=profile,
        authorized_operations=frozenset({op}),
        conditions=(),
        authority_refs=(authority,),
    )


def make_evidence(
    boundary: Boundary = "C_BEFORE_COUNT",
    selected_job: SelectedJob | None = None,
) -> DecisionEvidence:
    job = selected_job or make_selected_job()
    ref = _Ref("synthetic/publication", "0" * 64, 17, "publication-r1")
    return _Evidence(
        selected_job=job,
        authority_revisions=job.authority_refs,
        window=_ExistingScope(identity=make_root_obj("pub-root-obj")),
        processes=(_ProcessRef("worker"),),
        effect=make_selected_op(),
        phase=boundary_to_phase(boundary),
        boundary=boundary,
        source=ref,
        closure=ref,
        compatibility=job.compatibility_profile,
        receiving=(),
    )


def make_grant(
    selected_job: SelectedJob,
    *,
    observation_permission: bool = True,
    use_future_subject: bool = False,
    boundary: Boundary = "C_BEFORE_COUNT",
) -> ObservationGrant:
    subj: ExistingSubject | FutureSubject
    if use_future_subject:
        subj = _FutureScope(selected_scope_reference="future-scope-263")
    else:
        subj = _ExistingScope(identity=make_root_obj("pub-root-obj"))
    perm_str = "granted-263" if observation_permission else ""
    perm = _Permission(observation_permission=perm_str)
    w = make_witness("wit-auth")
    instant = TrustedInstant(clock_domain="monotonic", reading="1000", witness=w)
    auth = VerifiedAuthority(
        issuer_identity=selected_job.selector_issuer.issuer_id,
        verified_record_digest="9" * 64,
        subject=SelectedSubject(
            subject=subj,
            job=selected_job.pre_dispatch_or_running_job,
            selection_revision=selected_job.selection_revision,
        ),
        actors=(_ProcessRef("worker"),),
        operations=selected_job.authorized_operations,
        roots=(subj,),
        conditions=(),
        not_before=instant,
        expires_at=instant,
        revocation_source=selected_job.selector_issuer,
        revocation_revision="rev-1",
        checked_at=instant,
        verification_profile="p3-worker-observation/1",
        validity=_Interval("interval-263", "monotonic", w),
    )
    return _ObservationGrant(
        authority=auth,
        permission=perm,
        subject=subj,
        operations=selected_job.authorized_operations,
        boundary=boundary,
        valid_until=instant,
    )


def make_host_and_worker_processes() -> tuple[
    ProcessInstance,
    ClosureProcessInstance,
    ProcessInstance,
    ClosureProcessInstance,
]:
    world = clean_world("N3-08")
    by_id = {
        p.instance.instance_id: p.instance
        for p in world.observed.envelope.process_observations
    }
    host_closure = by_id["host"]
    worker_closure = by_id["worker"]

    host_proc = ProcessInstance(
        native_identity=make_witness(host_closure.instance_id),
        host_instance_id="spark-host",
        boot_id=host_closure.host_boot,
        pid_namespace_id=host_closure.pid_namespace,
        pid=host_closure.pid,
        start_identity=_Birth(
            host_closure.start_identity,
            make_witness(f"birth:{host_closure.instance_id}"),
        ),
        exec_generation=make_witness(f"exec:{host_closure.instance_id}:1"),
        launch_id=host_closure.launch_identity,
        parent_instance=_ProcessRef(host_closure.parent_instance)
        if host_closure.parent_instance
        else None,
        role="controller",
        runtime_ref=world.observed,
        container_instance=None,
        mount_namespace_id=host_closure.mount_namespace,
        user_namespace_id=host_closure.user_namespace,
    )
    cid = worker_closure.container_identity or "container-1"
    worker_proc = ProcessInstance(
        native_identity=make_witness(worker_closure.instance_id),
        host_instance_id="spark-host",
        boot_id=worker_closure.host_boot,
        pid_namespace_id=worker_closure.pid_namespace,
        pid=worker_closure.pid,
        start_identity=_Birth(
            worker_closure.start_identity,
            make_witness(f"birth:{worker_closure.instance_id}"),
        ),
        exec_generation=make_witness(f"exec:{worker_closure.instance_id}:1"),
        launch_id=worker_closure.launch_identity,
        parent_instance=_ProcessRef(worker_closure.parent_instance)
        if worker_closure.parent_instance
        else None,
        role="worker",
        runtime_ref=world.observed,
        container_instance=_Container(
            container_identity=cid,
            full_container_id=cid,
            daemon_instance=_ProcessRef("dockerd"),
            start_witness=make_witness("wit-container"),
        ),
        mount_namespace_id=worker_closure.mount_namespace,
        user_namespace_id=worker_closure.user_namespace,
    )
    return host_proc, host_closure, worker_proc, worker_closure


def make_child_pair(
    worker_proc: ProcessInstance,
    worker_closure: ClosureProcessInstance,
    *,
    os_pid: int = 301,
    instance_id: str = "child",
    exec_epoch: int = 1,
    birth_ref: str = "birth-child",
    parent_id: str | None = None,
    mount_namespace_id: str | None = None,
) -> tuple[ProcessInstance, ClosureProcessInstance]:
    actual_parent_id = (
        parent_id if parent_id is not None else worker_closure.instance_id
    )
    mnt_ns = mount_namespace_id or worker_proc.mount_namespace_id
    closure_child = ClosureProcessInstance(
        instance_id=instance_id,
        host_boot=worker_closure.host_boot,
        pid=os_pid,
        start_identity=birth_ref,
        exec_epoch=exec_epoch,
        parent_instance=actual_parent_id,
        launch_identity=worker_closure.launch_identity,
        pid_namespace=worker_closure.pid_namespace,
        mount_namespace=mnt_ns,
        user_namespace=worker_closure.user_namespace,
        location="container",
        container_identity=worker_closure.container_identity,
        principal="actor-child",
        uid=1001,
        gid=1001,
        supplementary_groups=(),
        runtime_id=worker_closure.runtime_id,
    )
    host_child = ProcessInstance(
        native_identity=make_witness(instance_id),
        host_instance_id="spark-host",
        boot_id=worker_proc.boot_id,
        pid_namespace_id=worker_proc.pid_namespace_id,
        pid=os_pid,
        start_identity=_Birth(birth_ref, make_witness(birth_ref)),
        exec_generation=make_witness(f"exec:{instance_id}:{exec_epoch}"),
        launch_id=worker_proc.launch_id,
        parent_instance=_ProcessRef(actual_parent_id),
        role="child",
        runtime_ref=worker_proc.runtime_ref,
        container_instance=worker_proc.container_instance,
        mount_namespace_id=mnt_ns,
        user_namespace_id=worker_proc.user_namespace_id,
    )
    return host_child, closure_child


def make_both_roots() -> BothRootObservations:
    actor = _ProcessRef("worker")
    pub_obj = make_root_obj("pub-root-obj")
    ev_obj = make_root_obj("host-ev-root-obj")
    w = make_witness("wit-root")
    interval = _Interval("interval-263", "monotonic", w)
    pub_binding = RootBinding(
        role="publication",
        object_identity=pub_obj,
        actor_instance=actor,
        namespace_and_mount_identity=make_witness("mntns-worker:21"),
        actor_visible_path="/workspace/pub",
        host_visible_path="/host/pub",
        rights=frozenset({"observe", "read"}),
        grant_refs=(_GrantRef("grant-263-1"),),
        validity=interval,
        mapping_witness=make_witness("map-pub"),
    )
    ev_binding = RootBinding(
        role="host-evidence",
        object_identity=ev_obj,
        actor_instance=actor,
        namespace_and_mount_identity=make_witness("mntns-worker:22"),
        actor_visible_path="/workspace/ev",
        host_visible_path="/host/ev",
        rights=frozenset({"observe", "read"}),
        grant_refs=(_GrantRef("grant-263-1"),),
        validity=interval,
        mapping_witness=make_witness("map-ev"),
    )
    pub_obs = RootObservation(
        root_kind="publication",
        binding=pub_binding,
        traversal_chain=(pub_obj,),
        observed_access=frozenset({"observe", "read"}),
        observation_boundary="C_BEFORE_COUNT",
        provenance=(make_witness("prov-pub"),),
    )
    ev_obs = RootObservation(
        root_kind="host_evidence",
        binding=ev_binding,
        traversal_chain=(ev_obj,),
        observed_access=frozenset({"observe", "read"}),
        observation_boundary="C_BEFORE_COUNT",
        provenance=(make_witness("prov-ev"),),
    )
    return BothRootObservations(
        publication=pub_obs,
        host_evidence=ev_obs,
    )


def make_supplied_worker_frame(
    *,
    case_id: str = "N3-08",
    both_roots: BothRootObservations | None = None,
    effect_fence_verified: bool = True,
    load_stream_refs: tuple[NativeEventRange, ...] | None = None,
    observed_override: LoadedClosureEnvelope | None = None,
    reviewed_override: ReviewedSourceGraph | None = None,
    Provide_roots: bool = True,
) -> SuppliedWorkerFrame:
    world = clean_world(case_id)
    host_proc, host_closure, worker_proc, worker_closure = (
        make_host_and_worker_processes()
    )
    obs_env = observed_override or world.observed
    rev_graph = reviewed_override if reviewed_override is not None else world.reviewed
    streams = (
        load_stream_refs
        if load_stream_refs is not None
        else (make_event_range(0, 8, 0),)
    )
    roots = (
        None
        if not Provide_roots
        else (both_roots if both_roots is not None else make_both_roots())
    )
    return SuppliedWorkerFrame(
        dispatcher_association=make_witness("wit-dispatch-263"),
        host_instance=host_proc,
        host_closure_instance=host_closure,
        worker_instance=worker_proc,
        worker_closure_instance=worker_closure,
        checker_instances=(),
        child_instances=(),
        runtime_facts=obs_env,
        reviewed_graph=rev_graph,
        launch_profile_ref=_Ref("synthetic/profile", "d" * 64, 32, "v1"),
        load_stream_refs=streams,
        collector_provenance=(make_witness("wit-collector-263"),),
        both_roots=roots,
        root_owner_assertions=(
            RootOwnerVsActorAssertion(
                root_kind="publication",
                actor_process_ref="worker",
                actor_principal="actor-worker",
                actor_uid=1001,
                file_owner_principal="host-builder",
                file_owner_uid=1000,
            ),
            RootOwnerVsActorAssertion(
                root_kind="host_evidence",
                actor_process_ref="worker",
                actor_principal="actor-worker",
                actor_uid=1001,
                file_owner_principal="host-root-owner",
                file_owner_uid=0,
            ),
        ),
        effect_fence_verified=effect_fence_verified,
    )


class SyntheticWorkerProviderDouble(WorkerObservationProviderPort):
    """Explicit test-only provider double; never installed by default."""

    def __init__(
        self,
        *,
        frame: SuppliedWorkerFrame | None = None,
        grant_refusal: Refusal | None = None,
        child_refusal: Refusal | None = None,
    ) -> None:
        self.frame = frame or make_supplied_worker_frame()
        self.grant_refusal = grant_refusal
        self.child_refusal = child_refusal
        self.verify_grant_calls = 0
        self.collect_frame_calls = 0
        self.collect_root_calls = 0
        self.verify_child_calls = 0

    def verify_grant(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Result[DecisionEvidence]:
        self.verify_grant_calls += 1
        if self.grant_refusal is not None:
            return self.grant_refusal
        ev = make_evidence(boundary, selected_job)
        return AcceptedData(data=ev, evidence=ev)

    def collect_worker_frame(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[SuppliedWorkerFrame]:
        self.collect_frame_calls += 1
        frame = self.frame
        if frame.both_roots is not None:
            frame = replace(
                frame,
                both_roots=BothRootObservations(
                    publication=replace(
                        frame.both_roots.publication,
                        observation_boundary=boundary,
                    ),
                    host_evidence=replace(
                        frame.both_roots.host_evidence,
                        observation_boundary=boundary,
                    ),
                ),
            )
        raw_env = frame.runtime_facts.envelope
        if raw_env.boundary.phase != boundary and boundary in (
            "A_PRE_CREATE",
            "A_PRE_ARM",
            "B_PRE_REQUEST",
            "C_PRE_REQUEST",
            "C_PRE_EXECUTION",
            "C_BEFORE_COUNT",
        ):
            updated_procs = tuple(
                replace(
                    p,
                    checkpoint=replace(
                        p.checkpoint,
                        boundary=replace(p.checkpoint.boundary, phase=boundary),  # type: ignore[arg-type]
                    ),
                )
                for p in raw_env.process_observations
            )
            frame = replace(
                frame,
                runtime_facts=replace(
                    frame.runtime_facts,
                    envelope=replace(
                        raw_env,
                        boundary=replace(raw_env.boundary, phase=boundary),  # type: ignore[arg-type]
                        process_observations=updated_procs,
                    ),
                ),
            )
        ev = make_evidence(boundary, selected_job)
        return AcceptedData(data=frame, evidence=ev)

    def collect_root_observation(
        self,
        grant: ObservationGrant,
        actor_instance: NativeProcessRef,
        selected_root: RootScope,
        required_operations: EffectSet,
        boundary: Boundary,
    ) -> Result[RootObservation]:
        self.collect_root_calls += 1
        both = self.frame.both_roots or make_both_roots()
        obs = (
            both.publication
            if selected_root.role == "publication"
            else both.host_evidence
        )
        obs = replace(obs, observation_boundary=boundary)
        ev = make_evidence(boundary)
        return AcceptedData(data=obs, evidence=ev)

    def verify_child_launch(
        self,
        ticket: ChildRegistrationTicket,
    ) -> Result[DecisionEvidence]:
        self.verify_child_calls += 1
        if self.child_refusal is not None:
            return self.child_refusal
        ev = make_evidence(ticket.boundary, ticket.selected_job)
        return AcceptedData(data=ev, evidence=ev)


def test_combined_child_registration_happy_path_through_script_and_bash_adapters(
    tmp_path: Path,
) -> None:
    """Combined happy path (bp-be8d76b9): parent observation -> ScriptAgent -> Bash Popen -> child registration -> execve generation -> termination."""
    job = make_selected_job()
    grant = make_grant(job)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)

    # 1. Establish parent worker observation first
    obs_res = observer.observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_res, AcceptedData)
    worker_obs = obs_res.data
    assert worker_obs.child_instances == ()

    _, _, worker_proc, worker_closure = make_host_and_worker_processes()

    def resolve_child(
        os_pid: int,
    ) -> Result[tuple[ProcessInstance, ClosureProcessInstance]]:
        pair = make_child_pair(
            worker_proc,
            worker_closure,
            os_pid=os_pid,
            instance_id="child",
            exec_epoch=1,
            birth_ref="birth-child",
        )
        ev = make_evidence("C_BEFORE_COUNT", job)
        return AcceptedData(data=pair, evidence=ev)

    bash_adapter = BashChildLaunchAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        parent_instance=worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=resolve_child,
    )
    script_adapter = ScriptLaunchObservationAdapter(
        bash_adapter=bash_adapter,
        selected_job=job,
        expected_agent_name="checker-script",
        cwd=str(tmp_path),
    )

    executor = ToolExecutor(workspace_root=str(tmp_path))
    executor.register_tools({"Bash": Bash()})
    ctx = ExecutionContext(
        run_id="00000000-0000-4000-8000-000000000263",
        workflow_name="designated-wf-263",
        node_path="check",
        agent_name="checker-script",
        event_recorder=None,
        tool_executor=executor,
        workspace_path=str(tmp_path),
    )
    agent = ScriptAgent(
        {
            "name": "checker-script",
            "script_template": 'python3 -c "import os, json; print(json.dumps({\'child_pid\': os.getpid()}))"',
            "p3_launch_adapter": script_adapter,
            "p3_protected_launch": True,
        }
    )

    res = agent.run({}, ctx)
    assert res.status.value == "completed"
    assert len(script_adapter.bindings) == 1
    assert bash_adapter.pre_spawn_checks >= 1
    assert bash_adapter.spawn_registrations == 1
    assert len(bash_adapter.registrations) == 1
    assert len(bash_adapter.terminations) == 1
    term = bash_adapter.terminations[0]
    assert term.returncode == 0
    assert term.aborted is False

    # 2. Verify in-place execve generation (exec_epoch 1 -> 2) on a live registered child
    child_gen1_host, child_gen1_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=4501,
        instance_id="child-exec",
        exec_epoch=1,
        birth_ref="birth:4501",
    )
    ticket_gen1 = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=child_gen1_host,
        closure_instance=child_gen1_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
    )
    reg1 = observer.register_child_ticket(ticket_gen1)
    assert isinstance(reg1, AcceptedData)

    child_gen2_host, child_gen2_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=4501,
        instance_id="child-exec",
        exec_epoch=2,
        birth_ref="birth:4501",
    )
    ticket_gen2 = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=child_gen2_host,
        closure_instance=child_gen2_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
        exec_from_generation=1,
    )
    reg2 = observer.register_child_ticket(ticket_gen2)
    assert isinstance(reg2, AcceptedData)
    entry2, updated_obs = reg2.data
    assert entry2.key.exec_epoch == 2
    assert child_gen2_host in updated_obs.child_instances


def test_constructing_process_instances_or_tickets_never_registers_child() -> None:
    """Merely constructing ProcessInstance, ClosureProcessInstance, or ChildRegistrationTicket registers nothing."""
    job = make_selected_job()
    grant = make_grant(job)
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    registry = ChildRegistrationRegistry(
        selected_job=job,
        worker_instance=worker_proc,
        worker_closure_instance=worker_closure,
    )
    child_host, child_closure = make_child_pair(worker_proc, worker_closure, os_pid=900)
    _ = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=child_host,
        closure_instance=child_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
    )
    assert registry.registered_children == ()
    assert registry.registered_closure_children == ()


@pytest.mark.parametrize("surrogate", sorted(NON_PROVIDER_REGISTRATION_SOURCES))
def test_surrogate_child_registration_sources_refused_with_peer_unverified(
    surrogate: str,
) -> None:
    """Env UUID, file owner, UID alone, serialized object, peer path, and profile bool are refused."""
    job = make_selected_job()
    grant = make_grant(job)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)
    assert isinstance(observer.observe(grant, job, "C_BEFORE_COUNT"), AcceptedData)

    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    child_host, child_closure = make_child_pair(worker_proc, worker_closure, os_pid=333)
    ticket = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=child_host,
        closure_instance=child_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
        registration_source=surrogate,
    )
    res = observer.register_child_ticket(ticket)
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.PEER_UNVERIFIED
    assert res.phase == Phase.C
    assert res.admission_state == AdmissionState.NOT_ADMITTED
    assert res.effect_state == EffectState.NONE
    assert res.sequence_use == SequenceUse.UNUSED


def test_foreign_parent_pid_reuse_and_exec_epoch_skip_or_reuse_refused() -> None:
    """Foreign parent -> SUBJECT_MISMATCH; active PID reuse or exec_epoch skip/reuse -> RUNTIME_CHANGED."""
    job = make_selected_job()
    grant = make_grant(job)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)
    assert isinstance(observer.observe(grant, job, "C_BEFORE_COUNT"), AcceptedData)

    _, _, worker_proc, worker_closure = make_host_and_worker_processes()

    # 1. Foreign parent not in registry
    foreign_host, foreign_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=601,
        parent_id="proc:foreign:9999",
    )
    foreign_ticket = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=foreign_host,
        closure_instance=foreign_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
    )
    foreign_res = observer.register_child_ticket(foreign_ticket)
    assert isinstance(foreign_res, Refusal)
    assert foreign_res.code == RefusalCode.SUBJECT_MISMATCH

    # 2. Register valid child at PID 602
    c1_host, c1_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=602,
        instance_id="proc:child:602:a",
        birth_ref="birth:602:a",
    )
    ok_res = observer.register_child_ticket(
        ChildRegistrationTicket(
            selected_job=job,
            grant=grant,
            parent_instance=worker_proc,
            child_instance=c1_host,
            closure_instance=c1_closure,
            boundary="C_BEFORE_COUNT",
            intended_effect=make_selected_op(),
        )
    )
    assert isinstance(ok_res, AcceptedData)

    # 3. Active PID 602 reuse with different birth witness while first child is still active -> RUNTIME_CHANGED
    c2_host, c2_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=602,
        instance_id="proc:child:602:b",
        birth_ref="birth:602:b",
    )
    pid_reuse_res = observer.register_child_ticket(
        ChildRegistrationTicket(
            selected_job=job,
            grant=grant,
            parent_instance=worker_proc,
            child_instance=c2_host,
            closure_instance=c2_closure,
            boundary="C_BEFORE_COUNT",
            intended_effect=make_selected_op(),
        )
    )
    assert isinstance(pid_reuse_res, Refusal)
    assert pid_reuse_res.code == RefusalCode.RUNTIME_CHANGED

    # 4. exec_epoch skip (1 -> 3) -> RUNTIME_CHANGED
    c3_host, c3_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=602,
        instance_id="proc:child:602:a",
        exec_epoch=3,
        birth_ref="birth:602:a",
    )
    skip_res = observer.register_child_ticket(
        ChildRegistrationTicket(
            selected_job=job,
            grant=grant,
            parent_instance=worker_proc,
            child_instance=c3_host,
            closure_instance=c3_closure,
            boundary="C_BEFORE_COUNT",
            intended_effect=make_selected_op(),
            exec_from_generation=1,
        )
    )
    assert isinstance(skip_res, Refusal)
    assert skip_res.code == RefusalCode.RUNTIME_CHANGED

    # 5. Undeclared mount namespace unshare -> ROOT_MISMATCH
    unshare_host, unshare_closure = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=603,
        instance_id="proc:child:603",
        mount_namespace_id="mntns:4026539999",
    )
    unshare_res = observer.register_child_ticket(
        ChildRegistrationTicket(
            selected_job=job,
            grant=grant,
            parent_instance=worker_proc,
            child_instance=unshare_host,
            closure_instance=unshare_closure,
            boundary="C_BEFORE_COUNT",
            intended_effect=make_selected_op(),
            allow_namespace_unshare=False,
        )
    )
    assert isinstance(unshare_res, Refusal)
    assert unshare_res.code == RefusalCode.ROOT_MISMATCH


def test_post_popen_registration_refusal_kills_and_reaps_child_without_leaking_canaries(
    tmp_path: Path,
) -> None:
    """When registration fails after Popen, Bash kills the process group, reaps it, and never leaks child output/argv."""
    job = make_selected_job()
    grant = make_grant(job)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)
    assert isinstance(observer.observe(grant, job, "C_BEFORE_COUNT"), AcceptedData)

    _, _, worker_proc, worker_closure = make_host_and_worker_processes()

    def refuse_foreign_child(
        os_pid: int,
    ) -> Result[tuple[ProcessInstance, ClosureProcessInstance]]:
        pair = make_child_pair(
            worker_proc,
            worker_closure,
            os_pid=os_pid,
            parent_id="proc:foreign:untrusted",
        )
        ev = make_evidence("C_BEFORE_COUNT", job)
        return AcceptedData(data=pair, evidence=ev)

    bash_adapter = BashChildLaunchAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        parent_instance=worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=refuse_foreign_child,
    )
    bash = Bash()
    cmd = (
        f'python3 -c "import sys, time; '
        f"sys.stdout.write('{CANARY_STDOUT}\\n'); sys.stdout.flush(); "
        f"sys.stderr.write('{CANARY_STDERR}\\n'); sys.stderr.flush(); "
        f'time.sleep(30)" {CANARY_ARGV}'
    )
    result = bash.execute(
        command=cmd,
        cwd=str(tmp_path),
        _skip_allowlist=True,
        _p3_launch_adapter=bash_adapter,
        _p3_protected_launch=True,
    )
    assert result.success is False
    assert result.metadata is not None
    assert result.metadata["p3_refusal_code"] == RefusalCode.SUBJECT_MISMATCH.value
    aborted_pid = result.metadata["aborted_pid"]
    assert isinstance(aborted_pid, int)

    # Verify child process does not survive
    with pytest.raises(ProcessLookupError):
        os.kill(aborted_pid, 0)

    # Verify canaries never appear in ToolResult error, result, or metadata
    combined_text = f"{result.result} {result.error} {result.metadata}"
    assert CANARY_STDOUT not in combined_text
    assert CANARY_STDERR not in combined_text
    assert CANARY_ARGV not in combined_text
    assert len(bash_adapter.terminations) == 1
    assert bash_adapter.terminations[0].aborted is True
    assert bash_adapter.terminations[0].stop_reason == "registration_refused"


def test_absent_provider_refuses_protected_bash_and_script_before_popen(
    tmp_path: Path,
) -> None:
    """Protected launch with no configured provider refuses before spawning any child process."""
    marker = tmp_path / "should_not_exist.txt"
    bash = Bash()
    res = bash.execute(
        command=f"touch {marker}",
        cwd=str(tmp_path),
        _skip_allowlist=True,
        _p3_protected_launch=True,
    )
    assert res.success is False
    assert res.metadata is not None
    assert (
        res.metadata["p3_refusal_code"] == RefusalCode.AUTHORITY_UNAVAILABLE.value
    )
    assert not marker.exists()

    # Ordinary uninvolved Bash call remains unchanged
    normal_marker = tmp_path / "ordinary_ok.txt"
    normal_res = bash.execute(
        command=f"touch {normal_marker}",
        cwd=str(tmp_path),
        _skip_allowlist=True,
    )
    assert normal_res.success is True
    assert normal_marker.exists()


def test_child_registration_guard_mutation_bites() -> None:
    """Every child registration guard fails a deterministic check when dropped or loosened."""
    job = make_selected_job()
    grant = make_grant(job)
    provider = SyntheticWorkerProviderDouble()
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()

    # Bite 1: registration_source guard (loosening to prefix match must fail)
    registry = ChildRegistrationRegistry(
        selected_job=job,
        worker_instance=worker_proc,
        worker_closure_instance=worker_closure,
    )
    c_host, c_closure = make_child_pair(worker_proc, worker_closure, os_pid=701)
    prefix_ticket = ChildRegistrationTicket(
        selected_job=job,
        grant=grant,
        parent_instance=worker_proc,
        child_instance=c_host,
        closure_instance=c_closure,
        boundary="C_BEFORE_COUNT",
        intended_effect=make_selected_op(),
        registration_source=f"{VERIFIED_LAUNCHER_REGISTRATION_SOURCE}_extra_canary",
    )
    res_prefix = registry.register_child(prefix_ticket, verification_port=provider)
    assert isinstance(res_prefix, Refusal)
    assert res_prefix.code == RefusalCode.PEER_UNVERIFIED

    # Bite 2: unpermitted read attempt poisons subsequent valid registration
    poisoned_registry = ChildRegistrationRegistry(
        selected_job=job,
        worker_instance=worker_proc,
        worker_closure_instance=worker_closure,
    )
    poisoned_registry.record_unpermitted_read_attempt()
    valid_ticket = replace(
        prefix_ticket,
        registration_source=VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
    )
    res_poisoned = poisoned_registry.register_child(
        valid_ticket,
        verification_port=provider,
    )
    assert isinstance(res_poisoned, Refusal)
    assert res_poisoned.code == RefusalCode.OBSERVATION_NOT_AUTHORIZED

    # Bite 3: process_key_for distinguishes start_identity and exec_epoch
    k1 = process_key_for(c_host, c_closure)
    _, c_closure_gen2 = make_child_pair(
        worker_proc,
        worker_closure,
        os_pid=701,
        exec_epoch=2,
    )
    k2 = process_key_for(c_host, c_closure_gen2)
    assert k1 != k2
    assert isinstance(k1, ProcessKey)
    assert isinstance(
        refuse_surrogate_child_registration(
            surrogate_kind="env_uuid",
            boundary="C_BEFORE_COUNT",
        ),
        Refusal,
    )
    assert signal.SIGKILL > 0
    assert sys.executable
