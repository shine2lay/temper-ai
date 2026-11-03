"""P3 T5-N4 deterministic phase-bound write/effect fence provider.

Implements ``EffectFenceProvider`` from ``temper_ai.p3_authority._providers``
along with explicit phase-bound write fence checks across the three authority
phases (``before_request``, ``before_admit``, ``before_execute``).

Invariants:
- Closed and inert by default (``writes_enabled=False``, ``fence_open=False``).
- An open or write-enabled fence is bound at construction to one selected job,
  one fenced actor and one expected frontier; without all three it is refused
  (ValueError), so there is no open fence that accepts any job or actor.
- Nothing here reads or changes ``WRITES_ADMITTED`` (configs/architecture/bin/first_app_p3_host.py).
- Closed, write-disabled or unavailable fence, an unpermitted phase, a phase
  out of order for its request, or a record without its own phase verified
  for that request -> ``RefusalCode.WRITES_DISABLED``.
- Stale frontier after a wait, or frontier/window/actor drift -> ``RefusalCode.RUNTIME_CHANGED``.
- Phases are kept per request only: each request walks before_request ->
  before_admit -> before_execute itself, never on another request's phases.
- No live Docker, host filesystem, database, or model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from temper_ai.p3_authority._providers import (
    EffectFenceProvider,
    RecordedRowOccurrence,
)
from temper_ai.p3_authority.boundary_types import CurrentObservationCursors
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    Boundary,
    CurrentBinding,
    EffectState,
    ImmutableRequestBinding,
    NativeProcessRef,
    NativeWitness,
    OccurrenceHandle,
    OperationLeg,
    Phase,
    Refusal,
    RefusalCode,
    RequestIdentity,
    Result,
    RetryKind,
    SelectedJob,
    SequenceUse,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    ImmutableReferenceRecord,
    PriorRequestHistory,
    boundary_to_phase,
    default_effect_for_job,
    make_refusal,
)

EffectFencePhase = Literal["before_request", "before_admit", "before_execute"]

VALID_FENCE_PHASES: tuple[EffectFencePhase, ...] = (
    "before_request",
    "before_admit",
    "before_execute",
)

PHASE_PREDECESSOR: dict[EffectFencePhase, EffectFencePhase | None] = {
    "before_request": None,
    "before_admit": "before_request",
    "before_execute": "before_admit",
}


@dataclass(frozen=True, slots=True)
class _FenceWitness:
    witness_reference: str


@dataclass(frozen=True, slots=True)
class _OpenFence:
    """What an open, write-enabled fence is bound to right now."""

    selected_job: SelectedJob
    actor: NativeProcessRef
    frontier: CurrentObservationCursors


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectFenceCheck:
    """Verified phase-bound write fence state at a single authority phase."""

    phase: EffectFencePhase
    selection_revision: str
    window_id: str
    fenced_actor: NativeProcessRef
    frontier: CurrentObservationCursors
    writes_enabled: bool
    fence_open: bool
    fence_witness: NativeWitness


def decision_evidence_for(
    *,
    selected_job: SelectedJob,
    actor: NativeProcessRef,
    boundary: Boundary,
) -> DecisionEvidenceRecord:
    """The decision evidence one actor's accepted check at ``boundary`` carries."""
    source_ref = ImmutableReferenceRecord(
        path=f"source/{selected_job.selection_revision}",
        digest=selected_job.expected_source_digest,
        length=64,
        revision=selected_job.selection_revision,
    )
    return DecisionEvidenceRecord(
        selected_job=selected_job,
        authority_revisions=selected_job.authority_refs,
        window=None,
        processes=(actor,),
        effect=default_effect_for_job(selected_job, boundary),
        phase=boundary_to_phase(boundary),
        boundary=boundary,
        source=source_ref,
        closure=selected_job.reviewed_closure_ref,
        compatibility=selected_job.compatibility_profile,
    )


def _refuse(
    code: RefusalCode, phase: Phase, retry_kind: RetryKind, history: PriorRequestHistory
) -> Refusal:
    return make_refusal(code, phase=phase, retry_kind=retry_kind, history=history)


