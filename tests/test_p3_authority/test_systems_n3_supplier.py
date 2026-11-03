"""Systems N3 supplier tests: generator + dual-role/10-category SharedN3 adapter proofs."""

from __future__ import annotations

import dataclasses
import inspect
import subprocess
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from p3_source_closure import (
    ALL_N3_COVERAGE_CATEGORIES,
    ArtifactProvenance,
    CachedProvenance,
    Checkpoint,
    ClosureBinding,
    ClosureBoundary,
    ClosureEnvelope,
    ContentIdentity,
    DeclaredNodeSpec,
    DynamicImportSpec,
    EntrypointSpec,
    EvidenceRef,
    ExpectedProcess,
    GeneratedProvenance,
    LoadedClosureEnvelope,
    LoadEvent,
    NativeClosureExpectation,
    ProcessFrontier,
    ProcessInstance,
    ProcessObservation,
    ProcessProfileSpec,
    ReviewedSourceGraph,
    SourceClosureComparison,
    SourceGraph,
    SourceNode,
    TargetRefused,
    VerifiedClosureOrigins,
    VerifiedOriginFact,
    build_reviewed_source_graph,
    compare_loaded_source,
    validate_loaded_envelope,
    validate_reviewed_graph,
)
from p3_source_closure import comparison as comparison_mod
from p3_source_closure.parsing import (
    byte_identity,
    canonical_bytes,
    claim_identity,
    to_wire,
)
from p3_source_closure.provenance import (
    checkpoint_claim,
    collector_claim,
    event_claim,
    process_claim,
)
from p3_source_closure.records import Purpose
from temper_ai.p3_authority._providers import SystemsSourceClosureComparator
from temper_ai.p3_authority.contract import (
    AcceptedData,
    Boundary,
    NativeSelection,
    Phase,
    Refusal,
    RefusalCode,
    Result,
)
from temper_ai.p3_authority.coverage_bookkeeping import (
    N3OriginResolverPort,
    SharedN3Adapter,
    make_refusal,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    default_effect_for_job,
)
from tests.test_p3_authority._composition_fixtures import (
    COMPAT_PROFILE_1,
    NATIVE_SELECTION_RUN,
    PROCESS_WORKER,
    REF_CLOSURE,
    REF_SOURCE,
    make_running_job,
)


