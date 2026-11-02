"""One pure reviewed-versus-loaded comparator. MATCH is data, never permission.

Canonical import: p3_source_closure. Every
record re-exported here has one definition in p3_source_closure.records. No engine
import, file access, collector, native verifier or production provider lives here.
"""

from __future__ import annotations

from typing import Literal

from . import records as t
from .loaded_envelope import check_boundary, validate_loaded_envelope
from .parsing import claim_identity, decode_record, to_wire, unique
from .provenance import (
    Findings,
    check_provenance,
    checkpoint_claim,
    collector_claim,
    event_claim,
    process_claim,
)
from .records import (  # noqa: F401 -- canonical public re-exports
    ArtifactProvenance,
    CachedProvenance,
    Checkpoint,
    ClosureBinding,
    ClosureBoundary,
    ClosureEnvelope,
    ContentIdentity,
    Entrypoint,
    EvidenceRef,
    ExpectedProcess,
    GeneratedProvenance,
    GitProvenance,
    LegacyLink,
    LegacyNodeLink,
    LoadedClosureEnvelope,
    LoadEvent,
    NativeClosureExpectation,
    ProcessFrontier,
    ProcessInstance,
    ProcessObservation,
    ProcessProfile,
    Repository,
    ReviewedSourceGraph,
    SourceClosureComparison,
    SourceEdge,
    SourceGraph,
    SourceNode,
    VerifiedClosureOrigins,
    VerifiedOriginFact,
)
from .reviewed_graph import validate_reviewed_graph
from .validation import TargetRefused, _refuse  # noqa: F401


def _record(value: object, cls: type[t.Record]) -> None:
    if type(value) is not cls:
        _refuse("TARGET_BINDING_INVALID")
    decode_record(to_wire(value), cls)


