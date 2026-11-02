"""Fixed positive, refusal, seam-placement, canary, and mutation-bite tests for P3 T4 worker observation."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from p3_source_closure import (
    Checkpoint,
    LoadEvent,
    N3ObservationEpoch,
)
from temper_ai.cli.main import take_box_delivery_first
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    BothRootObservations,
    EffectState,
    Phase,
    Refusal,
    RefusalCode,
    RootScope,
    SequenceUse,
    compare_loaded_source,
)
from temper_ai.p3_authority.coverage_bookkeeping import (
    ALL_N3_COVERAGE_CATEGORIES,
    CoverageBookkeeper,
)
from temper_ai.p3_authority.launch_adapters import (
    DockerLaunchObservationAdapter,
    EarlyBootstrapObservationHook,
    P3ObservationRefusedError,
    RunnerBootstrapObservationHook,
)
from temper_ai.p3_authority.worker_observation import (
    EXISTING_TEMPER_SEAM_GUARANTEES,
    WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    RootOwnerVsActorAssertion,
    WorkerObservationAdapter,
    build_worker_observation_compat_cases,
    refuse_existing_seam_as_complete_coverage,
    validate_compatibility_profile,
)
from temper_ai.runner.bootstrap import bootstrap_runner_context_from_env
from temper_ai.spawner.docker_spawner import DockerSpawner
from tests.test_architecture.ops_host_n3_cases import bad_twin, clean_world
from tests.test_p3_authority.test_child_registration import (
    CANARY_ARGV,
    CANARY_STDERR,
    CANARY_STDOUT,
    SyntheticWorkerProviderDouble,
    _ExistingScope,
    _ProcessRef,
    make_both_roots,
    make_child_pair,
    make_event_range,
    make_evidence,
    make_grant,
    make_host_and_worker_processes,
    make_root_obj,
    make_selected_job,
    make_selected_op,
    make_supplied_worker_frame,
)


def test_combined_worker_observation_happy_path_across_launch_bootstrap_roots_and_comparator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined source-only happy path (bp-be8d76b9): parent binding -> launch/bootstrap hooks -> separate roots/runtime -> complete synthetic stream -> Systems comparator MATCH."""
    job = make_selected_job()
    grant = make_grant(job)
    frame = make_supplied_worker_frame()
    provider = SyntheticWorkerProviderDouble(frame=frame)
    observer = WorkerObservationAdapter(provider=provider)

    # 1. DockerLaunchObservationAdapter pre-create and post-start binding
    grant_a = make_grant(job, boundary="A_PRE_CREATE")
    launch_hook = DockerLaunchObservationAdapter(
        worker_observer=observer,
        grant=grant_a,
        selected_job=job,
        boundary="A_PRE_CREATE",
    )
    pre_create = launch_hook.before_container_create(
        execution_id="00000000-0000-4000-8000-000000000263"
    )
    assert isinstance(pre_create, AcceptedData)
    post_start = launch_hook.after_container_start(
        execution_id="00000000-0000-4000-8000-000000000263",
        container_id="container-1",
    )
    assert isinstance(post_start, AcceptedData)
    assert len(launch_hook.records) == 1

    # 2. Early CLI take_box_delivery_first opt-in hook
    grant_b = make_grant(job, boundary="B_PRE_REQUEST")
    monkeypatch.delenv("TEMPER_BOX_PROFILE", raising=False)
    early_hook = EarlyBootstrapObservationHook(
        worker_observer=observer,
        grant=grant_b,
        selected_job=job,
        boundary="B_PRE_REQUEST",
    )
    take_box_delivery_first(bootstrap_observer=early_hook)
    assert len(early_hook.records) == 1
    assert early_hook.records[0].stage == "cli_no_box_profile"

    # 3. RunnerBootstrapObservationHook
    runner_hook = RunnerBootstrapObservationHook(
        worker_observer=observer,
        grant=grant_b,
        selected_job=job,
        boundary="B_PRE_REQUEST",
    )
    runner_res = runner_hook.on_runner_context_bootstrapped(
        execution_id="00000000-0000-4000-8000-000000000263"
    )
    assert isinstance(runner_res, AcceptedData)

    # 4. WorkerRootObservationAdapter direct RootObserver port check
    actor = _ProcessRef("worker")
    pub_obj = make_root_obj("pub-root-obj")
    pub_scope = RootScope(
        role="publication",
        actor=_ExistingScope(identity=pub_obj),
        selected_locator="synthetic:pub",
        expected_existing_object=pub_obj,
        new_leaf=None,
        required_rights=frozenset({"observe", "read"}),
    )
    root_res = observer.root_observer.observe(
        grant_b,
        actor,
        pub_scope,
        job.authorized_operations,
        "B_PRE_REQUEST",
    )
    assert isinstance(root_res, AcceptedData)
    assert root_res.data.binding.role == "publication"

    # 5. Phase C observation + pure Systems comparator remains the sole comparison implementation -> MATCH
    obs_c = observer.observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_c, AcceptedData)
    world = clean_world("N3-08")
    comp = compare_loaded_source(
        world.reviewed,
        obs_c.data.runtime_facts,
        expected=world.expected,
        verified=world.verified,
    )
    assert comp.disposition == "MATCH"
    assert comp.reasons == ()