def _git(repo_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    return proc.stdout.strip()


def _content(tag: str) -> ContentIdentity:
    return byte_identity(tag.encode("utf-8"))


def _ref(record_id: str, schema: str = "p3-evidence/1") -> EvidenceRef:
    return EvidenceRef(schema, _content("evidence-" + record_id), "independent-verifier", record_id)


@dataclasses.dataclass(frozen=True)
class SupplierTwinWorld:
    candidate_reviewed: ReviewedSourceGraph
    reviewed: ReviewedSourceGraph
    observed: LoadedClosureEnvelope
    expected: NativeClosureExpectation
    verified: VerifiedClosureOrigins
    dirty_main_bytes: bytes
    untracked_bytes: bytes


class _StaticOriginResolver(N3OriginResolverPort):
    def __init__(
        self,
        payload: Result[tuple[NativeClosureExpectation, VerifiedClosureOrigins]],
    ) -> None:
        self._payload = payload

    def resolve_closure_inputs(
        self,
        *,
        selection: NativeSelection,
        boundary: Boundary,
        reviewed: ReviewedSourceGraph,
        observed: LoadedClosureEnvelope,
    ) -> Result[tuple[NativeClosureExpectation, VerifiedClosureOrigins]]:
        return self._payload


def _witness_facts(
    graph: SourceGraph | ReviewedSourceGraph,
    processes: tuple[ProcessObservation, ...],
) -> tuple[VerifiedOriginFact, ...]:
    facts: dict[tuple[EvidenceRef, Purpose], VerifiedOriginFact] = {}

    def put(ref_obj: EvidenceRef | None, purpose: Purpose, claim_obj: object) -> None:
        if ref_obj is not None:
            facts[(ref_obj, purpose)] = VerifiedOriginFact(
                ref_obj,
                purpose,
                claim_identity(claim_obj),
            )

    rev_graph = graph.graph if isinstance(graph, ReviewedSourceGraph) else graph
    put(rev_graph.completeness_review_ref, "review", rev_graph)
    repos = {r.id: r for r in rev_graph.repositories}
    nodes = {n.id: n for n in rev_graph.nodes}
    for node in rev_graph.nodes:
        p = node.provenance
        if isinstance(p, ArtifactProvenance):
            put(
                p.provenance_ref,
                "artifact",
                (node, tuple(nodes[k] for k in (*p.sources, *p.dependencies, p.interpreter))),
            )
        elif isinstance(p, GeneratedProvenance):
            put(
                p.generation_ref,
                "generation",
                (node, tuple(nodes[k] for k in (*p.generators, *p.inputs, *p.toolchain))),
            )
        elif isinstance(p, CachedProvenance):
            put(
                p.provenance_ref,
                "cache",
                (node, tuple(nodes[k] for k in (*p.source_nodes, p.interpreter))),
            )
        else:
            put(p.membership_ref, "membership", (repos[p.repository], node))
    for edge in rev_graph.edges:
        put(edge.condition_ref, "condition", edge)
    for profile in rev_graph.process_profiles:
        put(profile.load_policy_ref, "policy", profile)
    for proc in processes:
        put(proc.process_ref, "process", process_claim(proc))
        put(proc.collector_ref, "collector", collector_claim(proc))
        put(
            proc.checkpoint.initial_state_ref,
            "collector",
            ("initial", collector_claim(proc)),
        )
        put(proc.checkpoint.checkpoint_ref, "checkpoint", checkpoint_claim(proc))
        for event in proc.events:
            put(event.origin_ref, "event", event_claim(proc, event))
    return tuple(facts.values())


def _rebuild_world(
    base: SupplierTwinWorld,
    *,
    reviewed: ReviewedSourceGraph | None = None,
    envelope: ClosureEnvelope | None = None,
    expected: NativeClosureExpectation | None = None,
    recompute_facts: bool = True,
    recompute_observed_bytes: bool = True,
    recompute_reviewed_bytes: bool = True,
    recompute_expectation_bytes: bool = True,
) -> SupplierTwinWorld:
    rev = reviewed if reviewed is not None else base.reviewed
    env_rec = envelope if envelope is not None else base.observed.envelope
    obs = LoadedClosureEnvelope(env_rec, claim_identity(env_rec))
    exp = expected if expected is not None else base.expected
    facts = _witness_facts(rev.graph, obs.envelope.process_observations) if recompute_facts else base.verified.facts
    ver = VerifiedClosureOrigins(
        reviewed_bytes=rev.content if recompute_reviewed_bytes else base.verified.reviewed_bytes,
        observed_bytes=obs.content if recompute_observed_bytes else base.verified.observed_bytes,
        expectation=claim_identity(exp) if recompute_expectation_bytes else base.verified.expectation,
        validity_checkpoint=exp.boundary.validity_checkpoint,
        facts=facts,
    )
    return replace(base, reviewed=rev, observed=obs, expected=exp, verified=ver)


@pytest.fixture(scope="module")
def clean_supplier_world(tmp_path_factory: pytest.TempPathFactory) -> SupplierTwinWorld:
    repo = tmp_path_factory.mktemp("n3_supplier_repo")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "systems@example.invalid")
    _git(repo, "config", "user.name", "Systems N3 Supplier")

    files = {
        "main.py": (
            b"import importlib\n"
            b"import json\n"
            b"import dep\n\n"
            b"def main(opt: bool = False) -> str:\n"
            b"    if opt:\n"
            b"        importlib.import_module('optional')\n"
            b"    return json.dumps({'dep': dep.tag()})\n"
        ),
        "dep.py": (
            b"import main\n\n"
            b"def tag() -> str:\n"
            b"    return 'clean'\n"
        ),
        "optional.py": b"FLAG = True\n",
    }
    for rel, raw in files.items():
        (repo / rel).write_bytes(raw)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "committed source closure")
    commit = _git(repo, "rev-parse", "HEAD")

    # Dirty working tree + untracked file after commit to prove Git-object-only build.
    dirty_main_bytes = b"raise SystemExit('dirty working tree bytes')\n"
    untracked_bytes = b"UNTRACKED_PAYLOAD = True\n"
    (repo / "main.py").write_bytes(dirty_main_bytes)
    (repo / "untracked.py").write_bytes(untracked_bytes)

    declared: list[SourceNode | DeclaredNodeSpec] = [
        SourceNode(
            "interpreter",
            "interpreter",
            _content("interpreter"),
            "interpreter",
            "0755",
            ArtifactProvenance(
                "artifact",
                _content("interpreter"),
                _content("build-runtime"),
                ("main",),
                (),
                "interpreter",
                "cpython-312-x86_64-linux-gnu",
                "bytes",
                _content("interpreter"),
                _ref("artifact-interpreter"),
            ),
        ),
        DeclaredNodeSpec(
            node=SourceNode(
                "stdlib",
                "stdlib",
                _content("stdlib"),
                "stdlib",
                "0644",
                ArtifactProvenance(
                    "artifact",
                    _content("stdlib"),
                    _content("build-runtime"),
                    ("main",),
                    ("interpreter",),
                    "interpreter",
                    "cpython-312-x86_64-linux-gnu",
                    "bytes",
                    _content("stdlib"),
                    _ref("artifact-stdlib"),
                ),
            ),
            module_names=("json", "importlib"),
        ),
        SourceNode(
            "native_binary",
            "native_binary",
            _content("native_binary"),
            "native_binary",
            "0755",
            ArtifactProvenance(
                "artifact",
                _content("native_binary"),
                _content("build-runtime"),
                ("main",),
                ("interpreter",),
                "interpreter",
                "cpython-312-x86_64-linux-gnu",
                "relocated",
                _content("relocated-native_binary"),
                _ref("artifact-native_binary"),
            ),
        ),
        SourceNode(
            "generated",
            "generated",
            _content("generated-source"),
            "gen/out.py",
            "0644",
            GeneratedProvenance(
                "generated",
                ("dep",),
                ("main",),
                ("interpreter",),
                _content("recipe"),
                _content("generated-source"),
                _content("generated-code"),
                _ref("generation"),
            ),
        ),
        SourceNode(
            "cache",
            "cached_code",
            _content("main-pyc"),
            "__pycache__/main.cpython-312.pyc",
            "0644",
            CachedProvenance(
                "cache",
                ("main", "generated"),
                "interpreter",
                "cpython-312-pyc",
                _content("main-pyc"),
                _ref("cache"),
            ),
        ),
    ]

    entrypoints = tuple(
        EntrypointSpec(
            id=f"{name}-entry",
            profile_id=name,
            target="main.py",
            symbol="main:main",
            bootstrap_chain=("dep.py",),
        )
        for name in ("creator", "host", "worker", "child")
    )
    profiles = (
        ProcessProfileSpec(
            id="creator",
            role="creator",
            entrypoint_ids=("creator-entry",),
            runtime_nodes=("interpreter", "stdlib"),
            extra_required_load_ids=("generated", "cache", "native_binary"),
            child_profiles=("host",),
            load_policy_ref=_ref("policy-creator"),
        ),
        ProcessProfileSpec(
            id="host",
            role="controller",
            entrypoint_ids=("host-entry",),
            runtime_nodes=("interpreter", "stdlib"),
            extra_required_load_ids=("generated", "cache", "native_binary"),
            child_profiles=("worker", "child"),
            load_policy_ref=_ref("policy-host"),
        ),
        ProcessProfileSpec(
            id="worker",
            role="worker",
            entrypoint_ids=("worker-entry",),
            runtime_nodes=("interpreter", "stdlib"),
            extra_required_load_ids=("generated", "cache", "native_binary"),
            child_profiles=("child",),
            load_policy_ref=_ref("policy-worker"),
        ),
        ProcessProfileSpec(
            id="child",
            role="child",
            entrypoint_ids=("child-entry",),
            runtime_nodes=("interpreter", "stdlib"),
            extra_required_load_ids=("generated", "cache", "native_binary"),
            child_profiles=(),
            load_policy_ref=_ref("policy-child"),
        ),
    )

    candidate_reviewed = build_reviewed_source_graph(
        repo_path=repo,
        commit=commit,
        entrypoints=entrypoints,
        process_profiles=profiles,
        declared_nodes=declared,
        dynamic_imports=(
            DynamicImportSpec(
                source="main.py",
                target="optional.py",
                condition_ref=_ref("condition"),
            ),
        ),
        graph_id="graph-supplier-1",
        repository_id="repo",
        repository_owner="temper",
    )
    assert candidate_reviewed.graph.completeness_review_ref is None

    review_ref = _ref("review")
    reviewed_graph = replace(candidate_reviewed.graph, completeness_review_ref=review_ref)
    reviewed = validate_reviewed_graph(canonical_bytes(reviewed_graph))
    nodes_by_id = {n.id: n for n in reviewed.graph.nodes}

    binding = ClosureBinding(
        "11111111-2222-4333-8444-555555555555",
        1,
        "nonce-1",
        "rev-1",
        "external-db-fresh",
        "sel-1",
        "subject-1",
        _content("build-1"),
        "parent-1",
        "window-1",
        "assoc-1",
    )
    boundary = ClosureBoundary(
        "C_BEFORE_COUNT",
        "count",
        "req-1",
        _content("receipt-1"),
        "barrier-1",
        "valid-1",
    )

    def make_process(
        instance_id: str,
        profile_id: str,
        location: Literal["host", "container"],
        parent_id: str | None,
        children: tuple[str, ...],
        state: Literal["running", "terminated"] = "running",
    ) -> tuple[ProcessObservation, ExpectedProcess]:
        instance = ProcessInstance(
            instance_id,
            "boot-1",
            100 if location == "host" else 200,
            f"start-{instance_id}",
            1,
            parent_id,
            f"launch-{instance_id}",
            f"pidns-{location}",
            f"mntns-{location}",
            f"userns-{location}",
            location,
            None if location == "host" else "ctr-1",
            f"principal-{location}",
            1000,
            1000,
            (1000,),
            "interpreter",
        )
        load_order = (
            "interpreter",
            "stdlib",
            "main",
            "dep",
            "generated",
            "cache",
            "native_binary",
        )
        events: list[LoadEvent] = [
            LoadEvent(0, f"{instance_id}-0", "start", None, None, "kernel", "bytes", None, _ref(f"{instance_id}-event-0"))
        ]
        for idx, nid in enumerate(load_order, start=1):
            node = nodes_by_id[nid]
            prov = node.provenance
            rep: Literal["bytes", "relocated"] = (
                "relocated" if nid.startswith("native_binary") else "bytes"
            )
            if isinstance(prov, GeneratedProvenance):
                loaded = prov.execution_object
            elif isinstance(prov, ArtifactProvenance):
                loaded = prov.loaded_representation
            else:
                loaded = node.content
            kind: Literal["compile", "cache", "load"] = (
                "compile"
                if nid == "generated"
                else "cache"
                if nid == "cache"
                else "load"
            )
            events.append(
                LoadEvent(
                    idx,
                    f"{instance_id}-{idx}",
                    kind,
                    nid,
                    loaded,
                    "loader-v1",
                    rep,
                    None,
                    _ref(f"{instance_id}-event-{idx}"),
                )
            )
        for child_id in children:
            seq = len(events)
            events.append(
                LoadEvent(
                    seq,
                    f"{instance_id}-{seq}",
                    "child",
                    None,
                    None,
                    "trusted-launch",
                    "bytes",
                    child_id,
                    _ref(f"{instance_id}-event-{seq}"),
                )
            )
        if state == "terminated":
            seq = len(events)
            events.append(
                LoadEvent(
                    seq,
                    f"{instance_id}-{seq}",
                    "end",
                    None,
                    None,
                    "kernel",
                    "bytes",
                    None,
                    _ref(f"{instance_id}-event-{seq}"),
                )
            )
        cp_ref = _ref(f"checkpoint-{instance_id}")
        cp = Checkpoint(
            f"epoch-{instance_id}",
            0,
            events[-1].sequence,
            events[-1].event_id,
            children,
            ALL_N3_COVERAGE_CATEGORIES,
            (),
            0,
            True,
            _ref(f"initial-{instance_id}"),
            cp_ref,
            boundary,
        )
        obs_proc = ProcessObservation(
            profile_id,
            instance,
            binding,
            reviewed.graph.graph_id,
            (f"{profile_id}-entry",),
            ("interpreter", "stdlib"),
            f"collector-{location}",
            "1.0",
            "ebpf-lsm",
            _ref(f"process-{instance_id}"),
            _ref(f"collector-{instance_id}"),
            tuple(events),
            cp,
            state,
        )
        frontier = ProcessFrontier(
            instance_id,
            cp.epoch,
            cp.last_sequence,
            cp.last_event_id,
            children,
            cp_ref,
        )
        return obs_proc, ExpectedProcess(profile_id, instance, frontier, ALL_N3_COVERAGE_CATEGORIES)

    pairs = (
        make_process("creator", "creator", "host", None, ("host",)),
        make_process("host", "host", "host", "creator", ("worker",)),
        make_process("worker", "worker", "container", "host", ("child",)),
        make_process("child", "child", "container", "worker", (), state="terminated"),
    )
    processes = tuple(p for p, _ in pairs)
    expected_procs = tuple(e for _, e in pairs)
    graph_ref = EvidenceRef("p3-reviewed-source-graph/1", reviewed.content, "independent-verifier", "graph-ref-1")
    envelope_rec = ClosureEnvelope(
        "p3-reviewed-loaded-closure/1",
        "env-supplier-1",
        graph_ref,
        (),
        binding,
        boundary,
        processes,
        (_ref("prov-1"),),
    )
    observed = validate_loaded_envelope(canonical_bytes(envelope_rec))
    expected = NativeClosureExpectation(
        binding,
        boundary,
        graph_ref,
        review_ref,
        expected_procs,
        (),
    )
    verified = VerifiedClosureOrigins(
        reviewed.content,
        observed.content,
        claim_identity(expected),
        boundary.validity_checkpoint,
        _witness_facts(reviewed.graph, processes),
    )
    return SupplierTwinWorld(
        candidate_reviewed=candidate_reviewed,
        reviewed=reviewed,
        observed=observed,
        expected=expected,
        verified=verified,
        dirty_main_bytes=dirty_main_bytes,
        untracked_bytes=untracked_bytes,
    )


