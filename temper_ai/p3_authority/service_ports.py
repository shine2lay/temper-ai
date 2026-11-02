"""Registry, phase-boundary and observation signatures, without service code.

Effects require independent authentication, exact current selection and a fence
at their own boundary. These protocols cannot implement or prove that fence.
An unavailable provider returns the fixed Refusal, not a successful empty value.
CandidateBindings and the frozen admission wire are unchanged.
"""

from abc import abstractmethod
from typing import Protocol

from p3_source_closure import N3ObservationEpoch, SourceClosureComparison
from temper_ai.config.admission_contract import DispatchIdentity

from .boundary_types import (
    ActualCreation,
    ActualRequestAndReceipt,
    AdmissionDecision,
    AdmittedRequestBinding,
    BothRootObservations,
    CheckerBinding,
    CheckerDecision,
    CompatibilityReceiving,
    CountDecision,
    CreateArmDecision,
    CurrentBinding,
    CurrentObservationCursors,
    ExecutionDecision,
    ImmutableRequestBinding,
    ObservationGrant,
    OperationLeg,
    P5Assessment,
    QAReceiving,
    ReceiptProducerBinding,
    RequestDecision,
    RequestIdentity,
    RootObservation,
    WindowBinding,
    WorkerObservation,
)
from .host_types import HostObservation, ReceiptProvenance, RootBinding, RootScope
from .references import AuthenticatedPeer, NativeProcessRef
from .results import Boundary, Result
from .selection import (
    AuthorityRef,
    EffectSet,
    SelectedJob,
    SelectedOperation,
    SelectedSubject,
    TrustedInstant,
    VerifiedAuthority,
)


class IssuerVerifier(Protocol):
    @abstractmethod
    def verify(
        self, ref: AuthorityRef, peer: AuthenticatedPeer, subject: SelectedSubject,
        effects: EffectSet, at: TrustedInstant,
    ) -> Result[VerifiedAuthority]: ...


class P3AuthorityRegistry(Protocol):
    """Read/validate/bind existing authority; inserting a row cannot issue it."""

    @abstractmethod
    def for_submit(
        self, peer: AuthenticatedPeer, workflow_name: str,
    ) -> Result[SelectedJob]: ...

    @abstractmethod
    def for_run(
        self, peer: AuthenticatedPeer, execution_uuid: str,
        dispatch_identity: DispatchIdentity,
    ) -> Result[SelectedJob]: ...

    @abstractmethod
    def check_current(
        self, peer: AuthenticatedPeer, selected_job_revision: str, boundary: Boundary,
        intended_effect: SelectedOperation, request_identity: RequestIdentity | None = None,
    ) -> Result[CurrentBinding]: ...

    @abstractmethod
    def bind_created(
        self, peer: AuthenticatedPeer, current_binding: CurrentBinding,
        actual_creation: ActualCreation,
    ) -> Result[WindowBinding]: ...


class P3NativeBoundary(Protocol):
    @abstractmethod
    def before_create(
        self, peer: AuthenticatedPeer, selected_job: SelectedJob,
        creator_observation: HostObservation, parent_access_observation: RootBinding,
        bootstrap_comparison: SourceClosureComparison,
    ) -> Result[CreateArmDecision]: ...

    @abstractmethod
    def before_checker(
        self, peer: AuthenticatedPeer, window_binding: WindowBinding,
        host_observation: HostObservation, worker_observation: WorkerObservation,
        both_root_observations: BothRootObservations,
        closure_comparison: SourceClosureComparison, qa_receiving: QAReceiving,
        compatibility_receiving: CompatibilityReceiving,
        receipt_producer_binding: ReceiptProducerBinding,
    ) -> Result[CheckerDecision]: ...

    @abstractmethod
    def before_request(
        self, peer: AuthenticatedPeer, checker_binding: CheckerBinding, row: str,
        request_identity: RequestIdentity, current_observation_cursors: CurrentObservationCursors,
    ) -> Result[RequestDecision]: ...

    @abstractmethod
    def before_admit(
        self, peer: AuthenticatedPeer, immutable_request_binding: ImmutableRequestBinding,
        current_observation_cursors: CurrentObservationCursors,
    ) -> Result[AdmissionDecision]: ...

    @abstractmethod
    def before_execute(
        self, peer: AuthenticatedPeer, admitted_request_binding: AdmittedRequestBinding,
        operation_leg: OperationLeg, current_observation_cursors: CurrentObservationCursors,
    ) -> Result[ExecutionDecision]: ...

    @abstractmethod
    def before_count(
        self, peer: AuthenticatedPeer, actual_request_and_receipt: ActualRequestAndReceipt,
        p5_assessment: P5Assessment, provenance: ReceiptProvenance,
        current_observation_cursors: CurrentObservationCursors,
        exact_qa_receiving: QAReceiving,
    ) -> Result[CountDecision]: ...


class WorkerObserver(Protocol):
    """Unimplemented native load/launch producer; an inventory is not coverage."""

    @abstractmethod
    def observe(
        self, grant: ObservationGrant, selected_job: SelectedJob, boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[WorkerObservation]: ...


class RootObserver(Protocol):
    @abstractmethod
    def observe(
        self, grant: ObservationGrant, actor_instance: NativeProcessRef,
        selected_root: RootScope, required_operations: EffectSet, boundary: Boundary,
    ) -> Result[RootObservation]: ...
