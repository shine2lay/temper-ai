"""P3 T5-N4 deterministic phase-bound write/effect fence provider.

Implements ``EffectFenceProvider`` from ``temper_ai.p3_authority._providers``
along with explicit phase-bound write fence checks across the three authority
phases (``before_request``, ``before_admit``, ``before_execute``).

Invariants:
- Closed and inert by default (``writes_enabled=False``, ``fence_open=False``).
- Nothing here reads or changes ``WRITES_ADMITTED`` (configs/architecture/bin/first_app_p3_host.py).
- ``writes_enabled=False``, ``fence_open=False``, ``fence_available=False``,
  unpermitted phase, or missing predecessor phase -> ``RefusalCode.WRITES_DISABLED``.
- Stale ``CurrentObservationCursors`` / ``N3ObservationEpoch`` frontier after a
  wait or frontier/binding drift between phases/legs -> ``RefusalCode.RUNTIME_CHANGED``.
- No live Docker, host filesystem, database, or model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

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


class DeterministicEffectFenceProvider(EffectFenceProvider):
    """Deterministic phase-bound write fence and row-occurrence provider.

    Satisfies ``EffectFenceProvider`` while enforcing phase-bound write fencing
    across ``before_request``, ``before_admit``, and ``before_execute``.
    Closed by default (``writes_enabled=False``, ``fence_open=False``); a closed
    fence with ``writes_enabled=False`` never admits or executes writes.
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
        enforce_phase_order: bool = True,
        require_explicit_phase_calls: bool = False,
        fence_witness: NativeWitness | None = None,
        distributed_enforced: bool = False,
    ) -> None:
        if distributed_enforced:
            raise ValueError(
                "DeterministicEffectFenceProvider is a local deterministic provider and cannot claim distributed enforcement"
            )
        self._writes_enabled = bool(writes_enabled)
        self._fence_open = bool(fence_open)
        self._fence_available = bool(fence_available)
        self._selected_job = selected_job
        self._window_id = window_id
        self._fenced_actor = fenced_actor
        self._expected_frontier = expected_frontier
        self._allowed_phases = frozenset(allowed_phases)
        self._enforce_phase_order = bool(enforce_phase_order)
        self._require_explicit_phase_calls = bool(require_explicit_phase_calls)
        rev = selected_job.selection_revision if selected_job is not None else "rev-default"
        self._fence_witness: NativeWitness = fence_witness or _FenceWitness(
            witness_reference=f"witness:effect-fence:{rev}"
        )
        self._frontier_stale = False

        # Per-(selection_revision, window_id) and per-request phase tracking
        self._completed_phases: dict[
            tuple[str, str], dict[EffectFencePhase, CurrentObservationCursors]
        ] = {}
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

    def verify_fence(
        self,
        *,
        phase: EffectFencePhase,
        selected_job: SelectedJob | None = None,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "B_PRE_REQUEST",
        request_identity: RequestIdentity | None = None,
    ) -> Result[EffectFenceCheck]:
        """Verify that the phase-bound write fence is open and bound to actor/frontier."""
        bound_phase = boundary_to_phase(boundary)
        history = (
            self.lookup_history(request_identity)
            if request_identity is not None
            else PriorRequestHistory()
        )
        if phase not in VALID_FENCE_PHASES or phase not in self._allowed_phases:
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                phase=bound_phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
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
        job = cast(SelectedJob, selected_job or self._selected_job)
        eff_window_id = window_id if window_id is not None else self._window_id

        scope_key = (job.selection_revision, eff_window_id)
        prior_scope_phases = self._completed_phases.setdefault(scope_key, {})
        prior_req_phases = (
            self._request_phases.setdefault(request_identity, {})
            if request_identity is not None
            else prior_scope_phases
        )

        if self._enforce_phase_order:
            predecessor = PHASE_PREDECESSOR[phase]
            if predecessor is not None:
                if predecessor not in prior_req_phases:
                    return make_refusal(
                        RefusalCode.WRITES_DISABLED,
                        phase=bound_phase,
                        retry_kind=RetryKind.NOT_APPLICABLE,
                        history=history,
                    )
                if prior_req_phases[predecessor] != frontier:
                    return make_refusal(
                        RefusalCode.RUNTIME_CHANGED,
                        phase=bound_phase,
                        retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                        history=history,
                    )

        prior_scope_phases[phase] = frontier
        if request_identity is not None:
            prior_req_phases[phase] = frontier

        check = EffectFenceCheck(
            phase=phase,
            selection_revision=job.selection_revision,
            window_id=eff_window_id,
            fenced_actor=actor,
            frontier=frontier,
            writes_enabled=self._writes_enabled,
            fence_open=self._fence_open,
            fence_witness=self._fence_witness,
        )
        evidence = decision_evidence_for(
            selected_job=job,
            actor=actor,
            boundary=boundary,
        )
        return AcceptedData(data=check, evidence=evidence)

    def refusal_if_closed_or_stale(
        self,
        *,
        selected_job: SelectedJob | None = None,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "B_PRE_REQUEST",
        history: PriorRequestHistory | None = None,
    ) -> Refusal | None:
        """Read-only gate: the refusal a closed, foreign or stale fence gives, else None.

        Records no phase. Closed, disabled or unavailable -> WRITES_DISABLED; foreign
        window, changed actor or stale/drifted frontier -> RUNTIME_CHANGED.
        """
        bound_phase = boundary_to_phase(boundary)
        history = history if history is not None else PriorRequestHistory()
        if (
            not self._writes_enabled
            or not self._fence_open
            or not self._fence_available
        ):
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                phase=bound_phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        job = selected_job or self._selected_job
        if job is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=bound_phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            self._selected_job is not None
            and job.selection_revision != self._selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                phase=bound_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        eff_window_id = window_id if window_id is not None else self._window_id
        if eff_window_id != self._window_id:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                phase=bound_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        if (
            self._fenced_actor is not None
            and actor.process_registration != self._fenced_actor.process_registration
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=bound_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if self._fenced_actor is not None and actor != self._fenced_actor:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                phase=bound_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        if self._frontier_stale or (
            self._expected_frontier is not None and frontier != self._expected_frontier
        ):
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                phase=bound_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        return None

    def before_request(
        self,
        *,
        selected_job: SelectedJob | None = None,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "B_PRE_REQUEST",
        request_identity: RequestIdentity | None = None,
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_request`` phase of the write fence."""
        return self.verify_fence(
            phase="before_request",
            selected_job=selected_job,
            window_id=window_id,
            actor=actor,
            frontier=frontier,
            boundary=boundary,
            request_identity=request_identity,
        )

    def before_admit(
        self,
        *,
        selected_job: SelectedJob | None = None,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "B_PRE_REQUEST",
        request_identity: RequestIdentity | None = None,
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_admit`` phase of the write fence."""
        return self.verify_fence(
            phase="before_admit",
            selected_job=selected_job,
            window_id=window_id,
            actor=actor,
            frontier=frontier,
            boundary=boundary,
            request_identity=request_identity,
        )

    def before_execute(
        self,
        *,
        selected_job: SelectedJob | None = None,
        window_id: str | None = None,
        actor: NativeProcessRef,
        frontier: CurrentObservationCursors,
        boundary: Boundary = "C_PRE_EXECUTION",
        request_identity: RequestIdentity | None = None,
    ) -> Result[EffectFenceCheck]:
        """Verify the ``before_execute`` phase of the write fence."""
        return self.verify_fence(
            phase="before_execute",
            selected_job=selected_job,
            window_id=window_id,
            actor=actor,
            frontier=frontier,
            boundary=boundary,
            request_identity=request_identity,
        )

    def _verify_fence_for_occurrence(
        self,
        *,
        phase: EffectFencePhase,
        current_binding: CurrentBinding,
        actor: NativeProcessRef,
        request_identity: RequestIdentity,
        target_phase: Phase,
    ) -> Refusal | None:
        history = self.lookup_history(request_identity)
        if (
            not self._writes_enabled
            or not self._fence_open
            or not self._fence_available
        ):
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                phase=target_phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if phase not in self._allowed_phases:
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                phase=target_phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if self._frontier_stale:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                phase=target_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if (
            self._selected_job is not None
            and current_binding.selected_job.selection_revision
            != self._selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                phase=target_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if (
            self._fenced_actor is not None
            and actor.process_registration != self._fenced_actor.process_registration
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=target_phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        scope_key = (
            current_binding.selected_job.selection_revision,
            self._window_id,
        )
        req_phases = self._request_phases.get(request_identity)
        scope_phases = self._completed_phases.get(scope_key)
        tracked_phases = req_phases if req_phases is not None else scope_phases

        if self._require_explicit_phase_calls or tracked_phases is not None:
            active_phases = tracked_phases or {}
            if phase not in active_phases:
                predecessor = PHASE_PREDECESSOR[phase]
                if self._require_explicit_phase_calls or (
                    predecessor is not None and predecessor not in active_phases
                ):
                    return make_refusal(
                        RefusalCode.WRITES_DISABLED,
                        phase=target_phase,
                        retry_kind=RetryKind.NOT_APPLICABLE,
                        history=history,
                    )
                if (
                    predecessor is not None
                    and self._expected_frontier is not None
                    and active_phases[predecessor] != self._expected_frontier
                ):
                    return make_refusal(
                        RefusalCode.RUNTIME_CHANGED,
                        phase=target_phase,
                        retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                        history=history,
                    )
            elif (
                self._expected_frontier is not None
                and active_phases[phase] != self._expected_frontier
            ):
                return make_refusal(
                    RefusalCode.RUNTIME_CHANGED,
                    phase=target_phase,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                    history=history,
                )

        return None

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
        fence_err = self._verify_fence_for_occurrence(
            phase="before_admit",
            current_binding=current_binding,
            actor=actor,
            request_identity=req_id,
            target_phase=Phase.B,
        )
        if fence_err is not None:
            return fence_err

        existing = self._occurrences.get(req_id)
        if existing is not None:
            if (
                existing.request_raw_sha256
                != immutable_request_binding.request_raw.sha256
                or existing.selection_revision
                != current_binding.selected_job.selection_revision
            ):
                return make_refusal(
                    RefusalCode.PRIOR_FOREIGN,
                    phase=Phase.B,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=self.lookup_history(req_id),
                )
            return AcceptedData(
                data=existing,
                evidence=decision_evidence_for(
                    selected_job=current_binding.selected_job,
                    actor=actor,
                    boundary=current_binding.boundary,
                ),
            )

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
        return AcceptedData(
            data=rec,
            evidence=decision_evidence_for(
                selected_job=current_binding.selected_job,
                actor=actor,
                boundary=current_binding.boundary,
            ),
        )

    def record_execution_leg(
        self,
        *,
        request_identity: RequestIdentity,
        operation_leg: OperationLeg,
        current_binding: CurrentBinding,
        effect_state: EffectState = EffectState.COMPLETE,
    ) -> Result[RecordedRowOccurrence]:
        fence_err = self._verify_fence_for_occurrence(
            phase="before_execute",
            current_binding=current_binding,
            actor=operation_leg.actor,
            request_identity=request_identity,
            target_phase=Phase.B,
        )
        if fence_err is not None:
            return fence_err

        existing = self._occurrences.get(request_identity)
        if existing is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=Phase.B,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )
        if (
            existing.selection_revision
            != current_binding.selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=Phase.B,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=self.lookup_history(request_identity),
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
        occ_existing = self._occurrences.get(request_identity)
        actor: NativeProcessRef
        if occ_existing is not None and occ_existing.executed_legs:
            actor = occ_existing.executed_legs[-1].actor
        elif self._fenced_actor is not None:
            actor = self._fenced_actor
        else:
            occ_obj: object = (
                occ_existing.occurrence if occ_existing is not None else None
            )
            actor = cast(
                NativeProcessRef,
                getattr(
                    getattr(occ_obj, "controller", occ_obj),
                    "native_identity",
                    getattr(occ_obj, "controller", occ_obj),
                ),
            )

        fence_err = self._verify_fence_for_occurrence(
            phase="before_execute",
            current_binding=current_binding,
            actor=actor,
            request_identity=request_identity,
            target_phase=Phase.C,
        )
        if fence_err is not None:
            return fence_err

        existing = self._occurrences.get(request_identity)
        if existing is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=Phase.C,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )
        if (
            existing.counted_idempotency_key is not None
            or idempotency_identity in self._counted_keys
        ):
            return make_refusal(
                RefusalCode.ALREADY_COUNTED,
                phase=Phase.C,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=self.lookup_history(request_identity),
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