def _make_decision_evidence(
    boundary: Boundary = "C_BEFORE_COUNT",
) -> DecisionEvidenceRecord:
    selected_job = make_running_job()
    return DecisionEvidenceRecord(
        selected_job=selected_job,
        authority_revisions=selected_job.authority_refs,
        window=None,
        processes=(PROCESS_WORKER,),
        effect=default_effect_for_job(selected_job, boundary),
        phase=Phase.C,
        boundary=boundary,
        source=REF_SOURCE,
        closure=REF_CLOSURE,
        compatibility=COMPAT_PROFILE_1,
    )


def _run_shared_n3_adapter(
    world: SupplierTwinWorld,
    *,
    boundary: Boundary = "C_BEFORE_COUNT",
    require_match: bool = True,
) -> Result[SourceClosureComparison]:
    resolved: Result[tuple[NativeClosureExpectation, VerifiedClosureOrigins]] = (
        AcceptedData(
            data=(world.expected, world.verified),
            evidence=_make_decision_evidence(boundary),
        )
    )
    adapter = SharedN3Adapter(
        origin_resolver=_StaticOriginResolver(resolved),
        require_match=require_match,
    )
    return adapter.compare(
        world.reviewed,
        world.observed,
        selection=NATIVE_SELECTION_RUN,
        boundary=boundary,
    )


