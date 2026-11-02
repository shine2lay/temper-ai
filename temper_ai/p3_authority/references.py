"""Abstract Temper service references, not concrete foreign records or grants.

A reference implementation is supplied by authenticated service composition.
There are deliberately no concrete handles, token parser, issuer, signer,
``runtime_checkable`` capability tests, serialization or production provider.
A matching Python shape is data, never proof that the service accepted it.

This leaf imports only the standard library. Supplier records can be generic
in these references without importing the service, its ports or its adapters.
"""

from __future__ import annotations

from typing import Literal, Protocol


class NativeProcessRef(Protocol):
    """Resolve a separately authenticated complete process registration."""

    @property
    def process_registration(self) -> str: ...


class NativeWitness(Protocol):
    """Locator for an independently captured event, never a caller hash."""

    @property
    def witness_reference(self) -> str: ...


class AuthenticatedPeer(Protocol):
    """Actual implementation must verify channel AND process registration."""

    @property
    def peer_registration(self) -> str: ...

    @property
    def process(self) -> NativeProcessRef: ...


class NativeSession(Protocol):
    """Service access context, explicitly not an operation grant."""

    @property
    def peer(self) -> AuthenticatedPeer: ...

    @property
    def session_reference(self) -> str: ...


class NativeSelection(Protocol):
    """Server reference to an independently selected exact job revision."""

    @property
    def selection_reference(self) -> str: ...

    @property
    def selection_revision(self) -> str: ...


class PermissionHandle(Protocol):
    """Service-resolved collection permission, not operation authority."""

    @property
    def observation_permission(self) -> str: ...


class NativeGrantRef(Protocol):
    """Locator for verified upstream authority; issuer checks remain required."""

    @property
    def grant_reference(self) -> str: ...


class NativeAdmission(Protocol):
    """Reference to one effect-specific current service decision."""

    @property
    def admission_reference(self) -> str: ...


class ObservationSession(Protocol):
    """Authenticated collection lifecycle established before protected reads."""

    @property
    def observation_session(self) -> str: ...

    @property
    def permission(self) -> PermissionHandle: ...


class NativeBirthIdentity(Protocol):
    """Independent kernel/process-birth proof, not a PID or wall time."""

    @property
    def birth_witness(self) -> NativeWitness: ...


class NativeContainerIdentity(Protocol):
    """Daemon instance, full container identity and observed start proof."""

    @property
    def daemon_instance(self) -> str: ...

    @property
    def full_container_id(self) -> str: ...

    @property
    def start_witness(self) -> NativeWitness: ...


class NativeRootObject(Protocol):
    """Filesystem object plus mount, namespace and observation epoch."""

    @property
    def filesystem_object(self) -> str: ...

    @property
    def mount_identity(self) -> str: ...

    @property
    def namespace_identity(self) -> str: ...

    @property
    def observation_epoch(self) -> str: ...


class ExistingSubject(Protocol):
    @property
    def subject_kind(self) -> Literal["existing"]: ...

    @property
    def identity(self) -> NativeProcessRef | NativeRootObject: ...


class FutureSubject(Protocol):
    """Selected constrained launch/new-leaf scope; not an observed identity."""

    @property
    def subject_kind(self) -> Literal["future"]: ...

    @property
    def selected_scope_reference(self) -> str: ...


NativeSubject = ExistingSubject | FutureSubject
NativeEffectTarget = ExistingSubject | FutureSubject


class NativeInterval(Protocol):
    """Service-attested causal validity; clocks do not establish order."""

    @property
    def interval_witness(self) -> NativeWitness: ...

    @property
    def clock_domain(self) -> str: ...


class NativeEventRange(Protocol):
    """Ordered event continuity and loss; no inferred complete default."""

    @property
    def continuity_witness(self) -> NativeWitness: ...

    @property
    def first_sequence(self) -> int: ...

    @property
    def last_sequence(self) -> int: ...

    @property
    def lost_events(self) -> int | None: ...


class NativeObservationFields(Protocol):
    @property
    def allowed_fields(self) -> frozenset[str]: ...


class NativeDisarmRelation(Protocol):
    @property
    def relation(self) -> Literal["before", "during", "after", "absent", "unknown"]: ...

    @property
    def witness(self) -> NativeWitness | None: ...
