"""Host port implementations for tests that share no class with the test doubles.

One job: stand in for a live Ops adapter. ``PortOnlyHostObserver`` and
``PortOnlyHostProvenance`` have no base class at all (not the ports, not the
in-memory doubles); each declares the port's members and the host-feed helpers
the fixtures use and answers them by delegating to a private double. A service
composed with them proves it has no provider class gate. The conformance kit,
not these wrappers, proves the port's semantics.

``EchoingHostProvenance`` is a deliberately wrong adapter: it answers
``verify_linked_receipt`` with a binding built from the caller's own receipt
(what before_count did before T5-A2). Tests use it to bite the service's own
checks and the conformance kit.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from temper_ai.p3_authority._providers import (
    InMemoryHostObserver,
    InMemoryHostProvenance,
)
from temper_ai.p3_authority.boundary_types import VerifiedReceiptBinding
from temper_ai.p3_authority.contract import (
    AcceptedData,
    Boundary,
    EffectLease,
    HostCoverage,
    HostEffect,
    HostObservation,
    NativeReceive,
    NativeSession,
    NativeWitness,
    ObservationScope,
    ObservationSession,
    OccurrenceHandle,
    OperationKey,
    PermissionHandle,
    RawPublication,
    ReceiptProvenance,
    Result,
    SelectedHostJob,
)
from temper_ai.p3_authority.registry import DecisionEvidenceRecord


class PortOnlyHostObserver:
    """A ``HostObserver`` with no base class (delegates to a private double)."""

    def __init__(self) -> None:
        self._host = InMemoryHostObserver()

    # -- host feed (test helpers) ------------------------------------------

    def register_evidence(
        self, selection_revision: str, evidence: DecisionEvidenceRecord
    ) -> None:
        self._host.register_evidence(selection_revision, evidence)

    def register_observation(self, **kwargs: Any) -> None:
        self._host.register_observation(**kwargs)

    def register_lease(self, **kwargs: Any) -> None:
        self._host.register_lease(**kwargs)

    # -- HostObserver -------------------------------------------------------

    def lookup_observation(
        self, *, selection_revision: str, boundary: Boundary
    ) -> HostObservation | None:
        return self._host.lookup_observation(
            selection_revision=selection_revision, boundary=boundary
        )

    def observe(
        self, session: ObservationSession, boundary: Boundary
    ) -> Result[HostObservation]:
        return self._host.observe(session, boundary)

    def begin(
        self,
        session: NativeSession,
        selection: SelectedHostJob,
        scope: ObservationScope,
        permission: PermissionHandle,
    ) -> Result[ObservationSession]:
        return self._host.begin(session, selection, scope, permission)

    def checkpoint(
        self, session: ObservationSession, boundary: HostEffect
    ) -> Result[HostCoverage]:
        return self._host.checkpoint(session, boundary)

    def before_effect(
        self,
        session: ObservationSession,
        effect: HostEffect,
        coverage: HostCoverage,
    ) -> Result[EffectLease]:
        return self._host.before_effect(session, effect, coverage)

    def finish(
        self, session: ObservationSession, boundary: HostEffect
    ) -> Result[HostCoverage]:
        return self._host.finish(session, boundary)

    def finish_witness(
        self, session: ObservationSession, boundary: Boundary
    ) -> Result[NativeWitness]:
        return self._host.finish_witness(session, boundary)


class PortOnlyHostProvenance:
    """A ``HostProvenance`` with no base class (delegates to a private double)."""

    def __init__(self) -> None:
        self._host = InMemoryHostProvenance()

    # -- host feed (test helpers; also the conformance kit's HostFeed) -------

    def register_evidence(
        self, selection_revision: str, evidence: DecisionEvidenceRecord
    ) -> None:
        self._host.register_evidence(selection_revision, evidence)

    def register_occurrence(
        self,
        key: OperationKey,
        occurrence: OccurrenceHandle,
        witness: NativeWitness | None = None,
    ) -> None:
        self._host.register_occurrence(key, occurrence, witness)

    def anchor_window(self, selection_revision: str, window_id: str) -> None:
        self._host.anchor_window(selection_revision, window_id)

    def taint_window(self, selection_revision: str, window_id: str) -> None:
        self._host.taint_window(selection_revision, window_id)

    def publish_receipt(
        self,
        provenance: ReceiptProvenance,
        *,
        request_raw: bytes | None,
        receipt_raw: bytes | None,
    ) -> None:
        self._host.publish_receipt(
            provenance, request_raw=request_raw, receipt_raw=receipt_raw
        )

    def register_publication_provenance(self, **kwargs: Any) -> None:
        self._host.register_publication_provenance(**kwargs)

    # -- HostProvenance -----------------------------------------------------

    def note_admission(
        self,
        session: NativeSession,
        key: OperationKey,
        lease: EffectLease,
        admission_witness: NativeWitness,
    ) -> Result[OccurrenceHandle]:
        return self._host.note_admission(session, key, lease, admission_witness)

    def note_effect(
        self,
        session: NativeSession,
        occurrence: OccurrenceHandle,
        effect: HostEffect,
        witness: NativeWitness,
    ) -> Result[OccurrenceHandle]:
        return self._host.note_effect(session, occurrence, effect, witness)

    def bind_publication(
        self,
        session: NativeSession,
        occurrence: OccurrenceHandle,
        publication: RawPublication,
        witness: NativeWitness,
    ) -> Result[ReceiptProvenance]:
        return self._host.bind_publication(session, occurrence, publication, witness)

    def verify_linked_receipt(
        self,
        key: OperationKey,
        provenance: ReceiptProvenance,
        boundary: Boundary,
    ) -> Result[NativeReceive]:
        return self._host.verify_linked_receipt(key, provenance, boundary)

    def lookup_occurrence_handle(self, key: OperationKey) -> OccurrenceHandle | None:
        return self._host.lookup_occurrence_handle(key)

    def lookup_witness(self, key: OperationKey) -> NativeWitness | None:
        return self._host.lookup_witness(key)


class EchoingHostProvenance(PortOnlyHostProvenance):
    """Wrong on purpose: verifies a receipt from the caller's own objects.

    Its ``verify_linked_receipt`` never consults the host's chain; it builds a
    "verified" binding from the caller's receipt (``binding_changes`` are then
    applied to it), so only the service's own checks stand in the way.
    """

    def __init__(self, **binding_changes: Any) -> None:
        super().__init__()
        self._binding_changes = binding_changes
        self._evidence: dict[str, DecisionEvidenceRecord] = {}

    def register_evidence(
        self, selection_revision: str, evidence: DecisionEvidenceRecord
    ) -> None:
        super().register_evidence(selection_revision, evidence)
        self._evidence[selection_revision] = evidence

    def verify_linked_receipt(
        self,
        key: OperationKey,
        provenance: ReceiptProvenance,
        boundary: Boundary,
    ) -> Result[NativeReceive]:
        binding = VerifiedReceiptBinding(
            selection=key.selection,
            operation_key=key,
            occurrence=provenance.raw_publication.occurrence,
            provenance=provenance,
            publication=provenance.raw_publication,
            receiving=provenance.occurrence_witness,
            predecessor=provenance.predecessor,
            disposition="verified",
        )
        if self._binding_changes:
            binding = replace(binding, **self._binding_changes)
        return AcceptedData(
            data=binding, evidence=self._evidence[key.selection.selection_revision]
        )


__all__ = ["EchoingHostProvenance", "PortOnlyHostObserver", "PortOnlyHostProvenance"]
