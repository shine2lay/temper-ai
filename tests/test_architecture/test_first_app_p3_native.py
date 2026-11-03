"""T4 disabled native-boundary consumer and offline conformance tests (#125 / #466).

Covers:
1. H1 Guard-off false canaries: while WRITES_ADMITTED is False, open_host, settle,
   run_row, and join_native_host_row refuse with status='BLOCKED' and reasons=[WRITES_OFF]
   before inspecting caller inputs, clocks, sleeps, filesystems, or supplier services.
2. Canonical supplier identity: temper_ai.p3_authority.contract, p3_host_contracts,
   p3_source_closure, ops_host_source_comparison, temper_ai.p3_authority.service, and
   temper_ai.p3_authority.worker_observation resolve without stubs and maintain
   WRITES_ADMITTED=False, DEFAULT_CANDIDATE_BINDINGS=None, N1-N8 UNRESOLVED,
   R-1/R-1i/D-1/D-5 UNQUALIFIED, and P5 UNTRUSTED.
3. H2 Offline consumer join over canonical #261/#262/#263/#71 suppliers across all four
   host rows (R-1, R-1i, D-1, D-5), verifying accepted inner decisions remain
   outer status='UNQUALIFIED' and count_eligible=False while writes are off.
4. Refusal and incomplete-closure propagation across authority, source closure,
   worker observation, and both-root verification, plus fail-loud input validation.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BIN = _ROOT / "configs/architecture/bin"
for _entry in (str(_BIN), str(_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import first_app_p3_host as wire  # noqa: E402
import first_app_p3_native as native_consumer  # noqa: E402
import ops_host_source_comparison as ops_closure  # noqa: E402

import p3_host_contracts as host_contracts  # noqa: E402
import p3_source_closure as source_closure  # noqa: E402
from temper_ai.p3_authority.boundary_types import BothRootObservations  # noqa: E402
from temper_ai.p3_authority.contract import (  # noqa: E402
    AdmissionState,
    EffectState,
    HostCalibrationSelection,
    HostProjectSelection,
    NativeClosureExpectation,
    Phase,
    RawRef,
    Refusal,
    RefusalCode,
    RetryKind,
    SequenceUse,
    SourceClosureComparison,
    VerifiedClosureOrigins,
    compare_loaded_source,
)
from temper_ai.p3_authority.worker_observation import (  # noqa: E402
    EXISTING_TEMPER_SEAM_GUARANTEES,
    WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    RootOwnerVsActorAssertion,
    WorkerObservationAdapter,
    build_worker_observation_compat_cases,
    refuse_existing_seam_as_complete_coverage,
)
from temper_ai.runner import admission as runner_admission  # noqa: E402
from temper_ai.runner.admission import is_designated  # noqa: E402
from tests.test_architecture.ops_host_n3_cases import (  # noqa: E402
    bad_twin,
    clean_world,
)
from tests.test_p3_authority._composition_fixtures import (  # noqa: E402
    WITNESS_1,
    FakeNativeRootObject,
    FakeSession,
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
)
from tests.test_p3_authority.test_child_registration import (  # noqa: E402
    SyntheticWorkerProviderDouble,
    make_both_roots,
    make_grant,
    make_selected_job,
    make_supplied_worker_frame,
)


class OpaqueInput:
    """A guard-off call must not even inspect caller-controlled data."""

    def __getattribute__(self, name: str):
        raise AssertionError("guard-off input inspected")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("guard-off input compared")

    def __str__(self) -> str:
        raise AssertionError("guard-off input formatted")


def unexpected_effect(*args: object, **kwargs: object):
    raise AssertionError("guard-off effect reached")


def _setup_offline_supplier_world():
    rig = make_populated_test_rig(writes_enabled=False)
    obs = populate_boundary_happy_path_observations(rig)
    rig.host_provenance.register_occurrence(
        obs["req_id"],
        obs["occ_handle"],
        witness=WITNESS_1,
    )
    rig.host_provenance.register_publication_provenance(
        key=obs["req_id"],
        publication_sha256=obs["rec_raw_ref"].sha256,
        provenance=obs["prov"],
        verified_receive=obs["ver_recv"],
        request_raw=obs["req_bytes"],
        receipt_raw=obs["rec_bytes"],
    )

    worker_job = make_selected_job()
    worker_grant = make_grant(worker_job, boundary="B_PRE_REQUEST")
    worker_frame = make_supplied_worker_frame()
    worker_provider = SyntheticWorkerProviderDouble(frame=worker_frame)
    worker_observer = WorkerObservationAdapter(provider=worker_provider)
    both_roots_arm = make_both_roots()
    root_assertions = (
        RootOwnerVsActorAssertion(
            root_kind="publication",
            actor_process_ref="worker",
            actor_principal="temper-worker",
            actor_uid=1000,
            file_owner_principal="root",
            file_owner_uid=0,
        ),
        RootOwnerVsActorAssertion(
            root_kind="host_evidence",
            actor_process_ref="worker",
            actor_principal="temper-worker",
            actor_uid=1000,
            file_owner_principal="root",
            file_owner_uid=0,
        ),
    )
    receive_effect = replace(
        rig.examples["HostEffect"],
        selection=obs["sel_run"],
        boundary="C_PRE_EXECUTION",
        operation="launch",
    )
    return {
        "rig": rig,
        "obs": obs,
        "worker_job": worker_job,
        "worker_grant": worker_grant,
        "worker_frame": worker_frame,
        "worker_provider": worker_provider,
        "worker_observer": worker_observer,
        "both_roots_arm": both_roots_arm,
        "both_roots_actor": both_roots_arm.publication.binding.actor_instance,
        "root_assertions": root_assertions,
        "receive_effect": receive_effect,
    }


def test_disabled_entries_refuse_before_inspecting_inputs_or_clock():
    assert wire.WRITES_ADMITTED is False
    assert wire.DEFAULT_CANDIDATE_BINDINGS is None
    assert native_consumer.WRITES_ADMITTED is False
    assert native_consumer.DEFAULT_CANDIDATE_BINDINGS is None

    opaque = OpaqueInput()
    session = wire.open_host(opaque, clock=unexpected_effect)
    assert session.record == {"status": "BLOCKED", "reasons": [wire.WRITES_OFF]}
    assert session.loaded is False

    assert asyncio.run(wire.settle(opaque, clock=unexpected_effect, sleep=unexpected_effect)) is None

    row_result = asyncio.run(
        wire.run_row(
            opaque,
            opaque,
            clock=unexpected_effect,
            sleep=unexpected_effect,
        )
    )
    assert row_result == {
        "status": "BLOCKED",
        "reasons": [wire.WRITES_OFF],
        "writer": wire.WRITER,
    }

    host_hook_result = asyncio.run(
        wire.join_native_host_row(
            opaque,
            opaque,
            native_boundary=opaque,
            clock=unexpected_effect,
            sleep=unexpected_effect,
        )
    )
    assert host_hook_result == {
        "status": "BLOCKED",
        "reasons": [wire.WRITES_OFF],
        "writer": wire.WRITER,
        "count_eligible": False,
    }

    native_hook_result = asyncio.run(
        native_consumer.join_native_host_row(
            opaque,
            opaque,
            native_boundary=opaque,
            clock=unexpected_effect,
            sleep=unexpected_effect,
        )
    )
    assert native_hook_result == {
        "status": "BLOCKED",
        "reasons": [wire.WRITES_OFF],
        "writer": wire.WRITER,
        "count_eligible": False,
        "native_obligations": dict(native_consumer.UNRESOLVED_NATIVE_OBLIGATIONS),
    }


def test_disabled_entries_ignore_locally_favorable_session(monkeypatch: pytest.MonkeyPatch):
    assert wire.WRITES_ADMITTED is False

    for module, names in (
        (wire, ("read_raw", "_read")),
        (wire.p5, ("load_bound_candidate_window", "judge_candidate_receipt")),
        (wire.hc, ("read_sequence", "make_request", "write_request")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, unexpected_effect)

    record = {"status": "LOADED", "reasons": [], "settled": [], "native": {"decision": "allowed"}}
    favorable_session = wire.HostSession(record, OpaqueInput(), OpaqueInput(), 0)

    assert asyncio.run(wire.settle(favorable_session, clock=unexpected_effect, sleep=unexpected_effect)) is None
    assert record == {"status": "LOADED", "reasons": [], "settled": [], "native": {"decision": "allowed"}}

    for row in wire.HOST_ROWS:
        result = asyncio.run(
            wire.run_row(
                favorable_session,
                row,
                clock=unexpected_effect,
                sleep=unexpected_effect,
            )
        )
        assert result == {
            "status": "BLOCKED",
            "reasons": [wire.WRITES_OFF],
            "writer": wire.WRITER,
        }

        joined = asyncio.run(
            native_consumer.join_native_host_row(
                favorable_session,
                row,
                clock=unexpected_effect,
                sleep=unexpected_effect,
            )
        )
        assert joined == {
            "status": "BLOCKED",
            "reasons": [wire.WRITES_OFF],
            "writer": wire.WRITER,
            "count_eligible": False,
            "native_obligations": dict(native_consumer.UNRESOLVED_NATIVE_OBLIGATIONS),
        }
    assert record == {"status": "LOADED", "reasons": [], "settled": [], "native": {"decision": "allowed"}}


def test_disabled_native_boundary_posture_and_canonical_supplier_identity():
    checks = native_consumer.verify_canonical_supplier_bindings()
    assert checks == {
        "host_contract_identity": True,
        "closure_identity": True,
        "service_identity": True,
        "worker_identity": True,
        "worker_compat_profile_valid": True,
    }

    assert getattr(runner_admission, "DEFAULT_CANDIDATE_BINDINGS", None) is None
    assert is_designated("designated_v1", native_consumer.DEFAULT_CANDIDATE_BINDINGS) is False
    assert RawRef is host_contracts.RawRef
    assert HostProjectSelection is host_contracts.ProjectSelection
    assert HostCalibrationSelection is host_contracts.CalibrationSelection
    assert NativeClosureExpectation is source_closure.NativeClosureExpectation
    assert NativeClosureExpectation is ops_closure.NativeClosureExpectation
    assert VerifiedClosureOrigins is source_closure.VerifiedClosureOrigins
    assert VerifiedClosureOrigins is ops_closure.VerifiedClosureOrigins
    assert SourceClosureComparison is source_closure.SourceClosureComparison
    assert SourceClosureComparison is ops_closure.SourceClosureComparison
    assert compare_loaded_source is source_closure.compare_loaded_source
    assert ops_closure.compare_loaded_source is source_closure.compare_loaded_source

    status = native_consumer.inspect_disabled_native_boundary()
    assert status.writes_admitted is False
    assert status.default_candidate_bindings_active is False
    assert status.default_native_boundary_active is False
    assert status.default_native_host_join_active is False
    assert status.default_worker_observer_active is False
    assert status.supplier_contract_bound is True
    assert status.supplier_service_bound is True
    assert status.supplier_worker_observation_bound is True
    assert status.supplier_closure_bound is True
    assert status.worker_compat_corpus_id == WORKER_OBSERVATION_COMPAT_CORPUS_ID
    assert dict(status.native_obligations) == {f"N{i}": "UNRESOLVED" for i in range(1, 9)}
    assert status.r1_status == "UNQUALIFIED"
    assert status.r1i_status == "UNQUALIFIED"
    assert status.d1_status == "UNQUALIFIED"
    assert status.d5_status == "UNQUALIFIED"
    assert status.p5_trust_posture == "UNTRUSTED"
    assert wire.native_boundary_status() == status.to_dict()

    composed = native_consumer.compose_disabled_consumer_service()
    assert composed.service.writes_enabled is False
    with pytest.raises(ValueError, match="forbids writes_enabled=True"):
        native_consumer.compose_disabled_consumer_service(writes_enabled=True)


def test_offline_consumer_join_over_canonical_suppliers_stays_unqualified_and_never_passes():
    for row in wire.HOST_ROWS:
        w = _setup_offline_supplier_world()
        rig = w["rig"]
        obs = w["obs"]
        evaluation = native_consumer.evaluate_offline_native_join(
            row=row,
            service=rig.composition.service,
            host_join=rig.composition.host_join,
            worker_observer=w["worker_observer"],
            peer_worker=rig.peer_worker,
            peer_checker=rig.peer_checker,
            peer_run=rig.peer_run,
            peer_qa=rig.peer_qa,
            session_host=rig.session_host,
            pre_dispatch_job=rig.pre_dispatch_job,
            running_job=rig.running_job,
            creator_observation=obs["creator_obs"],
            parent_root_binding=obs["parent_root"],
            bootstrap_comparison=obs["boot_cmp"],
            window_id="win-1",
            window_object_identity=FakeNativeRootObject("fs:win-1"),
            window_birth_witness=WITNESS_1,
            host_observation_arm=obs["host_obs_arm"],
            worker_observation_grant=w["worker_grant"],
            worker_observation_job=w["worker_job"],
            both_roots_observation=w["both_roots_arm"],
            both_roots_actor=w["both_roots_actor"],
            both_roots_assertions=w["root_assertions"],
            checker_worker_observation=obs["worker_obs_arm"],
            checker_both_roots_observation=obs["both_roots"],
            closure_comparison_arm=obs["cmp_arm"],
            qa_receiving=obs["qa_recv"],
            compatibility_receiving=obs["compat_recv"],
            receipt_producer_binding=obs["producer_binding"],
            request_identity=obs["req_id"],
            observation_cursors=obs["cursors"],
            occurrence_handle=obs["occ_handle"],
            admission_witness=WITNESS_1,
            operation_leg=obs["op_leg"],
            raw_publication=obs["raw_pub"],
            receive_effect=w["receive_effect"],
            p5_assessment=obs["p5_ass"],
        )
        assert evaluation.row == row
        assert evaluation.status == "UNQUALIFIED"
        assert evaluation.status != "PASS"
        assert evaluation.writes_admitted is False
        assert evaluation.default_candidate_bindings_active is False
        assert evaluation.authority_accepted is True
        assert evaluation.closure_accepted is True
        assert evaluation.worker_observation_accepted is True
        assert evaluation.roots_observation_accepted is True
        assert evaluation.native_receive_accepted is True
        assert evaluation.count_eligible is False
        assert evaluation.inner_count_decision is not None
        assert evaluation.inner_count_decision.verdict == "PASS"
        assert evaluation.refusal_codes == ()
        assert evaluation.closure_disposition == "MATCH"
        assert evaluation.closure_reasons == ()
        assert dict(evaluation.native_obligations) == {f"N{i}": "UNRESOLVED" for i in range(1, 9)}
        assert evaluation.r1_status == "UNQUALIFIED"
        assert evaluation.r1i_status == "UNQUALIFIED"
        assert evaluation.d1_status == "UNQUALIFIED"
        assert evaluation.d5_status == "UNQUALIFIED"
        assert evaluation.p5_trust_posture == "UNTRUSTED"


def test_offline_consumer_join_propagates_authority_closure_and_worker_refusals():
    w = _setup_offline_supplier_world()
    rig = w["rig"]
    obs = w["obs"]

    # 1. Unconfigured WorkerObservationAdapter refuses with AUTHORITY_UNAVAILABLE -> BLOCKED
    unconfigured_worker = WorkerObservationAdapter()
    eval_worker_refused = native_consumer.evaluate_offline_native_join(
        row="R-1",
        service=rig.composition.service,
        host_join=rig.composition.host_join,
        worker_observer=unconfigured_worker,
        peer_worker=rig.peer_worker,
        peer_checker=rig.peer_checker,
        peer_run=rig.peer_run,
        peer_qa=rig.peer_qa,
        session_host=rig.session_host,
        pre_dispatch_job=rig.pre_dispatch_job,
        running_job=rig.running_job,
        creator_observation=obs["creator_obs"],
        parent_root_binding=obs["parent_root"],
        bootstrap_comparison=obs["boot_cmp"],
        window_id="win-1",
        window_object_identity=FakeNativeRootObject("fs:win-1"),
        window_birth_witness=WITNESS_1,
        host_observation_arm=obs["host_obs_arm"],
        worker_observation_grant=w["worker_grant"],
        worker_observation_job=w["worker_job"],
        both_roots_observation=w["both_roots_arm"],
        both_roots_assertions=w["root_assertions"],
        closure_comparison_arm=obs["cmp_arm"],
        qa_receiving=obs["qa_recv"],
        compatibility_receiving=obs["compat_recv"],
        receipt_producer_binding=obs["producer_binding"],
        request_identity=obs["req_id"],
        observation_cursors=obs["cursors"],
        occurrence_handle=obs["occ_handle"],
        admission_witness=WITNESS_1,
        operation_leg=obs["op_leg"],
        raw_publication=obs["raw_pub"],
        receive_effect=w["receive_effect"],
        p5_assessment=obs["p5_ass"],
    )
    assert eval_worker_refused.status == "BLOCKED"
    assert eval_worker_refused.worker_observation_accepted is False
    assert eval_worker_refused.count_eligible is False
    assert RefusalCode.AUTHORITY_UNAVAILABLE.value in eval_worker_refused.refusal_codes

    # 2. Tampered N3 closure comparison (Systems #71 bad_twin) refuses with CLOSURE_INCOMPLETE / UNKNOWN -> BLOCKED
    w2 = _setup_offline_supplier_world()
    rig2 = w2["rig"]
    obs2 = w2["obs"]
    bad_n3_world = bad_twin("N3-08", clean_world("N3-08"))
    bad_cmp = compare_loaded_source(
        bad_n3_world.reviewed,
        bad_n3_world.observed,
        expected=bad_n3_world.expected,
        verified=bad_n3_world.verified,
    )
    assert bad_cmp.disposition in ("REFUSED", "UNKNOWN", "MISMATCH")
    assert len(bad_cmp.reasons) > 0

    eval_closure_refused = native_consumer.evaluate_offline_native_join(
        row="D-1",
        service=rig2.composition.service,
        host_join=rig2.composition.host_join,
        worker_observer=w2["worker_observer"],
        peer_worker=rig2.peer_worker,
        peer_checker=rig2.peer_checker,
        peer_run=rig2.peer_run,
        peer_qa=rig2.peer_qa,
        session_host=rig2.session_host,
        pre_dispatch_job=rig2.pre_dispatch_job,
        running_job=rig2.running_job,
        creator_observation=obs2["creator_obs"],
        parent_root_binding=obs2["parent_root"],
        bootstrap_comparison=obs2["boot_cmp"],
        window_id="win-1",
        window_object_identity=FakeNativeRootObject("fs:win-1"),
        window_birth_witness=WITNESS_1,
        host_observation_arm=obs2["host_obs_arm"],
        worker_observation_grant=w2["worker_grant"],
        worker_observation_job=w2["worker_job"],
        both_roots_observation=w2["both_roots_arm"],
        both_roots_actor=w2["both_roots_actor"],
        both_roots_assertions=w2["root_assertions"],
        checker_worker_observation=obs2["worker_obs_arm"],
        checker_both_roots_observation=obs2["both_roots"],
        closure_comparison_arm=bad_cmp,
        qa_receiving=obs2["qa_recv"],
        compatibility_receiving=obs2["compat_recv"],
        receipt_producer_binding=obs2["producer_binding"],
        request_identity=obs2["req_id"],
        observation_cursors=obs2["cursors"],
        occurrence_handle=obs2["occ_handle"],
        admission_witness=WITNESS_1,
        operation_leg=obs2["op_leg"],
        raw_publication=obs2["raw_pub"],
        receive_effect=w2["receive_effect"],
        p5_assessment=obs2["p5_ass"],
    )
    assert eval_closure_refused.status == "BLOCKED"
    assert eval_closure_refused.closure_accepted is False
    assert eval_closure_refused.closure_disposition == bad_cmp.disposition
    assert len(eval_closure_refused.closure_reasons) > 0
    assert eval_closure_refused.count_eligible is False

    # 3. Collapsed single root in BothRootObservations refuses with ROOT_MISMATCH -> BLOCKED
    w3 = _setup_offline_supplier_world()
    rig3 = w3["rig"]
    obs3 = w3["obs"]
    collapsed_roots = BothRootObservations(
        publication=w3["both_roots_arm"].publication,
        host_evidence=replace(
            w3["both_roots_arm"].host_evidence,
            binding=replace(
                w3["both_roots_arm"].host_evidence.binding,
                object_identity=w3["both_roots_arm"].publication.binding.object_identity,
            ),
        ),
    )
    eval_roots_refused = native_consumer.evaluate_offline_native_join(
        row="R-1",
        service=rig3.composition.service,
        host_join=rig3.composition.host_join,
        worker_observer=w3["worker_observer"],
        peer_worker=rig3.peer_worker,
        peer_checker=rig3.peer_checker,
        peer_run=rig3.peer_run,
        peer_qa=rig3.peer_qa,
        session_host=rig3.session_host,
        pre_dispatch_job=rig3.pre_dispatch_job,
        running_job=rig3.running_job,
        creator_observation=obs3["creator_obs"],
        parent_root_binding=obs3["parent_root"],
        bootstrap_comparison=obs3["boot_cmp"],
        window_id="win-1",
        window_object_identity=FakeNativeRootObject("fs:win-1"),
        window_birth_witness=WITNESS_1,
        host_observation_arm=obs3["host_obs_arm"],
        worker_observation_grant=w3["worker_grant"],
        worker_observation_job=w3["worker_job"],
        both_roots_observation=collapsed_roots,
        both_roots_actor=w3["both_roots_actor"],
        both_roots_assertions=w3["root_assertions"],
        checker_worker_observation=obs3["worker_obs_arm"],
        checker_both_roots_observation=obs3["both_roots"],
        closure_comparison_arm=obs3["cmp_arm"],
        qa_receiving=obs3["qa_recv"],
        compatibility_receiving=obs3["compat_recv"],
        receipt_producer_binding=obs3["producer_binding"],
        request_identity=obs3["req_id"],
        observation_cursors=obs3["cursors"],
        occurrence_handle=obs3["occ_handle"],
        admission_witness=WITNESS_1,
        operation_leg=obs3["op_leg"],
        raw_publication=obs3["raw_pub"],
        receive_effect=w3["receive_effect"],
        p5_assessment=obs3["p5_ass"],
    )
    assert eval_roots_refused.status == "BLOCKED"
    assert eval_roots_refused.roots_observation_accepted is False
    assert RefusalCode.ROOT_MISMATCH.value in eval_roots_refused.refusal_codes

    # 4. Unverified host session in NativeHostJoin refuses with OBSERVATION_NOT_AUTHORIZED -> BLOCKED
    w4 = _setup_offline_supplier_world()
    rig4 = w4["rig"]
    obs4 = w4["obs"]
    unverified_session = FakeSession("session:unverified-host", rig4.peer_host)
    eval_session_refused = native_consumer.evaluate_offline_native_join(
        row="D-5",
        service=rig4.composition.service,
        host_join=rig4.composition.host_join,
        worker_observer=w4["worker_observer"],
        peer_worker=rig4.peer_worker,
        peer_checker=rig4.peer_checker,
        peer_run=rig4.peer_run,
        peer_qa=rig4.peer_qa,
        session_host=unverified_session,
        pre_dispatch_job=rig4.pre_dispatch_job,
        running_job=rig4.running_job,
        creator_observation=obs4["creator_obs"],
        parent_root_binding=obs4["parent_root"],
        bootstrap_comparison=obs4["boot_cmp"],
        window_id="win-1",
        window_object_identity=FakeNativeRootObject("fs:win-1"),
        window_birth_witness=WITNESS_1,
        host_observation_arm=obs4["host_obs_arm"],
        worker_observation_grant=w4["worker_grant"],
        worker_observation_job=w4["worker_job"],
        both_roots_observation=w4["both_roots_arm"],
        both_roots_actor=w4["both_roots_actor"],
        both_roots_assertions=w4["root_assertions"],
        checker_worker_observation=obs4["worker_obs_arm"],
        checker_both_roots_observation=obs4["both_roots"],
        closure_comparison_arm=obs4["cmp_arm"],
        qa_receiving=obs4["qa_recv"],
        compatibility_receiving=obs4["compat_recv"],
        receipt_producer_binding=obs4["producer_binding"],
        request_identity=obs4["req_id"],
        observation_cursors=obs4["cursors"],
        occurrence_handle=obs4["occ_handle"],
        admission_witness=WITNESS_1,
        operation_leg=obs4["op_leg"],
        raw_publication=obs4["raw_pub"],
        receive_effect=w4["receive_effect"],
        p5_assessment=obs4["p5_ass"],
    )
    assert eval_session_refused.status == "BLOCKED"
    assert eval_session_refused.native_receive_accepted is False
    assert RefusalCode.OBSERVATION_NOT_AUTHORIZED.value in eval_session_refused.refusal_codes


def test_offline_consumer_join_fails_loud_on_non_canonical_or_spoofed_inputs():
    w = _setup_offline_supplier_world()
    obs = w["obs"]
    sample_refusal = Refusal(
        code=RefusalCode.AUTHORITY_UNAVAILABLE,
        phase=Phase.A,
        retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        admission_state=AdmissionState.NOT_ADMITTED,
        effect_state=EffectState.NONE,
        sequence_use=SequenceUse.NOT_APPLICABLE,
    )

    with pytest.raises(ValueError, match="row must be one of"):
        native_consumer.join_offline_supplier_results(
            row="NOT-A-ROW",
            create_result=sample_refusal,
            checker_result=sample_refusal,
            request_result=sample_refusal,
            admit_result=sample_refusal,
            execute_result=sample_refusal,
            closure_comparison=obs["cmp_arm"],
            worker_observation_result=sample_refusal,
            roots_observation_result=sample_refusal,
        )

    with pytest.raises(TypeError, match="closure_comparison must be SourceClosureComparison"):
        native_consumer.join_offline_supplier_results(
            row="R-1",
            create_result=sample_refusal,
            checker_result=sample_refusal,
            request_result=sample_refusal,
            admit_result=sample_refusal,
            execute_result=sample_refusal,
            closure_comparison={"disposition": "MATCH"},  # type: ignore[arg-type]
            worker_observation_result=sample_refusal,
            roots_observation_result=sample_refusal,
        )

    with pytest.raises(TypeError, match="expected Result\\[CreateArmDecision\\]"):
        native_consumer.join_offline_supplier_results(
            row="R-1",
            create_result={"fake": True},  # type: ignore[arg-type]
            checker_result=sample_refusal,
            request_result=sample_refusal,
            admit_result=sample_refusal,
            execute_result=sample_refusal,
            closure_comparison=obs["cmp_arm"],
            worker_observation_result=sample_refusal,
            roots_observation_result=sample_refusal,
        )


def test_worker_observation_compat_profile_and_reregistration_bindings():
    cases = build_worker_observation_compat_cases()
    assert len(cases) == 12
    assert all(c.corpus == WORKER_OBSERVATION_COMPAT_CORPUS_ID for c in cases)

    for seam_name, guarantee in EXISTING_TEMPER_SEAM_GUARANTEES.items():
        assert guarantee.establishes_complete_loaded_bytes is False
        assert guarantee.establishes_authentic_process_origin is False
        refusal = refuse_existing_seam_as_complete_coverage(seam_name, boundary="B_PRE_REQUEST")
        assert isinstance(refusal, Refusal)
        assert refusal.code is RefusalCode.CLOSURE_INCOMPLETE

    assert native_consumer.SUPPLIER_ARTIFACTS["systems_71"]["commit"] == "bfef9a61727819673fcb5df2a4f179d4c184f435"
    assert native_consumer.SUPPLIER_ARTIFACTS["temper_261"]["commit"] == "6363983af8dc9013e5326c59df76a900ee0c2f47"
    assert native_consumer.SUPPLIER_ARTIFACTS["temper_262"]["commit"] == "172fd7fe3f45fc7816df4947e0c5db0b07abf7b2"
    assert native_consumer.SUPPLIER_ARTIFACTS["temper_263"]["commit"] == "4310ca7f090780c805ad3276ab1716586a512c01"
    assert (
        native_consumer.SUPPLIER_ARTIFACTS["temper_263"]["corpus_registration_sha256"]
        == "1407ca93454b73867497a95efb6a29961e8c9474c007f2758bc4a7672904a6fd"
    )
    assert (
        native_consumer.SUPPLIER_ARTIFACTS["temper_263"]["ops_760_corpus_commit"]
        == "57a1988bba9b3bef65fa161fd188fae292300b92"
    )
