"""Ops-facing abstract service and adapter ports; no authenticated supplier.

All nine NativeHostJoin methods require current authenticated context. Separate
provider ports expose only their own job. No class here implements observation,
issuer verification, admission or counting. Missing providers must return an
explicit fixed Refusal with truthful history; never synthesize AcceptedData.
Abstract methods prevent nominal subclasses from silently inheriting no-op
success. Structural typing alone is not authentication or runtime enforcement.
"""

from abc import abstractmethod
from typing import Protocol

from p3_source_closure import (
    LoadedClosureEnvelope,
    ReviewedSourceGraph,
    SourceClosureComparison,
)

from .boundary_types import NativeReceive
from .host_types import (
    EffectLease,
    HostCoverage,
    HostEffect,
    HostObservation,
    ObservationScope,
    OccurrenceHandle,
    OperationKey,
    RawPublication,
    ReceiptProvenance,
    SelectedHostJob,
)
from .references import (
    NativeSelection,
    NativeSession,
    NativeWitness,
    ObservationSession,
    PermissionHandle,
)
from .results import Boundary, Result


class NativeObservationProvider(Protocol):
    @abstractmethod
    def open_observation(
        self, permission: PermissionHandle, scope: ObservationScope,
    ) -> Result[ObservationSession]: ...

    @abstractmethod
    def observe(
        self, session: ObservationSession, boundary: HostEffect,
    ) -> Result[HostObservation]: ...


class NativeEventProvider(Protocol):
    """Read captured native truth; none of these methods signs a caller assertion."""

    @abstractmethod
    def witness_event(
        self, session: ObservationSession, key: OperationKey, boundary: HostEffect,
    ) -> Result[NativeWitness]: ...

    @abstractmethod
    def lookup_occurrence(
        self, session: NativeSession, key: OperationKey,
    ) -> Result[NativeWitness]: ...

    @abstractmethod
    def verify_publication(
        self, session: NativeSession, key: OperationKey,
        publication: RawPublication, witness: NativeWitness,
    ) -> Result[ReceiptProvenance]: ...


class NativeHostJoin(NativeObservationProvider, NativeEventProvider, Protocol):
    """The same service composition; not another issuer or permission language."""

    @abstractmethod
    def select_host_job(self, session: NativeSession) -> Result[SelectedHostJob]: ...

    @abstractmethod
    def permit_observation(
        self, session: NativeSession, scope: ObservationScope,
    ) -> Result[PermissionHandle]: ...

    @abstractmethod
    def recheck_effect(
        self, session: ObservationSession, effect: HostEffect, coverage: HostCoverage,
    ) -> Result[EffectLease]: ...

    @abstractmethod
    def receive(
        self, session: NativeSession, key: OperationKey,
        provenance: ReceiptProvenance, boundary: HostEffect,
    ) -> Result[NativeReceive]: ...


class SharedN3(Protocol):
    """Adapter resolves/authenticates inputs, then uses Systems' ONE comparator.

    This is not a second comparator implementation. Local host completeness
    cannot replace missing worker history; MATCH grants no effect authority.
    """

    @abstractmethod
    def compare(
        self, reviewed: ReviewedSourceGraph, observed: LoadedClosureEnvelope, *,
        selection: NativeSelection, boundary: Boundary,
    ) -> Result[SourceClosureComparison]: ...


class HostObserver(Protocol):
    """Ops owns implementation; this is its lifecycle, not observe shorthand."""

    @abstractmethod
    def begin(
        self, session: NativeSession, selection: SelectedHostJob,
        scope: ObservationScope, permission: PermissionHandle,
    ) -> Result[ObservationSession]: ...

    @abstractmethod
    def checkpoint(
        self, session: ObservationSession, boundary: HostEffect,
    ) -> Result[HostCoverage]: ...

    @abstractmethod
    def before_effect(
        self, session: ObservationSession, effect: HostEffect, coverage: HostCoverage,
    ) -> Result[EffectLease]: ...

    @abstractmethod
    def finish(
        self, session: ObservationSession, boundary: HostEffect,
    ) -> Result[HostCoverage]: ...


class HostProvenance(Protocol):
    """Ops adapter boundary. Original raw bytes are never rewritten or logged."""

    @abstractmethod
    def note_admission(
        self, session: NativeSession, key: OperationKey,
        lease: EffectLease, admission_witness: NativeWitness,
    ) -> Result[OccurrenceHandle]: ...

    @abstractmethod
    def note_effect(
        self, session: NativeSession, occurrence: OccurrenceHandle,
        effect: HostEffect, witness: NativeWitness,
    ) -> Result[OccurrenceHandle]: ...

    @abstractmethod
    def bind_publication(
        self, session: NativeSession, occurrence: OccurrenceHandle,
        publication: RawPublication, witness: NativeWitness,
    ) -> Result[ReceiptProvenance]: ...

    @abstractmethod
    def verify_received(
        self, session: NativeSession, key: OperationKey, request_raw: bytes,
        receipt_raw: bytes, provenance: ReceiptProvenance, boundary: HostEffect,
    ) -> Result[NativeReceive]: ...