def test_default_unconfigured_provider_refuses_all_observation_and_launch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default provider=None refuses with AUTHORITY_UNAVAILABLE and never synthesizes success."""
    job = make_selected_job()
    grant = make_grant(job)
    observer = WorkerObservationAdapter()
    assert observer.is_configured is False

    res = observer.observe(grant, job, "B_PRE_REQUEST")
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.AUTHORITY_UNAVAILABLE
    assert res.phase == Phase.B
    assert res.admission_state == AdmissionState.NOT_ADMITTED
    assert res.effect_state == EffectState.NONE
    assert res.sequence_use == SequenceUse.UNUSED

    # RootObserver default-off refusal
    actor = _ProcessRef("worker")
    pub_obj = make_root_obj("pub-root-obj")
    root_scope = RootScope(
        role="publication",
        actor=_ExistingScope(identity=pub_obj),
        selected_locator="synthetic:pub",
        expected_existing_object=None,
        new_leaf=None,
        required_rights=frozenset({"observe"}),
    )
    root_res = observer.root_observer.observe(
        grant,
        actor,
        root_scope,
        job.authorized_operations,
        "B_PRE_REQUEST",
    )
    assert isinstance(root_res, Refusal)
    assert root_res.code == RefusalCode.AUTHORITY_UNAVAILABLE

    # DockerSpawner protected_launch=True without configured provider refuses before docker run
    run_mock = MagicMock()
    spawner = DockerSpawner(
        workspace_lookup=lambda _: "/tmp/ws",
        run=run_mock,
    )
    with pytest.raises(P3ObservationRefusedError) as exc_info:
        spawner.spawn(
            "00000000-0000-4000-8000-000000000263",
            protected_launch=True,
        )
    assert exc_info.value.refusal.code == RefusalCode.AUTHORITY_UNAVAILABLE
    run_mock.assert_not_called()

    # take_box_delivery_first protected_bootstrap=True without hook refuses
    monkeypatch.delenv("TEMPER_BOX_PROFILE", raising=False)
    with pytest.raises(P3ObservationRefusedError) as cli_exc:
        take_box_delivery_first(protected_bootstrap=True)
    assert cli_exc.value.refusal.code == RefusalCode.AUTHORITY_UNAVAILABLE


def test_permission_checked_before_collection_and_unpermitted_read_poisons_job() -> None:
    """Observation permission is checked before reading frame; unpermitted attempt poisons the job."""
    job = make_selected_job()
    unpermitted_grant = make_grant(job, observation_permission=False)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)

    res = observer.observe(unpermitted_grant, job, "B_PRE_REQUEST")
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.OBSERVATION_NOT_AUTHORIZED
    assert provider.collect_frame_calls == 0

    # Subsequent call even with a valid grant on the same poisoned selection_revision is refused
    valid_grant = make_grant(job, observation_permission=True)
    res_after = observer.observe(valid_grant, job, "B_PRE_REQUEST")
    assert isinstance(res_after, Refusal)
    assert res_after.code == RefusalCode.OBSERVATION_NOT_AUTHORIZED
    assert provider.collect_frame_calls == 0


def test_future_subject_at_phase_bc_and_collapsed_host_worker_runtime_refused() -> None:
    """Planned FutureSubject at Phase B/C -> SUBJECT_MISMATCH; collapsed host/worker runtime -> RUNTIME_CHANGED."""
    job = make_selected_job()
    future_grant = make_grant(job, use_future_subject=True)
    provider = SyntheticWorkerProviderDouble()
    observer = WorkerObservationAdapter(provider=provider)

    # FutureSubject is refused at B_PRE_REQUEST
    future_res = observer.observe(future_grant, job, "B_PRE_REQUEST")
    assert isinstance(future_res, Refusal)
    assert future_res.code == RefusalCode.SUBJECT_MISMATCH
    assert provider.collect_frame_calls == 0

    # Collapsing worker_instance onto host_instance is refused with RUNTIME_CHANGED
    valid_grant = make_grant(job)
    host_proc, _, _, worker_closure = make_host_and_worker_processes()
    collapsed_frame = replace(
        make_supplied_worker_frame(),
        worker_instance=host_proc,
        worker_closure_instance=replace(worker_closure, location="host"),
    )
    observer_collapsed = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=collapsed_frame)
    )
    collapsed_res = observer_collapsed.observe(
        valid_grant, job, "B_PRE_REQUEST"
    )
    assert isinstance(collapsed_res, Refusal)
    assert collapsed_res.code == RefusalCode.RUNTIME_CHANGED


def test_late_attach_and_incomplete_bootstrap_capture_refused_with_observation_gap() -> None:
    """Late attach or incomplete bootstrap capture from process start -> OBSERVATION_GAP."""
    job = make_selected_job()
    grant = make_grant(job)
    world = clean_world("N3-08")
    procs = list(world.observed.envelope.process_observations)
    # Remove start event at sequence 0 -> late attach
    procs[2] = replace(procs[2], events=procs[2].events[1:])
    late_env = replace(
        world.observed,
        envelope=replace(
            world.observed.envelope,
            process_observations=tuple(procs),
        ),
    )
    late_frame = make_supplied_worker_frame(observed_override=late_env)
    observer = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=late_frame)
    )
    res = observer.observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.OBSERVATION_GAP


@pytest.mark.parametrize(
    ("missing_category", "expected_code"),
    [
        ("bootstrap", RefusalCode.CLOSURE_INCOMPLETE),
        ("python", RefusalCode.CLOSURE_INCOMPLETE),
        ("generated", RefusalCode.CLOSURE_INCOMPLETE),
        ("cache", RefusalCode.CLOSURE_INCOMPLETE),
        ("native", RefusalCode.CLOSURE_INCOMPLETE),
        ("dynamic", RefusalCode.CLOSURE_INCOMPLETE),
        ("children", RefusalCode.CLOSURE_INCOMPLETE),
        ("effect_fence", RefusalCode.OBSERVATION_GAP),
    ],
)
def test_missing_generated_cache_native_lazy_and_runtime_coverage_categories_refused(
    missing_category: str,
    expected_code: RefusalCode,
) -> None:
    """Missing, unimplemented, or incomplete coverage for any required N3 category refuses (CLOSURE_INCOMPLETE; effect_fence -> OBSERVATION_GAP)."""
    job = make_selected_job()
    grant = make_grant(job)
    world = clean_world("N3-08")
    procs = list(world.observed.envelope.process_observations)
    cp: Checkpoint = procs[2].checkpoint
    filtered_cov = tuple(c for c in cp.coverage if c != missing_category)
    procs[2] = replace(procs[2], checkpoint=replace(cp, coverage=filtered_cov))
    incomplete_env = replace(
        world.observed,
        envelope=replace(
            world.observed.envelope,
            process_observations=tuple(procs),
        ),
    )
    frame = make_supplied_worker_frame(observed_override=incomplete_env)
    observer = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=frame)
    )
    res = observer.observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(res, Refusal)
    assert res.code == expected_code


def test_unknown_and_refused_dispositions_remain_distinct_in_comparator_and_adapter() -> None:
    """UNKNOWN (coverage gap / unverified origin) and REFUSED (undeclared load / byte substitution) remain distinct."""
    clean = clean_world("N3-08")
    twin_unknown = bad_twin("N3-08", clean)
    twin_refused = bad_twin("N3-02", clean)

    comp_unknown = compare_loaded_source(
        twin_unknown.reviewed,
        twin_unknown.observed,
        expected=twin_unknown.expected,
        verified=twin_unknown.verified,
    )
    comp_refused = compare_loaded_source(
        twin_refused.reviewed,
        twin_refused.observed,
        expected=twin_refused.expected,
        verified=twin_refused.verified,
    )
    assert comp_unknown.disposition == "UNKNOWN"
    assert comp_refused.disposition == "REFUSED"
    assert comp_unknown.disposition != comp_refused.disposition


def test_stream_gap_reorder_dropped_events_and_contradictory_duplicate_refused() -> None:
    """Stream sequence gap, reorder, dropped events, or contradictory duplicate load -> OBSERVATION_GAP."""
    job = make_selected_job()
    grant = make_grant(job)
    world = clean_world("N3-08")

    # 1. Sequence gap in process events (bad_twin N3-08)
    gap_world = bad_twin("N3-08", world)
    gap_frame = make_supplied_worker_frame(observed_override=gap_world.observed)
    obs_gap = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=gap_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_gap, Refusal)
    assert obs_gap.code == RefusalCode.OBSERVATION_GAP

    # 2. Dropped collector events (loss_count > 0)
    procs = list(world.observed.envelope.process_observations)
    procs[2] = replace(
        procs[2],
        checkpoint=replace(procs[2].checkpoint, loss_count=3),
    )
    dropped_env = replace(
        world.observed,
        envelope=replace(
            world.observed.envelope,
            process_observations=tuple(procs),
        ),
    )
    dropped_frame = make_supplied_worker_frame(observed_override=dropped_env)
    obs_dropped = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=dropped_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_dropped, Refusal)
    assert obs_dropped.code == RefusalCode.OBSERVATION_GAP

    # 3. Contradictory duplicate LoadEvent (same sequence, different event_id)
    procs_dup = list(world.observed.envelope.process_observations)
    first_ev: LoadEvent = procs_dup[2].events[1]
    contradictory_ev = replace(first_ev, event_id="contradictory-event-id")
    procs_dup[2] = replace(
        procs_dup[2],
        events=(*procs_dup[2].events, contradictory_ev),
    )
    dup_env = replace(
        world.observed,
        envelope=replace(
            world.observed.envelope,
            process_observations=tuple(procs_dup),
        ),
    )
    dup_frame = make_supplied_worker_frame(observed_override=dup_env)
    obs_dup = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=dup_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_dup, Refusal)
    assert obs_dup.code == RefusalCode.OBSERVATION_GAP


def test_host_only_half_root_and_actor_mismatch_refused() -> None:
    """Host-only half root or collapsed publication/host_evidence root -> ROOT_MISMATCH; actor mismatch -> SUBJECT_MISMATCH."""
    job = make_selected_job()
    grant = make_grant(job)
    both = make_both_roots()

    # 1. Missing BothRootObservations -> ROOT_MISMATCH
    no_roots_frame = make_supplied_worker_frame(Provide_roots=False)
    obs_none = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=no_roots_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_none, Refusal)
    assert obs_none.code == RefusalCode.ROOT_MISMATCH

    # 2. Collapsed single object_identity for both publication and host_evidence -> ROOT_MISMATCH
    collapsed_ev_binding = replace(
        both.host_evidence.binding,
        object_identity=both.publication.binding.object_identity,
    )
    collapsed_ev = replace(
        both.host_evidence,
        binding=collapsed_ev_binding,
        traversal_chain=both.publication.traversal_chain,
    )
    collapsed_roots = replace(
        both,
        host_evidence=collapsed_ev,
    )
    collapsed_frame = make_supplied_worker_frame(both_roots=collapsed_roots)
    obs_collapsed = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=collapsed_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_collapsed, Refusal)
    assert obs_collapsed.code == RefusalCode.ROOT_MISMATCH

    # 3. Root owner assertion with wrong actor_process_ref (substituting file owner for actor) -> SUBJECT_MISMATCH
    bad_actor_frame = replace(
        make_supplied_worker_frame(),
        root_owner_assertions=(
            RootOwnerVsActorAssertion(
                root_kind="publication",
                actor_process_ref="wrong-owner-as-actor",
                actor_principal="host-builder",
                actor_uid=1000,
                file_owner_principal="host-builder",
                file_owner_uid=1000,
            ),
        ),
    )
    obs_bad_actor = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=bad_actor_frame)
    ).observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(obs_bad_actor, Refusal)
    assert obs_bad_actor.code == RefusalCode.SUBJECT_MISMATCH


def test_stale_frontier_after_wait_and_effect_fence_unavailable_refused() -> None:
    """Stale causal frontier after wait or unavailable effect fence -> OBSERVATION_GAP."""
    job = make_selected_job()
    grant = make_grant(job)
    frame = make_supplied_worker_frame()
    observer = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=frame)
    )

    # 1. Stale frontier: since_cursor last_sequence is ahead of observed checkpoint
    world = clean_world("N3-08")
    worker_obs = world.observed.envelope.process_observations[2]
    worker_frontier = world.expected.processes[2].frontier
    ahead_cursor = N3ObservationEpoch(
        instance=worker_obs.instance,
        collector_ref=worker_obs.collector_ref,
        frontier=replace(worker_frontier, last_sequence=999),
    )
    stale_res = observer.observe(
        grant,
        job,
        "C_BEFORE_COUNT",
        since_cursor=ahead_cursor,
    )
    assert isinstance(stale_res, Refusal)
    assert stale_res.code == RefusalCode.OBSERVATION_GAP

    # 2. Effect fence unavailable -> OBSERVATION_GAP
    no_fence_frame = make_supplied_worker_frame(effect_fence_verified=False)
    no_fence_observer = WorkerObservationAdapter(
        provider=SyntheticWorkerProviderDouble(frame=no_fence_frame)
    )
    fence_res = no_fence_observer.observe(grant, job, "C_BEFORE_COUNT")
    assert isinstance(fence_res, Refusal)
    assert fence_res.code == RefusalCode.OBSERVATION_GAP


@pytest.mark.parametrize("seam_name", sorted(EXISTING_TEMPER_SEAM_GUARANTEES))
def test_existing_temper_seams_never_claim_complete_coverage_or_authentic_origin(
    seam_name: str,
) -> None:
    """box_profile.closure, tree_digest, box_view, box_guard, and box_bootstrap never establish complete loaded bytes."""
    guarantee = EXISTING_TEMPER_SEAM_GUARANTEES[seam_name]
    assert guarantee.establishes_complete_loaded_bytes is False
    assert guarantee.establishes_authentic_process_origin is False
    refusal = refuse_existing_seam_as_complete_coverage(
        seam_name,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(refusal, Refusal)
    assert refusal.code == RefusalCode.CLOSURE_INCOMPLETE


def test_docker_spawner_post_start_mismatch_kills_container_and_runs_cleanup() -> None:
    """When container_id after docker run mismatches observed container, DockerLaunchObservationAdapter returns PARTIAL refusal."""
    job = make_selected_job()
    grant = make_grant(job, boundary="A_PRE_CREATE")
    frame = make_supplied_worker_frame()
    provider = SyntheticWorkerProviderDouble(frame=frame)
    observer = WorkerObservationAdapter(provider=provider)
    launch_hook = DockerLaunchObservationAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        boundary="A_PRE_CREATE",
    )

    assert isinstance(
        launch_hook.before_container_create(
            execution_id="00000000-0000-4000-8000-000000000263"
        ),
        AcceptedData,
    )
    bad_post = launch_hook.after_container_start(
        execution_id="00000000-0000-4000-8000-000000000263",
        container_id="wrong_container_id_999",
    )
    assert isinstance(bad_post, Refusal)
    assert bad_post.code == RefusalCode.RUNTIME_CHANGED
    assert bad_post.effect_state == EffectState.PARTIAL


def test_fresh_process_import_has_zero_io_contact_and_preserves_cli_bootstrap_order() -> None:
    """Importing worker_observation, child_registration, coverage_bookkeeping, and launch_adapters makes zero DB/HTTP/Docker calls."""
    code = """
