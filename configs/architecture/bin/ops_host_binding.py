"""Whole selections, explicit actual bytes and an UNTRUSTED candidate (P2; ABI A3, A7).

P2 checks supplied data and nothing else:
- the closed M01 grammar of the QA publication and of the expected receiver
  binding, implemented here on its own from the M01 clauses; no producer
  module is imported, copied or run;
- the whole project table, or the whole calibration manifest, before any
  selection, then the exact six-key, five-key and fifteen-key selections;
- the explicit actual kit, SUMS and domain bytes (kit_evidence) and the exact
  bound subject bytes of every opaque record (record_subjects);
- the supplied source closure: repositories, nodes, edges, runtime, stdlib
  and the QA cohort with all original expectations, compared byte for byte.

Every file is read through the received P1 reader, ops_host_binding_files.py
in this folder (R1). This module runs no subprocess, Git command, exec or
object-store read, and it never lists a directory.

The result is a CandidateTarget: plain, immutable, caller-held data whose
trust is always UNTRUSTED. It is not a TrustedContext, a VerifiedExpectedTarget,
an issuer, a grant or a capability, and no recheck changes its trust. The five
REQUIRED_NATIVE_CHECKS stay unresolved here and nobody can switch them off.
docs/architecture/ops-host-binding.md has the whole contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import ops_host_binding_files as _files  # noqa: E402  (R1, the received P1 reader)

if Path(_files.__file__).resolve() != _HERE / "ops_host_binding_files.py":
    raise ImportError("ops_host_binding_files must be the P1 reader next to this module")

__all__ = [
    "BOUNDARIES",
    "CODES",
    "REQUIRED_NATIVE_CHECKS",
    "TRUST",
    "CandidateTarget",
    "TargetRefused",
    "load_calibration_candidate",
    "load_project_candidate",
    "loads_expected_binding",
    "loads_publication",
    "recheck_candidate",
    "validate_expected_binding",
    "validate_publication",
]

# ABI A7: the eleven codes, in R1's order and with R1's meanings.
CODES = (
    "TARGET_CONTEXT_MISSING",
    "TARGET_ISSUER_UNTRUSTED",
    "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING",
    "TARGET_SELECTOR_AMBIGUOUS",
    "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH",
    "TARGET_SOURCE_MISSING",
    "TARGET_SOURCE_DRIFT",
    "TARGET_REVIEW_MISSING",
    "TARGET_EVIDENCE_INVALID",
)
# _IU stays unused: no native issuer is judged here, so P2 never raises it.
_CM, _IU, _PI, _MS, _AM, _BI, _SI, _SM, _SD, _RM, _EI = CODES

TRUST = "UNTRUSTED"
ROUTES = ("project", "calibration")
BOUNDARIES = ("load-complete", "receiving", "before-count")
# ABI A7: exactly these, in this order, unresolved on every candidate.
REQUIRED_NATIVE_CHECKS = (
    "NATIVE_ISSUER_SCOPE_SUBJECT_CONDITIONS",
    "INDEPENDENT_JOB_KIT_CALIBRATION_SELECTION",
    "REVIEWED_BOOTSTRAP_COMPLETE_DEPENDENCIES_GIT_MEMBERSHIP_AND_ACTUAL_LOADED_SOURCE",
    "SELECTED_RUNTIME_UID_NAMESPACE_CONTAINER_MOUNTS_GRANTS_AND_BOTH_ROOTS_ACCESS",
    "EXACT_QA_PUBLICATION_COHORT_ALL_ORIGINAL_EXPECTATIONS_M02_AND_SECURITY_RECEIVING",
)

# A1 fixed limits.
MAX_DOCUMENT = 16777216
MAX_BINDING = 65536
MAX_GRAPH = 65536  # nodes, edges, files
MAX_ENTRIES = 4096  # table rows, manifest entries
MAX_DEPTH = 32
MAX_PATH_BYTES = 1024
MAX_RECORDS = 4096  # security_records and record_subjects
_RECHECK_BATCH = 65536  # R1 recheck_files batch limit

PUBLICATION_SCHEMA = "qa-ops-host-publication/3"
BINDING_SCHEMA = "qa-ops-host-expected-receiver-binding/1"
TABLE_SCHEMA = "qa-ops-host-project-kits/1"
MANIFEST_SCHEMA = "qa-calibration-manifest/2"
CLOSURE_SCHEMA = "qa-ops-host-source-closure/1"
COHORT_SCHEMA = "qa-ops-host-cohort-inventory/1"
ISSUER = "qa"
PROJECT = "three-passing-projects"
PUBLICATION_ID = "p3-inspect2-publication-1"
BINDING_ID = "p3-inspect2-closed23-env1"
PUBLICATION_NAME = "PUBLICATION.json"
TABLE_PATH = "PROJECT-KITS.json"
BINDING_PATH = "expected-receiver-bindings/p3-inspect2-closed23-env1.json"
CLOSURE_PATH = "SOURCE-CLOSURE.json"
COHORT_PATH = "COHORT-INVENTORY.json"
IDENTITY_PATH = "authority/security22/IDENTITY.json"
ADDRESS = "100.110.162.4"
CONTROL_MODE = 0o600  # kit, SUMS and zero-length cohort files: private leaf mode

_TARGET = {
    "receipt_schema": "ops-host-receipt/1",
    "inspect_schema": "ops-host-inspect/2",
    "runtime_contract": "CLOSED23-ORDERED-ENV/1",
    "semantics_revision": "p3-inspect-env-r3-a5-verdict/1",
    "caller_profiles": ["window-app-forwarder/1", "a5-launch/1"],
}
_TARGET_STRINGS = ("receipt_schema", "inspect_schema", "runtime_contract", "semantics_revision")


def _pin(path: str, sha256: str, byte_length: int) -> dict:
    return {"path": path, "sha256": sha256, "byte_length": byte_length}


# M01 fixed authority pins (binding.authority) and the Security22 review pin.
_AUTHORITY_PINS = {
    "base": _pin("authority/OPS-SLICE-A-PLAN.md",
                 "a9244fd51a3188dbea5242b7b691d7e70ced7b56c2c386c76394292780be29b4", 131525),
    "correction": _pin("authority/OPS-SLICE-A-CORRECTION-1.md",
                       "4507269b404e423b2fadae97301c75edd0b6c70275aedfe7aec507014237e540", 27581),
    "amendment": {
        "proposal": _pin("authority/340/PROPOSAL.md",
                         "983b099688f5cc94eee9c839c6243fb4f98fae2d2372eddfc1f838e129013cb1", 38076),
        "manifest": _pin("authority/340/manifest.json",
                         "f80b734cbecd0f59c465967047c7ef673f9882f6a6b1203c832ff12105f0c03a", 41503),
    },
    "binding_revision": {
        "proposal": _pin("authority/346/PROPOSAL.md",
                         "99dfd476ac723942d930c13e6634b258f2479c3c63e68577db7b2b8598df7dc6", 67702),
        "manifest": _pin("authority/346/manifest.json",
                         "3064bcf734d5dae6bf79d63efc5c2da44d92f7091ed9800e838b191bf9d38ebf", 21125),
    },
    "qa_authority_order": _pin("authority/qa/AUTHORITY-ORDER-1.md",
                               "90983afd65eec06bbef70bad28318ca08ef13de477ebf6b7b29f3c887bfccc08", 8657),
}
_SECURITY_REVIEW_PIN = _pin("authority/security22/REVIEW.md",
                            "9f4ff6ec6b7af39fd4e605fa0be3933b29f2c5e57c9a59490f015232065f33af", 27348)

_SCHEMA_PATHS = {
    "wire_catalog": "catalog/wire.json",
    "inspect": "schemas/inspect-2.schema.json",
    "binding": "schemas/expected-receiver-binding-1.schema.json",
    "source_closure": "schemas/source-closure-1.schema.json",
    "publication": "schemas/publication-3.schema.json",
    "project_kits": "schemas/project-kits-1.schema.json",
    "calibration_manifest": "schemas/calibration-manifest-2.schema.json",
    "cohort_inventory": "schemas/cohort-inventory-1.schema.json",
}

# The six existing window/source pins, unchanged: window key -> agent-tools path.
SIX_PINS = (
    ("ops_host_sha256", "ops-host/hostwin.py"),
    ("controller_sha256", "ops-host/hostctl.py"),
    ("executor_sha256", "ops-host/hostops.py"),
    ("probe_client_sha256", "ops-host/probe/probe_client.py"),
    ("forward_py_sha256", "ops-host/forward.py"),
    ("case_list_sha256", "ops-host/cases/p3-launch-cases.json"),
)

_HOST_ROWS = {"R-1": "restart", "R-1i": "restart", "D-1": "crash", "D-5": "start",
              "API-D-1": "crash", "API-D-5": "start", "HOST-L": "launch-cases"}
_ROLES = frozenset(("producer", "catalog", "schema", "projection", "generator", "stage", "receiver",
                    "safe_reader", "wrapper", "publication_loader", "caller", "resource", "contract",
                    "expectation", "dependency"))
_EDGE_KINDS = frozenset(("imports", "loads", "executes", "compares"))
_NODE_MODES = {"100644": 0o644, "100755": 0o755}
_EXECUTABLE_MODES = {"0755": 0o755, "0555": 0o555}
_STDLIB_MODES = {"0644": 0o644, "0755": 0o755, "0444": 0o444, "0555": 0o555}
_FILE_KINDS = frozenset(("original", "fresh", "intentional-negative"))
_DISPOSITIONS = frozenset(("resolved", "intentional-negative", "unknown"))
_FAILURES = frozenset(("none", "invalid-json", "invalid-ref", "missing-target", "hash-mismatch",
                       "length-mismatch", "cycle", "unknown"))

_PUBLICATION_KEYS = frozenset(("schema", "issuer", "project", "publication_id", "project_kits",
                               "calibration_manifests"))
_BINDING_KEYS = frozenset(("schema", "issuer", "project", "publication_id", "binding_id", "target",
                           "authority", "schemas", "security_context", "source_closure"))
_PROJECT_CONTEXT = frozenset(("window", "publication", "m01_record", "m02_record", "security_records",
                              "expected_window_sha256", "expected_binding", "release_roots",
                              "kit_evidence", "record_subjects"))
_CALIBRATION_CONTEXT = _PROJECT_CONTEXT | {"calibration_manifest", "expected_draft_kit_id",
                                           "expected_calibration_selection"}
_SIX = frozenset(("mode", "project_id", "run_id", "build_sums_sha256", "kit_id", "kit_sha256"))
_FIVE = frozenset(("mode", "manifest_sha256", "entry", "build_sums_sha256", "calibration_run"))
_FIFTEEN = frozenset(("manifest_path", "manifest_sha256", "entry", "build_id", "sums_sha256", "round",
                      "copy_id", "address", "port", "literal_origin", "runtime_sha256",
                      "security_receipt_id", "security_receipt_path", "security_receipt_sha256",
                      "security_selection_message_id"))
_ENTRY_KEYS = frozenset(("entry", "build_id", "purpose", "copy_id", "batch_id", "build_path", "sums_file",
                         "host_dir", "app_copy_path", "data_dir", "sums_sha256", "runtime_sha256",
                         "file_count", "plant_of", "diff_sha256", "round", "address", "port",
                         "literal_origin", "runtime", "inner_network_name", "edge_network_name",
                         "reuse_after", "scheduled_use_minutes", "schedule_source", "schedule_sha256",
                         "expected_receiver_binding"))
_ENTRY_STRINGS = ("entry", "build_id", "purpose", "copy_id", "batch_id", "inner_network_name",
                  "edge_network_name")
_ENTRY_PATHS = ("build_path", "sums_file", "host_dir", "app_copy_path", "data_dir")
_SCHEDULE = ("scheduled_use_minutes", "schedule_source", "schedule_sha256")

_T = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_H = re.compile(r"[0-9a-f]{64}")
_G = re.compile(r"[0-9a-f]{40}")
_COMPONENT = re.compile(r"[A-Za-z0-9._-]{1,128}")
_POINTER = re.compile(r"(?:/(?:[^~/]|~[01])*)*")
_CALIBRATION_PATH = re.compile(r"calibrations/([A-Za-z0-9][A-Za-z0-9._-]{0,127})/manifest\.json")
_SUMS_LINE = re.compile(r"([0-9a-f]{64})  ([^\x00-\x1f\\]+)")
_BAD = object()


class TargetRefused(ValueError):
    """A fixed local refusal: args, str and repr hold exactly the code."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in CODES:
            raise TypeError("unknown refusal code")
        super().__init__(code)
        self.__code = code

    @property
    def code(self) -> str:
        return self.__code


