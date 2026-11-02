"""Independent job selection data; never an issuer or a workflow-selected grant.

Frozen records preserve domain distinctions. Services still authenticate every
reference, enforce closed domains, and check current scope/revocation. There is
no native wire parser or registry here. Untrusted dictionaries must not be
passed to these constructors as a substitute for that service validation.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from temper_ai.config.admission_contract import DispatchIdentity

from .references import NativeInterval, NativeProcessRef, NativeSubject, NativeWitness


@dataclass(frozen=True, slots=True, kw_only=True)
class JobKey:
    """Reuse the existing dispatch generation; project run IDs stay separate."""

    dispatch: DispatchIdentity
    job_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PreDispatchJob:
    execution_uuid: str
    designated_workflow: str
    descriptor_digest: str
    job_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityRef:
    """Locator, explicitly not permission."""

    issuer_id: str
    record_id: str
    authority_revision: str


class ImmutableReference(Protocol):
    """Consumer view of exact bytes and revision, not an artifact loader."""

    @property
    def path(self) -> str: ...

    @property
    def digest(self) -> str: ...

    @property
    def length(self) -> int: ...

    @property
    def revision(self) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectSelection:
    project_id: str
    run_id: str
    kit_id: str
    kit_sha256: str
    build_sums_sha256: str
    publication_ref: ImmutableReference
    publication_revision: str
    build_ref: ImmutableReference
    kind: Literal["project"] = field(default="project", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationSelection:
    manifest_ref: ImmutableReference
    entry_id: str
    calibration_run: str
    round: str
    copy_identity: str
    expected_draft_kit: ImmutableReference
    build_sums_sha256: str
    publication_ref: ImmutableReference
    publication_revision: str
    build_ref: ImmutableReference
    selected_runtime_profile: str
    kind: Literal["calibration"] = field(default="calibration", init=False)


Selection = ProjectSelection | CalibrationSelection


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionRef:
    """Existing authority condition, not a new condition expression language."""

    authority: AuthorityRef
    condition_id: str
    revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedOperation:
    """Exact existing domain entry; the service rejects unknown combinations."""

    domain: str
    operation: str
    revision: str


EffectSet = frozenset[SelectedOperation]


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedSubject:
    subject: NativeSubject
    job: PreDispatchJob | JobKey
    selection_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TrustedInstant:
    clock_domain: str
    reading: str
    witness: NativeWitness


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedAuthority:
    """Verification snapshot DATA; construction cannot authenticate its origin."""

    issuer_identity: str
    verified_record_digest: str
    subject: SelectedSubject
    actors: tuple[NativeProcessRef, ...]
    operations: EffectSet
    roots: tuple[NativeSubject, ...]
    conditions: tuple[ConditionRef, ...]
    not_before: TrustedInstant
    expires_at: TrustedInstant
    revocation_source: AuthorityRef
    revocation_revision: str
    checked_at: TrustedInstant
    verification_profile: str
    validity: NativeInterval


@dataclass(frozen=True, slots=True, kw_only=True)
class CompatibilityProfile:
    """Independently selected whole version profile; suffixes are not aliases."""

    decision: str
    reviewed_graph: str
    loaded_envelope: str
    comparator: str
    observation: str
    inspect: Literal["/1", "/2"]
    caller: str
    corpus: Literal["ops-host-compat-corpus/1"]
    receiving: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedJob:
    pre_dispatch_or_running_job: PreDispatchJob | JobKey
    selector_issuer: AuthorityRef
    selection_revision: str
    selection: Selection
    approved_descriptor_digest: str
    expected_source_digest: str
    reviewed_closure_ref: ImmutableReference
    compatibility_profile: CompatibilityProfile
    authorized_operations: EffectSet
    conditions: tuple[ConditionRef, ...]
    authority_refs: tuple[AuthorityRef, ...]
    route: Literal["external-db-fresh"] = field(default="external-db-fresh", init=False)
