"""Tests for temper_ai.p3_authority.service (P3NativeBoundary, NativeHostJoin, and compose_p3_authority)."""

from __future__ import annotations

from dataclasses import replace

from temper_ai.api.caller import Caller
from temper_ai.p3_authority.boundary_types import (
    ActualCreation,
    ActualRequestAndReceipt,
    AdmissionDecision,
    AdmittedRequestBinding,
    BothRootObservations,
    CheckerDecision,
    CountDecision,
    CreateArmDecision,
    ExecutionDecision,
    ImmutableRequestBinding,
    RequestDecision,
    VerifiedReceiptBinding,
    WindowBinding,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    EffectState,
    Phase,
    Refusal,
    RefusalCode,
    SequenceUse,
)
from temper_ai.p3_authority.registry import (
    PriorRequestHistory,
    SelectionSnapshot,
    default_effect_for_job,
)
from temper_ai.p3_authority.service import NativeHostJoinAdapter, compose_p3_authority
from temper_ai.runner.admission import DbAdmissionTransport
from tests.test_p3_authority._composition_fixtures import (
    COMPAT_PROFILE_1,
    DISPATCH_1,
    PROCESS_QA,
    PROCESS_WORKER,
    REF_COMPAT,
    REF_QA,
    TRUSTED_NOW,
    WITNESS_1,
    WITNESS_2,
    FakeDisarmRelation,
    FakeNativeRootObject,
    FakeP5Assessment,
    FakeQAReceiving,
    FakeSession,
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
    publish_and_link_counted_receipt,
)


def _setup_ready_service_rig(*, writes_enabled: bool = False):
    rig = make_populated_test_rig(writes_enabled=writes_enabled)
    obs = populate_boundary_happy_path_observations(rig)

    # Exercise real candidate bindings authority_for_submit + transport + authority_for_run
    caller = Caller(name="p3-authorized-caller")
    assert rig.composition.candidate_bindings.designated("designated_v1") is True
    submit_auth = rig.composition.candidate_bindings.authority_for_submit(
        caller,
        "designated_v1",
    )
    assert (
        submit_auth.expected_descriptor_sha256
        == rig.v1_harness.expected_descriptor_sha256
    )
    transport = rig.composition.candidate_bindings.transport(submit_auth)
    assert isinstance(transport, DbAdmissionTransport)

    rig.composition.candidate_bindings.register_run_dispatch(
        DISPATCH_1.execution_uuid,
        DISPATCH_1,
    )
    run_auth = rig.composition.candidate_bindings.authority_for_run(
        DISPATCH_1.execution_uuid,
    )
    assert run_auth.expected_source_sha256 == rig.v1_harness.expected_source_sha256

    return rig, obs, submit_auth, run_auth


def test_combined_happy_path_p3_native_boundary_and_host_join() -> None:
    """First combined fixed source happy path:
    authenticated test providers -> real candidate capture/transport/snapshot ->
    synthetic A/B/C -> actual test occurrence D-1 -> D-5 linkage -> separate count decision.
    All N checks remain unresolved, rows UNQUALIFIED, P5 UNTRUSTED, writes false.
    """
    rig, obs, _, _ = _setup_ready_service_rig(writes_enabled=False)
    svc = rig.composition.service
    join = rig.composition.host_join

    assert isinstance(join, NativeHostJoinAdapter)
    assert join.service is svc
    assert svc.writes_enabled is False

    # 1. before_create (Phase A / A_PRE_CREATE)
    res_create = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        obs["creator_obs"],
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_create, AcceptedData)
    assert isinstance(res_create.data, CreateArmDecision)
    assert res_create.evidence.phase is Phase.A
    assert res_create.evidence.boundary == "A_PRE_CREATE"
    assert res_create.evidence.receiving == ()

    # 2. before_checker (Phase A / A_PRE_ARM)
    cur_run = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run, AcceptedData)
    win_binding = WindowBinding(
        current=cur_run.data,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=res_create.data.creator,
            birth=WITNESS_1,
        ),
    )
    res_checker = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_checker, AcceptedData)
    assert isinstance(res_checker.data, CheckerDecision)
    checker_binding = res_checker.data.binding

    # 3. before_request (Phase B / B_PRE_REQUEST)
    res_req = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(res_req, AcceptedData)
    assert isinstance(res_req.data, RequestDecision)
    imm_req_binding = res_req.data.binding

    # 4. before_admit + record_admitted_occurrence (Phase B / C_PRE_REQUEST -> D-1 occurrence)
    res_admit = svc.before_admit(
        rig.peer_run,
        imm_req_binding,
        obs["cursors"],
    )
    assert isinstance(res_admit, AcceptedData)
    assert isinstance(res_admit.data, AdmissionDecision)

    res_rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req_binding,
        current_binding=res_admit.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(res_rec_occ, AcceptedData)
    assert isinstance(res_rec_occ.data, AdmittedRequestBinding)
    admitted_binding = res_rec_occ.data

    # 5. before_execute (Phase B / C_PRE_EXECUTION)
    res_exec = svc.before_execute(
        rig.peer_run,
        admitted_binding,
        obs["op_leg"],
        obs["cursors"],
    )
    assert isinstance(res_exec, AcceptedData)
    assert isinstance(res_exec.data, ExecutionDecision)

    # 6. NativeHostJoin D-1 -> D-5 linkage (lookup_occurrence -> verify_publication -> receive)
    publish_and_link_counted_receipt(rig, obs)

    occ_lookup = join.lookup_occurrence(rig.session_host, obs["req_id"])
    assert isinstance(occ_lookup, AcceptedData)
    assert occ_lookup.data.witness_registration == WITNESS_1.witness_registration

    pub_ver = join.verify_publication(
        rig.session_host,
        obs["req_id"],
        obs["raw_pub"],
        occ_lookup.data,
    )
    assert isinstance(pub_ver, AcceptedData)
    assert pub_ver.data == obs["prov"]

    host_eff_exec = replace(
        rig.examples["HostEffect"],
        selection=obs["sel_run"],
        boundary="C_PRE_EXECUTION",
        operation="launch",
    )
    recv_res = join.receive(
        rig.session_host,
        obs["req_id"],
        pub_ver.data,
        host_eff_exec,
    )
    assert isinstance(recv_res, AcceptedData)
    assert isinstance(recv_res.data, VerifiedReceiptBinding)
    # Occurrence/publication/receive remains distinct from before_count:
    assert recv_res.evidence.receiving == ()

    # 7. Separate before_count decision (Phase C / C_BEFORE_COUNT)
    actual_req_and_rcpt = ActualRequestAndReceipt(
        request=imm_req_binding,
        publication=obs["raw_pub"],
    )
    res_count = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        pub_ver.data,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_count, AcceptedData)
    assert isinstance(res_count.data, CountDecision)
    assert res_count.data.verdict == "PASS"
    assert res_count.evidence.phase is Phase.C
    assert res_count.evidence.boundary == "C_BEFORE_COUNT"
    assert len(res_count.evidence.receiving) == 2