def _refuse(code: str) -> NoReturn:
    raise TargetRefused(code)


# ---------------------------------------------------------------------------
# A1 grammar atoms. Pure: no filesystem call.

def _utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_s(value: object) -> bool:
    return type(value) is str and value != "" and "\x00" not in value and _utf8(value)


def _is_t(value: object) -> bool:
    return type(value) is str and _T.fullmatch(value) is not None


def _is_h(value: object) -> bool:
    return type(value) is str and _H.fullmatch(value) is not None


def _is_g(value: object) -> bool:
    return type(value) is str and _G.fullmatch(value) is not None


def _is_int(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _is_p(value: object) -> bool:
    if type(value) is not str or not value or not _utf8(value):
        return False
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        return False
    return all(_COMPONENT.fullmatch(part) and part not in (".", "..") for part in value.split("/"))


def _is_a(value: object) -> bool:
    return type(value) is str and value.startswith("/") and _is_p(value[1:])


def _is_j(value: object) -> bool:
    return type(value) is str and _utf8(value) and _POINTER.fullmatch(value) is not None


def _lit(value: object, expected: str) -> bool:
    return type(value) is str and value == expected


def _keys(value: object, keys: frozenset | set) -> bool:
    return type(value) is dict and len(value) == len(keys) and set(value) == keys


def _is_ref(value: object, *, low: int = 1, path: str | None = None, absolute: bool = False) -> bool:
    if not _keys(value, {"path", "sha256", "byte_length"}):
        return False
    path_ok = _is_a(value["path"]) if absolute else _is_p(value["path"])
    if not path_ok or (path is not None and value["path"] != path):
        return False
    return _is_h(value["sha256"]) and _is_int(value["byte_length"], low, MAX_DOCUMENT)


def _is_absref(value: object) -> bool:
    return _is_ref(value, absolute=True)


def _identity(ref: dict) -> tuple[str, str, int]:
    return ref["path"], ref["sha256"], ref["byte_length"]


def _same(a: object, b: object) -> bool:
    """Equal values of exactly the same built-in types (True is not 1)."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _plain(value: object) -> bool:
    """Exact JSON built-ins only (no subclass, no float), at most MAX_DEPTH containers deep."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        kind = type(item)
        if kind is dict:
            if depth > MAX_DEPTH:
                return False
            for key, child in item.items():
                if type(key) is not str:
                    return False
                stack.append((child, depth + 1))
        elif kind is list:
            if depth > MAX_DEPTH:
                return False
            stack.extend((child, depth + 1) for child in item)
        elif kind not in (str, int, bool) and item is not None:
            return False
    return True


def _copy(value: Any) -> Any:
    if type(value) is dict:
        return {key: _copy(child) for key, child in value.items()}
    if type(value) is list:
        return [_copy(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _unique_names(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON name")
        out[key] = value
    return out


def _no_constant(name: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _json(raw: object, cap: int, code: str) -> Any:
    """Strict JSON: exact bytes, UTF-8, no duplicate name, no NaN/Infinity, no float, depth <= 32."""
    if type(raw) is not bytes or not 0 < len(raw) <= cap:
        _refuse(code)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_names,
                           parse_constant=_no_constant)
    except (ValueError, RecursionError):
        value = _BAD
    if value is _BAD or not _plain(value):
        _refuse(code)
    return value


def _sorted_unique(keys: list) -> bool:
    return all(a < b for a, b in zip(keys, keys[1:], strict=False))


# ---------------------------------------------------------------------------
# A3: the four standalone grammar APIs (M01 structural contract, own code).

def _check_publication(value: object) -> None:
    if not _plain(value) or not _keys(value, _PUBLICATION_KEYS) or type(value["schema"]) is not str:
        _refuse(_PI)
    if value["schema"] != PUBLICATION_SCHEMA:
        _refuse(_SI)
    if not (_lit(value["issuer"], ISSUER) and _lit(value["project"], PROJECT)
            and _lit(value["publication_id"], PUBLICATION_ID)
            and _is_ref(value["project_kits"], path=TABLE_PATH)):
        _refuse(_PI)
    manifests = value["calibration_manifests"]
    if type(manifests) is not list or len(manifests) > MAX_ENTRIES:
        _refuse(_PI)
    for ref in manifests:
        if not _is_ref(ref) or _CALIBRATION_PATH.fullmatch(ref["path"]) is None:
            _refuse(_PI)
    if not _sorted_unique([ref["path"].encode("utf-8") for ref in manifests]):
        _refuse(_PI)


def _check_binding(value: object) -> None:
    if not _plain(value) or not _keys(value, _BINDING_KEYS) or type(value["schema"]) is not str:
        _refuse(_BI)
    if value["schema"] != BINDING_SCHEMA:
        _refuse(_SI)
    if not (_lit(value["issuer"], ISSUER) and _lit(value["project"], PROJECT)
            and _lit(value["publication_id"], PUBLICATION_ID) and _lit(value["binding_id"], BINDING_ID)):
        _refuse(_BI)
    target = value["target"]
    if not _keys(target, set(_TARGET)) or any(type(target[key]) is not str for key in _TARGET_STRINGS):
        _refuse(_BI)
    profiles = target["caller_profiles"]
    if type(profiles) is not list or any(type(item) is not str for item in profiles):
        _refuse(_BI)
    if not _same(target, _TARGET):
        _refuse(_SI)
    if not _same(value["authority"], _AUTHORITY_PINS):
        _refuse(_BI)
    schemas = value["schemas"]
    if type(schemas) is not dict or set(schemas) != set(_SCHEMA_PATHS):
        _refuse(_BI)
    if not all(_is_ref(schemas[key], path=path) for key, path in _SCHEMA_PATHS.items()):
        _refuse(_BI)
    security = value["security_context"]
    if (not _keys(security, {"review", "identity"}) or not _same(security["review"], _SECURITY_REVIEW_PIN)
            or not _is_ref(security["identity"], path=IDENTITY_PATH)):
        _refuse(_BI)
    if not _is_ref(value["source_closure"], path=CLOSURE_PATH):
        _refuse(_BI)


def loads_publication(raw: bytes) -> dict:
    """Parse one qa-ops-host-publication/3 document: {trust: UNTRUSTED, value: fresh copy}."""
    value = _json(raw, MAX_DOCUMENT, _PI)
    _check_publication(value)
    return {"trust": TRUST, "value": value}


def validate_publication(value: object) -> dict:
    """Check an already parsed publication; the input is never changed or aliased."""
    _check_publication(value)
    return {"trust": TRUST, "value": _copy(value)}


def loads_expected_binding(raw: bytes) -> dict:
    """Parse one qa-ops-host-expected-receiver-binding/1 document (at most 65536 bytes)."""
    value = _json(raw, MAX_BINDING, _BI)
    _check_binding(value)
    return {"trust": TRUST, "value": value}


def validate_expected_binding(value: object) -> dict:
    """Check an already parsed binding; the input is never changed or aliased."""
    _check_binding(value)
    return {"trust": TRUST, "value": _copy(value)}


# ---------------------------------------------------------------------------
# A3.1 data context shape, checked before any read.

def _context(route: str, context: object) -> dict:
    keys = _PROJECT_CONTEXT if route == "project" else _CALIBRATION_CONTEXT
    if not _plain(context) or not _keys(context, keys):
        _refuse(_CM)
    ctx = _copy(context)
    records = ctx["security_records"]
    if not all(_is_absref(ctx[key]) for key in ("window", "publication", "m01_record", "m02_record")):
        _refuse(_CM)
    if type(records) is not list or not 1 <= len(records) <= MAX_RECORDS or not all(map(_is_absref, records)):
        _refuse(_CM)
    if not _is_h(ctx["expected_window_sha256"]) or type(ctx["expected_binding"]) is not dict:
        _refuse(_CM)
    roots = ctx["release_roots"]
    if type(roots) is not list or not 1 <= len(roots) <= MAX_GRAPH:
        _refuse(_CM)
    for item in roots:
        if not _keys(item, {"repository", "root"}) or not _is_t(item["repository"]) or not _is_a(item["root"]):
            _refuse(_CM)
    if len({item["repository"] for item in roots}) != len(roots):
        _refuse(_CM)
    _kit_shape(route, ctx["kit_evidence"])
    if route == "calibration" and not (_is_absref(ctx["calibration_manifest"])
                                       and _is_s(ctx["expected_draft_kit_id"])
                                       and type(ctx["expected_calibration_selection"]) is dict):
        _refuse(_CM)
    return ctx


def _kit_shape(route: str, kit: object) -> None:
    if not _keys(kit, {"root", "kit", "sums", "files", "file_count"}):
        _refuse(_CM)
    if not _is_a(kit["root"]) or not _is_ref(kit["sums"]):
        _refuse(_CM)
    if not (_is_ref(kit["kit"]) if route == "project" else kit["kit"] is None):
        _refuse(_CM)
    files = kit["files"]
    if type(files) is not list or not 1 <= len(files) <= MAX_GRAPH:
        _refuse(_CM)
    for item in files:
        if (not _keys(item, {"ref", "mode"}) or not _is_ref(item["ref"], low=0)
                or not _is_int(item["mode"], 0, 0o7777)):
            _refuse(_CM)
    if not _sorted_unique([item["ref"]["path"].encode("utf-8") for item in files]):
        _refuse(_CM)
    if not _is_int(kit["file_count"], 1) or kit["file_count"] != len(files):
        _refuse(_CM)


def _record_refs(ctx: dict) -> list[dict]:
    return [ctx["m01_record"], ctx["m02_record"], *ctx["security_records"]]


def _subjects_shape(ctx: dict) -> list[tuple[dict, dict]]:
    """record_subjects: exactly one closed association per opaque record identity (else RM)."""
    records = _record_refs(ctx)
    identities = [_identity(ref) for ref in records]
    if len(set(identities)) != len(identities):
        _refuse(_RM)
    subjects = ctx["record_subjects"]
    if type(subjects) is not list or len(subjects) > MAX_RECORDS:
        _refuse(_RM)
    by_record: dict = {}
    for item in subjects:
        if not _keys(item, {"record", "byte_offset", "byte_length", "expected_subject"}):
            _refuse(_RM)
        record, offset, length, subject = (item["record"], item["byte_offset"], item["byte_length"],
                                           item["expected_subject"])
        if not _is_absref(record) or not _is_int(offset, 0, MAX_DOCUMENT) or not _is_int(length, 1, MAX_DOCUMENT):
            _refuse(_RM)
        if not _is_absref(subject) or subject["byte_length"] != length:
            _refuse(_RM)
        key = _identity(record)
        if key not in identities or key in by_record:
            _refuse(_RM)
        if offset + length > record["byte_length"]:
            _refuse(_RM)
        by_record[key] = item
    if len(by_record) != len(identities):
        _refuse(_RM)
    return [(ref, by_record[_identity(ref)]) for ref in records]


def _subject_equal(record_raw: bytes, offset: int, length: int, subject_raw: bytes) -> bool:
    """The loader's subject guard: the supplied span equals the bound subject, byte for byte."""
    return record_raw[offset:offset + length] == subject_raw


# ---------------------------------------------------------------------------
# A3.2 whole table and whole manifest, before selection.

def _check_table(table: object) -> None:
    if not _keys(table, {"schema", "publication_id", "kits"}) or type(table["schema"]) is not str:
        _refuse(_BI)
    if table["schema"] != TABLE_SCHEMA:
        _refuse(_SI)
    rows = table["kits"]
    if not _lit(table["publication_id"], PUBLICATION_ID) or type(rows) is not list or len(rows) > MAX_ENTRIES:
        _refuse(_BI)
    for row in rows:
        if (not _keys(row, {"project_id", "kit_id", "kit_sha256", "build_sums_sha256", "expected_receiver_binding"})
                or not _is_s(row["project_id"]) or not _is_s(row["kit_id"]) or not _is_h(row["kit_sha256"])
                or not _is_h(row["build_sums_sha256"])
                or not _is_ref(row["expected_receiver_binding"], path=BINDING_PATH)):
            _refuse(_BI)


def _selector(row: dict) -> tuple[str, str, str, str]:
    return row["project_id"], row["kit_id"], row["kit_sha256"], row["build_sums_sha256"]


def _table_selectors_unique(rows: list) -> None:
    """Whole-table guard: every four-tuple selector is unique, selected or not (else AM)."""
    selectors = [_selector(row) for row in rows]
    if len(set(selectors)) != len(selectors):
        _refuse(_AM)


def _runtime_sha256(runtime: dict) -> str:
    text = json.dumps(runtime, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _origin(port: int) -> str:
    return f"http://{ADDRESS}:{port}"


def _runtime_ok(runtime: object, port: int) -> bool:
    env = {"HOST": "0.0.0.0", "PORT": "8000", "DATA_DIR": "/data", "ALLOWED_HOSTS": f"{ADDRESS}:{port},scanapp:8080"}
    return (_keys(runtime, {"image", "command", "internal_port", "workdir", "env"}) and _is_s(runtime["image"])
            and _same(runtime["command"], ["python3", "/app/server.py"])
            and _same(runtime["internal_port"], 8000) and _lit(runtime["workdir"], "/app")
            and _same(runtime["env"], env))


def _entry_ok(entry: object) -> bool:
    if not _keys(entry, _ENTRY_KEYS):
        return False
    if not all(_is_s(entry[key]) for key in _ENTRY_STRINGS) or not all(_is_a(entry[key]) for key in _ENTRY_PATHS):
        return False
    if not (_is_h(entry["sums_sha256"]) and _is_h(entry["runtime_sha256"])
            and _is_int(entry["file_count"], 1, MAX_GRAPH)):
        return False
    if not (entry["plant_of"] is None or _is_s(entry["plant_of"])):
        return False
    if not (entry["diff_sha256"] is None or _is_h(entry["diff_sha256"])):
        return False
    port = entry["port"]
    if not (_is_int(entry["round"], 1, 2) and _lit(entry["address"], ADDRESS) and _is_int(port, 8970, 8979)
            and _lit(entry["literal_origin"], _origin(port))):
        return False
    if not _runtime_ok(entry["runtime"], port) or entry["runtime_sha256"] != _runtime_sha256(entry["runtime"]):
        return False
    reuse = entry["reuse_after"]
    if type(reuse) is not list or len(reuse) > MAX_ENTRIES or not all(map(_is_s, reuse)) or len(set(reuse)) != len(reuse):
        return False
    schedule = [entry[key] for key in _SCHEDULE]
    if not all(item is None for item in schedule) and not (
            _is_int(schedule[0], 0) and _is_s(schedule[1]) and _is_h(schedule[2])):
        return False
    if entry["inner_network_name"] == entry["edge_network_name"]:
        return False
    return _is_ref(entry["expected_receiver_binding"], path=BINDING_PATH)


def _whole_manifest(manifest: object, path_id: str) -> None:
    """Whole-manifest guard: discriminator, every entry, unique ids, path id (before selection)."""
    if not _keys(manifest, {"schema", "publication_id", "calibration_id", "draft_kit_id", "host_rows", "entries"}):
        _refuse(_BI)
    if type(manifest["schema"]) is not str:
        _refuse(_BI)
    if manifest["schema"] != MANIFEST_SCHEMA:
        _refuse(_SI)
    entries = manifest["entries"]
    if not (_lit(manifest["publication_id"], PUBLICATION_ID) and _is_t(manifest["calibration_id"])
            and _is_s(manifest["draft_kit_id"]) and _same(manifest["host_rows"], _HOST_ROWS)
            and type(entries) is list and 1 <= len(entries) <= MAX_ENTRIES):
        _refuse(_BI)
    if not all(map(_entry_ok, entries)):
        _refuse(_BI)
    _manifest_ids_unique(entries)
    data_dirs = [entry["data_dir"] for entry in entries]
    if len(set(data_dirs)) != len(data_dirs):
        _refuse(_BI)  # fresh data folder per copy and round
    earlier: set = set()
    for entry in entries:
        if not set(entry["reuse_after"]) <= earlier:
            _refuse(_BI)  # reuse names only prior entries: no self, no cycle
        earlier.add(entry["entry"])
    if manifest["calibration_id"] != path_id:
        _refuse(_BI)


def _manifest_ids_unique(entries: list) -> None:
    """Whole-manifest guard: every entry id is unique, selected or not (else AM)."""
    ids = [entry["entry"] for entry in entries]
    if len(set(ids)) != len(ids):
        _refuse(_AM)


def _w(window: dict, key: str) -> Any:
    """A window member, or a marker no data equals when the member is absent."""
    return window.get(key, _BAD)


def _selection_ok(selection: dict) -> bool:
    port = selection.get("port")
    return (_keys(selection, _FIFTEEN) and _is_a(selection["manifest_path"]) and _is_h(selection["manifest_sha256"])
            and _is_s(selection["entry"]) and _is_s(selection["build_id"]) and _is_h(selection["sums_sha256"])
            and _is_int(selection["round"], 1, 2) and _is_s(selection["copy_id"])
            and _lit(selection["address"], ADDRESS) and _is_int(port, 8970, 8979)
            and _lit(selection["literal_origin"], _origin(port)) and _is_h(selection["runtime_sha256"])
            and _is_s(selection["security_receipt_id"]) and _is_a(selection["security_receipt_path"])
            and _is_h(selection["security_receipt_sha256"]) and _is_s(selection["security_selection_message_id"]))


# ---------------------------------------------------------------------------
# A3.3 supplied closure grammar.

def _closure_shape(closure: object) -> None:
    keys = {"schema", "publication_id", "repositories", "nodes", "edges", "entrypoints", "runtime", "generated_closure"}
    if not _keys(closure, keys) or type(closure["schema"]) is not str:
        _refuse(_BI)
    if closure["schema"] != CLOSURE_SCHEMA:
        _refuse(_SI)
    repositories, nodes, edges, entrypoints = (closure["repositories"], closure["nodes"], closure["edges"],
                                               closure["entrypoints"])
    if not _lit(closure["publication_id"], PUBLICATION_ID):
        _refuse(_BI)
    if any(type(items) is not list for items in (repositories, nodes, edges, entrypoints)):
        _refuse(_BI)
    if not (1 <= len(repositories) <= MAX_GRAPH and 1 <= len(nodes) <= MAX_GRAPH and len(edges) <= MAX_GRAPH
            and len(entrypoints) <= MAX_GRAPH):
        _refuse(_BI)  # graph bound
    for repo in repositories:
        if (not _keys(repo, {"id", "owner", "root", "commit", "tree"}) or not _is_t(repo["id"])
                or repo["owner"] not in ("ops", "architecture", "qa") or type(repo["owner"]) is not str
                or not _is_a(repo["root"]) or not _is_g(repo["commit"]) or not _is_g(repo["tree"])):
            _refuse(_BI)
    if not _sorted_unique([repo["id"] for repo in repositories]):
        _refuse(_BI)
    repo_ids = {repo["id"] for repo in repositories}
    for node in nodes:
        if not _node_ok(node, repo_ids):
            _refuse(_BI)
    if not _sorted_unique([node["id"] for node in nodes]):
        _refuse(_BI)  # duplicate or unsorted node
    members = [(node["repository"], node["path"]) for node in nodes]
    if len(set(members)) != len(members):
        _refuse(_BI)  # one node per repository path
    for edge in edges:
        if (not _keys(edge, {"from", "to", "kind"}) or not _is_t(edge["from"]) or not _is_t(edge["to"])
                or type(edge["kind"]) is not str or edge["kind"] not in _EDGE_KINDS):
            _refuse(_BI)
    if not _sorted_unique([(edge["from"], edge["to"], edge["kind"]) for edge in edges]):
        _refuse(_BI)  # duplicate or unsorted edge
    for item in entrypoints:
        if not _keys(item, {"node", "symbol"}) or not _is_t(item["node"]) or not _is_s(item["symbol"]):
            _refuse(_BI)
    if not _sorted_unique([(item["node"], item["symbol"]) for item in entrypoints]):
        _refuse(_BI)
    runtime = closure["runtime"]
    if (not _keys(runtime, {"implementation", "version", "executable", "executable_uid", "executable_mode",
                            "stdlib_root", "stdlib_inventory"})
            or not _lit(runtime["implementation"], "cpython") or not _is_s(runtime["version"])
            or not _is_absref(runtime["executable"]) or not _is_int(runtime["executable_uid"], 0)
            or type(runtime["executable_mode"]) is not str or runtime["executable_mode"] not in _EXECUTABLE_MODES
            or not _is_a(runtime["stdlib_root"]) or not _is_ref(runtime["stdlib_inventory"])):
        _refuse(_BI)
    if not _is_ref(closure["generated_closure"], path=COHORT_PATH):
        _refuse(_BI)
    ids = {node["id"] for node in nodes}
    if any(edge["from"] not in ids or edge["to"] not in ids for edge in edges):
        _refuse(_SM)  # unresolved dependency
    if any(item["node"] not in ids for item in entrypoints):
        _refuse(_SM)
    if not _acyclic(ids, edges):
        _refuse(_BI)


def _node_ok(node: object, repo_ids: set) -> bool:
    if not _keys(node, {"id", "repository", "path", "git_blob", "sha256", "byte_length", "mode", "roles"}):
        return False
    roles = node["roles"]
    return (_is_t(node["id"]) and _is_t(node["repository"]) and node["repository"] in repo_ids
            and _is_p(node["path"]) and _is_g(node["git_blob"]) and _is_h(node["sha256"])
            and _is_int(node["byte_length"], 0, MAX_DOCUMENT) and type(node["mode"]) is str
            and node["mode"] in _NODE_MODES and type(roles) is list and len(roles) >= 1
            and all(type(role) is str and role in _ROLES for role in roles) and _sorted_unique(roles))


def _acyclic(ids: set, edges: list) -> bool:
    targets: dict = {node: [] for node in ids}
    incoming = dict.fromkeys(ids, 0)
    for edge in edges:
        targets[edge["from"]].append(edge["to"])
        incoming[edge["to"]] += 1
    ready = [node for node, count in incoming.items() if count == 0]
    seen = 0
    while ready:
        node = ready.pop()
        seen += 1
        for target in targets[node]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return seen == len(ids)


def _git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()  # noqa: S324 (Git object id, not security)


def _stdlib_ok(items: object) -> bool:
    if type(items) is not list or len(items) > MAX_GRAPH:
        return False
    for item in items:
        if (not _keys(item, {"path", "sha256", "byte_length", "mode", "uid"}) or not _is_p(item["path"])
                or not _is_h(item["sha256"]) or not _is_int(item["byte_length"], 0, MAX_DOCUMENT)
                or type(item["mode"]) is not str or item["mode"] not in _STDLIB_MODES
                or not _is_int(item["uid"], 0)):
            return False
    return _sorted_unique([item["path"].encode("utf-8") for item in items])


def _cohort_shape(cohort: object) -> None:
    keys = {"schema", "publication_id", "cohort_id", "files", "references", "original_inventory",
            "original_index", "old_to_new_expectations"}
    if not _keys(cohort, keys) or type(cohort["schema"]) is not str:
        _refuse(_BI)
    if cohort["schema"] != COHORT_SCHEMA:
        _refuse(_SI)
    files, references = cohort["files"], cohort["references"]
    if not (_lit(cohort["publication_id"], PUBLICATION_ID) and _is_t(cohort["cohort_id"])
            and type(files) is list and len(files) <= MAX_GRAPH and type(references) is list
            and len(references) <= MAX_GRAPH and all(_is_ref(cohort[key]) for key in
                                                    ("original_inventory", "original_index", "old_to_new_expectations"))):
        _refuse(_BI)
    for item in files:
        if (not _keys(item, {"path", "sha256", "byte_length", "kind"}) or not _is_ref(
                {"path": item["path"], "sha256": item["sha256"], "byte_length": item["byte_length"]}, low=0)
                or type(item["kind"]) is not str or item["kind"] not in _FILE_KINDS):
            _refuse(_BI)
    if not _sorted_unique([item["path"].encode("utf-8") for item in files]):
        _refuse(_BI)
    for item in references:
        if not _reference_ok(item):
            _refuse(_BI)
    order = [(item["from"], item["pointer"], "" if item["to"] is None else "\x01" + item["to"]) for item in references]
    if not _sorted_unique(order):
        _refuse(_BI)


def _reference_ok(item: object) -> bool:
    keys = {"from", "pointer", "to", "sha256", "byte_length", "disposition", "failure"}
    if not _keys(item, keys) or not _is_p(item["from"]) or not _is_j(item["pointer"]):
        return False
    if not (item["to"] is None or _is_p(item["to"])) or not (item["sha256"] is None or _is_h(item["sha256"])):
        return False
    if not (item["byte_length"] is None or _is_int(item["byte_length"], 0, MAX_DOCUMENT)):
        return False
    if type(item["disposition"]) is not str or item["disposition"] not in _DISPOSITIONS:
        return False
    if type(item["failure"]) is not str or item["failure"] not in _FAILURES:
        return False
    if item["disposition"] == "resolved":
        return (item["to"] is not None and item["sha256"] is not None and item["byte_length"] is not None
                and item["failure"] == "none")
    return True


def _inventory_ok(items: object) -> bool:
    if type(items) is not list or len(items) > MAX_GRAPH:
        return False
    if not all(_keys(item, {"path", "sha256", "byte_length"}) and _is_ref(item, low=0) for item in items):
        return False
    return _sorted_unique([item["path"].encode("utf-8") for item in items])


def _expectations_ok(items: object) -> bool:
    keys = {"original_pointer", "original_path", "original_label", "observed_original_result", "new_path",
            "new_expected_result", "reason"}
    if type(items) is not list or len(items) > MAX_GRAPH:
        return False
    for item in items:
        if (not _keys(item, keys) or not _is_j(item["original_pointer"]) or not _is_p(item["original_path"])
                or not _is_s(item["original_label"]) or not _is_s(item["observed_original_result"])
                or not (item["new_path"] is None or _is_p(item["new_path"]))
                or not _is_s(item["new_expected_result"]) or not _is_s(item["reason"])):
            return False
    pointers = [item["original_pointer"] for item in items]
    return len(set(pointers)) == len(pointers)


def _sums_names(raw: bytes) -> dict | None:
    """The existing build SUMS grammar: '<64 hex>  <name>' lines, no alias, no duplicate."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    names: dict = {}
    for line in text.splitlines():
        match = _SUMS_LINE.fullmatch(line)
        if match is None:
            return None
        digest, name = match.groups()
        if name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")) or name in names:
            return None
        names[name] = digest
    return names


def _split(path: str) -> tuple[str, str]:
    parent, name = path.rsplit("/", 1)
    return parent or "/", name


# ---------------------------------------------------------------------------
# The candidate.

@dataclass(frozen=True, slots=True, repr=False)
class CandidateTarget:
    """Immutable UNTRUSTED data: exactly the eleven A3.3 fields, no hidden field or authority bit."""

    trust: str
    route: str
    target: Any
    publication: Any
    binding: Any
    source_closure: Any
    expected_window_sha256: str
    expected_binding: Any
    selection: Any
    reads: tuple
    required_native_checks: tuple

    def __post_init__(self) -> None:
        if (self.trust != TRUST or type(self.trust) is not str or self.route not in ROUTES
                or type(self.reads) is not tuple or not all(type(read) is _files.FileRead for read in self.reads)
                or type(self.required_native_checks) is not tuple
                or self.required_native_checks != REQUIRED_NATIVE_CHECKS):
            raise TypeError("a CandidateTarget is UNTRUSTED data with every native check unresolved")

    def __repr__(self) -> str:
        return f"CandidateTarget(trust={self.trust!r}, route={self.route!r}, reads={len(self.reads)})"

    __str__ = __repr__


class _Loader:
    """One load: reads go through R1 only, and every read is kept for the rechecks."""

    def __init__(self, route: str, uid: object) -> None:
        if not _is_int(uid, 0):
            _refuse(_EI)
        self.route = route
        self.uid = uid
        self.reads: list = []
        self.paths: dict = {}  # QA-root relative path -> (sha256, byte_length)

    # R1 calls, each mapped to the code of the ref's class; R1 drift stays drift.
    def _r1(self, code: str, call: Any, *args: Any, **kwargs: Any) -> Any:
        refused = None
        try:
            read = call(*args, **kwargs)
        except _files.TargetRefused as exc:
            refused = _SD if exc.code == _SD else code
        if refused is not None:
            _refuse(refused)
        self.reads.append(read)
        return read

    def private(self, root: str, ref: dict, code: str) -> Any:
        return self._r1(code, _files.read_private_file, root, _copy(ref), uid=self.uid, cap=MAX_DOCUMENT)

    def private_abs(self, ref: dict, code: str) -> Any:
        root, name = _split(ref["path"])
        return self.private(root, {"path": name, "sha256": ref["sha256"], "byte_length": ref["byte_length"]}, code)

    def control(self, ref: dict) -> Any:
        """A QA-root control file; an explicit zero length uses the release route at 0o600."""
        self.register(ref)
        if ref["byte_length"] == 0:
            return self._r1(_PI, _files.read_release_file, self.qa_root, _copy(ref), uid=self.uid,
                            mode=CONTROL_MODE, cap=MAX_DOCUMENT)
        return self.private(self.qa_root, ref, _PI)

    def source(self, root: str, ref: dict, uid: int, mode: int, modes: tuple) -> Any:
        """A release source; bytes found only under another allowed mode mean the declaration is wrong."""
        refused = None
        try:
            read = _files.read_release_file(root, _copy(ref), uid=uid, mode=mode, cap=MAX_DOCUMENT)
        except _files.TargetRefused as exc:
            refused = _SD if exc.code == _SD else _SM
        if refused == _SM:
            for other in modes:
                if other != mode and self._present(root, ref, uid, other):
                    refused = _BI
                    break
        if refused is not None:
            _refuse(refused)
        self.reads.append(read)
        return read

    @staticmethod
    def _present(root: str, ref: dict, uid: int, mode: int) -> bool:
        try:
            _files.read_release_file(root, _copy(ref), uid=uid, mode=mode, cap=MAX_DOCUMENT)
        except _files.TargetRefused:
            return False
        return True

    def register(self, ref: dict) -> None:
        """One identity per QA-root path across every Ref reachable from the publication (else PI)."""
        seen = self.paths.setdefault(ref["path"], (ref["sha256"], ref["byte_length"]))
        if seen != (ref["sha256"], ref["byte_length"]):
            _refuse(_PI)

    # The load, in its fixed order.
    def run(self, context: object) -> CandidateTarget:
        ctx = _context(self.route, context)
        subjects = _subjects_shape(ctx)
        window = self._window(ctx)
        self._expected(ctx, window)
        publication = self._publication(ctx)
        if self.route == "project":
            chosen, binding_ref = self._project(ctx, publication)
        else:
            chosen, binding_ref = self._calibration(ctx, publication, window)
        self.register(binding_ref)
        binding = _json(self.private(self.qa_root, binding_ref, _PI).raw, MAX_BINDING, _BI)
        _check_binding(binding)
        self._kit(ctx, chosen)
        self._subjects(subjects)
        closure, cohort = self._closure(ctx, binding, window)
        _recheck(tuple(self.reads))
        selection = {"route": self.route, "window": ctx["window"], "publication": ctx["publication"],
                     "m01_record": ctx["m01_record"], "m02_record": ctx["m02_record"],
                     "security_records": ctx["security_records"], "record_subjects": ctx["record_subjects"],
                     "kit_evidence": ctx["kit_evidence"], "release_roots": ctx["release_roots"]}
        if self.route == "project":
            selection["row"] = chosen
        else:
            selection.update(calibration_manifest=ctx["calibration_manifest"], entry=chosen,
                             expected_draft_kit_id=ctx["expected_draft_kit_id"],
                             calibration_selection=ctx["expected_calibration_selection"])
        candidate = CandidateTarget(
            trust=TRUST, route=self.route, target=_freeze(binding["target"]), publication=_freeze(publication),
            binding=_freeze(binding), source_closure=_freeze({"closure": closure, "cohort": cohort}),
            expected_window_sha256=ctx["expected_window_sha256"], expected_binding=_freeze(ctx["expected_binding"]),
            selection=_freeze(selection), reads=tuple(self.reads), required_native_checks=REQUIRED_NATIVE_CHECKS)
        if not _identities(candidate):
            _refuse(_EI)
        return candidate

    def _window(self, ctx: dict) -> dict:
        """The explicit window AbsRef: same hash as expected, read FIRST with its declared length."""
        ref = ctx["window"]
        if ref["sha256"] != ctx["expected_window_sha256"]:
            _refuse(_BI)
        window = _json(self.private_abs(ref, _PI).raw, MAX_DOCUMENT, _PI)
        if type(window) is not dict:
            _refuse(_PI)
        return window

    def _expected(self, ctx: dict, window: dict) -> None:
        binding = ctx["expected_binding"]
        if self.route == "project":
            ok = (_keys(binding, _SIX) and _lit(binding["mode"], "project") and _is_s(binding["project_id"])
                  and _is_s(binding["run_id"]) and _is_s(binding["kit_id"]) and _is_h(binding["kit_sha256"])
                  and _is_h(binding["build_sums_sha256"]))
        else:
            ok = (_keys(binding, _FIVE) and _lit(binding["mode"], "calibration") and _is_h(binding["manifest_sha256"])
                  and _is_s(binding["entry"]) and _is_h(binding["build_sums_sha256"])
                  and _is_s(binding["calibration_run"]))
        if not ok or not _same(binding, _w(window, "binding")):
            _refuse(_BI)
        if self.route == "project":
            return
        selection = ctx["expected_calibration_selection"]
        if not _selection_ok(selection) or not _same(selection, _w(window, "calibration_selection")):
            _refuse(_BI)
        if not (_same(selection["security_receipt_path"], _w(window, "security_receipt_path"))
                and _same(selection["security_receipt_sha256"], _w(window, "security_receipt_sha256"))):
            _refuse(_BI)
        if not (selection["manifest_sha256"] == binding["manifest_sha256"] and selection["entry"] == binding["entry"]
                and selection["sums_sha256"] == binding["build_sums_sha256"]):
            _refuse(_BI)

    def _publication(self, ctx: dict) -> dict:
        ref = ctx["publication"]
        root, name = _split(ref["path"])
        if name != PUBLICATION_NAME:
            _refuse(_PI)
        self.qa_root = root
        publication = _json(self.private_abs(ref, _PI).raw, MAX_DOCUMENT, _PI)
        _check_publication(publication)
        self.register(publication["project_kits"])
        for item in publication["calibration_manifests"]:
            self.register(item)
        return publication

    def _project(self, ctx: dict, publication: dict) -> tuple[dict, dict]:
        table = _json(self.control(publication["project_kits"]).raw, MAX_DOCUMENT, _BI)
        _check_table(table)
        rows = table["kits"]
        _table_selectors_unique(rows)
        for row in rows:
            self.register(row["expected_receiver_binding"])
        binding = ctx["expected_binding"]
        wanted = (binding["project_id"], binding["kit_id"], binding["kit_sha256"], binding["build_sums_sha256"])
        matches = [row for row in rows if _selector(row) == wanted]
        if not matches:
            _refuse(_MS)
        if len(matches) > 1:
            _refuse(_AM)
        return matches[0], matches[0]["expected_receiver_binding"]

    def _calibration(self, ctx: dict, publication: dict, window: dict) -> tuple[dict, dict]:
        supplied, binding = ctx["calibration_manifest"], ctx["expected_binding"]
        selection = ctx["expected_calibration_selection"]
        listed = [ref for ref in publication["calibration_manifests"]
                  if self.qa_root.rstrip("/") + "/" + ref["path"] == supplied["path"]
                  and ref["sha256"] == supplied["sha256"] and ref["byte_length"] == supplied["byte_length"]]
        if len(listed) != 1:
            _refuse(_BI)  # unlisted manifest: no alternate
        if (supplied["sha256"] != binding["manifest_sha256"] or supplied["sha256"] != selection["manifest_sha256"]
                or supplied["path"] != selection["manifest_path"]):
            _refuse(_BI)
        ref = listed[0]
        manifest = _json(self.control(ref).raw, MAX_DOCUMENT, _BI)
        _whole_manifest(manifest, _CALIBRATION_PATH.fullmatch(ref["path"]).group(1))
        entries = manifest["entries"]
        for entry in entries:
            self.register(entry["expected_receiver_binding"])
        matches = [entry for entry in entries if entry["entry"] == binding["entry"]]
        if not matches:
            _refuse(_MS)
        if len(matches) > 1:
            _refuse(_AM)
        entry = matches[0]
        self._entry(ctx, manifest, entry, window)
        return entry, entry["expected_receiver_binding"]

    @staticmethod
    def _entry(ctx: dict, manifest: dict, entry: dict, window: dict) -> None:
        """Per-entry predicates of the selected entry against the independent data (else BI)."""
        kit, selection = ctx["kit_evidence"], ctx["expected_calibration_selection"]
        same_as_selection = ("entry", "build_id", "sums_sha256", "round", "copy_id", "address", "port",
                             "literal_origin", "runtime_sha256")
        checks = (
            _same(manifest["draft_kit_id"], ctx["expected_draft_kit_id"]),
            all(_same(entry[key], selection[key]) for key in same_as_selection),
            entry["sums_sha256"] == ctx["expected_binding"]["build_sums_sha256"],
            entry["build_path"] == kit["root"],
            entry["sums_file"] == kit["root"].rstrip("/") + "/" + kit["sums"]["path"],
            entry["file_count"] == kit["file_count"],
            _same(entry["runtime"], _w(window, "runtime")),
            _same(entry["literal_origin"], _w(window, "origin")),
            all(_same(entry[key], _w(window, key)) for key in ("host_dir", "app_copy_path", "data_dir")),
            all(_same(entry[key], _w(window, key)) for key in _SCHEDULE),
        )
        if not all(checks):
            _refuse(_BI)

    def _kit(self, ctx: dict, chosen: dict) -> None:
        """kit_evidence: the actual raw kit, SUMS and every declared domain file, through R1."""
        kit, binding = ctx["kit_evidence"], ctx["expected_binding"]
        root = kit["root"]
        sums = self._r1(_SM, _files.read_release_file, root, _copy(kit["sums"]), uid=self.uid, mode=CONTROL_MODE,
                        cap=MAX_DOCUMENT)
        artifact = None
        if self.route == "project":
            artifact = self._r1(_SM, _files.read_release_file, root, _copy(kit["kit"]), uid=self.uid,
                                mode=CONTROL_MODE, cap=MAX_DOCUMENT)
        for item in kit["files"]:
            self._r1(_SM, _files.read_release_file, root, _copy(item["ref"]), uid=self.uid, mode=item["mode"],
                     cap=MAX_DOCUMENT)
        if hashlib.sha256(sums.raw).hexdigest() != binding["build_sums_sha256"]:
            _refuse(_BI)
        if self.route == "project" and (hashlib.sha256(artifact.raw).hexdigest() != binding["kit_sha256"]
                                        or chosen["kit_sha256"] != binding["kit_sha256"]):
            _refuse(_BI)
        names = _sums_names(sums.raw)
        declared = {item["ref"]["path"]: item["ref"] for item in kit["files"]}
        if names is None or len(names) != kit["file_count"] or set(names) != set(declared):
            _refuse(_BI)
        if any(declared[name]["sha256"] != digest for name, digest in names.items()):
            _refuse(_BI)

    def _subjects(self, subjects: list[tuple[dict, dict]]) -> None:
        for record_ref, item in subjects:
            record = self.private_abs(record_ref, _RM)
            subject = self.private_abs(item["expected_subject"], _RM)
            if not _subject_equal(record.raw, item["byte_offset"], item["byte_length"], subject.raw):
                _refuse(_RM)

    def _closure(self, ctx: dict, binding: dict, window: dict) -> tuple[dict, dict]:
        authority = binding["authority"]
        for key in ("base", "correction", "qa_authority_order"):
            self.control(authority[key])
        for key in ("amendment", "binding_revision"):
            self.control(authority[key]["proposal"])
            self.control(authority[key]["manifest"])
        schema_reads = [self.control(binding["schemas"][key]) for key in sorted(_SCHEMA_PATHS)]
        self.control(binding["security_context"]["review"])
        self.control(binding["security_context"]["identity"])
        closure = _json(self.control(binding["source_closure"]).raw, MAX_DOCUMENT, _BI)
        _closure_shape(closure)
        roots = {item["repository"]: item["root"] for item in ctx["release_roots"]}
        repositories = closure["repositories"]
        if any(repo["id"] not in roots for repo in repositories):
            _refuse(_SM)  # a supplied release root is missing
        if set(roots) != {repo["id"] for repo in repositories} or any(
                roots[repo["id"]] != repo["root"] for repo in repositories):
            _refuse(_BI)
        node_raw: dict = {}
        for node in closure["nodes"]:
            ref = {"path": node["path"], "sha256": node["sha256"], "byte_length": node["byte_length"]}
            read = self.source(roots[node["repository"]], ref, self.uid, _NODE_MODES[node["mode"]],
                               tuple(_NODE_MODES.values()))
            if _git_blob(read.raw) != node["git_blob"]:
                _refuse(_BI)
            node_raw[node["id"]] = read.raw
        owners = {repo["id"]: repo["owner"] for repo in repositories}
        for key, path in SIX_PINS:
            pinned = [node for node in closure["nodes"] if owners[node["repository"]] == "ops" and node["path"] == path]
            if not pinned:
                _refuse(_SM)
            if len(pinned) != 1 or not _same(_w(window, key), pinned[0]["sha256"]):
                _refuse(_BI)
        schema_nodes = [node_raw[node["id"]] for node in closure["nodes"]
                        if {"schema", "catalog"} & set(node["roles"])]
        if any(read.raw not in schema_nodes for read in schema_reads):
            _refuse(_BI)  # every schema copy is byte-identical to a reviewed closure node
        self._runtime(closure["runtime"])
        return closure, self._cohort(closure["generated_closure"])

    def _runtime(self, runtime: dict) -> None:
        executable = runtime["executable"]
        root, name = _split(executable["path"])
        ref = {"path": name, "sha256": executable["sha256"], "byte_length": executable["byte_length"]}
        self.source(root, ref, runtime["executable_uid"], _EXECUTABLE_MODES[runtime["executable_mode"]],
                    tuple(_EXECUTABLE_MODES.values()))
        inventory = _json(self.control(runtime["stdlib_inventory"]).raw, MAX_DOCUMENT, _BI)
        if not _stdlib_ok(inventory):
            _refuse(_BI)
        for item in inventory:
            ref = {"path": item["path"], "sha256": item["sha256"], "byte_length": item["byte_length"]}
            self.source(runtime["stdlib_root"], ref, item["uid"], _STDLIB_MODES[item["mode"]],
                        tuple(_STDLIB_MODES.values()))

    def _cohort(self, ref: dict) -> dict:
        """The QA cohort: every file, all originals and expectations; bad and unknown cells kept as given."""
        cohort = _json(self.control(ref).raw, MAX_DOCUMENT, _BI)
        _cohort_shape(cohort)
        files = {item["path"]: (item["sha256"], item["byte_length"]) for item in cohort["files"]}
        for item in cohort["files"]:
            self.control({"path": item["path"], "sha256": item["sha256"], "byte_length": item["byte_length"]})
        for item in cohort["references"]:
            if item["from"] not in files:
                _refuse(_BI)
            if item["disposition"] == "resolved" and files.get(item["to"]) != (item["sha256"], item["byte_length"]):
                _refuse(_BI)
        originals = [{"path": item["path"], "sha256": item["sha256"], "byte_length": item["byte_length"]}
                     for item in cohort["files"] if item["kind"] == "original"]
        inventory = _json(self.control(cohort["original_inventory"]).raw, MAX_DOCUMENT, _BI)
        if not _inventory_ok(inventory) or not _same(inventory, originals):
            _refuse(_BI)
        self.control(cohort["original_index"])
        expectations = _json(self.control(cohort["old_to_new_expectations"]).raw, MAX_DOCUMENT, _BI)
        if not _expectations_ok(expectations):
            _refuse(_BI)
        original_paths = {item["path"] for item in originals}
        if any(item["original_path"] not in original_paths
               or (item["new_path"] is not None and item["new_path"] not in files) for item in expectations):
            _refuse(_BI)
        if original_paths - {item["original_path"] for item in expectations}:
            _refuse(_BI)  # every original has its expectation
        return cohort


def _recheck(reads: tuple) -> None:
    for start in range(0, len(reads), _RECHECK_BATCH):
        refused = None
        try:
            _files.recheck_files(reads[start:start + _RECHECK_BATCH])
        except _files.TargetRefused as exc:
            refused = _SD if exc.code == _SD else _EI
        if refused is not None:
            _refuse(refused)


def _identities(candidate: CandidateTarget) -> bool:
    """Re-derive the candidate's identities from its own retained bytes."""
    reads = candidate.reads
    if not reads or any(hashlib.sha256(read.raw).hexdigest() != read.ref["sha256"]
                        or len(read.raw) != read.ref["byte_length"] for read in reads):
        return False
    by_name = {(read.root, read.ref["path"]): read for read in reads}
    selection = candidate.selection
    window_root, window_name = _split(selection["window"]["path"])
    first = reads[0]
    if (first.root, first.ref["path"]) != (window_root, window_name) or \
            first.ref["sha256"] != candidate.expected_window_sha256:
        return False
    kit = selection["kit_evidence"]
    sums = by_name.get((kit["root"], kit["sums"]["path"]))
    if sums is None or hashlib.sha256(sums.raw).hexdigest() != candidate.expected_binding["build_sums_sha256"]:
        return False
    if candidate.route == "project":
        artifact = by_name.get((kit["root"], kit["kit"]["path"]))
        if artifact is None or hashlib.sha256(artifact.raw).hexdigest() != candidate.expected_binding["kit_sha256"]:
            return False
    for item in selection["record_subjects"]:
        record = by_name.get(_split(item["record"]["path"]))
        subject = by_name.get(_split(item["expected_subject"]["path"]))
        if record is None or subject is None or not _subject_equal(
                record.raw, item["byte_offset"], item["byte_length"], subject.raw):
            return False
    return True


# ---------------------------------------------------------------------------
# A3 loaders and the recheck.

def load_project_candidate(data_context: object, *, uid: int) -> CandidateTarget:
    """Load the exact project route from explicit data; returns UNTRUSTED data only."""
    return _Loader("project", uid).run(data_context)


def load_calibration_candidate(data_context: object, *, uid: int) -> CandidateTarget:
    """Load the exact calibration route from explicit data; returns UNTRUSTED data only."""
    return _Loader("calibration", uid).run(data_context)


def recheck_candidate(candidate: CandidateTarget, boundary: str) -> None:
    """Recheck every R1 observation and identity at load-complete, receiving or before-count.

    Returns None when nothing changed. Trust never changes: the candidate stays
    UNTRUSTED and its native checks stay unresolved.
    """
    if type(candidate) is not CandidateTarget or type(boundary) is not str or boundary not in BOUNDARIES:
        _refuse(_EI)
    _recheck(candidate.reads)
    if not _identities(candidate):
        _refuse(_EI)
