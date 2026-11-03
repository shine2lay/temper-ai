"""Tests for P3 T5-N4 ``DeterministicEffectFenceProvider``."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

from p3_source_closure import N3ObservationEpoch
from temper_ai.p3_authority._providers import (
    EffectFenceProvider,
    RecordedRowOccurrence,
)
from temper_ai.p3_authority.boundary_types import (
    CurrentObservationCursors,
    OperationLeg,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    CurrentBinding,
    EffectState,
    ImmutableRequestBinding,
    NativeProcessRef,
    NativeWitness,
    OccurrenceHandle,
    Refusal,
    RefusalCode,
    RequestIdentity,
    SelectedJob,
    SequenceUse,
)
from temper_ai.p3_authority.effect_fence import (
    DeterministicEffectFenceProvider,
    EffectFenceCheck,
)
from temper_ai.p3_authority.registry import (
    ExistingSubjectRecord,
    default_effect_for_job,
)
from tests.test_architecture.ops_host_n3_cases import clean_world
from tests.test_p3_authority.test_child_registration import (
    _ProcessRef,
    make_root_obj,
    make_witness,
)
from tests.test_p3_authority.test_child_registration import (
    make_selected_job as make_registration_job,
)

_ARCHITECTURE_BIN = Path(__file__).resolve().parents[2] / "configs/architecture/bin"


def writes_admitted_on_master() -> bool:
    """The one shipped write switch (configs/architecture/bin/first_app_p3_host.py)."""
    if str(_ARCHITECTURE_BIN) not in sys.path:
        sys.path.insert(0, str(_ARCHITECTURE_BIN))
    wire = importlib.import_module("first_app_p3_host")
    return bool(wire.WRITES_ADMITTED)


def make_selected_job(selection_revision: str) -> SelectedJob:
    return make_registration_job(selection_revision=selection_revision)


def make_process_ref(registration: str) -> NativeProcessRef:
    return _ProcessRef(registration)


@dataclass(frozen=True, slots=True)
class _FakeRawRef:
    sha256: str = "a" * 64
    byte_length: int = 32


@dataclass(frozen=True, slots=True)
class _FakeCheckerBinding:
    checker: NativeProcessRef


@dataclass(frozen=True, slots=True)
class _FakeRequestIdentity:
    window_id: str = "win-n4-1"
    row: str = "row-1"
    request_id: str = "req-1"
    sequence: int = 1


@dataclass(frozen=True, slots=True)
class _FakeImmutableRequestBinding:
    request_identity: RequestIdentity
    request_raw: _FakeRawRef
    checker: _FakeCheckerBinding


@dataclass(frozen=True, slots=True)
class _FakeOccurrenceHandle:
    controller: NativeProcessRef
    witness: NativeWitness


def _build_cursors(revision: str = "rev-fence-286") -> CurrentObservationCursors:
    world = clean_world(revision)
    obs0 = world.observed.envelope.process_observations[0]
    obs2 = world.observed.envelope.process_observations[2]
    host_ep = N3ObservationEpoch(
        instance=obs0.instance,
        collector_ref=obs0.collector_ref,
        frontier=world.expected.processes[0].frontier,
    )
    worker_ep = N3ObservationEpoch(
        instance=obs2.instance,
        collector_ref=obs2.collector_ref,
        frontier=world.expected.processes[2].frontier,
    )
    return CurrentObservationCursors(
        host=(host_ep,),
        worker=(worker_ep,),
    )


def _advance_cursors(cursors: CurrentObservationCursors) -> CurrentObservationCursors:
    w0 = cursors.worker[0]
    advanced_w0 = N3ObservationEpoch(
        instance=w0.instance,
        collector_ref=w0.collector_ref,
        frontier=replace(w0.frontier, last_sequence=w0.frontier.last_sequence + 10),
    )
    return CurrentObservationCursors(
        host=cursors.host,
        worker=(advanced_w0,),
    )


def _build_occurrence_inputs(
    job: SelectedJob,
    actor: NativeProcessRef,
    req_key: str = "req-1",
    sha256: str = "a" * 64,
) -> tuple[
    RequestIdentity,
    ImmutableRequestBinding,
    CurrentBinding,
    OccurrenceHandle,
    OperationLeg,
]:
    req_id = cast(RequestIdentity, _FakeRequestIdentity(request_id=req_key))
    imm = cast(
        ImmutableRequestBinding,
        _FakeImmutableRequestBinding(
            request_identity=req_id,
            request_raw=_FakeRawRef(sha256=sha256),
            checker=_FakeCheckerBinding(checker=actor),
        ),
    )
    cur = CurrentBinding(
        selected_job=job,
        authority_revisions=job.authority_refs,
        boundary="B_PRE_REQUEST",
        intended_effect=default_effect_for_job(job, "B_PRE_REQUEST"),
    )
    occ = cast(
        OccurrenceHandle,
        _FakeOccurrenceHandle(
            controller=actor,
            witness=make_witness("wit-occ-1"),
        ),
    )
    leg = OperationLeg(
        operation=default_effect_for_job(job, "C_PRE_EXECUTION"),
        actor=actor,
        target=ExistingSubjectRecord(identity=cast(Any, make_root_obj("obj-row-1"))),
    )
    return req_id, imm, cur, occ, leg


# ---------------------------------------------------------------------------
# 1. Combined whole-feature happy path
# ---------------------------------------------------------------------------


def test_combined_happy_path_open_phase_bound_effect_fence_and_occurrence_lifecycle() -> None:
    """Combined happy path: open DeterministicEffectFenceProvider admits before_request -> before_admit -> before_execute and occurrence lifecycle."""
    assert writes_admitted_on_master() is False

    default_fence = DeterministicEffectFenceProvider()
    assert default_fence.writes_enabled is False
    assert default_fence.fence_open is False

    job = make_selected_job("rev-fence-286")
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors("rev-fence-286")
    req_id, imm, cur, occ, leg = _build_occurrence_inputs(job, actor)

    fence = DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
        require_explicit_phase_calls=True,
    )
    as_protocol: EffectFenceProvider = fence
    assert as_protocol is fence

    # Initial history is NOT_ADMITTED / NONE / UNUSED
    h0 = fence.lookup_history(req_id)
    assert h0.admission_state == AdmissionState.NOT_ADMITTED
    assert h0.effect_state == EffectState.NONE
    assert h0.sequence_use == SequenceUse.UNUSED
    assert fence.lookup_occurrence(req_id) is None

    # Phase 1: before_request
    r1 = fence.before_request(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        boundary="B_PRE_REQUEST",
        request_identity=req_id,
    )
    assert isinstance(r1, AcceptedData)
    assert isinstance(r1.data, EffectFenceCheck)
    assert r1.data.phase == "before_request"
    assert r1.data.fence_open is True
    assert r1.data.writes_enabled is True
    assert r1.data.fenced_actor == actor
    assert r1.data.frontier == cursors

    # Phase 2: before_admit + record_admission
    r2 = fence.before_admit(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        boundary="B_PRE_REQUEST",
        request_identity=req_id,
    )
    assert isinstance(r2, AcceptedData)
    assert r2.data.phase == "before_admit"

    admit_res = fence.record_admission(
        immutable_request_binding=imm,
        current_binding=cur,
        occurrence=occ,
        admission_witness=make_witness("wit-admit-1"),
    )
    assert isinstance(admit_res, AcceptedData)
    assert isinstance(admit_res.data, RecordedRowOccurrence)
    assert admit_res.data.effect_state == EffectState.ADMITTED_ONLY
    assert admit_res.data.sequence_use == SequenceUse.USED

    # Phase 3: before_execute + record_execution_leg + mark_counted
    r3 = fence.before_execute(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        boundary="C_PRE_EXECUTION",
        request_identity=req_id,
    )
    assert isinstance(r3, AcceptedData)
    assert r3.data.phase == "before_execute"

    exec_res = fence.record_execution_leg(
        request_identity=req_id,
        operation_leg=leg,
        current_binding=cur,
        effect_state=EffectState.COMPLETE,
    )
    assert isinstance(exec_res, AcceptedData)
    assert exec_res.data.effect_state == EffectState.COMPLETE
    assert exec_res.data.executed_legs == (leg,)

    counted_res = fence.mark_counted(
        request_identity=req_id,
        idempotency_identity="idem-n4-1",
        current_binding=cur,
    )
    assert isinstance(counted_res, AcceptedData)
    assert counted_res.data.counted_idempotency_key == "idem-n4-1"

    h_final = fence.lookup_history(req_id)
    assert h_final.admission_state == AdmissionState.ALREADY_ADMITTED
    assert h_final.effect_state == EffectState.COMPLETE
    assert h_final.sequence_use == SequenceUse.USED


# ---------------------------------------------------------------------------
# 2. Guard bite: closed fence with writes_enabled=False never admits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "writes_enabled,fence_open,fence_available",
    [
        (False, False, True),
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
def test_guard_bite_closed_or_disabled_fence_never_admits(
    writes_enabled: bool,
    fence_open: bool,
    fence_available: bool,
) -> None:
    """Guard bite: writes_enabled=False, fence_open=False, or fence_available=False refuses with WRITES_DISABLED everywhere."""
    job = make_selected_job("rev-fence-286")
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors("rev-fence-286")
    req_id, imm, cur, occ, leg = _build_occurrence_inputs(job, actor)

    fence = DeterministicEffectFenceProvider(
        writes_enabled=writes_enabled,
        fence_open=fence_open,
        fence_available=fence_available,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
    )

    for phase_fn in (fence.before_request, fence.before_admit, fence.before_execute):
        res = phase_fn(
            selected_job=job,
            window_id="win-n4-1",
            actor=actor,
            frontier=cursors,
            request_identity=req_id,
        )
        assert isinstance(res, Refusal)
        assert res.code == RefusalCode.WRITES_DISABLED

    admit_res = fence.record_admission(
        immutable_request_binding=imm,
        current_binding=cur,
        occurrence=occ,
        admission_witness=make_witness("wit-admit-closed"),
    )
    assert isinstance(admit_res, Refusal)
    assert admit_res.code == RefusalCode.WRITES_DISABLED
    assert fence.lookup_occurrence(req_id) is None

    exec_res = fence.record_execution_leg(
        request_identity=req_id,
        operation_leg=leg,
        current_binding=cur,
    )
    assert isinstance(exec_res, Refusal)
    assert exec_res.code == RefusalCode.WRITES_DISABLED

    count_res = fence.mark_counted(
        request_identity=req_id,
        idempotency_identity="idem-closed",
        current_binding=cur,
    )
    assert isinstance(count_res, Refusal)
    assert count_res.code == RefusalCode.WRITES_DISABLED


# ---------------------------------------------------------------------------
# 3. Refusal twins: stale frontier after wait, phase ordering, subject/selection/occurrence
# ---------------------------------------------------------------------------


def test_stale_frontier_after_wait_refuses_runtime_changed() -> None:
    """Refusal twin: stale frontier after wait between phases or before execution -> RUNTIME_CHANGED."""
    job = make_selected_job("rev-fence-286")
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors("rev-fence-286")
    newer_cursors = _advance_cursors(cursors)
    req_id, imm, cur, occ, leg = _build_occurrence_inputs(job, actor)

    fence = DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
    )
    r1 = fence.before_request(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        request_identity=req_id,
    )
    assert isinstance(r1, AcceptedData)

    # Simulate runtime frontier advancing while waiting before_admit
    fence.advance_frontier(newer_cursors)

    # Caller presenting the stale pre-wait cursors is refused with RUNTIME_CHANGED
    r2_stale = fence.before_admit(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        request_identity=req_id,
    )
    assert isinstance(r2_stale, Refusal)
    assert r2_stale.code == RefusalCode.RUNTIME_CHANGED

    # Even if caller passes newer_cursors to before_admit, predecessor phase had old cursors -> RUNTIME_CHANGED
    r2_drift = fence.before_admit(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=newer_cursors,
        request_identity=req_id,
    )
    assert isinstance(r2_drift, Refusal)
    assert r2_drift.code == RefusalCode.RUNTIME_CHANGED

    # And record_admission after frontier moved is refused with RUNTIME_CHANGED
    admit_stale = fence.record_admission(
        immutable_request_binding=imm,
        current_binding=cur,
        occurrence=occ,
        admission_witness=make_witness("wit-admit-stale"),
    )
    assert isinstance(admit_stale, Refusal)
    assert admit_stale.code == RefusalCode.RUNTIME_CHANGED

    # Explicit mark_frontier_stale also refuses record_execution_leg with RUNTIME_CHANGED
    fence2 = DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
    )
    assert isinstance(
        fence2.record_admission(
            immutable_request_binding=imm,
            current_binding=cur,
            occurrence=occ,
            admission_witness=make_witness("wit-admit-ok"),
        ),
        AcceptedData,
    )
    fence2.mark_frontier_stale()
    exec_stale = fence2.record_execution_leg(
        request_identity=req_id,
        operation_leg=leg,
        current_binding=cur,
    )
    assert isinstance(exec_stale, Refusal)
    assert exec_stale.code == RefusalCode.RUNTIME_CHANGED


def test_out_of_order_phases_or_unpermitted_phase_refuses_writes_disabled() -> None:
    """Refusal twin: calling before_admit before before_request or before_execute before before_admit -> WRITES_DISABLED."""
    job = make_selected_job("rev-fence-286")
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors("rev-fence-286")
    req_id, imm, cur, occ, _ = _build_occurrence_inputs(job, actor)

    fence = DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
        require_explicit_phase_calls=True,
    )

    # Calling before_admit before before_request -> WRITES_DISABLED
    r_admit_early = fence.before_admit(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        request_identity=req_id,
    )
    assert isinstance(r_admit_early, Refusal)
    assert r_admit_early.code == RefusalCode.WRITES_DISABLED

    # Calling record_admission when require_explicit_phase_calls=True and before_admit not completed -> WRITES_DISABLED
    admit_without_phase = fence.record_admission(
        immutable_request_binding=imm,
        current_binding=cur,
        occurrence=occ,
        admission_witness=make_witness("wit-no-phase"),
    )
    assert isinstance(admit_without_phase, Refusal)
    assert admit_without_phase.code == RefusalCode.WRITES_DISABLED

    # Complete before_request, then try before_execute skipping before_admit -> WRITES_DISABLED
    assert isinstance(
        fence.before_request(
            selected_job=job,
            window_id="win-n4-1",
            actor=actor,
            frontier=cursors,
            request_identity=req_id,
        ),
        AcceptedData,
    )
    r_exec_early = fence.before_execute(
        selected_job=job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
        request_identity=req_id,
    )
    assert isinstance(r_exec_early, Refusal)
    assert r_exec_early.code == RefusalCode.WRITES_DISABLED


def test_actor_selection_window_and_occurrence_refusal_twins() -> None:
    """Refusal twins for actor mismatch, selection mismatch, window drift, prior missing/foreign, and duplicate count."""
    job = make_selected_job("rev-fence-286")
    other_job = make_selected_job("rev-other-999")
    actor = make_process_ref("inst-worker")
    wrong_actor = make_process_ref("inst-impostor")
    cursors = _build_cursors("rev-fence-286")
    req_id, imm, cur, occ, leg = _build_occurrence_inputs(job, actor)

    with pytest.raises(ValueError, match="distributed enforcement"):
        DeterministicEffectFenceProvider(distributed_enforced=True)

    fence = DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        window_id="win-n4-1",
        fenced_actor=actor,
        expected_frontier=cursors,
    )

    # Wrong actor -> SUBJECT_MISMATCH
    res_actor = fence.before_request(
        selected_job=job,
        window_id="win-n4-1",
        actor=wrong_actor,
        frontier=cursors,
    )
    assert isinstance(res_actor, Refusal)
    assert res_actor.code == RefusalCode.SUBJECT_MISMATCH

    # Wrong selection -> SELECTION_CHANGED
    res_sel = fence.before_request(
        selected_job=other_job,
        window_id="win-n4-1",
        actor=actor,
        frontier=cursors,
    )
    assert isinstance(res_sel, Refusal)
    assert res_sel.code == RefusalCode.SELECTION_CHANGED

    # Wrong window -> RUNTIME_CHANGED
    res_win = fence.before_request(
        selected_job=job,
        window_id="win-other-999",
        actor=actor,
        frontier=cursors,
    )
    assert isinstance(res_win, Refusal)
    assert res_win.code == RefusalCode.RUNTIME_CHANGED

    # Execution leg before admission -> PRIOR_MISSING
    res_prior_missing = fence.record_execution_leg(
        request_identity=req_id,
        operation_leg=leg,
        current_binding=cur,
    )
    assert isinstance(res_prior_missing, Refusal)
    assert res_prior_missing.code == RefusalCode.PRIOR_MISSING

    # Admit, then re-admit with conflicting sha256 -> PRIOR_FOREIGN
    assert isinstance(
        fence.record_admission(
            immutable_request_binding=imm,
            current_binding=cur,
            occurrence=occ,
            admission_witness=make_witness("wit-admit-1"),
        ),
        AcceptedData,
    )
    _, imm_conflict, _, _, _ = _build_occurrence_inputs(
        job, actor, req_key="req-1", sha256="b" * 64
    )
    res_prior_foreign = fence.record_admission(
        immutable_request_binding=imm_conflict,
        current_binding=cur,
        occurrence=occ,
        admission_witness=make_witness("wit-admit-2"),
    )
    assert isinstance(res_prior_foreign, Refusal)
    assert res_prior_foreign.code == RefusalCode.PRIOR_FOREIGN

    # Execute and count once -> AcceptedData; count second time -> ALREADY_COUNTED
    assert isinstance(
        fence.record_execution_leg(
            request_identity=req_id,
            operation_leg=leg,
            current_binding=cur,
        ),
        AcceptedData,
    )
    assert isinstance(
        fence.mark_counted(
            request_identity=req_id,
            idempotency_identity="idem-1",
            current_binding=cur,
        ),
        AcceptedData,
    )
    res_dup = fence.mark_counted(
        request_identity=req_id,
        idempotency_identity="idem-1",
        current_binding=cur,
    )
    assert isinstance(res_dup, Refusal)
    assert res_dup.code == RefusalCode.ALREADY_COUNTED