def _run_systems_comparator(
    world: SupplierTwinWorld,
    *,
    boundary: Boundary = "C_BEFORE_COUNT",
) -> Result[SourceClosureComparison]:
    selected_job = make_running_job()
    comparator = SystemsSourceClosureComparator(
        job_lookup=lambda _rev: selected_job,
        peer_lookup=lambda _rev: PROCESS_WORKER,
        expectation_lookup=lambda _rev, _b: (world.expected, world.verified),
    )
    return comparator.compare(
        world.reviewed,
        world.observed,
        selection=NATIVE_SELECTION_RUN,
        boundary=boundary,
    )


def install_mutation(monkeypatch: pytest.MonkeyPatch, owner: object, function: str, before: str, after: str) -> None:
    import sys

    import p3_source_closure as pkg_mod
    import temper_ai.p3_authority._providers as providers_mod
    import temper_ai.p3_authority.coverage_bookkeeping as cb_mod

    original = getattr(owner, function)
    source = textwrap.dedent(inspect.getsource(original))
    assert source.count(before) == 1
    namespace = dict(original.__globals__)
    exec(compile(source.replace(before, after), "<supplier-guard-mutation>", "exec"), namespace)
    mutated = namespace[function]
    monkeypatch.setattr(owner, function, mutated)
    if owner is comparison_mod and function == "compare_loaded_source":
        monkeypatch.setattr(pkg_mod, function, mutated)
        monkeypatch.setattr(providers_mod, function, mutated)
        monkeypatch.setattr(cb_mod, function, mutated)
        monkeypatch.setattr(sys.modules[__name__], function, mutated)


def test_combined_worker_and_host_happy_path_matches_across_all_categories(
    clean_supplier_world: SupplierTwinWorld,
) -> None:
    assert len(ALL_N3_COVERAGE_CATEGORIES) == 10
    direct = compare_loaded_source(
        clean_supplier_world.reviewed,
        clean_supplier_world.observed,
        expected=clean_supplier_world.expected,
        verified=clean_supplier_world.verified,
    )
    assert direct.disposition == "MATCH"
    assert direct.reasons == ()
    assert len(direct.frontiers) == 4

    shared_out = _run_shared_n3_adapter(clean_supplier_world)
    assert isinstance(shared_out, AcceptedData)
    assert shared_out.data.disposition == "MATCH"

    sys_out = _run_systems_comparator(clean_supplier_world)
    assert isinstance(sys_out, AcceptedData)
    assert sys_out.data.disposition == "MATCH"


@pytest.mark.parametrize(
    "missing_mode,expected_disposition,expected_shared_code,expected_systems_code",
    [
        ("observed_host_only", "UNKNOWN", RefusalCode.CLOSURE_INCOMPLETE, RefusalCode.CLOSURE_INCOMPLETE),
        ("observed_worker_only", "UNKNOWN", RefusalCode.CLOSURE_INCOMPLETE, RefusalCode.CLOSURE_INCOMPLETE),
        ("both_host_only", "UNKNOWN", RefusalCode.CLOSURE_INCOMPLETE, RefusalCode.CLOSURE_INCOMPLETE),
        ("both_worker_only", "UNKNOWN", RefusalCode.CLOSURE_INCOMPLETE, RefusalCode.CLOSURE_INCOMPLETE),
        ("container_child_only_no_worker_role", "UNKNOWN", RefusalCode.CLOSURE_INCOMPLETE, RefusalCode.CLOSURE_INCOMPLETE),
        ("worker_role_collapsed_to_host_location", "REFUSED", RefusalCode.RUNTIME_CHANGED, RefusalCode.CLOSURE_MISMATCH),
    ],
)
def test_dual_role_completeness_and_single_half_refusal_twins(
    clean_supplier_world: SupplierTwinWorld,
    missing_mode: str,
    expected_disposition: str,
    expected_shared_code: RefusalCode,
    expected_systems_code: RefusalCode,
) -> None:
    env = clean_supplier_world.observed.envelope
    exp = clean_supplier_world.expected

    if missing_mode == "observed_host_only":
        new_obs = tuple(p for p in env.process_observations if p.instance.location == "host")
        twin = _rebuild_world(clean_supplier_world, envelope=replace(env, process_observations=new_obs))
    elif missing_mode == "observed_worker_only":
        new_obs = tuple(p for p in env.process_observations if p.instance.location == "container")
        twin = _rebuild_world(clean_supplier_world, envelope=replace(env, process_observations=new_obs))
    elif missing_mode == "both_host_only":
        host_obs_list: list[ProcessObservation] = []
        for p in env.process_observations:
            if p.instance.location != "host":
                continue
            if p.instance.instance_id == "host":
                evs = tuple(e for e in p.events if e.child_instance != "worker")
                cp = replace(
                    p.checkpoint,
                    last_sequence=evs[-1].sequence,
                    last_event_id=evs[-1].event_id,
                    child_frontier=(),
                )
                host_obs_list.append(replace(p, events=evs, checkpoint=cp))
            else:
                host_obs_list.append(p)
        new_obs = tuple(host_obs_list)
        new_exp = tuple(
            replace(
                p,
                frontier=replace(
                    p.frontier,
                    last_sequence=new_obs[1].checkpoint.last_sequence,
                    last_event_id=new_obs[1].checkpoint.last_event_id,
                    child_frontier=(),
                ),
            )
            if p.instance.instance_id == "host"
            else p
            for p in exp.processes
            if p.instance.location == "host"
        )
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=new_obs),
            expected=replace(exp, processes=new_exp),
        )
    elif missing_mode == "both_worker_only":
        new_obs = tuple(
            replace(p, instance=replace(p.instance, parent_instance=None))
            if p.instance.instance_id == "worker"
            else p
            for p in env.process_observations
            if p.instance.location == "container"
        )
        new_exp = tuple(
            replace(p, instance=replace(p.instance, parent_instance=None))
            if p.instance.instance_id == "worker"
            else p
            for p in exp.processes
            if p.instance.location == "container"
        )
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=new_obs),
            expected=replace(exp, processes=new_exp),
        )
    elif missing_mode == "container_child_only_no_worker_role":
        # Host spawns child directly in container, omitting the worker-role process.
        obs_list: list[ProcessObservation] = []
        for p in env.process_observations:
            if p.instance.instance_id == "worker":
                continue
            if p.instance.instance_id == "host":
                evs = tuple(replace(e, child_instance="child") if e.child_instance == "worker" else e for e in p.events)
                cp = replace(p.checkpoint, child_frontier=("child",))
                obs_list.append(replace(p, events=evs, checkpoint=cp))
            elif p.instance.instance_id == "child":
                obs_list.append(replace(p, instance=replace(p.instance, parent_instance="host")))
            else:
                obs_list.append(p)
        exp_list: list[ExpectedProcess] = []
        for ep in exp.processes:
            if ep.instance.instance_id == "worker":
                continue
            if ep.instance.instance_id == "host":
                exp_list.append(replace(ep, frontier=replace(ep.frontier, child_frontier=("child",))))
            elif ep.instance.instance_id == "child":
                exp_list.append(replace(ep, instance=replace(ep.instance, parent_instance="host")))
            else:
                exp_list.append(ep)
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(obs_list)),
            expected=replace(exp, processes=tuple(exp_list)),
        )
    else:
        # Collapse worker role onto location="host" while keeping child at location="container".
        new_obs = tuple(
            replace(p, instance=replace(p.instance, location="host", container_identity=None))
            if p.instance.instance_id == "worker"
            else p
            for p in env.process_observations
        )
        new_exp = tuple(
            replace(p, instance=replace(p.instance, location="host", container_identity=None))
            if p.instance.instance_id == "worker"
            else p
            for p in exp.processes
        )
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=new_obs),
            expected=replace(exp, processes=new_exp),
        )

    direct = compare_loaded_source(
        twin.reviewed,
        twin.observed,
        expected=twin.expected,
        verified=twin.verified,
    )
    assert direct.disposition == expected_disposition
    assert direct.disposition != "MATCH"

    shared_out = _run_shared_n3_adapter(twin)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == expected_shared_code

    sys_out = _run_systems_comparator(twin)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == expected_systems_code