def test_native_host_join_nine_methods_happy_path_and_refusal_twins() -> None:
    """Exercise all 9 NativeHostJoin methods on the same service and their refusal twins."""
    rig, obs, _, _ = _setup_ready_service_rig()
    join = rig.composition.host_join
    ex = rig.examples

    # Multi-job snapshot refuses select_host_job with SELECTION_AMBIGUOUS
    ambig_sel = join.select_host_job(rig.session_host)
    assert isinstance(ambig_sel, Refusal)
    assert ambig_sel.code is RefusalCode.SELECTION_AMBIGUOUS

    # Publish single-job snapshot for select_host_job
    rig.publisher.publish_snapshot(
        SelectionSnapshot(
            snapshot_revision="snap-single-1",
            jobs=(rig.running_job,),
            verified_at=TRUSTED_NOW,
        )
    )
    sel_host = join.select_host_job(rig.session_host)
    assert isinstance(sel_host, AcceptedData)
    assert (
        sel_host.data.selection.selection_revision == rig.running_job.selection_revision
    )

    # Unknown session refuses OBSERVATION_NOT_AUTHORIZED
    unknown_session = FakeSession("session:unknown-999", rig.peer_host)
    bad_sel = join.select_host_job(unknown_session)
    assert isinstance(bad_sel, Refusal)
    assert bad_sel.code is RefusalCode.OBSERVATION_NOT_AUTHORIZED

    # 2. permit_observation
    eff_arm = replace(
        ex["HostEffect"],
        selection=obs["sel_run"],
        boundary="A_PRE_ARM",
        operation="launch",
    )
    scope = replace(
        ex["ObservationScope"],
        selection=obs["sel_run"],
        protected_effects=(eff_arm,),
    )
    perm_res = join.permit_observation(rig.session_host, scope)
    assert isinstance(perm_res, AcceptedData)
    perm_handle = perm_res.data

    # Foreign effect selection in scope refuses SELECTION_FOREIGN
    foreign_eff = replace(eff_arm, selection=obs["sel_pre"])
    foreign_scope = replace(scope, protected_effects=(foreign_eff,))
    bad_perm = join.permit_observation(rig.session_host, foreign_scope)
    assert isinstance(bad_perm, Refusal)
    assert bad_perm.code is RefusalCode.SELECTION_FOREIGN

    # 3. open_observation
    open_res = join.open_observation(perm_handle, scope)
    assert isinstance(open_res, AcceptedData)
    obs_session = open_res.data

    # Mismatched scope on open_observation refuses SCOPE_MISMATCH
    other_eff = replace(eff_arm, operation="other_op")
    other_scope = replace(scope, protected_effects=(other_eff,))
    bad_open = join.open_observation(perm_handle, other_scope)
    assert isinstance(bad_open, Refusal)
    assert bad_open.code is RefusalCode.SCOPE_MISMATCH

    # 4. observe
    # Before registering observation -> OBSERVATION_GAP
    rig.host_observer._observations.pop(
        (rig.running_job.selection_revision, "A_PRE_ARM"),
        None,
    )
    gap_obs = join.observe(obs_session, eff_arm)
    assert isinstance(gap_obs, Refusal)
    assert gap_obs.code is RefusalCode.OBSERVATION_GAP

    cov = replace(
        ex["HostCoverage"],
        observation=obs["host_obs_arm"],
        comparison=obs["cmp_arm"],
        native_binding=WITNESS_1,
        through_boundary=eff_arm,
        live_watch=obs_session,
    )
    rig.host_observer.register_observation(
        selection_revision=rig.running_job.selection_revision,
        boundary="A_PRE_ARM",
        observation=obs["host_obs_arm"],
        coverage=cov,
        witness=WITNESS_1,
    )
    obs_res = join.observe(obs_session, eff_arm)
    assert isinstance(obs_res, AcceptedData)
    assert obs_res.data == obs["host_obs_arm"]

    # Effect outside scope.protected_effects refuses SCOPE_MISMATCH
    bad_observe = join.observe(obs_session, other_eff)
    assert isinstance(bad_observe, Refusal)
    assert bad_observe.code is RefusalCode.SCOPE_MISMATCH

    # 5. recheck_effect
    # Before registering lease -> RIGHTS_MISSING
    no_lease_res = join.recheck_effect(obs_session, eff_arm, cov)
    assert isinstance(no_lease_res, Refusal)
    assert no_lease_res.code is RefusalCode.RIGHTS_MISSING

    lease = replace(ex["EffectLease"], effect=eff_arm)
    rig.host_observer.register_lease(
        selection_revision=rig.running_job.selection_revision,
        operation_id="launch",
        lease=lease,
    )
    recheck_res = join.recheck_effect(obs_session, eff_arm, cov)
    assert isinstance(recheck_res, AcceptedData)
    assert recheck_res.data == lease

    # Coverage with gaps refuses OBSERVATION_GAP
    gapped_host_obs = replace(obs["host_obs_arm"], gaps=("launch",))
    bad_cov = replace(cov, observation=gapped_host_obs)
    bad_recheck = join.recheck_effect(obs_session, eff_arm, bad_cov)
    assert isinstance(bad_recheck, Refusal)
    assert bad_recheck.code is RefusalCode.OBSERVATION_GAP

    # 6. witness_event
    life_key = replace(ex["LifecycleKey"], selection=obs["sel_run"])
    wit_res = join.witness_event(obs_session, life_key, eff_arm)
    assert isinstance(wit_res, AcceptedData)
    assert wit_res.data.witness_registration == WITNESS_1.witness_registration


