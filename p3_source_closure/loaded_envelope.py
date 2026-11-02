"""Observation grammar only. Missing histories remain comparison gaps, not defaults."""

from __future__ import annotations

from . import records as t
from .parsing import document, unique
from .validation import _refuse


def check_boundary(binding: t.ClosureBinding, boundary: t.ClosureBoundary) -> None:
    early = boundary.phase in ("A_PRE_CREATE", "A_PRE_ARM")
    if early:
        if boundary.receipt is not None or boundary.request_id is not None:
            _refuse("TARGET_BINDING_INVALID")
        if boundary.phase == "A_PRE_CREATE" and (binding.window_id is not None or binding.creation_association is not None):
            _refuse("TARGET_BINDING_INVALID")
    elif binding.window_id is None or binding.creation_association is None:
        _refuse("TARGET_BINDING_INVALID")
    if boundary.phase in ("C_PRE_REQUEST", "C_PRE_EXECUTION", "C_BEFORE_COUNT") and boundary.request_id is None:
        _refuse("TARGET_BINDING_INVALID")
    if boundary.phase == "C_BEFORE_COUNT" and boundary.receipt is None:
        _refuse("TARGET_BINDING_INVALID")
    if boundary.phase in ("B_PRE_REQUEST", "C_PRE_REQUEST") and boundary.receipt is not None:
        _refuse("TARGET_BINDING_INVALID")


def validate_loaded_envelope(value: object) -> t.LoadedClosureEnvelope:
    envelope, content = document(value, t.ClosureEnvelope)
    if envelope.reviewed_graph.schema != "p3-reviewed-source-graph/1":
        _refuse("TARGET_SCHEMA_MISMATCH")
    check_boundary(envelope.binding, envelope.boundary)
    unique(envelope.provenance_refs)
    unique(tuple(link.legacy_ref for link in envelope.legacy_links))
    for link in envelope.legacy_links:
        if link.legacy_ref.schema != "qa-ops-host-source-closure/1":
            _refuse("TARGET_SCHEMA_MISMATCH")
        unique(tuple(node.legacy_node_id for node in link.node_map))
        unique(tuple(node.graph_node_id for node in link.node_map))
    unique(tuple((p.instance.instance_id, p.checkpoint.epoch) for p in envelope.process_observations))
    for process in envelope.process_observations:
        instance, checkpoint = process.instance, process.checkpoint
        if instance.pid == 0 or (instance.location == "container") != (instance.container_identity is not None):
            _refuse("TARGET_BINDING_INVALID")
        unique(instance.supplementary_groups)
        unique(process.entrypoint_ids)
        unique(process.runtime_nodes)
        unique(checkpoint.child_frontier)
        unique(checkpoint.coverage)
        unique(checkpoint.gaps)
        # Sequence/duplicate contradictions are comparison facts, never normalized away.
        for event in process.events:
            if (event.node_id is None) != (event.loaded is None):
                _refuse("TARGET_BINDING_INVALID")
            if event.kind in ("load", "compile", "cache", "use") and event.node_id is None:
                _refuse("TARGET_BINDING_INVALID")
            if event.kind == "child" and event.child_instance is None:
                _refuse("TARGET_BINDING_INVALID")
    return t.LoadedClosureEnvelope(envelope, content)