@pytest.mark.parametrize("dropped_category", ALL_N3_COVERAGE_CATEGORIES)
@pytest.mark.parametrize("drop_from_expected_too", [False, True])
def test_dropping_each_n3_coverage_category_refuses_closure_incomplete(
    clean_supplier_world: SupplierTwinWorld,
    dropped_category: str,
    drop_from_expected_too: bool,
) -> None:
    reduced = tuple(c for c in ALL_N3_COVERAGE_CATEGORIES if c != dropped_category)
    env = clean_supplier_world.observed.envelope
    exp = clean_supplier_world.expected

    obs_procs = list(env.process_observations)
    target_proc = obs_procs[2]  # worker process
    obs_procs[2] = replace(target_proc, checkpoint=replace(target_proc.checkpoint, coverage=reduced))

    exp_procs = list(exp.processes)
    if drop_from_expected_too:
        exp_procs[2] = replace(exp_procs[2], coverage=reduced)

    twin = _rebuild_world(
        clean_supplier_world,
        envelope=replace(env, process_observations=tuple(obs_procs)),
        expected=replace(exp, processes=tuple(exp_procs)),
    )

    direct = compare_loaded_source(
        twin.reviewed,
        twin.observed,
        expected=twin.expected,
        verified=twin.verified,
    )
    assert direct.disposition == "UNKNOWN"
    assert "COVERAGE_GAP" in direct.reasons

    shared_out = _run_shared_n3_adapter(twin)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == RefusalCode.CLOSURE_INCOMPLETE

    sys_out = _run_systems_comparator(twin)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_INCOMPLETE


@pytest.mark.parametrize("gap_kind", ["late_attach", "sequence_gap", "stale_frontier", "missing_collector_origin"])
def test_observation_gap_refusal_twins(
    clean_supplier_world: SupplierTwinWorld,
    gap_kind: str,
) -> None:
    env = clean_supplier_world.observed.envelope
    exp = clean_supplier_world.expected
    obs_procs = list(env.process_observations)
    worker = obs_procs[2]

    if gap_kind == "late_attach":
        # Late attach: missing start event at sequence 0 (first_sequence=1).
        trimmed = worker.events[1:]
        cp = replace(worker.checkpoint, first_sequence=1)
        obs_procs[2] = replace(worker, events=trimmed, checkpoint=cp)
        twin = _rebuild_world(clean_supplier_world, envelope=replace(env, process_observations=tuple(obs_procs)))
    elif gap_kind == "sequence_gap":
        # Dropped mid-stream event leaving a sequence gap.
        gapped = worker.events[:2] + worker.events[3:]
        obs_procs[2] = replace(worker, events=gapped)
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(obs_procs)),
            recompute_facts=False,
        )
    elif gap_kind == "stale_frontier":
        exp_procs = list(exp.processes)
        exp_procs[2] = replace(
            exp_procs[2],
            frontier=replace(exp_procs[2].frontier, last_sequence=99, last_event_id="worker-99"),
        )
        twin = _rebuild_world(clean_supplier_world, expected=replace(exp, processes=tuple(exp_procs)))
    else:
        filtered_facts = tuple(
            f for f in clean_supplier_world.verified.facts if f.ref != worker.collector_ref
        )
        twin = replace(
            clean_supplier_world,
            verified=replace(clean_supplier_world.verified, facts=filtered_facts),
        )

    direct = compare_loaded_source(
        twin.reviewed,
        twin.observed,
        expected=twin.expected,
        verified=twin.verified,
    )
    assert direct.disposition == "UNKNOWN"
    assert bool({"SEQUENCE_GAP", "STALE_FRONTIER", "OBSERVER_ORIGIN"} & set(direct.reasons))

    shared_out = _run_shared_n3_adapter(twin)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == RefusalCode.OBSERVATION_GAP

    sys_out = _run_systems_comparator(twin)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_INCOMPLETE


