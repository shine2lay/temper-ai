"""Provider adapters and explicit test-only doubles for P3 authority composition.

Delegates source-closure comparison to Systems' ``p3_source_closure.compare_loaded_source``
via the canonical ``SharedN3`` port and defines narrow provider protocols plus
explicit in-memory doubles for synthetic testing. No provider is active by default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    AuthenticatedPeer,
    Boundary,
    CurrentBinding,
    EffectLease,
    EffectSet,
    EffectState,
    HostCoverage,
    HostEffect,
    HostObservation,
    HostObserver,
    HostProvenance,
    ImmutableRequestBinding,
    LoadedClosureEnvelope,
    N3ObservationEpoch,
    NativeProcessRef,
    NativeReceive,
    NativeSelection,
    NativeSession,
    NativeWitness,
    ObservationGrant,
    ObservationScope,
    ObservationSession,
    OccurrenceHandle,
    OperationKey,
    OperationLeg,
    PermissionHandle,
    Phase,
    QAReceiving,
    RawPublication,
    ReceiptProvenance,
    Refusal,
    RefusalCode,
    RequestIdentity,
    Result,
    RetryKind,
    ReviewedSourceGraph,
    RootBinding,
    RootObservation,
    RootObserver,
    RootScope,
    RowKey,
    SelectedHostJob,
    SelectedJob,
    SequenceUse,
    SharedN3,
    SourceClosureComparison,
    VerifiedReceiptBinding,
    WorkerObservation,
    WorkerObserver,
    compare_loaded_source,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    ImmutableReferenceRecord,
    PriorRequestHistory,
    boundary_to_phase,
    default_effect_for_job,
    make_refusal,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedRowOccurrence:
    """Actual row-scoped admission/execution occurrence state (D-1 before D-5)."""

    request_identity: RequestIdentity
    selection_revision: str
    request_raw_sha256: str
    occurrence: OccurrenceHandle
    admission_witness: NativeWitness
    admitted_binding: CurrentBinding
    executed_legs: tuple[OperationLeg, ...] = ()
    effect_state: EffectState = EffectState.ADMITTED_ONLY
    sequence_use: SequenceUse = SequenceUse.USED
    counted_idempotency_key: str | None = None


class EffectFenceProvider(Protocol):
    """Explicit row-scoped admission/execution/count fence provider.

    Missing provider fails closed with ``AUTHORITY_UNAVAILABLE``. Local database
    or in-memory implementations must not claim distributed effect enforcement.
    """

    def lookup_history(
        self,
        request_identity: RequestIdentity,
    ) -> PriorRequestHistory: ...

    def lookup_occurrence(
        self,
        request_identity: RequestIdentity,
    ) -> RecordedRowOccurrence | None: ...

    def record_admission(
        self,
        *,
        immutable_request_binding: ImmutableRequestBinding,
        current_binding: CurrentBinding,
        occurrence: OccurrenceHandle,
        admission_witness: NativeWitness,
    ) -> Result[RecordedRowOccurrence]: ...

    def record_execution_leg(
        self,
        *,
        request_identity: RequestIdentity,
        operation_leg: OperationLeg,
        current_binding: CurrentBinding,
        effect_state: EffectState = EffectState.COMPLETE,
    ) -> Result[RecordedRowOccurrence]: ...

    def mark_counted(
        self,
        *,
        request_identity: RequestIdentity,
        idempotency_identity: str,
        current_binding: CurrentBinding,
    ) -> Result[RecordedRowOccurrence]: ...


class QAReceivingVerifier(Protocol):
    """Explicit read-only verifier for exact QA receiving receipts."""

    def verify_qa_receiving(
        self,
        qa_receiving: QAReceiving,
        *,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Refusal | None: ...


class HostSessionPeerResolver(Protocol):
    """Read-only resolver mapping a ``NativeSession`` to an ``AuthenticatedPeer``."""

    def resolve_session_peer(
        self,
        session: NativeSession,
    ) -> AuthenticatedPeer | None: ...


class SystemsSourceClosureComparator(SharedN3):
    """``SharedN3`` adapter delegating comparison to ``p3_source_closure.compare_loaded_source``."""

    def __init__(
        self,
        *,
        comparator_fn: Callable[..., SourceClosureComparison]
        | None = compare_loaded_source,
        job_lookup: Callable[[str], SelectedJob | None] | None = None,
        peer_lookup: Callable[[str], NativeProcessRef | None] | None = None,
        expectation_lookup: (
            Callable[[str, Boundary], tuple[object, object] | None] | None
        ) = None,
    ) -> None:
        self._comparator_fn = comparator_fn
        self._job_lookup = job_lookup
        self._peer_lookup = peer_lookup
        self._expectation_lookup = expectation_lookup

    def compare(
        self,
        reviewed: ReviewedSourceGraph,
        observed: LoadedClosureEnvelope,
        *,
        selection: NativeSelection,
        boundary: Boundary,
    ) -> Result[SourceClosureComparison]:
        try:
            phase = boundary_to_phase(boundary)
        except ValueError:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        if (
            self._comparator_fn is None
            or self._job_lookup is None
            or self._peer_lookup is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if (
            type(reviewed) is not ReviewedSourceGraph
            or type(observed) is not LoadedClosureEnvelope
            or not hasattr(selection, "selection_revision")
        ):
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        selected_job = self._job_lookup(selection.selection_revision)
        process_ref = self._peer_lookup(selection.selection_revision)
        if selected_job is None or process_ref is None:
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        rev_graph_obj = getattr(reviewed, "graph", reviewed)
        obs_env_obj = getattr(observed, "envelope", observed)
        rev_schema = getattr(
            rev_graph_obj, "schema", getattr(rev_graph_obj, "schema_version", None)
        )
        obs_schema = getattr(
            obs_env_obj, "schema", getattr(obs_env_obj, "schema_version", None)
        )
        if (
            rev_schema != "p3-reviewed-source-graph/1"
            or obs_schema != "p3-reviewed-loaded-closure/1"
        ):
            return make_refusal(
                RefusalCode.CLOSURE_VERSION,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        try:
            exp_pair = (
                self._expectation_lookup(selection.selection_revision, boundary)
                if self._expectation_lookup is not None
                else None
            )
            if exp_pair is not None:
                expected, verified = exp_pair
                comparison = self._comparator_fn(
                    reviewed,
                    observed,
                    expected=expected,
                    verified=verified,
                )
            else:
                comparison = self._comparator_fn(
                    reviewed,
                    observed,
                    boundary=boundary,
                )
        except Exception:
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        disp = getattr(comparison, "disposition", getattr(comparison, "verdict", None))
        if disp in ("UNKNOWN", "INSUFFICIENT_OBSERVATION"):
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if disp != "MATCH":
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        effect = default_effect_for_job(selected_job, boundary)
        source_ref = ImmutableReferenceRecord(
            path=f"source/{selected_job.selection_revision}",
            digest=selected_job.expected_source_digest,
            length=64,
            revision=selected_job.selection_revision,
        )
        evidence = DecisionEvidenceRecord(
            selected_job=selected_job,
            authority_revisions=selected_job.authority_refs,
            window=None,
            processes=(process_ref,),
            effect=effect,
            phase=phase,
            boundary=boundary,
            source=source_ref,
            closure=selected_job.reviewed_closure_ref,
            compatibility=selected_job.compatibility_profile,
        )
        return AcceptedData(data=comparison, evidence=evidence)


class InMemoryEffectFenceProvider:
    """Explicit test-only row-scoped admission/execution/count fence."""

    def __init__(self, *, distributed_enforced: bool = False) -> None:
        if distributed_enforced:
            raise ValueError(
                "InMemoryEffectFenceProvider is a local test fence and cannot claim distributed enforcement"
            )
        self._occurrences: dict[RequestIdentity, RecordedRowOccurrence] = {}
        self._counted_keys: dict[str, RequestIdentity] = {}
        self._explicit_history: dict[RequestIdentity, PriorRequestHistory] = {}

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

    def _evidence(
        self,
        current_binding: CurrentBinding,
        actor: NativeProcessRef,
    ) -> DecisionEvidenceRecord:
        job = current_binding.selected_job
        source_ref = ImmutableReferenceRecord(
            path=f"source/{job.selection_revision}",
            digest=job.expected_source_digest,
            length=64,
            revision=job.selection_revision,
        )
        return DecisionEvidenceRecord(
            selected_job=job,
            authority_revisions=current_binding.authority_revisions,
            window=None,
            processes=(actor,),
            effect=current_binding.intended_effect,
            phase=boundary_to_phase(current_binding.boundary),
            boundary=current_binding.boundary,
            source=source_ref,
            closure=job.reviewed_closure_ref,
            compatibility=job.compatibility_profile,
        )

    def record_admission(
        self,
        *,
        immutable_request_binding: ImmutableRequestBinding,
        current_binding: CurrentBinding,
        occurrence: OccurrenceHandle,
        admission_witness: NativeWitness,
    ) -> Result[RecordedRowOccurrence]:
        req_id = immutable_request_binding.request_identity
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
                evidence=self._evidence(
                    current_binding,
                    immutable_request_binding.checker.checker,
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
            evidence=self._evidence(
                current_binding,
                immutable_request_binding.checker.checker,
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
            evidence=self._evidence(current_binding, operation_leg.actor),
        )

    def mark_counted(
        self,
        *,
        request_identity: RequestIdentity,
        idempotency_identity: str,
        current_binding: CurrentBinding,
    ) -> Result[RecordedRowOccurrence]:
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
        occ_obj: object = existing.occurrence
        actor = (
            existing.executed_legs[-1].actor
            if existing.executed_legs
            else cast(
                NativeProcessRef,
                getattr(
                    getattr(occ_obj, "controller", occ_obj),
                    "native_identity",
                    getattr(occ_obj, "controller", occ_obj),
                ),
            )
        )
        return AcceptedData(
            data=updated,
            evidence=self._evidence(current_binding, actor),
        )


class InMemoryQAReceivingVerifier:
    """Explicit test-only QA receiving verifier."""

    def __init__(self) -> None:
        self._allowed: dict[tuple[str, str], QAReceiving] = {}

    def register_qa_receiving(
        self,
        *,
        selection_revision: str,
        qa_receiving: QAReceiving,
    ) -> None:
        self._allowed[(selection_revision, qa_receiving.receiving_reference.digest)] = (
            qa_receiving
        )

    def verify_qa_receiving(
        self,
        qa_receiving: QAReceiving,
        *,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Refusal | None:
        phase = boundary_to_phase(boundary)
        if not hasattr(qa_receiving, "receiving_reference") or not hasattr(
            qa_receiving, "receiver"
        ):
            return make_refusal(
                RefusalCode.QA_RECEIVING_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        expected = self._allowed.get(
            (
                selected_job.selection_revision,
                qa_receiving.receiving_reference.digest,
            )
        )
        if expected is None or expected != qa_receiving:
            return make_refusal(
                RefusalCode.QA_RECEIVING_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return None


class InMemoryHostSessionPeerResolver:
    """Explicit test-only resolver mapping ``NativeSession.session_reference`` to ``AuthenticatedPeer``."""

    def __init__(self) -> None:
        self._sessions: dict[str, AuthenticatedPeer] = {}

    def register_session(
        self,
        session: NativeSession,
        peer: AuthenticatedPeer | None = None,
    ) -> None:
        resolved = peer if peer is not None else session.peer
        self._sessions[session.session_reference] = resolved

    def revoke_session(self, session: NativeSession) -> None:
        self._sessions.pop(session.session_reference, None)

    def resolve_session_peer(
        self,
        session: NativeSession,
    ) -> AuthenticatedPeer | None:
        if not hasattr(session, "session_reference") or not hasattr(session, "peer"):
            return None
        expected = self._sessions.get(session.session_reference)
        if expected is None or expected != session.peer:
            return None
        return expected


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionHandleRecord:
    """Concrete immutable ``PermissionHandle`` carrier."""

    observation_permission: str
    selection_revision: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationSessionRecord:
    """Concrete immutable ``ObservationSession`` carrier."""

    observation_session: str
    permission: PermissionHandle
    selection_revision: str = ""


class InMemoryHostObserver(HostObserver):
    """Explicit test-only ``HostObserver`` double."""

    def __init__(self) -> None:
        self._observations: dict[tuple[str, Boundary], HostObservation] = {}
        self._coverages: dict[tuple[str, Boundary], HostCoverage] = {}
        self._leases: dict[tuple[str, str], EffectLease] = {}
        self._witnesses: dict[tuple[str, Boundary], NativeWitness] = {}
        self._evidence_by_rev: dict[str, DecisionEvidenceRecord] = {}
        self._sessions: dict[str, tuple[SelectedHostJob, ObservationScope]] = {}

    def register_evidence(
        self,
        selection_revision: str,
        evidence: DecisionEvidenceRecord,
    ) -> None:
        self._evidence_by_rev[selection_revision] = evidence

    def register_observation(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
        observation: HostObservation,
        coverage: HostCoverage | None = None,
        witness: NativeWitness | None = None,
    ) -> None:
        self._observations[(selection_revision, boundary)] = observation
        if coverage is not None:
            self._coverages[(selection_revision, boundary)] = coverage
        if witness is not None:
            self._witnesses[(selection_revision, boundary)] = witness

    def register_lease(
        self,
        *,
        selection_revision: str,
        operation_id: str,
        lease: EffectLease,
    ) -> None:
        self._leases[(selection_revision, operation_id)] = lease

    def lookup_observation(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
    ) -> HostObservation | None:
        return self._observations.get((selection_revision, boundary))

    def lookup_witness(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
    ) -> NativeWitness | None:
        return self._witnesses.get((selection_revision, boundary))

    def begin(
        self,
        session: NativeSession,
        selection: SelectedHostJob,
        scope: ObservationScope,
        permission: PermissionHandle,
    ) -> Result[ObservationSession]:
        rev = selection.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if ev is None or scope.selection.selection_revision != rev:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        obs_session = ObservationSessionRecord(
            observation_session=f"obs:{permission.observation_permission}",
            permission=permission,
            selection_revision=rev,
        )
        self._sessions[obs_session.observation_session] = (selection, scope)
        return AcceptedData(data=obs_session, evidence=ev)

    def open(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        scope: ObservationScope,
    ) -> Result[ObservationSession]:
        rev = selected_job.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if ev is None or scope.selection.selection_revision != rev:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        grant_ref = getattr(
            getattr(grant, "grant", grant),
            "grant_reference",
            str(grant),
        )
        perm = PermissionHandleRecord(
            observation_permission=f"perm:{rev}:{grant_ref}",
            selection_revision=rev,
        )
        obs_session = ObservationSessionRecord(
            observation_session=f"obs:{rev}:{grant_ref}:{len(self._sessions) + 1}",
            permission=perm,
            selection_revision=rev,
        )
        return AcceptedData(data=obs_session, evidence=ev)

    def observe(
        self,
        session: ObservationSession,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[HostObservation]:
        phase = boundary_to_phase(boundary)
        rev = getattr(session, "selection_revision", "")
        if not rev:
            entry = self._sessions.get(session.observation_session)
            if entry is not None:
                rev = entry[0].selection.selection_revision
        obs = self._observations.get((rev, boundary))
        ev = self._evidence_by_rev.get(rev)
        if obs is None or ev is None:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(data=obs, evidence=ev)

    def checkpoint(
        self,
        session: ObservationSession,
        boundary: HostEffect,
    ) -> Result[HostCoverage]:
        phase = boundary_to_phase(boundary.boundary)
        entry = self._sessions.get(session.observation_session)
        if entry is None:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        selection, scope = entry
        rev = selection.selection.selection_revision
        if boundary not in scope.protected_effects:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        bnd = cast(Boundary, boundary.boundary)
        cov = self._coverages.get((rev, bnd))
        ev = self._evidence_by_rev.get(rev)
        if cov is None or ev is None:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(data=cov, evidence=ev)

    def before_effect(
        self,
        session: ObservationSession,
        effect: HostEffect,
        coverage: HostCoverage,
    ) -> Result[EffectLease]:
        phase = boundary_to_phase(effect.boundary)
        entry = self._sessions.get(session.observation_session)
        if entry is None:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        selection, scope = entry
        rev = selection.selection.selection_revision
        if effect not in scope.protected_effects:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            not getattr(coverage.observation, "coverage", None)
            or bool(getattr(coverage.observation, "gaps", None))
            or getattr(coverage.comparison, "disposition", None) != "MATCH"
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        lease = self._leases.get((rev, effect.operation))
        ev = self._evidence_by_rev.get(rev)
        if lease is None or ev is None:
            return make_refusal(
                RefusalCode.RIGHTS_MISSING,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=lease, evidence=ev)

    def finish(
        self,
        session: ObservationSession,
        boundary: HostEffect,
    ) -> Result[HostCoverage]:
        return self.checkpoint(session, boundary)

    def finish_witness(
        self,
        session: ObservationSession,
        boundary: Boundary,
    ) -> Result[NativeWitness]:
        phase = boundary_to_phase(boundary)
        rev = getattr(session, "selection_revision", "")
        if not rev:
            entry = self._sessions.get(session.observation_session)
            if entry is not None:
                rev = entry[0].selection.selection_revision
        witness = self._witnesses.get((rev, boundary))
        ev = self._evidence_by_rev.get(rev)
        if witness is None or ev is None:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(data=witness, evidence=ev)


class InMemoryHostProvenance(HostProvenance):
    """Explicit test-only ``HostProvenance`` double."""

    def __init__(self) -> None:
        self._occurrences: dict[OperationKey, OccurrenceHandle] = {}
        self._witnesses: dict[OperationKey, NativeWitness] = {}
        self._provenances: dict[tuple[OperationKey, str], ReceiptProvenance] = {}
        self._verified_receives: dict[
            tuple[OperationKey, str], VerifiedReceiptBinding
        ] = {}
        self._raw_payloads: dict[tuple[OperationKey, str], tuple[bytes, bytes]] = {}
        self._evidence_by_rev: dict[str, DecisionEvidenceRecord] = {}

    def register_evidence(
        self,
        selection_revision: str,
        evidence: DecisionEvidenceRecord,
    ) -> None:
        self._evidence_by_rev[selection_revision] = evidence

    def register_occurrence(
        self,
        key: OperationKey,
        occurrence: OccurrenceHandle,
        witness: NativeWitness | None = None,
    ) -> None:
        self._occurrences[key] = occurrence
        if witness is not None:
            self._witnesses[key] = witness
        else:
            self._witnesses[key] = occurrence.witness

    def record_witness(
        self,
        key: OperationKey,
        witness: NativeWitness,
    ) -> None:
        self._witnesses[key] = witness

    def register_publication_provenance(
        self,
        *,
        key: OperationKey,
        publication_sha256: str,
        provenance: ReceiptProvenance,
        verified_receive: VerifiedReceiptBinding | None = None,
        request_raw: bytes | None = None,
        receipt_raw: bytes | None = None,
    ) -> None:
        self._provenances[(key, publication_sha256)] = provenance
        if verified_receive is not None:
            self._verified_receives[(key, publication_sha256)] = verified_receive
        if request_raw is not None and receipt_raw is not None:
            self._raw_payloads[(key, publication_sha256)] = (request_raw, receipt_raw)

    def lookup_raw_payloads(
        self,
        key: OperationKey,
        publication_sha256: str,
    ) -> tuple[bytes, bytes] | None:
        return self._raw_payloads.get((key, publication_sha256))

    def lookup_witness(self, key: OperationKey) -> NativeWitness | None:
        return self._witnesses.get(key)

    def lookup_occurrence_handle(self, key: OperationKey) -> OccurrenceHandle | None:
        return self._occurrences.get(key)

    def note_admission(
        self,
        session: NativeSession,
        key: OperationKey,
        lease: EffectLease,
        admission_witness: NativeWitness,
    ) -> Result[OccurrenceHandle]:
        row_key_origin = getattr(RowKey, "__origin__", RowKey)
        phase = Phase.C if type(key) is row_key_origin else Phase.A
        occ = self._occurrences.get(key)
        rev = key.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if occ is None or ev is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        occ_wit = getattr(
            occ.witness, "witness_registration", occ.witness.witness_reference
        )
        adm_wit = getattr(
            admission_witness,
            "witness_registration",
            admission_witness.witness_reference,
        )
        if occ_wit != adm_wit:
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=occ, evidence=ev)

    def note_effect(
        self,
        session: NativeSession,
        occurrence: OccurrenceHandle,
        effect: HostEffect,
        witness: NativeWitness,
    ) -> Result[OccurrenceHandle]:
        row_key_origin = getattr(RowKey, "__origin__", RowKey)
        key = occurrence.key
        phase = Phase.C if type(key) is row_key_origin else Phase.A
        rev = key.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if ev is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        self._witnesses[key] = witness
        return AcceptedData(data=occurrence, evidence=ev)

    def bind_publication(
        self,
        session: NativeSession,
        occurrence: OccurrenceHandle,
        publication: RawPublication,
        witness: NativeWitness,
    ) -> Result[ReceiptProvenance]:
        row_key_origin = getattr(RowKey, "__origin__", RowKey)
        key = occurrence.key
        phase = Phase.C if type(key) is row_key_origin else Phase.A
        pub_ref = (
            publication.receipt_raw_ref
            if publication.receipt_raw_ref is not None
            else publication.request_raw_ref
        )
        if pub_ref is None:
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        pub_sha = pub_ref.sha256
        prov = self._provenances.get((key, pub_sha))
        rev = key.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if prov is None or ev is None:
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=prov, evidence=ev)

    def lookup_occurrence(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        key: OperationKey,
        lease: EffectLease,
        admission_witness: NativeWitness,
    ) -> Result[OccurrenceHandle]:
        row_key_origin = getattr(RowKey, "__origin__", RowKey)
        phase = Phase.C if type(key) is row_key_origin else Phase.A
        occ = self._occurrences.get(key)
        ev = self._evidence_by_rev.get(selected_job.selection_revision)
        if occ is None or ev is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if occ.key.selection.selection_revision != selected_job.selection_revision:
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        occ_wit = getattr(
            occ.witness, "witness_registration", occ.witness.witness_reference
        )
        adm_wit = getattr(
            admission_witness,
            "witness_registration",
            admission_witness.witness_reference,
        )
        if occ_wit != adm_wit:
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=occ, evidence=ev)

    def verify_publication(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        occurrence: OccurrenceHandle,
        publication: RawPublication,
        witness: NativeWitness,
    ) -> Result[ReceiptProvenance]:
        row_key_origin = getattr(RowKey, "__origin__", RowKey)
        key = occurrence.key
        phase = Phase.C if type(key) is row_key_origin else Phase.A
        pub_ref = (
            publication.receipt_raw_ref
            if publication.receipt_raw_ref is not None
            else publication.request_raw_ref
        )
        if pub_ref is None:
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        pub_sha = pub_ref.sha256
        prov = self._provenances.get((key, pub_sha))
        ev = self._evidence_by_rev.get(selected_job.selection_revision)
        if prov is None or ev is None:
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            prov.operation_key.selection.selection_revision
            != selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        prov_occ_wit = getattr(
            prov.occurrence_witness,
            "witness_registration",
            prov.occurrence_witness.witness_reference,
        )
        occ_wit = getattr(
            occurrence.witness,
            "witness_registration",
            occurrence.witness.witness_reference,
        )
        prov_pub_wit = getattr(
            prov.publication_witness,
            "witness_registration",
            prov.publication_witness.witness_reference,
        )
        pub_wit = getattr(witness, "witness_registration", witness.witness_reference)
        if prov_occ_wit != occ_wit or prov_pub_wit != pub_wit:
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            prov.state != "complete"
            or publication.cleanup_state not in ("not-required", "complete")
            or publication.outcome not in ("success", "app-failure", "host-failure")
            or occurrence.state not in ("completed", "failed")
            or prov.raw_publication != publication
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=prov, evidence=ev)

    def verify_received(
        self,
        session: NativeSession,
        key: OperationKey,
        request_raw: bytes,
        receipt_raw: bytes,
        provenance: ReceiptProvenance,
        boundary: HostEffect,
    ) -> Result[NativeReceive]:
        import hashlib

        phase = boundary_to_phase(boundary.boundary)
        pub_req_ref = provenance.raw_publication.request_raw_ref
        pub_rec_ref = (
            provenance.raw_publication.receipt_raw_ref
            or provenance.raw_publication.request_raw_ref
        )
        if (
            not request_raw
            or not receipt_raw
            or pub_req_ref is None
            or pub_rec_ref is None
            or pub_req_ref.sha256 != hashlib.sha256(request_raw).hexdigest()
            or pub_rec_ref.sha256 != hashlib.sha256(receipt_raw).hexdigest()
            or provenance.state != "complete"
            or provenance.raw_publication.cleanup_state
            not in ("not-required", "complete")
            or provenance.raw_publication.outcome
            not in ("success", "app-failure", "host-failure")
            or provenance.raw_publication.occurrence.state
            not in ("completed", "failed")
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        pub_sha = pub_rec_ref.sha256
        rec = self._verified_receives.get((key, pub_sha))
        rev = provenance.operation_key.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if rec is None or ev is None or rec.disposition != "verified":
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if rec.provenance != provenance or rec.operation_key != key:
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            provenance.predecessor is not None
            and rec.predecessor != provenance.predecessor
        ):
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=rec, evidence=ev)

    def receive_verified(
        self,
        *,
        key: OperationKey,
        provenance: ReceiptProvenance,
        boundary: HostEffect,
        phase: Phase,
    ) -> Result[VerifiedReceiptBinding]:
        pub_ref = (
            provenance.raw_publication.receipt_raw_ref
            if provenance.raw_publication.receipt_raw_ref is not None
            else provenance.raw_publication.request_raw_ref
        )
        if (
            pub_ref is None
            or provenance.state != "complete"
            or provenance.raw_publication.cleanup_state
            not in ("not-required", "complete")
            or provenance.raw_publication.outcome
            not in ("success", "app-failure", "host-failure")
            or provenance.raw_publication.occurrence.state
            not in ("completed", "failed")
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        pub_sha = pub_ref.sha256
        rec = self._verified_receives.get((key, pub_sha))
        if rec is None or rec.disposition != "verified":
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if rec.provenance != provenance or rec.operation_key != key:
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            provenance.predecessor is not None
            and rec.predecessor != provenance.predecessor
        ):
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        rev = provenance.operation_key.selection.selection_revision
        ev = self._evidence_by_rev.get(rev)
        if ev is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(data=rec, evidence=ev)


class InMemoryWorkerObserver(WorkerObserver):
    """Explicit test-only ``WorkerObserver`` double."""

    def __init__(self) -> None:
        self._observations: dict[tuple[str, Boundary], WorkerObservation] = {}
        self._evidence_by_rev: dict[str, DecisionEvidenceRecord] = {}

    def register_worker_observation(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
        observation: WorkerObservation,
        evidence: DecisionEvidenceRecord | None = None,
    ) -> None:
        self._observations[(selection_revision, boundary)] = observation
        if evidence is not None:
            self._evidence_by_rev[selection_revision] = evidence

    def lookup_worker_observation(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
    ) -> WorkerObservation | None:
        return self._observations.get((selection_revision, boundary))

    def observe(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[WorkerObservation]:
        phase = boundary_to_phase(boundary)
        obs = self._observations.get((selected_job.selection_revision, boundary))
        ev = self._evidence_by_rev.get(selected_job.selection_revision)
        if obs is None or ev is None:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(data=obs, evidence=ev)


class InMemoryRootObserver(RootObserver):
    """Explicit test-only ``RootObserver`` double."""

    def __init__(self) -> None:
        self._roots: dict[tuple[str, str], RootObservation] = {}
        self._root_bindings: dict[tuple[str, Boundary], RootBinding] = {}
        self._evidence_by_proc: dict[str, DecisionEvidenceRecord] = {}

    def register_root_binding(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
        binding: RootBinding,
    ) -> None:
        self._root_bindings[(selection_revision, boundary)] = binding

    def lookup_root_binding(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
    ) -> RootBinding | None:
        return self._root_bindings.get((selection_revision, boundary))

    def register_root_observation(
        self,
        *,
        process_registration: str,
        root_kind: str,
        observation: RootObservation,
        evidence: DecisionEvidenceRecord | None = None,
    ) -> None:
        self._roots[(process_registration, root_kind)] = observation
        if evidence is not None:
            self._evidence_by_proc[process_registration] = evidence

    def lookup_root_observation(
        self,
        *,
        process_registration: str,
        root_kind: str,
    ) -> RootObservation | None:
        return self._roots.get((process_registration, root_kind))

    def observe(
        self,
        grant: ObservationGrant,
        actor_instance: NativeProcessRef,
        selected_root: RootScope,
        required_operations: EffectSet,
        boundary: Boundary,
    ) -> Result[RootObservation]:
        phase = boundary_to_phase(boundary)
        obs = self._roots.get((actor_instance.process_registration, selected_root.role))
        ev = self._evidence_by_proc.get(actor_instance.process_registration)
        if obs is None or ev is None:
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return AcceptedData(data=obs, evidence=ev)


__all__ = [
    "EffectFenceProvider",
    "HostSessionPeerResolver",
    "InMemoryEffectFenceProvider",
    "InMemoryHostObserver",
    "InMemoryHostProvenance",
    "InMemoryHostSessionPeerResolver",
    "InMemoryQAReceivingVerifier",
    "InMemoryRootObserver",
    "InMemoryWorkerObserver",
    "ObservationSessionRecord",
    "PermissionHandleRecord",
    "QAReceivingVerifier",
    "RecordedRowOccurrence",
    "SystemsSourceClosureComparator",
]
