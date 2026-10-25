"""Inert candidate wire v1. No resolver, database, provider, or filesystem I/O.

Pass the shipped schema bytes explicitly: this keeps one authoritative wire
schema and lets the metadata compiler use this module by file location without
importing config/__init__.py (which imports the ordinary store). Neither a wire
value nor DescriptorAuthority grants access or authorizes execution.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, NoReturn, Protocol, TypeVar

SCHEMA_SHA256 = "426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d"
RESERVED_KEY = "config_admission"
SUPPORTED_MODE = "external-db-fresh"


class RefusalCode(StrEnum):
    JSON = "invalid_json"
    TYPE = "invalid_type"
    ALIAS = "aliased_or_cyclic_value"
    NONFINITE = "nonfinite_number"
    DUPLICATE = "duplicate_key"
    CANONICAL = "noncanonical_bytes"
    SCHEMA = "wire_schema"
    VERSION = "unsupported_version"
    MODE = "unsupported_mode"
    DIGEST = "digest_mismatch"
    ORIGIN = "source_origin"
    AUTHORITY = "descriptor_authority"
    SOURCE = "source_drift"
    FIELDS = "field_set_drift"
    CLOSURE = "closure_mismatch"
    GRAPH = "graph_mismatch"
    POSITION = "position_mismatch"
    PROTECTED = "protected_metadata"
    GENERATION = "dispatch_generation"
    READINESS = "root_readiness"
    CUSTODY = "unresolved_custody"
    ROLLBACK = "rollback_fence"
    MISSING = "admission_required"
    LOOKUP = "outside_closure"


class AdmissionRefused(Exception):
    """Export only .code / str(exc), never parser exceptions or rejected data."""

    def __init__(self, code: RefusalCode):
        self.code = code
        super().__init__(code.value)


def _fail(code: RefusalCode) -> NoReturn:
    raise AdmissionRefused(code) from None


class DigestDomain(StrEnum):
    DESCRIPTOR = "descriptor"
    RAW_RECORD = "raw-record"
    RAW_CLOSURE = "raw-closure"
    GRAPH = "graph"
    SOURCE = "source"
    IMMUTABLE = "immutable"
    READINESS = "readiness"


def canonical_bytes(value: Any) -> bytes:
    """CAJ-1: scalar-key-sorted UTF-8 JSON; exact finite binary64 decimals.

    Exact built-in types only. Shared mutable containers, cycles and surrogates
    refuse. Floats retain a decimal point, so 1, 1.0 and true stay distinct.
    See docs/candidate-admission-contract.md for the language-neutral algorithm.
    """
    seen: set[int] = set()

    def encode(v: Any) -> str:
        t = type(v)
        if v is None:
            return "null"
        if t is bool:
            return "true" if v else "false"
        if t is int:
            return str(v)
        if t is float:
            if not math.isfinite(v):
                _fail(RefusalCode.NONFINITE)
            s = format(Decimal.from_float(v), "f")
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s if "." in s else s + ".0"
        if t is str:
            return json.dumps(v, ensure_ascii=False)
        if t not in (dict, list):
            _fail(RefusalCode.TYPE)
        if id(v) in seen:
            _fail(RefusalCode.ALIAS)
        seen.add(id(v))
        if t is list:
            return "[" + ",".join(encode(item) for item in v) + "]"
        if any(type(k) is not str for k in v):
            _fail(RefusalCode.TYPE)
        return "{" + ",".join(encode(k) + ":" + encode(v[k]) for k in sorted(v)) + "}"

    try:
        return encode(value).encode("utf-8", errors="strict")
    except (UnicodeError, ValueError, RecursionError):
        _fail(RefusalCode.JSON)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(RefusalCode.DUPLICATE)
        result[key] = value
    return result


def _parse(data: bytes) -> Any:
    if type(data) is not bytes:
        _fail(RefusalCode.TYPE)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: _fail(RefusalCode.NONFINITE))
    except (UnicodeError, ValueError, RecursionError):
        _fail(RefusalCode.JSON)


def decode_canonical(data: bytes) -> Any:
    value = _parse(data)
    if canonical_bytes(value) != data:
        _fail(RefusalCode.CANONICAL)
    return value


def digest(domain: DigestDomain, data: bytes) -> str:
    """SHA256(b'temper-admission/v1\\0' + ASCII(domain) + b'\\0' + CAJ-1)."""
    if type(domain) is not DigestDomain:
        _fail(RefusalCode.TYPE)
    decode_canonical(data)
    return hashlib.sha256(b"temper-admission/v1\0" + domain.value.encode("ascii")
                          + b"\0" + data).hexdigest()


def _hash_matches(actual: str, expected: str, code: RefusalCode = RefusalCode.DIGEST) -> None:
    if type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
        _fail(code)


def _object(text: str) -> dict[str, Any]:
    value = decode_canonical(text.encode("utf-8"))
    if type(value) is not dict:
        _fail(RefusalCode.TYPE)
    return value


def _path(path: str, *, absolute: bool = True) -> None:
    parts = path.split("/")
    if (path.startswith("/") != absolute or "\0" in path
            or any(p in ("", ".", "..") for p in (parts[1:] if absolute else parts))):
        _fail(RefusalCode.ORIGIN)


@dataclass(frozen=True, slots=True)
class FrozenJSON:
    """Own bytes, never caller mappings; each .value() is an independent parse."""

    wire: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(decode_canonical(self.wire)) is not dict:
            _fail(RefusalCode.TYPE)

    def value(self) -> dict[str, Any]:
        value = decode_canonical(self.wire)
        if type(value) is not dict:
            _fail(RefusalCode.TYPE)
        return value


@dataclass(frozen=True, slots=True)
class DescriptorAuthority:
    """Out-of-band pins from the EXISTING authorized caller; not wire-supplied.

    Caller authentication and receipt verification are the adapter's job. A
    public Python constructor is deliberately not a security capability.
    """

    expected_descriptor_sha256: str
    expected_source_sha256: str
    authorized_caller_label: str
    receipt_id: str


@dataclass(frozen=True, slots=True)
class ApprovedCandidateDescriptor(FrozenJSON):
    authority: DescriptorAuthority = field(repr=False)

    @property
    def sha256(self) -> str:
        return digest(DigestDomain.DESCRIPTOR, self.wire)


@dataclass(frozen=True, slots=True)
class RawRecord(FrozenJSON):
    @property
    def key(self) -> tuple[str, str]:
        v = self.value()
        return v["kind"], v["name"]

    @property
    def sha256(self) -> str:
        v = self.value()
        # Identity binds pre-substitution JSON plus schema and origin, not
        # nonexistent original YAML for DB rows. Exact files bind via origin.
        identity = {k: v[k] for k in ("kind", "name", "schema_version", "origin", "config_json")}
        return digest(DigestDomain.RAW_RECORD, canonical_bytes(identity))


@dataclass(frozen=True, slots=True)
class RawClosure:
    records: tuple[RawRecord, ...]

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(type(r) is not RawRecord for r in self.records):
            _fail(RefusalCode.TYPE)
        keys = [r.key for r in self.records]
        if not keys or keys != sorted(set(keys)):
            _fail(RefusalCode.CLOSURE)

    @property
    def sha256(self) -> str:
        return digest(DigestDomain.RAW_CLOSURE, canonical_bytes([r.value() for r in self.records]))

    def get(self, kind: str, name: str) -> dict[str, Any]:
        for record in self.records:
            if record.key == (kind, name):
                return _object(record.value()["config_json"])
        _fail(RefusalCode.LOOKUP)


@dataclass(frozen=True, slots=True)
class AdmissionRecord(FrozenJSON):
    """Transport data only; not proof of adapter enforcement or custody."""


@dataclass(frozen=True, slots=True)
class RootReadiness(FrozenJSON):
    """Measured metadata, not proof its producer was authorized."""


# Only the supplied, pinned schema defines the wire object shapes. This small
# interpreter implements exactly the keywords used by that artifact, no remote
# $ref resolution, coercion, defaults, plugin formats or arbitrary callbacks.
def _validate(value: Any, rule: dict, schema: dict) -> None:
    if "$ref" in rule:
        return _validate(value, schema["$defs"][rule["$ref"].removeprefix("#/$defs/")], schema)
    if "oneOf" in rule:
        matches = 0
        for branch in rule["oneOf"]:
            try:
                _validate(value, branch, schema)
                matches += 1
            except AdmissionRefused:
                pass
        if matches != 1:
            _fail(RefusalCode.SCHEMA)
        return
    if "const" in rule and canonical_bytes(value) != canonical_bytes(rule["const"]):
        _fail(RefusalCode.SCHEMA)
    if "enum" in rule and canonical_bytes(value) not in [canonical_bytes(v) for v in rule["enum"]]:
        _fail(RefusalCode.SCHEMA)
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if "type" in rule:
        allowed = rule["type"] if type(rule["type"]) is list else [rule["type"]]
        if type(value) not in [types[t] for t in allowed]:
            _fail(RefusalCode.SCHEMA)
    if type(value) is dict and "properties" in rule:
        if set(value) - rule["properties"].keys() or not set(rule["required"]) <= value.keys():
            _fail(RefusalCode.SCHEMA)
        for k, v in value.items():
            _validate(v, rule["properties"][k], schema)
    if type(value) is list:
        if len(value) < rule.get("minItems", 0):
            _fail(RefusalCode.SCHEMA)
        if rule.get("uniqueItems") and len({canonical_bytes(v) for v in value}) != len(value):
            _fail(RefusalCode.SCHEMA)
        for v in value:
            _validate(v, rule.get("items", {}), schema)
    if type(value) is str:
        if len(value) < rule.get("minLength", 0) or ("pattern" in rule and not re.fullmatch(rule["pattern"], value)):
            _fail(RefusalCode.SCHEMA)
    if type(value) is int:
        if ("minimum" in rule and value < rule["minimum"]) or ("maximum" in rule and value > rule["maximum"]):
            _fail(RefusalCode.SCHEMA)


class ContractCodec:
    """Reference parser/validator; reads no files, DB rows, environment or APIs."""

    def __init__(self, schema_bytes: bytes):
        if type(schema_bytes) is not bytes:
            _fail(RefusalCode.TYPE)
        _hash_matches(hashlib.sha256(schema_bytes).hexdigest(), SCHEMA_SHA256)
        self._schema_bytes = bytes(schema_bytes)

    def validate_shape(self, value: Any, definition: str) -> None:
        schema = _parse(self._schema_bytes)
        if definition not in schema["$defs"]:
            _fail(RefusalCode.SCHEMA)
        # Own before validation; reject non-JSON values/aliases even in extra fields.
        owned = decode_canonical(canonical_bytes(value))
        if definition in ("descriptor", "rawRecord", "record", "readiness"):
            expected_format = schema["$defs"][definition]["properties"]["format"]["const"]
            if type(owned) is dict and "format" in owned and owned["format"] != expected_format:
                _fail(RefusalCode.VERSION)
        if definition == "descriptor" and type(owned) is dict and "mode" in owned:
            require_mode(owned["mode"])
        _validate(owned, schema["$defs"][definition], schema)

    def raw_record(self, data: bytes) -> RawRecord:
        v = decode_canonical(data)
        self.validate_shape(v, "rawRecord")
        _object(v["config_json"])
        origin = v["origin"]
        if origin["kind"] == "db":
            if v["file_base64"] is not None:
                _fail(RefusalCode.ORIGIN)
        else:
            _path(origin["relative_path"], absolute=False)
            try:
                raw = base64.b64decode(v["file_base64"], validate=True)
            except (ValueError, TypeError):
                _fail(RefusalCode.ORIGIN)
            if base64.b64encode(raw).decode("ascii") != v["file_base64"]:
                _fail(RefusalCode.ORIGIN)
            _hash_matches(hashlib.sha256(raw).hexdigest(), origin["file_sha256"])
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
            if blob != origin["git_blob_sha1"]:
                _fail(RefusalCode.DIGEST)
        return RawRecord(data)

    def descriptor(self, data: bytes, authority: DescriptorAuthority) -> ApprovedCandidateDescriptor:
        if type(authority) is not DescriptorAuthority or any(
            type(s) is not str or not s for s in (authority.authorized_caller_label, authority.receipt_id)
        ):
            _fail(RefusalCode.AUTHORITY)
        v = decode_canonical(data)
        self.validate_shape(v, "descriptor")
        _hash_matches(digest(DigestDomain.DESCRIPTOR, data), authority.expected_descriptor_sha256,
                      RefusalCode.AUTHORITY)
        _hash_matches(digest(DigestDomain.SOURCE, canonical_bytes(v["source"])),
                      authority.expected_source_sha256, RefusalCode.SOURCE)
        self._descriptor_semantics(v)
        return ApprovedCandidateDescriptor(data, authority)

    def _descriptor_semantics(self, v: dict) -> None:
        _path(v["workspace_path"])
        _object(v["metadata_inputs_json"])
        options = _object(v["request_options_json"])
        fields = v["source"]["field_sets"]
        for names in fields.values():
            if names != sorted(names):
                _fail(RefusalCode.FIELDS)
        if sorted(options) != fields["request"]:
            _fail(RefusalCode.FIELDS)
        keys = [(r["kind"], r["name"]) for r in v["records"]]
        if keys != sorted(set(keys)) or ("workflow", v["workflow_name"]) not in keys:
            _fail(RefusalCode.CLOSURE)
        # Classified raw records have a codec, not a newly enabled start route.
        if any(r["origin"]["kind"] != "db" for r in v["records"]):
            _fail(RefusalCode.MODE)
        workflow = _object(v["graph"]["workflow_json"])
        if sorted(workflow) != fields["workflow"]:
            _fail(RefusalCode.FIELDS)
        if workflow.get("name") != v["workflow_name"]:
            _fail(RefusalCode.GRAPH)
        flattened: list[tuple[tuple[str, ...], bytes]] = []

        def walk(nodes: Any, parent: tuple[str, ...]) -> None:
            if type(nodes) is not list:
                _fail(RefusalCode.GRAPH)
            for n in nodes:
                if type(n) is not dict or sorted(n) != fields["node"]:
                    _fail(RefusalCode.FIELDS)
                if type(n.get("name")) is not str:
                    _fail(RefusalCode.GRAPH)
                path = (*parent, n["name"])
                flattened.append((path, canonical_bytes(n)))
                if n.get("nodes") is not None:
                    walk(n["nodes"], path)

        walk(workflow.get("nodes"), ())
        actual = [(tuple(n["path"]), n["node_json"].encode("utf-8")) for n in v["graph"]["nodes"]]
        if actual != flattened or len({p for p, _ in actual}) != len(actual):
            _fail(RefusalCode.GRAPH)
        nodes_by_path = {tuple(n["path"]): n for n in v["graph"]["nodes"]}
        calls: set[tuple[str, ...]] = set()
        scripts: set[tuple[str, ...]] = set()
        for n in nodes_by_path.values():
            node = _object(n["node_json"])
            factory = n["factory"]
            if node.get("type") == "stage":
                if factory is not None:
                    _fail(RefusalCode.GRAPH)
            elif node.get("type") == "agent" and factory is not None:
                cfg = _object(factory["config_json"])
                if cfg.get("type") != factory["type"]:
                    _fail(RefusalCode.GRAPH)
                (calls if factory["type"] == "single_call" else scripts).add(tuple(n["path"]))
            else:
                _fail(RefusalCode.GRAPH)
        position_paths: list[tuple[str, ...]] = []
        positions: set[str] = set()
        claims: set[tuple[str, str]] = set()
        for p in v["positions"]:
            path = tuple(p["node_path"])
            if path not in calls or tuple(p["preparation_path"]) not in scripts or p["position_id"] in positions:
                _fail(RefusalCode.POSITION)
            position_paths.append(path)
            positions.add(p["position_id"])
            if p["agent_config_json"] != nodes_by_path[path]["factory"]["config_json"]:
                _fail(RefusalCode.POSITION)
            cfg = _object(p["agent_config_json"])
            native = cfg.get("single_call")
            if type(native) is not dict or set(native) - set(fields["native"]) or native.get("slot") != p["slot"]:
                _fail(RefusalCode.POSITION)
            output_root = native.get("output_root")
            if type(output_root) is not str:
                _fail(RefusalCode.POSITION)
            _path(output_root)
            claim = (output_root, p["slot"])
            if claim in claims:
                _fail(RefusalCode.POSITION)
            claims.add(claim)
            root = p["root_policy"]
            if root is not None:
                _path(root["path"])
                _path(root["permitted_parent"])
                if (native.get("output_root") != root["path"]
                        or not root["path"].startswith(root["permitted_parent"] + "/")):
                    _fail(RefusalCode.POSITION)
        if len(position_paths) != len(calls) or set(position_paths) != calls:
            _fail(RefusalCode.POSITION)
        script_paths = []
        for s in v["scripts"]:
            path = tuple(s["node_path"])
            if path not in scripts:
                _fail(RefusalCode.GRAPH)
            script_paths.append(path)
            cfg = _object(nodes_by_path[path]["factory"]["config_json"])
            if cfg.get("script_template") != s["template_utf8"]:
                _fail(RefusalCode.GRAPH)
            _hash_matches(hashlib.sha256(s["template_utf8"].encode("utf-8")).hexdigest(), s["template_sha256"])
            _object(s["variables_json"])
        if len(script_paths) != len(scripts) or set(script_paths) != scripts:
            _fail(RefusalCode.GRAPH)

    def closure(self, descriptor: ApprovedCandidateDescriptor, records: tuple[RawRecord, ...]) -> RawClosure:
        # Revalidate wrappers; constructing a dataclass is not admission.
        d = self.descriptor(descriptor.wire, descriptor.authority).value()
        closure = RawClosure(tuple(self.raw_record(r.wire) for r in records))
        expected = d["records"]
        if len(expected) != len(records):
            _fail(RefusalCode.CLOSURE)
        for r, e in zip(closure.records, expected, strict=True):
            value = r.value()
            if any(canonical_bytes(value[k]) != canonical_bytes(e[k])
                   for k in ("kind", "name", "schema_version", "origin")):
                _fail(RefusalCode.CLOSURE)
            _hash_matches(r.sha256, e["raw_sha256"])
        return closure

    def readiness(self, data: bytes) -> RootReadiness:
        v = decode_canonical(data)
        self.validate_shape(v, "readiness")
        for stat in [v["root"], *v["parents"], *(f["stat"] for f in v["files"])]:
            _path(stat["path"])
        return RootReadiness(data)

    def record(self, data: bytes, authority: DescriptorAuthority) -> AdmissionRecord:
        v = decode_canonical(data)
        self.validate_shape(v, "record")
        immutable = v["immutable"]
        d = self.descriptor(immutable["descriptor_json"].encode("utf-8"), authority)
        dv = d.value()
        if (immutable["authorized_caller_label"] != authority.authorized_caller_label
                or immutable["authority_receipt_id"] != authority.receipt_id):
            _fail(RefusalCode.AUTHORITY)
        _hash_matches(d.sha256, immutable["descriptor_sha256"])
        closure = self.closure(d, tuple(self.raw_record(canonical_bytes(r)) for r in immutable["raw_records"]))
        _hash_matches(closure.sha256, immutable["raw_closure_sha256"])
        graph_sha = digest(DigestDomain.GRAPH, canonical_bytes(dv["graph"]))
        _hash_matches(graph_sha, immutable["effective_graph_sha256"])
        _hash_matches(digest(DigestDomain.IMMUTABLE, canonical_bytes(immutable)), v["immutable_sha256"])
        dispatch = v["dispatch"]
        if dispatch["phase"] == "queued":
            if (dispatch["running_attempt"] != 0 or dispatch["previous_nonce"] is not None
                    or dispatch["worker_label"] is not None or v["readiness"]):
                _fail(RefusalCode.GENERATION)
        elif (dispatch["running_attempt"] < 1 or dispatch["previous_nonce"] is None
              or dispatch["previous_nonce"] == dispatch["dispatch_nonce"] or not dispatch["worker_label"]):
            _fail(RefusalCode.GENERATION)
        positions = {p["position_id"]: p for p in dv["positions"]}
        seen = set()
        for r in v["readiness"]:
            self.readiness(canonical_bytes(r))
            p = positions.get(r["position_id"])
            if p is None or p["root_policy"] is None or r["position_id"] in seen:
                _fail(RefusalCode.READINESS)
            seen.add(r["position_id"])
            if (r["preparation_path"] != p["preparation_path"] or r["descriptor_sha256"] != d.sha256
                    or r["graph_sha256"] != graph_sha or r["execution_uuid"] != dv["execution_uuid"]
                    or r["dispatch_nonce"] != dispatch["dispatch_nonce"]
                    or r["running_attempt"] != dispatch["running_attempt"]):
                _fail(RefusalCode.READINESS)
            policy, root = p["root_policy"], r["root"]
            if (root["path"] != policy["path"] or root["uid"] != policy["creator_uid"]
                    or root["gid"] != policy["creator_gid"] or root["mode"] != policy["directory_mode"]
                    or dispatch["worker_label"] != policy["worker_label"]):
                _fail(RefusalCode.READINESS)
        return AdmissionRecord(data)


def require_mode(mode: str) -> None:
    if type(mode) is not str or mode != SUPPORTED_MODE:
        _fail(RefusalCode.MODE)


def require_source(descriptor: ApprovedCandidateDescriptor, actual_source: FrozenJSON) -> None:
    if canonical_bytes(descriptor.value()["source"]) != actual_source.wire:
        _fail(RefusalCode.SOURCE)


def require_custody(descriptor: ApprovedCandidateDescriptor) -> None:
    if any(p["root_policy"] is None for p in descriptor.value()["positions"]):
        _fail(RefusalCode.CUSTODY)


def require_admission(*, designated_candidate: bool, has_record: bool, supported_code: bool) -> None:
    """Compatibility predicate only; adapters must call BEFORE legacy loading."""
    if any(type(v) is not bool for v in (designated_candidate, has_record, supported_code)):
        _fail(RefusalCode.TYPE)
    if has_record and not supported_code:
        _fail(RefusalCode.ROLLBACK)
    if designated_candidate and not has_record:
        _fail(RefusalCode.MISSING)


def check_preserved(before: AdmissionRecord, after: AdmissionRecord) -> None:
    """No untyped metadata writer may change ANY part of the reserved slot."""
    if before.wire != after.wire:
        _fail(RefusalCode.PROTECTED)


def check_dispatch_transition(before: AdmissionRecord, after: AdmissionRecord) -> None:
    """Pure proposal check; caller must CAS the actual row in one transaction."""
    b, a = before.value(), after.value()
    if canonical_bytes(b["immutable"]) != canonical_bytes(a["immutable"]) or b["immutable_sha256"] != a["immutable_sha256"]:
        _fail(RefusalCode.PROTECTED)
    old, new = b["dispatch"], a["dispatch"]
    if (old["phase"] != "queued" or old["running_attempt"] != 0 or new["phase"] != "running"
            or new["previous_nonce"] != old["dispatch_nonce"]
            or new["dispatch_nonce"] == old["dispatch_nonce"]
            or new["running_attempt"] != old["running_attempt"] + 1
            or not new["worker_label"] or a["readiness"] != b["readiness"]):
        _fail(RefusalCode.GENERATION)


def check_readiness_transition(before: AdmissionRecord, after: AdmissionRecord, receipt: RootReadiness) -> None:
    """Compare-once proposal, not verification of NodeResult/checkpoint origin."""
    b, a, r = before.value(), after.value(), receipt.value()
    if (b["dispatch"]["phase"] != "running" or r["dispatch_nonce"] != b["dispatch"]["dispatch_nonce"]
            or r["running_attempt"] != b["dispatch"]["running_attempt"]):
        _fail(RefusalCode.READINESS)
    if canonical_bytes({k: v for k, v in b.items() if k != "readiness"}) != canonical_bytes(
        {k: v for k, v in a.items() if k != "readiness"}
    ):
        _fail(RefusalCode.PROTECTED)
    existing = next((v for v in b["readiness"] if v["position_id"] == r["position_id"]), None)
    if existing is not None and canonical_bytes(existing) != receipt.wire:
        _fail(RefusalCode.READINESS)
    expected = b["readiness"] if existing is not None else [*b["readiness"], r]
    if canonical_bytes(a["readiness"]) != canonical_bytes(expected):
        _fail(RefusalCode.READINESS)


# Frozen local-only context/hook types. These are intentionally NOT additions to
# shared/types.py; T1's adapter owns dataclasses.replace propagation later.
@dataclass(frozen=True, slots=True)
class DispatchIdentity:
    execution_uuid: str
    dispatch_nonce: str
    running_attempt: int

    def __post_init__(self) -> None:
        for value in (self.execution_uuid, self.dispatch_nonce):
            if type(value) is not str or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
                _fail(RefusalCode.GENERATION)
        if type(self.running_attempt) is not int or self.running_attempt < 1:
            _fail(RefusalCode.GENERATION)


@dataclass(frozen=True, slots=True)
class CandidateInvocationBinding:
    descriptor: ApprovedCandidateDescriptor
    closure: RawClosure
    graph_sha256: str
    dispatch: DispatchIdentity
    node_path: tuple[str, ...]
    position_id: str | None
    expected_node: FrozenJSON
    expected_agent: FrozenJSON | None
    readiness: RootReadiness | None

    def __post_init__(self) -> None:
        expected = ((self.descriptor, ApprovedCandidateDescriptor), (self.closure, RawClosure),
                    (self.dispatch, DispatchIdentity), (self.expected_node, FrozenJSON))
        if any(type(v) is not t for v, t in expected):
            _fail(RefusalCode.TYPE)
        if (type(self.node_path) is not tuple or not self.node_path
                or any(type(p) is not str or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", p) for p in self.node_path)
                or type(self.position_id) not in (str, type(None))
                or type(self.expected_agent) not in (FrozenJSON, type(None))
                or type(self.readiness) not in (RootReadiness, type(None))):
            _fail(RefusalCode.TYPE)
        _hash_matches(self.graph_sha256, self.graph_sha256)


@dataclass(frozen=True, slots=True)
class OpenedRoot:
    """Borrowed fd retained by native attempt; never serialize, close or reopen.

    traversal contains same-no-follow-traversal measurements, not stat(path).
    The claim hook must fstat fd itself; these facts alone cannot authorize it.
    """

    fd: int
    traversal: tuple[FrozenJSON, ...]

    def __post_init__(self) -> None:
        if (type(self.fd) is not int or self.fd < 0 or type(self.traversal) is not tuple
                or not self.traversal or any(type(v) is not FrozenJSON for v in self.traversal)):
            _fail(RefusalCode.TYPE)


class RawCapture(Protocol):
    def capture(self, descriptor: ApprovedCandidateDescriptor, *, transaction: object) -> tuple[RawRecord, ...]: ...


class SnapshotResolver(Protocol):
    def get(self, name: str, config_type: str) -> dict[str, Any]: ...


class AdmissionContext(Protocol):
    @property
    def admission(self) -> CandidateInvocationBinding | None: ...

    @property
    def run_id(self) -> str: ...

    @property
    def node_path(self) -> str: ...

    @property
    def workspace_path(self) -> str | None: ...


class AdmissionTransport(Protocol):
    def install(self, *, admission: AdmissionRecord, transaction: object) -> None: ...
    def restore(self, *, execution_uuid: str, authority: DescriptorAuthority, mode: str) -> AdmissionRecord: ...
    def preserve(self, current: AdmissionRecord, extra: Mapping[str, Any]) -> AdmissionRecord: ...
    def bind_dispatch(self, current: AdmissionRecord, proposed: AdmissionRecord, *, transaction: object) -> None: ...
    def bind_root_readiness(self, current: AdmissionRecord, receipt: RootReadiness,
                            *, verified_preparation: object, transaction: object) -> AdmissionRecord: ...


ClaimResult = TypeVar("ClaimResult")


class AdmissionUseHooks(Protocol):
    def check_graph(self, *, binding: CandidateInvocationBinding, actual_graph: FrozenJSON) -> None: ...
    def invocation(self, *, binding: CandidateInvocationBinding, actual_context: AdmissionContext,
                   actual_node: FrozenJSON, actual_agent: FrozenJSON | None) -> CandidateInvocationBinding: ...
    def check_script(self, *, binding: CandidateInvocationBinding, template: bytes, variables: FrozenJSON) -> None: ...
    def authorize_and_claim(self, *, binding: CandidateInvocationBinding, root: OpenedRoot,
                            actual_config: FrozenJSON, actual_context: AdmissionContext,
                            claim: Callable[[], ClaimResult]) -> ClaimResult: ...