@pytest.mark.parametrize("target", ["graph", "envelope"])
def test_closure_version_mismatch_refusal_twins(
    clean_supplier_world: SupplierTwinWorld,
    target: str,
) -> None:
    if target == "graph":
        wire_graph = to_wire(clean_supplier_world.reviewed.graph)
        assert isinstance(wire_graph, dict)
        raw_graph = dict(wire_graph)
        raw_graph["schema"] = "p3-reviewed-source-graph/999"
        with pytest.raises(TargetRefused) as caught:
            validate_reviewed_graph(raw_graph)
        assert caught.value.code == "TARGET_SCHEMA_MISMATCH"

        bad_graph = object.__new__(type(clean_supplier_world.reviewed.graph))
        for f in dataclasses.fields(clean_supplier_world.reviewed.graph):
            object.__setattr__(
                bad_graph,
                f.name,
                "p3-reviewed-source-graph/999" if f.name == "schema" else getattr(clean_supplier_world.reviewed.graph, f.name),
            )
        bad_reviewed = object.__new__(ReviewedSourceGraph)
        object.__setattr__(bad_reviewed, "graph", bad_graph)
        object.__setattr__(bad_reviewed, "content", clean_supplier_world.reviewed.content)
        twin = replace(clean_supplier_world, reviewed=bad_reviewed)
    else:
        wire_env = to_wire(clean_supplier_world.observed.envelope)
        assert isinstance(wire_env, dict)
        raw_env = dict(wire_env)
        raw_env["schema"] = "p3-reviewed-loaded-closure/999"
        with pytest.raises(TargetRefused) as caught:
            validate_loaded_envelope(raw_env)
        assert caught.value.code == "TARGET_SCHEMA_MISMATCH"

        bad_env = object.__new__(type(clean_supplier_world.observed.envelope))
        for f in dataclasses.fields(clean_supplier_world.observed.envelope):
            object.__setattr__(
                bad_env,
                f.name,
                "p3-reviewed-loaded-closure/999" if f.name == "schema" else getattr(clean_supplier_world.observed.envelope, f.name),
            )
        bad_observed = object.__new__(LoadedClosureEnvelope)
        object.__setattr__(bad_observed, "envelope", bad_env)
        object.__setattr__(bad_observed, "content", clean_supplier_world.observed.content)
        twin = replace(clean_supplier_world, observed=bad_observed)

    sys_out = _run_systems_comparator(twin)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_VERSION

    shared_version_refusal = SharedN3Adapter(
        origin_resolver=_StaticOriginResolver(
            make_refusal(
                RefusalCode.CLOSURE_VERSION,
                "C_BEFORE_COUNT",
            )
        ),
        require_match=True,
    ).compare(
        twin.reviewed,
        twin.observed,
        selection=NATIVE_SELECTION_RUN,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(shared_version_refusal, Refusal)
    assert shared_version_refusal.code == RefusalCode.CLOSURE_VERSION


@pytest.mark.parametrize(
    "fault_mode,expected_reason",
    [
        ("unreviewed_load", "UNREVIEWED_LOAD"),
        ("dirty_git_source_digest_mismatch", "BYTE_SUBSTITUTION"),
        ("non_member_untracked_git_source", "UNREVIEWED_LOAD"),
        ("git_membership_witness_mismatch", "GIT_MEMBERSHIP"),
    ],
)
def test_closure_mismatch_and_dirty_git_source_refusal_twins(
    clean_supplier_world: SupplierTwinWorld,
    fault_mode: str,
    expected_reason: str,
) -> None:
    env = clean_supplier_world.observed.envelope
    exp = clean_supplier_world.expected
    obs_procs = list(env.process_observations)
    worker = obs_procs[2]
    events = list(worker.events)

    if fault_mode in ("unreviewed_load", "non_member_untracked_git_source"):
        node_name = "untracked" if fault_mode == "non_member_untracked_git_source" else "rogue_mod"
        payload = clean_supplier_world.untracked_bytes if fault_mode == "non_member_untracked_git_source" else b"rogue"
        seq = len(events)
        events.append(
            LoadEvent(
                seq,
                f"worker-{seq}",
                "load",
                node_name,
                byte_identity(payload),
                "loader-v1",
                "bytes",
                None,
                _ref(f"worker-event-{seq}"),
            )
        )
        cp = replace(worker.checkpoint, last_sequence=seq, last_event_id=f"worker-{seq}")
        obs_procs[2] = replace(worker, events=tuple(events), checkpoint=cp)
        exp_procs = list(exp.processes)
        exp_procs[2] = replace(
            exp_procs[2],
            frontier=replace(exp_procs[2].frontier, last_sequence=seq, last_event_id=f"worker-{seq}"),
        )
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(obs_procs)),
            expected=replace(exp, processes=tuple(exp_procs)),
        )
    elif fault_mode == "dirty_git_source_digest_mismatch":
        # Worker loads dirty working-tree main.py bytes while ReviewedSourceGraph holds committed Git blob.
        main_idx = next(i for i, e in enumerate(events) if e.node_id == "main")
        events[main_idx] = replace(
            events[main_idx],
            loaded=byte_identity(clean_supplier_world.dirty_main_bytes),
        )
        obs_procs[2] = replace(worker, events=tuple(events))
        twin = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(obs_procs)),
        )
    else:
        facts = list(clean_supplier_world.verified.facts)
        mem_idx = next(i for i, f in enumerate(facts) if f.purpose == "membership")
        facts[mem_idx] = replace(facts[mem_idx], claim=_content("wrong-git-tree-or-blob-witness"))
        twin = replace(
            clean_supplier_world,
            verified=replace(clean_supplier_world.verified, facts=tuple(facts)),
        )

    direct = compare_loaded_source(
        twin.reviewed,
        twin.observed,
        expected=twin.expected,
        verified=twin.verified,
    )
    assert direct.disposition == "REFUSED"
    assert expected_reason in direct.reasons

    shared_out = _run_shared_n3_adapter(twin)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == RefusalCode.CLOSURE_MISMATCH

    sys_out = _run_systems_comparator(twin)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_MISMATCH


def test_generator_output_without_independent_completeness_review_ref_never_matches(
    clean_supplier_world: SupplierTwinWorld,
) -> None:
    candidate = clean_supplier_world.candidate_reviewed
    assert candidate.graph.completeness_review_ref is None

    graph_ref = replace(clean_supplier_world.expected.reviewed_graph, content=candidate.content)
    env = replace(clean_supplier_world.observed.envelope, reviewed_graph=graph_ref)
    exp = replace(clean_supplier_world.expected, reviewed_graph=graph_ref)
    unreviewed_world = _rebuild_world(
        clean_supplier_world,
        reviewed=candidate,
        envelope=env,
        expected=exp,
    )

    direct = compare_loaded_source(
        unreviewed_world.reviewed,
        unreviewed_world.observed,
        expected=unreviewed_world.expected,
        verified=unreviewed_world.verified,
    )
    assert direct.disposition == "UNKNOWN"
    assert direct.disposition != "MATCH"
    assert "COVERAGE_GAP" in direct.reasons
    assert "REVIEW_ORIGIN" in direct.reasons

    shared_out = _run_shared_n3_adapter(unreviewed_world)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == RefusalCode.CLOSURE_INCOMPLETE

    sys_out = _run_systems_comparator(unreviewed_world)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_INCOMPLETE


