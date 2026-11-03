"""Tests for P3 T5-N3W deterministic worker LoadedClosureEnvelope + GitProvenance capture."""

from __future__ import annotations

import inspect
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from p3_source_closure import (
    Checkpoint,
    ClosureEnvelope,
    ContentIdentity,
    EvidenceRef,
    ExpectedProcess,
    LegacyLink,
    LoadEvent,
    ProcessFrontier,
    ProcessObservation,
    ReviewedSourceGraph,
    SourceGraph,
    VerifiedClosureOrigins,
    validate_loaded_envelope,
    validate_reviewed_graph,
)
from p3_source_closure.parsing import byte_identity
from p3_source_closure.provenance import Findings, check_provenance
from temper_ai.p3_authority import worker_closure_capture
from temper_ai.p3_authority._providers import SystemsSourceClosureComparator
from temper_ai.p3_authority.child_registration import ChildRegistrationRegistry
from temper_ai.p3_authority.contract import AcceptedData, Refusal, RefusalCode
from temper_ai.p3_authority.coverage_bookkeeping import (
    ALL_N3_COVERAGE_CATEGORIES,
    CoverageBookkeeper,
)
from temper_ai.p3_authority.launch_adapters import (
    BashChildLaunchAdapter,
    DockerLaunchObservationAdapter,
    EarlyBootstrapObservationHook,
    RunnerBootstrapObservationHook,
    ScriptLaunchObservationAdapter,
)
from temper_ai.p3_authority.selection import PreDispatchJob
from temper_ai.p3_authority.worker_closure_capture import (
    WORKER_CLOSURE_COLLECTOR_ID,
    WORKER_CLOSURE_COLLECTOR_VERSION,
    WORKER_CLOSURE_MECHANISM,
    ObservedLoad,
    WorkerClosureCollector,
    byte_content_identity,
    capture_git_checkout_provenance,
    claim_identity,
    make_evidence_ref,
    merge_dual_role_halves,
    to_wire,
    verify_and_compare_worker_closure,
)
from temper_ai.p3_authority.worker_observation import WorkerObservationAdapter
from tests.test_architecture.ops_host_n3_cases import clean_world, witnesses
from tests.test_p3_authority.test_child_registration import (
    SyntheticWorkerProviderDouble,
    make_child_pair,
    make_event_range,
    make_evidence,
    make_grant,
    make_host_and_worker_processes,
    make_selected_job,
    make_selected_op,
)

# The observer's stream for each container process: the reviewed node ids it
# saw loaded, in load order. A load carries no category: what the observer
# watched is its own sealed scope record (``_observer_record``), never a label.
WORKER_RUNTIME_SCRIPT: tuple[str, ...] = ("interpreter-worker", "stdlib-worker")
BOOTSTRAP_SCRIPT: tuple[str, ...] = ("main", "dep")
RUNNER_SCRIPT: tuple[str, ...] = ("generated", "cache", "native_binary-worker")
CHILD_OS_PID = 104


def _git(repo_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_clean_tmp_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "worker_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@temper.local")
    _git(repo_dir, "config", "user.name", "Temper Test")
    for name in ("main", "dep", "tool", "optional"):
        (repo_dir / f"{name}.py").write_bytes(name.encode("ascii"))
    _git(repo_dir, "add", "main.py", "dep.py", "tool.py", "optional.py")
    _git(repo_dir, "commit", "-m", "fixture commit")
    return repo_dir


def _build_reviewed_world_for_git_repo(
    repo_dir: Path, boundary: str = "C_BEFORE_COUNT"
):
    ev = make_evidence(boundary=boundary)  # type: ignore[arg-type]
    git_res = capture_git_checkout_provenance(
        repo_root=repo_dir,
        repo_id="repo",
        role="temper",
        tracked_files=(
            ("main", "main.py"),
            ("dep", "dep.py"),
            ("tool", "tool.py"),
            ("optional", "optional.py"),
        ),
        boundary=boundary,  # type: ignore[arg-type]
        evidence=ev,
    )
    assert isinstance(git_res, AcceptedData)
    git_cap = git_res.data

    base = clean_world("N3-01")
    git_nodes_by_id = {n.id: n for n in git_cap.nodes}
    updated_nodes = tuple(
        git_nodes_by_id.get(n.id, n) for n in base.reviewed.graph.nodes
    )
    raw_graph: SourceGraph = replace(
        base.reviewed.graph,
        repositories=(git_cap.repository,),
        nodes=updated_nodes,
    )
    reviewed = validate_reviewed_graph(to_wire(raw_graph))
    findings = Findings(
        VerifiedClosureOrigins(
            reviewed_bytes=reviewed.content,
            observed_bytes=None,
            expectation=None,
            validity_checkpoint=None,
            facts=witnesses(reviewed.graph, ()),
        )
    )
    check_provenance(reviewed.graph, findings)
    assert not findings.contradictions and not findings.gaps
    return base, reviewed, git_cap, ev


def _make_host_procs(base, reviewed: ReviewedSourceGraph, binding):
    by_node = {n.id: n for n in reviewed.graph.nodes}
    out = []
    for p in base.observed.envelope.process_observations:
        if p.instance.location != "host":
            continue
        events = tuple(
            replace(
                e,
                loaded=(
                    by_node["generated"].provenance.execution_object  # type: ignore[attr-defined]
                    if e.node_id == "generated"
                    else by_node[e.node_id].content
                ),
            )
            if e.node_id in by_node
            else e
            for e in p.events
        )
        out.append(replace(p, binding=binding, events=events))
    return tuple(out)


def _loaded_bytes(reviewed: ReviewedSourceGraph, node_id: str) -> ContentIdentity:
    node = {n.id: n for n in reviewed.graph.nodes}[node_id]
    if node_id == "generated":
        return node.provenance.execution_object  # type: ignore[attr-defined]
    return node.content


def _entry_node(entry) -> str:
    """A script entry is a node id, or (node id, loaded bytes override)."""
    return entry if isinstance(entry, str) else entry[0]


def _entry_bytes(reviewed: ReviewedSourceGraph, entry) -> ContentIdentity:
    """A script entry's loaded bytes: its own override, else the reviewed node's."""
    return _loaded_bytes(reviewed, entry) if isinstance(entry, str) else entry[1]


def _observed_loads(reviewed: ReviewedSourceGraph, script) -> tuple[ObservedLoad, ...]:
    return tuple(
        ObservedLoad(node_id=_entry_node(entry), loaded=_entry_bytes(reviewed, entry))
        for entry in script
    )


def _binding_for_job(base, job):
    """The closure binding of the observed job: dispatch, attempt, revisions."""
    key = job.pre_dispatch_or_running_job
    return replace(
        base.observed.envelope.binding,
        execution_uuid=key.dispatch.execution_uuid,
        attempt=key.dispatch.running_attempt,
        dispatch_nonce=key.dispatch.dispatch_nonce,
        job_revision=key.job_revision,
        selection_revision=job.selection_revision,
    )


