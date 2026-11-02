"""Typed worker/checker/child observation and root observation adapters for P3 T4.

Implements ``WorkerObserver`` and ``RootObserver`` against ``temper_ai.p3_authority.contract``
with zero import-time or startup I/O and no default provider installed:
- When no verified provider is configured, every observation or registration call
  returns an explicit ``Refusal(code=RefusalCode.AUTHORITY_UNAVAILABLE, ...)`` with
  truthful history, never synthesizing ``AcceptedData``.
- Observation permission (``ObservationGrant``) is verified before reading any
  process, root, or load-stream state; any unpermitted read attempt poisons the
  session and refuses with ``RefusalCode.OBSERVATION_NOT_AUTHORIZED``.
- Keeps host runtime and worker/checker/child runtime observations separate,
  effective actor identity separate from root file owner, planned Phase A
  ``FutureSubject`` separate from actual Phase B/C ``ExistingSubject`` /
  ``ProcessInstance``, and publication versus host_evidence roots separate in
  ``BothRootObservations``.
- Maps existing Temper seams (``box_profile.closure``, ``tree_digest``,
  ``box_view``, ``box_guard``, ``box_bootstrap``) to their true narrow
  guarantees and refuses any attempt to report them as complete coverage.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field, replace
from typing import Final, Literal, Protocol

from p3_source_closure import (
    LoadedClosureEnvelope,
    N3ObservationEpoch,
    ReviewedSourceGraph,
)
from p3_source_closure import (
    ProcessInstance as ClosureProcessInstance,
)
from temper_ai.p3_authority.child_registration import (
    ChildLaunchVerificationPort,
    ChildRegistrationRegistry,
    ChildRegistrationTicket,
    ProcessKey,
    RegisteredChildEntry,
)
from temper_ai.p3_authority.contract import (
    DECISION_SCHEMA,
    AcceptedData,
    BothRootObservations,
    Boundary,
    CompatibilityProfile,
    DecisionEvidence,
    EffectSet,
    ImmutableReference,
    NativeEventRange,
    NativeProcessRef,
    NativeWitness,
    ObservationGrant,
    ProcessInstance,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    RootObservation,
    RootObserver,
    RootScope,
    SelectedJob,
    WorkerObservation,
    WorkerObserver,
)
from temper_ai.p3_authority.coverage_bookkeeping import (
    ALL_N3_COVERAGE_CATEGORIES,
    CoverageBookkeeper,
    make_refusal,
)

WORKER_OBSERVATION_COMPAT_CORPUS_ID: Final[Literal["ops-host-compat-corpus/1"]] = (
    "ops-host-compat-corpus/1"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingSeamGuarantee:
    """True narrow guarantee of an existing Temper seam versus complete coverage."""

    seam_name: str
    module_path: str
    actual_guarantee: str
    establishes_complete_loaded_bytes: Literal[False] = field(default=False, init=False)
    establishes_authentic_process_origin: Literal[False] = field(default=False, init=False)
    refusal_code_when_claimed_as_complete: RefusalCode = RefusalCode.CLOSURE_INCOMPLETE


EXISTING_TEMPER_SEAM_GUARANTEES: Final[dict[str, ExistingSeamGuarantee]] = {
    "box_profile.closure": ExistingSeamGuarantee(
        seam_name="box_profile.closure",
        module_path="temper_ai.pi_agent.box_profile",
        actual_guarantee="outbound_network_endpoint_closure_only",
    ),
    "tree_digest": ExistingSeamGuarantee(
        seam_name="tree_digest",
        module_path="temper_ai.pi_agent.tree_digest",
        actual_guarantee="static_disk_file_tree_inventory_only",
    ),
    "box_view": ExistingSeamGuarantee(
        seam_name="box_view",
        module_path="temper_ai.pi_agent.box_view",
        actual_guarantee="startup_point_in_time_process_mount_env_view_only",
    ),
    "box_guard": ExistingSeamGuarantee(
        seam_name="box_guard",
        module_path="temper_ai.pi_agent.box_guard",
        actual_guarantee="command_launch_classification_only",
    ),
    "box_bootstrap": ExistingSeamGuarantee(
        seam_name="box_bootstrap",
        module_path="temper_ai.pi_agent.box_bootstrap",
        actual_guarantee="one_shot_stdin_delivery_binding_only",
    ),
}


def refuse_existing_seam_as_complete_coverage(
    seam_name: str,
    *,
    boundary: Boundary,
) -> Refusal:
    """Refuse treating any existing Temper box seam as complete loaded coverage."""
    _ = EXISTING_TEMPER_SEAM_GUARANTEES.get(seam_name)
    return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)


@dataclass(frozen=True, slots=True, kw_only=True)
class RootOwnerVsActorAssertion:
    """Explicit separation between a root's filesystem owner and the effective actor."""

    root_kind: Literal["publication", "host_evidence"]
    actor_process_ref: str
    actor_principal: str
    actor_uid: int
    file_owner_principal: str
    file_owner_uid: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SuppliedWorkerFrame:
    """Synthetic worker/host/root/stream payload returned by an injected test provider."""

    dispatcher_association: NativeWitness
    host_instance: ProcessInstance
    host_closure_instance: ClosureProcessInstance
    worker_instance: ProcessInstance
    worker_closure_instance: ClosureProcessInstance
    checker_instances: tuple[ProcessInstance, ...]
    child_instances: tuple[ProcessInstance, ...]
    runtime_facts: LoadedClosureEnvelope
    reviewed_graph: ReviewedSourceGraph | None
    launch_profile_ref: ImmutableReference
    load_stream_refs: tuple[NativeEventRange, ...]
    collector_provenance: tuple[NativeWitness, ...]
    both_roots: BothRootObservations | None = None
    root_owner_assertions: tuple[RootOwnerVsActorAssertion, ...] = ()
    effect_fence_verified: bool = True


