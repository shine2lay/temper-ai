"""Candidate-only raw policy and actual snapshot-resolved projections.

The ordinary loader is unchanged. This module performs no registration, start,
provider call, file acquisition, custody check or source discovery. The caller
supplies independent descriptor authority AND measured installed-source facts.
"""
from __future__ import annotations

import re
import types
from dataclasses import fields, replace
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
    AdmissionRefused,
    ApprovedCandidateDescriptor,
    ContractCodec,
    DescriptorAuthority,
    FrozenJSON,
    RawClosure,
    RefusalCode,
    canonical_bytes,
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


def _current_inventory(source: FrozenJSON) -> dict:
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
    return inventories


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


def _dataclass_projection(value: Any, cls: type[NodeConfig] | type[WorkflowConfig], inventory: list[str]) -> dict:
    if (type(value) is not cls or sorted(f.name for f in fields(cls)) != inventory
            or sorted(vars(value)) != inventory):
        _refuse(RefusalCode.FIELDS)
    result: dict[str, Any] = {}
    hints = get_type_hints(cls)
    for f in fields(cls):
        actual = getattr(value, f.name)
        if f.name == "_KNOWN_FIELDS":
            if type(actual) is not frozenset or any(type(k) is not str for k in actual) or actual != cls._KNOWN_FIELDS:
                _refuse(RefusalCode.FIELDS)
            result[f.name] = _known(cls)
        elif f.name == "nodes":
            if actual is None and cls is NodeConfig:
                result[f.name] = None
            elif type(actual) is list:
                result[f.name] = [_dataclass_projection(n, NodeConfig, sorted(f.name for f in fields(NodeConfig)))
                                  for n in actual]
            else:
                _refuse(RefusalCode.TYPE)
        else:
            if not _typed(actual, hints[f.name]):
                _refuse(RefusalCode.TYPE)
            result[f.name] = actual
    canonical_bytes(result)
    return result


def project_node(config: NodeConfig, *, source: FrozenJSON) -> FrozenJSON:
    return FrozenJSON(canonical_bytes(_dataclass_projection(config, NodeConfig, _current_inventory(source)["node"])))


def project_agent(config: dict) -> FrozenJSON:
    """Complete actual mapping; only engine-owned _KNOWN_FIELDS has a projection."""
    if type(config) is not dict:
        _refuse(RefusalCode.TYPE)
    # Copy only this outer mapping so alias detection still sees shared nested values.
    projected = dict(config)
    if "_KNOWN_FIELDS" in config:
        value = config["_KNOWN_FIELDS"]
        if type(value) is not frozenset or any(type(k) is not str for k in value) or value != NodeConfig._KNOWN_FIELDS:
            _refuse(RefusalCode.FIELDS)
        projected["_KNOWN_FIELDS"] = _known(NodeConfig)
    return FrozenJSON(canonical_bytes(projected))


def project_graph(nodes: list[Node], workflow: WorkflowConfig, *, source: FrozenJSON) -> FrozenJSON:
    """Read actual runtime objects, including every policy, factory and config."""
    inventories = _current_inventory(source)
    workflow_value = _dataclass_projection(workflow, WorkflowConfig, inventories["workflow"])
    flattened: list[dict] = []

    def walk(actual: list[Node], configs: list[dict], parent: tuple[str, ...]) -> None:
        if type(actual) is not list or len(actual) != len(configs):
            _refuse(RefusalCode.GRAPH)
        for node, expected_config in zip(actual, configs, strict=True):
            if type(node) not in (AgentNode, StageNode):
                _refuse(RefusalCode.GRAPH)
            projected = _dataclass_projection(node.config, NodeConfig, inventories["node"])
            if canonical_bytes(projected) != canonical_bytes(expected_config) or node.name != node.config.name:
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
                           "config_json": project_agent(cfg).wire.decode("utf-8")}
            elif node.config.type != "stage" or projected["nodes"] is None:
                _refuse(RefusalCode.GRAPH)
            flattened.append({"path": list(path), "node_json": canonical_bytes(projected).decode("utf-8"),
                              "factory": factory})
            if type(node) is StageNode:
                walk(node.child_nodes, projected["nodes"], path)

    walk(nodes, workflow_value["nodes"], ())
    return FrozenJSON(canonical_bytes({"workflow_json": canonical_bytes(workflow_value).decode("utf-8"),
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
