"""Candidate-only raw policy and actual snapshot-resolved projections.

The ordinary loader is unchanged. This module performs no registration, start,
provider call, file acquisition, custody check or source discovery. The caller
supplies independent descriptor authority AND measured installed-source facts.
"""
from __future__ import annotations

import copy
import re
import types
from dataclasses import dataclass, fields, replace
from typing import Any, NoReturn, Union, get_args, get_origin, get_type_hints

from temper_ai.agent import AGENT_TYPES
from temper_ai.agent.script_agent import ScriptAgent, _rewrite_interpolations
from temper_ai.agent.single_call_agent import (
    SINGLE_CALL_AGENT_SETTINGS,
    SINGLE_CALL_REQUIRED,
    SINGLE_CALL_SETTINGS,
    SingleCallAgent,
)
from temper_ai.config.admission_capture import SnapshotResolver
from temper_ai.config.admission_contract import (
    AdmissionRecord,
    AdmissionRefused,
    ApprovedCandidateDescriptor,
    ContractCodec,
    DescriptorAuthority,
    FrozenJSON,
    RawClosure,
    RawRecord,
    RefusalCode,
    RootReadiness,
    canonical_bytes,
    decode_canonical,
    require_source,
)
from temper_ai.config.helpers import SUPPORTED_SCHEMA_VERSION
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import StageError
from temper_ai.stage.input_defaults import fill_input_defaults
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from temper_ai.stage.node import Node
from temper_ai.stage.stage_node import StageNode

# Candidate grammar, not new ScriptAgent/global model-value policy. ScriptAgent
# has no closed-key registry; these are its source-read settings plus base fields.
_SCRIPT_KEYS = frozenset({"name", "type", "description", "script_template",
                          "strict_undefined", "timeout_seconds", "log_max_bytes"})
_DEFAULT_KEYS = frozenset({"provider", "model", "temperature", "max_tokens"})
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
_INTERPOLATION = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|\s*env\s*)?\}\}")
_MARKERS = ("${", "{{", "}}", "{%", "%}", "{#", "#}")


def _refuse(code: RefusalCode) -> NoReturn:
    raise AdmissionRefused(code) from None


def _known(cls: type[NodeConfig] | type[WorkflowConfig]) -> list[str]:
    value = cls._KNOWN_FIELDS
    if (type(value) is not frozenset or any(type(k) is not str for k in value)
            or value != {f.name for f in fields(cls) if f.name != "_KNOWN_FIELDS"}):
        _refuse(RefusalCode.FIELDS)
    return sorted(value)


def source_inventory(*, engine_commit: str, engine_tree: str, request_fields: tuple[str, ...]) -> FrozenJSON:
    """Assemble actual inventories around caller-measured installed Git identities.

    The T2 adapter supplies its ACTUAL request field inventory, not descriptor
    fields. This pure assembler does not authenticate those source facts or find
    a checkout. Never call it with candidate-supplied source identities.
    """
    if (type(engine_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", engine_commit)
            or type(engine_tree) is not str or not re.fullmatch(r"[0-9a-f]{40}", engine_tree)
            or type(request_fields) is not tuple
            or any(type(f) is not str or not f for f in request_fields)
            or len(set(request_fields)) != len(request_fields)):
        _refuse(RefusalCode.SOURCE)
    if type(SINGLE_CALL_SETTINGS) is not frozenset or any(type(f) is not str for f in SINGLE_CALL_SETTINGS):
        _refuse(RefusalCode.FIELDS)
    return FrozenJSON(canonical_bytes({
        "engine_commit": engine_commit, "engine_tree": engine_tree,
        "binding_abi": "candidate-admission/v1",
        "field_sets": {"workflow": sorted(f.name for f in fields(WorkflowConfig)),
                       "node": sorted(f.name for f in fields(NodeConfig)),
                       "native": sorted(SINGLE_CALL_SETTINGS), "request": sorted(request_fields)},
    }))


_DEFAULT_SOURCE_INVENTORY = source_inventory
_MAX_CACHE_ENTRIES = 4096
_ORIG_CODEC_METHODS = (
    ContractCodec.validate_shape,
    ContractCodec.descriptor,
    ContractCodec.raw_record,
    ContractCodec.readiness,
    ContractCodec.closure,
    ContractCodec.record,
)
_PURE_CODEC_CACHE: dict[tuple[Any, ...], Any] = {}
_INVENTORY_CACHE: dict[tuple[Any, ...], dict[str, tuple[str, ...]]] = {}
_FROZEN_JSON_CACHE: dict[bytes, FrozenJSON] = {}


def _cache_put(cache: dict[Any, Any], key: Any, value: Any) -> None:
    if key not in cache and len(cache) >= _MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)), None)
    cache[key] = value


def _codec_class_unpatched() -> bool:
    return (
        ContractCodec.validate_shape,
        ContractCodec.descriptor,
        ContractCodec.raw_record,
        ContractCodec.readiness,
        ContractCodec.closure,
        ContractCodec.record,
    ) == _ORIG_CODEC_METHODS


