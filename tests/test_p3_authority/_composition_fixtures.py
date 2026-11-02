"""Explicit test-only fixtures for P3 T4 authority composition tests (#262).

Test doubles and synthetic world builders live only in test modules and explicit
test-only helpers. Production defaults in ``compose_p3_authority()`` remain
unconfigured (all providers ``None``, ``writes_enabled=False``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel

import temper_ai.config.models  # noqa: F401
import temper_ai.observability.models  # noqa: F401
import temper_ai.runner.models  # noqa: F401
from p3_source_closure import (
    N3ObservationEpoch,
)
from temper_ai.config.admission_capture import ConfigStore
from temper_ai.config.admission_contract import (
    ContractCodec,
    DescriptorAuthority,
    DispatchIdentity,
    FrozenJSON,
)
from temper_ai.p3_authority._providers import (
    InMemoryEffectFenceProvider,
    InMemoryHostObserver,
    InMemoryHostProvenance,
    InMemoryHostSessionPeerResolver,
    InMemoryQAReceivingVerifier,
    InMemoryRootObserver,
    InMemoryWorkerObserver,
    SystemsSourceClosureComparator,
)
from temper_ai.p3_authority.boundary_types import (
    BothRootObservations,
    CurrentObservationCursors,
    OperationLeg,
    VerifiedReceiptBinding,
)
from temper_ai.p3_authority.candidate_bindings import (
    CandidateCaptureAdapter,
    StaticCallerPeerProvider,
)
from temper_ai.p3_authority.contract import (
    AuthorityRef,
    Boundary,
    CalibrationSelection,
    CompatibilityProfile,
    ConditionRef,
    JobKey,
    NativeGrantRef,
    NativeProcessRef,
    NativeWitness,
    PermissionHandle,
    Phase,
    PreDispatchJob,
    ProjectSelection,
    RawRef,
    RootObservation,
    SelectedJob,
    SelectedOperation,
    SelectedSubject,
    TrustedInstant,
    VerifiedAuthority,
    WorkerObservation,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    ExistingSubjectRecord,
    FutureSubjectRecord,
    ImmutableReferenceRecord,
    InMemoryIssuerVerifier,
    InMemoryPeerVerifier,
    InMemoryRequestHistoryProvider,
    InMemorySelectionPublisher,
    InMemorySelectionSnapshotProvider,
    SelectionSnapshot,
    default_effect_for_job,
)
from temper_ai.p3_authority.service import (
    P3AuthorityComposition,
    compose_p3_authority,
)
from tests.test_architecture.ops_host_n3_cases import clean_world
from tests.test_p3_host_contracts.examples import examples as host_examples

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_SCHEMA = (
    _REPO_ROOT / "docs/schemas/candidate-admission-v1.schema.json"
).read_bytes()


# ---------------------------------------------------------------------------
# Concrete test-only carriers satisfying #261's abstract reference protocols
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FakeProcessRef:
    process_reference: str

    @property
    def process_registration(self) -> str:
        return self.process_reference


@dataclass(frozen=True, slots=True)
class FakeWitness:
    witness_registration: str

    @property
    def witness_reference(self) -> str:
        return self.witness_registration


@dataclass(frozen=True, slots=True)
class FakePeer:
    peer_reference: str
    process: NativeProcessRef = field(
        default_factory=lambda: FakeProcessRef("proc-default")
    )

    @property
    def peer_registration(self) -> str:
        return self.peer_reference


@dataclass(frozen=True, slots=True)
class FakeSession:
    session_reference: str
    peer: FakePeer


@dataclass(frozen=True, slots=True)
class FakeNativeSelection:
    selection_reference: str
    selection_revision: str


@dataclass(frozen=True, slots=True)
class FakePermissionHandle:
    observation_permission: str


@dataclass(frozen=True, slots=True)
class FakeGrantRef:
    grant_reference: str


@dataclass(frozen=True, slots=True)
class FakeAdmission:
    admission_registration: str

    @property
    def admission_reference(self) -> str:
        return self.admission_registration


@dataclass(frozen=True, slots=True)
class FakeObservationSession:
    observation_session: str
    permission: PermissionHandle


@dataclass(frozen=True, slots=True)
class FakeBirthIdentity:
    birth_witness: NativeWitness


@dataclass(frozen=True, slots=True)
class FakeContainerIdentity:
    daemon_instance: str
    full_container_id: str
    start_witness: NativeWitness


@dataclass(frozen=True, slots=True)
class FakeNativeRootObject:
    filesystem_object: str
    mount_identity: str = "mount:root-1"
    namespace_identity: str = "mnt:[4026531840]"
    observation_epoch: str = "obs-epoch-1"


@dataclass(frozen=True, slots=True)
class FakeInterval:
    interval_witness: NativeWitness
    clock_domain: str = "monotonic:host-test-1"


@dataclass(frozen=True, slots=True)
class FakeEventRange:
    continuity_witness: NativeWitness
    first_sequence: int = 1
    last_sequence: int = 4
    lost_events: int | None = 0


@dataclass(frozen=True, slots=True)
class FakeObservationFields:
    allowed_fields: frozenset[str] = frozenset({"pid", "argv", "roots"})


@dataclass(frozen=True, slots=True)
class FakeDisarmRelation:
    relation: Literal["before", "during", "after", "absent", "unknown"] = "after"
    witness: NativeWitness | None = None


@dataclass(frozen=True, slots=True)
class FakeObservationGrant:
    grant: NativeGrantRef
    handle: PermissionHandle


@dataclass(frozen=True, slots=True)
class FakeQAReceiving:
    receiving_reference: ImmutableReferenceRecord
    receiver: NativeProcessRef


@dataclass(frozen=True, slots=True)
class FakeCompatibilityReceiving:
    compatibility_reference: ImmutableReferenceRecord
    profile: CompatibilityProfile


# ---------------------------------------------------------------------------
# Canonical test constants
# ---------------------------------------------------------------------------

WITNESS_1 = FakeWitness("wit:test-1")
WITNESS_2 = FakeWitness("wit:test-2")

TRUSTED_NOW = TrustedInstant(
    clock_domain="monotonic:host-test-1",
    reading="5000",
    witness=WITNESS_1,
)
TRUSTED_BEFORE = TrustedInstant(
    clock_domain="monotonic:host-test-1",
    reading="1000",
    witness=WITNESS_1,
)
TRUSTED_EXPIRES = TrustedInstant(
    clock_domain="monotonic:host-test-1",
    reading="10000",
    witness=WITNESS_1,
)

PROCESS_SUBMIT = FakeProcessRef("proc:submit-1")
PROCESS_RUN = FakeProcessRef("proc:run-1")
PROCESS_CHECKER = FakeProcessRef("proc:checker-1")
PROCESS_WORKER = FakeProcessRef("proc:worker-1")
PROCESS_HOST = FakeProcessRef("proc:host-1")
PROCESS_QA = FakeProcessRef("proc:qa-1")
PROCESS_PRODUCER = FakeProcessRef("proc:producer-1")
PROCESS_PUBLISHER = FakeProcessRef("proc:publisher-1")

NATIVE_SELECTION_1 = FakeNativeSelection(
    selection_reference="sel-ref:sel-rev-1",
    selection_revision="sel-rev-1",
)
NATIVE_SELECTION_RUN = FakeNativeSelection(
    selection_reference="sel-ref:sel-rev-run-1",
    selection_revision="sel-rev-run-1",
)

DISPATCH_1 = DispatchIdentity(
    execution_uuid="11111111-1111-4111-8111-111111111111",
    dispatch_nonce="22222222-2222-4222-8222-222222222222",
    running_attempt=1,
)
DISPATCH_2 = DispatchIdentity(
    execution_uuid="11111111-1111-4111-8111-111111111111",
    dispatch_nonce="33333333-3333-4333-8333-333333333333",
    running_attempt=2,
)

REF_SOURCE = ImmutableReferenceRecord(
    path="source/sel-rev-1",
    digest="4" * 64,
    length=64,
    revision="sel-rev-1",
)
REF_CLOSURE = ImmutableReferenceRecord(
    path="closure/reviewed-1.json",
    digest="5" * 64,
    length=128,
    revision="closure-rev-1",
)
REF_KIT = ImmutableReferenceRecord(
    path="kit/project-1.json",
    digest="6" * 64,
    length=256,
    revision="kit-rev-1",
)
REF_BINDING = ImmutableReferenceRecord(
    path="binding/expected-1.json",
    digest="7" * 64,
    length=256,
    revision="binding-rev-1",
)
REF_MANIFEST = ImmutableReferenceRecord(
    path="calibration/manifest-1.json",
    digest="8" * 64,
    length=512,
    revision="manifest-rev-1",
)
REF_QA = ImmutableReferenceRecord(
    path="qa/receiving-1.json",
    digest="9" * 64,
    length=128,
    revision="qa-rev-1",
)
REF_COMPAT = ImmutableReferenceRecord(
    path="compat/receiving-1.json",
    digest="a" * 64,
    length=128,
    revision="compat-rev-1",
)

RAW_REF_BUILD = RawRef(
    root_locator="repo:temper-ai",
    relative_path="build/manifest.json",
    byte_length=128,
    sha256="b" * 64,
)
RAW_REF_KIT = RawRef(
    root_locator="repo:temper-ai",
    relative_path="kit/project-1.json",
    byte_length=256,
    sha256="6" * 64,
)
RAW_REF_BINDING = RawRef(
    root_locator="repo:temper-ai",
    relative_path="binding/expected-1.json",
    byte_length=256,
    sha256="7" * 64,
)
RAW_REF_REQUEST = RawRef(
    root_locator="window:win-1",
    relative_path="requests/req-1.json",
    byte_length=64,
    sha256="c" * 64,
)
RAW_REF_RECEIPT = RawRef(
    root_locator="window:win-1",
    relative_path="receipts/rec-1.json",
    byte_length=64,
    sha256="d" * 64,
)
RAW_REF_EVIDENCE = RawRef(
    root_locator="window:win-1",
    relative_path="evidence/ev-1.json",
    byte_length=64,
    sha256="e" * 64,
)
RAW_REF_WINDOW = RawRef(
    root_locator="window:win-1",
    relative_path="window.json",
    byte_length=64,
    sha256="1" * 64,
)
RAW_REF_LOG = RawRef(
    root_locator="window:win-1",
    relative_path="numbered.log",
    byte_length=64,
    sha256="2" * 64,
)
RAW_REF_ROW = RawRef(
    root_locator="window:win-1",
    relative_path="rows/row-1.json",
    byte_length=64,
    sha256="3" * 64,
)

PROJECT_SELECTION_1 = ProjectSelection(
    project_id="proj-1",
    run_id="run-1",
    kit_id="kit-1",
    kit_sha256="6" * 64,
    build_sums_sha256="b" * 64,
    publication_ref=REF_BINDING,
    publication_revision="pub-rev-1",
    build_ref=REF_KIT,
)
CALIBRATION_SELECTION_1 = CalibrationSelection(
    manifest_ref=REF_MANIFEST,
    entry_id="entry-1",
    calibration_run="cal-run-1",
    round="round-1",
    copy_identity="copy-1",
    expected_draft_kit=REF_KIT,
    build_sums_sha256="b" * 64,
    publication_ref=REF_BINDING,
    publication_revision="pub-rev-1",
    build_ref=REF_KIT,
    selected_runtime_profile="profile-1",
)
COMPAT_PROFILE_1 = CompatibilityProfile(
    decision="p3-native-decision/1",
    reviewed_graph="p3-reviewed-source-graph/1",
    loaded_envelope="p3-reviewed-loaded-closure/1",
    comparator="systems-n3-comparator/1",
    observation="ops-host-observation/1",
    inspect="/1",
    caller="temper.candidate-admission.v1",
    corpus="ops-host-compat-corpus/1",
    receiving="qa-receiving/1",
)

SELECTOR_ISSUER_REF = AuthorityRef(
    issuer_id="issuer:selector-test",
    record_id="auth:selector-1",
    authority_revision="rev-1",
)
AUTHORITY_REF_1 = AuthorityRef(
    issuer_id="issuer:authority-test",
    record_id="auth:grant-1",
    authority_revision="rev-1",
)
AUTHORITY_REF_2 = AuthorityRef(
    issuer_id="issuer:authority-test",
    record_id="auth:grant-2",
    authority_revision="rev-1",
)
CONDITION_1 = ConditionRef(
    authority=AUTHORITY_REF_1,
    condition_id="mode:external-db-fresh",
    revision="cond-rev-1",
)

ALL_OPERATIONS: frozenset[SelectedOperation] = frozenset(
    {
        SelectedOperation(
            domain="A_PRE_CREATE", operation="A_PRE_CREATE", revision="op-1"
        ),
        SelectedOperation(domain="A_PRE_ARM", operation="A_PRE_ARM", revision="op-1"),
        SelectedOperation(
            domain="B_PRE_REQUEST", operation="B_PRE_REQUEST", revision="op-1"
        ),
        SelectedOperation(
            domain="C_PRE_REQUEST", operation="C_PRE_REQUEST", revision="op-1"
        ),
        SelectedOperation(
            domain="C_PRE_EXECUTION", operation="C_PRE_EXECUTION", revision="op-1"
        ),
        SelectedOperation(
            domain="C_BEFORE_COUNT", operation="C_BEFORE_COUNT", revision="op-1"
        ),
        SelectedOperation(domain="p3.row", operation="mutate", revision="op-1"),
        SelectedOperation(domain="p3.host", operation="launch", revision="op-1"),
    }
)


def make_pre_dispatch_job(
    *,
    designated_workflow: str = "designated_v1",
    execution_uuid: str = DISPATCH_1.execution_uuid,
    job_revision: str = "job-rev-1",
    selection_revision: str = "sel-rev-1",
    selection: ProjectSelection | CalibrationSelection = PROJECT_SELECTION_1,
    approved_descriptor_digest: str = "3" * 64,
    expected_source_digest: str = "4" * 64,
    authorized_operations: frozenset[SelectedOperation] = ALL_OPERATIONS,
    conditions: tuple[ConditionRef, ...] | frozenset[ConditionRef] = (CONDITION_1,),
    authority_refs: tuple[AuthorityRef, ...] = (AUTHORITY_REF_1,),
) -> SelectedJob:
    return SelectedJob(
        pre_dispatch_or_running_job=PreDispatchJob(
            execution_uuid=execution_uuid,
            designated_workflow=designated_workflow,
            descriptor_digest=approved_descriptor_digest,
            job_revision=job_revision,
        ),
        selector_issuer=SELECTOR_ISSUER_REF,
        selection_revision=selection_revision,
        selection=selection,
        approved_descriptor_digest=approved_descriptor_digest,
        expected_source_digest=expected_source_digest,
        reviewed_closure_ref=REF_CLOSURE,
        compatibility_profile=COMPAT_PROFILE_1,
        authorized_operations=frozenset(authorized_operations),
        conditions=tuple(conditions),
        authority_refs=authority_refs,
    )


def make_running_job(
    *,
    dispatch: DispatchIdentity = DISPATCH_1,
    job_revision: str = "job-rev-run-1",
    selection_revision: str = "sel-rev-run-1",
    selection: ProjectSelection | CalibrationSelection = PROJECT_SELECTION_1,
    approved_descriptor_digest: str = "3" * 64,
    expected_source_digest: str = "4" * 64,
    authorized_operations: frozenset[SelectedOperation] = ALL_OPERATIONS,
    conditions: tuple[ConditionRef, ...] | frozenset[ConditionRef] = (CONDITION_1,),
    authority_refs: tuple[AuthorityRef, ...] = (AUTHORITY_REF_1,),
) -> SelectedJob:
    return SelectedJob(
        pre_dispatch_or_running_job=JobKey(
            dispatch=dispatch,
            job_revision=job_revision,
        ),
        selector_issuer=SELECTOR_ISSUER_REF,
        selection_revision=selection_revision,
        selection=selection,
        approved_descriptor_digest=approved_descriptor_digest,
        expected_source_digest=expected_source_digest,
        reviewed_closure_ref=REF_CLOSURE,
        compatibility_profile=COMPAT_PROFILE_1,
        authorized_operations=frozenset(authorized_operations),
        conditions=tuple(conditions),
        authority_refs=authority_refs,
    )


def make_verified_authority(
    *,
    authority: AuthorityRef = AUTHORITY_REF_1,
    subject: SelectedSubject,
    actors: tuple[NativeProcessRef, ...] | frozenset[NativeProcessRef] = (
        PROCESS_SUBMIT,
        PROCESS_RUN,
        PROCESS_CHECKER,
        PROCESS_WORKER,
        PROCESS_HOST,
        PROCESS_QA,
    ),
    operations: frozenset[SelectedOperation] = ALL_OPERATIONS,
    conditions: tuple[ConditionRef, ...] | frozenset[ConditionRef] = (CONDITION_1,),
    not_before: TrustedInstant = TRUSTED_BEFORE,
    expires_at: TrustedInstant = TRUSTED_EXPIRES,
    witness: NativeWitness = WITNESS_1,
) -> VerifiedAuthority:
    return VerifiedAuthority(
        issuer_identity=authority.issuer_id,
        verified_record_digest="d" * 64,
        subject=subject,
        actors=tuple(actors),
        operations=frozenset(operations),
        roots=(
            FutureSubjectRecord(selected_scope_reference=subject.selection_revision),
        ),
        conditions=tuple(conditions),
        not_before=not_before,
        expires_at=expires_at,
        revocation_source=authority,
        revocation_revision="rev-1",
        checked_at=TRUSTED_NOW,
        verification_profile="p3-test-profile",
        validity=FakeInterval(interval_witness=witness),
    )


@dataclass
class V1CandidateHarness:
    engine: Any
    session_factory: sessionmaker[Session]
    codec: ContractCodec
    config_store: ConfigStore
    source_json: FrozenJSON
    expected_source_sha256: str
    expected_descriptor_sha256: str
    authority: DescriptorAuthority
    installation_verifier: Any
    preparation_verifier: Any
    capture_adapter: CandidateCaptureAdapter


class _DummyInstallAndPrepVerifier:
    def verify_install(self, admission: Any, *, transaction: Any) -> bool:
        return True

    def captured_nodes(self, admission: Any, *, transaction: Any) -> tuple[Any, ...]:
        return ()

    def verify_preparation(
        self,
        current: Any,
        receipt: Any,
        provenance: Any,
        *,
        transaction: Any,
    ) -> bool:
        return True


def make_v1_candidate_harness(
    *,
    session_factory: sessionmaker[Session] | None = None,
    workflow_name: str = "designated_v1",
    authorized_caller_label: str = "p3-authorized-caller",
    receipt_id: str = "p3:designated_v1:job-rev-1:sel-rev-1",
) -> V1CandidateHarness:
    if session_factory is None:
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    else:
        engine = session_factory.kw.get("bind")

    codec = ContractCodec(_CANDIDATE_SCHEMA)
    # Canonical JSON requires sorted keys ("revision" before "schema")
    source_bytes = b'{"revision":"source-rev-1","schema":"temper.source.v1"}'
    source_json = FrozenJSON(source_bytes)
    expected_source_sha = "4" * 64
    expected_descriptor_sha = "3" * 64

    authority = DescriptorAuthority(
        expected_descriptor_sha256=expected_descriptor_sha,
        expected_source_sha256=expected_source_sha,
        authorized_caller_label=authorized_caller_label,
        receipt_id=receipt_id,
    )
    store = ConfigStore()
    verifier = _DummyInstallAndPrepVerifier()
    adapter = CandidateCaptureAdapter(
        codec=codec,
        config_store=store,
        current_source=lambda: source_json,
        worker_identity=lambda: "worker-1",
        expected_descriptor_sha256=expected_descriptor_sha,
        expected_source_sha256=expected_source_sha,
        authorized_caller_label=authorized_caller_label,
        designated_workflows=frozenset({workflow_name}),
        dispatch_identity=DISPATCH_1,
    )
    return V1CandidateHarness(
        engine=engine,
        session_factory=session_factory,
        codec=codec,
        config_store=store,
        source_json=source_json,
        expected_source_sha256=expected_source_sha,
        expected_descriptor_sha256=expected_descriptor_sha,
        authority=authority,
        installation_verifier=verifier,
        preparation_verifier=verifier,
        capture_adapter=adapter,
    )


@dataclass
class PopulatedAuthorityTestRig:
    peer_submit: FakePeer
    peer_run: FakePeer
    peer_checker: FakePeer
    peer_worker: FakePeer
    peer_host: FakePeer
    peer_qa: FakePeer
    session_host: FakeSession
    witness: FakeWitness
    peer_verifier: InMemoryPeerVerifier
    issuer_verifier: InMemoryIssuerVerifier
    publisher: InMemorySelectionPublisher
    selection_provider: InMemorySelectionSnapshotProvider
    request_history_provider: InMemoryRequestHistoryProvider
    host_observer: InMemoryHostObserver
    worker_observer: InMemoryWorkerObserver
    root_observer: InMemoryRootObserver
    qa_verifier: InMemoryQAReceivingVerifier
    effect_fence_provider: InMemoryEffectFenceProvider
    host_provenance: InMemoryHostProvenance
    host_session_peer_resolver: InMemoryHostSessionPeerResolver
    comparator: SystemsSourceClosureComparator
    v1_harness: V1CandidateHarness
    pre_dispatch_job: SelectedJob
    running_job: SelectedJob
    calibration_job: SelectedJob
    snapshot: SelectionSnapshot
    examples: dict[str, Any]
    world: dict[str, Any]
    composition: P3AuthorityComposition


def make_populated_test_rig(
    *,
    session_factory: sessionmaker[Session] | None = None,
    writes_enabled: bool = False,
) -> PopulatedAuthorityTestRig:
    v1_harness = make_v1_candidate_harness(session_factory=session_factory)
    ex = host_examples()
    w = clean_world()

    peer_submit = FakePeer("peer:submit-1", PROCESS_SUBMIT)
    peer_run = FakePeer("peer:run-1", PROCESS_RUN)
    peer_checker = FakePeer("peer:checker-1", PROCESS_CHECKER)
    peer_worker = FakePeer("peer:worker-1", PROCESS_WORKER)
    peer_host = FakePeer("peer:host-1", PROCESS_HOST)
    peer_qa = FakePeer("peer:qa-1", PROCESS_QA)
    session_host = FakeSession("session:host-1", peer_host)
    witness = WITNESS_1

    peer_verifier = InMemoryPeerVerifier(
        allowed_peers=(
            peer_submit,
            peer_run,
            peer_checker,
            peer_worker,
            peer_host,
            peer_qa,
        )
    )

    pre_job = make_pre_dispatch_job(
        approved_descriptor_digest=v1_harness.expected_descriptor_sha256,
        expected_source_digest=v1_harness.expected_source_sha256,
    )
    run_job = make_running_job(
        dispatch=DISPATCH_1,
        approved_descriptor_digest=v1_harness.expected_descriptor_sha256,
        expected_source_digest=v1_harness.expected_source_sha256,
    )
    cal_job = make_running_job(
        dispatch=DispatchIdentity(
            execution_uuid="99999999-9999-4999-8999-999999999999",
            dispatch_nonce="33333333-3333-4333-8333-333333333333",
            running_attempt=1,
        ),
        selection_revision="sel-rev-cal-1",
        selection=CALIBRATION_SELECTION_1,
        approved_descriptor_digest=v1_harness.expected_descriptor_sha256,
        expected_source_digest=v1_harness.expected_source_sha256,
    )

    snapshot = SelectionSnapshot(
        snapshot_revision="snap-rev-1",
        jobs=(pre_job, run_job, cal_job),
        verified_at=TRUSTED_NOW,
    )

    issuer_verifier = InMemoryIssuerVerifier()
    for job in (pre_job, run_job, cal_job):
        subj = snapshot.subject_for(job)
        for ref in (job.selector_issuer, *job.authority_refs):
            issuer_verifier.register_authority(
                ref,
                make_verified_authority(authority=ref, subject=subj, witness=witness),
                job=job,
            )

    publisher = InMemorySelectionPublisher()
    publisher.publish_snapshot(snapshot)
    selection_provider = publisher.reader()
    request_history_provider = InMemoryRequestHistoryProvider()

    host_observer = InMemoryHostObserver()
    worker_observer = InMemoryWorkerObserver()
    root_observer = InMemoryRootObserver()
    qa_verifier = InMemoryQAReceivingVerifier()
    effect_fence_provider = InMemoryEffectFenceProvider()
    host_provenance = InMemoryHostProvenance()
    host_session_peer_resolver = InMemoryHostSessionPeerResolver()
    host_session_peer_resolver.register_session(session_host, peer_host)

    jobs_by_rev = {
        pre_job.selection_revision: pre_job,
        run_job.selection_revision: run_job,
        cal_job.selection_revision: cal_job,
    }
    expectations_by_key: dict[tuple[str, Boundary], tuple[object, object]] = {}

    comparator = SystemsSourceClosureComparator(
        job_lookup=lambda rev: jobs_by_rev.get(rev),
        peer_lookup=lambda _rev: PROCESS_HOST,
        expectation_lookup=lambda rev, bnd: expectations_by_key.get((rev, bnd)),
    )
    comparator._expectations_by_key = expectations_by_key  # type: ignore[attr-defined]

    for job in (pre_job, run_job, cal_job):
        ev = DecisionEvidenceRecord(
            selected_job=job,
            authority_revisions=job.authority_refs,
            window=None,
            processes=(PROCESS_HOST,),
            effect=default_effect_for_job(job, "A_PRE_CREATE"),
            phase=Phase.A,
            boundary="A_PRE_CREATE",
            source=REF_SOURCE,
            closure=REF_CLOSURE,
            compatibility=COMPAT_PROFILE_1,
        )
        host_observer.register_evidence(job.selection_revision, ev)
        host_provenance.register_evidence(job.selection_revision, ev)

    caller_peer_provider = StaticCallerPeerProvider(
        submit_peers={("p3-authorized-caller", "designated_v1"): peer_submit},
        run_peers={DISPATCH_1.execution_uuid: peer_run},
    )

    composition = compose_p3_authority(
        snapshot_provider=selection_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=peer_verifier,
        history_provider=request_history_provider,
        caller_peer_provider=caller_peer_provider,
        session_factory=v1_harness.session_factory,
        capture_adapter=v1_harness.capture_adapter,
        installation_verifier=v1_harness.installation_verifier,
        preparation_verifier=v1_harness.preparation_verifier,
        designated_workflows=frozenset({"designated_v1"}),
        default_dispatch_identity=DISPATCH_1,
        host_observer=host_observer,
        worker_observer=worker_observer,
        root_observer=root_observer,
        closure_comparator=comparator,
        qa_receiving_verifier=qa_verifier,
        effect_fence_provider=effect_fence_provider,
        host_provenance=host_provenance,
        host_session_peer_resolver=host_session_peer_resolver,
        writes_enabled=writes_enabled,
    )

    return PopulatedAuthorityTestRig(
        peer_submit=peer_submit,
        peer_run=peer_run,
        peer_checker=peer_checker,
        peer_worker=peer_worker,
        peer_host=peer_host,
        peer_qa=peer_qa,
        session_host=session_host,
        witness=witness,
        peer_verifier=peer_verifier,
        issuer_verifier=issuer_verifier,
        publisher=publisher,
        selection_provider=selection_provider,
        request_history_provider=request_history_provider,
        host_observer=host_observer,
        worker_observer=worker_observer,
        root_observer=root_observer,
        qa_verifier=qa_verifier,
        effect_fence_provider=effect_fence_provider,
        host_provenance=host_provenance,
        host_session_peer_resolver=host_session_peer_resolver,
        comparator=comparator,
        v1_harness=v1_harness,
        pre_dispatch_job=pre_job,
        running_job=run_job,
        calibration_job=cal_job,
        snapshot=snapshot,
        examples=ex,
        world=w,
        composition=composition,
    )


@dataclass(frozen=True, slots=True)
class FakeReceiptProducerBinding:
    producer: NativeProcessRef
    mechanism: NativeWitness


@dataclass(frozen=True, slots=True)
class FakeP5Assessment:
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    trust: Literal["UNTRUSTED"]
    assessment_reference: Any


def make_world_for_boundary(phase: Boundary, operation: str = "B-2") -> Any:
    """Build a canonical p3_source_closure Inputs world for the given boundary phase."""
    from dataclasses import replace as dc_replace

    import p3_source_closure as t
    from tests.test_architecture.ops_host_n3_cases import (
        Inputs,
        clean_world,
        identity,
        witnesses,
    )

    if phase == "A_PRE_CREATE":
        return clean_world("N3-11")
    w = clean_world("N3-01")
    early = phase in ("A_PRE_CREATE", "A_PRE_ARM")
    b = dc_replace(
        w.expected.boundary,
        phase=phase,
        operation=operation,
        request_id=None if early else w.expected.boundary.request_id,
        receipt=(
            None
            if early or phase in ("B_PRE_REQUEST", "C_PRE_REQUEST")
            else w.expected.boundary.receipt
        ),
    )
    procs = tuple(
        dc_replace(p, checkpoint=dc_replace(p.checkpoint, boundary=b))
        for p in w.observed.envelope.process_observations
    )
    env = dc_replace(w.observed.envelope, boundary=b, process_observations=procs)
    exp = dc_replace(w.expected, boundary=b)
    ver = t.VerifiedClosureOrigins(
        identity(w.reviewed.graph),
        identity(env),
        identity(exp),
        b.validity_checkpoint,
        witnesses(w.reviewed.graph, procs),
    )
    return Inputs(
        w.reviewed,
        t.LoadedClosureEnvelope(env, identity(env)),
        exp,
        ver,
    )


def populate_boundary_happy_path_observations(
    rig: PopulatedAuthorityTestRig,
) -> dict[str, Any]:
    """Populate synthetic A/B/C observations in rig's in-memory observers for the happy path."""
    import hashlib
    from dataclasses import replace as dc_replace

    from p3_source_closure import compare_loaded_source
    from temper_ai.p3_authority.contract import AcceptedData, ActualCreation
    from tests.test_architecture.ops_host_n3_cases import COVERAGE

    ex = rig.examples
    w_create = make_world_for_boundary("A_PRE_CREATE", "create")
    w_arm = make_world_for_boundary("A_PRE_ARM", "B-2")

    boot_cmp = compare_loaded_source(
        w_create.reviewed,
        w_create.observed,
        expected=w_create.expected,
        verified=w_create.verified,
    )
    cmp_arm = compare_loaded_source(
        w_arm.reviewed,
        w_arm.observed,
        expected=w_arm.expected,
        verified=w_arm.verified,
    )

    exp_map = getattr(rig.comparator, "_expectations_by_key", None)
    if isinstance(exp_map, dict):
        exp_map[(rig.pre_dispatch_job.selection_revision, "A_PRE_CREATE")] = (
            w_create.expected,
            w_create.verified,
        )
        exp_map[(rig.running_job.selection_revision, "A_PRE_ARM")] = (
            w_arm.expected,
            w_arm.verified,
        )

    sel_pre = FakeNativeSelection(
        selection_reference=f"sel:{rig.pre_dispatch_job.selection_revision}",
        selection_revision=rig.pre_dispatch_job.selection_revision,
    )
    sel_run = FakeNativeSelection(
        selection_reference=f"sel:{rig.running_job.selection_revision}",
        selection_revision=rig.running_job.selection_revision,
    )

    creator_inst = dc_replace(ex["ProcessInstance"], native_identity=PROCESS_WORKER)
    checker_inst = dc_replace(ex["ProcessInstance"], native_identity=PROCESS_CHECKER)

    creator_obs = dc_replace(
        ex["HostObservation"],
        selection=sel_pre,
        process_instances=(creator_inst,),
        coverage=COVERAGE,
        gaps=(),
    )
    parent_root = dc_replace(
        ex["RootBinding"],
        actor_instance=creator_inst,
    )

    host_obs_arm = dc_replace(
        ex["HostObservation"],
        selection=sel_run,
        process_instances=(creator_inst,),
        coverage=COVERAGE,
        gaps=(),
    )
    worker_obs_arm = WorkerObservation(
        job=rig.running_job,
        selection_revision=rig.running_job.selection_revision,
        dispatcher_association=WITNESS_1,
        worker_instance=creator_inst,
        checker_instances=(checker_inst,),
        child_instances=(),
        runtime_facts=w_arm.observed,
        launch_profile_ref=REF_CLOSURE,
        load_stream_refs=(FakeEventRange(continuity_witness=WITNESS_1),),
        collector_provenance=(WITNESS_1,),
    )
    pub_root_obs = RootObservation(
        root_kind="publication",
        binding=parent_root,
        traversal_chain=(FakeNativeRootObject("fs:pub-1"),),
        observed_access=frozenset({"read", "write"}),
        observation_boundary="A_PRE_ARM",
        provenance=(WITNESS_1,),
    )
    ev_root_obs = RootObservation(
        root_kind="host_evidence",
        binding=parent_root,
        traversal_chain=(FakeNativeRootObject("fs:ev-1"),),
        observed_access=frozenset({"read", "write"}),
        observation_boundary="A_PRE_ARM",
        provenance=(WITNESS_1,),
    )
    both_roots = BothRootObservations(
        publication=pub_root_obs,
        host_evidence=ev_root_obs,
    )
    qa_recv = FakeQAReceiving(receiving_reference=REF_QA, receiver=PROCESS_QA)
    rig.qa_verifier.register_qa_receiving(
        selection_revision=rig.running_job.selection_revision,
        qa_receiving=qa_recv,
    )
    compat_recv = COMPAT_PROFILE_1
    producer_binding = FakeReceiptProducerBinding(
        producer=PROCESS_PRODUCER,
        mechanism=WITNESS_1,
    )

    epoch = N3ObservationEpoch(
        w_arm.expected.processes[0].instance,
        w_arm.observed.envelope.process_observations[0].collector_ref,
        w_arm.expected.processes[0].frontier,
    )
    cursors = CurrentObservationCursors(
        host=(epoch,),
        worker=(epoch,),
    )

    rig.composition.service.register_closure_inputs(
        selection_revision=rig.pre_dispatch_job.selection_revision,
        boundary="A_PRE_CREATE",
        reviewed_graph=w_create.reviewed,
        loaded_closure=w_create.observed,
        observation_epoch=epoch,
    )
    rig.composition.service.register_closure_inputs(
        selection_revision=rig.running_job.selection_revision,
        boundary="A_PRE_ARM",
        reviewed_graph=w_arm.reviewed,
        loaded_closure=w_arm.observed,
        observation_epoch=epoch,
    )
    rig.host_observer.register_observation(
        selection_revision=rig.pre_dispatch_job.selection_revision,
        boundary="A_PRE_CREATE",
        observation=creator_obs,
    )
    rig.host_observer.register_observation(
        selection_revision=rig.running_job.selection_revision,
        boundary="A_PRE_ARM",
        observation=host_obs_arm,
    )
    rig.worker_observer.register_worker_observation(
        selection_revision=rig.running_job.selection_revision,
        boundary="A_PRE_ARM",
        observation=worker_obs_arm,
    )
    rig.root_observer.register_root_binding(
        selection_revision=rig.pre_dispatch_job.selection_revision,
        boundary="A_PRE_CREATE",
        binding=parent_root,
    )
    rig.root_observer.register_root_observation(
        process_registration=PROCESS_WORKER.process_registration,
        root_kind="publication",
        observation=pub_root_obs,
    )
    rig.root_observer.register_root_observation(
        process_registration=PROCESS_WORKER.process_registration,
        root_kind="host_evidence",
        observation=ev_root_obs,
    )

    actual_creation = ActualCreation(
        window_id="win-1",
        object_identity=FakeNativeRootObject("fs:win-1"),
        creator=PROCESS_WORKER,
        birth=WITNESS_1,
    )
    cur_run_arm = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    if isinstance(cur_run_arm, AcceptedData):
        rig.composition.registry.bind_created(
            rig.peer_checker,
            cur_run_arm.data,
            actual_creation,
        )

    req_bytes = b'{"row":"row-1"}'
    rec_bytes = b'{"status":"ok"}'
    req_raw_ref = dc_replace(
        RAW_REF_REQUEST,
        sha256=hashlib.sha256(req_bytes).hexdigest(),
        byte_length=len(req_bytes),
    )
    rec_raw_ref = dc_replace(
        RAW_REF_RECEIPT,
        sha256=hashlib.sha256(rec_bytes).hexdigest(),
        byte_length=len(rec_bytes),
    )
    req_id = dc_replace(
        ex["RowKey"],
        selection=sel_run,
        window_id="win-1",
        row="row-1",
        request_id="req-1",
        sequence=1,
        request_raw_ref=req_raw_ref,
    )
    pred_key = dc_replace(
        ex["LifecycleKey"],
        selection=sel_run,
        launch_id="launch-1",
    )
    pred_occ_handle = dc_replace(
        ex["OccurrenceHandle"],
        key=pred_key,
        controller=PROCESS_HOST,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    rig.host_provenance.register_occurrence(
        pred_key,
        pred_occ_handle,
        witness=WITNESS_1,
    )
    pred_pub = dc_replace(
        ex["RawPublication"],
        occurrence=pred_occ_handle,
        receipt_raw_ref=rec_raw_ref,
        outcome="success",
        cleanup_state="complete",
    )
    pred_prov = dc_replace(
        ex["ReceiptProvenance"],
        operation_key=pred_key,
        occurrence_witness=WITNESS_1,
        publication_witness=WITNESS_1,
        raw_publication=pred_pub,
        producer_instance=creator_inst,
        disarm_relation=FakeDisarmRelation(relation="before", witness=WITNESS_1),
        predecessor=None,
        state="complete",
    )
    occ_handle = dc_replace(
        ex["OccurrenceHandle"],
        key=req_id,
        controller=PROCESS_HOST,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    raw_pub = dc_replace(
        ex["RawPublication"],
        occurrence=occ_handle,
        request_raw_ref=req_raw_ref,
        receipt_raw_ref=rec_raw_ref,
        window_ref=RAW_REF_WINDOW,
        numbered_log_ref=RAW_REF_LOG,
        current_row_ref=RAW_REF_ROW,
        outcome="success",
        cleanup_state="complete",
    )
    prov = dc_replace(
        ex["ReceiptProvenance"],
        operation_key=req_id,
        occurrence_witness=WITNESS_1,
        publication_witness=WITNESS_1,
        raw_publication=raw_pub,
        producer_instance=creator_inst,
        disarm_relation=FakeDisarmRelation(relation="before", witness=WITNESS_1),
        predecessor=pred_prov,
        state="complete",
    )
    ver_recv = VerifiedReceiptBinding(
        selection=sel_run,
        operation_key=req_id,
        occurrence=occ_handle,
        provenance=prov,
        publication=raw_pub,
        receiving=WITNESS_1,
        predecessor=pred_prov,
        disposition="verified",
    )

    op_leg = OperationLeg(
        operation=default_effect_for_job(rig.running_job, "C_PRE_EXECUTION"),
        actor=PROCESS_WORKER,
        target=ExistingSubjectRecord(identity=FakeNativeRootObject("fs:row-1")),
    )
    p5_ass = FakeP5Assessment(
        verdict="PASS",
        trust="UNTRUSTED",
        assessment_reference=REF_COMPAT,
    )

    return {
        "w_create": w_create,
        "w_arm": w_arm,
        "boot_cmp": boot_cmp,
        "cmp_arm": cmp_arm,
        "sel_pre": sel_pre,
        "sel_run": sel_run,
        "creator_inst": creator_inst,
        "checker_inst": checker_inst,
        "creator_obs": creator_obs,
        "parent_root": parent_root,
        "host_obs_arm": host_obs_arm,
        "worker_obs_arm": worker_obs_arm,
        "pub_root_obs": pub_root_obs,
        "ev_root_obs": ev_root_obs,
        "both_roots": both_roots,
        "qa_recv": qa_recv,
        "compat_recv": compat_recv,
        "producer_binding": producer_binding,
        "epoch": epoch,
        "cursors": cursors,
        "req_bytes": req_bytes,
        "rec_bytes": rec_bytes,
        "req_raw_ref": req_raw_ref,
        "rec_raw_ref": rec_raw_ref,
        "req_id": req_id,
        "pred_key": pred_key,
        "pred_occ_handle": pred_occ_handle,
        "pred_pub": pred_pub,
        "pred_prov": pred_prov,
        "occ_handle": occ_handle,
        "raw_pub": raw_pub,
        "prov": prov,
        "ver_recv": ver_recv,
        "op_leg": op_leg,
        "p5_ass": p5_ass,
    }