def test_boundary_refusal_twins_missing_halves_and_comparator_outcomes() -> None:
    """Same-boundary refusal twins for before_create, before_checker, before_request, before_admit, before_execute."""
    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service

    # 1. before_create: foreign selection in creator_observation -> SELECTION_FOREIGN
    foreign_obs = replace(obs["creator_obs"], selection=obs["sel_run"])
    res_foreign = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        foreign_obs,
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_foreign, Refusal)
    assert res_foreign.code is RefusalCode.SELECTION_FOREIGN

    # before_create: observation with gaps -> OBSERVATION_GAP
    gapped_obs = replace(obs["creator_obs"], gaps=("launch",))
    res_gap = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        gapped_obs,
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_gap, Refusal)
    assert res_gap.code is RefusalCode.OBSERVATION_GAP

    # before_create: actor mismatch in parent_access_observation -> ROOT_MISMATCH
    wrong_root = replace(obs["parent_root"], actor_instance=obs["checker_inst"])
    res_root = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        obs["creator_obs"],
        wrong_root,
        obs["boot_cmp"],
    )
    assert isinstance(res_root, Refusal)
    assert res_root.code is RefusalCode.ROOT_MISMATCH

    # before_create: wrong boundary phase in comparison -> CLOSURE_MISMATCH
    res_wrong_bnd = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        obs["creator_obs"],
        obs["parent_root"],
        obs["cmp_arm"],
    )
    assert isinstance(res_wrong_bnd, Refusal)
    assert res_wrong_bnd.code is RefusalCode.CLOSURE_MISMATCH

    # before_create: registered closure inputs recomputed through Systems comparator
    svc.register_closure_inputs(
        selection_revision=rig.pre_dispatch_job.selection_revision,
        boundary="A_PRE_CREATE",
        reviewed_graph=obs["w_create"].reviewed,
        loaded_closure=obs["w_create"].observed,
        observation_epoch=obs["epoch"],
    )
    res_recomputed_ok = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        obs["creator_obs"],
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_recomputed_ok, AcceptedData)

    # 2. before_checker refusal twins
    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )

    # Unregistered QA receiving -> QA_RECEIVING_MISSING
    unreg_qa = FakeQAReceiving(
        receiving_reference=replace(REF_QA, digest="0" * 64),
        receiver=PROCESS_QA,
    )
    res_unreg_qa = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        unreg_qa,
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_unreg_qa, Refusal)
    assert res_unreg_qa.code is RefusalCode.QA_RECEIVING_MISSING

    # Wrong compatibility corpus -> COMPATIBILITY_UNQUALIFIED
    bad_compat = replace(COMPAT_PROFILE_1, corpus="wrong-corpus/0")
    res_bad_compat = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        bad_compat,
        obs["producer_binding"],
    )
    assert isinstance(res_bad_compat, Refusal)
    assert res_bad_compat.code is RefusalCode.COMPATIBILITY_UNQUALIFIED

    # Swapped root kinds in BothRootObservations -> ROOT_MISMATCH
    bad_roots = BothRootObservations(
        publication=obs["ev_root_obs"],
        host_evidence=obs["pub_root_obs"],
    )
    res_bad_roots = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        bad_roots,
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_bad_roots, Refusal)
    assert res_bad_roots.code is RefusalCode.ROOT_MISMATCH


def test_late_refusal_sequence_effects_and_lost_ack_uncertainty() -> None:
    """Late refusal with used sequence / post-dispatch state, and lost-ack uncertainty."""
    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service

    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )
    checker_res = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker_res, AcceptedData)
    checker_binding = checker_res.data.binding

    # Record prior request history with ALREADY_ADMITTED, UNCERTAIN effect, and USED sequence
    rig.request_history_provider.record_history(
        obs["req_id"],
        PriorRequestHistory(
            admission_state=AdmissionState.ALREADY_ADMITTED,
            effect_state=EffectState.UNCERTAIN,
            sequence_use=SequenceUse.USED,
        ),
    )
    # Revoke issuer so before_request produces a late refusal carrying the recorded history
    rig.issuer_verifier.set_revoked(rig.running_job.selector_issuer, True)
    late_res = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(late_res, Refusal)
    assert late_res.code is RefusalCode.AUTHORITY_REVOKED
    assert late_res.admission_state is AdmissionState.ALREADY_ADMITTED
    assert late_res.effect_state is EffectState.UNCERTAIN
    assert late_res.sequence_use is SequenceUse.USED


