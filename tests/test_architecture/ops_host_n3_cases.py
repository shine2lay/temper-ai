"""Additive N3 synthetic case exports, NOT a provider or a second corpus registry.

The facts below are an invented fixed world. Expected service selection is built
before candidate faults; independent witness encoding does not call production
parsers, comparator, claim builders or verdict logic. QA owns canonical registration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, replace

from p3_source_closure import records as t


def wire(value):
    if isinstance(value, t.Record):
        names = {"source": "from", "target": "to"} if type(value) is t.SourceEdge else {}
        return {names.get(f.name, f.name): wire(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return [wire(v) for v in value]
    return value


def identity(value):
    raw = json.dumps(wire(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return t.ContentIdentity(hashlib.sha256(raw).hexdigest(), len(raw))


def content(label):
    raw = label.encode("ascii")
    return t.ContentIdentity(hashlib.sha256(raw).hexdigest(), len(raw))


def ref(label, schema="synthetic-evidence/1"):
    return t.EvidenceRef(schema, content(label), "synthetic-independent-custody", label)


@dataclass(frozen=True, repr=False)
class Inputs:
    reviewed: t.ReviewedSourceGraph
    observed: t.LoadedClosureEnvelope
    expected: t.NativeClosureExpectation
    verified: t.VerifiedClosureOrigins

    def __repr__(self):
        return "Inputs(synthetic)"


@dataclass(frozen=True)
class Family:
    case_id: str
    disposition: str
    reason: str | None


FAMILIES = (
    Family("N3-01", "UNKNOWN", "REVIEW_ORIGIN"),
    Family("N3-02", "REFUSED", "UNREVIEWED_LOAD"),
    Family("N3-03", "REFUSED", "GIT_MEMBERSHIP"),
    Family("N3-04", "UNKNOWN", "GENERATED_PROVENANCE"),
    Family("N3-05", "REFUSED", "BYTE_SUBSTITUTION"),
    Family("N3-06", "REFUSED", "RUNTIME_PROVENANCE"),
    Family("N3-07", "REFUSED", "PROCESS_INSTANCE"),
    Family("N3-08", "UNKNOWN", "SEQUENCE_GAP"),
    Family("N3-09", "UNKNOWN", "STALE_FRONTIER"),
    Family("N3-10", "UNKNOWN", "OBSERVER_ORIGIN"),
    Family("N3-11", "REFUSED", "BINDING"),
    Family("N3-12", "UNKNOWN", "STALE_FRONTIER"),
    Family("N3-13", "TARGET_SCHEMA_MISMATCH", None),
    Family("N3-14", "UNKNOWN", "CHILD_COVERAGE"),
    Family("N3-15", "REFUSED", "REQUIRED_LOAD"),
)


def _process_key(p):
    return p.instance, p.profile_id, p.binding, p.graph_id


def witnesses(graph, processes):
    """Fixed synthetic native producer, test-only. Never imported by production."""
    facts = []

    def add(reference, purpose, claim):
        if reference is not None:
            facts.append(t.VerifiedOriginFact(reference, purpose, identity(claim)))

    add(graph.completeness_review_ref, "review", graph)
    repos, nodes = {r.id: r for r in graph.repositories}, {n.id: n for n in graph.nodes}
    for node in graph.nodes:
        p = node.provenance
        if type(p) is t.GitProvenance:
            add(p.membership_ref, "membership", (repos[p.repository], node))
        elif type(p) is t.GeneratedProvenance:
            add(p.generation_ref, "generation", (node, tuple(nodes[k] for k in (*p.generators, *p.inputs, *p.toolchain))))
        elif type(p) is t.CachedProvenance:
            add(p.provenance_ref, "cache", (node, tuple(nodes[k] for k in (*p.source_nodes, p.interpreter))))
        else:
            add(p.provenance_ref, "artifact", (node, tuple(nodes[k] for k in (*p.sources, *p.dependencies, p.interpreter))))
    for edge in graph.edges:
        add(edge.condition_ref, "condition", edge)
    for profile in graph.process_profiles:
        add(profile.load_policy_ref, "policy", profile)
    for p in processes:
        key = _process_key(p)
        collector = (key, p.collector_id, p.collector_version, p.mechanism, p.checkpoint.epoch, p.checkpoint.coverage)
        add(p.process_ref, "process", key)
        add(p.collector_ref, "collector", collector)
        add(p.checkpoint.initial_state_ref, "collector", ("initial", collector))
        add(p.checkpoint.checkpoint_ref, "checkpoint", (key, p.checkpoint))
        for event in p.events:
            add(event.origin_ref, "event", (key, p.checkpoint.epoch, event))
    return tuple(facts)


COVERAGE = ("launch", "bootstrap", "python", "generated", "cache", "native", "dynamic", "children", "control_plane", "effect_fence")


def clean_world(case_id="N3-01"):
    early = case_id == "N3-11"
    binding = t.ClosureBinding("job-7", 2, "nonce-3", "revision-5", "external-db-fresh", "selection-9", "create-4", content("build"), "parent-6", None if early else "window-2", None if early else "association-8")
    boundary = t.ClosureBoundary("A_PRE_CREATE" if early else "C_BEFORE_COUNT", "create" if early else "D-1", None if early else "request-11", None if early else content("receipt-13"), "barrier-17", "validity-19")
    repo = t.Repository("repo", "temper", "sha1", "a" * 40, "b" * 40)
    nodes = []
    for name in ("main", "dep", "tool", "optional"):
        nodes.append(t.SourceNode(name, "git_source", content(name), name + ".py", "100644", t.GitProvenance("git", "repo", repo.commit, repo.tree, name + ".py", "100644", "c" * 40, ref("membership-" + name), (), "regular")))
    for family in ("host", "worker"):
        for kind in ("interpreter", "stdlib", "native_binary"):
            name = kind + "-" + family
            nodes.append(t.SourceNode(name, kind, content(name), name, "100755", t.ArtifactProvenance("artifact", content(name), content("build-" + name), ("tool",), (), "interpreter-" + family, "abi-" + family, "bytes", content(name), ref("artifact-" + name))))
    nodes.append(t.SourceNode("generated", "generated", content("generated"), "generated", "100644", t.GeneratedProvenance("generated", ("tool",), ("dep",), ("interpreter-host",), content("recipe"), content("generated"), content("compiled-generated"), ref("generation"))))
    nodes.append(t.SourceNode("cache", "cached_code", content("cache"), "cache", "100644", t.CachedProvenance("cache", ("main",), "interpreter-worker", "cache-v1", content("cache"), ref("cache"))))
    names = ("creator",) if early else ("creator", "host", "worker", "child")
    roles = {"creator": "creator", "host": "controller", "worker": "worker", "child": "child"}
    profiles, entries = [], []
    for name in names:
        runtime = "worker" if name in ("worker", "child") else "host"
        children = ("worker",) if name == "host" else ("child",) if name == "worker" else ()
        required = ("main", "dep", "generated", "cache", "native_binary-" + runtime)
        profiles.append(t.ProcessProfile(name, roles[name], (name + "-entry",), ("interpreter-" + runtime, "stdlib-" + runtime), tuple(n.id for n in nodes), required, children, ref("policy-" + name)))
        entries.append(t.Entrypoint(name + "-entry", name, "main", "main:run", ("dep",)))
    graph = t.SourceGraph("p3-reviewed-source-graph/1", "graph-1", (repo,), tuple(nodes), (t.SourceEdge("main", "dep", "import", None), t.SourceEdge("dep", "main", "import", None), t.SourceEdge("main", "optional", "dynamic_import", ref("condition"))), tuple(entries), tuple(profiles), ref("review"))
    graph_ref = replace(ref("graph", graph.schema), content=identity(graph))
    processes, expected = [], []
    by_node = {n.id: n for n in nodes}
    for number, profile in enumerate(profiles, 101):
        name = profile.id
        parent = "host" if name == "worker" else "worker" if name == "child" else None
        location = "container" if name in ("worker", "child") else "host"
        instance = t.ProcessInstance(name, "boot-1", number, "birth-" + name, 1, parent, "launch-" + name, "pidns-" + location, "mntns-" + location, "userns-" + location, location, "container-1" if location == "container" else None, "actor-" + name, 1001, 1001, (), profile.runtime_nodes[0])
        events = [t.LoadEvent(0, name + "-0", "start", None, None, "trusted-launch", "bytes", None, ref(name + "-event-0"))]
        for node_id in (*profile.runtime_nodes, *profile.required_load_ids):
            sequence = len(events)
            executed = content("compiled-generated") if node_id == "generated" else by_node[node_id].content
            events.append(t.LoadEvent(sequence, name + "-" + str(sequence), "load", node_id, executed, "loader-v1", "bytes", None, ref(name + "-event-" + str(sequence))))
        for child in profile.child_profiles:
            sequence = len(events)
            events.append(t.LoadEvent(sequence, name + "-" + str(sequence), "child", None, None, "trusted-launch", "bytes", child, ref(name + "-event-" + str(sequence))))
        if name == "child":
            sequence = len(events)
            events.append(t.LoadEvent(sequence, name + "-" + str(sequence), "end", None, None, "trusted-launch", "bytes", None, ref(name + "-event-" + str(sequence))))
        cp = t.Checkpoint("epoch-" + name, 0, len(events) - 1, events[-1].event_id, profile.child_profiles, COVERAGE, (), 0, True, ref("initial-" + name), ref("checkpoint-" + name), boundary)
        processes.append(t.ProcessObservation(name, instance, binding, graph.graph_id, profile.entrypoint_ids, profile.runtime_nodes, "independent-collector", "collector-v1", "synthetic-combined-launch-load-fence", ref("process-" + name), ref("collector-" + name), tuple(events), cp, "terminated" if name == "child" else "running"))
        frontier = t.ProcessFrontier(name, cp.epoch, cp.last_sequence, cp.last_event_id, cp.child_frontier, cp.checkpoint_ref)
        expected.append(t.ExpectedProcess(name, instance, frontier, COVERAGE))
    envelope = t.ClosureEnvelope("p3-reviewed-loaded-closure/1", "envelope-1", graph_ref, (), binding, boundary, tuple(processes), ())
    expectation = t.NativeClosureExpectation(binding, boundary, graph_ref, graph.completeness_review_ref, tuple(expected), ())
    snapshot = t.VerifiedClosureOrigins(identity(graph), identity(envelope), identity(expectation), boundary.validity_checkpoint, witnesses(graph, processes))
    return Inputs(t.ReviewedSourceGraph(graph, identity(graph)), t.LoadedClosureEnvelope(envelope, identity(envelope)), expectation, snapshot)


def received(inputs, envelope, *, observed_facts=False):
    """Authenticated transport bytes, not an assertion of complete event history."""
    snapshot = replace(inputs.verified, observed_bytes=identity(envelope))
    if observed_facts:
        # Actual changed loads/processes can be authentically observed and still wrong.
        snapshot = replace(snapshot, facts=witnesses(inputs.reviewed.graph, envelope.process_observations))
    return replace(inputs, observed=t.LoadedClosureEnvelope(envelope, identity(envelope)), verified=snapshot)


def bad_twin(case_id, clean):
    envelope = clean.observed.envelope
    processes = list(envelope.process_observations)
    p = processes[0]
    facts = list(clean.verified.facts)
    if case_id == "N3-01":
        return replace(clean, verified=replace(clean.verified, facts=tuple(f for f in facts if f.purpose != "review")))
    if case_id == "N3-03":
        index = next(i for i, f in enumerate(facts) if f.purpose == "membership")
        facts[index] = replace(facts[index], claim=content("different-tree-path-blob-mode"))
        return replace(clean, verified=replace(clean.verified, facts=tuple(facts)))
    if case_id == "N3-04":
        return replace(clean, verified=replace(clean.verified, facts=tuple(f for f in facts if f.purpose != "generation")))
    if case_id == "N3-10":
        return replace(clean, verified=replace(clean.verified, facts=tuple(f for f in facts if f.ref != p.collector_ref)))
    if case_id in ("N3-09", "N3-12"):
        required = list(clean.expected.processes)
        required[0] = replace(required[0], frontier=replace(required[0].frontier, last_sequence=100, last_event_id="late-100"))
        expectation = replace(clean.expected, processes=tuple(required))
        return replace(clean, expected=expectation, verified=replace(clean.verified, expectation=identity(expectation)))
    if case_id == "N3-13":
        return replace(clean, observed=replace(clean.observed, envelope=replace(envelope, schema="qa-ops-host-source-closure/1")))
    if case_id == "N3-14":
        return received(clean, replace(envelope, process_observations=tuple(p for p in processes if p.profile_id != "child")))
    if case_id == "N3-11":
        return received(clean, replace(envelope, binding=replace(envelope.binding, creation_subject="other-subject")), observed_facts=True)
    if case_id == "N3-06":
        processes[0] = replace(p, runtime_nodes=("interpreter-worker", "stdlib-worker"))
    elif case_id == "N3-07":
        processes[0] = replace(p, instance=replace(p.instance, exec_epoch=2))
    elif case_id == "N3-08":
        processes[0] = replace(p, events=p.events[:2] + p.events[3:])
    elif case_id in ("N3-02", "N3-05", "N3-15"):
        events = list(p.events)
        index = next(i for i, e in enumerate(events) if e.node_id == "cache")
        if case_id == "N3-02":
            # A transitive dependency is really loaded outside the reviewed set.
            events.insert(-1, replace(events[index], sequence=len(events), event_id="unreviewed-event", node_id="omitted", loaded=content("omitted"), origin_ref=ref("unreviewed-event")))
        elif case_id == "N3-05":
            events[index] = replace(events[index], loaded=content("different-executed-cache"))
        else:
            events = [e for e in events if e.node_id != "cache"]
        events = [replace(event, sequence=i) for i, event in enumerate(events)]
        cp = replace(p.checkpoint, last_sequence=len(events) - 1, last_event_id=events[-1].event_id)
        processes[0] = replace(p, events=tuple(events), checkpoint=cp)
        # Service advances the exact frontier independently, not from candidate selection.
        required = list(clean.expected.processes)
        required[0] = replace(required[0], frontier=replace(required[0].frontier, last_sequence=cp.last_sequence, last_event_id=cp.last_event_id))
        expectation = replace(clean.expected, processes=tuple(required))
        clean = replace(clean, expected=expectation, verified=replace(clean.verified, expectation=identity(expectation)))
    return received(clean, replace(envelope, process_observations=tuple(processes)), observed_facts=case_id != "N3-08")