def _check_process(process: t.ProcessObservation, required: t.ExpectedProcess,
                   graph: t.SourceGraph, envelope: t.ClosureEnvelope, findings: Findings) -> None:
    profile = next((p for p in graph.process_profiles if p.id == required.profile_id), None)
    if process.instance != required.instance or process.profile_id != required.profile_id:
        findings.refuse("PROCESS_INSTANCE")
    if process.binding != envelope.binding or process.graph_id != graph.graph_id:
        findings.refuse("BINDING")
    if profile is None:
        findings.refuse("PROCESS_INSTANCE")
    else:
        if process.entrypoint_ids != profile.entrypoint_ids:
            findings.refuse("PROCESS_INSTANCE")
        if process.runtime_nodes != profile.runtime_nodes or process.instance.runtime_id not in profile.runtime_nodes:
            findings.refuse("RUNTIME_PROVENANCE")
    findings.origin(process.process_ref, "process", process_claim(process), "PROCESS_INSTANCE")
    findings.origin(process.collector_ref, "collector", collector_claim(process), "OBSERVER_ORIGIN")
    cp = process.checkpoint
    findings.origin(cp.initial_state_ref, "collector", ("initial", collector_claim(process)), "COVERAGE_GAP")
    findings.origin(cp.checkpoint_ref, "checkpoint", checkpoint_claim(process), "OBSERVER_ORIGIN")
    actual_frontier = t.ProcessFrontier(process.instance.instance_id, cp.epoch, cp.last_sequence,
                                       cp.last_event_id, cp.child_frontier, cp.checkpoint_ref) if cp.checkpoint_ref else None
    if actual_frontier != required.frontier or cp.boundary != envelope.boundary:
        findings.unknown("STALE_FRONTIER")
    if not cp.sealed or cp.loss_count or cp.gaps or not set(required.coverage) <= set(cp.coverage):
        findings.unknown("COVERAGE_GAP")
    if "effect_fence" not in cp.coverage:
        findings.unknown("COVERAGE_GAP")
    events = process.events
    sequences = tuple(e.sequence for e in events)
    if not events or cp.first_sequence != 0 or sequences != tuple(range(cp.first_sequence, cp.first_sequence + len(events))) or (events and cp.last_sequence != events[-1].sequence):
        findings.unknown("SEQUENCE_GAP")
    if events and cp.last_event_id != events[-1].event_id:
        findings.unknown("STALE_FRONTIER")
    # Contradictory duplicates remain contradictions; identical repeats remain gaps.
    by_sequence: dict[int, t.LoadEvent] = {}
    by_id: dict[str, t.LoadEvent] = {}
    for event in events:
        if (event.sequence in by_sequence and by_sequence[event.sequence] != event) or (event.event_id in by_id and by_id[event.event_id] != event):
            findings.refuse("SEQUENCE_GAP")
        elif event.sequence in by_sequence or event.event_id in by_id:
            findings.unknown("SEQUENCE_GAP")
        by_sequence[event.sequence], by_id[event.event_id] = event, event
    if not events or events[0].kind != "start":
        findings.unknown("COVERAGE_GAP")
    if process.state == "terminated" and (not events or events[-1].kind != "end"):
        findings.unknown("COVERAGE_GAP")
    if process.state == "running" and any(e.kind == "end" for e in events):
        findings.refuse("PROCESS_INSTANCE")
    if any(e.kind in ("start", "exec") for e in events[1:]):
        # An exec needs its own independently expected instance and epoch.
        findings.unknown("PROCESS_INSTANCE")
    nodes = {n.id: n for n in graph.nodes}
    loads: set[str] = set()
    children: set[str] = set()
    for event in events:
        findings.origin(event.origin_ref, "event", event_claim(process, event), "OBSERVER_ORIGIN")
        if event.child_instance is not None:
            children.add(event.child_instance)
        if event.node_id is None:
            continue
        loads.add(event.node_id)
        node = nodes.get(event.node_id)
        if node is None or profile is None or event.node_id not in profile.allowed_node_ids:
            findings.refuse("UNREVIEWED_LOAD")
            continue
        provenance = node.provenance
        executed = provenance.execution_object if type(provenance) is t.GeneratedProvenance else node.content
        if type(provenance) is t.ArtifactProvenance:
            executed = provenance.loaded_representation
            if event.representation != provenance.representation:
                findings.refuse("RUNTIME_PROVENANCE")
        if event.loaded != executed:
            findings.refuse("BYTE_SUBSTITUTION")
            if node.kind == "cached_code":
                findings.refuse("CACHED_CODE")
        if event.representation != "bytes":
            if type(provenance) is not t.ArtifactProvenance or provenance.representation != event.representation:
                findings.unknown("RUNTIME_PROVENANCE")
    if set(cp.child_frontier) != children:
        findings.unknown("CHILD_COVERAGE")
    if profile is not None:
        entries = {e.id: e for e in graph.entrypoints}
        mandatory = set(profile.required_load_ids) | set(profile.runtime_nodes)
        for key in profile.entrypoint_ids:
            mandatory.update((entries[key].node, *entries[key].bootstrap_chain))
        if not mandatory <= loads:
            if findings.gaps & {"COVERAGE_GAP", "SEQUENCE_GAP", "OBSERVER_ORIGIN", "STALE_FRONTIER"}:
                findings.unknown("REQUIRED_LOAD")
            else:
                findings.refuse("REQUIRED_LOAD")


