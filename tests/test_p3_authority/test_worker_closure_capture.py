"""Tests for P3 T5-N3W deterministic worker LoadedClosureEnvelope + GitProvenance capture."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

from p3_source_closure import (
    ClosureEnvelope,
    ReviewedSourceGraph,
    SourceGraph,
    VerifiedClosureOrigins,
    validate_loaded_envelope,
    validate_reviewed_graph,
)
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
from temper_ai.p3_authority.worker_closure_capture import (
    WorkerClosureCollector,
    capture_git_checkout_provenance,
    claim_identity,
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


def _run_opt_in_worker_capture_flow(
    base,
    reviewed: ReviewedSourceGraph,
    ev,
    *,
    boundary: str = "C_BEFORE_COUNT",
):
    job = make_selected_job()
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    grant = make_grant(job, boundary=boundary)  # type: ignore[arg-type]
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    observer = WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble())

    graph_ref = replace(
        base.observed.envelope.reviewed_graph,
        content=reviewed.content,
    )
    collector = WorkerClosureCollector(
        binding=replace(
            base.observed.envelope.binding,
            execution_uuid=exec_uuid,
        ),
        closure_boundary=base.observed.envelope.boundary,
        reviewed_graph_ref=graph_ref,
        graph_id=reviewed.graph.graph_id,
        worker_instance=worker_closure,
        evidence=ev,
    )
    by_node = {n.id: n for n in reviewed.graph.nodes}
    bootstrap_nodes = (
        ("main", by_node["main"].content),
        ("dep", by_node["dep"].content),
    )
    runner_nodes = (
        ("generated", by_node["generated"].provenance.execution_object),  # type: ignore[attr-defined]
        ("cache", by_node["cache"].content),
        ("native_binary-worker", by_node["native_binary-worker"].content),
    )
    child_loaded = bootstrap_nodes + runner_nodes

    docker_adapter = DockerLaunchObservationAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        closure_collector=collector,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(
        docker_adapter.before_container_create(execution_id=exec_uuid),
        AcceptedData,
    )
    assert isinstance(
        docker_adapter.after_container_start(
            execution_id=exec_uuid,
            container_id="container-1",
        ),
        AcceptedData,
    )

    early_hook = EarlyBootstrapObservationHook(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        closure_collector=collector,
        bootstrap_nodes=bootstrap_nodes,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(
        early_hook.on_delivery_taken(had_box_profile=True),
        AcceptedData,
    )
    assert collector.box_profile_closure_ignored is True

    runner_hook = RunnerBootstrapObservationHook(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        closure_collector=collector,
        loaded_nodes=runner_nodes,
        boundary=boundary,  # type: ignore[arg-type]
    )
    assert isinstance(
        runner_hook.on_runner_context_bootstrapped(execution_id=exec_uuid),
        AcceptedData,
    )

    def _resolve_child(os_pid: int):
        return AcceptedData(
            data=make_child_pair(worker_proc, worker_closure, os_pid=os_pid),
            evidence=ev,
        )

    bash_adapter = BashChildLaunchAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        parent_instance=worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=_resolve_child,
        closure_collector=collector,
        child_loaded_nodes=child_loaded,
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
        agent_name="script-1",
        run_id=exec_uuid,
        base_kwargs={"command": "true"},
    )
    assert isinstance(prep, AcceptedData)
    spawned = bash_adapter.on_spawned(os_pid=104)
    assert isinstance(spawned, AcceptedData)
    bash_adapter.on_terminated(
        child_key=spawned.data.key,
        os_pid=104,
        returncode=0,
        aborted=False,
        stop_reason=None,
    )
    return collector, graph_ref


def test_worker_closure_capture_combined_happy_path(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, graph_ref = _run_opt_in_worker_capture_flow(base, reviewed, ev)

    assert collector.recorded_coverage == frozenset(ALL_N3_COVERAGE_CATEGORIES)
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    validate_loaded_envelope(to_wire(worker_envelope.envelope))

    host_procs = _make_host_procs(base, reviewed, worker_envelope.envelope.binding)
    peer_envelope = validate_loaded_envelope(
        to_wire(
            ClosureEnvelope(
                schema="p3-reviewed-loaded-closure/1",
                envelope_id="envelope-host-1",
                reviewed_graph=graph_ref,
                legacy_links=(),
                binding=worker_envelope.envelope.binding,
                boundary=worker_envelope.envelope.boundary,
                process_observations=host_procs,
                provenance_refs=(),
            )
        )
    )
    host_expected = tuple(
        p for p in base.expected.processes if p.instance.location == "host"
    )
    expectation = replace(
        base.expected,
        binding=worker_envelope.envelope.binding,
        reviewed_graph=graph_ref,
        processes=(*host_expected, *collector.expected_processes()),
    )
    all_procs = (*host_procs, *worker_envelope.envelope.process_observations)
    verified = VerifiedClosureOrigins(
        reviewed_bytes=reviewed.content,
        observed_bytes=worker_envelope.content,
        expectation=claim_identity(expectation),
        validity_checkpoint=worker_envelope.envelope.boundary.validity_checkpoint,
        facts=witnesses(reviewed.graph, all_procs),
    )
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=peer_envelope,
        expectation=expectation,
        verified_origins=verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_res, AcceptedData)
    assert comp_res.data.disposition == "MATCH"

    selected_job = make_selected_job()
    merged_env = validate_loaded_envelope(
        to_wire(replace(worker_envelope.envelope, process_observations=all_procs))
    )
    merged_verified = replace(verified, observed_bytes=merged_env.content)
    sys_comp = SystemsSourceClosureComparator(
        job_lookup=lambda _rev: selected_job,
        peer_lookup=lambda _rev: ev.processes[0],
        expectation_lookup=lambda _rev, _b: (expectation, merged_verified),
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
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    _, _, _, worker_closure = make_host_and_worker_processes()
    graph_ref = replace(base.observed.envelope.reviewed_graph, content=reviewed.content)
    collector = WorkerClosureCollector(
        binding=base.observed.envelope.binding,
        closure_boundary=base.observed.envelope.boundary,
        reviewed_graph_ref=graph_ref,
        graph_id=reviewed.graph.graph_id,
        worker_instance=worker_closure,
        evidence=ev,
    )
    # Skipping record_docker_launch simulates late attach / bootstrap gap
    early_res = collector.record_early_bootstrap(
        execution_id=base.observed.envelope.binding.execution_uuid,
        had_box_profile=True,
        bootstrap_nodes=(("main", reviewed.graph.nodes[0].content),),
        boundary="B_PRE_REQUEST",
    )
    assert isinstance(early_res, Refusal)
    assert early_res.code == RefusalCode.OBSERVATION_GAP

    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.OBSERVATION_GAP


def test_refusal_twin_closure_incomplete_on_missing_category(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    _, _, _, worker_closure = make_host_and_worker_processes()
    graph_ref = replace(base.observed.envelope.reviewed_graph, content=reviewed.content)
    job = make_selected_job()
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    collector = WorkerClosureCollector(
        binding=replace(base.observed.envelope.binding, execution_uuid=exec_uuid),
        closure_boundary=base.observed.envelope.boundary,
        reviewed_graph_ref=graph_ref,
        graph_id=reviewed.graph.graph_id,
        worker_instance=worker_closure,
        evidence=ev,
    )
    observer = WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble())
    obs = observer.observe(make_grant(job), job, "A_PRE_CREATE")
    assert isinstance(obs, AcceptedData)

    assert isinstance(
        collector.record_docker_launch(
            execution_id=exec_uuid,
            container_id="container-1",
            worker_observation=obs.data,
        ),
        AcceptedData,
    )
    assert isinstance(
        collector.record_early_bootstrap(
            execution_id=exec_uuid,
            had_box_profile=True,
            bootstrap_nodes=(("main", reviewed.graph.nodes[0].content),),
        ),
        AcceptedData,
    )
    assert isinstance(
        collector.record_runner_bootstrap(
            execution_id=exec_uuid,
            loaded_nodes=(("dep", reviewed.graph.nodes[1].content),),
        ),
        AcceptedData,
    )
    # Missing "children" category -> CLOSURE_INCOMPLETE
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.CLOSURE_INCOMPLETE


def test_refusal_twin_closure_version_on_schema_mismatch(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, _ = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, AcceptedData)
    bad_inner = replace(env_res.data.envelope)
    object.__setattr__(bad_inner, "schema", "qa-ops-host-source-closure/1")
    bad_worker_env = replace(env_res.data, envelope=bad_inner)
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=bad_worker_env,
        peer_envelope=base.observed,
        expectation=base.expected,
        verified_origins=base.verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_res, Refusal)
    assert comp_res.code == RefusalCode.CLOSURE_VERSION


def test_refusal_twin_closure_mismatch_on_unreviewed_module(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, graph_ref = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    # Inject an unreviewed module load into runner bootstrap before building envelope
    assert isinstance(
        collector.record_runner_bootstrap(
            execution_id=collector._binding.execution_uuid,
            loaded_nodes=(("unreviewed_plugin", reviewed.graph.nodes[0].content),),
        ),
        AcceptedData,
    )
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data

    host_procs = tuple(
        replace(p, binding=worker_envelope.envelope.binding)
        for p in base.observed.envelope.process_observations
        if p.instance.location == "host"
    )
    peer_envelope = validate_loaded_envelope(
        to_wire(
            replace(
                worker_envelope.envelope,
                envelope_id="envelope-host-1",
                process_observations=host_procs,
            )
        )
    )
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=peer_envelope,
        expectation=base.expected,
        verified_origins=base.verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 9, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_res, Refusal)
    assert comp_res.code == RefusalCode.CLOSURE_MISMATCH


def test_refusal_twin_dirty_tree_source_changed_and_digest_mismatch_closure_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)

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

    # Restore clean repo: loaded-byte substitution / digest mismatch is REFUSED by
    # compare_loaded_source and mapped by comparison_to_refusal -> CLOSURE_MISMATCH
    _git(repo_dir, "checkout", "--", "main.py")
    collector, graph_ref = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    # Load main with substituted bytes
    assert isinstance(
        collector.record_runner_bootstrap(
            execution_id=collector._binding.execution_uuid,
            loaded_nodes=(("main", reviewed.graph.nodes[1].content),),
        ),
        AcceptedData,
    )
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    # Same binding, expectation and verified origins as the happy path, so the
    # substituted bytes are the only difference the comparison can see.
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
    host_expected = tuple(
        p for p in base.expected.processes if p.instance.location == "host"
    )
    expectation = replace(
        base.expected,
        binding=worker_envelope.envelope.binding,
        reviewed_graph=graph_ref,
        processes=(*host_expected, *collector.expected_processes()),
    )
    all_procs = (*host_procs, *worker_envelope.envelope.process_observations)
    verified = VerifiedClosureOrigins(
        reviewed_bytes=reviewed.content,
        observed_bytes=worker_envelope.content,
        expectation=claim_identity(expectation),
        validity_checkpoint=worker_envelope.envelope.boundary.validity_checkpoint,
        facts=witnesses(reviewed.graph, all_procs),
    )
    seen = []
    landed_mapping = worker_closure_capture.comparison_to_refusal

    def recording_mapping(comparison, boundary):
        seen.append(comparison)
        return landed_mapping(comparison, boundary)

    monkeypatch.setattr(worker_closure_capture, "comparison_to_refusal", recording_mapping)
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=peer_envelope,
        expectation=expectation,
        verified_origins=verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 9, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert [(c.disposition, c.reasons) for c in seen] == [
        ("REFUSED", ("BYTE_SUBSTITUTION",))
    ]
    assert isinstance(comp_res, Refusal)
    assert comp_res.code == RefusalCode.CLOSURE_MISMATCH


def test_guard_bite_box_profile_closure_never_counts_as_complete(
    tmp_path: Path,
) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    job = make_selected_job()
    exec_uuid = job.pre_dispatch_or_running_job.dispatch.execution_uuid
    grant = make_grant(job)
    _, _, _, worker_closure = make_host_and_worker_processes()
    observer = WorkerObservationAdapter(provider=SyntheticWorkerProviderDouble())
    graph_ref = replace(base.observed.envelope.reviewed_graph, content=reviewed.content)

    collector = WorkerClosureCollector(
        binding=replace(base.observed.envelope.binding, execution_uuid=exec_uuid),
        closure_boundary=base.observed.envelope.boundary,
        reviewed_graph_ref=graph_ref,
        graph_id=reviewed.graph.graph_id,
        worker_instance=worker_closure,
        evidence=ev,
    )
    docker_adapter = DockerLaunchObservationAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        closure_collector=collector,
    )
    assert isinstance(
        docker_adapter.before_container_create(execution_id=exec_uuid), AcceptedData
    )
    assert isinstance(
        docker_adapter.after_container_start(
            execution_id=exec_uuid, container_id="container-1"
        ),
        AcceptedData,
    )
    early_hook = EarlyBootstrapObservationHook(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        closure_collector=collector,
        bootstrap_nodes=(),
        use_box_profile_closure_as_complete=True,
    )
    res = early_hook.on_delivery_taken(had_box_profile=True)
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.CLOSURE_INCOMPLETE
    assert collector.box_profile_closure_ignored is True


def test_guard_bite_unverified_launcher_registration_never_counts_as_complete(
    tmp_path: Path,
) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, _ = _run_opt_in_worker_capture_flow(base, reviewed, ev)

    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    job = make_selected_job()
    grant = make_grant(job, boundary="C_BEFORE_COUNT")
    reg = ChildRegistrationRegistry(
        selected_job=job,
        worker_instance=worker_proc,
        worker_closure_instance=worker_closure,
        closure_collector=collector,
    )
    surrogate_res = reg.verify_pre_spawn(
        grant=grant,
        selected_job=job,
        intended_effect=make_selected_op(),
        boundary="C_BEFORE_COUNT",
        verification_port=None,
        registration_source="bash_argv_log",
    )
    assert isinstance(surrogate_res, Refusal)
    assert surrogate_res.code == RefusalCode.PEER_UNVERIFIED
    assert collector.surrogate_registration_tainted is True

    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, Refusal)
    assert env_res.code == RefusalCode.PEER_UNVERIFIED


def test_guard_bite_dropping_any_n3_coverage_category_fails(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    assert len(ALL_N3_COVERAGE_CATEGORIES) == 10

    for dropped_cat in ALL_N3_COVERAGE_CATEGORIES:
        collector, _ = _run_opt_in_worker_capture_flow(base, reviewed, ev)
        collector._coverage.discard(dropped_cat)
        env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
        assert isinstance(env_res, Refusal), f"Dropping {dropped_cat} must refuse"
        assert env_res.code in (
            RefusalCode.CLOSURE_INCOMPLETE,
            RefusalCode.OBSERVATION_GAP,
        )


def test_guard_bite_one_half_envelope_refused(tmp_path: Path, monkeypatch) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, _ = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
    assert isinstance(env_res, AcceptedData)
    worker_envelope = env_res.data
    # A one-half envelope must be refused before any comparison runs.
    compared = []
    landed_compare = worker_closure_capture.compare_loaded_source

    def recording_compare(*args, **kwargs):
        compared.append(args)
        return landed_compare(*args, **kwargs)

    monkeypatch.setattr(worker_closure_capture, "compare_loaded_source", recording_compare)

    # 1. Missing peer_envelope -> CLOSURE_INCOMPLETE
    comp_none = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=None,
        expectation=base.expected,
        verified_origins=base.verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_none, Refusal)
    assert comp_none.code == RefusalCode.CLOSURE_INCOMPLETE

    # 2. Peer envelope containing only container observations (no host half) -> CLOSURE_INCOMPLETE
    comp_same_half = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=worker_envelope,
        expectation=base.expected,
        verified_origins=base.verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_same_half, Refusal)
    assert comp_same_half.code == RefusalCode.CLOSURE_INCOMPLETE

    # 3. Distinct, valid peer envelope carrying no host observations: the merged
    #    envelope is container-only -> CLOSURE_INCOMPLETE from the dual-role check
    container_only_peer = validate_loaded_envelope(
        to_wire(
            replace(
                worker_envelope.envelope,
                envelope_id="envelope-host-1",
                process_observations=(),
            )
        )
    )
    comp_container_only = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=container_only_peer,
        expectation=base.expected,
        verified_origins=base.verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_container_only, Refusal)
    assert comp_container_only.code == RefusalCode.CLOSURE_INCOMPLETE
    assert compared == []


def test_guard_bite_unknown_disposition_never_maps_to_match(tmp_path: Path) -> None:
    repo_dir = _init_clean_tmp_git_repo(tmp_path)
    base, reviewed, _git_cap, ev = _build_reviewed_world_for_git_repo(repo_dir)
    collector, graph_ref = _run_opt_in_worker_capture_flow(base, reviewed, ev)
    env_res = collector.build_envelope(boundary="C_BEFORE_COUNT")
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
    host_expected = tuple(
        p for p in base.expected.processes if p.instance.location == "host"
    )
    expectation = replace(
        base.expected,
        binding=worker_envelope.envelope.binding,
        reviewed_graph=graph_ref,
        processes=(*host_expected, *collector.expected_processes()),
    )
    all_procs = (*host_procs, *worker_envelope.envelope.process_observations)
    # Strip the review origin fact -> compare_loaded_source returns disposition="UNKNOWN"
    facts_no_review = tuple(
        f for f in witnesses(reviewed.graph, all_procs) if f.purpose != "review"
    )
    verified = VerifiedClosureOrigins(
        reviewed_bytes=reviewed.content,
        observed_bytes=worker_envelope.content,
        expectation=claim_identity(expectation),
        validity_checkpoint=worker_envelope.envelope.boundary.validity_checkpoint,
        facts=facts_no_review,
    )
    comp_res = verify_and_compare_worker_closure(
        reviewed_graph=reviewed,
        worker_envelope=worker_envelope,
        peer_envelope=peer_envelope,
        expectation=expectation,
        verified_origins=verified,
        bookkeeper=CoverageBookkeeper(),
        load_stream_refs=(make_event_range(0, 8, 0),),
        boundary="C_BEFORE_COUNT",
        evidence=ev,
    )
    assert isinstance(comp_res, Refusal)
    assert comp_res.code == RefusalCode.CLOSURE_INCOMPLETE


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




