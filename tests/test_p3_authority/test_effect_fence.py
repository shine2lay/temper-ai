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
    Result,
    SelectedJob,
    SequenceUse,
)
from temper_ai.p3_authority.effect_fence import (
    DeterministicEffectFenceProvider,
    EffectFenceCheck,
    EffectFencePhase,
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
WINDOW = "win-n4-1"
REVISION = "rev-fence-286"


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


@dataclass(frozen=True)
class _ProcessRefAtEpoch:
    """The same registration seen at another start epoch: equal name, other process."""

    process_registration: str
    epoch: str


@dataclass(frozen=True, slots=True)
class _FakeRawRef:
    sha256: str = "a" * 64
    byte_length: int = 32


@dataclass(frozen=True, slots=True)
class _FakeCheckerBinding:
    checker: NativeProcessRef


@dataclass(frozen=True, slots=True)
class _FakeRequestIdentity:
    window_id: str = WINDOW
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


def _build_cursors(revision: str = REVISION) -> CurrentObservationCursors:
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


@dataclass
class FenceWorld:
    """One open fence bound to one job, actor and frontier, plus one request's inputs."""

    job: SelectedJob
    actor: NativeProcessRef
    cursors: CurrentObservationCursors
    fence: DeterministicEffectFenceProvider
    req_id: RequestIdentity
    imm: ImmutableRequestBinding
    cur: CurrentBinding
    occ: OccurrenceHandle
    leg: OperationLeg

    def phase(
        self,
        phase: EffectFencePhase,
        *,
        req_id: RequestIdentity | None = None,
        job: SelectedJob | None = None,
        actor: NativeProcessRef | None = None,
        frontier: CurrentObservationCursors | None = None,
        window_id: str = WINDOW,
    ) -> Result[EffectFenceCheck]:
        return self.fence.verify_fence(
            phase=phase,
            selected_job=job if job is not None else self.job,
            request_identity=req_id if req_id is not None else self.req_id,
            actor=actor if actor is not None else self.actor,
            frontier=frontier if frontier is not None else self.cursors,
            window_id=window_id,
            boundary="C_PRE_EXECUTION"
            if phase == "before_execute"
            else "B_PRE_REQUEST",
        )

    def admit(
        self, *, cur: CurrentBinding | None = None
    ) -> Result[RecordedRowOccurrence]:
        return self.fence.record_admission(
            immutable_request_binding=self.imm,
            current_binding=cur if cur is not None else self.cur,
            occurrence=self.occ,
            admission_witness=make_witness("wit-admit-1"),
        )

    def execute(
        self, *, cur: CurrentBinding | None = None
    ) -> Result[RecordedRowOccurrence]:
        return self.fence.record_execution_leg(
            request_identity=self.req_id,
            operation_leg=self.leg,
            current_binding=cur if cur is not None else self.cur,
        )

    def count(self, key: str = "idem-n4-1") -> Result[RecordedRowOccurrence]:
        return self.fence.mark_counted(
            request_identity=self.req_id,
            idempotency_identity=key,
            current_binding=self.cur,
        )


def open_world(**fence_overrides: Any) -> FenceWorld:
    job = make_selected_job(REVISION)
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors(REVISION)
    req_id, imm, cur, occ, leg = _build_occurrence_inputs(job, actor)
    settings: dict[str, Any] = {
        "writes_enabled": True,
        "fence_open": True,
        "selected_job": job,
        "window_id": WINDOW,
        "fenced_actor": actor,
        "expected_frontier": cursors,
    }
    settings.update(fence_overrides)
    fence = DeterministicEffectFenceProvider(**settings)
    return FenceWorld(job, actor, cursors, fence, req_id, imm, cur, occ, leg)


def refusal_code(result: object) -> RefusalCode | None:
    return result.code if isinstance(result, Refusal) else None


# ---------------------------------------------------------------------------
# 1. Combined whole-feature happy path
# ---------------------------------------------------------------------------


def test_combined_happy_path_open_phase_bound_effect_fence_and_occurrence_lifecycle() -> (
    None
):
    """One request walks before_request -> before_admit -> before_execute through an open fence."""
    assert writes_admitted_on_master() is False

    default_fence = DeterministicEffectFenceProvider()
    assert default_fence.writes_enabled is False
    assert default_fence.fence_open is False

    w = open_world()
    as_protocol: EffectFenceProvider = w.fence
    assert as_protocol is w.fence

    h0 = w.fence.lookup_history(w.req_id)
    assert h0.admission_state == AdmissionState.NOT_ADMITTED
    assert h0.effect_state == EffectState.NONE
    assert h0.sequence_use == SequenceUse.UNUSED
    assert w.fence.lookup_occurrence(w.req_id) is None
    assert (
        w.fence.refusal_if_closed_or_stale(
            selected_job=w.job, actor=w.actor, frontier=w.cursors
        )
        is None
    )

    r1 = w.phase("before_request")
    assert isinstance(r1, AcceptedData)
    assert isinstance(r1.data, EffectFenceCheck)
    assert r1.data.phase == "before_request"
    assert r1.data.fence_open is True
    assert r1.data.writes_enabled is True
    assert r1.data.fenced_actor == w.actor
    assert r1.data.frontier == w.cursors
    assert r1.data.window_id == WINDOW
    assert r1.data.selection_revision == REVISION

    r2 = w.phase("before_admit")
    assert isinstance(r2, AcceptedData)
    assert r2.data.phase == "before_admit"
    admitted = w.admit()
    assert isinstance(admitted, AcceptedData)
    assert isinstance(admitted.data, RecordedRowOccurrence)
    assert admitted.data.effect_state == EffectState.ADMITTED_ONLY
    assert admitted.data.sequence_use == SequenceUse.USED
    again = w.admit()
    assert isinstance(again, AcceptedData) and again.data == admitted.data

    r3 = w.phase("before_execute")
    assert isinstance(r3, AcceptedData)
    assert r3.data.phase == "before_execute"
    executed = w.execute()
    assert isinstance(executed, AcceptedData)
    assert executed.data.effect_state == EffectState.COMPLETE
    assert executed.data.executed_legs == (w.leg,)

    counted = w.count()
    assert isinstance(counted, AcceptedData)
    assert counted.data.counted_idempotency_key == "idem-n4-1"

    h_final = w.fence.lookup_history(w.req_id)
    assert h_final.admission_state == AdmissionState.ALREADY_ADMITTED
    assert h_final.effect_state == EffectState.COMPLETE
    assert h_final.sequence_use == SequenceUse.USED
    assert writes_admitted_on_master() is False


def test_public_phase_wrappers_open_the_record_path_in_order() -> None:
    """The join's entry points: before_request, before_admit, before_execute, by keyword."""
    w = open_world()
    bound: dict[str, Any] = {
        "selected_job": w.job,
        "request_identity": w.req_id,
        "actor": w.actor,
        "frontier": w.cursors,
        "window_id": WINDOW,
    }
    assert refusal_code(w.fence.before_admit(**bound)) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.admit()) == RefusalCode.WRITES_DISABLED

    walked = (
        (w.fence.before_request, "before_request", "B_PRE_REQUEST"),
        (w.fence.before_admit, "before_admit", "B_PRE_REQUEST"),
        (w.fence.before_execute, "before_execute", "C_PRE_EXECUTION"),
    )
    for wrapper, phase, boundary in walked:
        checked = wrapper(**bound)
        assert isinstance(checked, AcceptedData), phase
        assert (checked.data.phase, checked.evidence.boundary) == (phase, boundary)
    assert isinstance(w.admit(), AcceptedData)
    assert isinstance(w.execute(), AcceptedData)
    assert isinstance(w.count(), AcceptedData)
    assert refusal_code(w.fence.before_request(**bound)) == RefusalCode.WRITES_DISABLED