def compare_loaded_source(reviewed: ReviewedSourceGraph, observed: LoadedClosureEnvelope, *,
                          expected: NativeClosureExpectation,
                          verified: VerifiedClosureOrigins) -> SourceClosureComparison:
    """Compare supplied data only; authenticity is the calling service's precondition."""
    for value, cls in ((reviewed, t.ReviewedSourceGraph), (observed, t.LoadedClosureEnvelope),
                       (expected, t.NativeClosureExpectation), (verified, t.VerifiedClosureOrigins)):
        _record(value, cls)
    # Revalidate even directly constructed records. Constructors are not authority.
    validate_reviewed_graph(to_wire(reviewed.graph))
    validate_loaded_envelope(to_wire(observed.envelope))
    check_boundary(expected.binding, expected.boundary)
    unique(tuple((f.ref, f.purpose) for f in verified.facts))
    unique(tuple(p.instance.instance_id for p in expected.processes))
    findings = Findings(verified)
    graph, envelope = reviewed.graph, observed.envelope
    input_bindings: tuple[tuple[t.ContentIdentity | None, t.ContentIdentity, t.Reason], ...] = (
        (verified.reviewed_bytes, reviewed.content, "REVIEW_ORIGIN"),
        (verified.observed_bytes, observed.content, "OBSERVER_ORIGIN"),
        (verified.expectation, claim_identity(expected), "BINDING"),
    )
    for supplied, input_identity, reason in input_bindings:
        if supplied is None:
            findings.unknown(reason)
        elif supplied != input_identity:
            findings.refuse(reason)
    if verified.validity_checkpoint != expected.boundary.validity_checkpoint:
        findings.unknown("STALE_FRONTIER")
    if (envelope.reviewed_graph != expected.reviewed_graph or
            envelope.reviewed_graph.content != reviewed.content or
            graph.completeness_review_ref != expected.review_ref):
        findings.refuse("REVIEW_ORIGIN")
    if graph.completeness_review_ref is None:
        findings.unknown("COVERAGE_GAP")
    findings.origin(graph.completeness_review_ref, "review", graph, "REVIEW_ORIGIN")
    if envelope.binding != expected.binding or envelope.boundary != expected.boundary:
        findings.refuse("BINDING")
    check_provenance(graph, findings)
    if envelope.legacy_links != expected.legacy_links:
        findings.refuse("REVIEW_ORIGIN")
    nodes = {n.id: n for n in graph.nodes}
    for link in envelope.legacy_links:
        findings.origin(link.legacy_ref, "legacy", link, "REVIEW_ORIGIN")
        for mapping in link.node_map:
            node = nodes.get(mapping.graph_node_id)
            if node is None or mapping.content != node.content:
                findings.refuse("BYTE_SUBSTITUTION")
            findings.origin(mapping.provenance_ref, "legacy", (mapping, node), "REVIEW_ORIGIN")
    required = {p.instance.instance_id: p for p in expected.processes}
    actual = {p.instance.instance_id: p for p in envelope.process_observations}
    if len(actual) != len(envelope.process_observations):
        findings.refuse("PROCESS_INSTANCE")
    if not required:
        findings.unknown("COVERAGE_GAP")
    if required.keys() - actual.keys():
        findings.unknown("CHILD_COVERAGE" if any(required[k].instance.parent_instance is not None for k in required.keys() - actual.keys()) else "PROCESS_INSTANCE")
    if actual.keys() - required.keys():
        findings.refuse("PROCESS_INSTANCE")
    if envelope.boundary.phase not in ("A_PRE_CREATE", "A_PRE_ARM"):
        if {p.instance.location for p in expected.processes} != {"host", "container"}:
            findings.unknown("COVERAGE_GAP")
    for key in sorted(required.keys() & actual.keys()):
        process = actual[key]
        _check_process(process, required[key], graph, envelope, findings)
        parent = process.instance.parent_instance
        if parent is not None:
            if parent not in actual or key not in actual[parent].checkpoint.child_frontier:
                findings.unknown("CHILD_COVERAGE")
            else:
                parent_profile = next((p for p in graph.process_profiles if p.id == actual[parent].profile_id), None)
                if parent_profile is None or process.profile_id not in parent_profile.child_profiles:
                    findings.refuse("CHILD_COVERAGE")
        for child in process.checkpoint.child_frontier:
            if child not in actual:
                findings.unknown("CHILD_COVERAGE")
            elif actual[child].instance.parent_instance != key:
                findings.refuse("CHILD_COVERAGE")
    disposition: Literal["REFUSED", "UNKNOWN", "MATCH"] = "REFUSED" if findings.contradictions else "UNKNOWN" if findings.gaps else "MATCH"
    return t.SourceClosureComparison(disposition, tuple(sorted(findings.contradictions | findings.gaps)),
                                     expected.binding, expected.boundary, expected.reviewed_graph,
                                     tuple(sorted((p.frontier for p in expected.processes), key=lambda p: p.instance_id)) if disposition == "MATCH" else ())
