"""P3 T5-N2: Read-only SelectionSnapshotProvider and RequestHistoryProvider over DbAdmissionTransport.

Joins Temper's own run and admission records (WorkflowRun, AdmissionRecord,
DispatchIdentity) to P3 SelectedJob and p3_host_contracts SelectedHostJob so
caller flags or environment variables cannot spoof job, kit, calibration, or
route selection. Inert and read-only by default (WRITES_ADMITTED = False).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlmodel import select

from p3_host_contracts.selection import (
    CalibrationSelection as HostCalibrationSelection,
)
from p3_host_contracts.selection import (
    CallerSelection,
)
from p3_host_contracts.selection import (
    ProjectSelection as HostProjectSelection,
)
from p3_host_contracts.selection import (
    SelectedHostJob as GenericSelectedHostJob,
)
from temper_ai.config.admission_contract import (
    SUPPORTED_MODE,
    AdmissionRecord,
    AdmissionRefused,
    DescriptorAuthority,
    DispatchIdentity,
)
from temper_ai.database import get_session
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AuthorityRef,
    Boundary,
    CalibrationSelection,
    CompatibilityProfile,
    ConditionRef,
    EffectSet,
    ImmutableReference,
    JobKey,
    Phase,
    PreDispatchJob,
    ProjectSelection,
    Refusal,
    RefusalCode,
    RequestIdentity,
    Result,
    RetryKind,
    SelectedJob,
    SelectedSubject,
    Selection,
    TrustedInstant,
)
from temper_ai.p3_authority.host_types import (
    RawRef,
    ReviewedSourceGraph,
    SelectedHostJob,
)
from temper_ai.p3_authority.native_values import (
    NativeProcessRefValue,
    NativeWitnessValue,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    ImmutableReferenceRecord,
    PriorRequestHistory,
    RequestHistoryProvider,
    SelectionSnapshot,
    SelectionSnapshotProvider,
    default_effect_for_job,
    make_refusal,
)
from temper_ai.runner.admission import DbAdmissionTransport
from temper_ai.runner.models import WorkflowRun

WRITES_ADMITTED: Final[bool] = False
SUPPORTED_SELECTION_ROUTE: Final[str] = SUPPORTED_MODE
DEFAULT_SELECTION_SNAPSHOT_PROVIDER: Final[SelectionSnapshotProvider | None] = None
DEFAULT_REQUEST_HISTORY_PROVIDER: Final[RequestHistoryProvider | None] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HostSelectionHandle:
    """NativeSelection carrier for host-join selections."""

    selection_reference: str
    selection_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RunSelectionBinding:
    """Authoritative admission-side P3 selection metadata bound to an execution_uuid."""

    execution_uuid: str
    authority: DescriptorAuthority
    job_revision: str
    selection_revision: str
    selector_issuer: AuthorityRef
    selection: Selection
    reviewed_closure_ref: ImmutableReference
    compatibility_profile: CompatibilityProfile
    authorized_operations: EffectSet
    conditions: tuple[ConditionRef, ...] = ()
    authority_refs: tuple[AuthorityRef, ...] = ()
    route: str = SUPPORTED_SELECTION_ROUTE
    expected_dispatch: DispatchIdentity | None = None
    reviewed_graph: ReviewedSourceGraph | None = None
    allowed_rows: frozenset[str] = frozenset({"row-default"})
    caller_role: str = "checker"
    runtime_route: str = "temper-dev"
    creator_launch_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestHistoryEntry:
    """Immutable recorded request history entry associated with an admitted run."""

    execution_uuid: str
    request_identity: RequestIdentity
    history: PriorRequestHistory = field(default_factory=PriorRequestHistory)


def _dispatch_identity_matches(
    db_dispatch: DispatchIdentity,
    claimed_dispatch: DispatchIdentity,
    *,
    row_attempts: int,
) -> bool:
    """Verify live DB DispatchIdentity equals the claimed DispatchIdentity and row attempts."""
    return (
        db_dispatch == claimed_dispatch
        and row_attempts == db_dispatch.running_attempt
    )


def _selection_revision_matches(
    binding: RunSelectionBinding,
    immutable: Mapping[str, Any],
    descriptor: Mapping[str, Any],
) -> bool:
    """Verify the admitted DB record has not drifted from the bound selection revision."""
    recorded_revision = str(
        descriptor.get("selection_revision", binding.selection_revision)
    )
    return (
        str(immutable.get("descriptor_sha256", ""))
        == binding.authority.expected_descriptor_sha256
        and str(immutable.get("authority_receipt_id", ""))
        == binding.authority.receipt_id
        and recorded_revision == binding.selection_revision
    )


def _resolve_verified_route(
    binding: RunSelectionBinding,
    descriptor: Mapping[str, Any],
) -> str:
    """Resolve and verify the execution route from the binding and admitted descriptor."""
    descriptor_mode = str(descriptor.get("mode", SUPPORTED_SELECTION_ROUTE))
    if (
        binding.route != SUPPORTED_SELECTION_ROUTE
        or descriptor_mode != SUPPORTED_SELECTION_ROUTE
    ):
        return (
            binding.route
            if binding.route != SUPPORTED_SELECTION_ROUTE
            else descriptor_mode
        )
    return SUPPORTED_SELECTION_ROUTE


def _selection_matches_descriptor(
    selection: Selection,
    descriptor: Mapping[str, Any],
) -> bool:
    """Check that descriptor-pinned project/kit/calibration attributes match selection."""
    if isinstance(selection, ProjectSelection):
        if "project_id" in descriptor and str(descriptor["project_id"]) != selection.project_id:
            return False
        if "kit_id" in descriptor and str(descriptor["kit_id"]) != selection.kit_id:
            return False
        if "kit_sha256" in descriptor and str(descriptor["kit_sha256"]) != selection.kit_sha256:
            return False
        return True
    if isinstance(selection, CalibrationSelection):
        if "entry_id" in descriptor and str(descriptor["entry_id"]) != selection.entry_id:
            return False
        if (
            "calibration_run" in descriptor
            and str(descriptor["calibration_run"]) != selection.calibration_run
        ):
            return False
        if "round" in descriptor and str(descriptor["round"]) != selection.round:
            return False
        if (
            "copy_identity" in descriptor
            and str(descriptor["copy_identity"]) != selection.copy_identity
        ):
            return False
        return True
    return False


def verify_boundary_transition(
    prior_job: SelectedJob,
    current_job: SelectedJob,
    *,
    phase: Phase = Phase.B,
    history: PriorRequestHistory | None = None,
) -> Result[SelectedJob]:
    """Verify SelectedJob continuity across for_submit, for_run, and check_current."""
    prior_target = prior_job.pre_dispatch_or_running_job
    current_target = current_job.pre_dispatch_or_running_job
    prior_exec = (
        prior_target.execution_uuid
        if isinstance(prior_target, PreDispatchJob)
        else prior_target.dispatch.execution_uuid
    )
    current_exec = (
        current_target.execution_uuid
        if isinstance(current_target, PreDispatchJob)
        else current_target.dispatch.execution_uuid
    )
    if prior_exec != current_exec:
        return make_refusal(
            RefusalCode.SELECTION_FOREIGN,
            phase=phase,
            retry_kind=RetryKind.NOT_APPLICABLE,
            history=history,
        )
    if (
        prior_job.selection_revision != current_job.selection_revision
        or prior_job.selection != current_job.selection
        or prior_job.approved_descriptor_digest != current_job.approved_descriptor_digest
        or prior_job.expected_source_digest != current_job.expected_source_digest
        or prior_job.reviewed_closure_ref != current_job.reviewed_closure_ref
        or prior_job.compatibility_profile != current_job.compatibility_profile
        or prior_target.job_revision != current_target.job_revision
    ):
        return make_refusal(
            RefusalCode.SELECTION_CHANGED,
            phase=phase,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            history=history,
        )
    return AcceptedData(
        data=current_job,
        evidence=_build_snapshot_evidence(current_job, phase=phase),
    )


def _make_default_reviewed_graph(job: SelectedJob) -> Any:
    return RawRef(
        root_locator=f"root://closure/{job.selection_revision}",
        relative_path=job.reviewed_closure_ref.path,
        byte_length=job.reviewed_closure_ref.length,
        sha256=job.reviewed_closure_ref.digest,
    )


def project_selected_host_job(
    job: SelectedJob,
    *,
    binding: RunSelectionBinding | None = None,
) -> SelectedHostJob:
    """Project an authoritative SelectedJob into a p3_host_contracts SelectedHostJob."""
    target = job.pre_dispatch_or_running_job
    if isinstance(target, JobKey):
        job_id = target.dispatch.execution_uuid
        attempt_id = f"{target.dispatch.dispatch_nonce}:{target.dispatch.running_attempt}"
    else:
        job_id = target.execution_uuid or target.designated_workflow
        attempt_id = target.job_revision

    build_ref = RawRef(
        root_locator=f"root://build/{job.selection_revision}",
        relative_path=job.selection.build_ref.path,
        byte_length=job.selection.build_ref.length,
        sha256=job.selection.build_ref.digest,
    )
    expected_binding_ref = RawRef(
        root_locator=f"root://pub/{job.selection_revision}",
        relative_path=job.selection.publication_ref.path,
        byte_length=job.selection.publication_ref.length,
        sha256=job.selection.publication_ref.digest,
    )
    if isinstance(job.selection, ProjectSelection):
        route: HostProjectSelection | HostCalibrationSelection = HostProjectSelection(
            project_id=job.selection.project_id,
            kit_ref=RawRef(
                root_locator=f"root://kit/{job.selection.project_id}",
                relative_path=f"{job.selection.kit_id}.json",
                byte_length=64,
                sha256=job.selection.kit_sha256,
            ),
            expected_binding_ref=expected_binding_ref,
        )
    else:
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

    reviewed_graph = (
        binding.reviewed_graph
        if binding is not None and binding.reviewed_graph is not None
        else _make_default_reviewed_graph(job)
    )
    allowed_rows = (
        binding.allowed_rows if binding is not None else frozenset({"row-default"})
    )
    caller_role = binding.caller_role if binding is not None else "checker"
    runtime_route = binding.runtime_route if binding is not None else "temper-dev"
    creator_launch_id = (
        binding.creator_launch_id
        if binding is not None and binding.creator_launch_id is not None
        else f"launch:{job_id}:{job.selection_revision}"
    )
    caller = CallerSelection(
        entrypoint=getattr(job, "route", SUPPORTED_SELECTION_ROUTE),
        source_review_ref=reviewed_graph,
        caller_role=caller_role,
        writer=job.selector_issuer.issuer_id,
        allowed_rows=allowed_rows,
        inspect_variant=job.compatibility_profile.inspect,
        runtime_route=runtime_route,
    )
    native_selection = HostSelectionHandle(
        selection_reference=f"sel://{job_id}/{job.selection_revision}",
        selection_revision=job.selection_revision,
    )
    return SelectedHostJob(
        selection=native_selection,
        job_id=job_id,
        attempt_id=attempt_id,
        publication_id=job.selection.publication_revision,
        build_ref=build_ref,
        route=route,
        creator_launch_id=creator_launch_id,
        caller=caller,
    )


def verify_selected_host_job(
    job: SelectedJob,
    host_job: GenericSelectedHostJob[Any, Any],
    *,
    phase: Phase = Phase.B,
    history: PriorRequestHistory | None = None,
) -> Result[GenericSelectedHostJob[Any, Any]]:
    """Verify a SelectedHostJob matches the authoritative SelectedJob without spoofing."""
    job_route = getattr(job, "route", SUPPORTED_SELECTION_ROUTE)
    if (
        job_route != SUPPORTED_SELECTION_ROUTE
        or host_job.caller.entrypoint != SUPPORTED_SELECTION_ROUTE
    ):
        return make_refusal(
            RefusalCode.ROUTE_UNSUPPORTED,
            phase=phase,
            retry_kind=RetryKind.NOT_APPLICABLE,
            history=history,
        )

    expected = project_selected_host_job(job)
    if host_job.job_id != expected.job_id:
        return make_refusal(
            RefusalCode.SELECTION_FOREIGN,
            phase=phase,
            retry_kind=RetryKind.NOT_APPLICABLE,
            history=history,
        )
    if (
        isinstance(job.selection, ProjectSelection)
        and job.selection.run_id != expected.job_id
    ):
        return make_refusal(
            RefusalCode.SELECTION_FOREIGN,
            phase=phase,
            retry_kind=RetryKind.NOT_APPLICABLE,
            history=history,
        )

    if isinstance(expected.route, HostProjectSelection):
        if not isinstance(host_job.route, HostProjectSelection):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if (
            host_job.route.project_id != expected.route.project_id
            or host_job.route.kit_ref.sha256 != expected.route.kit_ref.sha256
            or host_job.route.kit_ref.relative_path != expected.route.kit_ref.relative_path
            or host_job.publication_id != expected.publication_id
            or host_job.build_ref.sha256 != expected.build_ref.sha256
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
    else:
        if not isinstance(host_job.route, HostCalibrationSelection):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if (
            host_job.route.entry_id != expected.route.entry_id
            or host_job.route.round_id != expected.route.round_id
            or host_job.route.calibration_run != expected.route.calibration_run
            or host_job.route.copy_id != expected.route.copy_id
            or host_job.route.manifest_ref.sha256 != expected.route.manifest_ref.sha256
            or host_job.publication_id != expected.publication_id
            or host_job.build_ref.sha256 != expected.build_ref.sha256
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

    if (
        getattr(host_job.selection, "selection_revision", None) != job.selection_revision
        or host_job.attempt_id != expected.attempt_id
    ):
        return make_refusal(
            RefusalCode.SELECTION_CHANGED,
            phase=phase,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            history=history,
        )

    return AcceptedData(
        data=host_job,
        evidence=_build_snapshot_evidence(job, phase=phase),
    )


_SNAPSHOT_PROCESS: Final[NativeProcessRefValue] = NativeProcessRefValue(
    "proc:temper-selection-snapshot"
)


def _build_snapshot_evidence(
    job: SelectedJob,
    *,
    phase: Phase = Phase.B,
    boundary: Boundary = "B_PRE_REQUEST",
) -> DecisionEvidenceRecord:
    return DecisionEvidenceRecord(
        selected_job=job,
        authority_revisions=job.authority_refs or (job.selector_issuer,),
        window=None,
        processes=(_SNAPSHOT_PROCESS,),
        effect=default_effect_for_job(job, boundary),
        phase=phase,
        boundary=boundary,
        source=ImmutableReferenceRecord(
            path=f"source/{job.selection_revision}",
            digest=job.expected_source_digest,
            length=64,
            revision=job.selection_revision,
        ),
        closure=job.reviewed_closure_ref,
        compatibility=job.compatibility_profile,
    )

_DEFAULT_VERIFIED_AT: Final[TrustedInstant] = TrustedInstant(
    clock_domain="monotonic:temper-selection-snapshot",
    reading="1000",
    witness=NativeWitnessValue("witness:temper-selection-snapshot"),
)


class DbSelectionSnapshotProvider:
    """Read-only SelectionSnapshotProvider backed by DbAdmissionTransport."""

    def __init__(
        self,
        transport: DbAdmissionTransport | None = None,
        *,
        bindings: Sequence[RunSelectionBinding] | Callable[[], Sequence[RunSelectionBinding]] = (),
        snapshot_revision: str = "db-snapshot-rev-1",
        verified_at: TrustedInstant | None = None,
        subjects: Mapping[str, SelectedSubject] | None = None,
    ) -> None:
        self._transport = transport
        self._bindings_source = bindings
        self._snapshot_revision = snapshot_revision
        self._verified_at = verified_at or _DEFAULT_VERIFIED_AT
        self._subjects = dict(subjects) if subjects is not None else None

    def _current_bindings(self) -> tuple[RunSelectionBinding, ...]:
        if callable(self._bindings_source):
            return tuple(self._bindings_source())
        return tuple(self._bindings_source)

    def _load_row_and_record(
        self, binding: RunSelectionBinding
    ) -> tuple[WorkflowRun, AdmissionRecord, Mapping[str, Any]] | None:
        if self._transport is None:
            return None
        with get_session() as session:
            row = session.scalars(
                select(WorkflowRun).where(
                    WorkflowRun.execution_id == binding.execution_uuid
                )
            ).first()
            if row is None:
                return None
            session.expunge(row)
        try:
            record = self._transport._row_record(row)
            descriptor = self._transport._descriptor(record)
            return row, record, descriptor
        except AdmissionRefused:
            if (
                binding.authority is None
                or binding.authority == self._transport.authority
            ):
                return None
        transport = copy.copy(self._transport)
        transport.authority = binding.authority
        try:
            record = transport._row_record(row)
            descriptor = transport._descriptor(record)
        except AdmissionRefused:
            return None
        return row, record, descriptor

    def _build_selected_job(
        self, binding: RunSelectionBinding
    ) -> SelectedJob | None:
        loaded = self._load_row_and_record(binding)
        if loaded is None:
            return None
        row, record, descriptor = loaded
        raw = record.value()
        immutable = raw["immutable"]
        dispatch_map = raw["dispatch"]

        if (
            str(immutable.get("authorized_caller_label", ""))
            != binding.authority.authorized_caller_label
        ):
            return None
        if not _selection_matches_descriptor(binding.selection, descriptor):
            return None
        if (
            isinstance(binding.selection, ProjectSelection)
            and binding.selection.run_id != row.execution_id
        ):
            return None

        descriptor_sha = str(immutable["descriptor_sha256"])
        source_sha = binding.authority.expected_source_sha256
        phase = str(dispatch_map.get("phase", ""))

        if row.status == "queued" and phase == "queued" and int(row.attempts) == 0:
            target: PreDispatchJob | JobKey = PreDispatchJob(
                designated_workflow=row.workflow_name,
                job_revision=binding.job_revision,
                execution_uuid=row.execution_id,
                descriptor_digest=descriptor_sha,
            )
        elif row.status == "running" and phase == "running" and int(row.attempts) >= 1:
            db_dispatch = DispatchIdentity(
                execution_uuid=row.execution_id,
                dispatch_nonce=str(dispatch_map["dispatch_nonce"]),
                running_attempt=int(dispatch_map["running_attempt"]),
            )
            claimed_dispatch = (
                binding.expected_dispatch
                if binding.expected_dispatch is not None
                else db_dispatch
            )
            if _dispatch_identity_matches(
                db_dispatch, claimed_dispatch, row_attempts=int(row.attempts)
            ):
                target = JobKey(
                    dispatch=claimed_dispatch,
                    job_revision=binding.job_revision,
                )
            else:
                target = PreDispatchJob(
                    designated_workflow=row.workflow_name,
                    job_revision=binding.job_revision,
                    execution_uuid=row.execution_id,
                    descriptor_digest=descriptor_sha,
                )
        else:
            return None

        if _selection_revision_matches(binding, immutable, descriptor):
            effective_revision = binding.selection_revision
        else:
            effective_revision = (
                f"{binding.selection_revision}:drifted:"
                f"{descriptor_sha[:12]}:{descriptor.get('selection_revision', '')}"
            )

        resolved_route = _resolve_verified_route(binding, descriptor)
        job = SelectedJob(
            pre_dispatch_or_running_job=target,
            selector_issuer=binding.selector_issuer,
            selection_revision=effective_revision,
            selection=binding.selection,
            approved_descriptor_digest=descriptor_sha,
            expected_source_digest=source_sha,
            reviewed_closure_ref=binding.reviewed_closure_ref,
            compatibility_profile=binding.compatibility_profile,
            authorized_operations=binding.authorized_operations,
            conditions=binding.conditions,
            authority_refs=binding.authority_refs,
        )
        if resolved_route != SUPPORTED_SELECTION_ROUTE:
            object.__setattr__(job, "route", resolved_route)
        return job

    def read_snapshot(self) -> SelectionSnapshot | None:
        """Read current SelectionSnapshot from DbAdmissionTransport (read-only)."""
        if self._transport is None:
            return None
        jobs: list[SelectedJob] = []
        for binding in self._current_bindings():
            job = self._build_selected_job(binding)
            if job is not None:
                jobs.append(job)
        return SelectionSnapshot(
            snapshot_revision=self._snapshot_revision,
            jobs=tuple(jobs),
            verified_at=self._verified_at,
            expected_subjects=dict(self._subjects) if self._subjects is not None else {},
        )

    def join_host_job(
        self,
        selected_job: SelectedJob,
        *,
        candidate_host_job: GenericSelectedHostJob[Any, Any] | None = None,
        prior_job: SelectedJob | None = None,
        phase: Phase = Phase.B,
        history: PriorRequestHistory | None = None,
    ) -> Result[SelectedHostJob]:
        """Join an authoritative SelectedJob to a p3_host_contracts SelectedHostJob."""
        if self._transport is None:
            return make_refusal(
                RefusalCode.AUTHORITY_UNAVAILABLE,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if prior_job is not None:
            transition = verify_boundary_transition(
                prior_job, selected_job, phase=phase, history=history
            )
            if isinstance(transition, Refusal):
                return transition

        job_route = getattr(selected_job, "route", SUPPORTED_SELECTION_ROUTE)
        if job_route != SUPPORTED_SELECTION_ROUTE:
            return make_refusal(
                RefusalCode.ROUTE_UNSUPPORTED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        target = selected_job.pre_dispatch_or_running_job
        exec_uuid = (
            target.execution_uuid
            if isinstance(target, PreDispatchJob)
            else target.dispatch.execution_uuid
        )
        matching_bindings = [
            b for b in self._current_bindings() if b.execution_uuid == exec_uuid
        ]
        if not matching_bindings:
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        if len(matching_bindings) > 1:
            return make_refusal(
                RefusalCode.SELECTION_AMBIGUOUS,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )

        binding = matching_bindings[0]
        loaded = self._load_row_and_record(binding)
        if loaded is None:
            return make_refusal(
                RefusalCode.SELECTION_MISSING,
                phase=phase,
                retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
                history=history,
            )
        row, record, descriptor = loaded
        raw = record.value()
        immutable = raw["immutable"]
        dispatch_map = raw["dispatch"]

        if _resolve_verified_route(binding, descriptor) != SUPPORTED_SELECTION_ROUTE:
            return make_refusal(
                RefusalCode.ROUTE_UNSUPPORTED,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if not _selection_matches_descriptor(selected_job.selection, descriptor):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if (
            isinstance(selected_job.selection, ProjectSelection)
            and selected_job.selection.run_id != row.execution_id
        ):
            return make_refusal(
                RefusalCode.SELECTION_FOREIGN,
                phase=phase,
                retry_kind=RetryKind.NOT_APPLICABLE,
                history=history,
            )
        if not _selection_revision_matches(binding, immutable, descriptor):
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                phase=phase,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                history=history,
            )
        if isinstance(target, JobKey):
            if row.status != "running" or str(dispatch_map.get("phase", "")) != "running":
                return make_refusal(
                    RefusalCode.DISPATCH_CHANGED,
                    phase=phase,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                    history=history,
                )
            db_dispatch = DispatchIdentity(
                execution_uuid=row.execution_id,
                dispatch_nonce=str(dispatch_map["dispatch_nonce"]),
                running_attempt=int(dispatch_map["running_attempt"]),
            )
            if not _dispatch_identity_matches(
                db_dispatch, target.dispatch, row_attempts=int(row.attempts)
            ):
                return make_refusal(
                    RefusalCode.DISPATCH_CHANGED,
                    phase=phase,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                    history=history,
                )

        projected = project_selected_host_job(selected_job, binding=binding)
        if candidate_host_job is not None:
            verified = verify_selected_host_job(
                selected_job, candidate_host_job, phase=phase, history=history
            )
            if isinstance(verified, Refusal):
                return verified
        return AcceptedData(
            data=projected,
            evidence=_build_snapshot_evidence(selected_job, phase=phase),
        )


class DbRequestHistoryProvider:
    """Read-only RequestHistoryProvider backed by DbAdmissionTransport."""

    def __init__(
        self,
        transport: DbAdmissionTransport | None = None,
        *,
        entries: Sequence[RequestHistoryEntry] | Callable[[], Sequence[RequestHistoryEntry]] = (),
        bindings: Sequence[RunSelectionBinding] | Callable[[], Sequence[RunSelectionBinding]] = (),
        default_history: PriorRequestHistory | None = None,
    ) -> None:
        self._transport = transport
        self._entries_source = entries
        self._bindings_source = bindings
        self._default_history = default_history or PriorRequestHistory()

    def _current_entries(self) -> tuple[RequestHistoryEntry, ...]:
        if callable(self._entries_source):
            return tuple(self._entries_source())
        return tuple(self._entries_source)

    def _current_bindings(self) -> tuple[RunSelectionBinding, ...]:
        if callable(self._bindings_source):
            return tuple(self._bindings_source())
        return tuple(self._bindings_source)

    def _run_has_valid_admission_envelope(self, execution_uuid: str) -> bool:
        if self._transport is None:
            return False
        with get_session() as session:
            row = session.scalars(
                select(WorkflowRun).where(
                    WorkflowRun.execution_id == execution_uuid
                )
            ).first()
            if row is None:
                return False
            session.expunge(row)
        transport = self._transport
        for spec in self._current_bindings():
            if (
                spec.execution_uuid == execution_uuid
                and spec.authority is not None
                and spec.authority != self._transport.authority
            ):
                transport = copy.copy(self._transport)
                transport.authority = spec.authority
                break
        try:
            transport._row_record(row)
        except AdmissionRefused:
            return False
        return True

    def lookup_history(
        self, request_identity: RequestIdentity
    ) -> PriorRequestHistory:
        """Look up PriorRequestHistory for request_identity via DbAdmissionTransport."""
        if self._transport is None:
            return self._default_history
        for entry in self._current_entries():
            if entry.request_identity == request_identity:
                if self._run_has_valid_admission_envelope(entry.execution_uuid):
                    return entry.history
        for spec in self._current_bindings():
            if spec.selection_revision == request_identity.selection.selection_revision:
                self._run_has_valid_admission_envelope(spec.execution_uuid)
        return self._default_history


__all__ = [
    "DEFAULT_REQUEST_HISTORY_PROVIDER",
    "DEFAULT_SELECTION_SNAPSHOT_PROVIDER",
    "SUPPORTED_SELECTION_ROUTE",
    "WRITES_ADMITTED",
    "DbRequestHistoryProvider",
    "DbSelectionSnapshotProvider",
    "HostSelectionHandle",
    "RequestHistoryEntry",
    "RunSelectionBinding",
    "project_selected_host_job",
    "verify_boundary_transition",
    "verify_selected_host_job",
]






