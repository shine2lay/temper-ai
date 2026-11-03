"""T4 disabled native-boundary consumer and offline conformance tests (#125 / #466).

Covers:
1. H1 Guard-off false canaries: while WRITES_ADMITTED is False, open_host, settle,
   run_row, and join_native_host_row refuse with status='BLOCKED' and reasons=[WRITES_OFF]
   before inspecting caller inputs, clocks, sleeps, filesystems, or supplier services.
2. Canonical supplier identity: temper_ai.p3_authority.contract, p3_host_contracts,
   p3_source_closure, ops_host_source_comparison, temper_ai.p3_authority.service, and
   temper_ai.p3_authority.worker_observation resolve without stubs and maintain
   one switch (first_app_p3_host.WRITES_ADMITTED=False), no native boundary installed,
   N1-N8 UNRESOLVED, R-1/R-1i/D-1/D-5 UNQUALIFIED, and P5 UNTRUSTED.
   With writes on, the host-row join still refuses every row and never runs run_row (O-466-1).
   Candidate bindings stay unset in the source: four facts checked over temper_ai/, configs/ and
   scripts/ (None defaults, untouched pass-through, no stores, P3 composition names only in the
   consumer), each with planted twins it must catch and clean twins it must pass (O-466-3,
   R-125-1). Names built at run time are not seen.
3. H2 Offline consumer join over canonical #261/#262/#263/#71 suppliers across all four
   host rows (R-1, R-1i, D-1, D-5), verifying accepted inner decisions remain
   outer status='UNQUALIFIED' and count_eligible=False while writes are off. The harness
   that drives the suppliers (_evaluate_offline_native_join) lives here, not in production,
   and takes only the exact in-memory supplier types (O-466-2).
4. Refusal and incomplete-closure propagation across authority, source closure,
   worker observation, and both-root verification, plus fail-loud input validation.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
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
from temper_ai.p3_authority import registry as authority_registry  # noqa: E402
from temper_ai.p3_authority.boundary_types import BothRootObservations  # noqa: E402
from temper_ai.p3_authority.contract import (  # noqa: E402
    AcceptedData,
    ActualCreation,
    ActualRequestAndReceipt,
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
    WindowBinding,
    compare_loaded_source,
)
from temper_ai.p3_authority.service import (  # noqa: E402
    NativeHostJoinAdapter,
    P3AuthorityService,
)
from temper_ai.p3_authority.worker_observation import (  # noqa: E402
    EXISTING_TEMPER_SEAM_GUARANTEES,
    WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    RootOwnerVsActorAssertion,
    WorkerObservationAdapter,
    build_worker_observation_compat_cases,
    refuse_existing_seam_as_complete_coverage,
)
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


def _evaluate_offline_native_join(
    *,
    row,
    service,
    host_join,
    worker_observer,
    peer_worker,
    peer_checker,
    peer_run,
    peer_qa,
    session_host,
    pre_dispatch_job,
    running_job,
    creator_observation,
    parent_root_binding,
    bootstrap_comparison,
    window_id,
    window_object_identity,
    window_birth_witness,
    host_observation_arm,
    worker_observation_grant,
    worker_observation_job=None,
    both_roots_observation,
    both_roots_actor=None,
    both_roots_assertions=(),
    checker_worker_observation=None,
    checker_both_roots_observation=None,
    closure_comparison_arm,
    qa_receiving,
    compatibility_receiving,
    receipt_producer_binding,
    request_identity,
    observation_cursors,
    occurrence_handle,
    admission_witness,
    operation_leg,
    raw_publication,
    receive_effect,
    p5_assessment,
):
    """Test-only harness: drive the in-memory #261/#262/#263/#71 suppliers, then the pure production join.

    It calls state-changing supplier methods (record_admitted_occurrence, receive), so it takes only the exact
    in-memory types the test rig builds and lives here, not in first_app_p3_native (O-466-2).
    """
    for name, value, kind in (
        ("service", service, P3AuthorityService),
        ("host_join", host_join, NativeHostJoinAdapter),
        ("worker_observer", worker_observer, WorkerObservationAdapter),
    ):
        if type(value) is not kind:
            raise TypeError(f"{name} must be exactly {kind.__name__}, got {type(value).__name__}")

    eff_worker_job = worker_observation_job if worker_observation_job is not None else running_job
    worker_obs_res = worker_observer.observe(
        worker_observation_grant,
        eff_worker_job,
        worker_observation_grant.boundary,
    )
    if isinstance(worker_obs_res, AcceptedData):
        actor_ref = (
            both_roots_actor
            if both_roots_actor is not None
            else both_roots_observation.publication.binding.actor_instance
        )
        roots_obs_res = worker_observer.root_observer.verify_both_roots(
            both_roots_observation,
            actor_instance=actor_ref,
            root_owner_assertions=both_roots_assertions,
            boundary=both_roots_observation.publication.observation_boundary,
            evidence=worker_obs_res.evidence,
        )
    else:
        roots_obs_res = worker_obs_res

    create_res = service.before_create(
        peer_worker,
        pre_dispatch_job,
        creator_observation,
        parent_root_binding,
        bootstrap_comparison,
    )

    if (
        isinstance(create_res, AcceptedData)
        and isinstance(worker_obs_res, AcceptedData)
        and isinstance(roots_obs_res, AcceptedData)
    ):
        reg = getattr(service, "registry", None) or getattr(service, "_registry", None)
        if reg is None:
            raise TypeError("service does not expose a P3AuthorityRegistry")
        cur_arm = reg.check_current(
            peer_checker,
            running_job.selection_revision,
            "A_PRE_ARM",
            authority_registry.default_effect_for_job(running_job, "A_PRE_ARM"),
        )
        if isinstance(cur_arm, AcceptedData):
            win_binding = WindowBinding(
                current=cur_arm.data,
                actual_creation=ActualCreation(
                    window_id=window_id,
                    object_identity=window_object_identity,
                    creator=create_res.data.creator,
                    birth=window_birth_witness,
                ),
            )
            checker_res = service.before_checker(
                peer_checker,
                win_binding,
                host_observation_arm,
                checker_worker_observation
                if checker_worker_observation is not None
                else worker_obs_res.data,
                checker_both_roots_observation
                if checker_both_roots_observation is not None
                else roots_obs_res.data,
                closure_comparison_arm,
                qa_receiving,
                compatibility_receiving,
                receipt_producer_binding,
            )
        else:
            checker_res = cur_arm
    elif isinstance(create_res, Refusal):
        checker_res = create_res
    elif isinstance(worker_obs_res, Refusal):
        checker_res = worker_obs_res
    else:
        assert isinstance(roots_obs_res, Refusal)
        checker_res = roots_obs_res

    if isinstance(checker_res, AcceptedData):
        req_row = getattr(request_identity, "row", row)
        req_res = service.before_request(
            peer_run,
            checker_res.data.binding,
            req_row if isinstance(req_row, str) else row,
            request_identity,
            observation_cursors,
        )
    else:
        req_res = checker_res

    admitted_binding = None
    if isinstance(req_res, AcceptedData):
        admit_res = service.before_admit(
            peer_run,
            req_res.data.binding,
            observation_cursors,
        )
        if isinstance(admit_res, AcceptedData):
            rec_occ = service.record_admitted_occurrence(
                immutable_request_binding=req_res.data.binding,
                current_binding=admit_res.data.current,
                occurrence=occurrence_handle,
                admission_witness=admission_witness,
            )
            if isinstance(rec_occ, AcceptedData):
                admitted_binding = rec_occ.data
            else:
                admit_res = rec_occ
    else:
        admit_res = req_res

    if isinstance(admit_res, AcceptedData) and admitted_binding is not None:
        exec_res = service.before_execute(
            peer_run,
            admitted_binding,
            operation_leg,
            observation_cursors,
        )
    else:
        assert isinstance(admit_res, Refusal)
        exec_res = admit_res

    recv_res = None
    count_res = None
    if isinstance(exec_res, AcceptedData) and isinstance(req_res, AcceptedData):
        occ_lookup = host_join.lookup_occurrence(session_host, request_identity)
        if isinstance(occ_lookup, AcceptedData):
            pub_ver = host_join.verify_publication(
                session_host,
                request_identity,
                raw_publication,
                occ_lookup.data,
            )
            if isinstance(pub_ver, AcceptedData):
                recv_res = host_join.receive(
                    session_host,
                    request_identity,
                    pub_ver.data,
                    receive_effect,
                )
                if isinstance(recv_res, AcceptedData):
                    count_res = service.before_count(
                        peer_qa,
                        ActualRequestAndReceipt(
                            request=req_res.data.binding,
                            publication=raw_publication,
                        ),
                        p5_assessment,
                        pub_ver.data,
                        observation_cursors,
                        qa_receiving,
                    )
            else:
                recv_res = pub_ver
        else:
            recv_res = occ_lookup

    return native_consumer.join_offline_supplier_results(
        row=row,
        create_result=create_res,
        checker_result=checker_res,
        request_result=req_res,
        admit_result=admit_res,
        execute_result=exec_res,
        closure_comparison=closure_comparison_arm,
        worker_observation_result=worker_obs_res,
        roots_observation_result=roots_obs_res,
        native_receive_result=recv_res,
        count_result=count_res,
    )


def test_disabled_entries_refuse_before_inspecting_inputs_or_clock():
    assert wire.WRITES_ADMITTED is False
    assert not hasattr(wire, "DEFAULT_CANDIDATE_BINDINGS")
    assert not hasattr(native_consumer, "WRITES_ADMITTED")
    assert not hasattr(native_consumer, "DEFAULT_CANDIDATE_BINDINGS")
    assert not hasattr(native_consumer, "evaluate_offline_native_join")

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
    assert "default_candidate_bindings_active" not in status.to_dict()
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
        evaluation = _evaluate_offline_native_join(
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
    eval_worker_refused = _evaluate_offline_native_join(
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

    eval_closure_refused = _evaluate_offline_native_join(
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
    eval_roots_refused = _evaluate_offline_native_join(
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
    eval_session_refused = _evaluate_offline_native_join(
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


# --- O-466-1: with writes on, the host-row join still refuses and never runs the plain wire ---------------


def test_writes_on_native_join_refuses_every_row_and_never_runs_the_plain_wire(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wire, "WRITES_ADMITTED", True)
    monkeypatch.setattr(wire, "run_row", unexpected_effect)
    refused = {
        "status": "BLOCKED",
        "reasons": [native_consumer.NATIVE_BOUNDARY_NOT_WIRED],
        "writer": wire.WRITER,
        "count_eligible": False,
        "native_obligations": dict(native_consumer.UNRESOLVED_NATIVE_OBLIGATIONS),
    }
    opaque = OpaqueInput()
    for row in wire.HOST_ROWS:
        for entry in (
            wire.join_native_host_row,
            native_consumer.join_native_host_row,
            native_consumer.join_admitted_host_row,
        ):
            result = asyncio.run(entry(opaque, row, clock=unexpected_effect, sleep=unexpected_effect))
            assert result == refused


def test_native_join_entries_take_no_boundary_argument():
    for entry in (
        wire.join_native_host_row,
        native_consumer.join_native_host_row,
        native_consumer.join_admitted_host_row,
    ):
        assert "native_boundary" not in inspect.signature(entry).parameters
        with pytest.raises(TypeError, match="native_boundary"):
            entry(OpaqueInput(), "R-1", native_boundary=object())


# --- O-466-2: the offline harness takes only the exact in-memory supplier types ---------------------------

_HARNESS_PLAIN_INPUTS = tuple(
    name
    for name, parameter in inspect.signature(_evaluate_offline_native_join).parameters.items()
    if parameter.default is inspect.Parameter.empty
    and name not in {"row", "service", "host_join", "worker_observer"}
)


@pytest.mark.parametrize("field", ["service", "host_join", "worker_observer"])
def test_offline_harness_refuses_anything_but_the_exact_in_memory_suppliers(field):
    w = _setup_offline_supplier_world()
    rig = w["rig"]
    suppliers = {
        "service": rig.composition.service,
        "host_join": rig.composition.host_join,
        "worker_observer": w["worker_observer"],
    }
    assert {name: type(value) for name, value in suppliers.items()} == {
        "service": P3AuthorityService,
        "host_join": NativeHostJoinAdapter,
        "worker_observer": WorkerObservationAdapter,
    }
    lookalike = type("Lookalike", (type(suppliers[field]),), {})
    suppliers[field] = lookalike.__new__(lookalike)
    with pytest.raises(TypeError, match=f"{field} must be exactly"):
        _evaluate_offline_native_join(
            row="R-1",
            **suppliers,
            **{name: OpaqueInput() for name in _HARNESS_PLAIN_INPUTS},
        )


# --- O-466-3 / R-125-1: candidate bindings stay unset in the source (facts over the source) ----

_P3_AUTHORITY_DIR = _ROOT / "temper_ai" / "p3_authority"
_RUNNER_ENTRY_POINTS = {
    ("temper_ai.runner.execute", "execute_workflow"),
    ("temper_ai.cli.run_workflow", "cmd_run_workflow"),
    ("temper_ai.cli.watch_queue", "_scan_and_dispatch"),
    ("temper_ai.cli.watch_queue", "_claim_row"),
    ("temper_ai.cli.main", "_cmd_validate"),
}
# The one module allowed to name the P3 composition types and composers: the disabled consumer, which refuses writes.
_REFERENCE_ALLOWED_FILE = "configs/architecture/bin/first_app_p3_native.py"
_PROTECTED_NAMES = frozenset(
    {
        "P3CandidateBindings",
        "P3AuthorityComposition",
        "P3AuthorityService",
        "compose_p3_authority",
        "compose_disabled_consumer_service",
    }
)
# The one place that reads bindings off the server's state and hands them to admission: routes._start_run, as
# `bindings = _candidate_bindings()`, assigned once. While nothing stores state.candidate_bindings it reads None.
_STATE_READER = ("temper_ai/api/routes.py", "_start_run")
_STATE_READER_CALL = "_candidate_bindings"
_SETATTR_CALLS = {"setattr", "__setattr__"}
_NAME_LOOKUP_CALLS = {"getattr", "hasattr"}


def _production_sources():
    for top in ("temper_ai", "configs", "scripts"):
        for path in sorted((_ROOT / top).rglob("*.py")):
            if _P3_AUTHORITY_DIR in path.parents or "__pycache__" in path.parts:
                continue
            yield path.relative_to(_ROOT).as_posix(), path.read_text(encoding="utf-8")


def _parameter_defaults(node):
    args = node.args
    positional = args.posonlyargs + args.args
    padded = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    return list(zip(positional, padded, strict=True)) + list(zip(args.kwonlyargs, args.kw_defaults, strict=True))


def _name_bindings(function, name):
    """Every node in the function that binds name: a store or delete (any assignment, loop, with, comprehension),
    an except or match capture, an import alias, or a nested definition. The parameter itself is not one."""
    found = []
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
            found.append(node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == name:
            found.append(node)
        elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name:
            found.append(node)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not function
            and node.name == name
        ):
            found.append(node)
    return found


def _callee(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def _is_literal(node, text: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == text


class _CandidateBindingFacts(ast.NodeVisitor):
    """Collect breaks of the four facts in one file, plus every function that takes candidate_bindings.

    1. A candidate_bindings parameter defaults to None.
    2. A candidate_bindings value handed on (keyword, dict key, or bindings= to submit_candidate) is the calling
       function's own untouched candidate_bindings parameter; the one exception is the state reader in
       routes._start_run.
    3. Nothing stores candidate_bindings: no attribute or subscript store, no setattr with that literal name, no
       module- or class-level value other than None, no global declaration.
    4. Only first_app_p3_native.py names the P3 composition types and composers (a name, attribute, import, or
       getattr/hasattr string).
    Not seen: names built at run time (setattr(obj, name, ...), import_module strings) and positional passes to
    functions whose candidate_bindings parameter is not keyword-only.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.violations: list[str] = []
        self.takes_bindings: set[str] = set()

    def _report(self, node, text: str) -> None:
        self.violations.append(f"{self.name}:{node.lineno}: {text}")

    def _own_function(self):
        return self.functions[-1] if self.functions else None

    def _passes_own_parameter(self, value) -> bool:
        own = self._own_function()
        return (
            isinstance(value, ast.Name)
            and value.id == "candidate_bindings"
            and own is not None
            and any(arg.arg == "candidate_bindings" for arg, _ in _parameter_defaults(own))
            and not _name_bindings(own, "candidate_bindings")
        )

    def _passes_state_reader(self, value) -> bool:
        own = self._own_function()
        if own is None or (self.name, own.name) != _STATE_READER or not isinstance(value, ast.Name):
            return False
        bindings = _name_bindings(own, value.id)
        if len(bindings) != 1:
            return False
        for node in ast.walk(own):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and node.targets[0] is bindings[0]:
                call = node.value
                return (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == _STATE_READER_CALL
                    and not call.args
                    and not call.keywords
                )
        return False

    def _reference(self, node, name: str) -> None:
        if name in _PROTECTED_NAMES and self.name != _REFERENCE_ALLOWED_FILE:
            self._report(node, f"{name} named outside first_app_p3_native.py")

    def _store(self, target, value) -> None:
        """value is the stored expression, or None when the store has no single one (loop, with, augmented)."""
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._store(element, None)
        elif isinstance(target, ast.Starred):
            self._store(target.value, None)
        elif isinstance(target, ast.Attribute) and target.attr == "candidate_bindings":
            self._report(target, f"{ast.unparse(target)} = ... stores candidate_bindings")
        elif isinstance(target, ast.Subscript) and _is_literal(target.slice, "candidate_bindings"):
            self._report(target, f"{ast.unparse(target)} = ... stores candidate_bindings")
        elif (
            isinstance(target, ast.Name)
            and target.id == "candidate_bindings"
            and not self.functions
            and not (isinstance(value, ast.Constant) and value.value is None)
        ):
            self._report(target, "a module- or class-level candidate_bindings value stores candidate_bindings")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._store(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._store(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._store(node.target, None)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._store(node.target, node.value)
        self.generic_visit(node)

    def _loop(self, node) -> None:
        self._store(node.target, None)
        self.generic_visit(node)

    visit_For = _loop
    visit_AsyncFor = _loop
    visit_comprehension = _loop

    def _with(self, node) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._store(item.optional_vars, None)
        self.generic_visit(node)

    visit_With = _with
    visit_AsyncWith = _with

    def visit_Global(self, node: ast.Global) -> None:
        if "candidate_bindings" in node.names:
            self._report(node, "global candidate_bindings stores candidate_bindings")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._reference(node, node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._reference(node, node.attr)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._reference(node, alias.name)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if _is_literal(key, "candidate_bindings") and not self._passes_own_parameter(value):
                self._report(node, f"{{'candidate_bindings': {ast.unparse(value)}}} is not its own untouched parameter")
        self.generic_visit(node)

    def _function(self, node) -> None:
        for arg, default in _parameter_defaults(node):
            if arg.arg != "candidate_bindings":
                continue
            self.takes_bindings.add(node.name)
            if not (isinstance(default, ast.Constant) and default.value is None):
                self.violations.append(f"{self.name}:{node.lineno} {node.name}: candidate_bindings must default to None")
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Call(self, node: ast.Call) -> None:
        callee = _callee(node.func)
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == "candidate_bindings" and not self._passes_own_parameter(value):
                self._report(node, f"candidate_bindings={ast.unparse(value)} is not its own untouched parameter")
            if callee != "submit_candidate":
                continue
            if keyword.arg is None:
                self._report(
                    node, f"submit_candidate(**{ast.unparse(value)}) hides bindings: is not its own untouched parameter"
                )
            elif keyword.arg == "bindings" and not (
                self._passes_own_parameter(value) or self._passes_state_reader(value)
            ):
                self._report(
                    node,
                    f"submit_candidate(bindings={ast.unparse(value)}) is not its own untouched parameter"
                    " or the state reader",
                )
        if callee in _SETATTR_CALLS and any(_is_literal(arg, "candidate_bindings") for arg in node.args):
            self._report(node, f"{callee}(..., 'candidate_bindings', ...) stores candidate_bindings")
        if callee in _NAME_LOOKUP_CALLS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._reference(node, arg.value)
        self.generic_visit(node)


def _scan(name: str, text: str) -> _CandidateBindingFacts:
    facts = _CandidateBindingFacts(name)
    facts.visit(ast.parse(text, filename=name))
    return facts


_DEFAULT_RULE = "candidate_bindings must default to None"
_PASS_THROUGH_RULE = "is not its own untouched parameter"
_STORE_RULE = "stores candidate_bindings"
_REFERENCE_RULE = "named outside first_app_p3_native.py"
_PLANTED = "temper_ai/planted.py"
_ROUTES = _STATE_READER[0]
_READER = "def _start_run():\n    bindings = _candidate_bindings()\n"
# Each twin breaks one fact; the check must report it under that fact's rule, and only once.
_PLANTED_TWINS = {
    "non-None default": (_PLANTED, "def run(*, candidate_bindings=object()):\n    pass\n", _DEFAULT_RULE),
    "required parameter": (_PLANTED, "def run(candidate_bindings):\n    pass\n", _DEFAULT_RULE),
    "built value passed": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n    go(candidate_bindings=make())\n",
        _PASS_THROUGH_RULE,
    ),
    "name that is not a parameter": (
        _PLANTED,
        "def run():\n    go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "parameter replaced first": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n    candidate_bindings = make()\n    go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "parameter rebound by a loop": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n"
        "    for candidate_bindings in [make()]:\n"
        "        go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "module-level call": (_PLANTED, "go(candidate_bindings=BINDINGS)\n", _PASS_THROUGH_RULE),
    "dict key with a built value": (
        _PLANTED,
        "def run():\n    execute_workflow(**{'candidate_bindings': make()})\n",
        _PASS_THROUGH_RULE,
    ),
    "built bindings to submit_candidate": (
        _PLANTED,
        "def start():\n    submit_candidate(bindings=make())\n",
        _PASS_THROUGH_RULE,
    ),
    "splat into submit_candidate": (_PLANTED, "def start(kw):\n    submit_candidate(**kw)\n", _PASS_THROUGH_RULE),
    "state reader outside routes": (
        _PLANTED,
        _READER + "    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value replaced": (
        _ROUTES,
        _READER + "    bindings = make()\n    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "attribute store": (_PLANTED, "def boot(state):\n    state.candidate_bindings = make()\n", _STORE_RULE),
    "setattr store": (_PLANTED, "def boot(state):\n    setattr(state, 'candidate_bindings', make())\n", _STORE_RULE),
    "object.__setattr__ store": (
        _PLANTED,
        "def boot(state):\n    object.__setattr__(state, 'candidate_bindings', make())\n",
        _STORE_RULE,
    ),
    "subscript store": (_PLANTED, "def boot(state):\n    vars(state)['candidate_bindings'] = make()\n", _STORE_RULE),
    "class field with a value": (_PLANTED, "class AppState:\n    candidate_bindings: object = make()\n", _STORE_RULE),
    "module-level value": (_PLANTED, "candidate_bindings = make()\n", _STORE_RULE),
    "global store": (
        _PLANTED,
        "def boot():\n    global candidate_bindings\n    candidate_bindings = make()\n",
        _STORE_RULE,
    ),
    "composition built": (_PLANTED, "def boot():\n    return compose_p3_authority()\n", _REFERENCE_RULE),
    "disabled composer called": (
        _PLANTED,
        "import first_app_p3_native as n\nn.compose_disabled_consumer_service()\n",
        _REFERENCE_RULE,
    ),
    "composer imported under another name": (
        _PLANTED,
        "from temper_ai.p3_authority.service import compose_p3_authority as build\n",
        _REFERENCE_RULE,
    ),
    "composer reached through getattr": (
        _PLANTED,
        "def boot(module):\n    return getattr(module, 'compose_p3_authority')()\n",
        _REFERENCE_RULE,
    ),
    "bindings type named": (_PLANTED, "def boot():\n    return P3CandidateBindings()\n", _REFERENCE_RULE),
    "service type named": (_PLANTED, "def boot(x):\n    return isinstance(x, P3AuthorityService)\n", _REFERENCE_RULE),
}
# Each clean twin keeps every fact; the check must report nothing.
_CLEAN_TWINS = {
    "keyword pass-through": (
        _PLANTED,
        "def outer(*, candidate_bindings=None):\n"
        "    return inner(candidate_bindings=candidate_bindings)\n"
        "async def inner(*, candidate_bindings=None):\n"
        "    return candidate_bindings is None\n",
    ),
    "dict key pass-through": (
        _PLANTED,
        "def outer(*, candidate_bindings=None):\n    return run(**{'candidate_bindings': candidate_bindings})\n",
    ),
    "state reader in routes": (
        _ROUTES,
        "def _candidate_bindings():\n"
        "    return vars(_state()).get('candidate_bindings')\n" + _READER + "    submit_candidate(bindings=bindings)\n",
    ),
    "class field left None": (_PLANTED, "class AppState:\n    candidate_bindings: object = None\n"),
    "composer named in its own module": (
        _REFERENCE_ALLOWED_FILE,
        "from temper_ai.p3_authority.service import P3AuthorityService, compose_p3_authority\n"
        "def compose(**kwargs):\n    return compose_p3_authority(**kwargs)\n",
    ),
}


@pytest.mark.parametrize("twin", sorted(_PLANTED_TWINS))
def test_candidate_binding_fact_checks_catch_each_planted_twin(twin):
    path, source, rule = _PLANTED_TWINS[twin]
    violations = _scan(path, source).violations
    assert len(violations) == 1, violations
    assert rule in violations[0]


@pytest.mark.parametrize("twin", sorted(_CLEAN_TWINS))
def test_candidate_binding_fact_checks_pass_each_clean_twin(twin):
    path, source = _CLEAN_TWINS[twin]
    assert _scan(path, source).violations == []


def test_candidate_binding_fact_checks_list_the_functions_that_take_bindings():
    facts = _scan(_PLANTED, _CLEAN_TWINS["keyword pass-through"][1])
    assert facts.takes_bindings == {"outer", "inner"}


def test_production_tree_breaks_no_candidate_binding_fact():
    violations: list[str] = []
    takes_bindings: set[tuple[str, str]] = set()
    scanned = 0
    for name, text in _production_sources():
        facts = _scan(name, text)
        scanned += 1
        violations += facts.violations
        module = name.removesuffix(".py").replace("/", ".")
        takes_bindings |= {(module, function) for function in facts.takes_bindings}
    assert scanned > 100
    assert violations == []
    assert _RUNNER_ENTRY_POINTS <= takes_bindings
    for module, function in sorted(_RUNNER_ENTRY_POINTS):
        parameter = inspect.signature(getattr(importlib.import_module(module), function)).parameters[
            "candidate_bindings"
        ]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None