@pytest.mark.parametrize(
    "guard_id,function,before,after",
    [
        (
            "FP-01-all-categories",
            "_check_process",
            "if (not set(t.ALL_N3_COVERAGE_CATEGORIES) <= set(cp.coverage) or\n            not set(t.ALL_N3_COVERAGE_CATEGORIES) <= set(required.coverage)):",
            "if False:",
        ),
        (
            "FP-02-host-half",
            "compare_loaded_source",
            "or not has_host_half",
            "or False",
        ),
        (
            "FP-03-worker-half",
            "compare_loaded_source",
            "or not has_worker_half",
            "or False",
        ),
        (
            "FP-04-role-location",
            "_check_process",
            "if ((profile.role in t.HOST_PROCESS_ROLES and process.instance.location != \"host\") or\n                (profile.role in t.WORKER_PROCESS_ROLES and process.instance.location != \"container\")):",
            "if False:",
        ),
        (
            "FP-05-unreviewed-candidate",
            "compare_loaded_source",
            "if graph.completeness_review_ref is None:\n        findings.unknown(\"COVERAGE_GAP\")",
            "if False:\n        findings.unknown(\"COVERAGE_GAP\")",
        ),
        (
            "FP-06-unknown-never-match",
            "compare_loaded_source",
            '"UNKNOWN" if findings.gaps else "MATCH"',
            '"MATCH"',
        ),
    ],
)
def test_guard_fault_proofs_fail_on_deliberately_broken_copy(
    clean_supplier_world: SupplierTwinWorld,
    monkeypatch: pytest.MonkeyPatch,
    guard_id: str,
    function: str,
    before: str,
    after: str,
) -> None:
    env = clean_supplier_world.observed.envelope
    exp = clean_supplier_world.expected

    if guard_id == "FP-01-all-categories":
        reduced = tuple(c for c in ALL_N3_COVERAGE_CATEGORIES if c != "python")
        obs_procs = list(env.process_observations)
        obs_procs[2] = replace(obs_procs[2], checkpoint=replace(obs_procs[2].checkpoint, coverage=reduced))
        exp_procs = list(exp.processes)
        exp_procs[2] = replace(exp_procs[2], coverage=reduced)
        fault_world = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(obs_procs)),
            expected=replace(exp, processes=tuple(exp_procs)),
        )

        def run_guard() -> None:
            res = _run_shared_n3_adapter(fault_world)
            assert isinstance(res, Refusal) and res.code == RefusalCode.CLOSURE_INCOMPLETE

    elif guard_id == "FP-02-host-half":
        # Replace host processes with child role so location=="host" has no host-role half.
        mut_profiles = tuple(
            replace(p, role="child") if p.id in ("creator", "host") else p
            for p in clean_supplier_world.reviewed.graph.process_profiles
        )
        mut_graph = replace(clean_supplier_world.reviewed.graph, process_profiles=mut_profiles)
        mut_reviewed = validate_reviewed_graph(canonical_bytes(mut_graph))
        g_ref = replace(exp.reviewed_graph, content=mut_reviewed.content)
        fault_world = _rebuild_world(
            clean_supplier_world,
            reviewed=mut_reviewed,
            envelope=replace(env, reviewed_graph=g_ref),
            expected=replace(exp, reviewed_graph=g_ref),
        )

        def run_guard() -> None:
            res = _run_shared_n3_adapter(fault_world)
            assert isinstance(res, Refusal) and res.code == RefusalCode.CLOSURE_INCOMPLETE

    elif guard_id == "FP-03-worker-half":
        # Container has only child-role process; worker-role process is omitted.
        fp_obs: list[ProcessObservation] = []
        for p in env.process_observations:
            if p.instance.instance_id == "worker":
                continue
            if p.instance.instance_id == "host":
                evs = tuple(replace(e, child_instance="child") if e.child_instance == "worker" else e for e in p.events)
                cp = replace(p.checkpoint, child_frontier=("child",))
                fp_obs.append(replace(p, events=evs, checkpoint=cp))
            elif p.instance.instance_id == "child":
                fp_obs.append(replace(p, instance=replace(p.instance, parent_instance="host")))
            else:
                fp_obs.append(p)
        fp_exp: list[ExpectedProcess] = []
        for ep in exp.processes:
            if ep.instance.instance_id == "worker":
                continue
            if ep.instance.instance_id == "host":
                fp_exp.append(replace(ep, frontier=replace(ep.frontier, child_frontier=("child",))))
            elif ep.instance.instance_id == "child":
                fp_exp.append(replace(ep, instance=replace(ep.instance, parent_instance="host")))
            else:
                fp_exp.append(ep)
        fault_world = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=tuple(fp_obs)),
            expected=replace(exp, processes=tuple(fp_exp)),
        )

        def run_guard() -> None:
            res = _run_shared_n3_adapter(fault_world)
            assert isinstance(res, Refusal) and res.code == RefusalCode.CLOSURE_INCOMPLETE

    elif guard_id == "FP-04-role-location":
        loc_obs = tuple(
            replace(p, instance=replace(p.instance, location="host", container_identity=None))
            if p.instance.instance_id == "worker"
            else p
            for p in env.process_observations
        )
        loc_exp = tuple(
            replace(ep, instance=replace(ep.instance, location="host", container_identity=None))
            if ep.instance.instance_id == "worker"
            else ep
            for ep in exp.processes
        )
        fault_world = _rebuild_world(
            clean_supplier_world,
            envelope=replace(env, process_observations=loc_obs),
            expected=replace(exp, processes=loc_exp),
        )

        def run_guard() -> None:
            res = _run_shared_n3_adapter(fault_world)
            assert isinstance(res, Refusal) and res.code == RefusalCode.RUNTIME_CHANGED

    elif guard_id == "FP-05-unreviewed-candidate":
        candidate = clean_supplier_world.candidate_reviewed
        g_ref = replace(exp.reviewed_graph, content=candidate.content)
        fault_world = _rebuild_world(
            clean_supplier_world,
            reviewed=candidate,
            envelope=replace(env, reviewed_graph=g_ref),
            expected=replace(exp, reviewed_graph=g_ref),
        )

        def run_guard() -> None:
            res = compare_loaded_source(
                fault_world.reviewed,
                fault_world.observed,
                expected=fault_world.expected,
                verified=fault_world.verified,
            )
            assert "COVERAGE_GAP" in res.reasons

    else:
        unavailable = VerifiedClosureOrigins(None, None, None, None, ())
        fault_world = replace(clean_supplier_world, verified=unavailable)

        def run_guard() -> None:
            res = _run_shared_n3_adapter(fault_world)
            assert isinstance(res, Refusal)

    # Guard passes on intact code.
    run_guard()
    # Guard fails against deliberately broken copy.
    install_mutation(monkeypatch, comparison_mod, function, before, after)
    with pytest.raises(AssertionError):
        run_guard()