class DeterministicEffectFenceProvider(EffectFenceProvider):
    """Deterministic phase-bound write fence and row-occurrence provider.

    Satisfies ``EffectFenceProvider`` while enforcing phase-bound write fencing
    across ``before_request``, ``before_admit``, and ``before_execute``.
    Closed by default (``writes_enabled=False``, ``fence_open=False``); a closed
    fence with ``writes_enabled=False`` never admits or executes writes.

    On the record path each request needs its own phase verified first, at the
    current frontier: ``before_admit`` before ``record_admission``, and
    ``before_execute`` before ``record_execution_leg`` and ``mark_counted``.
    """

    def __init__(
        self,
        *,
        writes_enabled: bool = False,
        fence_open: bool = False,
        fence_available: bool = True,
        selected_job: SelectedJob | None = None,
        window_id: str = "win-default",
        fenced_actor: NativeProcessRef | None = None,
        expected_frontier: CurrentObservationCursors | None = None,
        allowed_phases: frozenset[EffectFencePhase] = frozenset(VALID_FENCE_PHASES),
        fence_witness: NativeWitness | None = None,
        distributed_enforced: bool = False,
    ) -> None:
        if distributed_enforced:
            raise ValueError(
                "DeterministicEffectFenceProvider is a local deterministic provider "
                "and cannot claim distributed enforcement"
            )
        if (writes_enabled or fence_open) and (
            selected_job is None or fenced_actor is None or expected_frontier is None
        ):
            raise ValueError(
                "an open or write-enabled fence needs its selected_job, fenced_actor "
                "and expected_frontier"
            )
        if not allowed_phases <= frozenset(VALID_FENCE_PHASES):
            raise ValueError(
                "allowed_phases may hold only before_request, before_admit, before_execute"
            )
        if not window_id:
            raise ValueError("window_id must name the fenced window")
        self._writes_enabled = bool(writes_enabled)
        self._fence_open = bool(fence_open)
        self._fence_available = bool(fence_available)
        self._selected_job = selected_job
        self._window_id = window_id
        self._fenced_actor = fenced_actor
        self._expected_frontier = expected_frontier
        self._allowed_phases = frozenset(allowed_phases)
        rev = selected_job.selection_revision if selected_job is not None else "closed"
        self._fence_witness: NativeWitness = fence_witness or _FenceWitness(
            witness_reference=f"witness:effect-fence:{rev}"
        )
        self._frontier_stale = False
        # The phases each request has passed, with the frontier it passed them at.
        self._request_phases: dict[
            RequestIdentity, dict[EffectFencePhase, CurrentObservationCursors]
        ] = {}
        # Row-scoped occurrence and idempotency state
        self._occurrences: dict[RequestIdentity, RecordedRowOccurrence] = {}
        self._counted_keys: dict[str, RequestIdentity] = {}
        self._explicit_history: dict[RequestIdentity, PriorRequestHistory] = {}

    @property
    def writes_enabled(self) -> bool:
        return self._writes_enabled

    @property
    def fence_open(self) -> bool:
        return self._fence_open

    @property
    def fence_available(self) -> bool:
        return self._fence_available

    @property
    def expected_frontier(self) -> CurrentObservationCursors | None:
        return self._expected_frontier

    def advance_frontier(self, new_frontier: CurrentObservationCursors) -> None:
        """Advance the live runtime frontier (simulating runtime evolution during a wait)."""
        self._expected_frontier = new_frontier

    def mark_frontier_stale(self) -> None:
        """Mark the fence's observed runtime frontier stale after a wait."""
        self._frontier_stale = True

    def close_fence(self) -> None:
        """Close the write fence immediately."""
        self._fence_open = False

    def disable_writes(self) -> None:
        """Disable writes on this fence."""
        self._writes_enabled = False

    def set_explicit_history(
        self,
        request_identity: RequestIdentity,
        history: PriorRequestHistory,
    ) -> None:
        self._explicit_history[request_identity] = history

    def lookup_history(
        self,
        request_identity: RequestIdentity,
    ) -> PriorRequestHistory:
        if request_identity in self._explicit_history:
            return self._explicit_history[request_identity]
        occ = self._occurrences.get(request_identity)
        if occ is None:
            return PriorRequestHistory(
                admission_state=AdmissionState.NOT_ADMITTED,
                effect_state=EffectState.NONE,
                sequence_use=SequenceUse.UNUSED,
            )
        return PriorRequestHistory(
            admission_state=AdmissionState.ALREADY_ADMITTED,
            effect_state=occ.effect_state,
            sequence_use=occ.sequence_use,
        )

    def lookup_occurrence(
        self,
        request_identity: RequestIdentity,
    ) -> RecordedRowOccurrence | None:
        return self._occurrences.get(request_identity)

    # -- the gates ---------------------------------------------------------------------

    def _open(self) -> _OpenFence | None:
        """What the fence is bound to while open, write-enabled and available; else None."""
        job, actor, frontier = (
            self._selected_job,
            self._fenced_actor,
            self._expected_frontier,
        )
        if (
            not self._writes_enabled
            or not self._fence_open
            or not self._fence_available
            or job is None
            or actor is None
            or frontier is None
        ):
            return None
        return _OpenFence(selected_job=job, actor=actor, frontier=frontier)

    def _binding_refusal(
        self,
        bound: _OpenFence,
        *,
        selected_job: SelectedJob,
        window_id: str,
        actor: NativeProcessRef,
        phase: Phase,
        history: PriorRequestHistory,
    ) -> Refusal | None:
        """Another job, window or actor than the fence's, or a stale frontier."""
        new_binding = RetryKind.NEW_BINDING_REQUIRED
        if selected_job != bound.selected_job:
            code = (
                RefusalCode.SELECTION_CHANGED
                if selected_job.selection_revision
                != bound.selected_job.selection_revision
                else RefusalCode.DISPATCH_CHANGED
            )
            return _refuse(code, phase, new_binding, history)
        if window_id != self._window_id:
            return _refuse(RefusalCode.RUNTIME_CHANGED, phase, new_binding, history)
        if actor.process_registration != bound.actor.process_registration:
            return _refuse(RefusalCode.SUBJECT_MISMATCH, phase, new_binding, history)
        if actor != bound.actor or self._frontier_stale:
            return _refuse(RefusalCode.RUNTIME_CHANGED, phase, new_binding, history)
        return None

    def refusal_if_closed_or_stale(
        self,
        *,
        selected_job: SelectedJob,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "B_PRE_REQUEST",
        history: PriorRequestHistory | None = None,
    ) -> Refusal | None:
        """Read-only gate: the refusal a closed, foreign or stale fence gives, else None.

        Records no phase. Closed, disabled or unavailable -> WRITES_DISABLED; another
        selection -> SELECTION_CHANGED, another job -> DISPATCH_CHANGED; another
        actor -> SUBJECT_MISMATCH; foreign window, changed actor, or stale/drifted
        frontier -> RUNTIME_CHANGED.
        """
        phase = boundary_to_phase(boundary)
        history = history if history is not None else PriorRequestHistory()
        bound = self._open()
        if bound is None:
            return _refuse(
                RefusalCode.WRITES_DISABLED, phase, RetryKind.NOT_APPLICABLE, history
            )
        refused = self._binding_refusal(
            bound,
            selected_job=selected_job,
            window_id=window_id if window_id is not None else self._window_id,
            actor=actor,
            phase=phase,
            history=history,
        )
        if refused is not None:
            return refused
        if frontier != bound.frontier:
            return _refuse(
                RefusalCode.RUNTIME_CHANGED,
                phase,
                RetryKind.NEW_BINDING_REQUIRED,
                history,
            )
        return None

    # -- the three phases --------------------------------------------------------------

    def verify_fence(
        self,
        *,
        phase: EffectFencePhase,
        selected_job: SelectedJob,
        request_identity: RequestIdentity,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        window_id: str | None = None,
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> Result[EffectFenceCheck]:
        """Verify one phase for one request: fence open and bound, phases in order.

        Records the phase for this request only when accepted.
        """
        bound_phase = boundary_to_phase(boundary)
        history = self.lookup_history(request_identity)
        if phase not in VALID_FENCE_PHASES or phase not in self._allowed_phases:
            return _refuse(
                RefusalCode.WRITES_DISABLED,
                bound_phase,
                RetryKind.NOT_APPLICABLE,
                history,
            )
        closed = self.refusal_if_closed_or_stale(
            selected_job=selected_job,
            window_id=window_id,
            actor=actor,
            frontier=frontier,
            boundary=boundary,
            history=history,
        )
        if closed is not None:
            return closed
        passed = self._request_phases.get(request_identity, {})
        later = VALID_FENCE_PHASES[VALID_FENCE_PHASES.index(phase) + 1 :]
        predecessor = PHASE_PREDECESSOR[phase]
        if any(p in passed for p in later) or (
            predecessor is not None and predecessor not in passed
        ):
            return _refuse(
                RefusalCode.WRITES_DISABLED,
                bound_phase,
                RetryKind.NOT_APPLICABLE,
                history,
            )
        if predecessor is not None and passed[predecessor] != frontier:
            return _refuse(
                RefusalCode.RUNTIME_CHANGED,
                bound_phase,
                RetryKind.NEW_BINDING_REQUIRED,
                history,
            )
        self._request_phases.setdefault(request_identity, {})[phase] = frontier
        check = EffectFenceCheck(
            phase=phase,
            selection_revision=selected_job.selection_revision,
            window_id=self._window_id,
            fenced_actor=actor,
            frontier=frontier,
            writes_enabled=self._writes_enabled,
            fence_open=self._fence_open,
            fence_witness=self._fence_witness,
        )
        evidence = decision_evidence_for(
            selected_job=selected_job, actor=actor, boundary=boundary
        )
        return AcceptedData(data=check, evidence=evidence)

    def before_request(
        self,
        *,
        selected_job: SelectedJob,
        request_identity: RequestIdentity,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        window_id: str | None = None,
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_request`` phase of the write fence."""
        return self.verify_fence(
            phase="before_request",
            selected_job=selected_job,
            request_identity=request_identity,
            actor=actor,
            frontier=frontier,
            window_id=window_id,
            boundary=boundary,
        )

    def before_admit(
        self,
        *,
        selected_job: SelectedJob,
        request_identity: RequestIdentity,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        window_id: str | None = None,
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_admit`` phase of the write fence."""
        return self.verify_fence(
            phase="before_admit",
            selected_job=selected_job,
            request_identity=request_identity,
            actor=actor,
            frontier=frontier,
            window_id=window_id,
            boundary=boundary,
        )

    def before_execute(
        self,
        *,
        selected_job: SelectedJob,
        request_identity: RequestIdentity,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        window_id: str | None = None,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_execute`` phase of the write fence."""
        return self.verify_fence(
            phase="before_execute",
            selected_job=selected_job,
            request_identity=request_identity,
            actor=actor,
            frontier=frontier,
            window_id=window_id,
            boundary=boundary,
        )

    # -- the record path ---------------------------------------------------------------

    def _occurrence_gate(
        self,
        *,
        phase: EffectFencePhase,
        current_binding: CurrentBinding,
        actor: NativeProcessRef | None,
        request_identity: RequestIdentity,
        target_phase: Phase,
    ) -> Refusal | _OpenFence:
        """The fence a record may go through, or why not.

        ``actor`` None means the fenced actor. The request must have passed ``phase``
        itself (never another request's), at the frontier the fence expects now.
        """
        history = self.lookup_history(request_identity)
        bound = self._open()
        if bound is None or phase not in self._allowed_phases:
            return _refuse(
                RefusalCode.WRITES_DISABLED,
                target_phase,
                RetryKind.NOT_APPLICABLE,
                history,
            )
        refused = self._binding_refusal(
            bound,
            selected_job=current_binding.selected_job,
            window_id=self._window_id,
            actor=actor if actor is not None else bound.actor,
            phase=target_phase,
            history=history,
        )
        if refused is not None:
            return refused
        passed = self._request_phases.get(request_identity, {})
        if phase not in passed:
            return _refuse(
                RefusalCode.WRITES_DISABLED,
                target_phase,
                RetryKind.NOT_APPLICABLE,
                history,
            )
        if passed[phase] != bound.frontier:
            return _refuse(
                RefusalCode.RUNTIME_CHANGED,
                target_phase,
                RetryKind.NEW_BINDING_REQUIRED,
                history,
            )
        return bound

    def record_admission(
        self,
        *,
        immutable_request_binding: ImmutableRequestBinding,
        current_binding: CurrentBinding,
        occurrence: OccurrenceHandle,
        admission_witness: NativeWitness,
    ) -> Result[RecordedRowOccurrence]:
        req_id = immutable_request_binding.request_identity
        actor = immutable_request_binding.checker.checker
        gate = self._occurrence_gate(
            phase="before_admit",
            current_binding=current_binding,
            actor=actor,
            request_identity=req_id,
            target_phase=Phase.B,
        )
        if isinstance(gate, Refusal):
            return gate
        evidence = decision_evidence_for(
            selected_job=current_binding.selected_job,
            actor=actor,
            boundary=current_binding.boundary,
        )
        existing = self._occurrences.get(req_id)
        if existing is not None:
            if (
                existing.request_raw_sha256
                != immutable_request_binding.request_raw.sha256
                or existing.selection_revision
                != current_binding.selected_job.selection_revision
            ):
                return _refuse(
                    RefusalCode.PRIOR_FOREIGN,
                    Phase.B,
                    RetryKind.NOT_APPLICABLE,
                    self.lookup_history(req_id),
                )
            return AcceptedData(data=existing, evidence=evidence)
        rec = RecordedRowOccurrence(
            request_identity=req_id,
            selection_revision=current_binding.selected_job.selection_revision,
            request_raw_sha256=immutable_request_binding.request_raw.sha256,
            occurrence=occurrence,
            admission_witness=admission_witness,
            admitted_binding=current_binding,
            executed_legs=(),
            effect_state=EffectState.ADMITTED_ONLY,
            sequence_use=SequenceUse.USED,
        )
        self._occurrences[req_id] = rec
        return AcceptedData(data=rec, evidence=evidence)

    def record_execution_leg(
        self,
        *,
        request_identity: RequestIdentity,
        operation_leg: OperationLeg,
        current_binding: CurrentBinding,
        effect_state: EffectState = EffectState.COMPLETE,
    ) -> Result[RecordedRowOccurrence]:
        gate = self._occurrence_gate(
            phase="before_execute",
            current_binding=current_binding,
            actor=operation_leg.actor,
            request_identity=request_identity,
            target_phase=Phase.B,
        )
        if isinstance(gate, Refusal):
            return gate
        existing = self._occurrences.get(request_identity)
        if existing is None:
            return _refuse(
                RefusalCode.PRIOR_MISSING,
                Phase.B,
                RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )
        if (
            existing.selection_revision
            != current_binding.selected_job.selection_revision
        ):
            return _refuse(
                RefusalCode.PRIOR_FOREIGN,
                Phase.B,
                RetryKind.NOT_APPLICABLE,
                self.lookup_history(request_identity),
            )
        updated = RecordedRowOccurrence(
            request_identity=existing.request_identity,
            selection_revision=existing.selection_revision,
            request_raw_sha256=existing.request_raw_sha256,
            occurrence=existing.occurrence,
            admission_witness=existing.admission_witness,
            admitted_binding=current_binding,
            executed_legs=(*existing.executed_legs, operation_leg),
            effect_state=effect_state,
            sequence_use=SequenceUse.USED,
            counted_idempotency_key=existing.counted_idempotency_key,
        )
        self._occurrences[request_identity] = updated
        return AcceptedData(
            data=updated,
            evidence=decision_evidence_for(
                selected_job=current_binding.selected_job,
                actor=operation_leg.actor,
                boundary=current_binding.boundary,
            ),
        )

    def mark_counted(
        self,
        *,
        request_identity: RequestIdentity,
        idempotency_identity: str,
        current_binding: CurrentBinding,
    ) -> Result[RecordedRowOccurrence]:
        """Count an executed occurrence once: its last leg's actor, else the fenced actor."""
        occ_existing = self._occurrences.get(request_identity)
        last_actor = (
            occ_existing.executed_legs[-1].actor
            if occ_existing is not None and occ_existing.executed_legs
            else None
        )
        gate = self._occurrence_gate(
            phase="before_execute",
            current_binding=current_binding,
            actor=last_actor,
            request_identity=request_identity,
            target_phase=Phase.C,
        )
        if isinstance(gate, Refusal):
            return gate
        actor = last_actor if last_actor is not None else gate.actor
        existing = self._occurrences.get(request_identity)
        if existing is None:
            return _refuse(
                RefusalCode.PRIOR_MISSING,
                Phase.C,
                RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )
        if (
            existing.counted_idempotency_key is not None
            or idempotency_identity in self._counted_keys
        ):
            return _refuse(
                RefusalCode.ALREADY_COUNTED,
                Phase.C,
                RetryKind.NOT_APPLICABLE,
                self.lookup_history(request_identity),
            )
        updated = RecordedRowOccurrence(
            request_identity=existing.request_identity,
            selection_revision=existing.selection_revision,
            request_raw_sha256=existing.request_raw_sha256,
            occurrence=existing.occurrence,
            admission_witness=existing.admission_witness,
            admitted_binding=current_binding,
            executed_legs=existing.executed_legs,
            effect_state=existing.effect_state,
            sequence_use=SequenceUse.USED,
            counted_idempotency_key=idempotency_identity,
        )
        self._occurrences[request_identity] = updated
        self._counted_keys[idempotency_identity] = request_identity
        return AcceptedData(
            data=updated,
            evidence=decision_evidence_for(
                selected_job=current_binding.selected_job,
                actor=actor,
                boundary=current_binding.boundary,
            ),
        )


__all__ = [
    "DeterministicEffectFenceProvider",
    "EffectFenceCheck",
    "EffectFencePhase",
    "PHASE_PREDECESSOR",
    "VALID_FENCE_PHASES",
    "decision_evidence_for",
]
