"""P3 authority registry and read-only selection/issuer verification service.

Implements the canonical ``P3AuthorityRegistry`` and ``IssuerVerifier`` ports
from ``temper_ai.p3_authority.contract`` over injected read-only provider
interfaces and immutable snapshots. Production defaults remain inert and
unconfigured (``None`` providers fail closed with ``AUTHORITY_UNAVAILABLE``).
Publisher/admin test helpers live in separate explicit test doubles and do not
implement reader or registry ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from temper_ai.config.admission_contract import DispatchIdentity
from temper_ai.p3_authority.contract import (
    DECISION_SCHEMA,
    AcceptedData,
    ActualCreation,
    AdmissionState,
    AuthenticatedPeer,
    AuthorityRef,
    Boundary,
    CompatibilityProfile,
    ConditionRef,
    CurrentBinding,
    DecisionEvidence,
    EffectSet,
    EffectState,
    ImmutableReference,
    IssuerVerifier,
    JobKey,
    NativeProcessRef,
    NativeRootObject,
    NativeSubject,
    P3AuthorityRegistry,
    Phase,
    PreDispatchJob,
    Refusal,
    RefusalCode,
    RequestIdentity,
    Result,
    RetryKind,
    SelectedJob,
    SelectedOperation,
    SelectedSubject,
    SequenceUse,
    TrustedInstant,
    VerifiedAuthority,
    WindowBinding,
)
from temper_ai.p3_authority.issuer_verifier import (
    CONDITION_PREDICATES,
    evaluate_registry_conditions,
    is_text,
    parse_strict_instant_int,
)

COMPATIBILITY_CORPUS_SCHEMA: Literal["ops-host-compat-corpus/1"] = (
    "ops-host-compat-corpus/1"
)
REVIEWED_GRAPH_SCHEMA: Literal["p3-reviewed-source-graph/1"] = (
    "p3-reviewed-source-graph/1"
)
LOADED_CLOSURE_SCHEMA: Literal["p3-reviewed-loaded-closure/1"] = (
    "p3-reviewed-loaded-closure/1"
)


def boundary_to_phase(boundary: Boundary | str) -> Phase:
    if boundary in ("A_PRE_CREATE", "A_PRE_ARM"):
        return Phase.A
    if boundary in ("B_PRE_REQUEST", "C_PRE_REQUEST", "C_PRE_EXECUTION"):
        return Phase.B
    if boundary == "C_BEFORE_COUNT":
        return Phase.C
    raise ValueError(f"unsupported boundary: {boundary!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ImmutableReferenceRecord:
    """Concrete immutable ``ImmutableReference`` implementation."""

    path: str
    digest: str
    length: int
    revision: str

    def __post_init__(self) -> None:
        if not self.path or not self.digest or self.length <= 0 or not self.revision:
            raise ValueError("invalid ImmutableReferenceRecord fields")


@dataclass(frozen=True, slots=True, kw_only=True)
class FutureSubjectRecord:
    """Concrete immutable ``FutureSubject`` implementation for pre-create scope."""

    selected_scope_reference: str
    subject_kind: Literal["future"] = field(default="future", init=False)

    def __post_init__(self) -> None:
        if not self.selected_scope_reference:
            raise ValueError("selected_scope_reference must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingSubjectRecord:
    """Concrete immutable ``ExistingSubject`` implementation for existing identity."""

    identity: NativeProcessRef | NativeRootObject
    subject_kind: Literal["existing"] = field(default="existing", init=False)

    def __post_init__(self) -> None:
        if not hasattr(self.identity, "process_registration") and not hasattr(
            self.identity, "filesystem_object"
        ):
            raise TypeError(
                "ExistingSubjectRecord.identity must be NativeProcessRef or NativeRootObject"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionEvidenceRecord:
    """Concrete immutable ``DecisionEvidence`` carrier for accepted results."""

    selected_job: SelectedJob
    authority_revisions: tuple[AuthorityRef, ...]
    window: NativeSubject | None
    processes: tuple[NativeProcessRef, ...]
    effect: SelectedOperation
    phase: Phase
    boundary: Boundary
    source: ImmutableReference
    closure: ImmutableReference
    compatibility: CompatibilityProfile
    receiving: tuple[ImmutableReference, ...] = ()
    schema: Literal["p3-native-decision/1"] = field(default=DECISION_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if type(self.selected_job) is not SelectedJob:
            raise TypeError("DecisionEvidenceRecord.selected_job must be SelectedJob")
        if not self.authority_revisions or any(
            type(item) is not AuthorityRef for item in self.authority_revisions
        ):
            raise TypeError(
                "DecisionEvidenceRecord.authority_revisions must be non-empty tuple[AuthorityRef, ...]"
            )
        if not self.processes or any(
            not hasattr(item, "process_registration") for item in self.processes
        ):
            raise TypeError(
                "DecisionEvidenceRecord.processes must be non-empty tuple[NativeProcessRef, ...]"
            )
        if type(self.effect) is not SelectedOperation:
            raise TypeError("DecisionEvidenceRecord.effect must be SelectedOperation")
        if type(self.phase) is not Phase:
            raise TypeError("DecisionEvidenceRecord.phase must be Phase")
        if self.boundary != "C_BEFORE_COUNT" and self.receiving:
            raise ValueError(
                "non-count DecisionEvidenceRecord cannot carry receiving refs"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionSnapshot:
    """Immutable read-only snapshot returned by a selection snapshot provider."""

    snapshot_revision: str
    jobs: tuple[SelectedJob, ...]
    verified_at: TrustedInstant
    expected_subjects: dict[str, SelectedSubject] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.snapshot_revision:
            raise ValueError("snapshot_revision must be non-empty")
        if any(type(job) is not SelectedJob for job in self.jobs):
            raise TypeError("SelectionSnapshot.jobs must contain only SelectedJob")
        if type(self.verified_at) is not TrustedInstant:
            raise TypeError("SelectionSnapshot.verified_at must be TrustedInstant")

    def subject_for(self, job: SelectedJob) -> SelectedSubject:
        explicit = self.expected_subjects.get(job.selection_revision)
        if explicit is not None:
            return explicit
        return SelectedSubject(
            subject=FutureSubjectRecord(
                selected_scope_reference=f"scope:{job.selection_revision}",
            ),
            job=job.pre_dispatch_or_running_job,
            selection_revision=job.selection_revision,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriorRequestHistory:
    """Explicit prior admission/effect/sequence truth for refusal construction."""

    admission_state: AdmissionState = AdmissionState.NOT_ADMITTED
    effect_state: EffectState = EffectState.NONE
    sequence_use: SequenceUse = SequenceUse.NOT_APPLICABLE


class PeerVerifierProtocol(Protocol):
    """Read-only channel + process peer authenticator."""

    def verify_peer(self, peer: AuthenticatedPeer) -> bool: ...


class SelectionSnapshotProvider(Protocol):
    """Read-only selection snapshot source (no publish/mutate methods)."""

    def read_snapshot(self) -> SelectionSnapshot | None: ...


class RequestHistoryProvider(Protocol):
    """Read-only lookup of prior request admission/effect/sequence history."""

    def lookup_history(
        self, request_identity: RequestIdentity
    ) -> PriorRequestHistory: ...


def make_refusal(
    code: RefusalCode,
    *,
    phase: Phase,
    retry_kind: RetryKind,
    history: PriorRequestHistory | None = None,
) -> Refusal:
    resolved = history if history is not None else PriorRequestHistory()
    return Refusal(
        code=code,
        phase=phase,
        retry_kind=retry_kind,
        admission_state=resolved.admission_state,
        effect_state=resolved.effect_state,
        sequence_use=resolved.sequence_use,
    )


def default_effect_for_job(job: SelectedJob, boundary: Boundary) -> SelectedOperation:
    if job.authorized_operations:
        for op in sorted(
            job.authorized_operations,
            key=lambda item: (item.domain, item.operation, item.revision),
        ):
            if op.domain == boundary or op.operation == boundary:
                return op
        return sorted(
            job.authorized_operations,
            key=lambda item: (item.domain, item.operation, item.revision),
        )[0]
    return SelectedOperation(
        domain="p3.boundary",
        operation=boundary,
        revision=job.selection_revision,
    )


def _strict_proc_registration(proc: object) -> str:
    val = getattr(proc, "process_registration", None)
    return val if type(val) is str and val != "" else ""


def _strict_peer_registration(peer: object) -> str:
    val = getattr(peer, "peer_registration", None)
    return val if type(val) is str and val != "" else ""


def _same_strict_proc_registration(left: object, right: object) -> bool:
    left_reg = _strict_proc_registration(left)
    right_reg = _strict_proc_registration(right)
    return bool(left_reg) and bool(right_reg) and left_reg == right_reg


def _proc_ref(proc: object) -> str:
    if hasattr(proc, "process_registration"):
        return _strict_proc_registration(proc)
    val = getattr(proc, "process_reference", "")
    return val if type(val) is str and val != "" else ""


def _peer_ref(peer: object) -> str:
    if hasattr(peer, "peer_registration"):
        return _strict_peer_registration(peer)
    val = getattr(peer, "peer_reference", "")
    return val if type(val) is str and val != "" else ""


def _same_non_empty_proc_ref(left: object, right: object) -> bool:
    left_ref = _proc_ref(left)
    right_ref = _proc_ref(right)
    return bool(left_ref) and bool(right_ref) and left_ref == right_ref


class AuthorityRegistryService(P3AuthorityRegistry):
    """Read-only P3 selection and authority verification service.

    All provider dependencies default to ``None`` and fail closed with
    ``AUTHORITY_UNAVAILABLE``. Never accepts selection/authority claims from
    candidate workflow dictionaries, environment variables, or unverified peers.
    """

    def __init__(
        self,
        *,
        snapshot_provider: SelectionSnapshotProvider | None = None,
        issuer_verifier: IssuerVerifier | None = None,
        peer_verifier: PeerVerifierProtocol | None = None,
        history_provider: RequestHistoryProvider | None = None,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._issuer_verifier = issuer_verifier
        self._peer_verifier = peer_verifier
        self._history_provider = history_provider
        self._created_windows: dict[str, WindowBinding] = {}

    def _history_for(
        self,
        request_identity: RequestIdentity | None,
        *,
        default_sequence: SequenceUse = SequenceUse.NOT_APPLICABLE,
    ) -> PriorRequestHistory:
        if request_identity is not None and self._history_provider is not None:
            found = self._history_provider.lookup_history(request_identity)
            if (
                found.admission_state is AdmissionState.NOT_ADMITTED
                and found.effect_state is EffectState.NONE
                and found.sequence_use is SequenceUse.NOT_APPLICABLE
                and default_sequence is not SequenceUse.NOT_APPLICABLE
            ):
                return PriorRequestHistory(
                    admission_state=AdmissionState.NOT_ADMITTED,
                    effect_state=EffectState.NONE,
                    sequence_use=default_sequence,
                )
            return found
        return PriorRequestHistory(
            admission_state=AdmissionState.NOT_ADMITTED,
            effect_state=EffectState.NONE,
            sequence_use=default_sequence,
        )

    def _verify_peer(
        self,
        peer: AuthenticatedPeer,
        *,
        phase: Phase,
        history: PriorRequestHistory,
    ) -> Refusal | None:
        if (
            not _peer_ref(peer)
            or not hasattr(peer, "process")
            or not _proc_ref(getattr(peer, "process", None))
        ):
            return make_refusal(
                RefusalCode.PEER_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if self._peer_verifier is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if not self._peer_verifier.verify_peer(peer):
            return make_refusal(
                RefusalCode.PEER_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        return None

    def _require_ready(
        self,
        *,
        phase: Phase,
        history: PriorRequestHistory,
    ) -> SelectionSnapshot | Refusal:
        if self._snapshot_provider is None or self._issuer_verifier is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        snapshot = self._snapshot_provider.read_snapshot()
        if snapshot is None or type(snapshot) is not SelectionSnapshot:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        return snapshot

    def _source_ref_for_job(self, job: SelectedJob) -> ImmutableReference:
        return ImmutableReferenceRecord(
            path=f"source/{job.selection_revision}",
            digest=job.expected_source_digest,
            length=64,
            revision=job.selection_revision,
        )

    def _validate_job_authorities(
        self,
        *,
        snapshot: SelectionSnapshot,
        job: SelectedJob,
        peer: AuthenticatedPeer,
        phase: Phase,
        boundary: Boundary,
        intended_effect: SelectedOperation,
        history: PriorRequestHistory,
    ) -> tuple[VerifiedAuthority, ...] | Refusal:
        if type(job) is not SelectedJob:
            return make_refusal(
                RefusalCode.AUTHORITY_UNBOUND,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if getattr(job, "route", "external-db-fresh") != "external-db-fresh":
            return make_refusal(
                RefusalCode.ROUTE_UNSUPPORTED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if not job.authority_refs or not job.authorized_operations:
            return make_refusal(
                RefusalCode.AUTHORITY_UNBOUND,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if intended_effect not in job.authorized_operations:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        expected_subject = snapshot.subject_for(job)
        if expected_subject.selection_revision != job.selection_revision:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if expected_subject.job != job.pre_dispatch_or_running_job:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        assert self._issuer_verifier is not None
        required_effects = frozenset({intended_effect})

        selector_res = self._issuer_verifier.verify(
            job.selector_issuer,
            peer,
            expected_subject,
            required_effects,
            snapshot.verified_at,
        )
        if isinstance(selector_res, Refusal):
            return make_refusal(
                selector_res.code,
                phase=phase,
                retry_kind=selector_res.retry_kind,
                history=history,
            )
        selector_verified = selector_res.data
        if type(selector_verified) is not VerifiedAuthority:
            return make_refusal(
                RefusalCode.ISSUER_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if selector_verified.subject != expected_subject:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        peer_proc = _strict_proc_registration(getattr(peer, "process", None))
        if not peer_proc or not _strict_peer_registration(peer):
            return make_refusal(
                RefusalCode.PEER_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if not selector_verified.actors or any(
            not _strict_proc_registration(actor) for actor in selector_verified.actors
        ):
            return make_refusal(
                RefusalCode.PEER_UNVERIFIED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if not any(
            _same_strict_proc_registration(actor, peer.process)
            for actor in selector_verified.actors
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if intended_effect not in selector_verified.operations:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        verified_by_ref: dict[AuthorityRef, VerifiedAuthority] = {
            job.selector_issuer: selector_verified,
        }
        verified_list: list[VerifiedAuthority] = []
        for auth_ref in job.authority_refs:
            ver_res = self._issuer_verifier.verify(
                auth_ref,
                peer,
                expected_subject,
                required_effects,
                snapshot.verified_at,
            )
            if isinstance(ver_res, Refusal):
                return make_refusal(
                    ver_res.code,
                    phase=phase,
                    retry_kind=ver_res.retry_kind,
                    history=history,
                )
            verified = ver_res.data
            if type(verified) is not VerifiedAuthority:
                return make_refusal(
                    RefusalCode.ISSUER_UNVERIFIED,
                    phase=phase,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=history,
                )
            if verified.subject != expected_subject:
                return make_refusal(
                    RefusalCode.SUBJECT_MISMATCH,
                    phase=phase,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=history,
                )
            if not verified.actors or any(
                not _strict_proc_registration(actor) for actor in verified.actors
            ):
                return make_refusal(
                    RefusalCode.PEER_UNVERIFIED,
                    phase=phase,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=history,
                )
            if not any(
                _same_strict_proc_registration(actor, peer.process)
                for actor in verified.actors
            ):
                return make_refusal(
                    RefusalCode.SUBJECT_MISMATCH,
                    phase=phase,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=history,
                )
            if intended_effect not in verified.operations:
                return make_refusal(
                    RefusalCode.SCOPE_MISMATCH,
                    phase=phase,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                    history=history,
                )
            verified_by_ref[auth_ref] = verified
            verified_list.append(verified)

        cond_table = getattr(self._issuer_verifier, "condition_table", None)
        if (
            evaluate_registry_conditions(
                job,
                verified_by_ref,
                condition_table=cond_table,
            )
            is not None
        ):
            return make_refusal(
                RefusalCode.CONDITIONS_UNMET,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        return tuple(verified_list)

    def _build_evidence(
        self,
        *,
        job: SelectedJob,
        peer: AuthenticatedPeer,
        phase: Phase,
        boundary: Boundary,
        effect: SelectedOperation,
        window: NativeSubject | None = None,
        extra_processes: tuple[NativeProcessRef, ...] = (),
        receiving: tuple[ImmutableReference, ...] = (),
    ) -> DecisionEvidence:
        seen: list[NativeProcessRef] = [peer.process]
        for proc in extra_processes:
            if not any(_proc_ref(p) == _proc_ref(proc) for p in seen):
                seen.append(proc)
        return DecisionEvidenceRecord(
            selected_job=job,
            authority_revisions=job.authority_refs,
            window=window,
            processes=tuple(seen),
            effect=effect,
            phase=phase,
            boundary=boundary,
            source=self._source_ref_for_job(job),
            closure=job.reviewed_closure_ref,
            compatibility=job.compatibility_profile,
            receiving=receiving,
        )

    def for_submit(
        self,
        peer: AuthenticatedPeer,
        workflow_name: str,
    ) -> Result[SelectedJob]:
        phase = Phase.A
        boundary: Boundary = "A_PRE_CREATE"
        history = self._history_for(None)
        peer_refusal = self._verify_peer(peer, phase=phase, history=history)
        if peer_refusal is not None:
            return peer_refusal
        if not isinstance(workflow_name, str) or not workflow_name.strip():
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        snapshot_or_refusal = self._require_ready(phase=phase, history=history)
        if isinstance(snapshot_or_refusal, Refusal):
            return snapshot_or_refusal
        snapshot = snapshot_or_refusal

        matching: list[SelectedJob] = []
        for job in snapshot.jobs:
            target = job.pre_dispatch_or_running_job
            if (
                type(target) is PreDispatchJob
                and target.designated_workflow == workflow_name
            ):
                matching.append(job)

        if not matching:
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if len(matching) > 1:
            return make_refusal(
                RefusalCode.SELECTION_AMBIGUOUS,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        selected = matching[0]
        effect = default_effect_for_job(selected, boundary)
        verified_or_refusal = self._validate_job_authorities(
            snapshot=snapshot,
            job=selected,
            peer=peer,
            phase=phase,
            boundary=boundary,
            intended_effect=effect,
            history=history,
        )
        if isinstance(verified_or_refusal, Refusal):
            return verified_or_refusal

        return AcceptedData(
            data=selected,
            evidence=self._build_evidence(
                job=selected,
                peer=peer,
                phase=phase,
                boundary=boundary,
                effect=effect,
            ),
        )

    def for_run(
        self,
        peer: AuthenticatedPeer,
        execution_uuid: str,
        dispatch_identity: DispatchIdentity,
    ) -> Result[SelectedJob]:
        phase = Phase.A
        boundary: Boundary = "A_PRE_ARM"
        history = self._history_for(None)
        peer_refusal = self._verify_peer(peer, phase=phase, history=history)
        if peer_refusal is not None:
            return peer_refusal
        if (
            not isinstance(execution_uuid, str)
            or not execution_uuid.strip()
            or type(dispatch_identity) is not DispatchIdentity
        ):
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if dispatch_identity.execution_uuid != execution_uuid:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        snapshot_or_refusal = self._require_ready(phase=phase, history=history)
        if isinstance(snapshot_or_refusal, Refusal):
            return snapshot_or_refusal
        snapshot = snapshot_or_refusal

        exact_matches: list[SelectedJob] = []
        same_exec_wrong_dispatch: list[SelectedJob] = []
        for job in snapshot.jobs:
            target = job.pre_dispatch_or_running_job
            if type(target) is JobKey:
                if target.dispatch == dispatch_identity:
                    exact_matches.append(job)
                elif target.dispatch.execution_uuid == execution_uuid:
                    same_exec_wrong_dispatch.append(job)
            elif (
                type(target) is PreDispatchJob
                and target.execution_uuid == execution_uuid
            ):
                same_exec_wrong_dispatch.append(job)

        if not exact_matches:
            if same_exec_wrong_dispatch:
                return make_refusal(
                    RefusalCode.DISPATCH_CHANGED,
                    phase=phase,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                    history=history,
                )
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if len(exact_matches) > 1:
            return make_refusal(
                RefusalCode.SELECTION_AMBIGUOUS,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        selected = exact_matches[0]
        effect = default_effect_for_job(selected, boundary)
        verified_or_refusal = self._validate_job_authorities(
            snapshot=snapshot,
            job=selected,
            peer=peer,
            phase=phase,
            boundary=boundary,
            intended_effect=effect,
            history=history,
        )
        if isinstance(verified_or_refusal, Refusal):
            return verified_or_refusal

        return AcceptedData(
            data=selected,
            evidence=self._build_evidence(
                job=selected,
                peer=peer,
                phase=phase,
                boundary=boundary,
                effect=effect,
            ),
        )

    def check_current(
        self,
        peer: AuthenticatedPeer,
        selected_job_revision: str,
        boundary: Boundary,
        intended_effect: SelectedOperation,
        request_identity: RequestIdentity | None = None,
    ) -> Result[CurrentBinding]:
        try:
            phase = boundary_to_phase(boundary)
        except ValueError:
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        default_seq = (
            SequenceUse.UNUSED
            if boundary in ("B_PRE_REQUEST", "C_PRE_REQUEST")
            else SequenceUse.NOT_APPLICABLE
        )
        history = self._history_for(request_identity, default_sequence=default_seq)

        peer_refusal = self._verify_peer(peer, phase=phase, history=history)
        if peer_refusal is not None:
            return peer_refusal
        if (
            not isinstance(selected_job_revision, str)
            or not selected_job_revision.strip()
            or type(intended_effect) is not SelectedOperation
        ):
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        snapshot_or_refusal = self._require_ready(phase=phase, history=history)
        if isinstance(snapshot_or_refusal, Refusal):
            return snapshot_or_refusal
        snapshot = snapshot_or_refusal

        if not snapshot.jobs:
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )

        matching = [
            job
            for job in snapshot.jobs
            if job.selection_revision == selected_job_revision
        ]
        if not matching:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if len(matching) > 1:
            return make_refusal(
                RefusalCode.SELECTION_AMBIGUOUS,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        selected = matching[0]
        if (
            request_identity is not None
            and request_identity.selection.selection_revision
            != selected.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        verified_or_refusal = self._validate_job_authorities(
            snapshot=snapshot,
            job=selected,
            peer=peer,
            phase=phase,
            boundary=boundary,
            intended_effect=intended_effect,
            history=history,
        )
        if isinstance(verified_or_refusal, Refusal):
            return verified_or_refusal

        binding = CurrentBinding(
            selected_job=selected,
            authority_revisions=selected.authority_refs,
            boundary=boundary,
            intended_effect=intended_effect,
        )
        return AcceptedData(
            data=binding,
            evidence=self._build_evidence(
                job=selected,
                peer=peer,
                phase=phase,
                boundary=boundary,
                effect=intended_effect,
            ),
        )

    def bind_created(
        self,
        peer: AuthenticatedPeer,
        current_binding: CurrentBinding,
        actual_creation: ActualCreation,
    ) -> Result[WindowBinding]:
        phase = Phase.A
        boundary: Boundary = "A_PRE_ARM"
        history = self._history_for(None)

        peer_refusal = self._verify_peer(peer, phase=phase, history=history)
        if peer_refusal is not None:
            return peer_refusal
        if (
            type(current_binding) is not CurrentBinding
            or type(actual_creation) is not ActualCreation
        ):
            return make_refusal(
                RefusalCode.WINDOW_INELIGIBLE,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if current_binding.boundary not in ("A_PRE_CREATE", "A_PRE_ARM"):
            return make_refusal(
                RefusalCode.WINDOW_INELIGIBLE,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        rechecked = self.check_current(
            peer,
            current_binding.selected_job.selection_revision,
            boundary,
            current_binding.intended_effect,
        )
        if isinstance(rechecked, Refusal):
            return rechecked
        if rechecked.data.selected_job != current_binding.selected_job:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        existing = self._created_windows.get(actual_creation.window_id)
        if existing is not None and existing.actual_creation != actual_creation:
            return make_refusal(
                RefusalCode.WINDOW_INELIGIBLE,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )

        window_binding = WindowBinding(
            current=rechecked.data,
            actual_creation=actual_creation,
        )
        self._created_windows[actual_creation.window_id] = window_binding
        window_subject = ExistingSubjectRecord(identity=actual_creation.object_identity)
        return AcceptedData(
            data=window_binding,
            evidence=self._build_evidence(
                job=rechecked.data.selected_job,
                peer=peer,
                phase=phase,
                boundary=boundary,
                effect=rechecked.data.intended_effect,
                window=window_subject,
                extra_processes=(actual_creation.creator,),
            ),
        )


# ---------------------------------------------------------------------------
# Explicit test-only doubles (never active by default in production)
# ---------------------------------------------------------------------------


class InMemoryPeerVerifier:
    """Explicit test double for peer channel + process registration verification."""

    def __init__(self, allowed_peers: tuple[AuthenticatedPeer, ...] = ()) -> None:
        self._allowed: dict[tuple[str, str], AuthenticatedPeer] = {}
        for p in allowed_peers:
            self.register_peer(p)

    def register_peer(self, peer: AuthenticatedPeer) -> None:
        peer_ref = _peer_ref(peer)
        proc_ref = _proc_ref(getattr(peer, "process", None))
        if peer_ref and proc_ref:
            self._allowed[(peer_ref, proc_ref)] = peer

    def revoke_peer(self, peer: AuthenticatedPeer) -> None:
        peer_ref = _peer_ref(peer)
        proc_ref = _proc_ref(getattr(peer, "process", None))
        if peer_ref and proc_ref:
            self._allowed.pop((peer_ref, proc_ref), None)

    def verify_peer(self, peer: AuthenticatedPeer) -> bool:
        peer_ref = _peer_ref(peer)
        proc_ref = _proc_ref(getattr(peer, "process", None))
        if not peer_ref or not proc_ref:
            return False
        key = (peer_ref, proc_ref)
        expected = self._allowed.get(key)
        return expected is not None and expected == peer


@dataclass(frozen=True, slots=True, kw_only=True)
class _StoredIssuerRecord:
    ref: AuthorityRef
    verified: VerifiedAuthority
    job_Lookup: SelectedJob
    revoked: bool = False
    expired: bool = False


class InMemoryIssuerVerifier(IssuerVerifier):
    """Explicit test-only ``IssuerVerifier`` double."""

    def __init__(self) -> None:
        self._records: dict[AuthorityRef, _StoredIssuerRecord] = {}
        self._records_by_job: dict[tuple[AuthorityRef, str], _StoredIssuerRecord] = {}

    def register_authority(
        self,
        ref: AuthorityRef,
        verified: VerifiedAuthority,
        *,
        job: SelectedJob,
        revoked: bool = False,
        expired: bool = False,
    ) -> None:
        rec = _StoredIssuerRecord(
            ref=ref,
            verified=verified,
            job_Lookup=job,
            revoked=revoked,
            expired=expired,
        )
        self._records[ref] = rec
        self._records_by_job[(ref, job.selection_revision)] = rec

    def set_revoked(self, ref: AuthorityRef, revoked: bool = True) -> None:
        rec = self._records.get(ref)
        if rec is not None:
            self._records[ref] = _StoredIssuerRecord(
                ref=rec.ref,
                verified=rec.verified,
                job_Lookup=rec.job_Lookup,
                revoked=revoked,
                expired=rec.expired,
            )
        for key, item in list(self._records_by_job.items()):
            if key[0] == ref:
                self._records_by_job[key] = _StoredIssuerRecord(
                    ref=item.ref,
                    verified=item.verified,
                    job_Lookup=item.job_Lookup,
                    revoked=revoked,
                    expired=item.expired,
                )

    def set_expired(self, ref: AuthorityRef, expired: bool = True) -> None:
        rec = self._records.get(ref)
        if rec is not None:
            self._records[ref] = _StoredIssuerRecord(
                ref=rec.ref,
                verified=rec.verified,
                job_Lookup=rec.job_Lookup,
                revoked=rec.revoked,
                expired=expired,
            )
        for key, item in list(self._records_by_job.items()):
            if key[0] == ref:
                self._records_by_job[key] = _StoredIssuerRecord(
                    ref=item.ref,
                    verified=item.verified,
                    job_Lookup=item.job_Lookup,
                    revoked=item.revoked,
                    expired=expired,
                )

    def verify(
        self,
        ref: AuthorityRef,
        peer: AuthenticatedPeer,
        subject: SelectedSubject,
        effects: EffectSet,
        at: TrustedInstant,
    ) -> Result[VerifiedAuthority]:
        if (
            type(ref) is not AuthorityRef
            or type(subject) is not SelectedSubject
            or type(at) is not TrustedInstant
            or not isinstance(effects, (frozenset, tuple))
            or not effects
        ):
            return make_refusal(
                RefusalCode.ISSUER_UNVERIFIED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        rec = self._records_by_job.get((ref, subject.selection_revision))
        if rec is None:
            rec = self._records.get(ref)
        if rec is None:
            return make_refusal(
                RefusalCode.ISSUER_UNVERIFIED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if rec.revoked:
            return make_refusal(
                RefusalCode.AUTHORITY_REVOKED,
                phase=Phase.A,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if rec.expired or at.clock_domain != rec.verified.not_before.clock_domain:
            return make_refusal(
                RefusalCode.AUTHORITY_EXPIRED,
                phase=Phase.A,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        at_int = parse_strict_instant_int(at.reading)
        nb_int = parse_strict_instant_int(rec.verified.not_before.reading)
        exp_int = parse_strict_instant_int(rec.verified.expires_at.reading)
        if at_int is None or nb_int is None or exp_int is None:
            return make_refusal(
                RefusalCode.AUTHORITY_EXPIRED,
                phase=Phase.A,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if not (nb_int <= at_int < exp_int):
            return make_refusal(
                RefusalCode.AUTHORITY_EXPIRED,
                phase=Phase.A,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if rec.verified.subject != subject:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if (
            not _peer_ref(peer)
            or not _proc_ref(getattr(peer, "process", None))
            or not rec.verified.actors
            or any(not _proc_ref(actor) for actor in rec.verified.actors)
        ):
            return make_refusal(
                RefusalCode.PEER_UNVERIFIED,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if not any(
            _same_non_empty_proc_ref(actor, peer.process)
            for actor in rec.verified.actors
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if not set(effects).issubset(set(rec.verified.operations)):
            return make_refusal(
                RefusalCode.SCOPE_MISMATCH,
                phase=Phase.A,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        for cond in rec.verified.conditions:
            if (
                type(cond) is not ConditionRef
                or type(cond.authority) is not AuthorityRef
                or not is_text(cond.revision)
                or cond.condition_id not in CONDITION_PREDICATES
                or not CONDITION_PREDICATES[cond.condition_id](rec.job_Lookup)
            ):
                return make_refusal(
                    RefusalCode.CONDITIONS_UNMET,
                    phase=Phase.A,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                )
        effect = sorted(
            effects,
            key=lambda item: (item.domain, item.operation, item.revision),
        )[0]
        source_ref = ImmutableReferenceRecord(
            path=f"source/{rec.job_Lookup.selection_revision}",
            digest=rec.job_Lookup.expected_source_digest,
            length=64,
            revision=rec.job_Lookup.selection_revision,
        )
        evidence = DecisionEvidenceRecord(
            selected_job=rec.job_Lookup,
            authority_revisions=rec.job_Lookup.authority_refs,
            window=None,
            processes=(peer.process,),
            effect=effect,
            phase=Phase.A,
            boundary="A_PRE_CREATE",
            source=source_ref,
            closure=rec.job_Lookup.reviewed_closure_ref,
            compatibility=rec.job_Lookup.compatibility_profile,
        )
        return AcceptedData(data=rec.verified, evidence=evidence)


class InMemorySelectionPublisher:
    """Explicit test-only publisher/admin object, separate from reader ports."""

    def __init__(self) -> None:
        self._snapshot: SelectionSnapshot | None = None

    def publish_snapshot(self, snapshot: SelectionSnapshot | None) -> None:
        if snapshot is not None and type(snapshot) is not SelectionSnapshot:
            raise TypeError("publish_snapshot requires SelectionSnapshot | None")
        self._snapshot = snapshot

    def reader(self) -> InMemorySelectionSnapshotProvider:
        return InMemorySelectionSnapshotProvider(self)


class InMemorySelectionSnapshotProvider:
    """Read-only view bound to an ``InMemorySelectionPublisher``."""

    def __init__(self, publisher: InMemorySelectionPublisher) -> None:
        self._publisher = publisher

    def read_snapshot(self) -> SelectionSnapshot | None:
        return self._publisher._snapshot


class InMemoryRequestHistoryProvider:
    """Explicit test-only provider of prior request admission/effect/sequence truth."""

    def __init__(self) -> None:
        self._history: dict[RequestIdentity, PriorRequestHistory] = {}

    def record_history(
        self,
        request_identity: RequestIdentity,
        history: PriorRequestHistory,
    ) -> None:
        self._history[request_identity] = history

    def lookup_history(
        self,
        request_identity: RequestIdentity,
    ) -> PriorRequestHistory:
        return self._history.get(request_identity, PriorRequestHistory())


__all__ = [
    "COMPATIBILITY_CORPUS_SCHEMA",
    "LOADED_CLOSURE_SCHEMA",
    "REVIEWED_GRAPH_SCHEMA",
    "AuthorityRegistryService",
    "DecisionEvidenceRecord",
    "ExistingSubjectRecord",
    "FutureSubjectRecord",
    "ImmutableReferenceRecord",
    "InMemoryIssuerVerifier",
    "InMemoryPeerVerifier",
    "InMemoryRequestHistoryProvider",
    "InMemorySelectionPublisher",
    "InMemorySelectionSnapshotProvider",
    "PeerVerifierProtocol",
    "PriorRequestHistory",
    "RequestHistoryProvider",
    "SelectionSnapshot",
    "SelectionSnapshotProvider",
    "boundary_to_phase",
    "default_effect_for_job",
    "make_refusal",
]