def _frozen_json(wire: bytes) -> FrozenJSON:
    hit = _FROZEN_JSON_CACHE.get(wire)
    if hit is not None:
        return hit
    res = FrozenJSON(wire)
    _cache_put(_FROZEN_JSON_CACHE, wire, res)
    return res


@dataclass(frozen=True, slots=True)
class ValidatedRecordParts:
    record: AdmissionRecord
    descriptor: ApprovedCandidateDescriptor
    descriptor_dict: dict[str, Any]
    immutable_dict: dict[str, Any]
    immutable_sha256: str
    dispatch_dict: dict[str, Any]
    dispatch_wire: bytes
    non_readiness_wire: bytes
    readiness_list: tuple[dict[str, Any], ...]
    readiness_wire_tuple: tuple[bytes, ...]
    readiness_wires: frozenset[bytes]
    base_dict: dict[str, Any]


def _clone_record_parts(parts: ValidatedRecordParts) -> ValidatedRecordParts:
    return ValidatedRecordParts(
        record=parts.record,
        descriptor=parts.descriptor,
        descriptor_dict=copy.deepcopy(parts.descriptor_dict),
        immutable_dict=copy.deepcopy(parts.immutable_dict),
        immutable_sha256=parts.immutable_sha256,
        dispatch_dict=copy.deepcopy(parts.dispatch_dict),
        dispatch_wire=parts.dispatch_wire,
        non_readiness_wire=parts.non_readiness_wire,
        readiness_list=tuple(copy.deepcopy(r) for r in parts.readiness_list),
        readiness_wire_tuple=parts.readiness_wire_tuple,
        readiness_wires=parts.readiness_wires,
        base_dict=copy.deepcopy(parts.base_dict),
    )


def _build_record_parts(
    codec: ContractCodec,
    rec: AdmissionRecord,
    authority: DescriptorAuthority,
    schema_bytes: bytes | None,
) -> ValidatedRecordParts:
    v = decode_canonical(rec.wire)
    immutable = v["immutable"]
    d = codec.descriptor(immutable["descriptor_json"].encode("utf-8"), authority)
    dv = decode_canonical(d.wire)
    base_dict = {k: val for k, val in v.items() if k != "readiness"}
    non_readiness_wire = canonical_bytes(base_dict)
    r_list = tuple(copy.deepcopy(r) for r in v["readiness"])
    r_wire_tuple = tuple(canonical_bytes(r) for r in r_list)
    r_wires = frozenset(r_wire_tuple)
    parts = ValidatedRecordParts(
        record=rec,
        descriptor=d,
        descriptor_dict=dv,
        immutable_dict=immutable,
        immutable_sha256=v["immutable_sha256"],
        dispatch_dict=v["dispatch"],
        dispatch_wire=canonical_bytes(v["dispatch"]),
        non_readiness_wire=non_readiness_wire,
        readiness_list=r_list,
        readiness_wire_tuple=r_wire_tuple,
        readiness_wires=r_wires,
        base_dict=base_dict,
    )
    if schema_bytes is not None:
        _cache_put(_PURE_CODEC_CACHE, ("record_parts", schema_bytes, authority, rec.wire), parts)
        if v["dispatch"]["phase"] == "running" and not r_list and rec.wire.endswith(b',"readiness":[]}'):
            prefix_bytes = rec.wire[:-3]
            _cache_put(
                _PURE_CODEC_CACHE,
                ("running_prefix", schema_bytes, authority, prefix_bytes),
                (
                    prefix_bytes,
                    _clone_record_parts(parts),
                    d.sha256,
                    dv["execution_uuid"],
                    copy.deepcopy(v["dispatch"]),
                    immutable["effective_graph_sha256"],
                    {p["position_id"]: copy.deepcopy(p) for p in dv["positions"]},
                ),
            )
        return _clone_record_parts(parts)
    return parts


def validated_record_parts(
    codec: ContractCodec,
    wire: bytes,
    authority: DescriptorAuthority,
) -> ValidatedRecordParts:
    if type(wire) is not bytes:
        _refuse(RefusalCode.TYPE)
    memoize_codec(codec)
    schema_bytes = getattr(codec, "_schema_bytes", None)

    def _unpatched() -> bool:
        return (
            type(codec) is ContractCodec
            and type(schema_bytes) is bytes
            and "validate_shape" not in codec.__dict__
            and _codec_class_unpatched()
            and getattr(codec, "record", None) is getattr(codec, "_memo_record", None)
            and getattr(codec, "descriptor", None) is getattr(codec, "_memo_descriptor", None)
        )

    unpatched = _unpatched()
    if unpatched:
        hit = _PURE_CODEC_CACHE.get(("record_parts", schema_bytes, authority, wire))
        if hit is not None:
            return _clone_record_parts(hit)
    rec = codec.record(wire, authority)
    if unpatched:
        hit = _PURE_CODEC_CACHE.get(("record_parts", schema_bytes, authority, wire))
        if hit is not None:
            return _clone_record_parts(hit)
        return _build_record_parts(codec, rec, authority, schema_bytes)
    return _build_record_parts(codec, rec, authority, None)