# ---------------------------------------------------------------------------
# 2. A closed, write-disabled or unavailable fence never admits
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
    w = open_world(
        writes_enabled=writes_enabled,
        fence_open=fence_open,
        fence_available=fence_available,
    )
    for phase in ("before_request", "before_admit", "before_execute"):
        assert refusal_code(w.phase(phase)) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.admit()) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.execute()) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.count()) == RefusalCode.WRITES_DISABLED
    assert w.fence.lookup_occurrence(w.req_id) is None


def test_fence_closed_or_disabled_mid_request_stops_the_record_path() -> None:
    w = open_world()
    assert isinstance(w.phase("before_request"), AcceptedData)
    assert isinstance(w.phase("before_admit"), AcceptedData)
    w.fence.close_fence()
    assert refusal_code(w.admit()) == RefusalCode.WRITES_DISABLED
    w2 = open_world()
    assert isinstance(w2.phase("before_request"), AcceptedData)
    assert isinstance(w2.phase("before_admit"), AcceptedData)
    w2.fence.disable_writes()
    assert refusal_code(w2.admit()) == RefusalCode.WRITES_DISABLED
    assert w.fence.lookup_occurrence(w.req_id) is None
    assert w2.fence.lookup_occurrence(w2.req_id) is None


def test_open_fence_without_its_binding_or_with_bad_settings_fails_loud() -> None:
    """An open or write-enabled fence is always bound to a job, an actor and a frontier."""
    job = make_selected_job(REVISION)
    actor = make_process_ref("inst-worker")
    cursors = _build_cursors(REVISION)
    whole: dict[str, Any] = {
        "selected_job": job,
        "fenced_actor": actor,
        "expected_frontier": cursors,
    }
    switches: tuple[dict[str, Any], ...] = (
        {"writes_enabled": True},
        {"fence_open": True},
    )
    for switch in switches:
        for missing in whole:
            partial = {k: v for k, v in whole.items() if k != missing}
            with pytest.raises(ValueError, match="selected_job, fenced_actor"):
                DeterministicEffectFenceProvider(**switch, **partial)
    # A closed fence needs none of them: that is the default.
    assert DeterministicEffectFenceProvider().fence_open is False
    with pytest.raises(ValueError, match="distributed enforcement"):
        DeterministicEffectFenceProvider(distributed_enforced=True)
    with pytest.raises(ValueError, match="allowed_phases"):
        DeterministicEffectFenceProvider(
            allowed_phases=cast(Any, frozenset({"before_anything"}))
        )
    with pytest.raises(ValueError, match="window_id"):
        DeterministicEffectFenceProvider(window_id="")


