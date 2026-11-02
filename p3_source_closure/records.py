"""Canonical immutable N3 data records. Constructors confer no authentication.

Origins and expectations must come from an independently authenticated service.
No production provider is implemented here. Repr never includes supplied data.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from types import UnionType
from typing import Literal, get_args, get_origin, get_type_hints

from .validation import _refuse

GraphSchema = Literal["p3-reviewed-source-graph/1"]
EnvelopeSchema = Literal["p3-reviewed-loaded-closure/1"]
BoundaryPhase = Literal["A_PRE_CREATE", "A_PRE_ARM", "B_PRE_REQUEST", "C_PRE_REQUEST", "C_PRE_EXECUTION", "C_BEFORE_COUNT"]
Reason = Literal["FORMAT", "REVIEW_ORIGIN", "GIT_MEMBERSHIP", "GENERATED_PROVENANCE", "RUNTIME_PROVENANCE", "CACHED_CODE", "BINDING", "PROCESS_INSTANCE", "UNREVIEWED_LOAD", "BYTE_SUBSTITUTION", "REQUIRED_LOAD", "OBSERVER_ORIGIN", "SEQUENCE_GAP", "COVERAGE_GAP", "STALE_FRONTIER", "CHILD_COVERAGE"]
Coverage = Literal["launch", "bootstrap", "python", "generated", "cache", "native", "dynamic", "children", "control_plane", "effect_fence"]
# Adopted §8.1 names reuse the checkpoint's exact categories; no complete flag.
N3Coverage = Coverage
N3Gap = Coverage
Purpose = Literal["review", "membership", "generation", "artifact", "cache", "condition", "policy", "legacy", "process", "collector", "event", "checkpoint"]
Role = Literal["creator", "controller", "executor", "worker", "checker", "child", "registry", "verifier", "observer", "comparator", "dispatcher"]


def _typed(value: object, annotation: object) -> bool:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if origin is UnionType:
        return any(_typed(value, item) for item in args)
    if origin is tuple:
        return type(value) is tuple and all(_typed(item, args[0]) for item in value)
    if annotation is str:
        # All N3 textual identities are nonempty UTF-8 without an embedded NUL.
        return (type(value) is str and bool(value) and "\x00" not in value
                and not any(0xD800 <= ord(char) <= 0xDFFF for char in value))
    if annotation is int:
        return type(value) is int and value >= 0
    return type(value) is annotation


class Record:
    """Strict built-in primitives; no mutable collections or subclass coercion."""

    __slots__ = ()

    def __post_init__(self) -> None:
        hints = get_type_hints(type(self))
        if not all(_typed(getattr(self, f.name), hints[f.name]) for f in fields(self)):
            _refuse("TARGET_BINDING_INVALID")

    def __repr__(self) -> str:
        return type(self).__name__ + "(data)"


@dataclass(frozen=True, slots=True, repr=False)
class ContentIdentity(Record):
    sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceRef(Record):
    schema: str
    content: ContentIdentity
    supplier: str
    record_id: str


@dataclass(frozen=True, slots=True, repr=False)
class Repository(Record):
    id: str
    owner: Literal["ops", "architecture", "qa", "temper", "systems"]
    object_format: Literal["sha1", "sha256"]
    commit: str
    tree: str


@dataclass(frozen=True, slots=True, repr=False)
class GitProvenance(Record):
    tag: Literal["git"]
    repository: str
    commit: str
    tree: str
    path: str
    mode: Literal["100644", "100755", "120000", "160000"]
    object_id: str
    membership_ref: EvidenceRef | None
    target_chain: tuple[str, ...]
    representation: Literal["regular", "symlink", "submodule", "lfs"]


@dataclass(frozen=True, slots=True, repr=False)
class GeneratedProvenance(Record):
    tag: Literal["generated"]
    generators: tuple[str, ...]
    inputs: tuple[str, ...]
    toolchain: tuple[str, ...]
    recipe: ContentIdentity
    output: ContentIdentity
    execution_object: ContentIdentity
    generation_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class ArtifactProvenance(Record):
    tag: Literal["artifact"]
    artifact: ContentIdentity
    build: ContentIdentity
    sources: tuple[str, ...]
    dependencies: tuple[str, ...]
    interpreter: str
    abi: str
    representation: Literal["bytes", "relocated", "jit"]
    loaded_representation: ContentIdentity
    provenance_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class CachedProvenance(Record):
    tag: Literal["cache"]
    source_nodes: tuple[str, ...]
    interpreter: str
    cache_format: str
    executed: ContentIdentity
    provenance_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class SourceNode(Record):
    id: str
    kind: Literal["git_source", "generated", "package", "interpreter", "stdlib", "native_binary", "resource", "cached_code"]
    content: ContentIdentity
    logical_origin: str
    mode: str
    provenance: GitProvenance | GeneratedProvenance | ArtifactProvenance | CachedProvenance


@dataclass(frozen=True, slots=True, repr=False)
class SourceEdge(Record):
    source: str
    target: str
    kind: Literal["bootstrap", "import", "dynamic_import", "resource", "generates", "generated_input", "links", "cache_of", "spawns"]
    condition_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class Entrypoint(Record):
    id: str
    profile_id: str
    node: str
    symbol_or_invocation: str
    bootstrap_chain: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class ProcessProfile(Record):
    id: str
    role: Role
    entrypoint_ids: tuple[str, ...]
    runtime_nodes: tuple[str, ...]
    allowed_node_ids: tuple[str, ...]
    required_load_ids: tuple[str, ...]
    child_profiles: tuple[str, ...]
    load_policy_ref: EvidenceRef


@dataclass(frozen=True, slots=True, repr=False)
class SourceGraph(Record):
    schema: GraphSchema
    graph_id: str
    repositories: tuple[Repository, ...]
    nodes: tuple[SourceNode, ...]
    edges: tuple[SourceEdge, ...]
    entrypoints: tuple[Entrypoint, ...]
    process_profiles: tuple[ProcessProfile, ...]
    completeness_review_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class ClosureBinding(Record):
    execution_uuid: str
    attempt: int
    dispatch_nonce: str
    job_revision: str
    route: Literal["external-db-fresh"]
    selection_revision: str
    creation_subject: str
    build: ContentIdentity
    parent_identity: str
    window_id: str | None
    creation_association: str | None


@dataclass(frozen=True, slots=True, repr=False)
class ClosureBoundary(Record):
    phase: BoundaryPhase
    operation: str
    request_id: str | None
    receipt: ContentIdentity | None
    barrier_id: str
    validity_checkpoint: str


@dataclass(frozen=True, slots=True, repr=False)
class ProcessInstance(Record):
    instance_id: str
    host_boot: str
    pid: int
    start_identity: str
    exec_epoch: int
    parent_instance: str | None
    launch_identity: str
    pid_namespace: str
    mount_namespace: str
    user_namespace: str
    location: Literal["host", "container"]
    container_identity: str | None
    principal: str
    uid: int
    gid: int
    supplementary_groups: tuple[int, ...]
    runtime_id: str


@dataclass(frozen=True, slots=True, repr=False)
class LoadEvent(Record):
    sequence: int
    event_id: str
    kind: Literal["start", "load", "compile", "cache", "use", "exec", "child", "end"]
    node_id: str | None
    loaded: ContentIdentity | None
    loader: str
    representation: Literal["bytes", "relocated", "jit"]
    child_instance: str | None
    origin_ref: EvidenceRef | None


@dataclass(frozen=True, slots=True, repr=False)
class Checkpoint(Record):
    epoch: str
    first_sequence: int
    last_sequence: int
    last_event_id: str
    child_frontier: tuple[str, ...]
    coverage: tuple[Coverage, ...]
    gaps: tuple[Coverage, ...]
    loss_count: int
    sealed: bool
    initial_state_ref: EvidenceRef | None
    checkpoint_ref: EvidenceRef | None
    boundary: ClosureBoundary


@dataclass(frozen=True, slots=True, repr=False)
class ProcessObservation(Record):
    profile_id: str
    instance: ProcessInstance
    binding: ClosureBinding
    graph_id: str
    entrypoint_ids: tuple[str, ...]
    runtime_nodes: tuple[str, ...]
    collector_id: str
    collector_version: str
    mechanism: str
    process_ref: EvidenceRef | None
    collector_ref: EvidenceRef | None
    events: tuple[LoadEvent, ...]
    checkpoint: Checkpoint
    state: Literal["running", "terminated"]


@dataclass(frozen=True, slots=True, repr=False)
class LegacyNodeLink(Record):
    legacy_node_id: str
    graph_node_id: str
    content: ContentIdentity
    provenance_ref: EvidenceRef


@dataclass(frozen=True, slots=True, repr=False)
class LegacyLink(Record):
    legacy_ref: EvidenceRef
    node_map: tuple[LegacyNodeLink, ...]


@dataclass(frozen=True, slots=True, repr=False)
class ClosureEnvelope(Record):
    schema: EnvelopeSchema
    envelope_id: str
    reviewed_graph: EvidenceRef
    legacy_links: tuple[LegacyLink, ...]
    binding: ClosureBinding
    boundary: ClosureBoundary
    process_observations: tuple[ProcessObservation, ...]
    provenance_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True, repr=False)
class ReviewedSourceGraph(Record):
    graph: SourceGraph
    content: ContentIdentity


@dataclass(frozen=True, slots=True, repr=False)
class LoadedClosureEnvelope(Record):
    envelope: ClosureEnvelope
    content: ContentIdentity


@dataclass(frozen=True, slots=True, repr=False)
class ProcessFrontier(Record):
    instance_id: str
    epoch: str
    last_sequence: int
    last_event_id: str
    child_frontier: tuple[str, ...]
    checkpoint_ref: EvidenceRef


@dataclass(frozen=True, slots=True, repr=False)
class N3SourceEpoch(Record):
    """Exact review/selection identity, not a producer-maintained counter."""

    reviewed_graph: EvidenceRef
    review_ref: EvidenceRef
    selection_revision: str


@dataclass(frozen=True, slots=True, repr=False)
class N3ObservationEpoch(Record):
    """Exact process, collector and sealed frontier reference; no authenticity."""

    instance: ProcessInstance
    collector_ref: EvidenceRef
    frontier: ProcessFrontier

    def __post_init__(self) -> None:
        Record.__post_init__(self)
        if self.instance.instance_id != self.frontier.instance_id:
            _refuse("TARGET_BINDING_INVALID")


@dataclass(frozen=True, slots=True, repr=False)
class ExpectedProcess(Record):
    profile_id: str
    instance: ProcessInstance
    frontier: ProcessFrontier
    coverage: tuple[Coverage, ...]


@dataclass(frozen=True, slots=True, repr=False)
class NativeClosureExpectation(Record):
    binding: ClosureBinding
    boundary: ClosureBoundary
    reviewed_graph: EvidenceRef
    review_ref: EvidenceRef
    processes: tuple[ExpectedProcess, ...]
    legacy_links: tuple[LegacyLink, ...]


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedOriginFact(Record):
    """Service-verified exact claim identity, not a wire trust flag or an issuer."""

    ref: EvidenceRef
    purpose: Purpose
    claim: ContentIdentity


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedClosureOrigins(Record):
    """Unavailable provider = None identities and no facts, never synthetic MATCH."""

    reviewed_bytes: ContentIdentity | None
    observed_bytes: ContentIdentity | None
    expectation: ContentIdentity | None
    validity_checkpoint: str | None
    facts: tuple[VerifiedOriginFact, ...]


@dataclass(frozen=True, slots=True, repr=False)
class SourceClosureComparison(Record):
    disposition: Literal["MATCH", "REFUSED", "UNKNOWN"]
    reasons: tuple[Reason, ...]
    binding: ClosureBinding
    boundary: ClosureBoundary
    reviewed_graph: EvidenceRef
    frontiers: tuple[ProcessFrontier, ...]