def memoize_codec(codec: ContractCodec) -> ContractCodec:
    """Memoize pure wire-bytes ContractCodec operations keyed by _schema_bytes + wire."""
    if type(codec) is not ContractCodec or getattr(codec, "_pure_memoized", False):
        return codec
    schema_bytes = getattr(codec, "_schema_bytes", None)
    if type(schema_bytes) is not bytes:
        return codec

    def _unpatched() -> bool:
        return (
            getattr(codec, "_schema_bytes", None) == schema_bytes
            and "validate_shape" not in codec.__dict__
            and _codec_class_unpatched()
        )

    def _descriptor(data: bytes, authority: DescriptorAuthority) -> ApprovedCandidateDescriptor:
        if type(data) is bytes and type(authority) is DescriptorAuthority and _unpatched():
            key = ("descriptor", schema_bytes, data, authority)
            hit = _PURE_CODEC_CACHE.get(key)
            if hit is not None:
                return hit
            res = ContractCodec.descriptor(codec, data, authority)
            _cache_put(_PURE_CODEC_CACHE, key, res)
            return res
        return ContractCodec.descriptor(codec, data, authority)

    def _raw_record(data: bytes) -> RawRecord:
        if type(data) is bytes and _unpatched():
            key = ("raw_record", schema_bytes, data)
            hit = _PURE_CODEC_CACHE.get(key)
            if hit is not None:
                return hit
            res = ContractCodec.raw_record(codec, data)
            _cache_put(_PURE_CODEC_CACHE, key, res)
            return res
        return ContractCodec.raw_record(codec, data)

    def _readiness(data: bytes) -> RootReadiness:
        if type(data) is bytes and _unpatched():
            key = ("readiness", schema_bytes, data)
            hit = _PURE_CODEC_CACHE.get(key)
            if hit is not None:
                return hit
            res = ContractCodec.readiness(codec, data)
            _cache_put(_PURE_CODEC_CACHE, key, res)
            return res
        return ContractCodec.readiness(codec, data)

    def _closure(descriptor: ApprovedCandidateDescriptor, records: tuple[RawRecord, ...]) -> RawClosure:
        if (
            type(descriptor) is ApprovedCandidateDescriptor
            and type(records) is tuple
            and all(type(r) is RawRecord for r in records)
            and _unpatched()
            and getattr(codec, "descriptor", None) is _descriptor
            and getattr(codec, "raw_record", None) is _raw_record
        ):
            key = (
                "closure",
                schema_bytes,
                descriptor.wire,
                descriptor.sha256,
                tuple((r.wire, r.sha256) for r in records),
            )
            hit = _PURE_CODEC_CACHE.get(key)
            if hit is not None:
                return hit
            res = ContractCodec.closure(codec, descriptor, records)
            _cache_put(_PURE_CODEC_CACHE, key, res)
            return res
        return ContractCodec.closure(codec, descriptor, records)

    def _record(data: bytes, authority: DescriptorAuthority) -> AdmissionRecord:
        if (
            type(data) is bytes
            and type(authority) is DescriptorAuthority
            and _unpatched()
            and getattr(codec, "descriptor", None) is _descriptor
            and getattr(codec, "raw_record", None) is _raw_record
            and getattr(codec, "closure", None) is _closure
            and getattr(codec, "readiness", None) is _readiness
        ):
            key = ("record", schema_bytes, data, authority)
            hit = _PURE_CODEC_CACHE.get(key)
            if hit is not None:
                return hit
            idx = data.find(b',"readiness":[')
            prefix_entry = (
                _PURE_CODEC_CACHE.get(("running_prefix", schema_bytes, authority, data[: idx + len(b',"readiness":')]))
                if idx != -1
                else None
            )
            if prefix_entry is not None:
                prefix_bytes, base_parts, d_sha256, exec_uuid, dispatch, graph_sha, positions = prefix_entry
                if data.startswith(prefix_bytes) and data.endswith(b"}"):
                    tail = data[len(prefix_bytes):-1]
                    try:
                        readiness_list = decode_canonical(tail)
                    except AdmissionRefused:
                        readiness_list = None
                    if type(readiness_list) is list:
                        seen: set[str] = set()
                        r_wires: list[bytes] = []
                        ok = True
                        for r in readiness_list:
                            if type(r) is not dict:
                                ok = False
                                break
                            try:
                                r_wire = canonical_bytes(r)
                                _readiness(r_wire)
                            except AdmissionRefused:
                                ok = False
                                break
                            r_wires.append(r_wire)
                            pos_id = r.get("position_id")
                            p = positions.get(pos_id) if isinstance(pos_id, str) else None
                            if not isinstance(pos_id, str) or p is None or p["root_policy"] is None or pos_id in seen:
                                ok = False
                                break
                            seen.add(pos_id)
                            if (
                                r["preparation_path"] != p["preparation_path"]
                                or r["descriptor_sha256"] != d_sha256
                                or r["graph_sha256"] != graph_sha
                                or r["execution_uuid"] != exec_uuid
                                or r["dispatch_nonce"] != dispatch["dispatch_nonce"]
                                or r["running_attempt"] != dispatch["running_attempt"]
                            ):
                                ok = False
                                break
                            policy, root = p["root_policy"], r["root"]
                            if (
                                root["path"] != policy["path"]
                                or root["uid"] != policy["creator_uid"]
                                or root["gid"] != policy["creator_gid"]
                                or root["mode"] != policy["directory_mode"]
                                or dispatch["worker_label"] != policy["worker_label"]
                            ):
                                ok = False
                                break
                        if ok:
                            rec = object.__new__(AdmissionRecord)
                            object.__setattr__(rec, "wire", data)
                            _cache_put(_PURE_CODEC_CACHE, key, rec)
                            r_wire_tuple = tuple(r_wires)
                            _cache_put(
                                _PURE_CODEC_CACHE,
                                ("record_parts", schema_bytes, authority, data),
                                ValidatedRecordParts(
                                    record=rec,
                                    descriptor=base_parts.descriptor,
                                    descriptor_dict=copy.deepcopy(base_parts.descriptor_dict),
                                    immutable_dict=copy.deepcopy(base_parts.immutable_dict),
                                    immutable_sha256=base_parts.immutable_sha256,
                                    dispatch_dict=copy.deepcopy(base_parts.dispatch_dict),
                                    dispatch_wire=base_parts.dispatch_wire,
                                    non_readiness_wire=base_parts.non_readiness_wire,
                                    readiness_list=tuple(copy.deepcopy(r) for r in readiness_list),
                                    readiness_wire_tuple=r_wire_tuple,
                                    readiness_wires=frozenset(r_wire_tuple),
                                    base_dict=copy.deepcopy(base_parts.base_dict),
                                ),
                            )
                            return rec
            res = ContractCodec.record(codec, data, authority)
            _cache_put(_PURE_CODEC_CACHE, key, res)
            _build_record_parts(codec, res, authority, schema_bytes)
            return res
        return ContractCodec.record(codec, data, authority)

    object.__setattr__(codec, "descriptor", _descriptor)
    object.__setattr__(codec, "raw_record", _raw_record)
    object.__setattr__(codec, "readiness", _readiness)
    object.__setattr__(codec, "closure", _closure)
    object.__setattr__(codec, "record", _record)
    object.__setattr__(codec, "_memo_descriptor", _descriptor)
    object.__setattr__(codec, "_memo_record", _record)
    object.__setattr__(codec, "_pure_memoized", True)
    return codec