class WorkerObservationProviderPort(ChildLaunchVerificationPort, Protocol):
    """Injected provider port for worker observation and root verification.

    Production installs ``None``; tests inject explicit synthetic doubles.
    """

    @abstractmethod
    def verify_grant(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Result[DecisionEvidence]: ...

    @abstractmethod
    def collect_worker_frame(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[SuppliedWorkerFrame]: ...

    @abstractmethod
    def collect_root_observation(
        self,
        grant: ObservationGrant,
        actor_instance: NativeProcessRef,
        selected_root: RootScope,
        required_operations: EffectSet,
        boundary: Boundary,
    ) -> Result[RootObservation]: ...


def validate_compatibility_profile(
    profile: CompatibilityProfile,
    boundary: Boundary,
) -> Refusal | None:
    """Enforce exact version domains on CompatibilityProfile without silent widening."""
    if (
        profile.decision != DECISION_SCHEMA
        or profile.reviewed_graph != "p3-reviewed-source-graph/1"
        or profile.loaded_envelope != "p3-reviewed-loaded-closure/1"
    ):
        return make_refusal(
            RefusalCode.CLOSURE_VERSION,
            boundary,
            retry_kind=RetryKind.NOT_APPLICABLE,
        )
    if (
        profile.corpus != WORKER_OBSERVATION_COMPAT_CORPUS_ID
        or profile.inspect not in ("/1", "/2")
        or not profile.comparator
        or not profile.observation
        or not profile.caller
        or not profile.receiving
    ):
        return make_refusal(
            RefusalCode.COMPATIBILITY_UNQUALIFIED,
            boundary,
            retry_kind=RetryKind.NOT_APPLICABLE,
        )
    return None


class WorkerRootObservationAdapter(RootObserver):
    """Typed RootObserver adapter enforcing permission-first and both-root separation."""

    def __init__(
        self,
        *,
        provider: WorkerObservationProviderPort | None = None,
    ) -> None:
        self._provider = provider
        self._unpermitted_read_attempted = False

    def record_unpermitted_read_attempt(self) -> None:
        self._unpermitted_read_attempted = True

    def observe(
        self,
        grant: ObservationGrant,
        actor_instance: NativeProcessRef,
        selected_root: RootScope,
        required_operations: EffectSet,
        boundary: Boundary,
    ) -> Result[RootObservation]:
        if self._unpermitted_read_attempted:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if self._provider is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)
        if not grant.permission.observation_permission:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if not required_operations.issubset(grant.authority.operations):
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if actor_instance not in grant.authority.actors:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        res = self._provider.collect_root_observation(
            grant,
            actor_instance,
            selected_root,
            required_operations,
            boundary,
        )
        if isinstance(res, Refusal):
            return res
        obs = res.data
        if obs.observation_boundary != boundary:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if obs.binding.actor_instance != actor_instance:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if not selected_root.required_rights.issubset(obs.binding.rights):
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if not selected_root.required_rights.issubset(obs.observed_access):
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if not obs.traversal_chain or not obs.provenance:
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        if (
            selected_root.expected_existing_object is not None
            and obs.binding.object_identity != selected_root.expected_existing_object
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return res

    def verify_both_roots(
        self,
        both: BothRootObservations | None,
        *,
        actor_instance: NativeProcessRef,
        root_owner_assertions: tuple[RootOwnerVsActorAssertion, ...],
        boundary: Boundary,
        evidence: DecisionEvidence,
    ) -> Result[BothRootObservations]:
        """Verify that both publication and host_evidence roots are present and distinct."""
        if both is None:
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        pub = both.publication
        host_ev = both.host_evidence
        if pub.root_kind != "publication" or host_ev.root_kind != "host_evidence":
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        if pub.binding.role != "publication" or host_ev.binding.role != "host-evidence":
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        if (
            pub.observation_boundary != boundary
            or host_ev.observation_boundary != boundary
        ):
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if (
            pub.binding.object_identity.filesystem_object
            == host_ev.binding.object_identity.filesystem_object
        ):
            # Host-only half or collapsed single root cannot satisfy BothRootObservations
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        if (
            pub.binding.actor_instance != actor_instance
            or host_ev.binding.actor_instance != actor_instance
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # Verify effective actor vs file owner separation: file ownership alone never substitutes for actor identity
        for assertion in root_owner_assertions:
            if assertion.actor_process_ref != actor_instance.process_registration:
                return make_refusal(
                    RefusalCode.SUBJECT_MISMATCH,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            if not assertion.actor_principal or not assertion.file_owner_principal:
                return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)

        return AcceptedData(data=both, evidence=evidence)


@dataclass
class _SessionState:
    selected_job: SelectedJob
    child_registry: ChildRegistrationRegistry
    bookkeeper: CoverageBookkeeper
    last_observation: WorkerObservation
    last_evidence: DecisionEvidence


class WorkerObservationAdapter(WorkerObserver):
    """Disabled-by-default P3 T4 WorkerObserver and child registration adapter.

    Requires an explicitly injected ``WorkerObservationProviderPort``. Default
    ``provider=None`` refuses every operation with ``RefusalCode.AUTHORITY_UNAVAILABLE``.
    """

    def __init__(
        self,
        *,
        provider: WorkerObservationProviderPort | None = None,
        require_both_roots: bool = True,
        require_effect_fence: bool = True,
    ) -> None:
        self._provider = provider
        self._require_both_roots = require_both_roots
        self._require_effect_fence = require_effect_fence
        self._root_observer = WorkerRootObservationAdapter(provider=provider)
        self._sessions: dict[str, _SessionState] = {}
        self._unpermitted_jobs: set[str] = set()

    @property
    def is_configured(self) -> bool:
        return self._provider is not None

    @property
    def root_observer(self) -> WorkerRootObservationAdapter:
        return self._root_observer

    def record_unpermitted_read_attempt(self, selection_revision: str) -> None:
        """Poison a job selection when a caller attempts collection before permission."""
        self._unpermitted_jobs.add(selection_revision)
        self._root_observer.record_unpermitted_read_attempt()
        session = self._sessions.get(selection_revision)
        if session is not None:
            session.child_registry.record_unpermitted_read_attempt()

    def observe(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[WorkerObservation]:
        rev_key = selected_job.selection_revision
        if rev_key in self._unpermitted_jobs:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if self._provider is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)

        # 1. Validate exact version profile before any collection
        compat_err = validate_compatibility_profile(
            selected_job.compatibility_profile,
            boundary,
        )
        if compat_err is not None:
            return compat_err
        if selected_job.route != "external-db-fresh":
            return make_refusal(
                RefusalCode.ROUTE_UNSUPPORTED,
                boundary,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )

        # 2. Verify ObservationGrant BEFORE collecting any process, root, or stream
        if not grant.permission.observation_permission:
            self._unpermitted_jobs.add(rev_key)
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if grant.authority.subject.selection_revision != selected_job.selection_revision:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if grant.authority.subject.job != selected_job.pre_dispatch_or_running_job:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        # In Phase B/C, planned FutureSubject cannot substitute for an ExistingSubject
        if boundary != "A_PRE_CREATE" and grant.authority.subject.subject.subject_kind == "future":
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        grant_ver = self._provider.verify_grant(grant, selected_job, boundary)
        if isinstance(grant_ver, Refusal):
            return grant_ver
        evidence = grant_ver.evidence

        # 3. Collect synthetic worker frame from verified provider
        frame_res = self._provider.collect_worker_frame(
            grant,
            selected_job,
            boundary,
            since_cursor=since_cursor,
        )
        if isinstance(frame_res, Refusal):
            return frame_res
        frame = frame_res.data

        # 4. Enforce effect fence availability before accepting observation
        if self._require_effect_fence and not frame.effect_fence_verified:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        # 5. Enforce separate host and worker runtime identities
        host_inst = frame.host_instance
        worker_inst = frame.worker_instance
        host_closure = frame.host_closure_instance
        worker_closure = frame.worker_closure_instance
        if (
            host_closure.location != "host"
            or worker_closure.location != "container"
            or worker_inst.container_instance is None
            or host_inst.native_identity.witness_reference
            == worker_inst.native_identity.witness_reference
            or (
                host_inst.pid_namespace_id == worker_inst.pid_namespace_id
                and host_inst.pid == worker_inst.pid
            )
        ):
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if (
            worker_inst.pid != worker_closure.pid
            or worker_inst.boot_id != worker_closure.host_boot
            or worker_inst.pid_namespace_id != worker_closure.pid_namespace
            or worker_inst.mount_namespace_id != worker_closure.mount_namespace
            or worker_inst.user_namespace_id != worker_closure.user_namespace
            or worker_inst.launch_id != worker_closure.launch_identity
        ):
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

        # 6. Verify BothRootObservations (publication + host_evidence) and actor vs owner
        if self._require_both_roots:
            if not grant.authority.actors:
                return make_refusal(
                    RefusalCode.SUBJECT_MISMATCH,
                    boundary,
                    retry_kind=RetryKind.NEW_BINDING_REQUIRED,
                )
            actor_ref = grant.authority.actors[0]
            roots_res = self._root_observer.verify_both_roots(
                frame.both_roots,
                actor_instance=actor_ref,
                root_owner_assertions=frame.root_owner_assertions,
                boundary=boundary,
                evidence=evidence,
            )
            if isinstance(roots_res, Refusal):
                return roots_res

        # 7. Initialize or retrieve per-job ChildRegistrationRegistry and CoverageBookkeeper
        session = self._sessions.get(rev_key)
        if session is None:
            child_reg = ChildRegistrationRegistry(
                selected_job=selected_job,
                worker_instance=worker_inst,
                worker_closure_instance=worker_closure,
            )
            bookkeeper = CoverageBookkeeper(
                required_categories=ALL_N3_COVERAGE_CATEGORIES,
            )
        else:
            child_reg = session.child_registry
            bookkeeper = session.bookkeeper

        registered_child_ids = frozenset(
            c.instance_id for c in child_reg.registered_closure_children
        ) | frozenset(
            c.native_identity.witness_reference for c in frame.child_instances
        )

        # 8. Verify LoadedClosureEnvelope and load_stream_refs continuity & coverage
        cov_res = bookkeeper.verify_envelope(
            frame.runtime_facts,
            boundary=boundary,
            load_stream_refs=frame.load_stream_refs,
            reviewed_graph=frame.reviewed_graph,
            since_cursor=since_cursor,
            registered_child_ids=registered_child_ids,
            evidence=evidence,
        )
        if isinstance(cov_res, Refusal):
            return cov_res

        if not frame.collector_provenance:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        combined_children = tuple(
            dict.fromkeys((*frame.child_instances, *child_reg.registered_children))
        )
        worker_obs = WorkerObservation(
            job=selected_job,
            selection_revision=selected_job.selection_revision,
            dispatcher_association=frame.dispatcher_association,
            worker_instance=worker_inst,
            checker_instances=frame.checker_instances,
            child_instances=combined_children,
            runtime_facts=frame.runtime_facts,
            launch_profile_ref=frame.launch_profile_ref,
            load_stream_refs=frame.load_stream_refs,
            collector_provenance=frame.collector_provenance,
        )
        self._sessions[rev_key] = _SessionState(
            selected_job=selected_job,
            child_registry=child_reg,
            bookkeeper=bookkeeper,
            last_observation=worker_obs,
            last_evidence=evidence,
        )
        return AcceptedData(data=worker_obs, evidence=evidence)

    def verify_pre_spawn(
        self,
        *,
        grant: ObservationGrant | None,
        selected_job: SelectedJob,
        ticket_effect_domain: str = "worker-child",
        ticket_effect_op: str = "spawn",
        ticket_effect_rev: str = "o1",
        boundary: Boundary = "C_PRE_EXECUTION",
        registration_source: str = "verified_parent_launcher_provider",
    ) -> Result[ObservationGrant]:
        """Verify provider, grant, and registration source before spawning a child."""
        rev_key = selected_job.selection_revision
        if rev_key in self._unpermitted_jobs:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if self._provider is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)
        session = self._sessions.get(rev_key)
        if session is None:
            return make_refusal(RefusalCode.PRIOR_MISSING, boundary)
        # Match an authorized operation from selected_job or construct one for refusal check
        matching_op = next(
            (
                op
                for op in selected_job.authorized_operations
                if op.domain == ticket_effect_domain and op.operation == ticket_effect_op
            ),
            next(iter(selected_job.authorized_operations)),
        )
        return session.child_registry.verify_pre_spawn(
            grant=grant,
            selected_job=selected_job,
            intended_effect=matching_op,
            boundary=boundary,
            verification_port=self._provider,
            registration_source=registration_source,
        )

    def register_child_ticket(
        self,
        ticket: ChildRegistrationTicket,
    ) -> Result[tuple[RegisteredChildEntry, WorkerObservation]]:
        """Register a child birth or exec transition and return updated WorkerObservation."""
        rev_key = ticket.selected_job.selection_revision
        if rev_key in self._unpermitted_jobs:
            return make_refusal(
                RefusalCode.OBSERVATION_NOT_AUTHORIZED,
                ticket.boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if self._provider is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, ticket.boundary)
        session = self._sessions.get(rev_key)
        if session is None:
            return make_refusal(RefusalCode.PRIOR_MISSING, ticket.boundary)

        reg_res = session.child_registry.register_child(
            ticket,
            verification_port=self._provider,
        )
        if isinstance(reg_res, Refusal):
            return reg_res
        entry = reg_res.data
        updated_obs = replace(
            session.last_observation,
            child_instances=session.child_registry.registered_children,
        )
        session.last_observation = updated_obs
        return AcceptedData(
            data=(entry, updated_obs),
            evidence=reg_res.evidence,
        )

    def terminate_child(
        self,
        selected_job: SelectedJob,
        key: ProcessKey,
        *,
        exit_code: int,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Result[RegisteredChildEntry]:
        """Mark a registered child generation as terminated."""
        session = self._sessions.get(selected_job.selection_revision)
        if session is None:
            return make_refusal(RefusalCode.PRIOR_MISSING, boundary)
        return session.child_registry.terminate_child(
            key,
            exit_code=exit_code,
            boundary=boundary,
            evidence=session.last_evidence,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerCompatCaseEntry:
    """Uniquely owned worker observation case in ops-host-compat-corpus/1."""

    case_id: str
    corpus: Literal["ops-host-compat-corpus/1"]
    category: str
    expected_outcome: Literal["AcceptedData", "Refusal"]
    expected_refusal_code: RefusalCode | None


def build_worker_observation_compat_cases() -> tuple[WorkerCompatCaseEntry, ...]:
    """Return uniquely owned worker-obs-* case descriptors for ops-host-compat-corpus/1."""
    return (
        WorkerCompatCaseEntry(
            case_id="worker-obs-01-combined-happy-path",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="happy_path",
            expected_outcome="AcceptedData",
            expected_refusal_code=None,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-02-missing-provider-unavailable",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="provider",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.AUTHORITY_UNAVAILABLE,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-03-permission-after-read-unauthorized",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="permission_order",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.OBSERVATION_NOT_AUTHORIZED,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-04-foreign-child-subject-mismatch",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="child_lineage",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.SUBJECT_MISMATCH,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-05-pid-or-exec-reuse-runtime-changed",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="pid_exec_monotonicity",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.RUNTIME_CHANGED,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-06-late-attach-observation-gap",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="bootstrap_coverage",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.OBSERVATION_GAP,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-07-missing-category-closure-incomplete",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="category_gaps",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.CLOSURE_INCOMPLETE,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-08-stream-gap-reorder-contradictory-duplicate",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="stream_continuity",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.OBSERVATION_GAP,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-09-host-only-half-root-mismatch",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="both_roots",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.ROOT_MISMATCH,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-10-stale-frontier-after-wait",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="causal_frontier",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.OBSERVATION_GAP,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-11-effect-fence-unavailable",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="effect_fence",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.OBSERVATION_GAP,
        ),
        WorkerCompatCaseEntry(
            case_id="worker-obs-12-surrogate-child-registration-peer-unverified",
            corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
            category="child_registration_origin",
            expected_outcome="Refusal",
            expected_refusal_code=RefusalCode.PEER_UNVERIFIED,
        ),
    )
