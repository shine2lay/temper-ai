"""Reviewed-graph grammar only; cycles are legal here, never in legacy R2 /1."""

from __future__ import annotations

import re

from . import records as t
from .parsing import (
    document,
    named,
    object_id,
    references,
    repository_path,
    unique,
)
from .validation import _refuse


def validate_reviewed_graph(value: object) -> t.ReviewedSourceGraph:
    graph, content = document(value, t.SourceGraph)
    repositories, nodes, profiles, entries = (
        named(graph.repositories), named(graph.nodes), named(graph.process_profiles), named(graph.entrypoints)
    )
    if not nodes or not profiles or not entries:
        _refuse("TARGET_BINDING_INVALID")
    for collection in (repositories, nodes, profiles, entries):
        if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key) is None for key in collection):
            _refuse("TARGET_BINDING_INVALID")
    for repo in graph.repositories:
        if not object_id(repo.commit, repo.object_format) or not object_id(repo.tree, repo.object_format):
            _refuse("TARGET_BINDING_INVALID")
    for node in graph.nodes:
        provenance = node.provenance
        if type(provenance) is t.GitProvenance:
            repo = repositories.get(provenance.repository)
            if repo is None or not repository_path(provenance.path):
                _refuse("TARGET_BINDING_INVALID")
            if not all(object_id(oid, repo.object_format) for oid in (provenance.commit, provenance.tree, provenance.object_id)):
                _refuse("TARGET_BINDING_INVALID")
            references(provenance.target_chain, nodes)
            if node.kind not in ("git_source", "resource"):
                _refuse("TARGET_BINDING_INVALID")
        elif type(provenance) is t.GeneratedProvenance:
            for refs in (provenance.generators, provenance.inputs, provenance.toolchain):
                references(refs, nodes)
            if node.kind != "generated":
                _refuse("TARGET_BINDING_INVALID")
        elif type(provenance) is t.CachedProvenance:
            references(provenance.source_nodes, nodes)
            references((provenance.interpreter,), nodes)
            if node.kind != "cached_code":
                _refuse("TARGET_BINDING_INVALID")
        else:
            for refs in (provenance.sources, provenance.dependencies, (provenance.interpreter,)):
                references(refs, nodes)
            if node.kind not in ("package", "interpreter", "stdlib", "native_binary", "resource"):
                _refuse("TARGET_BINDING_INVALID")
    unique(tuple((edge.source, edge.target, edge.kind) for edge in graph.edges))
    for edge in graph.edges:
        # Cycles and self edges can represent real imports/runtime bootstrap.
        if edge.source not in nodes or edge.target not in nodes:
            _refuse("TARGET_BINDING_INVALID")
    for entry in graph.entrypoints:
        references(entry.bootstrap_chain, nodes)
        if entry.node not in nodes or entry.profile_id not in profiles:
            _refuse("TARGET_BINDING_INVALID")
    for profile in graph.process_profiles:
        for refs, targets in ((profile.entrypoint_ids, entries), (profile.runtime_nodes, nodes), (profile.allowed_node_ids, nodes), (profile.required_load_ids, nodes), (profile.child_profiles, profiles)):
            references(refs, targets)
        if not profile.entrypoint_ids or not profile.runtime_nodes:
            _refuse("TARGET_BINDING_INVALID")
        allowed = set(profile.allowed_node_ids)
        if not (set(profile.runtime_nodes) | set(profile.required_load_ids)) <= allowed:
            _refuse("TARGET_BINDING_INVALID")
        if not any(nodes[key].kind == "interpreter" for key in profile.runtime_nodes):
            _refuse("TARGET_BINDING_INVALID")
        for key in profile.entrypoint_ids:
            entry = entries[key]
            if entry.profile_id != profile.id or not {entry.node, *entry.bootstrap_chain} <= allowed:
                _refuse("TARGET_BINDING_INVALID")
    return t.ReviewedSourceGraph(graph, content)