# ---------------------------------------------------------------------------
# 3. Phases per request, in order, at the current frontier
# ---------------------------------------------------------------------------


def test_phases_out_of_order_or_unpermitted_refuse_writes_disabled() -> None:
    w = open_world()
    assert refusal_code(w.phase("before_admit")) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.phase("before_execute")) == RefusalCode.WRITES_DISABLED
    assert isinstance(w.phase("before_request"), AcceptedData)
    assert refusal_code(w.phase("before_execute")) == RefusalCode.WRITES_DISABLED
    assert isinstance(w.phase("before_admit"), AcceptedData)
    # Phases only go forward: no earlier phase once a later one passed.
    assert refusal_code(w.phase("before_request")) == RefusalCode.WRITES_DISABLED

    limited = open_world(allowed_phases=frozenset({"before_request", "before_admit"}))
    assert isinstance(limited.phase("before_request"), AcceptedData)
    assert isinstance(limited.phase("before_admit"), AcceptedData)
    assert refusal_code(limited.phase("before_execute")) == RefusalCode.WRITES_DISABLED
    assert isinstance(limited.admit(), AcceptedData)
    assert refusal_code(limited.execute()) == RefusalCode.WRITES_DISABLED


def test_each_record_needs_its_own_phase_for_its_own_request() -> None:
    """Another request's phases never let this request's record through."""
    w = open_world()
    assert refusal_code(w.admit()) == RefusalCode.WRITES_DISABLED
    assert isinstance(w.phase("before_request"), AcceptedData)
    assert refusal_code(w.admit()) == RefusalCode.WRITES_DISABLED
    assert isinstance(w.phase("before_admit"), AcceptedData)
    assert isinstance(w.admit(), AcceptedData)
    assert refusal_code(w.execute()) == RefusalCode.WRITES_DISABLED
    assert refusal_code(w.count()) == RefusalCode.WRITES_DISABLED

    other_req, other_imm, _, _, other_leg = _build_occurrence_inputs(
        w.job, w.actor, req_key="req-2"
    )
    other_admit = w.fence.record_admission(
        immutable_request_binding=other_imm,
        current_binding=w.cur,
        occurrence=w.occ,
        admission_witness=make_witness("wit-admit-2"),
    )
    assert refusal_code(other_admit) == RefusalCode.WRITES_DISABLED
    assert (
        refusal_code(w.phase("before_admit", req_id=other_req))
        == RefusalCode.WRITES_DISABLED
    )
    assert isinstance(w.phase("before_execute"), AcceptedData)
    other_leg_result = w.fence.record_execution_leg(
        request_identity=other_req, operation_leg=other_leg, current_binding=w.cur
    )
    assert refusal_code(other_leg_result) == RefusalCode.WRITES_DISABLED
    assert w.fence.lookup_occurrence(other_req) is None


def test_stale_or_moved_frontier_refuses_runtime_changed() -> None:
    w = open_world()
    moved = _advance_cursors(w.cursors)
    assert (
        refusal_code(w.phase("before_request", frontier=moved))
        == RefusalCode.RUNTIME_CHANGED
    )
    assert isinstance(w.phase("before_request"), AcceptedData)
    assert isinstance(w.phase("before_admit"), AcceptedData)

    # The runtime moved during a wait: the phase passed at the old frontier no longer counts.
    w.fence.advance_frontier(moved)
    assert refusal_code(w.admit()) == RefusalCode.RUNTIME_CHANGED
    # And the next phase must be at the frontier its predecessor passed at.
    assert (
        refusal_code(w.phase("before_execute", frontier=moved))
        == RefusalCode.RUNTIME_CHANGED
    )
    assert w.fence.lookup_occurrence(w.req_id) is None

    stale = open_world()
    assert isinstance(stale.phase("before_request"), AcceptedData)
    assert isinstance(stale.phase("before_admit"), AcceptedData)
    stale.fence.mark_frontier_stale()
    assert refusal_code(stale.phase("before_execute")) == RefusalCode.RUNTIME_CHANGED
    assert refusal_code(stale.admit()) == RefusalCode.RUNTIME_CHANGED
    assert (
        refusal_code(
            stale.fence.refusal_if_closed_or_stale(
                selected_job=stale.job, actor=stale.actor, frontier=stale.cursors
            )
        )
        == RefusalCode.RUNTIME_CHANGED
    )