import sys
import httpx
import sqlalchemy
import sqlmodel

def refuse(*args, **kwargs):
    raise RuntimeError("unexpected_operational_contact")

httpx.Client.__init__ = refuse
httpx.AsyncClient.__init__ = refuse
sqlalchemy.create_engine = refuse
sqlmodel.create_engine = refuse

from temper_ai.p3_authority import (
    child_registration,
    coverage_bookkeeping,
    launch_adapters,
    worker_observation,
)

for forbidden in ("temper_ai.p3_authority.service", "temper_ai.p3_authority.registry"):
    if forbidden in sys.modules:
        raise RuntimeError(f"forbidden_sibling_imported:{forbidden}")

adapter = worker_observation.WorkerObservationAdapter()
assert adapter.is_configured is False
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    code_rc = proc.returncode
    assert code_rc == 0


def test_vv_and_junit_xml_never_leak_child_canaries_on_refusal(
    tmp_path: Path,
) -> None:
    """Run pytest -vv with --junitxml in a child process and verify child canaries never appear in stdout, stderr, or junit XML."""
    junit_path = tmp_path / "junit-canary.xml"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-vv",
            "-o",
            "junit_family=xunit2",
            f"--junitxml={junit_path}",
            "tests/test_p3_authority/test_child_registration.py",
            "-k",
            "test_post_popen_registration_refusal_kills_and_reaps_child_without_leaking_canaries",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    code_rc = proc.returncode
    assert code_rc == 0
    junit_text = junit_path.read_text(encoding="utf-8")
    for canary in (CANARY_STDOUT, CANARY_STDERR, CANARY_ARGV):
        assert canary not in junit_text


