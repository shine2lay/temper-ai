"""Purpose-specific pure evidence comparisons; no verifier/provider implementation."""

from __future__ import annotations

from . import records as t
from .parsing import claim_identity


class Findings:
    """Accumulate contradictions and gaps without losing either or leaking values."""

    def __init__(self, verified: t.VerifiedClosureOrigins) -> None:
        self.origins = {(f.ref, f.purpose): f.claim for f in verified.facts}
        self.contradictions: set[t.Reason] = set()
        self.gaps: set[t.Reason] = set()

    def refuse(self, reason: t.Reason) -> None:
        self.contradictions.add(reason)

    def unknown(self, reason: t.Reason) -> None:
        self.gaps.add(reason)

    def origin(self, ref: t.EvidenceRef | None, purpose: t.Purpose, claim: object, reason: t.Reason) -> None:
        actual = self.origins.get((ref, purpose))
        if actual is None:
            self.unknown(reason)
        elif actual != claim_identity(claim):
            self.refuse(reason)


def check_provenance(graph: t.SourceGraph, findings: Findings) -> None:
    repos = {r.id: r for r in graph.repositories}
    nodes = {n.id: n for n in graph.nodes}
    for node in graph.nodes:
        p = node.provenance
        if type(p) is t.GitProvenance:
            repo = repos[p.repository]
            if p.commit != repo.commit or p.tree != repo.tree or p.mode != node.mode:
                findings.refuse("GIT_MEMBERSHIP")
            findings.origin(p.membership_ref, "membership", (repo, node), "GIT_MEMBERSHIP")
            if p.representation != "regular" and not p.target_chain:
                findings.unknown("COVERAGE_GAP")
            if (p.representation == "symlink") != (p.mode == "120000") or (p.representation == "submodule") != (p.mode == "160000"):
                findings.refuse("GIT_MEMBERSHIP")
        elif type(p) is t.GeneratedProvenance:
            findings.origin(p.generation_ref, "generation", (node, tuple(nodes[key] for key in (*p.generators, *p.inputs, *p.toolchain))), "GENERATED_PROVENANCE")
            if not p.generators or not p.inputs or not p.toolchain:
                findings.unknown("GENERATED_PROVENANCE")
            if node.content != p.output:
                findings.refuse("GENERATED_PROVENANCE")
        elif type(p) is t.CachedProvenance:
            findings.origin(p.provenance_ref, "cache", (node, tuple(nodes[key] for key in (*p.source_nodes, p.interpreter))), "CACHED_CODE")
            if not p.source_nodes:
                findings.unknown("CACHED_CODE")
            if node.content != p.executed:
                findings.refuse("CACHED_CODE")
        else:
            findings.origin(p.provenance_ref, "artifact", (node, tuple(nodes[key] for key in (*p.sources, *p.dependencies, p.interpreter))), "RUNTIME_PROVENANCE")
            if node.content != p.artifact:
                findings.refuse("RUNTIME_PROVENANCE")
            if nodes[p.interpreter].kind != "interpreter":
                findings.refuse("RUNTIME_PROVENANCE")
    for edge in graph.edges:
        if edge.condition_ref is not None:
            findings.origin(edge.condition_ref, "condition", edge, "COVERAGE_GAP")
    for profile in graph.process_profiles:
        findings.origin(profile.load_policy_ref, "policy", profile, "COVERAGE_GAP")


def process_claim(process: t.ProcessObservation) -> tuple:
    return process.instance, process.profile_id, process.binding, process.graph_id


def collector_claim(process: t.ProcessObservation) -> tuple:
    return (process_claim(process), process.collector_id, process.collector_version,
            process.mechanism, process.checkpoint.epoch, process.checkpoint.coverage)


def event_claim(process: t.ProcessObservation, event: t.LoadEvent) -> tuple:
    return process_claim(process), process.checkpoint.epoch, event


def checkpoint_claim(process: t.ProcessObservation) -> tuple:
    return process_claim(process), process.checkpoint
