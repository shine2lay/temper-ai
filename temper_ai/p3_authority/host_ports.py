"""Ops-facing abstract service and adapter ports; no authenticated supplier.

All nine NativeHostJoin methods require current authenticated context. Separate
provider ports expose only their own job. No class here implements observation,
issuer verification, admission or counting. Missing providers must return an
explicit fixed Refusal with truthful history; never synthesize AcceptedData.
Abstract methods prevent nominal subclasses from silently inheriting no-op
success. Structural typing alone is not authentication or runtime enforcement.
"""

from abc import abstractmethod
from typing import Final, Protocol

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
    """Ops owns implementation; this is its lifecycle, not observe shorthand.

    Every member the service calls is declared here, so an adapter needs no
    test-double base; ``require_port_members`` checks them at composition.
    """

    @abstractmethod
    def lookup_observation(
        self, *, selection_revision: str, boundary: Boundary,
    ) -> HostObservation | None:
        """The host's own observation for this revision and boundary, or None.

        Observation only: the service compares it with the caller's, never
        trusts the caller's in its place.
        """

    @abstractmethod
    def observe(
        self, session: ObservationSession, boundary: Boundary,
    ) -> Result[HostObservation]:
        """The host's current observation in an opened session, or a refusal."""

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

    @abstractmethod
    def finish_witness(
        self, session: ObservationSession, boundary: Boundary,
    ) -> Result[NativeWitness]:
        """The host's witness of the finished boundary in an opened session."""


def require_port_members(provider: object, port: type, *, role: str) -> None:
    """Fail composition loudly when ``provider`` lacks a member of ``port``.

    The ports are not runtime-checkable Protocols, and an adapter need not
    subclass them or a test double, so this is the one structural check: each
    abstract member of ``port`` must be callable on ``provider``.
    """
    members = getattr(port, "__abstractmethods__", None) if isinstance(port, type) else None
    if not members:
        raise TypeError(f"{role}: {port!r} is not a port with abstract members")
    missing = sorted(
        name for name in members if not callable(getattr(provider, name, None))
    )
    if missing:
        raise TypeError(
            f"{role} lacks {port.__name__} members: {', '.join(missing)}"
        )


LINKED_RECEIPT_BOUNDARIES: Final[frozenset[Boundary]] = frozenset(
    {"C_PRE_EXECUTION", "C_BEFORE_COUNT"}
)
"""Exactly the boundaries the service passes to ``verify_linked_receipt``.

``before_count`` passes ``C_BEFORE_COUNT``; ``receive`` passes its effect's
boundary and refuses ``SCOPE_MISMATCH`` before the port for any other. An
adapter refuses ``SCOPE_MISMATCH`` for a boundary outside this set.
"""


class HostProvenance(Protocol):
    """Ops adapter boundary. Original raw bytes are never rewritten or logged.

    The adapter keeps one receipt chain per window (``selection_revision``,
    ``window_id``): ``bind_publication`` links a receipt after the window's
    current head; ``verify_linked_receipt`` is the one authentication of a
    receipt for count and receive. Lookups are observation, never
    authentication.
    """

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
    ) -> Result[ReceiptProvenance]:
        """Return the host-published provenance for ``publication`` and link it.

        From the adapter's own records: provenance selection != occurrence key's
        selection -> SELECTION_FOREIGN; its occurrence_witness differs from
        ``occurrence.witness`` or its publication_witness from ``witness`` ->
        PRIOR_UNVERIFIED; provenance state not complete, cleanup not
        not-required/complete, outcome not success/app-failure/host-failure,
        occurrence state not completed/failed or raw_publication !=
        ``publication`` -> RESULT_UNVERIFIED. Linking: the provenance's
        predecessor must equal the window's linked head (None and a head ->
        PRIOR_MISSING; otherwise unequal -> PRIOR_UNVERIFIED) and a
        continuation row (``REQUIRED_PREDECESSOR_ROW``) needs a linked
        successful required row as that predecessor (None -> PRIOR_MISSING,
        other -> PRIOR_UNVERIFIED). A key already linked answers its link.
        """

    @abstractmethod
    def verify_linked_receipt(
        self, key: OperationKey, provenance: ReceiptProvenance, boundary: Boundary,
    ) -> Result[NativeReceive]:
        """Authenticate ``provenance`` for ``key`` from this adapter's own chain.

        Never from the caller's objects or host-observed occurrences alone; the
        service counts or receives only the returned binding. Obligations, in
        order, each from the adapter's records:
        a. ``boundary`` in ``LINKED_RECEIPT_BOUNDARIES`` else SCOPE_MISMATCH;
           key exactly RowKey/LifecycleKey, ``type(provenance) is
           ReceiptProvenance`` and ``provenance.operation_key == key`` else
           RESULT_UNVERIFIED.
        b. the key's window genesis is anchored else PRIOR_MISSING.
        c. the window is untainted else WINDOW_INELIGIBLE.
        d. ``key`` is linked in the window's chain else RESULT_UNVERIFIED.
        e. predecessor exact both ways against the linked one: caller None and
           linked not None -> PRIOR_MISSING; caller not None and linked None,
           or not type-exact equal -> PRIOR_UNVERIFIED; then ``provenance`` ==
           the linked provenance (type-exact) else RESULT_UNVERIFIED.
        f. the linked predecessor is the window head the key was linked after
           (None only for the window's first link) - checked at link time.
        g. a continuation row's linked predecessor is a linked successful
           ``REQUIRED_PREDECESSOR_ROW`` row of the same window: None ->
           PRIOR_MISSING, other -> PRIOR_UNVERIFIED.
        h. the original request/receipt bytes the adapter holds hash to the
           linked publication's request_raw_ref/receipt_raw_ref, else (no bytes
           held included) RESULT_UNVERIFIED.
        i. returns AcceptedData(VerifiedReceiptBinding(selection=key.selection,
           operation_key=key, occurrence=linked publication's occurrence,
           provenance=linked, publication=linked raw_publication,
           receiving=the link's receiving witness, predecessor=linked
           predecessor, disposition="verified")) with the selection revision's
           evidence; no evidence -> RESULT_UNVERIFIED.
        """

    @abstractmethod
    def lookup_occurrence_handle(self, key: OperationKey) -> OccurrenceHandle | None:
        """Host-observed occurrence for this exact key, for the join's lookup_occurrence.

        Observation only, never authentication of a receipt or a predecessor.
        """

    @abstractmethod
    def lookup_witness(self, key: OperationKey) -> NativeWitness | None:
        """Host-observed witness for this exact key (observation only, never authentication)."""