def test_d1_before_d5_duplicate_counting_prior_fail_and_foreign_receipt_refusals() -> (
    None
):
    """Enforce actual D-1 before D-5, refuse prior FAIL/foreign/future receipt, and refuse duplicate counting."""
    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service
    join = rig.composition.host_join

    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )
    checker_res = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker_res, AcceptedData)
    checker_binding = checker_res.data.binding

    imm_req_res = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(imm_req_res, AcceptedData)
    imm_req_binding = imm_req_res.data.binding

    res_admit = svc.before_admit(
        rig.peer_run,
        imm_req_binding,
        obs["cursors"],
    )
    assert isinstance(res_admit, AcceptedData)

    actual_req_and_rcpt = ActualRequestAndReceipt(
        request=imm_req_binding,
        publication=obs["raw_pub"],
    )

    # 1. before_execute BEFORE D-1 record_admitted_occurrence -> PRIOR_MISSING
    admitted_unrecorded = AdmittedRequestBinding(
        request=imm_req_binding,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    exec_before_d1 = svc.before_execute(
        rig.peer_run,
        admitted_unrecorded,
        obs["op_leg"],
        obs["cursors"],
    )
    assert isinstance(exec_before_d1, Refusal)
    assert exec_before_d1.code is RefusalCode.PRIOR_MISSING

    # 2. before_count BEFORE D-1 record_admitted_occurrence -> PRIOR_MISSING
    count_before_d1 = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_before_d1, Refusal)
    assert count_before_d1.code is RefusalCode.PRIOR_MISSING

    # 3. Record D-1 occurrence
    res_rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req_binding,
        current_binding=res_admit.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(res_rec_occ, AcceptedData)
    publish_and_link_counted_receipt(rig, obs)

    # 4. Foreign selection in provenance -> PRIOR_FOREIGN
    foreign_req_id = replace(obs["req_id"], selection=obs["sel_pre"])
    foreign_prov = replace(obs["prov"], operation_key=foreign_req_id)
    count_foreign = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        foreign_prov,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_foreign, Refusal)
    assert count_foreign.code is RefusalCode.PRIOR_FOREIGN

    # 5. Mismatched occurrence witness in provenance -> PRIOR_UNVERIFIED
    wrong_wit_prov = replace(obs["prov"], occurrence_witness=WITNESS_2)
    count_wrong_wit = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        wrong_wit_prov,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_wrong_wit, Refusal)
    assert count_wrong_wit.code is RefusalCode.PRIOR_UNVERIFIED

    # 6. Disarm relation "after" -> WINDOW_INELIGIBLE
    after_disarm_prov = replace(
        obs["prov"],
        disarm_relation=FakeDisarmRelation(relation="after", witness=WITNESS_1),
    )
    count_disarm = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        after_disarm_prov,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_disarm, Refusal)
    assert count_disarm.code is RefusalCode.WINDOW_INELIGIBLE

    # 7. P5 verdict BLOCKED -> RESULT_UNVERIFIED
    blocked_p5 = FakeP5Assessment(
        verdict="BLOCKED",
        trust="UNTRUSTED",
        assessment_reference=REF_COMPAT,
    )
    count_blocked = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        blocked_p5,
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_blocked, Refusal)
    assert count_blocked.code is RefusalCode.RESULT_UNVERIFIED

    # 8. Uncertain effect state (lost-ack uncertainty) -> RESULT_UNVERIFIED
    rig.effect_fence_provider.record_execution_leg(
        request_identity=obs["req_id"],
        operation_leg=obs["op_leg"],
        current_binding=res_admit.data.current,
        effect_state=EffectState.UNCERTAIN,
    )
    count_uncertain = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_uncertain, Refusal)
    assert count_uncertain.code is RefusalCode.RESULT_UNVERIFIED
    assert count_uncertain.effect_state is EffectState.UNCERTAIN

    # Restore clean execution leg so effect_state is COMPLETE
    svc.before_execute(
        rig.peer_run,
        res_rec_occ.data,
        obs["op_leg"],
        obs["cursors"],
    )

    # 9. First valid before_count succeeds; idempotent verify_publication does not replay,
    #    and duplicate before_count refuses ALREADY_COUNTED!
    count_ok = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_ok, AcceptedData)

    pub_ver_again = join.verify_publication(
        rig.session_host,
        obs["req_id"],
        obs["raw_pub"],
        WITNESS_1,
    )
    assert isinstance(pub_ver_again, AcceptedData)
    assert pub_ver_again.data == obs["prov"]

    count_dup = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_dup, Refusal)
    assert count_dup.code is RefusalCode.ALREADY_COUNTED
    assert count_dup.sequence_use is SequenceUse.USED


def test_default_compose_p3_authority_is_inert_and_refuses_all_ports() -> None:
    """Default compose_p3_authority() has no configured providers, writes_enabled=False, and refuses fail-closed."""
    comp = compose_p3_authority()
    rig, obs, _, _ = _setup_ready_service_rig()

    assert comp.service.writes_enabled is False

    res_create = comp.service.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        obs["creator_obs"],
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_create, Refusal)
    assert res_create.code is RefusalCode.AUTHORITY_UNAVAILABLE

    res_host_job = comp.host_join.select_host_job(rig.session_host)
    assert isinstance(res_host_job, Refusal)
    assert res_host_job.code is RefusalCode.AUTHORITY_UNAVAILABLE

    # writes_enabled=True is forced to False in source composition
    comp_writes = compose_p3_authority(writes_enabled=True)
    assert comp_writes.service.writes_enabled is False


def test_distributed_fence_unimplemented_and_mid_boundary_change_controls() -> None:
    """Prove distributed effect fence claims are refused and mid-boundary selection
    changes distinguish pre-new-request refusal from already-admitted history.
    """
    import pytest

    from temper_ai.p3_authority._providers import InMemoryEffectFenceProvider

    with pytest.raises(ValueError, match="cannot claim distributed enforcement"):
        InMemoryEffectFenceProvider(distributed_enforced=True)

    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service

    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )
    checker_res = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker_res, AcceptedData)
    checker_binding = checker_res.data.binding

    imm_req_res = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(imm_req_res, AcceptedData)
    imm_req_binding = imm_req_res.data.binding
    res_admit = svc.before_admit(rig.peer_run, imm_req_binding, obs["cursors"])
    assert isinstance(res_admit, AcceptedData)
    res_rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req_binding,
        current_binding=res_admit.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(res_rec_occ, AcceptedData)

    # Record history for the admitted request
    rig.request_history_provider.record_history(
        obs["req_id"],
        PriorRequestHistory(
            admission_state=AdmissionState.ALREADY_ADMITTED,
            effect_state=EffectState.ADMITTED_ONLY,
            sequence_use=SequenceUse.USED,
        ),
    )

    # Mid-boundary change: publish a snapshot that supersedes running_job's selection_revision
    rig.publisher.publish_snapshot(
        SelectionSnapshot(
            snapshot_revision="snap-superseded-run",
            jobs=(rig.pre_dispatch_job,),
            verified_at=TRUSTED_NOW,
        )
    )

    # 1. Pre-new-request refusal for a new un-admitted request carries NOT_ADMITTED + UNUSED
    new_req_id = replace(obs["req_id"], request_id="req-new-2", sequence=2)
    pre_new_refusal = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        new_req_id,
        obs["cursors"],
    )
    assert isinstance(pre_new_refusal, Refusal)
    assert pre_new_refusal.code is RefusalCode.SELECTION_CHANGED
    assert pre_new_refusal.admission_state is AdmissionState.NOT_ADMITTED
    assert pre_new_refusal.sequence_use is SequenceUse.UNUSED

    # 2. Mid-boundary before_execute on the already-admitted request refuses SELECTION_CHANGED
    #    while preserving ALREADY_ADMITTED + USED history
    mid_exec_refusal = svc.before_execute(
        rig.peer_run,
        res_rec_occ.data,
        obs["op_leg"],
        obs["cursors"],
    )
    assert isinstance(mid_exec_refusal, Refusal)
    assert mid_exec_refusal.code is RefusalCode.SELECTION_CHANGED
    assert mid_exec_refusal.admission_state is AdmissionState.ALREADY_ADMITTED
    assert mid_exec_refusal.sequence_use is SequenceUse.USED