def _current_inventory(source: FrozenJSON) -> dict:
    if (
        type(source) is FrozenJSON
        and source_inventory is _DEFAULT_SOURCE_INVENTORY
        and type(SINGLE_CALL_SETTINGS) is frozenset
        and all(type(f) is str for f in SINGLE_CALL_SETTINGS)
    ):
        cache_key = (
            source.wire,
            tuple(f.name for f in fields(WorkflowConfig)),
            tuple(f.name for f in fields(NodeConfig)),
            SINGLE_CALL_SETTINGS,
        )
        cached = _INVENTORY_CACHE.get(cache_key)
        if cached is not None:
            return {k: list(v) for k, v in cached.items()}
    else:
        cache_key = None
    value = source.value()
    if set(value) != {"engine_commit", "engine_tree", "binding_abi", "field_sets"}:
        _refuse(RefusalCode.SOURCE)
    inventories = value["field_sets"]
    if type(inventories) is not dict or set(inventories) != {"workflow", "node", "native", "request"}:
        _refuse(RefusalCode.FIELDS)
    if type(inventories["request"]) is not list:
        _refuse(RefusalCode.FIELDS)
    actual = source_inventory(engine_commit=value["engine_commit"], engine_tree=value["engine_tree"],
                              request_fields=tuple(inventories["request"]))
    if source.wire != actual.wire:
        _refuse(RefusalCode.FIELDS)
    if cache_key is not None:
        _cache_put(_INVENTORY_CACHE, cache_key, {k: tuple(v) for k, v in inventories.items()})
    return {k: list(v) for k, v in inventories.items()}


def _typed(value: Any, hint: Any) -> bool:
    """Exact declared JSON types; bool is never int and subclasses never coerce."""
    origin, args = get_origin(hint), get_args(hint)
    if hint is Any:
        return True  # canonical_bytes separately checks the entire JSON value.
    if origin in (types.UnionType, Union):
        return any(_typed(value, arg) for arg in args)
    if origin is list:
        return type(value) is list and all(_typed(v, args[0]) for v in value)
    if origin is dict:
        return type(value) is dict and all(_typed(k, args[0]) and _typed(v, args[1]) for k, v in value.items())
    return type(value) is hint


