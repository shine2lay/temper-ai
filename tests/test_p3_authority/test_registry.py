"""Unit and boundary tests for ``temper_ai.p3_authority.registry`` (#262).

Covers:
1. Combined happy path across ``for_submit``, ``for_run``, ``check_current``,
   and ``bind_created`` with independent ``SelectionSnapshot``, ``IssuerVerifier``,
   and ``PeerVerifierProtocol`` test doubles.
2. Separation of publisher/admin (``InMemorySelectionPublisher``) from read-only
   ``SelectionSnapshotProvider`` and ``P3AuthorityRegistry``.
3. Same-boundary negative twins for missing/ambiguous/foreign/changed selection,
   changed dispatch, unsupported route, unverified/revoked/expired/unbound issuer
   authority, subject/actor/operation/condition mismatch, unverified/malformed peer,
   window binding boundary/conflict refusals, prior request history propagation,
   and absent-provider fail-closed defaults.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from temper_ai.config.admission_contract import DispatchIdentity
from temper_ai.p3_authority.boundary_types import (
    ActualCreation,
    CurrentBinding,
    WindowBinding,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    ConditionRef,
    EffectState,
    Phase,
    Refusal,
    RefusalCode,
    RequestIdentity,
    RetryKind,
    SelectedOperation,
    SequenceUse,
    TrustedInstant,
)
from temper_ai.p3_authority.registry import (
    AuthorityRegistryService,
    ExistingSubjectRecord,
    FutureSubjectRecord,
    ImmutableReferenceRecord,
    InMemoryIssuerVerifier,
    InMemoryPeerVerifier,
    InMemorySelectionPublisher,
    InMemorySelectionSnapshotProvider,
    PriorRequestHistory,
    SelectionSnapshot,
    boundary_to_phase,
    default_effect_for_job,
)
from tests.test_p3_authority._composition_fixtures import (
    AUTHORITY_REF_1,
    AUTHORITY_REF_2,
    CONDITION_1,
    DISPATCH_1,
    NATIVE_SELECTION_1,
    NATIVE_SELECTION_RUN,
    PROCESS_HOST,
    PROCESS_RUN,
    PROCESS_SUBMIT,
    RAW_REF_REQUEST,
    TRUSTED_NOW,
    FakeNativeRootObject,
    FakePeer,
    FakeProcessRef,
    FakeWitness,
    make_populated_test_rig,
    make_pre_dispatch_job,
    make_running_job,
    make_verified_authority,
)


def test_combined_registry_selection_authority_and_window_binding_happy_path() -> None:
    rig = make_populated_test_rig()
    registry = rig.composition.registry

    # 1. Pre-dispatch submit selection
    res_submit = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_submit, AcceptedData)
    assert res_submit.data == rig.pre_dispatch_job
    assert res_submit.evidence.selected_job == rig.pre_dispatch_job
    assert res_submit.evidence.phase is Phase.A
    assert res_submit.evidence.boundary == "A_PRE_CREATE"
    assert res_submit.evidence.window is None
    assert res_submit.evidence.receiving == ()

    # 2. Running job selection by exact DispatchIdentity
    res_run = registry.for_run(
        rig.peer_run,
        DISPATCH_1.execution_uuid,
        DISPATCH_1,
    )
    assert isinstance(res_run, AcceptedData)
    assert res_run.data == rig.running_job
    assert res_run.evidence.selected_job == rig.running_job
    assert res_run.evidence.phase is Phase.A
    assert res_run.evidence.boundary == "A_PRE_ARM"

    # 3. Current binding check at A_PRE_ARM and B_PRE_REQUEST
    arm_op = default_effect_for_job(rig.running_job, "A_PRE_ARM")
    res_current_a = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        arm_op,
    )
    assert isinstance(res_current_a, AcceptedData)
    assert isinstance(res_current_a.data, CurrentBinding)
    assert res_current_a.data.selected_job == rig.running_job
    assert res_current_a.data.boundary == "A_PRE_ARM"
    assert res_current_a.data.intended_effect == arm_op

    req_id = RequestIdentity(
        selection=NATIVE_SELECTION_RUN,
        window_id="win-1",
        writer="writer-1",
        row="row-1",
        operation="mutate",
        request_id="req-1",
        sequence=1,
        request_raw_ref=RAW_REF_REQUEST,
        binding_ref=RAW_REF_REQUEST,
    )
    req_op = default_effect_for_job(rig.running_job, "B_PRE_REQUEST")
    res_current_b = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "B_PRE_REQUEST",
        req_op,
        request_identity=req_id,
    )
    assert isinstance(res_current_b, AcceptedData)
    assert res_current_b.evidence.phase is Phase.B
    assert res_current_b.evidence.boundary == "B_PRE_REQUEST"

    # 4. Bind created execution window
    creation = ActualCreation(
        window_id="win-1",
        creator=PROCESS_SUBMIT,
        object_identity=FakeNativeRootObject("obj:win-1"),
        birth=FakeWitness("wit:created-1"),
    )
    res_window = registry.bind_created(
        rig.peer_run,
        res_current_a.data,
        creation,
    )
    assert isinstance(res_window, AcceptedData)
    assert isinstance(res_window.data, WindowBinding)
    assert res_window.data.actual_creation == creation
    assert res_window.evidence.window == ExistingSubjectRecord(
        identity=creation.object_identity
    )
    assert PROCESS_SUBMIT in res_window.evidence.processes
    assert PROCESS_RUN in res_window.evidence.processes

    # Idempotent repeat of exact same window creation succeeds
    res_window_repeat = registry.bind_created(
        rig.peer_run,
        res_current_a.data,
        creation,
    )
    assert isinstance(res_window_repeat, AcceptedData)
    assert res_window_repeat.data == res_window.data


def test_publisher_and_reader_interfaces_remain_strictly_separated() -> None:
    publisher = InMemorySelectionPublisher()
    reader = publisher.reader()
    assert isinstance(reader, InMemorySelectionSnapshotProvider)
    assert not hasattr(reader, "publish_snapshot")
    assert not hasattr(AuthorityRegistryService, "publish_snapshot")
    assert reader.read_snapshot() is None

    with pytest.raises(TypeError, match="SelectionSnapshot"):
        publisher.publish_snapshot("not-a-snapshot")  # type: ignore[arg-type]


def test_registry_fails_closed_when_providers_absent() -> None:
    empty_registry = AuthorityRegistryService()
    peer = FakePeer("peer:1", PROCESS_SUBMIT)

    res_submit = empty_registry.for_submit(peer, "designated_v1")
    assert isinstance(res_submit, Refusal)
    assert res_submit.code is RefusalCode.AUTHORITY_UNAVAILABLE
    assert res_submit.phase is Phase.A
    assert res_submit.retry_kind is RetryKind.SAME_BOUNDARY_AFTER_REPAIR
    assert res_submit.counted is False

    res_run = empty_registry.for_run(peer, DISPATCH_1.execution_uuid, DISPATCH_1)
    assert isinstance(res_run, Refusal)
    assert res_run.code is RefusalCode.AUTHORITY_UNAVAILABLE

    op = SelectedOperation(domain="A_PRE_ARM", operation="A_PRE_ARM", revision="op-1")
    res_check = empty_registry.check_current(peer, "sel-rev-1", "A_PRE_ARM", op)
    assert isinstance(res_check, Refusal)
    assert res_check.code is RefusalCode.AUTHORITY_UNAVAILABLE

    # Peer verifier present, but snapshot_provider / issuer_verifier absent -> AUTHORITY_UNAVAILABLE
    peer_only_registry = AuthorityRegistryService(
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
    )
    res_no_snap = peer_only_registry.for_submit(peer, "designated_v1")
    assert isinstance(res_no_snap, Refusal)
    assert res_no_snap.code is RefusalCode.AUTHORITY_UNAVAILABLE

    # Publisher with None snapshot -> AUTHORITY_UNAVAILABLE
    pub = InMemorySelectionPublisher()
    unpopulated_registry = AuthorityRegistryService(
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
        snapshot_provider=pub.reader(),
        issuer_verifier=InMemoryIssuerVerifier(),
    )
    res_none_snap = unpopulated_registry.for_submit(peer, "designated_v1")
    assert isinstance(res_none_snap, Refusal)
    assert res_none_snap.code is RefusalCode.AUTHORITY_UNAVAILABLE


def test_peer_verification_and_malformed_peer_twins() -> None:
    rig = make_populated_test_rig()
    registry = rig.composition.registry

    # Unregistered peer -> PEER_UNVERIFIED
    unregistered = FakePeer("peer:unknown", FakeProcessRef("proc:unknown"))
    res_unreg = registry.for_submit(unregistered, "designated_v1")
    assert isinstance(res_unreg, Refusal)
    assert res_unreg.code is RefusalCode.PEER_UNVERIFIED
    assert res_unreg.retry_kind is RetryKind.NOT_APPLICABLE

    # Same peer_registration but forged process_registration -> PEER_UNVERIFIED
    forged_proc = FakePeer(
        rig.peer_submit.peer_registration,
        FakeProcessRef("proc:forged"),
    )
    res_forged = registry.for_submit(forged_proc, "designated_v1")
    assert isinstance(res_forged, Refusal)
    assert res_forged.code is RefusalCode.PEER_UNVERIFIED

    # Malformed peer missing attributes -> PEER_UNVERIFIED
    res_malformed = registry.for_submit(object(), "designated_v1")  # type: ignore[arg-type]
    assert isinstance(res_malformed, Refusal)
    assert res_malformed.code is RefusalCode.PEER_UNVERIFIED

    # Revoking a peer causes subsequent calls to refuse with PEER_UNVERIFIED
    rig.peer_verifier.revoke_peer(rig.peer_submit)
    res_revoked_peer = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_revoked_peer, Refusal)
    assert res_revoked_peer.code is RefusalCode.PEER_UNVERIFIED
    rig.peer_verifier.register_peer(rig.peer_submit)


def test_selection_missing_ambiguous_foreign_changed_and_dispatch_twins() -> None:
    rig = make_populated_test_rig()
    registry = rig.composition.registry

    # Empty or non-string workflow name -> SELECTION_MISSING
    assert (
        registry.for_submit(rig.peer_submit, "").code
        is RefusalCode.SELECTION_MISSING  # type: ignore[union-attr]
    )
    assert (
        registry.for_submit(rig.peer_submit, "unknown_wf").code
        is RefusalCode.SELECTION_MISSING  # type: ignore[union-attr]
    )

    # Ambiguous pre-dispatch job for same workflow -> SELECTION_AMBIGUOUS
    dup_pre = make_pre_dispatch_job(
        designated_workflow="designated_v1",
        selection_revision="sel-rev-dup",
    )
    ambig_snap = SelectionSnapshot(
        snapshot_revision="snap-ambig",
        jobs=(rig.pre_dispatch_job, dup_pre),
        verified_at=TRUSTED_NOW,
    )
    rig.publisher.publish_snapshot(ambig_snap)
    res_ambig = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_ambig, Refusal)
    assert res_ambig.code is RefusalCode.SELECTION_AMBIGUOUS
    assert res_ambig.retry_kind is RetryKind.NEW_BINDING_REQUIRED

    # Ambiguous running job for same DispatchIdentity -> SELECTION_AMBIGUOUS
    dup_run = make_running_job(
        dispatch=DISPATCH_1,
        selection_revision="sel-rev-run-dup",
    )
    ambig_run_snap = SelectionSnapshot(
        snapshot_revision="snap-ambig-run",
        jobs=(rig.running_job, dup_run),
        verified_at=TRUSTED_NOW,
    )
    rig.publisher.publish_snapshot(ambig_run_snap)
    res_ambig_run = registry.for_run(
        rig.peer_run,
        DISPATCH_1.execution_uuid,
        DISPATCH_1,
    )
    assert isinstance(res_ambig_run, Refusal)
    assert res_ambig_run.code is RefusalCode.SELECTION_AMBIGUOUS

    # Restore valid snapshot
    rig.publisher.publish_snapshot(rig.snapshot)

    # Dispatch mismatch: execution_uuid != dispatch_identity.execution_uuid -> DISPATCH_CHANGED
    res_mismatch_exec = registry.for_run(
        rig.peer_run,
        "99999999-9999-4999-8999-999999999999",
        DISPATCH_1,
    )
    assert isinstance(res_mismatch_exec, Refusal)
    assert res_mismatch_exec.code is RefusalCode.DISPATCH_CHANGED

    # Same execution_uuid but different nonce/attempt -> DISPATCH_CHANGED
    wrong_nonce = DispatchIdentity(
        execution_uuid=DISPATCH_1.execution_uuid,
        dispatch_nonce="77777777-7777-4777-8777-777777777777",
        running_attempt=9,
    )
    res_wrong_nonce = registry.for_run(
        rig.peer_run,
        DISPATCH_1.execution_uuid,
        wrong_nonce,
    )
    assert isinstance(res_wrong_nonce, Refusal)
    assert res_wrong_nonce.code is RefusalCode.DISPATCH_CHANGED

    # Unknown execution_uuid -> SELECTION_MISSING
    unknown_disp = DispatchIdentity(
        execution_uuid="88888888-8888-4888-8888-888888888888",
        dispatch_nonce="77777777-7777-4777-8777-777777777777",
        running_attempt=1,
    )
    res_unknown_run = registry.for_run(
        rig.peer_run,
        unknown_disp.execution_uuid,
        unknown_disp,
    )
    assert isinstance(res_unknown_run, Refusal)
    assert res_unknown_run.code is RefusalCode.SELECTION_MISSING

    # check_current with unknown selection_revision -> SELECTION_CHANGED
    op = default_effect_for_job(rig.running_job, "B_PRE_REQUEST")
    res_changed = registry.check_current(
        rig.peer_run,
        "sel-rev-superseded",
        "B_PRE_REQUEST",
        op,
    )
    assert isinstance(res_changed, Refusal)
    assert res_changed.code is RefusalCode.SELECTION_CHANGED
    assert res_changed.phase is Phase.B

    # check_current with foreign RequestIdentity.selection -> SELECTION_FOREIGN
    foreign_req = RequestIdentity(
        selection=NATIVE_SELECTION_1,  # sel-rev-1 != sel-rev-run-1
        window_id="win-1",
        writer="writer-1",
        row="row-1",
        operation="mutate",
        request_id="req-foreign",
        sequence=1,
        request_raw_ref=RAW_REF_REQUEST,
        binding_ref=RAW_REF_REQUEST,
    )
    res_foreign = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "B_PRE_REQUEST",
        op,
        request_identity=foreign_req,
    )
    assert isinstance(res_foreign, Refusal)
    assert res_foreign.code is RefusalCode.SELECTION_FOREIGN


def test_issuer_revoked_expired_unverified_unbound_and_conditions_twins() -> None:
    rig = make_populated_test_rig()
    registry = rig.composition.registry

    # Revoked authority -> AUTHORITY_REVOKED
    rig.issuer_verifier.set_revoked(AUTHORITY_REF_1, True)
    res_rev = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_rev, Refusal)
    assert res_rev.code is RefusalCode.AUTHORITY_REVOKED
    assert res_rev.retry_kind is RetryKind.NEW_BINDING_REQUIRED
    rig.issuer_verifier.set_revoked(AUTHORITY_REF_1, False)

    # Expired authority -> AUTHORITY_EXPIRED
    rig.issuer_verifier.set_expired(AUTHORITY_REF_1, True)
    res_exp = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_exp, Refusal)
    assert res_exp.code is RefusalCode.AUTHORITY_EXPIRED
    rig.issuer_verifier.set_expired(AUTHORITY_REF_1, False)

    # Clock reading outside [not_before, expires_at] -> AUTHORITY_EXPIRED
    late_snap = SelectionSnapshot(
        snapshot_revision="snap-late",
        jobs=rig.snapshot.jobs,
        verified_at=TrustedInstant(
            clock_domain="monotonic:host-test-1",
            reading="99999",
            witness=FakeWitness("wit:late"),
        ),
    )
    rig.publisher.publish_snapshot(late_snap)
    res_late = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_late, Refusal)
    assert res_late.code is RefusalCode.AUTHORITY_EXPIRED
    rig.publisher.publish_snapshot(rig.snapshot)

    # Unregistered AuthorityRef -> ISSUER_UNVERIFIED
    unver_job = replace(rig.pre_dispatch_job, authority_refs=(AUTHORITY_REF_2,))
    rig.publisher.publish_snapshot(
        SelectionSnapshot(
            snapshot_revision="snap-unver",
            jobs=(unver_job,),
            verified_at=TRUSTED_NOW,
        )
    )
    res_unver = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_unver, Refusal)
    assert res_unver.code is RefusalCode.ISSUER_UNVERIFIED

    # Unmet ConditionRef -> CONDITIONS_UNMET
    extra_cond = ConditionRef(
        authority="issuer:policy-test-1",
        condition_id="tier:strict",
        revision="cond-rev-2",
    )
    cond_job = make_pre_dispatch_job(
        conditions=frozenset({CONDITION_1, extra_cond}),
    )
    cond_snap = SelectionSnapshot(
        snapshot_revision="snap-cond",
        jobs=(cond_job,),
        verified_at=TRUSTED_NOW,
    )
    subj = cond_snap.subject_for(cond_job)
    for ref in (cond_job.selector_issuer, *cond_job.authority_refs):
        rig.issuer_verifier.register_authority(
            ref,
            make_verified_authority(
                authority=ref,
                subject=subj,
                conditions=frozenset({CONDITION_1}),  # missing extra_cond
            ),
            job=cond_job,
        )
    rig.publisher.publish_snapshot(cond_snap)
    res_cond = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_cond, Refusal)
    assert res_cond.code is RefusalCode.CONDITIONS_UNMET

    # Actor process not in VerifiedAuthority.actors -> SUBJECT_MISMATCH
    for ref in (cond_job.selector_issuer, *cond_job.authority_refs):
        rig.issuer_verifier.register_authority(
            ref,
            make_verified_authority(
                authority=ref,
                subject=subj,
                actors=frozenset({PROCESS_HOST}),  # peer_submit is PROCESS_SUBMIT
                conditions=frozenset({CONDITION_1, extra_cond}),
            ),
            job=cond_job,
        )
    res_actor = registry.for_submit(rig.peer_submit, "designated_v1")
    assert isinstance(res_actor, Refusal)
    assert res_actor.code is RefusalCode.SUBJECT_MISMATCH


def test_bind_created_and_scope_and_prior_history_twins() -> None:
    rig = make_populated_test_rig()
    registry = rig.composition.registry

    # Unauthorized operation in check_current -> SCOPE_MISMATCH
    unauth_op = SelectedOperation(
        domain="p3.forbidden",
        operation="delete_all",
        revision="op-99",
    )
    res_scope = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "C_PRE_REQUEST",
        unauth_op,
    )
    assert isinstance(res_scope, Refusal)
    assert res_scope.code is RefusalCode.SCOPE_MISMATCH
    assert res_scope.phase is Phase.B

    # Prior request history propagation on refusal
    req_id = RequestIdentity(
        selection=NATIVE_SELECTION_RUN,
        window_id="win-hist-1",
        writer="writer-1",
        row="row-1",
        operation="mutate",
        request_id="req-hist-1",
        sequence=7,
        request_raw_ref=RAW_REF_REQUEST,
        binding_ref=RAW_REF_REQUEST,
    )
    rig.request_history_provider.record_history(
        req_id,
        PriorRequestHistory(
            admission_state=AdmissionState.ALREADY_ADMITTED,
            effect_state=EffectState.UNCERTAIN,
            sequence_use=SequenceUse.USED,
        ),
    )
    res_with_hist = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "C_PRE_EXECUTION",
        unauth_op,
        request_identity=req_id,
    )
    assert isinstance(res_with_hist, Refusal)
    assert res_with_hist.code is RefusalCode.SCOPE_MISMATCH
    assert res_with_hist.admission_state is AdmissionState.ALREADY_ADMITTED
    assert res_with_hist.effect_state is EffectState.UNCERTAIN
    assert res_with_hist.sequence_use is SequenceUse.USED

    # bind_created with non-Phase-A CurrentBinding -> WINDOW_INELIGIBLE
    b_op = default_effect_for_job(rig.running_job, "B_PRE_REQUEST")
    b_binding = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "B_PRE_REQUEST",
        b_op,
    )
    assert isinstance(b_binding, AcceptedData)
    creation = ActualCreation(
        window_id="win-bad-boundary",
        creator=PROCESS_SUBMIT,
        object_identity=FakeNativeRootObject("obj:win-bad"),
        birth=FakeWitness("wit:bad"),
    )
    res_bad_win = registry.bind_created(rig.peer_run, b_binding.data, creation)
    assert isinstance(res_bad_win, Refusal)
    assert res_bad_win.code is RefusalCode.WINDOW_INELIGIBLE

    # Conflicting second ActualCreation for same window_id -> WINDOW_INELIGIBLE
    a_op = default_effect_for_job(rig.running_job, "A_PRE_ARM")
    a_binding = registry.check_current(
        rig.peer_run,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        a_op,
    )
    assert isinstance(a_binding, AcceptedData)
    creation_1 = ActualCreation(
        window_id="win-conflict",
        creator=PROCESS_SUBMIT,
        object_identity=FakeNativeRootObject("obj:win-c1"),
        birth=FakeWitness("wit:c1"),
    )
    creation_2 = ActualCreation(
        window_id="win-conflict",
        creator=PROCESS_SUBMIT,
        object_identity=FakeNativeRootObject("obj:win-c2"),
        birth=FakeWitness("wit:c2"),
    )
    assert isinstance(
        registry.bind_created(rig.peer_run, a_binding.data, creation_1),
        AcceptedData,
    )
    res_conflict = registry.bind_created(rig.peer_run, a_binding.data, creation_2)
    assert isinstance(res_conflict, Refusal)
    assert res_conflict.code is RefusalCode.WINDOW_INELIGIBLE


def test_boundary_to_phase_and_record_validation_guards() -> None:
    assert boundary_to_phase("A_PRE_CREATE") is Phase.A
    assert boundary_to_phase("A_PRE_ARM") is Phase.A
    assert boundary_to_phase("B_PRE_REQUEST") is Phase.B
    assert boundary_to_phase("C_PRE_REQUEST") is Phase.B
    assert boundary_to_phase("C_PRE_EXECUTION") is Phase.B
    assert boundary_to_phase("C_BEFORE_COUNT") is Phase.C
    with pytest.raises(ValueError, match="unsupported boundary"):
        boundary_to_phase("INVALID")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="ImmutableReferenceRecord"):
        ImmutableReferenceRecord(path="", digest="a", length=1, revision="r")

    with pytest.raises(ValueError, match="selected_scope_reference"):
        FutureSubjectRecord(selected_scope_reference="")

    with pytest.raises(TypeError, match="ExistingSubjectRecord"):
        ExistingSubjectRecord(identity=object())  # type: ignore[arg-type]