# H-N3-CANONICAL-CONTENT-1 (Systems #91): a record's content field is a claim, not
# its identity. Origin checks bind only the content recomputed from the record.
ContentTarget = Literal["graph", "envelope"]
ContentKind = Literal["stale", "forged", "raw"]
VerifiedKind = Literal["same", "unavailable", "canonical"]


def _content_field_world(
    base: SupplierTwinWorld,
    target: ContentTarget,
    content_kind: ContentKind,
    verified_kind: VerifiedKind,
) -> SupplierTwinWorld:
    """Fixed world whose graph or envelope record carries a content field other than its bytes.

    stale: the identity of an earlier version of the record; forged: a fixed label;
    raw: valid non-canonical bytes (trailing newline) parsed by the real validator.
    same: the verified identity (and for the graph, both graph references) agree
    with the field; unavailable: the provider has no byte identity; canonical:
    everything else stays bound to the record's canonical identity.
    """
    if target == "graph":
        graph = base.reviewed.graph
        if content_kind == "raw":
            reviewed = validate_reviewed_graph(canonical_bytes(graph) + b"\n")
            assert reviewed.graph == graph
        else:
            label = base.candidate_reviewed.content if content_kind == "stale" else _content("forged-reviewed-graph")
            reviewed = ReviewedSourceGraph(graph, label)
        assert reviewed.content != claim_identity(graph)
        if verified_kind == "canonical":
            return _rebuild_world(base, reviewed=reviewed, recompute_reviewed_bytes=False)
        g_ref = replace(base.expected.reviewed_graph, content=reviewed.content)
        world = _rebuild_world(
            base,
            reviewed=reviewed,
            envelope=replace(base.observed.envelope, reviewed_graph=g_ref),
            expected=replace(base.expected, reviewed_graph=g_ref),
        )
        if verified_kind == "unavailable":
            world = replace(world, verified=replace(world.verified, reviewed_bytes=None))
        return world
    envelope = base.observed.envelope
    if content_kind == "raw":
        observed = validate_loaded_envelope(canonical_bytes(envelope) + b"\n")
        assert observed.envelope == envelope
    elif content_kind == "stale":
        observed = LoadedClosureEnvelope(replace(envelope, envelope_id="env-supplier-2"), base.observed.content)
    else:
        observed = LoadedClosureEnvelope(envelope, _content("forged-loaded-envelope"))
    assert observed.content != claim_identity(observed.envelope)
    world = _rebuild_world(base, envelope=observed.envelope)
    observed_bytes = {"same": observed.content, "unavailable": None, "canonical": world.observed.content}[verified_kind]
    return replace(world, observed=observed, verified=replace(world.verified, observed_bytes=observed_bytes))


def _assert_content_field_refused(
    world: SupplierTwinWorld,
    reason: Literal["REVIEW_ORIGIN", "OBSERVER_ORIGIN"],
) -> None:
    direct = compare_loaded_source(
        world.reviewed,
        world.observed,
        expected=world.expected,
        verified=world.verified,
    )
    assert direct.disposition == "REFUSED"
    assert direct.reasons == (reason,)
    assert direct.frontiers == ()
    assert direct.reviewed_graph == world.expected.reviewed_graph

    shared_out = _run_shared_n3_adapter(world)
    assert isinstance(shared_out, Refusal)
    assert shared_out.code == RefusalCode.CLOSURE_MISMATCH

    sys_out = _run_systems_comparator(world)
    assert isinstance(sys_out, Refusal)
    assert sys_out.code == RefusalCode.CLOSURE_MISMATCH


@pytest.mark.parametrize(
    "case_id,target,content_kind,verified_kind",
    [
        ("CC-G1", "graph", "stale", "same"),
        ("CC-G2", "graph", "forged", "same"),
        ("CC-G3", "graph", "forged", "unavailable"),
        ("CC-G4", "graph", "raw", "same"),
        ("CC-E1", "envelope", "stale", "same"),
        ("CC-E2", "envelope", "forged", "same"),
        ("CC-E3", "envelope", "forged", "unavailable"),
        ("CC-E4", "envelope", "raw", "same"),
    ],
)
def test_content_field_other_than_its_bytes_never_satisfies_origin_checks(
    clean_supplier_world: SupplierTwinWorld,
    case_id: str,
    target: ContentTarget,
    content_kind: ContentKind,
    verified_kind: VerifiedKind,
) -> None:
    clean = compare_loaded_source(
        clean_supplier_world.reviewed,
        clean_supplier_world.observed,
        expected=clean_supplier_world.expected,
        verified=clean_supplier_world.verified,
    )
    assert clean.disposition == "MATCH"

    fault_world = _content_field_world(clean_supplier_world, target, content_kind, verified_kind)
    _assert_content_field_refused(fault_world, "REVIEW_ORIGIN" if target == "graph" else "OBSERVER_ORIGIN")


@pytest.mark.parametrize(
    "case_id,target,reason,before",
    [
        ("FP-G", "graph", "REVIEW_ORIGIN", "if reviewed.content != canonical_reviewed.content:"),
        ("FP-E", "envelope", "OBSERVER_ORIGIN", "if observed.content != canonical_observed.content:"),
    ],
)
def test_content_field_guard_mutant_is_killed(
    clean_supplier_world: SupplierTwinWorld,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    target: ContentTarget,
    reason: Literal["REVIEW_ORIGIN", "OBSERVER_ORIGIN"],
    before: str,
) -> None:
    # Bindings to recomputed content alone would MATCH a forged field that every
    # other input contradicts; only the field check refuses it.
    fault_world = _content_field_world(clean_supplier_world, target, "forged", "canonical")
    _assert_content_field_refused(fault_world, reason)
    install_mutation(monkeypatch, comparison_mod, "compare_loaded_source", before, "if False:")
    with pytest.raises(AssertionError):
        _assert_content_field_refused(fault_world, reason)