_DEFAULT_TYPED = _typed
_CLASS_FIELD_SPECS_CACHE: dict[
    Any,
    tuple[tuple[str, ...], frozenset[str], frozenset[str], tuple[str, ...], tuple[tuple[str, bool, tuple[type, ...], Any], ...]],
] = {}


def _class_field_specs(
    cls: type[NodeConfig] | type[WorkflowConfig],
) -> tuple[tuple[str, ...], frozenset[str], frozenset[str], tuple[str, ...], tuple[tuple[str, bool, tuple[type, ...], Any], ...]]:
    cached = _CLASS_FIELD_SPECS_CACHE.get(cls)
    if cached is not None:
        return cached
    cls_fields = fields(cls)
    sorted_names = tuple(sorted(f.name for f in cls_fields))
    name_set = frozenset(sorted_names)
    non_known_set = frozenset(f.name for f in cls_fields if f.name != "_KNOWN_FIELDS")
    sorted_known = tuple(sorted(non_known_set))
    hints = get_type_hints(cls)
    specs: list[tuple[str, bool, tuple[type, ...], Any]] = []
    for f in cls_fields:
        if f.name in ("_KNOWN_FIELDS", "nodes"):
            continue
        hint = hints[f.name]
        origin, args = get_origin(hint), get_args(hint)
        branches = args if origin in (types.UnionType, Union) else (hint,)
        is_nullable = types.NoneType in branches or hint is Any
        simple = tuple(b for b in branches if b in (str, int, bool))
        specs.append((f.name, is_nullable, simple, hint))
    res = (sorted_names, name_set, non_known_set, sorted_known, tuple(specs))
    _CLASS_FIELD_SPECS_CACHE[cls] = res
    return res


def _dataclass_projection_inner(
    value: Any,
    cls: type[NodeConfig] | type[WorkflowConfig],
    inventory: list[str],
    seen_nodes: dict[int, tuple[NodeConfig, dict, bytes]] | None = None,
) -> dict:
    sorted_names, name_set, non_known_set, sorted_known, specs = _class_field_specs(cls)
    if type(value) is not cls or list(sorted_names) != inventory:
        _refuse(RefusalCode.FIELDS)
    v_vars = vars(value)
    if len(v_vars) != len(name_set) or v_vars.keys() != name_set:
        _refuse(RefusalCode.FIELDS)
    known_actual = value._KNOWN_FIELDS
    if type(known_actual) is not frozenset or known_actual != cls._KNOWN_FIELDS or cls._KNOWN_FIELDS != non_known_set:
        if any(type(k) is not str for k in known_actual) if type(known_actual) is frozenset else True:
            _refuse(RefusalCode.FIELDS)
        _refuse(RefusalCode.FIELDS)
    result: dict[str, Any] = {"_KNOWN_FIELDS": list(sorted_known)}
    actual_nodes = value.nodes
    if actual_nodes is None and cls is NodeConfig:
        result["nodes"] = None
    elif type(actual_nodes) is list:
        node_sorted_names = list(_class_field_specs(NodeConfig)[0])
        result["nodes"] = [
            _dataclass_projection_inner(n, NodeConfig, node_sorted_names, seen_nodes)
            for n in actual_nodes
        ]
    else:
        _refuse(RefusalCode.TYPE)
    fast_typed = _typed is _DEFAULT_TYPED
    for fname, is_nullable, simple_types, hint in specs:
        actual = getattr(value, fname)
        if fast_typed:
            if actual is None:
                if not is_nullable:
                    _refuse(RefusalCode.TYPE)
            elif type(actual) not in simple_types and not _typed(actual, hint):
                _refuse(RefusalCode.TYPE)
        else:
            if not _typed(actual, hint):
                _refuse(RefusalCode.TYPE)
        result[fname] = actual
    if seen_nodes is not None and cls is NodeConfig:
        seen_nodes[id(value)] = (value, result, canonical_bytes(result))
    return result


def _dataclass_projection(value: Any, cls: type[NodeConfig] | type[WorkflowConfig], inventory: list[str]) -> dict:
    result = _dataclass_projection_inner(value, cls, inventory)
    canonical_bytes(result)
    return result


_DEFAULT_DATACLASS_PROJECTION = _dataclass_projection


def project_node(config: NodeConfig, *, source: FrozenJSON) -> FrozenJSON:
    return _frozen_json(canonical_bytes(_dataclass_projection(config, NodeConfig, _current_inventory(source)["node"])))


def _project_agent_wire(config: dict) -> bytes:
    if type(config) is not dict:
        _refuse(RefusalCode.TYPE)
    # Copy only this outer mapping so alias detection still sees shared nested values.
    projected = dict(config)
    if "_KNOWN_FIELDS" in config:
        value = config["_KNOWN_FIELDS"]
        if type(value) is not frozenset or any(type(k) is not str for k in value) or value != NodeConfig._KNOWN_FIELDS:
            _refuse(RefusalCode.FIELDS)
        projected["_KNOWN_FIELDS"] = _known(NodeConfig)
    return canonical_bytes(projected)


