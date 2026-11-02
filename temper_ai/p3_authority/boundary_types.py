"""Typed boundary data, not executable admission, counting or issuance policy.

Constructors do not authenticate inputs. The service successor must verify
closed schemas, applicability and current authority before returning this data.
Abstract observation/receiving origins remain deliberately unimplemented.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from p3_source_closure import LoadedClosureEnvelope, N3ObservationEpoch

from .host_types import (
    OccurrenceHandle,
    OperationKey,
    ProcessInstance,
    RawPublication,
    RawRef,
    ReceiptProvenance,
    RootBinding,
    RowKey,
)
from .references import (
    ExistingSubject,
    NativeEventRange,
    NativeProcessRef,
    NativeRootObject,
    NativeSelection,
    NativeWitness,
    PermissionHandle,
)
from .results import Boundary
from .selection import (
    AuthorityRef,
    ImmutableReference,
    SelectedJob,
    SelectedOperation,
    VerifiedAuthority,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class N3Version:
    """Distinct schema domains plus an independently pinned comparator revision."""

    reviewed_graph: Literal["p3-reviewed-source-graph/1"]
    loaded_envelope: Literal["p3-reviewed-loaded-closure/1"]
    comparator_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentBinding:
    selected_job: SelectedJob
    authority_revisions: tuple[AuthorityRef, ...]
    boundary: Boundary
    intended_effect: SelectedOperation


@dataclass(frozen=True, slots=True, kw_only=True)
class ActualCreation:
    window_id: str
    object_identity: NativeRootObject
    creator: NativeProcessRef
    birth: NativeWitness


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowBinding:
    current: CurrentBinding
    actual_creation: ActualCreation


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentObservationCursors:
    host: tuple[N3ObservationEpoch, ...]
    worker: tuple[N3ObservationEpoch, ...]


class ObservationGrant(Protocol):
    """Verified collection scope is separate from operation authority."""

    @property
    def permission(self) -> PermissionHandle: ...

    @property
    def authority(self) -> VerifiedAuthority: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerObservation:
    job: SelectedJob
    selection_revision: str
    dispatcher_association: NativeWitness
    worker_instance: ProcessInstance
    checker_instances: tuple[ProcessInstance, ...]
    child_instances: tuple[ProcessInstance, ...]
    runtime_facts: LoadedClosureEnvelope
    launch_profile_ref: ImmutableReference
    load_stream_refs: tuple[NativeEventRange, ...]
    collector_provenance: tuple[NativeWitness, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RootObservation:
    root_kind: Literal["publication", "host_evidence"]
    binding: RootBinding
    traversal_chain: tuple[NativeRootObject, ...]
    observed_access: frozenset[str]
    observation_boundary: Boundary
    provenance: tuple[NativeWitness, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BothRootObservations:
    publication: RootObservation
    host_evidence: RootObservation


class QAReceiving(Protocol):
    """Exact receiver/byte/result reference, not a source-review receipt."""

    @property
    def receiving_reference(self) -> ImmutableReference: ...

    @property
    def receiver(self) -> NativeProcessRef: ...


class CompatibilityReceiving(Protocol):
    @property
    def corpus(self) -> Literal["ops-host-compat-corpus/1"]: ...

    @property
    def receiving_reference(self) -> ImmutableReference: ...


class ReceiptProducerBinding(Protocol):
    @property
    def producer(self) -> NativeProcessRef: ...

    @property
    def mechanism(self) -> NativeWitness: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckerBinding:
    window: WindowBinding
    checker: NativeProcessRef
    both_roots: BothRootObservations
    producer: ReceiptProducerBinding


RequestIdentity = RowKey


@dataclass(frozen=True, slots=True, kw_only=True)
class ImmutableRequestBinding:
    checker: CheckerBinding
    request_identity: RequestIdentity
    request_raw: RawRef


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmittedRequestBinding:
    request: ImmutableRequestBinding
    occurrence: OccurrenceHandle
    admission_witness: NativeWitness


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationLeg:
    operation: SelectedOperation
    actor: NativeProcessRef
    target: ExistingSubject


@dataclass(frozen=True, slots=True, kw_only=True)
class ActualRequestAndReceipt:
    request: ImmutableRequestBinding
    publication: RawPublication


class P5Assessment(Protocol):
    """Untrusted assessment data remains distinct from native receiving/count."""

    @property
    def verdict(self) -> Literal["PASS", "FAIL", "BLOCKED"]: ...

    @property
    def trust(self) -> Literal["UNTRUSTED"]: ...

    @property
    def assessment_reference(self) -> ImmutableReference: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedReceiptBinding:
    """Accepted DATA only; exact predecessor remains an actual occurrence.

    D-5's service check requires the actual authorized D-1 predecessor, earlier
    distinct sequence/request, original bytes and receiving; constructors do not
    enforce order or authorize continuation after drift/disarm.
    """

    selection: NativeSelection
    operation_key: OperationKey
    occurrence: OccurrenceHandle
    provenance: ReceiptProvenance
    publication: RawPublication
    receiving: NativeWitness
    predecessor: ReceiptProvenance | None
    disposition: Literal["verified"]


NativeReceive = VerifiedReceiptBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateArmDecision:
    current: CurrentBinding
    creator: NativeProcessRef
    parent: RootBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckerDecision:
    binding: CheckerBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestDecision:
    binding: ImmutableRequestBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmissionDecision:
    """Pre-journal decision, not a claim that admission/SEQ already happened."""

    binding: ImmutableRequestBinding
    current: CurrentBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionDecision:
    binding: AdmittedRequestBinding
    leg: OperationLeg
    current: CurrentBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class CountDecision:
    """Permission decision DATA, not count append or rewritten app verdict.

    No Boolean constructor grants authority. A truthful FAIL stays FAIL; absent
    evidence/BLOCKED is not a qualified result. Same idempotency key cannot count
    twice; enforcing that fence belongs to the future effect-owning service.
    """

    binding: AdmittedRequestBinding
    receipt: RawRef
    native_receiving: VerifiedReceiptBinding
    qa_receiving: QAReceiving
    verdict: Literal["PASS", "FAIL"]
    idempotency_identity: str
