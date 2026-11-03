"""P3 native boundary and host-join composition service (`P3NativeBoundary` + `NativeHostJoin`).

Implements the canonical ``P3NativeBoundary`` (6 boundary methods) and
``NativeHostJoin`` (9 host-join adapter methods) over a single service instance,
delegating authority/selection checks to ``P3AuthorityRegistry`` and source-closure
comparison to Systems' ``p3_source_closure.compare_loaded_source`` via ``SharedN3``.
All providers default to ``None`` and fail closed with ``AUTHORITY_UNAVAILABLE``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from temper_ai.p3_authority._providers import (
    EffectFenceProvider,
    HostSessionPeerResolver,
    InMemoryEffectFenceProvider,
    InMemoryHostObserver,
    InMemoryHostProvenance,
    InMemoryHostSessionPeerResolver,
    InMemoryQAReceivingVerifier,
    InMemoryRootObserver,
    InMemoryWorkerObserver,
    ObservationSessionRecord,
    PermissionHandleRecord,
    QAReceivingVerifier,
    RecordedRowOccurrence,
    SystemsSourceClosureComparator,
)
from temper_ai.p3_authority.candidate_bindings import (
    CallerPeerProvider,
    CandidateCaptureAdapter,
    P3CandidateBindings,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    ActualRequestAndReceipt,
    AdmissionDecision,
    AdmissionState,
    AdmittedRequestBinding,
    AuthenticatedPeer,
    AuthorityRef,
    BothRootObservations,
    Boundary,
    CalibrationSelection,
    CallerSelection,
    CheckerBinding,
    CheckerDecision,
    CompatibilityReceiving,
    CountDecision,
    CreateArmDecision,
    CurrentBinding,
    CurrentObservationCursors,
    DecisionEvidence,
    DispatchIdentity,
    EffectLease,
    EffectState,
    ExecutionDecision,
    HostCalibrationSelection,
    HostCoverage,
    HostEffect,
    HostObservation,
    HostObserver,
    HostProjectSelection,
    HostProvenance,
    ImmutableReference,
    ImmutableRequestBinding,
    LifecycleKey,
    LoadedClosureEnvelope,
    N3ObservationEpoch,
    NativeHostJoin,
    NativeProcessRef,
    NativeReceive,
    NativeSelection,
    NativeSession,
    NativeSubject,
    NativeWitness,
    ObservationScope,
    ObservationSession,
    OccurrenceHandle,
    OperationKey,
    OperationLeg,
    P3AuthorityRegistry,
    P3NativeBoundary,
    P5Assessment,
    PermissionHandle,
    Phase,
    ProjectSelection,
    QAReceiving,
    RawPublication,
    RawRef,
    ReceiptProducerBinding,
    ReceiptProvenance,
    Refusal,
    RefusalCode,
    RequestDecision,
    RequestIdentity,
    Result,
    RetryKind,
    ReviewedSourceGraph,
    RootBinding,
    RootObserver,
    RowKey,
    SelectedHostJob,
    SelectedJob,
    SelectedOperation,
    SequenceUse,
    SharedN3,
    SourceClosureComparison,
    VerifiedReceiptBinding,
    WindowBinding,
    WorkerObservation,
    WorkerObserver,
)
from temper_ai.p3_authority.host_ports import (
    LINKED_RECEIPT_BOUNDARIES,
    require_port_members,
)
from temper_ai.p3_authority.issuer_verifier import (
    PRODUCTION_ANCHOR_TABLE,
    PRODUCTION_TRUST_ANCHORS,
    AnchorEntry,
    AnchorTable,
    Ed25519IssuerVerifier,
    EnvelopeStore,
    PinnedPeerVerifier,
)
from temper_ai.p3_authority.linked_receipt_rules import (
    continuation_predecessor_refusal,
    exact_receipt_equal,
    linked_predecessor_mismatch,
)
from temper_ai.p3_authority.registry import (
    COMPATIBILITY_CORPUS_SCHEMA,
    AuthorityRegistryService,
    DecisionEvidenceRecord,
    ExistingSubjectRecord,
    ImmutableReferenceRecord,
    IssuerVerifier,
    PeerVerifierProtocol,
    PriorRequestHistory,
    RequestHistoryProvider,
    SelectionSnapshotProvider,
    boundary_to_phase,
    default_effect_for_job,
    make_refusal,
)
from temper_ai.runner.admission import (
    CandidateBindings,
    InstallationVerifier,
    PreparationVerifier,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _HostSelectionHandle:
    """Internal ``NativeSelection`` carrier for host-join selections."""

    selection_reference: str
    selection_revision: str


_HOST_OBSERVATION_CLS = getattr(HostObservation, "__origin__", HostObservation)
_ROOT_BINDING_CLS = getattr(RootBinding, "__origin__", RootBinding)
_ROW_KEY_CLS = getattr(RowKey, "__origin__", RowKey)
_LIFECYCLE_KEY_CLS = getattr(LifecycleKey, "__origin__", LifecycleKey)


def _wit_ref(w: object) -> str:
    val = getattr(w, "witness_registration", None) or getattr(
        w, "witness_reference", ""
    )
    return val if isinstance(val, str) else ""


def _proc_ref_str(proc: object) -> str:
    val = getattr(proc, "process_registration", None)
    if not (type(val) is str and val != ""):
        val = getattr(proc, "process_reference", "")
    return val if type(val) is str and val != "" else ""


def _proc_from_actor(actor: object) -> NativeProcessRef:
    return cast(NativeProcessRef, getattr(actor, "native_identity", actor))


def _peer_ref_str(peer: object) -> str:
    val = getattr(peer, "peer_registration", None)
    if not (type(val) is str and val != ""):
        val = getattr(peer, "peer_reference", "")
    return val if type(val) is str and val != "" else ""


_RECEIPT_PROVENANCE_CLS = getattr(ReceiptProvenance, "__origin__", ReceiptProvenance)
_SELECTED_HOST_JOB_CLS = getattr(SelectedHostJob, "__origin__", SelectedHostJob)
_OBSERVATION_SCOPE_CLS = getattr(ObservationScope, "__origin__", ObservationScope)
_HOST_EFFECT_CLS = getattr(HostEffect, "__origin__", HostEffect)
_HOST_COVERAGE_CLS = getattr(HostCoverage, "__origin__", HostCoverage)
_EFFECT_LEASE_CLS = getattr(EffectLease, "__origin__", EffectLease)
_OCCURRENCE_HANDLE_CLS = getattr(OccurrenceHandle, "__origin__", OccurrenceHandle)
_RAW_PUBLICATION_CLS = getattr(RawPublication, "__origin__", RawPublication)
_VERIFIED_RECEIPT_BINDING_CLS = getattr(
    VerifiedReceiptBinding, "__origin__", VerifiedReceiptBinding
)


def _retry_kind_for(code: RefusalCode) -> RetryKind:
    """PRIOR_MISSING may pass after the missing record arrives; the rest never retry."""
    if code is RefusalCode.PRIOR_MISSING:
        return RetryKind.SAME_BOUNDARY_AFTER_REPAIR
    return RetryKind.NOT_APPLICABLE


def _caller_predecessor_refusal_code(
    key: OperationKey,
    predecessor: ReceiptProvenance | None,
    selection_revision: str,
) -> RefusalCode | None:
    """The service's own checks on the predecessor a caller's receipt names.

    Shape only: whether the predecessor is linked in the window's chain is the
    port's answer (``HostProvenance.verify_linked_receipt``), never this one.
    Foreign selection, window or writer -> PRIOR_FOREIGN; a later or same
    request, a failed or incomplete receipt -> PRIOR_UNVERIFIED; then the
    continuation rule (``REQUIRED_PREDECESSOR_ROW``): none -> PRIOR_MISSING.
    """
    if predecessor is not None:
        if type(predecessor) is not _RECEIPT_PROVENANCE_CLS:
            return RefusalCode.PRIOR_UNVERIFIED
        pred_pub = predecessor.raw_publication
        pred_occ = pred_pub.occurrence
        pred_key = predecessor.operation_key
        if pred_key.selection.selection_revision != selection_revision:
            return RefusalCode.PRIOR_FOREIGN
        if type(pred_key) is _ROW_KEY_CLS and type(key) is _ROW_KEY_CLS:
            pred_row_key = cast(RequestIdentity, pred_key)
            row_key = cast(RequestIdentity, key)
            if (
                pred_row_key.window_id != row_key.window_id
                or pred_row_key.writer != row_key.writer
            ):
                return RefusalCode.PRIOR_FOREIGN
            if (
                pred_row_key.sequence >= row_key.sequence
                or pred_row_key.request_id == row_key.request_id
            ):
                return RefusalCode.PRIOR_UNVERIFIED
        # A failed receipt (app-failure, host-failure, occurrence failed) is
        # not a success, so the one check below refuses it too.
        if (
            predecessor.state != "complete"
            or pred_pub.outcome != "success"
            or pred_pub.cleanup_state not in ("not-required", "complete")
            or pred_occ.state != "completed"
            or pred_occ.key != pred_key
        ):
            return RefusalCode.PRIOR_UNVERIFIED
    return continuation_predecessor_refusal(key, predecessor)


def _linked_binding_refusal_code(
    binding: object,
    key: OperationKey,
    provenance: ReceiptProvenance,
    publication: RawPublication,
) -> RefusalCode | None:
    """Ruling C4: the port's binding is for exactly this receipt, else refuse.

    Predecessor exact both ways (ruling C2); any other mismatch ->
    RESULT_UNVERIFIED.
    """
    if type(binding) is not _VERIFIED_RECEIPT_BINDING_CLS:
        return RefusalCode.RESULT_UNVERIFIED
    verified = cast(VerifiedReceiptBinding, binding)
    if verified.disposition != "verified":
        return RefusalCode.RESULT_UNVERIFIED
    predecessor_code = linked_predecessor_mismatch(
        provenance.predecessor, verified.predecessor
    )
    if predecessor_code is not None:
        return predecessor_code
    if (
        verified.selection != key.selection
        or verified.operation_key != key
        or not exact_receipt_equal(verified.provenance, provenance)
        or verified.publication != publication
        or verified.occurrence != publication.occurrence
        or not _wit_ref(verified.receiving)
    ):
        return RefusalCode.RESULT_UNVERIFIED
    return None


DEFAULT_P3_ALLOWED_ROWS: frozenset[str] = frozenset(
    {"row-1", "row-2", "row-01", "row-02"}
)


class P3AuthorityService(P3NativeBoundary, NativeHostJoin):
    """Unified P3 authority boundary and host-join service.

    Exposes both the 6 ``P3NativeBoundary`` methods and the 9 ``NativeHostJoin``
    methods over the same authority registry, closure comparator, and observer/fence
    providers. Production defaults remain inert (`None` providers refuse fail-closed,
    and ``writes_enabled`` is ``False``).
    """

    def __init__(
        self,
        *,
        registry: P3AuthorityRegistry | None = None,
        closure_comparator: SharedN3 | None = None,
        host_observer: HostObserver | None = None,
        worker_observer: WorkerObserver | None = None,
        root_observer: RootObserver | None = None,
        host_provenance: HostProvenance | None = None,
        effect_fence_provider: EffectFenceProvider | None = None,
        qa_receiving_verifier: QAReceivingVerifier | None = None,
        session_peer_resolver: HostSessionPeerResolver | None = None,
        reviewed_graphs: dict[str, ReviewedSourceGraph] | None = None,
        allowed_rows_by_revision: dict[str, frozenset[str]] | None = None,
        writes_enabled: bool = False,
        refuse_count_as_write_disabled: bool = False,
    ) -> None:
        # Structural check of the host ports at composition (fail loud): an
        # adapter needs every member the service calls, never a double's base.
        if host_observer is not None:
            require_port_members(host_observer, HostObserver, role="host_observer")
        if host_provenance is not None:
            require_port_members(
                host_provenance, HostProvenance, role="host_provenance"
            )
        self._registry = registry
        self._closure_comparator = closure_comparator
        self._host_observer = host_observer
        self._worker_observer = worker_observer
        self._root_observer = root_observer
        self._host_provenance = host_provenance
        self._effect_fence_provider = effect_fence_provider
        self._qa_receiving_verifier = qa_receiving_verifier
        self._session_peer_resolver = session_peer_resolver
        self._reviewed_graphs: dict[str, ReviewedSourceGraph] = dict(
            reviewed_graphs or {}
        )
        self._allowed_rows_by_revision: dict[str, frozenset[str]] = dict(
            allowed_rows_by_revision or {}
        )
        self._closure_inputs: dict[
            tuple[str, Boundary],
            tuple[ReviewedSourceGraph, LoadedClosureEnvelope, N3ObservationEpoch],
        ] = {}
        # Source composition keeps writes permanently disabled (false).
        _ = writes_enabled
        self._writes_enabled = False
        self._refuse_count_as_write_disabled = bool(refuse_count_as_write_disabled)
        self._granted_permissions: dict[
            str,
            tuple[
                PermissionHandle,
                NativeSession,
                AuthenticatedPeer,
                SelectedHostJob,
                ObservationScope,
                CurrentBinding,
            ],
        ] = {}
        self._opened_observation_sessions: dict[
            str,
            tuple[
                ObservationSession, AuthenticatedPeer, ObservationScope, CurrentBinding
            ],
        ] = {}
        self._host_join_adapter = NativeHostJoinAdapter(self)

    @property
    def writes_enabled(self) -> bool:
        return self._writes_enabled

    @property
    def host_join(self) -> NativeHostJoin:
        return self._host_join_adapter

    def register_reviewed_graph(
        self,
        selection_revision: str,
        reviewed_graph: ReviewedSourceGraph,
    ) -> None:
        self._reviewed_graphs[selection_revision] = reviewed_graph

    def register_allowed_rows(
        self,
        selection_revision: str,
        allowed_rows: frozenset[str] | set[str] | tuple[str, ...],
    ) -> None:
        self._allowed_rows_by_revision[selection_revision] = frozenset(allowed_rows)

    def _lookup_reviewed_graph(
        self,
        selection_revision: str,
    ) -> ReviewedSourceGraph | None:
        graph = self._reviewed_graphs.get(selection_revision)
        if graph is not None:
            return graph
        for (rev, _bnd), (reg_graph, _env, _epoch) in self._closure_inputs.items():
            if rev == selection_revision:
                return reg_graph
        return None

    def register_closure_inputs(
        self,
        *,
        selection_revision: str,
        boundary: Boundary,
        reviewed_graph: ReviewedSourceGraph,
        loaded_closure: LoadedClosureEnvelope,
        observation_epoch: N3ObservationEpoch,
    ) -> None:
        self._reviewed_graphs[selection_revision] = reviewed_graph
        self._closure_inputs[(selection_revision, boundary)] = (
            reviewed_graph,
            loaded_closure,
            observation_epoch,
        )

    def compare_source_closure(
        self,
        *,
        reviewed_graph: ReviewedSourceGraph,
        loaded_closure: LoadedClosureEnvelope,
        boundary: Boundary,
        observation_epoch: N3ObservationEpoch,
        selection: NativeSelection | None = None,
    ) -> Result[SourceClosureComparison]:
        phase = boundary_to_phase(boundary)
        if self._closure_comparator is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=self._history_for(None),
            )
        sel = selection or _HostSelectionHandle(
            selection_reference=f"sel:{observation_epoch.collector_ref}",
            selection_revision=str(observation_epoch.collector_ref),
        )
        return self._closure_comparator.compare(
            reviewed_graph,
            loaded_closure,
            selection=sel,
            boundary=boundary,
        )

    def _history_for(
        self,
        request_identity: RequestIdentity | None,
        *,
        default_sequence: SequenceUse = SequenceUse.NOT_APPLICABLE,
    ) -> PriorRequestHistory:
        if request_identity is not None and self._effect_fence_provider is not None:
            return self._effect_fence_provider.lookup_history(request_identity)
        return PriorRequestHistory(
            admission_state=AdmissionState.NOT_ADMITTED,
            effect_state=EffectState.NONE,
            sequence_use=default_sequence,
        )

    def _evidence(
        self,
        *,
        current: CurrentBinding,
        processes: tuple[NativeProcessRef, ...],
        window: NativeSubject | None = None,
        receiving: tuple[ImmutableReference, ...] = (),
    ) -> DecisionEvidence:
        job = current.selected_job
        source_ref = ImmutableReferenceRecord(
            path=f"source/{job.selection_revision}",
            digest=job.expected_source_digest,
            length=64,
            revision=job.selection_revision,
        )
        return DecisionEvidenceRecord(
            selected_job=job,
            authority_revisions=current.authority_revisions,
            window=window,
            processes=processes,
            effect=current.intended_effect,
            phase=boundary_to_phase(current.boundary),
            boundary=current.boundary,
            source=source_ref,
            closure=job.reviewed_closure_ref,
            compatibility=job.compatibility_profile,
            receiving=receiving,
        )

    # ------------------------------------------------------------------
    # P3NativeBoundary (6 boundary methods)
    # ------------------------------------------------------------------

    def before_create(
        self,
        peer: AuthenticatedPeer,
        selected_job: SelectedJob,
        creator_observation: HostObservation,
        parent_access_observation: RootBinding,
        bootstrap_comparison: SourceClosureComparison,
    ) -> Result[CreateArmDecision]:
        phase = Phase.A
        boundary: Boundary = "A_PRE_CREATE"
        history = self._history_for(None)

        if (
            self._registry is None
            or self._host_observer is None
            or self._root_observer is None
            or self._closure_comparator is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(selected_job) is not SelectedJob
            or type(creator_observation) is not _HOST_OBSERVATION_CLS
            or type(parent_access_observation) is not _ROOT_BINDING_CLS
            or type(bootstrap_comparison) is not SourceClosureComparison
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        intended_effect = default_effect_for_job(selected_job, boundary)
        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            intended_effect,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        if (
            creator_observation.selection.selection_revision
            != selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if (
            not creator_observation.process_instances
            or not creator_observation.coverage
            or creator_observation.gaps
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        creator_proc = _proc_from_actor(creator_observation.process_instances[0])
        parent_proc = _proc_from_actor(parent_access_observation.actor_instance)
        if (
            not _proc_ref_str(parent_proc)
            or not _proc_ref_str(creator_proc)
            or _proc_ref_str(parent_proc) != _proc_ref_str(creator_proc)
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        expected_host_obs = self._host_observer.lookup_observation(
            selection_revision=selected_job.selection_revision,
            boundary=boundary,
        )
        if expected_host_obs is None or expected_host_obs != creator_observation:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        lookup_root_bind = getattr(self._root_observer, "lookup_root_binding", None)
        expected_root_bind = (
            lookup_root_bind(
                selection_revision=selected_job.selection_revision,
                boundary=boundary,
            )
            if lookup_root_bind is not None
            else None
        )
        if (
            expected_root_bind is None
            or expected_root_bind != parent_access_observation
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if bootstrap_comparison.boundary.phase != boundary:
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        registered_closure = self._closure_inputs.get(
            (selected_job.selection_revision, boundary)
        )
        if registered_closure is None:
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        rev_graph, loaded_env, _obs_epoch = registered_closure
        recomputed = self._closure_comparator.compare(
            rev_graph,
            loaded_env,
            selection=_HostSelectionHandle(
                selection_reference=f"sel:{selected_job.selection_revision}",
                selection_revision=selected_job.selection_revision,
            ),
            boundary=boundary,
        )
        if isinstance(recomputed, Refusal):
            return make_refusal(
                recomputed.code,
                phase=phase,
                retry_kind=recomputed.retry_kind,
                history=history,
            )
        if recomputed.data != bootstrap_comparison:
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if bootstrap_comparison.disposition == "UNKNOWN":
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if bootstrap_comparison.disposition != "MATCH":
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        decision = CreateArmDecision(
            current=current,
            creator=creator_proc,
            parent=parent_access_observation,
        )
        return AcceptedData(
            data=decision,
            evidence=self._evidence(
                current=current,
                processes=(peer.process, creator_proc),
            ),
        )

    def before_checker(
        self,
        peer: AuthenticatedPeer,
        window_binding: WindowBinding,
        host_observation: HostObservation,
        worker_observation: WorkerObservation,
        both_root_observations: BothRootObservations,
        closure_comparison: SourceClosureComparison,
        qa_receiving: QAReceiving,
        compatibility_receiving: CompatibilityReceiving,
        receipt_producer_binding: ReceiptProducerBinding,
    ) -> Result[CheckerDecision]:
        phase = Phase.A
        boundary: Boundary = "A_PRE_ARM"
        history = self._history_for(None)

        if (
            self._registry is None
            or self._host_observer is None
            or self._worker_observer is None
            or self._root_observer is None
            or self._closure_comparator is None
            or self._qa_receiving_verifier is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(window_binding) is not WindowBinding
            or type(host_observation) is not _HOST_OBSERVATION_CLS
            or type(worker_observation) is not WorkerObservation
            or type(both_root_observations) is not BothRootObservations
            or type(closure_comparison) is not SourceClosureComparison
            or not hasattr(qa_receiving, "receiving_reference")
            or not hasattr(compatibility_receiving, "corpus")
            or not hasattr(receipt_producer_binding, "producer")
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        selected_job = window_binding.current.selected_job
        if (
            compatibility_receiving.corpus != COMPATIBILITY_CORPUS_SCHEMA
            or selected_job.compatibility_profile.corpus != COMPATIBILITY_CORPUS_SCHEMA
        ):
            return make_refusal(
                RefusalCode.COMPATIBILITY_UNQUALIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        qa_refusal = self._qa_receiving_verifier.verify_qa_receiving(
            qa_receiving,
            selected_job=selected_job,
            boundary=boundary,
        )
        if qa_refusal is not None:
            return qa_refusal

        intended_effect = default_effect_for_job(selected_job, boundary)
        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            intended_effect,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        if isinstance(self._registry, AuthorityRegistryService):
            bound_win = self._registry._created_windows.get(
                window_binding.actual_creation.window_id
            )
            if (
                bound_win is None
                or bound_win.actual_creation != window_binding.actual_creation
                or bound_win.current.selected_job.selection_revision
                != selected_job.selection_revision
            ):
                return make_refusal(
                    RefusalCode.WINDOW_INELIGIBLE,
                    phase=phase,
                    retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                    history=history,
                )

        if (
            host_observation.selection.selection_revision
            != selected_job.selection_revision
            or worker_observation.selection_revision != selected_job.selection_revision
            or worker_observation.job != selected_job
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            not host_observation.process_instances
            or not host_observation.coverage
            or host_observation.gaps
            or not worker_observation.checker_instances
            or not worker_observation.load_stream_refs
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        expected_host_obs = self._host_observer.lookup_observation(
            selection_revision=selected_job.selection_revision,
            boundary=boundary,
        )
        lookup_worker_obs = getattr(
            self._worker_observer, "lookup_worker_observation", None
        )
        expected_worker_obs = (
            lookup_worker_obs(
                selection_revision=selected_job.selection_revision,
                boundary=boundary,
            )
            if lookup_worker_obs is not None
            else None
        )
        if (
            expected_host_obs is None
            or expected_host_obs != host_observation
            or expected_worker_obs is None
            or expected_worker_obs != worker_observation
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        pub_root = both_root_observations.publication
        ev_root = both_root_observations.host_evidence
        if (
            pub_root.root_kind != "publication"
            or ev_root.root_kind != "host_evidence"
            or pub_root.observation_boundary not in ("A_PRE_CREATE", "A_PRE_ARM")
            or ev_root.observation_boundary not in ("A_PRE_CREATE", "A_PRE_ARM")
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        lookup_root_obs = getattr(self._root_observer, "lookup_root_observation", None)
        pub_actor_reg = _proc_ref_str(_proc_from_actor(pub_root.binding.actor_instance))
        ev_actor_reg = _proc_ref_str(_proc_from_actor(ev_root.binding.actor_instance))
        expected_pub_root = (
            lookup_root_obs(
                process_registration=pub_actor_reg,
                root_kind="publication",
            )
            if lookup_root_obs is not None
            else None
        )
        expected_ev_root = (
            lookup_root_obs(
                process_registration=ev_actor_reg,
                root_kind="host_evidence",
            )
            if lookup_root_obs is not None
            else None
        )
        if (
            expected_pub_root is None
            or expected_pub_root != pub_root
            or expected_ev_root is None
            or expected_ev_root != ev_root
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if closure_comparison.boundary.phase != boundary:
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        registered_closure = self._closure_inputs.get(
            (selected_job.selection_revision, boundary)
        )
        if registered_closure is None:
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        rev_graph, loaded_env, _obs_epoch = registered_closure
        recomputed = self._closure_comparator.compare(
            rev_graph,
            loaded_env,
            selection=_HostSelectionHandle(
                selection_reference=f"sel:{selected_job.selection_revision}",
                selection_revision=selected_job.selection_revision,
            ),
            boundary=boundary,
        )
        if isinstance(recomputed, Refusal):
            return make_refusal(
                recomputed.code,
                phase=phase,
                retry_kind=recomputed.retry_kind,
                history=history,
            )
        if recomputed.data != closure_comparison:
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if closure_comparison.disposition == "UNKNOWN":
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if closure_comparison.disposition != "MATCH":
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        raw_checker = worker_observation.checker_instances[0]
        checker_proc = _proc_from_actor(raw_checker)
        updated_window = WindowBinding(
            current=current,
            actual_creation=window_binding.actual_creation,
        )
        checker_binding = CheckerBinding(
            window=updated_window,
            checker=checker_proc,
            both_roots=both_root_observations,
            producer=receipt_producer_binding,
        )
        window_subject = ExistingSubjectRecord(
            identity=window_binding.actual_creation.object_identity
        )
        return AcceptedData(
            data=CheckerDecision(binding=checker_binding),
            evidence=self._evidence(
                current=current,
                processes=(
                    peer.process,
                    checker_proc,
                    receipt_producer_binding.producer,
                ),
                window=window_subject,
            ),
        )

    def before_request(
        self,
        peer: AuthenticatedPeer,
        checker_binding: CheckerBinding,
        row: str,
        request_identity: RequestIdentity,
        current_observation_cursors: CurrentObservationCursors,
    ) -> Result[RequestDecision]:
        phase = Phase.B
        boundary: Boundary = "B_PRE_REQUEST"
        req_id = request_identity if type(request_identity) is _ROW_KEY_CLS else None
        history = self._history_for(req_id, default_sequence=SequenceUse.UNUSED)

        if (
            self._registry is None
            or self._host_observer is None
            or self._worker_observer is None
            or self._effect_fence_provider is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(checker_binding) is not CheckerBinding
            or not isinstance(row, str)
            or not row.strip()
            or type(request_identity) is not _ROW_KEY_CLS
            or type(current_observation_cursors) is not CurrentObservationCursors
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            request_identity.row != row
            or request_identity.window_id
            != checker_binding.window.actual_creation.window_id
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        selected_job = checker_binding.window.current.selected_job
        if (
            request_identity.selection.selection_revision
            != selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            not current_observation_cursors.host
            or not current_observation_cursors.worker
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        intended_effect = default_effect_for_job(selected_job, boundary)
        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            intended_effect,
            request_identity,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        request_raw = request_identity.request_raw_ref
        immutable_binding = ImmutableRequestBinding(
            checker=checker_binding,
            request_identity=request_identity,
            request_raw=request_raw,
        )
        window_subject = ExistingSubjectRecord(
            identity=checker_binding.window.actual_creation.object_identity
        )
        return AcceptedData(
            data=RequestDecision(binding=immutable_binding),
            evidence=self._evidence(
                current=current,
                processes=(peer.process, checker_binding.checker),
                window=window_subject,
            ),
        )

    def before_admit(
        self,
        peer: AuthenticatedPeer,
        immutable_request_binding: ImmutableRequestBinding,
        current_observation_cursors: CurrentObservationCursors,
    ) -> Result[AdmissionDecision]:
        phase = Phase.B
        boundary: Boundary = "C_PRE_REQUEST"
        req_id = (
            immutable_request_binding.request_identity
            if type(immutable_request_binding) is ImmutableRequestBinding
            else None
        )
        history = self._history_for(req_id, default_sequence=SequenceUse.UNUSED)

        if (
            self._registry is None
            or self._host_observer is None
            or self._worker_observer is None
            or self._host_provenance is None
            or self._effect_fence_provider is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(immutable_request_binding) is not ImmutableRequestBinding
            or type(current_observation_cursors) is not CurrentObservationCursors
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            not current_observation_cursors.host
            or not current_observation_cursors.worker
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        selected_job = immutable_request_binding.checker.window.current.selected_job
        if (
            immutable_request_binding.request_identity.window_id
            != immutable_request_binding.checker.window.actual_creation.window_id
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if (
            immutable_request_binding.request_identity.selection.selection_revision
            != selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        intended_effect = default_effect_for_job(selected_job, boundary)
        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            intended_effect,
            immutable_request_binding.request_identity,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        window_subject = ExistingSubjectRecord(
            identity=immutable_request_binding.checker.window.actual_creation.object_identity
        )
        return AcceptedData(
            data=AdmissionDecision(
                binding=immutable_request_binding,
                current=current,
            ),
            evidence=self._evidence(
                current=current,
                processes=(peer.process, immutable_request_binding.checker.checker),
                window=window_subject,
            ),
        )

    def record_admitted_occurrence(
        self,
        *,
        immutable_request_binding: ImmutableRequestBinding,
        current_binding: CurrentBinding,
        occurrence: OccurrenceHandle,
        admission_witness: NativeWitness,
    ) -> Result[AdmittedRequestBinding]:
        """Record actual D-1 occurrence in the injected fence provider and return ``AdmittedRequestBinding``."""
        phase = Phase.B
        req_id = immutable_request_binding.request_identity
        history = self._history_for(req_id, default_sequence=SequenceUse.UNUSED)
        if self._effect_fence_provider is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        rec_res = self._effect_fence_provider.record_admission(
            immutable_request_binding=immutable_request_binding,
            current_binding=current_binding,
            occurrence=occurrence,
            admission_witness=admission_witness,
        )
        if isinstance(rec_res, Refusal):
            return rec_res
        admitted = AdmittedRequestBinding(
            request=immutable_request_binding,
            occurrence=occurrence,
            admission_witness=admission_witness,
        )
        return AcceptedData(data=admitted, evidence=rec_res.evidence)

    def before_execute(
        self,
        peer: AuthenticatedPeer,
        admitted_request_binding: AdmittedRequestBinding,
        operation_leg: OperationLeg,
        current_observation_cursors: CurrentObservationCursors,
    ) -> Result[ExecutionDecision]:
        phase = Phase.B
        boundary: Boundary = "C_PRE_EXECUTION"
        req_id = (
            admitted_request_binding.request.request_identity
            if type(admitted_request_binding) is AdmittedRequestBinding
            else None
        )
        history = self._history_for(req_id, default_sequence=SequenceUse.USED)

        if (
            self._registry is None
            or self._host_observer is None
            or self._worker_observer is None
            or self._host_provenance is None
            or self._effect_fence_provider is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(admitted_request_binding) is not AdmittedRequestBinding
            or type(operation_leg) is not OperationLeg
            or type(current_observation_cursors) is not CurrentObservationCursors
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            not current_observation_cursors.host
            or not current_observation_cursors.worker
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        selected_job = (
            admitted_request_binding.request.checker.window.current.selected_job
        )
        actual_req_id = admitted_request_binding.request.request_identity
        expected_win_id = (
            admitted_request_binding.request.checker.window.actual_creation.window_id
        )
        if (
            actual_req_id.window_id != expected_win_id
            or getattr(admitted_request_binding.occurrence.key, "window_id", None)
            != expected_win_id
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=self._effect_fence_provider.lookup_history(actual_req_id),
            )
        recorded = self._effect_fence_provider.lookup_occurrence(actual_req_id)
        if recorded is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )
        if (
            recorded.selection_revision != selected_job.selection_revision
            or admitted_request_binding.occurrence.key.selection.selection_revision
            != selected_job.selection_revision
        ):
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=self._effect_fence_provider.lookup_history(actual_req_id),
            )
        if (
            recorded.occurrence != admitted_request_binding.occurrence
            or recorded.request_raw_sha256
            != admitted_request_binding.request.request_raw.sha256
        ):
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=self._effect_fence_provider.lookup_history(actual_req_id),
            )

        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            operation_leg.operation,
            actual_req_id,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        leg_res = self._effect_fence_provider.record_execution_leg(
            request_identity=actual_req_id,
            operation_leg=operation_leg,
            current_binding=current,
        )
        if isinstance(leg_res, Refusal):
            return leg_res

        window_subject = ExistingSubjectRecord(
            identity=admitted_request_binding.request.checker.window.actual_creation.object_identity
        )
        return AcceptedData(
            data=ExecutionDecision(
                binding=admitted_request_binding,
                leg=operation_leg,
                current=current,
            ),
            evidence=self._evidence(
                current=current,
                processes=(
                    peer.process,
                    admitted_request_binding.request.checker.checker,
                    operation_leg.actor,
                ),
                window=window_subject,
            ),
        )

    def before_count(
        self,
        peer: AuthenticatedPeer,
        actual_request_and_receipt: ActualRequestAndReceipt,
        p5_assessment: P5Assessment,
        provenance: ReceiptProvenance,
        current_observation_cursors: CurrentObservationCursors,
        exact_qa_receiving: QAReceiving,
    ) -> Result[CountDecision]:
        phase = Phase.C
        boundary: Boundary = "C_BEFORE_COUNT"
        req_id = (
            actual_request_and_receipt.request.request_identity
            if type(actual_request_and_receipt) is ActualRequestAndReceipt
            else None
        )
        history = self._history_for(req_id, default_sequence=SequenceUse.USED)

        if (
            self._registry is None
            or self._host_observer is None
            or self._worker_observer is None
            or self._host_provenance is None
            or self._effect_fence_provider is None
            or self._qa_receiving_verifier is None
        ):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if self._refuse_count_as_write_disabled and not self._writes_enabled:
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        if (
            type(actual_request_and_receipt) is not ActualRequestAndReceipt
            or type(provenance) is not _RECEIPT_PROVENANCE_CLS
            or type(current_observation_cursors) is not CurrentObservationCursors
            or not hasattr(p5_assessment, "verdict")
            or not hasattr(p5_assessment, "trust")
            or not hasattr(exact_qa_receiving, "receiving_reference")
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if p5_assessment.trust != "UNTRUSTED":
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if p5_assessment.verdict == "BLOCKED" or p5_assessment.verdict not in (
            "PASS",
            "FAIL",
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            not current_observation_cursors.host
            or not current_observation_cursors.worker
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        selected_job = (
            actual_request_and_receipt.request.checker.window.current.selected_job
        )
        actual_req_id = actual_request_and_receipt.request.request_identity
        qa_refusal = self._qa_receiving_verifier.verify_qa_receiving(
            exact_qa_receiving,
            selected_job=selected_job,
            boundary=boundary,
        )
        if qa_refusal is not None:
            return make_refusal(
                qa_refusal.code,
                phase=phase,
                retry_kind=qa_refusal.retry_kind,
                history=history,
            )

        recorded = self._effect_fence_provider.lookup_occurrence(actual_req_id)
        if recorded is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=SequenceUse.NOT_APPLICABLE,
                ),
            )

        history = self._effect_fence_provider.lookup_history(actual_req_id)
        publication = actual_request_and_receipt.publication
        expected_win_id = (
            actual_request_and_receipt.request.checker.window.actual_creation.window_id
        )
        if (
            recorded.selection_revision != selected_job.selection_revision
            or provenance.operation_key.selection.selection_revision
            != selected_job.selection_revision
            or publication.occurrence.key.selection.selection_revision
            != selected_job.selection_revision
            or provenance.operation_key != actual_req_id
            or publication.occurrence.key != actual_req_id
            or actual_req_id.window_id != expected_win_id
            or getattr(provenance.operation_key, "window_id", None) != expected_win_id
            or getattr(publication.occurrence.key, "window_id", None) != expected_win_id
        ):
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if (
            recorded.request_raw_sha256
            != actual_request_and_receipt.request.request_raw.sha256
            or _wit_ref(provenance.occurrence_witness)
            != _wit_ref(recorded.occurrence.witness)
        ):
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        predecessor_code = _caller_predecessor_refusal_code(
            actual_req_id, provenance.predecessor, selected_job.selection_revision
        )
        if predecessor_code is not None:
            return make_refusal(
                predecessor_code,
                phase=phase,
                retry_kind=_retry_kind_for(predecessor_code),
                history=history,
            )

        if (
            provenance.state != "complete"
            or publication.cleanup_state not in ("not-required", "complete")
            or publication.outcome not in ("success", "app-failure", "host-failure")
            or recorded.occurrence.state not in ("completed", "failed")
            or provenance.raw_publication != publication
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        native_failed = (
            publication.outcome in ("app-failure", "host-failure")
            or recorded.occurrence.state == "failed"
        )
        if (native_failed and p5_assessment.verdict != "FAIL") or (
            not native_failed and p5_assessment.verdict != "PASS"
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        pub_receipt_ref = publication.receipt_raw_ref or publication.request_raw_ref
        prov_receipt_ref = (
            provenance.raw_publication.receipt_raw_ref
            or provenance.raw_publication.request_raw_ref
        )
        if (
            publication.receipt_raw_ref is None
            or provenance.raw_publication.receipt_raw_ref is None
            or pub_receipt_ref is None
            or prov_receipt_ref is None
            or prov_receipt_ref.sha256 != pub_receipt_ref.sha256
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        disarm_rel = getattr(
            provenance.disarm_relation, "relation", provenance.disarm_relation
        )
        if disarm_rel in (
            "during",
            "after",
            "unknown",
            "DURING",
            "AFTER",
            "UNKNOWN",
            "AFTER_DISARM",
            "UNKNOWN_TO_DISARM",
        ):
            return make_refusal(
                RefusalCode.WINDOW_INELIGIBLE,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        if recorded.effect_state is EffectState.UNCERTAIN:
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        intended_effect = default_effect_for_job(selected_job, boundary)
        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            boundary,
            intended_effect,
            actual_req_id,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        # The one authentication of the counted receipt and its predecessor:
        # the port answers from its own chain, never from the caller's objects.
        linked_res = self._host_provenance.verify_linked_receipt(
            actual_req_id, provenance, boundary
        )
        if isinstance(linked_res, Refusal):
            return make_refusal(
                linked_res.code,
                phase=phase,
                retry_kind=linked_res.retry_kind,
                history=history,
            )
        binding_code = _linked_binding_refusal_code(
            linked_res.data, actual_req_id, provenance, publication
        )
        if binding_code is not None:
            return make_refusal(
                binding_code,
                phase=phase,
                retry_kind=_retry_kind_for(binding_code),
                history=history,
            )
        verified_receipt = linked_res.data

        idempotency_identity = (
            f"{selected_job.selection_revision}:{actual_req_id.row}:"
            f"{actual_req_id.request_id}:{actual_req_id.sequence}"
        )
        counted_res = self._effect_fence_provider.mark_counted(
            request_identity=actual_req_id,
            idempotency_identity=idempotency_identity,
            current_binding=current,
        )
        if isinstance(counted_res, Refusal):
            return counted_res

        admitted_binding = AdmittedRequestBinding(
            request=actual_request_and_receipt.request,
            occurrence=recorded.occurrence,
            admission_witness=recorded.admission_witness,
        )
        count_decision = CountDecision(
            binding=admitted_binding,
            receipt=pub_receipt_ref,
            native_receiving=verified_receipt,
            qa_receiving=exact_qa_receiving,
            verdict=p5_assessment.verdict,
            idempotency_identity=idempotency_identity,
        )
        window_subject = ExistingSubjectRecord(
            identity=actual_request_and_receipt.request.checker.window.actual_creation.object_identity
        )
        return AcceptedData(
            data=count_decision,
            evidence=self._evidence(
                current=current,
                processes=(
                    peer.process,
                    actual_request_and_receipt.request.checker.checker,
                    _proc_from_actor(provenance.producer_instance),
                ),
                window=window_subject,
                receiving=(
                    exact_qa_receiving.receiving_reference,
                    p5_assessment.assessment_reference,
                ),
            ),
        )

    # ------------------------------------------------------------------
    # NativeHostJoin (9 host-join adapter methods over same service)
    # ------------------------------------------------------------------

    def _resolve_host_session_peer(
        self,
        session: NativeSession,
        *,
        phase: Phase,
    ) -> tuple[AuthenticatedPeer | None, Refusal | None]:
        if self._session_peer_resolver is None:
            return None, make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        res = self._session_peer_resolver.resolve_session_peer(session)
        if res is None:
            return None, make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if isinstance(res, Refusal):
            return None, res
        return res, None

    @staticmethod
    def _to_host_selected_job(
        job: SelectedJob,
        current: CurrentBinding,
        reviewed_graph: ReviewedSourceGraph,
        allowed_rows: frozenset[str] = DEFAULT_P3_ALLOWED_ROWS,
    ) -> SelectedHostJob:
        digest = job.expected_source_digest
        build_ref = RawRef(
            root_locator=f"root://build/{job.selection_revision}",
            relative_path="build.json",
            byte_length=64,
            sha256=digest,
        )
        expected_binding_ref = RawRef(
            root_locator=f"root://binding/{job.selection_revision}",
            relative_path="binding.json",
            byte_length=64,
            sha256=digest,
        )
        if isinstance(job.selection, ProjectSelection):
            route: HostProjectSelection | HostCalibrationSelection = (
                HostProjectSelection(
                    project_id=job.selection.project_id,
                    kit_ref=RawRef(
                        root_locator=f"root://kit/{job.selection.project_id}",
                        relative_path=f"{job.selection.kit_id}.json",
                        byte_length=64,
                        sha256=job.selection.kit_sha256,
                    ),
                    expected_binding_ref=expected_binding_ref,
                )
            )
        elif isinstance(job.selection, CalibrationSelection):
            route = HostCalibrationSelection(
                manifest_ref=RawRef(
                    root_locator=f"root://manifest/{job.selection_revision}",
                    relative_path=job.selection.manifest_ref.path,
                    byte_length=job.selection.manifest_ref.length,
                    sha256=job.selection.manifest_ref.digest,
                ),
                entry_id=job.selection.entry_id,
                round_id=job.selection.round,
                calibration_run=job.selection.calibration_run,
                copy_id=job.selection.copy_identity,
                expected_binding_ref=expected_binding_ref,
            )
        else:  # pragma: no cover - guarded by SelectedJob validation
            raise TypeError("Unsupported SelectionMode")

        caller = CallerSelection(
            entrypoint=job.route,
            source_review_ref=reviewed_graph,
            caller_role="checker",
            writer=job.selector_issuer.issuer_id,
            allowed_rows=allowed_rows,
            inspect_variant=job.compatibility_profile.inspect,
            runtime_route="temper-dev",
        )
        sel_handle = _HostSelectionHandle(
            selection_reference=f"sel:{job.selection_revision}",
            selection_revision=job.selection_revision,
        )
        return SelectedHostJob(
            selection=sel_handle,
            job_id=f"job:{job.selection_revision}",
            attempt_id=f"attempt:{job.selection_revision}",
            publication_id=f"pub:{job.selection_revision}",
            build_ref=build_ref,
            route=route,
            creator_launch_id=f"launch:{job.selection_revision}",
            caller=caller,
        )

    def select_host_job(self, session: NativeSession) -> Result[SelectedHostJob]:
        phase = Phase.A
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        selected_job: SelectedJob | None = None
        if isinstance(self._registry, AuthorityRegistryService):
            snap_res = self._registry._require_ready(
                phase=phase,
                history=PriorRequestHistory(),
            )
            if isinstance(snap_res, Refusal):
                return snap_res
            if not snap_res.jobs:
                return make_refusal(
                    RefusalCode.SELECTION_MISSING,
                    phase=phase,
                    retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                )
            if len(snap_res.jobs) > 1:
                return make_refusal(
                    RefusalCode.SELECTION_AMBIGUOUS,
                    phase=phase,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            selected_job = snap_res.jobs[0]
        else:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        current_res = self._registry.check_current(
            peer,
            selected_job.selection_revision,
            "A_PRE_CREATE",
            default_effect_for_job(selected_job, "A_PRE_CREATE"),
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data
        reviewed_graph = self._lookup_reviewed_graph(selected_job.selection_revision)
        if reviewed_graph is None:
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        allowed_rows = self._allowed_rows_by_revision.get(
            selected_job.selection_revision,
            DEFAULT_P3_ALLOWED_ROWS,
        )
        host_job = self._to_host_selected_job(
            selected_job,
            current,
            reviewed_graph=reviewed_graph,
            allowed_rows=allowed_rows,
        )
        return AcceptedData(
            data=host_job,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def permit_observation(
        self,
        session: NativeSession,
        scope: ObservationScope,
    ) -> Result[PermissionHandle]:
        phase = Phase.A
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if self._registry is None or self._host_observer is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if type(scope) is not _OBSERVATION_SCOPE_CLS or not scope.protected_effects:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if any(
            eff.selection.selection_revision != scope.selection.selection_revision
            for eff in scope.protected_effects
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        first_effect = scope.protected_effects[0]
        first_bnd = cast(Boundary, first_effect.boundary)
        phase = boundary_to_phase(first_bnd)
        intended_op = SelectedOperation(
            domain="p3.host",
            operation=first_effect.operation,
            revision="op-1",
        )
        current_res = self._registry.check_current(
            peer,
            scope.selection.selection_revision,
            first_bnd,
            intended_op,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data
        reviewed_graph = self._lookup_reviewed_graph(
            current.selected_job.selection_revision
        )
        if reviewed_graph is None:
            return make_refusal(
                RefusalCode.CLOSURE_INCOMPLETE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        allowed_rows = self._allowed_rows_by_revision.get(
            current.selected_job.selection_revision,
            DEFAULT_P3_ALLOWED_ROWS,
        )
        host_job = self._to_host_selected_job(
            current.selected_job,
            current,
            reviewed_graph=reviewed_graph,
            allowed_rows=allowed_rows,
        )

        perm_ref = f"perm:{scope.selection.selection_revision}:{len(self._granted_permissions) + 1}"
        handle: PermissionHandle = PermissionHandleRecord(
            observation_permission=perm_ref,
            selection_revision=scope.selection.selection_revision,
        )
        self._granted_permissions[perm_ref] = (
            handle,
            session,
            peer,
            host_job,
            scope,
            current,
        )
        return AcceptedData(
            data=handle,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def open_observation(
        self,
        permission: PermissionHandle,
        scope: ObservationScope,
    ) -> Result[ObservationSession]:
        phase = Phase.A
        if (
            not hasattr(permission, "observation_permission")
            or type(scope) is not _OBSERVATION_SCOPE_CLS
            or not scope.protected_effects
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if self._host_observer is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        granted = self._granted_permissions.get(permission.observation_permission)
        if granted is None or granted[0] != permission:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        _, session, granted_peer, host_job, granted_scope, initial_current = granted
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if (
            not _peer_ref_str(granted_peer)
            or not _peer_ref_str(peer)
            or _peer_ref_str(granted_peer) != _peer_ref_str(peer)
            or granted_scope != scope
        ):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        first_effect = scope.protected_effects[0]
        first_bnd = cast(Boundary, first_effect.boundary)
        phase = boundary_to_phase(first_bnd)
        current_res = self._registry.check_current(
            peer,
            scope.selection.selection_revision,
            first_bnd,
            initial_current.intended_effect,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        open_res = self._host_observer.begin(
            session,
            host_job,
            scope,
            permission,
        )
        if isinstance(open_res, Refusal):
            return open_res
        obs_session = open_res.data
        self._opened_observation_sessions[obs_session.observation_session] = (
            obs_session,
            peer,
            scope,
            current,
        )
        return AcceptedData(
            data=obs_session,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def observe(
        self,
        session: ObservationSession,
        boundary: HostEffect,
    ) -> Result[HostObservation]:
        if (
            not hasattr(session, "observation_session")
            or type(boundary) is not _HOST_EFFECT_CLS
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        phase = boundary_to_phase(boundary.boundary)
        if self._host_observer is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        opened = self._opened_observation_sessions.get(session.observation_session)
        if opened is None or opened[0] != session:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        _, peer, scope, _ = opened
        if boundary not in scope.protected_effects:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        eff_bnd = cast(Boundary, boundary.boundary)
        intended_op = SelectedOperation(
            domain="p3.host",
            operation=boundary.operation,
            revision="op-1",
        )
        current_res = self._registry.check_current(
            peer,
            scope.selection.selection_revision,
            eff_bnd,
            intended_op,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        obs_res = self._host_observer.observe(session, eff_bnd)
        if isinstance(obs_res, Refusal):
            return obs_res
        if obs_res.data.gaps or not obs_res.data.coverage:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        return AcceptedData(
            data=obs_res.data,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def recheck_effect(
        self,
        session: ObservationSession,
        effect: HostEffect,
        coverage: HostCoverage,
    ) -> Result[EffectLease]:
        if (
            not hasattr(session, "observation_session")
            or type(effect) is not _HOST_EFFECT_CLS
            or type(coverage) is not _HOST_COVERAGE_CLS
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        phase = boundary_to_phase(effect.boundary)
        if self._host_observer is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        opened = self._opened_observation_sessions.get(session.observation_session)
        if opened is None or opened[0] != session:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        _, peer, scope, _ = opened
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

        eff_bnd = cast(Boundary, effect.boundary)
        intended_op = SelectedOperation(
            domain="p3.host",
            operation=effect.operation,
            revision="op-1",
        )
        current_res = self._registry.check_current(
            peer,
            scope.selection.selection_revision,
            eff_bnd,
            intended_op,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        obs_res = self._host_observer.observe(session, eff_bnd)
        if isinstance(obs_res, Refusal):
            return obs_res
        if obs_res.data.gaps or not obs_res.data.coverage:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        lease_res = self._host_observer.before_effect(session, effect, coverage)
        if isinstance(lease_res, Refusal):
            return lease_res
        return AcceptedData(
            data=lease_res.data,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def witness_event(
        self,
        session: ObservationSession,
        key: OperationKey,
        boundary: HostEffect,
    ) -> Result[NativeWitness]:
        if (
            not hasattr(session, "observation_session")
            or type(boundary) is not _HOST_EFFECT_CLS
            or type(key) not in (_LIFECYCLE_KEY_CLS, _ROW_KEY_CLS)
        ):
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        phase = boundary_to_phase(boundary.boundary)
        if self._host_observer is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        opened = self._opened_observation_sessions.get(session.observation_session)
        if opened is None or opened[0] != session:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        _, peer, scope, initial_current = opened
        if boundary not in scope.protected_effects:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        eff_bnd = cast(Boundary, boundary.boundary)
        current_res = self._registry.check_current(
            peer,
            scope.selection.selection_revision,
            eff_bnd,
            initial_current.intended_effect,
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        cov_res = self._host_observer.finish(session, boundary)
        if isinstance(cov_res, Refusal):
            return cov_res
        fin_res = self._host_observer.finish_witness(session, eff_bnd)
        if isinstance(fin_res, Refusal):
            return fin_res

        return AcceptedData(
            data=fin_res.data,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def lookup_occurrence(
        self,
        session: NativeSession,
        key: OperationKey,
    ) -> Result[NativeWitness]:
        phase = Phase.C if type(key) is _ROW_KEY_CLS else Phase.A
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if self._host_provenance is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if type(key) not in (_LIFECYCLE_KEY_CLS, _ROW_KEY_CLS):
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if not isinstance(self._registry, AuthorityRegistryService):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        snap_res = self._registry._require_ready(
            phase=phase,
            history=PriorRequestHistory(),
        )
        if isinstance(snap_res, Refusal):
            return snap_res
        matching_jobs = [
            j
            for j in snap_res.jobs
            if j.selection_revision == key.selection.selection_revision
        ]
        if not matching_jobs:
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        job = matching_jobs[0]

        boundary: Boundary = "C_PRE_EXECUTION" if phase is Phase.C else "A_PRE_ARM"
        current_res = self._registry.check_current(
            peer,
            job.selection_revision,
            boundary,
            default_effect_for_job(job, boundary),
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        # Observation only: what the host saw for this key, never authentication.
        occ = self._host_provenance.lookup_occurrence_handle(key)
        witness = self._host_provenance.lookup_witness(key)
        if occ is None or witness is None:
            return make_refusal(
                RefusalCode.PRIOR_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if occ.key.selection.selection_revision != job.selection_revision:
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if _wit_ref(occ.witness) != _wit_ref(witness):
            return make_refusal(
                RefusalCode.PRIOR_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        return AcceptedData(
            data=witness,
            evidence=self._evidence(current=current, processes=(peer.process,)),
        )

    def verify_publication(
        self,
        session: NativeSession,
        key: OperationKey,
        publication: RawPublication,
        witness: NativeWitness,
    ) -> Result[ReceiptProvenance]:
        if type(key) not in (_LIFECYCLE_KEY_CLS, _ROW_KEY_CLS):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        phase = Phase.C if type(key) is _ROW_KEY_CLS else Phase.A
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if self._host_provenance is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if (
            type(publication) is not _RAW_PUBLICATION_CLS
            or not hasattr(witness, "witness_registration")
            or type(publication.occurrence) is not _OCCURRENCE_HANDLE_CLS
            or publication.occurrence.key != key
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        occurrence = publication.occurrence

        boundary: Boundary = "C_BEFORE_COUNT" if phase is Phase.C else "A_PRE_ARM"
        if not isinstance(self._registry, AuthorityRegistryService):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        snap_res = self._registry._require_ready(
            phase=phase,
            history=PriorRequestHistory(),
        )
        if isinstance(snap_res, Refusal):
            return snap_res
        matching_jobs = [
            j
            for j in snap_res.jobs
            if j.selection_revision == key.selection.selection_revision
        ]
        if not matching_jobs:
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        job = matching_jobs[0]

        current_res = self._registry.check_current(
            peer,
            job.selection_revision,
            boundary,
            default_effect_for_job(job, boundary),
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        prov_res = self._host_provenance.bind_publication(
            session,
            occurrence,
            publication,
            witness,
        )
        if isinstance(prov_res, Refusal):
            return prov_res
        if (
            type(prov_res.data) is not _RECEIPT_PROVENANCE_CLS
            or prov_res.data.operation_key != key
            or prov_res.data.raw_publication != publication
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        return AcceptedData(
            data=prov_res.data,
            evidence=self._evidence(
                current=current,
                processes=(
                    peer.process,
                    _proc_from_actor(prov_res.data.producer_instance),
                ),
            ),
        )

    def receive(
        self,
        session: NativeSession,
        key: OperationKey,
        provenance: ReceiptProvenance,
        boundary: HostEffect,
    ) -> Result[NativeReceive]:
        if (
            type(key) not in (_LIFECYCLE_KEY_CLS, _ROW_KEY_CLS)
            or type(provenance) is not _RECEIPT_PROVENANCE_CLS
            or type(boundary) is not _HOST_EFFECT_CLS
        ):
            return make_refusal(
                RefusalCode.RESULT_UNVERIFIED,
                phase=Phase.C,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        phase = boundary_to_phase(boundary.boundary)
        peer, refusal = self._resolve_host_session_peer(session, phase=phase)
        if refusal is not None or peer is None:
            return refusal  # type: ignore[return-value]
        if self._host_provenance is None or self._registry is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )
        if not isinstance(self._registry, AuthorityRegistryService):
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
            )

        snap_res = self._registry._require_ready(
            phase=phase,
            history=PriorRequestHistory(),
        )
        if isinstance(snap_res, Refusal):
            return snap_res
        matching_jobs = [
            j
            for j in snap_res.jobs
            if j.selection_revision
            == provenance.operation_key.selection.selection_revision
        ]
        if not matching_jobs:
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if provenance.operation_key != key:
            return make_refusal(
                RefusalCode.PRIOR_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        job = matching_jobs[0]
        eff_bnd = cast(Boundary, boundary.boundary)
        current_res = self._registry.check_current(
            peer,
            job.selection_revision,
            eff_bnd,
            default_effect_for_job(job, eff_bnd),
        )
        if isinstance(current_res, Refusal):
            return current_res
        current = current_res.data

        if eff_bnd not in LINKED_RECEIPT_BOUNDARIES:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        predecessor_code = _caller_predecessor_refusal_code(
            key, provenance.predecessor, job.selection_revision
        )
        if predecessor_code is not None:
            return make_refusal(
                predecessor_code,
                phase=phase,
                retry_kind=_retry_kind_for(predecessor_code),
            )
        # The one authentication of the received receipt and its predecessor:
        # the port answers from its own chain, never from the caller's objects.
        rec_res = self._host_provenance.verify_linked_receipt(
            key, provenance, eff_bnd
        )
        if isinstance(rec_res, Refusal):
            return rec_res
        binding_code = _linked_binding_refusal_code(
            rec_res.data, key, provenance, provenance.raw_publication
        )
        if binding_code is not None:
            return make_refusal(
                binding_code,
                phase=phase,
                retry_kind=_retry_kind_for(binding_code),
            )

        return AcceptedData(
            data=rec_res.data,
            evidence=self._evidence(
                current=current,
                processes=(
                    peer.process,
                    _proc_from_actor(provenance.producer_instance),
                ),
            ),
        )


class NativeHostJoinAdapter(NativeHostJoin):
    """Thin 9-method ``NativeHostJoin`` adapter delegating to ``P3AuthorityService``."""

    def __init__(self, service: P3AuthorityService) -> None:
        self._service = service

    @property
    def service(self) -> P3AuthorityService:
        return self._service

    def select_host_job(self, session: NativeSession) -> Result[SelectedHostJob]:
        return self._service.select_host_job(session)

    def permit_observation(
        self,
        session: NativeSession,
        scope: ObservationScope,
    ) -> Result[PermissionHandle]:
        return self._service.permit_observation(session, scope)

    def open_observation(
        self,
        permission: PermissionHandle,
        scope: ObservationScope,
    ) -> Result[ObservationSession]:
        return self._service.open_observation(permission, scope)

    def observe(
        self,
        session: ObservationSession,
        boundary: HostEffect,
    ) -> Result[HostObservation]:
        return self._service.observe(session, boundary)

    def recheck_effect(
        self,
        session: ObservationSession,
        effect: HostEffect,
        coverage: HostCoverage,
    ) -> Result[EffectLease]:
        return self._service.recheck_effect(session, effect, coverage)

    def witness_event(
        self,
        session: ObservationSession,
        key: OperationKey,
        boundary: HostEffect,
    ) -> Result[NativeWitness]:
        return self._service.witness_event(session, key, boundary)

    def lookup_occurrence(
        self,
        session: NativeSession,
        key: OperationKey,
    ) -> Result[NativeWitness]:
        return self._service.lookup_occurrence(session, key)

    def verify_publication(
        self,
        session: NativeSession,
        key: OperationKey,
        publication: RawPublication,
        witness: NativeWitness,
    ) -> Result[ReceiptProvenance]:
        return self._service.verify_publication(session, key, publication, witness)

    def receive(
        self,
        session: NativeSession,
        key: OperationKey,
        provenance: ReceiptProvenance,
        boundary: HostEffect,
    ) -> Result[NativeReceive]:
        return self._service.receive(session, key, provenance, boundary)


@dataclass(frozen=True, slots=True, kw_only=True)
class P3AuthorityComposition:
    """Explicit dependency-injected composition bundle for P3 source authority."""

    registry: P3AuthorityRegistry
    candidate_bindings: P3CandidateBindings
    boundary: P3NativeBoundary
    host_join: NativeHostJoin
    service: P3AuthorityService


def compose_p3_authority(
    *,
    registry: P3AuthorityRegistry | None = None,
    snapshot_provider: SelectionSnapshotProvider | None = None,
    issuer_verifier: IssuerVerifier | None = None,
    peer_verifier: PeerVerifierProtocol | None = None,
    issuer_anchors: AnchorTable | None = None,
    issuer_records: EnvelopeStore | Mapping[AuthorityRef, bytes] | None = None,
    issuer_statuses: EnvelopeStore | Mapping[str, bytes] | None = None,
    pinned_peers: Sequence[AuthenticatedPeer] | None = None,
    history_provider: RequestHistoryProvider | None = None,
    closure_comparator: SharedN3 | None = None,
    host_observer: HostObserver | None = None,
    worker_observer: WorkerObserver | None = None,
    root_observer: RootObserver | None = None,
    host_provenance: HostProvenance | None = None,
    effect_fence_provider: EffectFenceProvider | None = None,
    qa_receiving_verifier: QAReceivingVerifier | None = None,
    session_peer_resolver: HostSessionPeerResolver | None = None,
    host_session_peer_resolver: HostSessionPeerResolver | None = None,
    caller_peer_provider: CallerPeerProvider | None = None,
    delegate_candidate_bindings: CandidateBindings | None = None,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    capture_adapter: CandidateCaptureAdapter | None = None,
    installation_verifier: InstallationVerifier | None = None,
    preparation_verifier: PreparationVerifier | None = None,
    designated_workflows: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    default_dispatch_identity: DispatchIdentity | None = None,
    writes_enabled: bool = False,
    refuse_count_as_write_disabled: bool = False,
) -> P3AuthorityComposition:
    """Build a composed P3 authority bundle without side effects or default test doubles.

    The issuer parts (``issuer_anchors``, ``issuer_records``, ``issuer_statuses``)
    build an ``Ed25519IssuerVerifier`` (its condition table is always the closed
    ``CONDITION_TABLE``) and ``pinned_peers`` builds a ``PinnedPeerVerifier`` for the
    registry composed here. Passing them together with ``issuer_verifier``,
    ``peer_verifier`` or ``registry`` raises ``ValueError`` instead of silently
    ignoring one of them.
    """
    issuer_parts_given = any(
        item is not None
        for item in (
            issuer_anchors,
            issuer_records,
            issuer_statuses,
        )
    )
    if issuer_parts_given and issuer_verifier is not None:
        raise ValueError(
            "compose_p3_authority: pass issuer_verifier or the issuer parts "
            "(issuer_anchors, issuer_records, issuer_statuses), "
            "not both"
        )
    if pinned_peers is not None and peer_verifier is not None:
        raise ValueError(
            "compose_p3_authority: pass peer_verifier or pinned_peers, not both"
        )
    if registry is not None and (issuer_parts_given or pinned_peers is not None):
        raise ValueError(
            "compose_p3_authority: the issuer parts and pinned_peers build the "
            "registry's verifiers; a given registry already holds its own"
        )
    effective_issuer_verifier: IssuerVerifier | None = issuer_verifier
    if effective_issuer_verifier is None and issuer_parts_given:
        effective_issuer_verifier = Ed25519IssuerVerifier(
            anchors=(
                issuer_anchors
                if issuer_anchors is not None
                else PRODUCTION_ANCHOR_TABLE
            ),
            records=issuer_records,
            statuses=issuer_statuses,
        )
    effective_peer_verifier: PeerVerifierProtocol | None = peer_verifier
    if effective_peer_verifier is None and pinned_peers is not None:
        effective_peer_verifier = PinnedPeerVerifier(pinned_peers)
    effective_registry = (
        registry
        if registry is not None
        else AuthorityRegistryService(
            snapshot_provider=snapshot_provider,
            issuer_verifier=effective_issuer_verifier,
            peer_verifier=effective_peer_verifier,
            history_provider=history_provider,
        )
    )
    effective_session_peer_resolver = (
        session_peer_resolver
        if session_peer_resolver is not None
        else host_session_peer_resolver
    )
    service = P3AuthorityService(
        registry=effective_registry,
        closure_comparator=closure_comparator,
        host_observer=host_observer,
        worker_observer=worker_observer,
        root_observer=root_observer,
        host_provenance=host_provenance,
        effect_fence_provider=effect_fence_provider,
        qa_receiving_verifier=qa_receiving_verifier,
        session_peer_resolver=effective_session_peer_resolver,
        writes_enabled=writes_enabled,
        refuse_count_as_write_disabled=refuse_count_as_write_disabled,
    )
    candidate_bindings = P3CandidateBindings(
        registry=effective_registry,
        caller_peer_provider=caller_peer_provider,
        delegate_bindings=delegate_candidate_bindings,
        session_factory=session_factory,
        capture_adapter=capture_adapter,
        installation_verifier=installation_verifier,
        preparation_verifier=preparation_verifier,
        designated_workflows=(
            frozenset(designated_workflows)
            if designated_workflows is not None
            else None
        ),
        default_dispatch_identity=default_dispatch_identity,
    )
    return P3AuthorityComposition(
        registry=effective_registry,
        candidate_bindings=candidate_bindings,
        boundary=service,
        host_join=service.host_join,
        service=service,
    )


__all__ = [
    "AnchorEntry",
    "AnchorTable",
    "Ed25519IssuerVerifier",
    "EffectFenceProvider",
    "EnvelopeStore",
    "HostSessionPeerResolver",
    "InMemoryEffectFenceProvider",
    "InMemoryHostObserver",
    "InMemoryHostProvenance",
    "InMemoryHostSessionPeerResolver",
    "InMemoryQAReceivingVerifier",
    "InMemoryRootObserver",
    "InMemoryWorkerObserver",
    "NativeHostJoinAdapter",
    "ObservationSessionRecord",
    "P3AuthorityComposition",
    "P3AuthorityService",
    "PRODUCTION_ANCHOR_TABLE",
    "PRODUCTION_TRUST_ANCHORS",
    "PermissionHandleRecord",
    "PinnedPeerVerifier",
    "QAReceivingVerifier",
    "RecordedRowOccurrence",
    "SystemsSourceClosureComparator",
    "compose_p3_authority",
]
