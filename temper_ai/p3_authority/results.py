"""Service result data, never an authority-bearing capability.

All accepted data carries the evaluated boundary and independently checked
identity/revision context. The abstract evidence interface intentionally has
no concrete production implementation here. Serialized records and local
constructors do not establish that the authenticated service accepted them.
"""

from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeAlias, TypeVar

from p3_source_closure.records import BoundaryPhase as Boundary

from .references import NativeProcessRef, NativeSubject
from .refusals import Phase, Refusal
from .selection import (
    AuthorityRef,
    CompatibilityProfile,
    ImmutableReference,
    SelectedJob,
    SelectedOperation,
)


class DecisionEvidence(Protocol):
    """Required service context; references still require authentication.

    ``None`` window means there is no actual/selected window at this stage,
    not an invented observed identity. Future subjects cannot satisfy B/C.
    No field's value provides an exemption from the service's boundary checks.
    """

    @property
    def schema(self) -> Literal["p3-native-decision/1"]: ...

    @property
    def selected_job(self) -> SelectedJob: ...

    @property
    def authority_revisions(self) -> tuple[AuthorityRef, ...]: ...

    @property
    def window(self) -> NativeSubject | None: ...

    @property
    def processes(self) -> tuple[NativeProcessRef, ...]: ...

    @property
    def effect(self) -> SelectedOperation: ...

    @property
    def phase(self) -> Phase: ...

    @property
    def boundary(self) -> Boundary: ...

    @property
    def source(self) -> ImmutableReference: ...

    @property
    def closure(self) -> ImmutableReference: ...

    @property
    def compatibility(self) -> CompatibilityProfile: ...

    @property
    def receiving(self) -> tuple[ImmutableReference, ...]: ...


T = TypeVar("T")


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedData(Generic[T]):
    """Authenticated-origin data when returned by a service, not by construction.

    A provider that is absent/unconfigured returns Refusal with the applicable
    fixed unavailable reason and explicit history, never AcceptedData(None).
    Observation/assessment/receiving data is not a count decision. Effect owners
    must recheck the current exact decision at their own effect boundary.
    """

    data: T
    evidence: DecisionEvidence


Result: TypeAlias = AcceptedData[T] | Refusal