def test_guard_deletion_and_loosening_bites_with_positive_twins() -> None:
    """Bite executable guards across registry, candidate_bindings, and service with
    canaries after allowed words and positive twins at the same boundary.
    """
    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service

    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )

    # Positive twin at before_checker passes
    pos_checker = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(pos_checker, AcceptedData)

    # Canary 1: corpus prefix/contains canary ("ops-host-compat-corpus/1-canary") must refuse COMPATIBILITY_UNQUALIFIED
    canary_compat = replace(
        COMPAT_PROFILE_1,
        corpus="ops-host-compat-corpus/1-canary",
    )
    res_canary_compat = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        canary_compat,
        obs["producer_binding"],
    )
    assert isinstance(res_canary_compat, Refusal)
    assert res_canary_compat.code is RefusalCode.COMPATIBILITY_UNQUALIFIED

    # Canary 2: root_kind prefix/contains canary ("publication-canary") must refuse ROOT_MISMATCH
    canary_pub_root = replace(
        obs["pub_root_obs"],
        root_kind="publication-canary",  # type: ignore[arg-type]
    )
    res_canary_root = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        BothRootObservations(
            publication=canary_pub_root,
            host_evidence=obs["ev_root_obs"],
        ),
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_canary_root, Refusal)
    assert res_canary_root.code is RefusalCode.ROOT_MISMATCH

    # Canary 3: observation_boundary prefix/contains canary ("A_PRE_ARM-canary") must refuse ROOT_MISMATCH
    canary_bnd_root = replace(
        obs["pub_root_obs"],
        observation_boundary="A_PRE_ARM-canary",  # type: ignore[arg-type]
    )
    res_canary_bnd = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        BothRootObservations(
            publication=canary_bnd_root,
            host_evidence=obs["ev_root_obs"],
        ),
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_canary_bnd, Refusal)
    assert res_canary_bnd.code is RefusalCode.ROOT_MISMATCH

    # Canary 4: P5 trust prefix/contains canary ("UNTRUSTED-canary") and verdict ("PASS-canary") at before_count
    imm_req_res = svc.before_request(
        rig.peer_run,
        pos_checker.data.binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(imm_req_res, AcceptedData)
    imm_req = imm_req_res.data.binding
    admit_res = svc.before_admit(rig.peer_run, imm_req, obs["cursors"])
    assert isinstance(admit_res, AcceptedData)
    rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req,
        current_binding=admit_res.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(rec_occ, AcceptedData)
    svc.before_execute(rig.peer_run, rec_occ.data, obs["op_leg"], obs["cursors"])
    publish_and_link_counted_receipt(rig, obs)
    actual_req_and_rcpt = ActualRequestAndReceipt(
        request=imm_req,
        publication=obs["raw_pub"],
    )

    canary_trust_p5 = FakeP5Assessment(
        verdict="PASS",
        trust="UNTRUSTED-canary",  # type: ignore[arg-type]
        assessment_reference=REF_COMPAT,
    )
    res_canary_trust = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        canary_trust_p5,
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_canary_trust, Refusal)
    assert res_canary_trust.code is RefusalCode.RESULT_UNVERIFIED

    canary_verdict_p5 = FakeP5Assessment(
        verdict="PASS-canary",  # type: ignore[arg-type]
        trust="UNTRUSTED",
        assessment_reference=REF_COMPAT,
    )
    res_canary_verdict = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        canary_verdict_p5,
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_canary_verdict, Refusal)
    assert res_canary_verdict.code is RefusalCode.RESULT_UNVERIFIED

    # Positive twin at before_count passes
    pos_count = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(pos_count, AcceptedData)

    # Programmatic guard-deletion / loosening bites:
    # Bite A: deleting _verify_peer on AuthorityRegistryService allows an unverified peer through for_submit
    unver_peer = replace(rig.peer_submit, peer_reference="peer:unverified-999")
    assert isinstance(
        rig.composition.registry.for_submit(unver_peer, "designated_v1"),
        Refusal,
    )
    orig_verify_peer = rig.composition.registry._verify_peer
    rig.composition.registry._verify_peer = lambda *a, **kw: None  # type: ignore[method-assign]
    try:
        bitten_submit = rig.composition.registry.for_submit(unver_peer, "designated_v1")
        assert isinstance(bitten_submit, AcceptedData), "Guard deletion must bite!"
    finally:
        rig.composition.registry._verify_peer = orig_verify_peer  # type: ignore[method-assign]

    # Bite B: deleting verify_qa_receiving on QAReceivingVerifier allows unregistered QA receiving through before_checker
    orig_verify_qa = rig.qa_verifier.verify_qa_receiving
    rig.qa_verifier.verify_qa_receiving = lambda *a, **kw: None  # type: ignore[method-assign]
    try:
        bitten_qa = svc.before_checker(
            rig.peer_checker,
            win_binding,
            obs["host_obs_arm"],
            obs["worker_obs_arm"],
            obs["both_roots"],
            obs["cmp_arm"],
            FakeQAReceiving(
                receiving_reference=replace(REF_QA, digest="0" * 64),
                receiver=PROCESS_QA,
            ),
            obs["compat_recv"],
            obs["producer_binding"],
        )
        assert isinstance(bitten_qa, AcceptedData), (
            "QA receiving guard deletion must bite!"
        )
    finally:
        rig.qa_verifier.verify_qa_receiving = orig_verify_qa  # type: ignore[method-assign]

    # Bite C: deleting mark_counted duplicate guard on EffectFenceProvider allows duplicate counting through before_count
    assert isinstance(
        svc.before_count(
            rig.peer_qa,
            actual_req_and_rcpt,
            obs["p5_ass"],
            obs["prov"],
            obs["cursors"],
            obs["qa_recv"],
        ),
        Refusal,
    )
    orig_mark_counted = rig.effect_fence_provider.mark_counted
    rig.effect_fence_provider.mark_counted = (  # type: ignore[method-assign]
        lambda *, request_identity, idempotency_identity, current_binding: AcceptedData(
            data=rig.effect_fence_provider.lookup_occurrence(request_identity),  # type: ignore[arg-type]
            evidence=pos_count.evidence,
        )
    )
    try:
        bitten_dup = svc.before_count(
            rig.peer_qa,
            actual_req_and_rcpt,
            obs["p5_ass"],
            obs["prov"],
            obs["cursors"],
            obs["qa_recv"],
        )
        assert isinstance(bitten_dup, AcceptedData), (
            "Duplicate-count guard deletion must bite!"
        )
    finally:
        rig.effect_fence_provider.mark_counted = orig_mark_counted  # type: ignore[method-assign]