def project_agent(config: dict) -> FrozenJSON:
    """Complete actual mapping; only engine-owned _KNOWN_FIELDS has a projection."""
    return _frozen_json(_project_agent_wire(config))


def project_graph(nodes: list[Node], workflow: WorkflowConfig, *, source: FrozenJSON) -> FrozenJSON:
    """Read actual runtime objects, including every policy, factory and config."""
    inventories = _current_inventory(source)
    use_fast_projection = _dataclass_projection is _DEFAULT_DATACLASS_PROJECTION
    seen_nodes: dict[int, tuple[NodeConfig, dict, bytes]] | None = {} if use_fast_projection else None
    if use_fast_projection:
        workflow_value = _dataclass_projection_inner(workflow, WorkflowConfig, inventories["workflow"], seen_nodes)
        workflow_wire = canonical_bytes(workflow_value)
    else:
        workflow_value = _dataclass_projection(workflow, WorkflowConfig, inventories["workflow"])
        workflow_wire = canonical_bytes(workflow_value)
    flattened: list[dict] = []

    def walk(actual: list[Node], configs: list[dict], parent: tuple[str, ...]) -> None:
        if type(actual) is not list or len(actual) != len(configs):
            _refuse(RefusalCode.GRAPH)
        for node, expected_config in zip(actual, configs, strict=True):
            if type(node) not in (AgentNode, StageNode):
                _refuse(RefusalCode.GRAPH)
            hit = seen_nodes.get(id(node.config)) if seen_nodes is not None else None
            if hit is not None and hit[0] is node.config:
                _, projected, projected_wire = hit
            else:
                projected = _dataclass_projection(node.config, NodeConfig, inventories["node"])
                projected_wire = canonical_bytes(projected)
            if (projected is not expected_config and projected_wire != canonical_bytes(expected_config)) or node.name != node.config.name:
                _refuse(RefusalCode.GRAPH)
            path = (*parent, node.name)
            factory = None
            if type(node) is AgentNode:
                if node.config.type != "agent" or node.config.nodes is not None:
                    _refuse(RefusalCode.GRAPH)
                cfg = node.agent_config
                if type(cfg) is not dict:
                    _refuse(RefusalCode.TYPE)
                kind = cfg.get("type")
                if type(kind) is not str:
                    _refuse(RefusalCode.TYPE)
                cls = {"script": ScriptAgent, "single_call": SingleCallAgent}.get(kind)
                if cls is None or AGENT_TYPES.get(kind) is not cls:
                    _refuse(RefusalCode.SOURCE)
                if kind == "single_call" and SingleCallAgent(cfg).validate_config():
                    _refuse(RefusalCode.FIELDS)
                factory = {"type": kind, "class_name": f"{cls.__module__}.{cls.__qualname__}",
                           "config_json": _project_agent_wire(cfg).decode("utf-8")}
            elif node.config.type != "stage" or projected["nodes"] is None:
                _refuse(RefusalCode.GRAPH)
            flattened.append({"path": list(path), "node_json": projected_wire.decode("utf-8"),
                              "factory": factory})
            if type(node) is StageNode:
                walk(node.child_nodes, projected["nodes"], path)

    walk(nodes, workflow_value["nodes"], ())
    return _frozen_json(canonical_bytes({"workflow_json": workflow_wire.decode("utf-8"),
                                         "nodes": flattened}))


def _unwrapped(raw: dict, kind: str, version: str) -> dict:
    if version != SUPPORTED_SCHEMA_VERSION:
        _refuse(RefusalCode.VERSION)
    if "schema_version" in raw and (type(raw["schema_version"]) is not str or raw["schema_version"] != version):
        _refuse(RefusalCode.VERSION)
    if kind in raw:
        if set(raw) - {kind, "schema_version"} or type(raw[kind]) is not dict:
            _refuse(RefusalCode.SCHEMA)
        return raw[kind]
    return {k: v for k, v in raw.items() if k != "schema_version"}


def _markers(value: Any, *, template: str | None = None) -> None:
    if type(value) is str:
        if value != template and any(marker in value for marker in _MARKERS):
            _refuse(RefusalCode.SCHEMA)
    elif type(value) is dict:
        for k, v in value.items():
            _markers(k)
            if k == "_KNOWN_FIELDS":
                _refuse(RefusalCode.FIELDS)
            _markers(v)
    elif type(value) is list:
        for v in value:
            _markers(v)