def test_worker_observation_compat_cases_and_guard_mutation_bites() -> None:
    """Verify ops-host-compat-corpus/1 worker case table and mutation bites on version/coverage guards."""
    cases = build_worker_observation_compat_cases()
    assert len(cases) == 12
    assert all(c.corpus == WORKER_OBSERVATION_COMPAT_CORPUS_ID for c in cases)
    case_ids = [c.case_id for c in cases]
    assert len(case_ids) == len(set(case_ids))

    # Bite 1: CompatibilityProfile version widening is refused
    job_bad_corpus = make_selected_job(corpus="ops-host-compat-corpus/999")
    err_corpus = validate_compatibility_profile(
        job_bad_corpus.compatibility_profile,
        "B_PRE_REQUEST",
    )
    assert isinstance(err_corpus, Refusal)
    assert err_corpus.code == RefusalCode.COMPATIBILITY_UNQUALIFIED

    # Bite 2: CoverageBookkeeper refuses unobserved registered child
    bookkeeper = CoverageBookkeeper(required_categories=ALL_N3_COVERAGE_CATEGORIES)
    world = clean_world("N3-08")
    ev = make_evidence("C_BEFORE_COUNT")
    stream_ref = make_event_range(0, 8, 0)
    res_unregistered_child = bookkeeper.verify_envelope(
        world.observed,
        boundary="C_BEFORE_COUNT",
        load_stream_refs=(stream_ref,),
        reviewed_graph=world.reviewed,
        registered_child_ids=frozenset({"proc:child:unobserved:999"}),
        evidence=ev,
    )
    assert isinstance(res_unregistered_child, Refusal)
    assert res_unregistered_child.code == RefusalCode.CLOSURE_INCOMPLETE

    # Bite 3: bootstrap_runner_context_from_env with protected_bootstrap=True refuses before DB/LLM init
    with pytest.raises(P3ObservationRefusedError) as boot_exc:
        bootstrap_runner_context_from_env(protected_bootstrap=True)
    assert boot_exc.value.refusal.code == RefusalCode.AUTHORITY_UNAVAILABLE
    assert make_child_pair is not None
    assert make_selected_op() is not None
    assert BothRootObservations is not None