def _run_isolated_probe(args: list[str], expected_token: str) -> tuple[int, bool]:
    """Run a child probe and return only (returncode, token_matched) so child
    stdout, stderr, and argv never enter pytest's assertion failure representation.
    """
    import subprocess

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("isolated child probe timed out after 15 s") from None
    rc = int(proc.returncode)
    matched = bool(
        any(line.strip() == expected_token for line in proc.stdout.splitlines())
    )
    del proc
    return rc, matched


def _assert_isolated_probe_succeeded(rc: int, ok: bool) -> None:
    assert rc == 0 and ok is True


def test_fresh_process_cold_import_and_contact_spies() -> None:
    """Spawn an isolated Python subprocess with network/DB/HTTP/subprocess spies installed
    before importing temper_ai.p3_authority.{registry,candidate_bindings,service}
    to prove cold import and default-off constructors make zero external contacts,
    and verify child-failure output privacy (CWE-532) against stdout/stderr/argv canaries.
    """
    import sys

    import pytest

    probe_code = """
import http.client
import socket
import subprocess
import urllib.request
import httpx
import temper_ai.database as db_mod

contacts = []

def _deny(*args, **kwargs):
    contacts.append(("contact", args))
    raise AssertionError("external contact attempted")

socket.socket.connect = _deny
socket.create_connection = _deny
urllib.request.urlopen = _deny
http.client.HTTPConnection.connect = _deny
http.client.HTTPSConnection.connect = _deny
httpx.Client = _deny
httpx.AsyncClient = _deny
db_mod.get_database = _deny
db_mod.get_session = _deny
subprocess.Popen = _deny
subprocess.run = _deny

from dataclasses import dataclass
from temper_ai.p3_authority.registry import AuthorityRegistryService
from temper_ai.p3_authority.candidate_bindings import P3CandidateBindings
from temper_ai.p3_authority.service import P3AuthorityService, compose_p3_authority
from temper_ai.p3_authority.contract import Refusal, RefusalCode

@dataclass(frozen=True)
class _Proc:
    process_reference: str = "proc:probe"

@dataclass(frozen=True)
class _Peer:
    peer_reference: str = "peer:probe"
    process: _Proc = _Proc()

reg = AuthorityRegistryService()
cb = P3CandidateBindings()
svc = P3AuthorityService()
comp = compose_p3_authority()

assert comp.service.writes_enabled is False
assert cb.designated("any_workflow") is False
res = reg.for_submit(_Peer(), "any_workflow")
assert isinstance(res, Refusal) and res.code is RefusalCode.AUTHORITY_UNAVAILABLE
res_create = svc.before_create(_Peer(), object(), object(), object(), object())
assert isinstance(res_create, Refusal) and res_create.code is RefusalCode.AUTHORITY_UNAVAILABLE
res_join = comp.host_join.select_host_job(object())
assert isinstance(res_join, Refusal) and res_join.code is RefusalCode.AUTHORITY_UNAVAILABLE
assert contacts == []
print("COLD_IMPORT_SPIES_OK")
"""
    rc, ok = _run_isolated_probe(
        [sys.executable, "-c", probe_code], "COLD_IMPORT_SPIES_OK"
    )
    _assert_isolated_probe_succeeded(rc, ok)

    # CWE-532 child-failure privacy canary: plant canaries after allowed words on stdout,
    # on an extra line, in stderr, and in argv; verify none appear in failure text.
    canary_out = "CANARY_STDOUT_" + ("A" * 48)
    canary_err = "CANARY_STDERR_" + ("B" * 48)
    canary_arg = "CANARY_ARGV_" + ("C" * 48)
    failing_code = (
        "import sys\n"
        f"print('COLD_IMPORT_SPIES_OK {canary_out}')\n"
        f"print('{canary_out}')\n"
        f"sys.stderr.write('err {canary_err}\\n')\n"
        "sys.exit(3)\n"
    )
    fail_rc, fail_ok = _run_isolated_probe(
        [sys.executable, "-c", failing_code, canary_arg],
        "COLD_IMPORT_SPIES_OK",
    )
    with pytest.raises(AssertionError) as exc_info:
        _assert_isolated_probe_succeeded(fail_rc, fail_ok)
    failure_text = str(exc_info.getrepr(style="long"))
    assert canary_out not in failure_text
    assert canary_err not in failure_text
    assert canary_arg not in failure_text