def _script(template: Any, expected: list[dict]) -> None:
    if type(template) is not str or not any(s["template_utf8"] == template for s in expected):
        _refuse(RefusalCode.GRAPH)
    rest = _INTERPOLATION.sub("", template)
    _markers(rest)
    names = {m.group(1) for m in _INTERPOLATION.finditer(template)}
    for spec in (s for s in expected if s["template_utf8"] == template):
        variables = FrozenJSON(spec["variables_json"].encode("utf-8")).value()
        if not names <= variables.keys() or any(type(v) not in (str, int, float, bool, type(None)) for v in variables.values()):
            _refuse(RefusalCode.SCHEMA)
        _markers(variables)
    try:
        _rewrite_interpolations(template, "admitted-script")
    except Exception:
        _refuse(RefusalCode.SCHEMA)


def _raw_fields(data: dict, cls: type[NodeConfig] | type[WorkflowConfig]) -> None:
    if set(data) - set(_known(cls)):
        _refuse(RefusalCode.FIELDS)
    hints = get_type_hints(cls)
    for key, value in data.items():
        if key == "nodes":
            if type(value) is not list:
                _refuse(RefusalCode.TYPE)
        elif key in ("undoes", "renamed_from") and type(value) is str:
            pass  # Documented ordinary shorthand, not arbitrary str() coercion.
        elif not _typed(value, hints[key]):
            _refuse(RefusalCode.TYPE)
    if type(data.get("name")) is not str or not _NAME.fullmatch(data["name"]):
        _refuse(RefusalCode.SCHEMA)


def validate_raw(resolver: SnapshotResolver, descriptor: ApprovedCandidateDescriptor) -> None:
    """Scan ALL raw data before loading; then check reachable typed closure."""
    d = descriptor.value()
    configs: dict[tuple[str, str], dict] = {}
    for record in resolver.closure.records:
        v = record.value()
        key = record.key
        raw = resolver.get(key[1], key[0])
        body = _unwrapped(raw, key[0], v["schema_version"])
        # The exception is ONLY this exact field on an actual script-agent
        # record. Identical text in another key/unknown/default still refuses.
        if key[0] == "agent" and body.get("type") == "script" and "script_template" in body:
            _script(body["script_template"], d["scripts"])
            for k, value in raw.items():
                if k == "agent":
                    _markers({n: x for n, x in body.items() if n != "script_template"})
                elif k != "script_template":
                    _markers({k: value})
        else:
            _markers(raw)
        if body.get("name") != key[1]:
            _refuse(RefusalCode.CLOSURE)
        configs[key] = body
    _markers(FrozenJSON(d["metadata_inputs_json"].encode("utf-8")).value())
    _markers(FrozenJSON(d["request_options_json"].encode("utf-8")).value())
    visited: set[tuple[str, str]] = set()
    active: set[tuple[str, str]] = set()

    def reference(ref: Any, kinds: dict[str, str]) -> tuple[str, str]:
        if type(ref) is not str or ref.count("/") != 1:
            _refuse(RefusalCode.CLOSURE)
        prefix, name = ref.split("/")
        if prefix not in kinds or not _NAME.fullmatch(name):
            _refuse(RefusalCode.CLOSURE)
        return kinds[prefix], name

    def node(raw: dict) -> None:
        if type(raw) is not dict:
            _refuse(RefusalCode.TYPE)
        _raw_fields(raw, NodeConfig)
        # Eligibility is separate from wire/graph equality: even an explicitly
        # approved null setting is prohibited raw presence in this profile.
        if any(k in raw for k in ("strategy", "strategy_config", "agents", "tools", "memory")):
            _refuse(RefusalCode.SCHEMA)
        # A count/default without a target is inert, not an active loop. Keep
        # on_failure/undoes (cleanup metadata) separate from LLM fallback.
        if raw.get("loop_to") is not None:
            _refuse(RefusalCode.SCHEMA)
        kind = raw.get("type", "agent")
        if "ref" in raw:
            if kind != "stage" or any(k in raw for k in ("nodes", "agent")):
                _refuse(RefusalCode.SCHEMA)
            target = reference(raw["ref"], {"stages": "stage", "workflows": "workflow"})
            if target[0] == "workflow" and target in configs:
                referred = configs[target]
                # These workflow-only behaviors cannot survive use as a node.
                if (referred.get("defaults") or set(referred) - set(_known(NodeConfig))
                        - {"description", "version", "defaults"}):
                    _refuse(RefusalCode.SCHEMA)
            visit(target)
        elif kind == "stage":
            if "agent" in raw or not raw.get("nodes"):
                _refuse(RefusalCode.SCHEMA)
            for child in raw["nodes"]:
                node(child)
        elif kind == "agent":
            if "nodes" in raw:
                _refuse(RefusalCode.SCHEMA)
            visit(reference(raw.get("agent"), {"agents": "agent"}))
        else:
            _refuse(RefusalCode.SCHEMA)

    def visit(key: tuple[str, str]) -> None:
        if key in active:
            _refuse(RefusalCode.CLOSURE)
        if key not in configs:
            _refuse(RefusalCode.LOOKUP)
        if key in visited:
            return
        active.add(key)
        body = configs[key]
        if key[0] == "agent":
            kind = body.get("type")
            allowed = _SCRIPT_KEYS if kind == "script" else SINGLE_CALL_AGENT_SETTINGS
            if kind not in ("script", "single_call") or set(body) - allowed:
                _refuse(RefusalCode.FIELDS)
            for k in ("name", "type", "description", "provider", "model", "script_template"):
                if k in body and type(body[k]) is not str:
                    _refuse(RefusalCode.TYPE)
            if kind == "single_call":
                fixed = body.get("single_call")
                if (type(fixed) is not dict or set(fixed) - SINGLE_CALL_SETTINGS
                        or not SINGLE_CALL_REQUIRED <= fixed.keys()):
                    _refuse(RefusalCode.FIELDS)
                for name, value in fixed.items():
                    if name in {"prompt_bytes", "max_tokens", "deadline_s", "thinking_budget"}:
                        ok = type(value) is int
                    elif name in {"cost_cap_usd", "temperature"}:
                        ok = type(value) in ((str, int, float) if name == "cost_cap_usd" else (int, float))
                    elif name == "thinking":
                        # Native provider syntax remains its runtime defense;
                        # admission preserves the entire JSON object or token.
                        ok = type(value) in (str, dict)
                    else:
                        ok = type(value) is str
                    if not ok:
                        _refuse(RefusalCode.TYPE)
                if SingleCallAgent(body).validate_config():
                    _refuse(RefusalCode.SCHEMA)
            else:
                if "script_template" not in body:
                    _refuse(RefusalCode.SCHEMA)
                for k, typ in (("strict_undefined", bool), ("timeout_seconds", int), ("log_max_bytes", int)):
                    if k in body and type(body[k]) is not typ:
                        _refuse(RefusalCode.TYPE)
        else:
            cls = WorkflowConfig if key[0] == "workflow" else NodeConfig
            _raw_fields(body, cls)
            if key[0] == "workflow":
                if body.get("starts_runs") is True or "memory" in body:
                    _refuse(RefusalCode.SCHEMA)
                defaults = body.get("defaults")
                if defaults is not None:
                    if set(defaults) - _DEFAULT_KEYS:
                        _refuse(RefusalCode.FIELDS)
                    for k, v in defaults.items():
                        if not _typed(v, get_type_hints(NodeConfig)[k]):
                            _refuse(RefusalCode.TYPE)
                for child in body.get("nodes", []):
                    node(child)
            else:
                node({"type": "stage", **body})
        active.remove(key)
        visited.add(key)

    visit(("workflow", d["workflow_name"]))
    if visited != configs.keys():
        _refuse(RefusalCode.CLOSURE)