# ---------------------------------------------------------------------------
# 4. Another job, window or actor
# ---------------------------------------------------------------------------


def test_other_selection_job_window_or_actor_refused() -> None:
    w = open_world()
    other_selection = make_selected_job("rev-other-999")
    other_job = make_registration_job(
        selection_revision=REVISION,
        execution_uuid="00000000-0000-4000-8000-000000000999",
    )
    assert (
        other_job != w.job and other_job.selection_revision == w.job.selection_revision
    )
    impostor = make_process_ref("inst-impostor")
    restarted = cast(NativeProcessRef, _ProcessRefAtEpoch("inst-worker", "epoch-2"))
    cases: dict[str, tuple[dict[str, Any], RefusalCode]] = {
        "other-selection": ({"job": other_selection}, RefusalCode.SELECTION_CHANGED),
        "other-job-same-selection": ({"job": other_job}, RefusalCode.DISPATCH_CHANGED),
        "other-window": ({"window_id": "win-other-999"}, RefusalCode.RUNTIME_CHANGED),
        "other-actor": ({"actor": impostor}, RefusalCode.SUBJECT_MISMATCH),
        "same-name-other-process": ({"actor": restarted}, RefusalCode.RUNTIME_CHANGED),
    }
    for case, (drift, code) in cases.items():
        assert refusal_code(w.phase("before_request", **drift)) == code, case
        gate = w.fence.refusal_if_closed_or_stale(
            selected_job=drift.get("job", w.job),
            window_id=drift.get("window_id"),
            actor=drift.get("actor", w.actor),
            frontier=w.cursors,
        )
        assert refusal_code(gate) == code, case

    # The record path checks the job its binding names, and the checker it records.
    assert isinstance(w.phase("before_request"), AcceptedData)
    assert isinstance(w.phase("before_admit"), AcceptedData)
    for job, code in (
        (other_selection, RefusalCode.SELECTION_CHANGED),
        (other_job, RefusalCode.DISPATCH_CHANGED),
    ):
        foreign = replace(w.cur, selected_job=job)
        assert refusal_code(w.admit(cur=foreign)) == code
    _, impostor_imm, _, _, _ = _build_occurrence_inputs(w.job, impostor)
    impostor_admit = w.fence.record_admission(
        immutable_request_binding=impostor_imm,
        current_binding=w.cur,
        occurrence=w.occ,
        admission_witness=make_witness("wit-admit-x"),
    )
    assert refusal_code(impostor_admit) == RefusalCode.SUBJECT_MISMATCH
    assert w.fence.lookup_occurrence(w.req_id) is None


# ---------------------------------------------------------------------------
# 5. Occurrence history
# ---------------------------------------------------------------------------


def test_occurrence_prior_missing_foreign_and_counted_once() -> None:
    w = open_world()
    for phase in ("before_request", "before_admit", "before_execute"):
        assert isinstance(w.phase(phase), AcceptedData)
    # Executing or counting what was never admitted.
    assert refusal_code(w.execute()) == RefusalCode.PRIOR_MISSING
    assert refusal_code(w.count()) == RefusalCode.PRIOR_MISSING

    w2 = open_world()
    assert isinstance(w2.phase("before_request"), AcceptedData)
    assert isinstance(w2.phase("before_admit"), AcceptedData)
    assert isinstance(w2.admit(), AcceptedData)
    _, conflicting, _, _, _ = _build_occurrence_inputs(
        w2.job, w2.actor, sha256="b" * 64
    )
    foreign = w2.fence.record_admission(
        immutable_request_binding=conflicting,
        current_binding=w2.cur,
        occurrence=w2.occ,
        admission_witness=make_witness("wit-admit-2"),
    )
    assert refusal_code(foreign) == RefusalCode.PRIOR_FOREIGN
    assert isinstance(w2.phase("before_execute"), AcceptedData)
    assert isinstance(w2.execute(), AcceptedData)
    assert isinstance(w2.count("idem-1"), AcceptedData)
    assert refusal_code(w2.count("idem-1")) == RefusalCode.ALREADY_COUNTED
    assert refusal_code(w2.count("idem-2")) == RefusalCode.ALREADY_COUNTED