def test_security_arm_b_hardening_twins_and_guard_bites() -> None:
    """Verify SB-F1, SB-F2, SB-F3, and SB-F4 positive/negative twins and canaries."""
    rig, obs, _, _ = _setup_ready_service_rig()
    svc = rig.composition.service
    join = rig.composition.host_join

    # --- SB-F4: select_host_job / permit_observation reviewed graph & caller fields ---
    rig.publisher.publish_snapshot(
        SelectionSnapshot(
            snapshot_revision="snap-sbf4-single",
            jobs=(rig.pre_dispatch_job,),
            verified_at=TRUSTED_NOW,
        )
    )
    svc.register_allowed_rows(
        rig.pre_dispatch_job.selection_revision,
        frozenset({"row-1", "row-custom"}),
    )
    host_job_ok = join.select_host_job(rig.session_host)
    assert isinstance(host_job_ok, AcceptedData)
    assert host_job_ok.data.caller.source_review_ref == obs["w_create"].reviewed
    assert (
        host_job_ok.data.caller.inspect_variant
        == rig.pre_dispatch_job.compatibility_profile.inspect
    )
    assert host_job_ok.data.caller.allowed_rows == frozenset({"row-1", "row-custom"})

    # Removing registered reviewed graph + closure inputs -> CLOSURE_INCOMPLETE
    saved_graphs = dict(svc._reviewed_graphs)
    saved_closures = dict(svc._closure_inputs)
    svc._reviewed_graphs.clear()
    svc._closure_inputs.clear()
    try:
        no_graph_job = join.select_host_job(rig.session_host)
        assert isinstance(no_graph_job, Refusal)
        assert no_graph_job.code is RefusalCode.CLOSURE_INCOMPLETE

        no_create_closure = svc.before_create(
            rig.peer_worker,
            rig.pre_dispatch_job,
            obs["creator_obs"],
            obs["parent_root"],
            obs["boot_cmp"],
        )
        assert isinstance(no_create_closure, Refusal)
        assert no_create_closure.code is RefusalCode.CLOSURE_INCOMPLETE
    finally:
        svc._reviewed_graphs.update(saved_graphs)
        svc._closure_inputs.update(saved_closures)
        rig.publisher.publish_snapshot(
            SelectionSnapshot(
                snapshot_revision="snap-sbf4-both",
                jobs=(rig.pre_dispatch_job, rig.running_job),
                verified_at=TRUSTED_NOW,
            )
        )
        cur_run_arm = rig.composition.registry.check_current(
            rig.peer_checker,
            rig.running_job.selection_revision,
            "A_PRE_ARM",
            default_effect_for_job(rig.running_job, "A_PRE_ARM"),
        )
        if isinstance(cur_run_arm, AcceptedData):
            rig.composition.registry.bind_created(
                rig.peer_checker,
                cur_run_arm.data,
                ActualCreation(
                    window_id="win-1",
                    object_identity=FakeNativeRootObject("fs:win-1"),
                    creator=PROCESS_WORKER,
                    birth=WITNESS_1,
                ),
            )

    # --- SB-F3: observer/root/window authentication in before_create & before_checker ---
    forged_creator_obs = replace(
        obs["creator_obs"],
        process_instances=obs["creator_obs"].process_instances * 2,
    )
    res_forged_host_create = svc.before_create(
        rig.peer_worker,
        rig.pre_dispatch_job,
        forged_creator_obs,
        obs["parent_root"],
        obs["boot_cmp"],
    )
    assert isinstance(res_forged_host_create, Refusal)
    assert res_forged_host_create.code is RefusalCode.OBSERVATION_GAP

    cur_run_res = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_res, AcceptedData)
    cur_run = cur_run_res.data
    win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-1",
            object_identity=FakeNativeRootObject("fs:win-1"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )
    unbound_win_binding = WindowBinding(
        current=cur_run,
        actual_creation=ActualCreation(
            window_id="win-unbound",
            object_identity=FakeNativeRootObject("fs:win-unbound"),
            creator=PROCESS_WORKER,
            birth=WITNESS_1,
        ),
    )
    res_unbound_win = svc.before_checker(
        rig.peer_checker,
        unbound_win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_unbound_win, Refusal)
    assert res_unbound_win.code is RefusalCode.WINDOW_INELIGIBLE

    forged_worker_obs = replace(
        obs["worker_obs_arm"],
        launch_profile_ref=REF_COMPAT,
    )
    res_forged_worker = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        forged_worker_obs,
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_forged_worker, Refusal)
    assert res_forged_worker.code is RefusalCode.OBSERVATION_GAP

    forged_pub_root = replace(
        obs["pub_root_obs"],
        observed_access=frozenset({"read"}),
    )
    res_forged_root = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        BothRootObservations(
            publication=forged_pub_root,
            host_evidence=obs["ev_root_obs"],
        ),
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(res_forged_root, Refusal)
    assert res_forged_root.code is RefusalCode.ROOT_MISMATCH

    checker_res = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker_res, AcceptedData)
    checker_binding = checker_res.data.binding

    # --- SB-F2: window_id continuity across Phase B/C ---
    wrong_win_req_id = replace(obs["req_id"], window_id="win-foreign")
    res_req_wrong_win = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        wrong_win_req_id,
        obs["cursors"],
    )
    assert isinstance(res_req_wrong_win, Refusal)
    assert res_req_wrong_win.code is RefusalCode.SCOPE_MISMATCH

    imm_req_res = svc.before_request(
        rig.peer_run,
        checker_binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(imm_req_res, AcceptedData)
    imm_req = imm_req_res.data.binding

    forged_imm_req = ImmutableRequestBinding(
        checker=checker_binding,
        request_identity=wrong_win_req_id,
        request_raw=obs["req_raw_ref"],
    )
    res_admit_wrong_win = svc.before_admit(
        rig.peer_run,
        forged_imm_req,
        obs["cursors"],
    )
    assert isinstance(res_admit_wrong_win, Refusal)
    assert res_admit_wrong_win.code is RefusalCode.SCOPE_MISMATCH

    admit_res = svc.before_admit(rig.peer_run, imm_req, obs["cursors"])
    assert isinstance(admit_res, AcceptedData)
    rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req,
        current_binding=admit_res.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(rec_occ, AcceptedData)
    svc.before_execute(rig.peer_run, rec_occ.data, obs["op_leg"], obs["cursors"])

    forged_admitted_occ = AdmittedRequestBinding(
        request=imm_req,
        occurrence=replace(obs["occ_handle"], key=wrong_win_req_id),
        admission_witness=WITNESS_1,
    )
    res_exec_wrong_win = svc.before_execute(
        rig.peer_run,
        forged_admitted_occ,
        obs["op_leg"],
        obs["cursors"],
    )
    assert isinstance(res_exec_wrong_win, Refusal)
    assert res_exec_wrong_win.code is RefusalCode.SCOPE_MISMATCH

    # --- SB-F1: provenance/publication/occurrence state, P5 parity & D-1 -> D-5 predecessor ---
    publish_and_link_counted_receipt(rig, obs)
    actual_req_and_rcpt = ActualRequestAndReceipt(
        request=imm_req,
        publication=obs["raw_pub"],
    )

    # 1. Incomplete provenance state ("incomplete" and "uncertain") -> RESULT_UNVERIFIED
    for bad_prov_state in ("incomplete", "uncertain"):
        bad_prov = replace(obs["prov"], state=bad_prov_state)
        res_bad_prov = svc.before_count(
            rig.peer_qa,
            actual_req_and_rcpt,
            obs["p5_ass"],
            bad_prov,
            obs["cursors"],
            obs["qa_recv"],
        )
        assert isinstance(res_bad_prov, Refusal)
        assert res_bad_prov.code is RefusalCode.RESULT_UNVERIFIED

    # 2. Incomplete cleanup_state ("incomplete" and "uncertain") -> RESULT_UNVERIFIED
    for bad_cleanup in ("incomplete", "uncertain"):
        bad_pub = replace(obs["raw_pub"], cleanup_state=bad_cleanup)
        bad_prov_pub = replace(obs["prov"], raw_publication=bad_pub)
        res_bad_cleanup = svc.before_count(
            rig.peer_qa,
            ActualRequestAndReceipt(request=imm_req, publication=bad_pub),
            obs["p5_ass"],
            bad_prov_pub,
            obs["cursors"],
            obs["qa_recv"],
        )
        assert isinstance(res_bad_cleanup, Refusal)
        assert res_bad_cleanup.code is RefusalCode.RESULT_UNVERIFIED

    # 3. Non-terminal publication outcome ("refused" / "uncertain") -> RESULT_UNVERIFIED
    uncertain_pub = replace(obs["raw_pub"], outcome="uncertain")
    uncertain_prov = replace(obs["prov"], raw_publication=uncertain_pub)
    res_uncertain_pub = svc.before_count(
        rig.peer_qa,
        ActualRequestAndReceipt(request=imm_req, publication=uncertain_pub),
        obs["p5_ass"],
        uncertain_prov,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_uncertain_pub, Refusal)
    assert res_uncertain_pub.code is RefusalCode.RESULT_UNVERIFIED

    # 4. Native outcome="app-failure" vs P5 Assessment(verdict="PASS") contradiction -> RESULT_UNVERIFIED
    fail_pub = replace(obs["raw_pub"], outcome="app-failure")
    fail_prov = replace(obs["prov"], raw_publication=fail_pub)
    res_fail_contradiction = svc.before_count(
        rig.peer_qa,
        ActualRequestAndReceipt(request=imm_req, publication=fail_pub),
        obs["p5_ass"],
        fail_prov,
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_fail_contradiction, Refusal)
    assert res_fail_contradiction.code is RefusalCode.RESULT_UNVERIFIED

    # 5. Predecessor (D-1 -> D-5) foreign, failed, incomplete, or unregistered -> refused
    foreign_pred_key = replace(obs["pred_key"], selection=obs["sel_pre"])
    foreign_pred_occ = replace(obs["pred_occ_handle"], key=foreign_pred_key)
    foreign_pred_pub = replace(obs["pred_pub"], occurrence=foreign_pred_occ)
    foreign_pred_prov = replace(
        obs["pred_prov"],
        operation_key=foreign_pred_key,
        raw_publication=foreign_pred_pub,
    )
    res_foreign_pred = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        replace(obs["prov"], predecessor=foreign_pred_prov),
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_foreign_pred, Refusal)
    assert res_foreign_pred.code is RefusalCode.PRIOR_FOREIGN

    failed_pred_occ = replace(obs["pred_occ_handle"], state="failed")
    failed_pred_pub = replace(
        obs["pred_pub"],
        occurrence=failed_pred_occ,
        outcome="app-failure",
    )
    failed_pred_prov = replace(obs["pred_prov"], raw_publication=failed_pred_pub)
    res_failed_pred = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        replace(obs["prov"], predecessor=failed_pred_prov),
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_failed_pred, Refusal)
    assert res_failed_pred.code is RefusalCode.PRIOR_UNVERIFIED

    incomplete_pred_occ = replace(obs["pred_occ_handle"], state="started")
    incomplete_pred_pub = replace(obs["pred_pub"], occurrence=incomplete_pred_occ)
    incomplete_pred_prov = replace(
        obs["pred_prov"],
        raw_publication=incomplete_pred_pub,
    )
    res_incomplete_pred = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        replace(obs["prov"], predecessor=incomplete_pred_prov),
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_incomplete_pred, Refusal)
    assert res_incomplete_pred.code is RefusalCode.PRIOR_UNVERIFIED

    unreg_pred_key = replace(obs["pred_key"], request_id="req-unreg-pred")
    unreg_pred_occ = replace(obs["pred_occ_handle"], key=unreg_pred_key)
    unreg_pred_pub = replace(obs["pred_pub"], occurrence=unreg_pred_occ)
    unreg_pred_prov = replace(
        obs["pred_prov"],
        operation_key=unreg_pred_key,
        raw_publication=unreg_pred_pub,
    )
    res_missing_pred = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        replace(obs["prov"], predecessor=unreg_pred_prov),
        obs["cursors"],
        obs["qa_recv"],
    )
    # Not the predecessor the host linked (ruling C2): PRIOR_UNVERIFIED, from the
    # port's own chain (it was PRIOR_MISSING from the test double's lookups).
    assert isinstance(res_missing_pred, Refusal)
    assert res_missing_pred.code is RefusalCode.PRIOR_UNVERIFIED

    # 6. Positive twin: valid D-1 -> D-5 predecessor preserved in VerifiedReceiptBinding
    res_count_ok = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(res_count_ok, AcceptedData)
    assert res_count_ok.data.native_receiving.predecessor == obs["pred_prov"]