class _SnapshotLoader(GraphLoader):
    """No stage/workflow fallback. All lookups use the same closed resolver."""

    def __init__(self, resolver: SnapshotResolver):
        super().__init__(resolver)

    def _load_referenced_graph(self, ref: str) -> dict:
        prefix = ref.split("/")[0]
        kind = {"stages": "stage", "workflows": "workflow"}.get(prefix)
        if kind is None:
            _refuse(RefusalCode.LOOKUP)
        return self._strip_graph_metadata(self._load_config(ref, kind), ref)

    def _resolve_explicit_stage(self, nc: NodeConfig) -> StageNode:
        stage = super()._resolve_explicit_stage(nc)
        stage.config = replace(nc, nodes=[n.config for n in stage.child_nodes])
        return stage


def load_candidate(
    codec: ContractCodec, descriptor: ApprovedCandidateDescriptor, closure: RawClosure, *,
    authority: DescriptorAuthority, source: FrozenJSON,
) -> tuple[list[Node], WorkflowConfig, FrozenJSON]:
    """Fresh snapshot-only structural load and exact complete independent comparison.

    Return actual nodes, resolved WorkflowConfig and owned graph projection.
    This is not a T2 transport install or a T3 invocation/claim authorization.
    """
    memoize_codec(codec)
    approved = codec.descriptor(descriptor.wire, authority)
    require_source(approved, source)
    _current_inventory(source)
    resolver = SnapshotResolver(codec, approved, closure.records, authority=authority)
    validate_raw(resolver, approved)
    d = approved.value()
    inputs = FrozenJSON(d["metadata_inputs_json"].encode("utf-8")).value()
    try:
        nodes, workflow = _SnapshotLoader(resolver).load_workflow(d["workflow_name"], inputs, run_start=True)
        # Ordinary ref resolution replaces NodeConfig objects. The candidate
        # WorkflowConfig describes those ACTUAL resolved objects, not stale refs.
        workflow = replace(workflow, nodes=[node.config for node in nodes])
        if canonical_bytes(fill_input_defaults(workflow.inputs, inputs)) != canonical_bytes(inputs):
            _refuse(RefusalCode.GRAPH)
        actual = project_graph(nodes, workflow, source=source)
    except (StageError, KeyError, TypeError, ValueError, RecursionError):
        _refuse(RefusalCode.GRAPH)
    if actual.wire != canonical_bytes(d["graph"]):
        _refuse(RefusalCode.GRAPH)
    return nodes, workflow, actual