def _new_collector(base, reviewed, ev, *, binding, worker_closure, **collector_kwargs):
    graph_ref = replace(base.observed.envelope.reviewed_graph, content=reviewed.content)
    collector = WorkerClosureCollector(
        binding=binding,
        closure_boundary=base.observed.envelope.boundary,
        reviewed_graph_ref=graph_ref,
        graph_id=reviewed.graph.graph_id,
        worker_instance=worker_closure,
        evidence=ev,
        **collector_kwargs,
    )
    return collector, graph_ref


def _run_opt_in_worker_capture_flow(
    base,
    reviewed: ReviewedSourceGraph,
    ev,
    *,
    boundary: str = "C_BEFORE_COUNT",
    runtime_script=WORKER_RUNTIME_SCRIPT,
    bootstrap_script=BOOTSTRAP_SCRIPT,
    runner_script=RUNNER_SCRIPT,
    spawn_child: bool = True,
    terminate_child: bool = True,
    child_runtime_script=None,
    child_load_script=None,
    collector_kwargs=None,
    expect_spawn_refused: bool = False,
) -> SimpleNamespace:
    """Drive every opt-in adapter with the observer's stream; return the flow's records.

    The child loads ``child_runtime_script`` (default: the worker's runtime), then
    ``child_load_script`` (default: the worker's bootstrap and runner loads, which
    the fixture graph's child profile requires).
    """
    if child_runtime_script is None:
        child_runtime_script = runtime_script
    if child_load_script is None:
        child_load_script = (*bootstrap_script, *runner_script)
    job = make_selected_job()
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    grant = make_grant(job, boundary=boundary)  # type: ignore[arg-type]
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    observer = WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble())
    binding = _binding_for_job(base, job)
    collector, graph_ref = _new_collector(
        base, reviewed, ev, binding=binding, worker_closure=worker_closure, **(collector_kwargs or {})
    )
    runtime_loads = _observed_loads(reviewed, runtime_script)
    bootstrap_loads = _observed_loads(reviewed, bootstrap_script)
    runner_loads = _observed_loads(reviewed, runner_script)
    common = {"worker_observer": observer, "grant": grant, "selected_job": job}

    docker_adapter = DockerLaunchObservationAdapter(
        **common,
        closure_collector=collector,
        runtime_loads=runtime_loads,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(docker_adapter.before_container_create(execution_id=exec_uuid), AcceptedData)
    started = docker_adapter.after_container_start(execution_id=exec_uuid, container_id="container-1")
    assert isinstance(started, AcceptedData)

    early_hook = EarlyBootstrapObservationHook(
        **common,
        closure_collector=collector,
        bootstrap_loads=bootstrap_loads,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(early_hook.on_delivery_taken(had_box_profile=True), AcceptedData)
    assert collector.box_profile_closure_ignored is True

    runner_hook = RunnerBootstrapObservationHook(
        **common,
        closure_collector=collector,
        loads=runner_loads,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(
        runner_hook.on_runner_context_bootstrapped(execution_id=exec_uuid), AcceptedData
    )

    host_child, closure_child = make_child_pair(worker_proc, worker_closure, os_pid=CHILD_OS_PID)
    flow = SimpleNamespace(
        collector=collector,
        graph_ref=graph_ref,
        job=job,
        binding=binding,
        worker_proc=worker_proc,
        worker_closure=worker_closure,
        host_child=host_child,
        closure_child=closure_child,
        reviewed=reviewed,
        scripts=(runtime_script, bootstrap_script, runner_script),
        child_runtime_script=child_runtime_script,
        child_load_script=child_load_script,
        graph_id=reviewed.graph.graph_id,
        closure_boundary=base.observed.envelope.boundary,
        spawned=False,
        terminated=False,
    )
    if not spawn_child:
        return flow

    def _resolve_child(os_pid: int):
        return AcceptedData(
            data=make_child_pair(worker_proc, worker_closure, os_pid=os_pid), evidence=ev
        )

    bash_adapter = BashChildLaunchAdapter(
        **common,
        parent_instance=worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=_resolve_child,
        closure_collector=collector,
        child_runtime_loads=_observed_loads(reviewed, child_runtime_script),
        child_loads=_observed_loads(reviewed, child_load_script),
        boundary=boundary,  # type: ignore[arg-type]
    )
    script_adapter = ScriptLaunchObservationAdapter(
        bash_adapter=bash_adapter,
        selected_job=job,
        expected_agent_name="script-1",
        closure_collector=collector,
        boundary=boundary,  # type: ignore[arg-type]
    )
    prep = script_adapter.prepare_bash_kwargs(
        agent_name="script-1", run_id=exec_uuid, base_kwargs={"command": "true"}
    )
    assert isinstance(prep, AcceptedData)
    spawned = bash_adapter.on_spawned(os_pid=CHILD_OS_PID)
    flow.observer = observer
    flow.common = common
    flow.resolve_child = _resolve_child
    flow.bash_adapter = bash_adapter
    flow.spawn_result = spawned
    if expect_spawn_refused:
        assert isinstance(spawned, Refusal), spawned
        return flow
    assert isinstance(spawned, AcceptedData)
    flow.spawned = True
    if terminate_child:
        bash_adapter.on_terminated(
            child_key=spawned.data.key,
            os_pid=CHILD_OS_PID,
            returncode=0,
            aborted=False,
            stop_reason=None,
        )
        flow.terminated = True
    return flow


def _observed_process(
    flow, *, profile_id, instance, epoch, entrypoints, steps, child_frontier, state, scope
) -> ProcessObservation:
    """One process as the test's observer saw it; steps are (kind, node, bytes, loader, child).

    Its ``Checkpoint`` is the observer's sealed scope record: by default every
    category watched, no gaps, sealed at the last event; ``scope`` changes fields.
    """
    events = tuple(
        LoadEvent(
            sequence=seq,
            event_id=f"{profile_id}-{seq}",
            kind=kind,
            node_id=node_id,
            loaded=loaded,
            loader=loader,
            representation="bytes",
            child_instance=child,
            origin_ref=make_evidence_ref(f"{profile_id}-event-{seq}"),
        )
        for seq, (kind, node_id, loaded, loader, child) in enumerate(steps)
    )
    return ProcessObservation(
        profile_id=profile_id,
        instance=instance,
        binding=flow.binding,
        graph_id=flow.graph_id,
        entrypoint_ids=entrypoints,
        runtime_nodes=("interpreter-worker", "stdlib-worker"),
        collector_id=WORKER_CLOSURE_COLLECTOR_ID,
        collector_version=WORKER_CLOSURE_COLLECTOR_VERSION,
        mechanism=WORKER_CLOSURE_MECHANISM,
        process_ref=make_evidence_ref(f"process-{profile_id}"),
        collector_ref=make_evidence_ref(f"collector-{profile_id}"),
        events=events,
        checkpoint=replace(
            Checkpoint(
                epoch=epoch,
                first_sequence=0,
                last_sequence=len(events) - 1,
                last_event_id=events[-1].event_id,
                child_frontier=child_frontier,
                coverage=ALL_N3_COVERAGE_CATEGORIES,
                gaps=(),
                loss_count=0,
                sealed=True,
                initial_state_ref=make_evidence_ref(f"initial-{profile_id}"),
                checkpoint_ref=make_evidence_ref(f"checkpoint-{profile_id}"),
                boundary=flow.closure_boundary,
            ),
            **(scope or {}),
        ),
        state=state,
    )


def _observer_record(
    flow, reviewed: ReviewedSourceGraph, scopes=None
) -> tuple[ProcessObservation, ...]:
    """The test's own record of what the observer saw, built from the scripts alone.

    Facts and the expectation come from this record, never from the collector, so
    a binding or scope the collector declares without observing finds no witness.
    ``scopes`` maps "worker" or "child" to changes in that process's sealed scope.
    """
    scopes = scopes or {}
    runtime, bootstrap, runner = flow.scripts

    def _loads(script):
        return [("load", _entry_node(e), _entry_bytes(reviewed, e), "loader-v1", None) for e in script]

    start = ("start", None, None, "trusted-launch", None)
    child_id = flow.closure_child.instance_id
    worker_steps = [start, *_loads((*runtime, *bootstrap, *runner))]
    if flow.spawned:
        worker_steps.append(("child", None, None, "trusted-launch", child_id))
    worker = _observed_process(
        flow,
        profile_id="worker",
        instance=flow.worker_closure,
        epoch=flow.worker_proc.exec_generation.witness_reference,
        entrypoints=("worker-entry",),
        steps=worker_steps,
        child_frontier=(child_id,) if flow.spawned else (),
        state="running",
        scope=scopes.get("worker"),
    )
    if not flow.spawned:
        return (worker,)
    child_steps = [start, *_loads((*flow.child_runtime_script, *flow.child_load_script))]
    if flow.terminated:
        child_steps.append(("end", None, None, "trusted-launch", None))
    child = _observed_process(
        flow,
        profile_id="child",
        instance=flow.closure_child,
        epoch=flow.host_child.exec_generation.witness_reference,
        entrypoints=("child-entry",),
        steps=child_steps,
        child_frontier=(),
        state="terminated" if flow.terminated else "running",
        scope=scopes.get("child"),
    )
    return (worker, child)


def _observer_checkpoints(flow, reviewed: ReviewedSourceGraph, scopes=None):
    """The observer's sealed scope record of each process, by closure instance id."""
    return {p.instance.instance_id: p.checkpoint for p in _observer_record(flow, reviewed, scopes)}


def _build(flow, scopes=None, *, boundary: str = "C_BEFORE_COUNT"):
    """Seal the collector's half with the observer's own scope record."""
    return flow.collector.build_envelope(
        observer_checkpoints=_observer_checkpoints(flow, flow.reviewed, scopes),
        boundary=boundary,  # type: ignore[arg-type]
    )


def _expected_from_record(records) -> tuple[ExpectedProcess, ...]:
    """The reviewed expectation of each observed container process: every category."""
    return tuple(
        ExpectedProcess(
            profile_id=p.profile_id,
            instance=p.instance,
            frontier=ProcessFrontier(
                instance_id=p.instance.instance_id,
                epoch=p.checkpoint.epoch,
                last_sequence=p.checkpoint.last_sequence,
                last_event_id=p.checkpoint.last_event_id,
                child_frontier=p.checkpoint.child_frontier,
                checkpoint_ref=p.checkpoint.checkpoint_ref,
            ),
            coverage=ALL_N3_COVERAGE_CATEGORIES,
        )
        for p in records
    )


def _expectation_and_origins(
    flow,
    base,
    reviewed,
    worker_envelope,
    host_procs,
    *,
    drop_fact_purpose: str | None = None,
    scopes=None,
):
    """The expectation and shared origin facts, from the test's observer record only."""
    record = _observer_record(flow, reviewed, scopes)
    host_expected = tuple(p for p in base.expected.processes if p.instance.location == "host")
    expectation = replace(
        base.expected,
        binding=worker_envelope.envelope.binding,
        reviewed_graph=flow.graph_ref,
        processes=(*host_expected, *_expected_from_record(record)),
    )
    # Shared origins only: each half's observer identity is passed separately and
    # the merged envelope's origin is derived, never supplied.
    verified = VerifiedClosureOrigins(
        reviewed_bytes=reviewed.content,
        observed_bytes=None,
        expectation=claim_identity(expectation),
        validity_checkpoint=worker_envelope.envelope.boundary.validity_checkpoint,
        facts=tuple(
            f
            for f in witnesses(reviewed.graph, (*host_procs, *record))
            if f.purpose != drop_fact_purpose
        ),
    )
    return expectation, verified, record


def _compare_capture(
    flow,
    base,
    reviewed,
    ev,
    *,
    worker_envelope=None,
    drop_fact_purpose: str | None = None,
    scopes=None,
) -> SimpleNamespace:
    """Compare the captured worker half with the host half.

    The expectation and the origin facts come from the test's observer record,
    never from the collector.
    """
    if worker_envelope is None:
        env_res = _build(flow)
        assert isinstance(env_res, AcceptedData), env_res
        worker_envelope = env_res.data
    binding = worker_envelope.envelope.binding
    host_procs = _make_host_procs(base, reviewed, binding)
    peer_envelope = validate_loaded_envelope(
        to_wire(
            ClosureEnvelope(
                schema="p3-reviewed-loaded-closure/1",
                envelope_id="envelope-host-1",
                reviewed_graph=flow.graph_ref,
                legacy_links=(),
                binding=binding,
                boundary=worker_envelope.envelope.boundary,
                process_observations=host_procs,
                provenance_refs=(),
            )
        )
    )
    expectation, verified, record = _expectation_and_origins(
        flow,
        base,
        reviewed,
        worker_envelope,
        host_procs,
        drop_fact_purpose=drop_fact_purpose,
        scopes=scopes,
    )
    result = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        worker_observed_bytes=worker_envelope.content,
        peer_envelope=peer_envelope,
        peer_observed_bytes=peer_envelope.content,
        expectation=expectation,
        verified_origins=verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, record[0].checkpoint.last_sequence, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    return SimpleNamespace(
        result=result,
        worker_envelope=worker_envelope,
        peer_envelope=peer_envelope,
        host_procs=host_procs,
        expectation=expectation,
        verified=verified,
    )


def _reviewed_world(tmp_path: Path):
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    return repo_dir, base, reviewed, ev


def test_worker_closure_capture_combined_happy_path(tmp_path: Path) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)

    observer_scopes = _observer_checkpoints(flow, reviewed)
    env_res = flow.collector.build_envelope(
        observer_checkpoints=observer_scopes, boundary="C_BEFORE_COUNT"
    )
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    validate_loaded_envelope(to_wire(worker_envelope.envelope))
    # The collector recorded exactly what the observer saw: the worker and its child.
    assert worker_envelope.envelope.process_observations == _observer_record(flow, reviewed)

    cmp = _compare_capture(flow, base, reviewed, ev, worker_envelope=worker_envelope)
    assert isinstance(cmp.result, AcceptedData)
    assert cmp.result.data.disposition == "MATCH"

    selected_job = make_selected_job()
    dual = merge_dual_role_halves(
        worker_envelope=worker_envelope,
        worker_observed_bytes=worker_envelope.content,
        peer_envelope=cmp.peer_envelope,
        peer_observed_bytes=cmp.peer_envelope.content,
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(dual, AcceptedData)
    merged_env = dual.data.envelope
    all_procs = (*cmp.host_procs, *worker_envelope.envelope.process_observations)
    assert merged_env.envelope.process_observations == all_procs
    assert merged_env.envelope.envelope_id == (
        f"{worker_envelope.envelope.envelope_id}+envelope-host-1"
    )
    assert dual.data.observed_bytes == merged_env.content
    merged_verified = replace(cmp.verified, observed_bytes=dual.data.observed_bytes)
    sys_comp = SystemsSourceClosureComparator(
        job_lookup=lambda _rev: selected_job,
        peer_lookup=lambda _rev: ev.processes[0],
        expectation_lookup=lambda _rev, _b: (cmp.expectation, merged_verified),
    )
    sys_res = sys_comp.compare(
        reviewed,
        merged_env,
        selection=selected_job,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(sys_res, AcceptedData)
    assert sys_res.data.disposition == "MATCH"


def test_refusal_twin_observation_gap_on_late_attach(tmp_path: Path) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    _, _, _, worker_closure = make_host_and_worker_processes()
    job = make_selected_job()
    collector, _ = _new_collector(
        base, reviewed, ev, binding=_binding_for_job(base, job), worker_closure=worker_closure
    )
    # Skipping record_docker_launch simulates late attach / bootstrap gap
    early_res = collector.record_early_bootstrap(
        execution_id=job.pre_dispatch_or_running_job.dispatch.execution_uuid,
        had_box_profile=True,
        bootstrap_loads=_observed_loads(reviewed, BOOTSTRAP_SCRIPT),
        boundary="B_PRE_REQUEST",
    )
    assert isinstance(early_res, Refusal)
    assert early_res.code == RefusalCode.OBSERVATION_GAP

    env_res = collector.build_envelope(observer_checkpoints={}, boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.OBSERVATION_GAP


@pytest.mark.parametrize("process", ["worker", "child"])
def test_refusal_twin_closure_incomplete_on_missing_category(tmp_path: Path, process: str) -> None:
    """The observer's scope record lacks "children": the collector adds none of its own."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    without = tuple(c for c in ALL_N3_COVERAGE_CATEGORIES if c != "children")
    env_res = _build(flow, {process: {"coverage": without}})
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.CLOSURE_INCOMPLETE


def _observed_worker(job):
    """The authenticated observation a clean Docker launch of ``job`` returns."""
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    adapter = DockerLaunchObservationAdapter(
        worker_observer=WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble()),
        grant=make_grant(job, boundary="C_BEFORE_COUNT"),
        selected_job=job,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(adapter.before_container_create(execution_id=exec_uuid), AcceptedData)
    started = adapter.after_container_start(execution_id=exec_uuid, container_id="container-1")
    assert isinstance(started, AcceptedData)
    return started.data.worker_observation


def _forged_job(job, case: str):
    if case == "observed_job_selection_revision":
        return replace(job, selection_revision="selection-other")
    if case == "observed_route":
        forged = replace(job)
        object.__setattr__(forged, "route", "external-db-other")
        return forged
    assert case == "pre_dispatch_job"
    key = job.pre_dispatch_or_running_job
    return replace(
        job,
        pre_dispatch_or_running_job=PreDispatchJob(
            execution_uuid=key.dispatch.execution_uuid,
            designated_workflow="workflow-263",
            descriptor_digest="3" * 64,
            job_revision=key.job_revision,
        ),
    )


# (case, closure worker changes, closure binding changes, observation change, code)
M2_BINDING_TWINS = (
    ("clean", {}, {}, None, None),
    ("worker_pid", {"pid": 4345}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("worker_boot", {"host_boot": "boot-other"}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("worker_pid_ns", {"pid_namespace": "pidns-other"}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("worker_mnt_ns", {"mount_namespace": "mntns-other"}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("worker_user_ns", {"user_namespace": "userns-other"}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("worker_launch", {"launch_identity": "launch-other"}, {}, None, RefusalCode.RUNTIME_CHANGED),
    ("selection_revision", {}, {"selection_revision": "selection-other"}, None, RefusalCode.SELECTION_CHANGED),
    ("observation_selection_revision", {}, {}, "observation_selection_revision", RefusalCode.SELECTION_CHANGED),
    ("observed_job_selection_revision", {}, {}, "observed_job_selection_revision", RefusalCode.SELECTION_CHANGED),
    ("job_revision", {}, {"job_revision": "job-other"}, None, RefusalCode.SELECTION_CHANGED),
    ("attempt", {}, {"attempt": 2}, None, RefusalCode.DISPATCH_CHANGED),
    ("dispatch_nonce", {}, {"dispatch_nonce": "00000000-0000-4000-8000-000000000265"}, None, RefusalCode.DISPATCH_CHANGED),
    ("execution_uuid", {}, {"execution_uuid": "00000000-0000-4000-8000-000000000266"}, None, RefusalCode.DISPATCH_CHANGED),
    ("observed_route", {}, {}, "observed_route", RefusalCode.ROUTE_UNSUPPORTED),
    ("pre_dispatch_job", {}, {}, "pre_dispatch_job", RefusalCode.DISPATCH_CHANGED),
)


@pytest.mark.parametrize(
    ("case", "closure_changes", "binding_changes", "observation_change", "code"),
    M2_BINDING_TWINS,
    ids=[t[0] for t in M2_BINDING_TWINS],
)
def test_refusal_twin_closure_not_bound_to_observed_worker_or_selection(
    tmp_path: Path, case, closure_changes, binding_changes, observation_change, code
) -> None:
    """Architecture #473 M2: the launch binds the closure to the observed worker and job."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    job = make_selected_job()
    observation = _observed_worker(job)
    if observation_change == "observation_selection_revision":
        observation = replace(observation, selection_revision="selection-other")
    elif observation_change is not None:
        observation = replace(observation, job=_forged_job(job, observation_change))
    _, _, _, worker_closure = make_host_and_worker_processes()
    binding = replace(_binding_for_job(base, job), **binding_changes)
    collector, _ = _new_collector(
        base,
        reviewed,
        ev,
        binding=binding,
        worker_closure=replace(worker_closure, **closure_changes),
    )
    res = collector.record_docker_launch(
        execution_id=binding.execution_uuid,
        container_id="container-1",
        worker_observation=observation,
        runtime_loads=_observed_loads(reviewed, WORKER_RUNTIME_SCRIPT),
        boundary="C_BEFORE_COUNT",
    )
    if code is None:
        assert isinstance(res, AcceptedData), case
        assert set(collector.recorded_streams) == {worker_closure.instance_id}
        return
    assert isinstance(res, Refusal), case
    assert res.code == code, case
    # A refused launch records nothing: no stream, and later stages see a gap.
    assert collector.recorded_streams == {}


@pytest.mark.parametrize("started_execution", ["same", "other"])
def test_refusal_twin_container_start_for_another_execution_writes_no_record(
    tmp_path: Path, started_execution: str
) -> None:
    """Architecture #482 S6: after_container_start trusts the collector's execution-id check."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    job = make_selected_job()
    _, _, _, worker_closure = make_host_and_worker_processes()
    collector, _ = _new_collector(
        base, reviewed, ev, binding=_binding_for_job(base, job), worker_closure=worker_closure
    )
    adapter = DockerLaunchObservationAdapter(
        worker_observer=WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble()),
        grant=make_grant(job, boundary="C_BEFORE_COUNT"),
        selected_job=job,
        closure_collector=collector,
        runtime_loads=_observed_loads(reviewed, WORKER_RUNTIME_SCRIPT),
        boundary="C_BEFORE_COUNT",
    )
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    assert isinstance(adapter.before_container_create(execution_id=exec_uuid), AcceptedData)
    started = exec_uuid if started_execution == "same" else "00000000-0000-4000-8000-000000000997"
    res = adapter.after_container_start(execution_id=started, container_id="container-1")
    if started_execution == "same":
        assert isinstance(res, AcceptedData), res
        assert len(adapter.records) == 1
        assert set(collector.recorded_streams) == {worker_closure.instance_id}
        return
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.DISPATCH_CHANGED
    assert adapter.records == ()
    assert collector.recorded_streams == {}


@pytest.mark.parametrize("mechanism", ["authenticated", "unauthenticated"])
def test_refusal_twin_child_refused_by_closure_is_never_registered(
    tmp_path: Path, mechanism: str
) -> None:
    """Architecture #482 S7: the closure refuses the child before the registry write."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    refused = mechanism == "unauthenticated"
    flow = _run_opt_in_worker_capture_flow(
        base,
        reviewed,
        ev,
        terminate_child=False,
        collector_kwargs={"mechanism": "self-labelled-probe/1"} if refused else None,
        expect_spawn_refused=refused,
    )
    # The same child registered again without a closure collector: an entry the
    # refused spawn left behind would refuse it as a duplicate (RUNTIME_CHANGED).
    again = BashChildLaunchAdapter(
        **flow.common,
        parent_instance=flow.worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=flow.resolve_child,
        boundary="C_BEFORE_COUNT",
    ).on_spawned(os_pid=CHILD_OS_PID)
    if not refused:
        assert isinstance(again, Refusal)
        assert again.code == RefusalCode.RUNTIME_CHANGED
        return
    assert flow.spawn_result.code == RefusalCode.CLOSURE_INCOMPLETE
    assert flow.bash_adapter.spawn_registrations == 0
    assert flow.bash_adapter.registrations == ()
    assert set(flow.collector.recorded_streams) == {flow.worker_closure.instance_id}
    assert isinstance(again, AcceptedData), again


def test_worker_epoch_is_the_observed_exec_generation(tmp_path: Path) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = _build(flow)
    assert isinstance(env_res, AcceptedData)
    worker = env_res.data.envelope.process_observations[0]
    assert worker.instance.instance_id == flow.worker_closure.instance_id
    assert worker.checkpoint.epoch == flow.worker_proc.exec_generation.witness_reference


def _without(category: str) -> tuple[str, ...]:
    return tuple(c for c in ALL_N3_COVERAGE_CATEGORIES if c != category)


# (case, scope change, code): the observer's sealed scope falls short of the stream.
OBSERVER_SCOPE_SHORTFALLS = (
    ("SC-03_native_not_watched", {"coverage": _without("native")}, RefusalCode.CLOSURE_INCOMPLETE),
    ("SC-04_effect_fence_in_gaps", {"gaps": ("effect_fence",)}, RefusalCode.OBSERVATION_GAP),
    ("SC-05_control_plane_in_gaps", {"gaps": ("control_plane",)}, RefusalCode.OBSERVATION_GAP),
    ("dynamic_in_gaps", {"gaps": ("dynamic",)}, RefusalCode.CLOSURE_INCOMPLETE),
    ("SC-07_sealed_before_last_load", {"last_sequence": 1}, RefusalCode.OBSERVATION_GAP),
    ("SC-08_unsealed", {"sealed": False}, RefusalCode.OBSERVATION_GAP),
    ("SC-08_loss", {"loss_count": 1}, RefusalCode.OBSERVATION_GAP),
    ("epoch", {"epoch": "epoch-other"}, RefusalCode.OBSERVATION_GAP),
    ("first_sequence", {"first_sequence": 1}, RefusalCode.OBSERVATION_GAP),
    ("last_event_id", {"last_event_id": "event-other"}, RefusalCode.OBSERVATION_GAP),
    ("child_frontier", {"child_frontier": ("child-other",)}, RefusalCode.OBSERVATION_GAP),
    ("initial_state_ref", {"initial_state_ref": None}, RefusalCode.OBSERVATION_GAP),
    ("checkpoint_ref", {"checkpoint_ref": None}, RefusalCode.OBSERVATION_GAP),
    ("boundary", "boundary", RefusalCode.OBSERVATION_GAP),
)


@pytest.mark.parametrize(
    ("case", "change", "code"), OBSERVER_SCOPE_SHORTFALLS, ids=[t[0] for t in OBSERVER_SCOPE_SHORTFALLS]
)
@pytest.mark.parametrize("process", ["worker", "child"])
def test_refusal_twin_observer_scope_shortfall(
    tmp_path: Path, case: str, change, code: RefusalCode, process: str
) -> None:
    """Systems #95 shape: the scope is the observer's sealed record; any shortfall refuses."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    if change == "boundary":
        change = {"boundary": replace(flow.closure_boundary, barrier_id="barrier-other")}
    assert isinstance(_build(flow), AcceptedData)
    env_res = _build(flow, {process: change})
    assert isinstance(env_res, Refusal), case
    assert env_res.code == code, case


def test_refusal_twin_observer_scope_missing_or_extra_process(tmp_path: Path) -> None:
    """Every recorded process needs the observer's scope, and no scope without a stream."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    scopes = _observer_checkpoints(flow, reviewed)
    missing = {k: v for k, v in scopes.items() if k != flow.closure_child.instance_id}
    res = flow.collector.build_envelope(observer_checkpoints=missing, boundary="C_BEFORE_COUNT")
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.OBSERVATION_GAP
    extra = {**scopes, "process-unrecorded": scopes[flow.worker_closure.instance_id]}
    res = flow.collector.build_envelope(observer_checkpoints=extra, boundary="C_BEFORE_COUNT")
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.CLOSURE_INCOMPLETE
    not_a_scope = {**scopes, flow.worker_closure.instance_id: {"coverage": "all"}}
    res = flow.collector.build_envelope(
        observer_checkpoints=not_a_scope,  # type: ignore[arg-type]
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.OBSERVATION_GAP


def test_refusal_twin_producer_widened_scope_is_refused_by_comparator(
    tmp_path: Path, monkeypatch
) -> None:
    """SC-06: an envelope claiming more than the observer sealed never compares MATCH."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = _build(flow)
    assert isinstance(env_res, AcceptedData)
    # The observer really sealed the worker without native; the envelope claims all.
    seen = _record_comparisons(monkeypatch)
    cmp = _compare_capture(
        flow,
        base,
        reviewed,
        ev,
        worker_envelope=env_res.data,
        scopes={"worker": {"coverage": _without("native")}},
    )
    assert seen and seen[0].disposition != "MATCH"
    assert isinstance(cmp.result, Refusal)


def test_no_hook_or_adapter_can_declare_coverage() -> None:
    """Architecture #473 M3: coverage has no declared input anywhere on the opt-in path."""
    declared = {"categories", "coverage", "child_coverage", "coverage_categories"}
    for owner in (
        DockerLaunchObservationAdapter,
        EarlyBootstrapObservationHook,
        RunnerBootstrapObservationHook,
        ScriptLaunchObservationAdapter,
        BashChildLaunchAdapter,
        ChildRegistrationRegistry,
        WorkerClosureCollector,
    ):
        for name, member in inspect.getmembers(owner, inspect.isfunction):
            if name.startswith("_") and name != "__init__":
                continue  # private helpers receive coverage the collector derived
            params = set(inspect.signature(member).parameters)
            assert not params & declared, f"{owner.__name__}.{name} declares coverage"


def test_refusal_twin_closure_version_on_schema_mismatch(tmp_path: Path) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = _build(flow)
    assert isinstance(env_res, AcceptedData)
    bad_inner = replace(env_res.data.envelope)
    object.__setattr__(bad_inner, "schema", "qa-ops-host-source-closure/1")
    bad_worker_env = replace(env_res.data, envelope=bad_inner)
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=bad_worker_env,
        worker_observed_bytes=bad_worker_env.content,
        peer_envelope=base.observed,
        peer_observed_bytes=base.observed.content,
        expectation=base.expected,
        verified_origins=replace(base.verified, observed_bytes=None),
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_res, Refusal)
    assert comp_res.code == RefusalCode.CLOSURE_VERSION


def test_refusal_twin_closure_mismatch_on_unreviewed_module(tmp_path: Path, monkeypatch) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    # The observer saw a module the reviewed graph does not hold.
    unreviewed = ("unreviewed_plugin", byte_identity(b"unreviewed plugin"))
    flow = _run_opt_in_worker_capture_flow(
        base, reviewed, ev, runner_script=(*RUNNER_SCRIPT, unreviewed)
    )
    seen = _record_comparisons(monkeypatch)
    cmp = _compare_capture(flow, base, reviewed, ev)
    # The landed CoverageBookkeeper refuses a load outside the reviewed profile's
    # allowed nodes before the comparison runs.
    assert seen == []
    assert isinstance(cmp.result, Refusal)
    assert cmp.result.code == RefusalCode.CLOSURE_MISMATCH


def test_refusal_twin_dirty_tree_source_changed_and_digest_mismatch_closure_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_dir, base, reviewed, ev = _reviewed_world(tmp_path)

    # 1. Dirty worktree -> SOURCE_CHANGED
    (repo_dir / "main.py").write_bytes(b"tampered dirty tree")
    dirty_res = capture_git_checkout_provenance(
        repo_root=repo_dir,
        repo_id="repo",
        role="temper",
        tracked_files=(("main", "main.py"),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(dirty_res, Refusal)
    assert dirty_res.code == RefusalCode.SOURCE_CHANGED

    # 2. Clean repo; the observer saw "main" loaded with other bytes. The
    # substitution is REFUSED by compare_loaded_source and mapped by the landed
    # comparison_to_refusal -> CLOSURE_MISMATCH; facts and expectation are the
    # happy path's, so the substituted bytes are the only difference.
    _git(repo_dir, "checkout", "--", "main.py")
    substituted = tuple(
        (node_id, _loaded_bytes(reviewed, "dep")) if node_id == "main" else node_id
        for node_id in BOOTSTRAP_SCRIPT
    )
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev, bootstrap_script=substituted)
    seen = _record_comparisons(monkeypatch)
    cmp = _compare_capture(flow, base, reviewed, ev)
    assert [(c.disposition, c.reasons) for c in seen] == [("REFUSED", ("BYTE_SUBSTITUTION",))]
    assert isinstance(cmp.result, Refusal)
    assert cmp.result.code == RefusalCode.CLOSURE_MISMATCH


def test_guard_bite_box_profile_closure_never_counts_as_complete(
    tmp_path: Path,
) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev, spawn_child=False)
    early_hook = EarlyBootstrapObservationHook(
        worker_observer=WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble()),
        grant=make_grant(flow.job),
        selected_job=flow.job,
        closure_collector=flow.collector,
        bootstrap_loads=(),
        use_box_profile_closure_as_complete=True,
    )
    res = early_hook.on_delivery_taken(had_box_profile=True)
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.CLOSURE_INCOMPLETE
    assert flow.collector.box_profile_closure_ignored is True


def test_guard_bite_unverified_launcher_registration_never_counts_as_complete(
    tmp_path: Path,
) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    grant = make_grant(flow.job, boundary="C_BEFORE_COUNT")
    reg = ChildRegistrationRegistry(
        selected_job=flow.job,
        worker_instance=flow.worker_proc,
        worker_closure_instance=flow.worker_closure,
        closure_collector=flow.collector,
    )
    surrogate_res = reg.verify_pre_spawn(
        grant=grant,
        selected_job=flow.job,
        intended_effect=make_selected_op(),
        boundary="C_BEFORE_COUNT",
        verification_port=None,
        registration_source="bash_argv_log",
    )
    assert isinstance(surrogate_res, Refusal)
    assert surrogate_res.code == RefusalCode.PEER_UNVERIFIED
    assert flow.collector.surrogate_registration_tainted is True

    env_res = _build(flow)
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.PEER_UNVERIFIED


@pytest.mark.parametrize("process", ["worker", "child"])
def test_guard_bite_dropping_any_n3_coverage_category_fails(
    tmp_path: Path, process: str
) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    assert len(ALL_N3_COVERAGE_CATEGORIES) == 10

    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    for dropped_cat in ALL_N3_COVERAGE_CATEGORIES:
        # The observer's sealed scope for one process omits the category.
        without = tuple(c for c in ALL_N3_COVERAGE_CATEGORIES if c != dropped_cat)
        env_res = _build(flow, {process: {"coverage": without}})
        assert isinstance(env_res, Refusal), f"Dropping {dropped_cat} from {process} must refuse"
        assert env_res.code == (
            RefusalCode.OBSERVATION_GAP
            if dropped_cat in ("effect_fence", "control_plane")
            else RefusalCode.CLOSURE_INCOMPLETE
        )


def test_guard_bite_one_half_envelope_refused(tmp_path: Path, monkeypatch) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = _build(flow)
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    # A one-half envelope must be refused before any comparison runs.
    compared = []
    landed_compare = worker_closure_capture.compare_loaded_source

    def recording_compare(*args, **kwargs):
        compared.append(args)
        return landed_compare(*args, **kwargs)

    monkeypatch.setattr(worker_closure_capture, "compare_loaded_source", recording_compare)
    container_only_peer = validate_loaded_envelope(
        to_wire(
            replace(
                worker_envelope.envelope,
                envelope_id="envelope-host-1",
                process_observations=(),
            )
        )
    )
    # 1. Missing peer; 2. the worker half again as its own peer (no host half);
    # 3. a distinct valid peer with no host observations: container-only merge.
    for peer in (None, worker_envelope, container_only_peer):
        comp = verify_and_compare_worker_closure(
            reviewed_graph=reviewed,
            worker_envelope=worker_envelope,
            worker_observed_bytes=worker_envelope.content,
            peer_envelope=peer,
            peer_observed_bytes=None if peer is None else peer.content,
            expectation=base.expected,
            verified_origins=replace(base.verified, observed_bytes=None),
            bookkeeper=CoverageBookkeeper(),
            load_stream_refs=(make_event_range(0, 8, 0),),
            boundary="C_BEFORE_COUNT",
            evidence=ev,
        )
        assert isinstance(comp, Refusal)
        assert comp.code == RefusalCode.CLOSURE_INCOMPLETE
    assert compared == []


def test_guard_bite_unknown_disposition_never_maps_to_match(
    tmp_path: Path, monkeypatch
) -> None:
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    # Strip the review origin fact -> compare_loaded_source returns disposition="UNKNOWN"
    seen = _record_comparisons(monkeypatch)
    cmp = _compare_capture(flow, base, reviewed, ev, drop_fact_purpose="review")
    assert [c.disposition for c in seen] == ["UNKNOWN"]
    assert isinstance(cmp.result, Refusal)
    assert cmp.result.code == RefusalCode.CLOSURE_INCOMPLETE


def _dual_role_world(tmp_path: Path) -> SimpleNamespace:
    """The happy path's matching worker + host halves, expectation and shared origins."""
    _, base, reviewed, ev = _reviewed_world(tmp_path)
    flow = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = _build(flow)
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    host_procs = _make_host_procs(base, reviewed, worker_envelope.envelope.binding)
    peer_envelope = validate_loaded_envelope(
        to_wire(
            replace(
                worker_envelope.envelope,
                envelope_id="envelope-host-1",
                process_observations=host_procs,
            )
        )
    )
    expectation, verified, _ = _expectation_and_origins(
        flow, base, reviewed, worker_envelope, host_procs
    )
    return SimpleNamespace(
        reviewed=reviewed,
        worker=worker_envelope,
        peer=peer_envelope,
        expectation=expectation,
        verified=verified,
        ev=ev,
    )


def _compare_dual_role(
    world,
    *,
    worker_observed_bytes,
    peer_observed_bytes,
    peer,
    verified,
    worker=None,
    reviewed=None,
):
    return verify_and_compare_worker_closure(
        reviewed_graph=world.reviewed if reviewed is None else reviewed,
        worker_envelope=world.worker if worker is None else worker,
        worker_observed_bytes=worker_observed_bytes,
        peer_envelope=peer,
        peer_observed_bytes=peer_observed_bytes,
        expectation=world.expectation,
        verified_origins=verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=world.ev,
    )


def _record_comparisons(monkeypatch) -> list:
    seen: list = []
    landed_compare = worker_closure_capture.compare_loaded_source

    def recording_compare(*args, **kwargs):
        result = landed_compare(*args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(
        worker_closure_capture, "compare_loaded_source", recording_compare
    )
    return seen


@pytest.mark.parametrize(
    ("case", "expected_code", "reaches_comparator"),
    [
        ("worker_origin_unavailable", RefusalCode.OBSERVATION_GAP, True),
        ("peer_origin_unavailable", RefusalCode.OBSERVATION_GAP, True),
        ("worker_origin_other_bytes", RefusalCode.CLOSURE_MISMATCH, False),
        ("peer_origin_other_bytes", RefusalCode.CLOSURE_MISMATCH, False),
        ("merged_origin_supplied", RefusalCode.CLOSURE_MISMATCH, False),
    ],
)
def test_guard_bite_observer_origin_never_synthesized(
    tmp_path: Path, monkeypatch, case, expected_code, reaches_comparator
) -> None:
    world = _dual_role_world(tmp_path)
    worker_bytes, peer_bytes, verified = (
        world.worker.content,
        world.peer.content,
        world.verified,
    )
    if case == "worker_origin_unavailable":
        worker_bytes = None
    elif case == "peer_origin_unavailable":
        peer_bytes = None
    elif case == "worker_origin_other_bytes":
        worker_bytes = world.peer.content
    elif case == "peer_origin_other_bytes":
        peer_bytes = world.worker.content
    else:
        # The merged envelope has no observer: an origin supplied for it is the
        # self-referential identity this guard refuses, even when it is exact.
        dual = merge_dual_role_halves(
            worker_envelope=world.worker,
            worker_observed_bytes=worker_bytes,
            peer_envelope=world.peer,
            peer_observed_bytes=peer_bytes,
            boundary="C_BEFORE_COUNT",
            evidence=world.ev,
        )
        assert isinstance(dual, AcceptedData)
        verified = replace(world.verified, observed_bytes=dual.data.envelope.content)
    seen = _record_comparisons(monkeypatch)
    res = _compare_dual_role(
        world,
        worker_observed_bytes=worker_bytes,
        peer_observed_bytes=peer_bytes,
        peer=world.peer,
        verified=verified,
    )
    assert isinstance(res, Refusal)
    assert res.code == expected_code
    if reaches_comparator:
        assert [(c.disposition, c.reasons) for c in seen] == [
            ("UNKNOWN", ("OBSERVER_ORIGIN",))
        ]
    else:
        assert seen == []


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("schema", RefusalCode.CLOSURE_VERSION),
        ("binding", RefusalCode.SUBJECT_MISMATCH),
        ("boundary", RefusalCode.SUBJECT_MISMATCH),
        ("reviewed_graph", RefusalCode.CLOSURE_MISMATCH),
        ("legacy_links", RefusalCode.CLOSURE_MISMATCH),
    ],
)
def test_guard_bite_peer_envelope_fields_must_match_worker(
    tmp_path: Path, monkeypatch, field, expected_code
) -> None:
    world = _dual_role_world(tmp_path)
    inner = world.peer.envelope
    if field == "schema":
        changed = replace(inner)
        object.__setattr__(changed, "schema", "qa-ops-host-source-closure/1")
        peer = replace(world.peer, envelope=changed)
    else:
        if field == "binding":
            changed = replace(
                inner, binding=replace(inner.binding, execution_uuid="other-execution")
            )
        elif field == "boundary":
            changed = replace(
                inner,
                boundary=replace(
                    inner.boundary, validity_checkpoint="other-checkpoint"
                ),
            )
        elif field == "reviewed_graph":
            changed = replace(
                inner,
                reviewed_graph=replace(inner.reviewed_graph, record_id="other-graph"),
            )
        else:
            legacy_ref = EvidenceRef(
                schema="qa-ops-host-source-closure/1",
                content=byte_content_identity("legacy-closure"),
                supplier="qa",
                record_id="legacy-1",
            )
            changed = replace(inner, legacy_links=(LegacyLink(legacy_ref, ()),))
        peer = validate_loaded_envelope(to_wire(changed))
    seen = _record_comparisons(monkeypatch)
    res = _compare_dual_role(
        world,
        worker_observed_bytes=world.worker.content,
        peer_observed_bytes=peer.content,
        peer=peer,
        verified=world.verified,
    )
    assert isinstance(res, Refusal)
    assert res.code == expected_code
    assert seen == []


@pytest.mark.parametrize("supplied", ["stale", "true"])
@pytest.mark.parametrize("half", ["worker", "peer"])
def test_guard_bite_stale_half_content_field_refused(
    tmp_path: Path, monkeypatch, half, supplied
) -> None:
    # LoadedClosureEnvelope.content is caller-set: a half whose envelope changed
    # after construction keeps a stale content field naming bytes never observed.
    world = _dual_role_world(tmp_path)
    original = world.worker if half == "worker" else world.peer
    changed_inner = replace(
        original.envelope, envelope_id=f"{original.envelope.envelope_id}-changed"
    )
    changed_content = validate_loaded_envelope(to_wire(changed_inner)).content
    stale_half = replace(original, envelope=changed_inner)
    assert stale_half.content == original.content != changed_content
    identity = original.content if supplied == "stale" else changed_content
    worker, worker_bytes = world.worker, world.worker.content
    peer, peer_bytes = world.peer, world.peer.content
    if half == "worker":
        worker, worker_bytes = stale_half, identity
    else:
        peer, peer_bytes = stale_half, identity
    seen = _record_comparisons(monkeypatch)
    res = _compare_dual_role(
        world,
        worker_observed_bytes=worker_bytes,
        peer_observed_bytes=peer_bytes,
        peer=peer,
        verified=world.verified,
        worker=worker,
    )
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.CLOSURE_MISMATCH
    assert seen == []


def test_guard_bite_stale_reviewed_graph_content_field_refused(
    tmp_path: Path, monkeypatch
) -> None:
    world = _dual_role_world(tmp_path)
    changed_graph = replace(
        world.reviewed.graph,
        completeness_review_ref=EvidenceRef(
            schema="synthetic-evidence/1",
            content=byte_content_identity("other-completeness-review"),
            supplier="systems",
            record_id="completeness-review-other",
        ),
    )
    stale_reviewed = replace(world.reviewed, graph=changed_graph)
    changed_content = validate_reviewed_graph(to_wire(changed_graph)).content
    assert stale_reviewed.content == world.verified.reviewed_bytes != changed_content
    seen = _record_comparisons(monkeypatch)
    res = _compare_dual_role(
        world,
        worker_observed_bytes=world.worker.content,
        peer_observed_bytes=world.peer.content,
        peer=world.peer,
        verified=world.verified,
        reviewed=stale_reviewed,
    )
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.CLOSURE_MISMATCH
    assert seen == []


@pytest.mark.parametrize("peer_only_first", [True, False])
def test_merge_dual_role_halves_keeps_peer_provenance_refs(
    tmp_path: Path, peer_only_first: bool
) -> None:
    """Merged provenance is peer-first, first kept: a peer-only ref ahead of the
    worker's refs stays ahead (pins the order, Architecture #473 S1)."""
    world = _dual_role_world(tmp_path)
    host_ref, worker_ref = (
        EvidenceRef(
            schema="synthetic-evidence/1",
            content=byte_content_identity(f"{side}-provenance"),
            supplier=supplier,
            record_id=f"{side}-provenance-1",
        )
        for side, supplier in (("host", "ops"), ("worker", "temper"))
    )
    worker = validate_loaded_envelope(
        to_wire(replace(world.worker.envelope, provenance_refs=(worker_ref,)))
    )
    peer_refs = (host_ref, worker_ref) if peer_only_first else (worker_ref, host_ref)
    peer = validate_loaded_envelope(
        to_wire(replace(world.peer.envelope, provenance_refs=peer_refs))
    )
    dual = merge_dual_role_halves(
        worker_envelope=worker,
        worker_observed_bytes=worker.content,
        peer_envelope=peer,
        peer_observed_bytes=peer.content,
        boundary="C_BEFORE_COUNT",
        evidence=world.ev,
    )
    assert isinstance(dual, AcceptedData)
    merged = dual.data.envelope.envelope
    assert merged.provenance_refs == peer_refs
    assert merged.process_observations == (
        *peer.envelope.process_observations,
        *worker.envelope.process_observations,
    )
    assert dual.data.observed_bytes == dual.data.envelope.content


def test_unchanged_defaults_when_no_adapter_or_no_collector(monkeypatch) -> None:
    bin_dir = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
    monkeypatch.syspath_prepend(str(bin_dir))
    import first_app_p3_host

    assert first_app_p3_host.WRITES_ADMITTED is False

    job = make_selected_job()
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    grant = make_grant(job)
    observer = WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble())

    docker_no_collector = DockerLaunchObservationAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
    )
    assert isinstance(
        docker_no_collector.before_container_create(execution_id=exec_uuid),
        AcceptedData,
    )
    rec = docker_no_collector.after_container_start(
        execution_id=exec_uuid,
        container_id="container-1",
    )
    assert isinstance(rec, AcceptedData)
    assert rec.data.container_id == "container-1"

    early_no_collector = EarlyBootstrapObservationHook(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
    )
    early_rec = early_no_collector.on_delivery_taken(had_box_profile=True)
    assert isinstance(early_rec, AcceptedData)
    assert early_rec.data.stage == "cli_box_delivery"

    runner_no_collector = RunnerBootstrapObservationHook(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
    )
    runner_rec = runner_no_collector.on_runner_context_bootstrapped(
        execution_id=exec_uuid
    )
    assert isinstance(runner_rec, AcceptedData)
    assert runner_rec.data.stage == "runner_bootstrap"
