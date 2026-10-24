"""Offline bound assessor for Project 3 host receipts (P5; r5 ABI A6, A6.1-A6.3, A7).

H-P3-P5-1 (Architecture #249)
- Wrong (evidence): the only receipt judge, ops_host_client.py (c537bed9, read
  only), reads ops-host-inspect/1 through its own reader, parses receipt numbers
  through binary floats, accepts only uuid4, blocks every Env miss and has no
  prior-Env carry, per-leg start/finish order or BLOCKED-over-FAIL leg rule.
- Change: this new module. It reads the armed window FIRST through the received
  P1 reader (R1) with its declared length, loads the candidate through P2 (R2),
  decodes every inspect edge through P3 (R3'), compares Env through P4 (R4) and
  implements A6.1-A6.3, A7 and HOME's three per-leg order additions freshly.
- Expected: every F5 row and HOME addition gets its exact verdict and code.
- Disproved if: any of them does not, or a bite does not flip its own case.

Two calls, nothing else:
- load_bound_candidate_window(path, window_sha256, *, data_context, uid)
- judge_candidate_receipt(request_raw, receipt_ref, *, window, now)

Everything returned is UNTRUSTED data. A verdict here is only an offline
comparison of a receipt with QA's rules: it is never counted, adopted or a row
PASS, and every native check stays unresolved. The module writes nothing, runs
nothing, opens no socket and never reads a file except through R1.
docs/architecture/ops-host-client-bound.md has the whole contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import ops_host_binding as _binding  # noqa: E402  (R2, the received P2 loader)
import ops_host_env as _env  # noqa: E402  (R4, the received P4 comparator)
import ops_host_inspect as _inspect  # noqa: E402  (R3', the received /2 decoder)

# R1 is the very reader object R2 reads with, so FileRead types and rechecks agree.
_files = _binding._files

for _module, _name in ((_files, "ops_host_binding_files.py"), (_binding, "ops_host_binding.py"),
                       (_inspect, "ops_host_inspect.py"), (_env, "ops_host_env.py")):
    if Path(_module.__file__).resolve() != _HERE / _name:
        raise ImportError("P5 uses only the received R1-R4 modules next to it")

__all__ = [
    "CODES",
    "NONE",
    "TRUST",
    "UNRESOLVED_NATIVE_CHECKS",
    "VERDICTS",
    "CandidateWindow",
    "TargetRefused",
    "UntrustedAssessment",
    "judge_candidate_receipt",
    "load_bound_candidate_window",
]

# ABI A7: the eleven codes, in A7 order.
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
# _IU, _MS, _AM and _RM are vocabulary here: R2 may raise them while loading.
_CM, _IU, _PI, _MS, _AM, _BI, _SI, _SM, _SD, _RM, _EI = CODES

NONE = "NONE"
TRUST = "UNTRUSTED"
VERDICTS = ("PASS", "FAIL", "BLOCKED")
PASS, FAIL, BLOCKED = VERDICTS

# Never resolved here (ABI A6/A7 L1-L6): R2's five, then P5's own.
UNRESOLVED_NATIVE_CHECKS = _binding.REQUIRED_NATIVE_CHECKS + (
    "NATIVE_PRIOR_RECEIPT_ISSUER_SCOPE_AND_JOB",
    "ACTUAL_INSPECT2_PRODUCER_VALIDATOR_CORPUS_AND_CALLER_COMPATIBILITY",
    "COUNTED_ADMISSION_AND_ROW_RESULT",
)

# A1 and host-publication-v2 limits.
WINDOW_MAX = _binding.MAX_DOCUMENT
REQUEST_MAX = 65536
RECEIPT_MAX = 16384
INSPECT_MAX = _inspect.MAX_INSPECT_BYTES
LISTING_MAX = 1048576
AUDIT_MAX = 262144
AUDIT_ENTRIES_MAX = 1024
LISTING_ENTRIES_MAX = 10000
IDENTITIES_MAX = 256

ADDRESS = "100.110.162.4"
ZERO_INSTANT = "0001-01-01T00:00:00Z"
_SECOND = 1_000_000  # instants are integer microseconds
HEALTH_LIMIT = Decimal("30.000")
STOP_LIMIT = Decimal("10.000")
BAND = Decimal("0.001")  # TD-1: one named constant, inclusive
CADENCE_GAP_US = 750_000
PROBE_TIMEOUT = 3

REQUEST_SCHEMA = "ops-host-request/1"
RECEIPT_SCHEMA = "ops-host-receipt/1"
LISTING_SCHEMA = "ops-host-listing/1"
AUDIT_SCHEMA = "start-audit/1"
# Proposed successors this module does not support (A6.3): fixed SOURCE_MISSING.
UNSUPPORTED_REQUEST_SCHEMAS = ("ops-host-request/2",)
UNSUPPORTED_RECEIPT_SCHEMAS = ("ops-host-receipt/3",)
UNSUPPORTED_OPERATIONS = ("engine-image", "launch-cases", "stop-graceful", "stop", "list", "LIST")
UNSUPPORTED_ROWS = ("W-IMG", "HOST-L", "LIST")
TARGET2_KEY = "operation_binding"

# host-publication-v2 section 3.1: writer -> row -> operation (supported rows only).
ROWS = {
    "checker": {"R-1": "restart", "R-1i": "restart", "D-1": "crash", "D-5": "start"},
    "api-check": {"API-D-1": "crash", "API-D-5": "start"},
}
ROW_SIGNAL = {"R-1": "TERM", "R-1i": "INT", "D-1": "KILL", "API-D-1": "KILL"}
PRIOR_CRASH = {"D-5": ("D-1", "checker"), "API-D-5": ("API-D-1", "api-check")}

REQUEST_KEYS = frozenset(("schema", "binding", "window_id", "row", "operation", "host_action", "writer",
                          "request_id", "origin", "receipt_file", "action", "expected", "since", "not_before",
                          "expires_at", "sequence", "wait_seconds", "receipt_format", "write"))
COMMON_KEYS = frozenset(("schema", "row", "operation", "host_action", "writer", "request_id", "window_id",
                         "sequence", "sequence_used", "expected_sequence", "binding", "request_sha256",
                         "controller_sha256", "executor_sha256", "sums_sha256", "done", "decision",
                         "failure_kind", "by", "note", "reason", "at", "seen_at", "started_at", "ended_at", "lane",
                         "app_container_id", "fwd_container_id", "exit_code", "window_ttl_minutes",
                         "window_expires_at", "bytes_used"))
STOP_KEYS = ("signal", "signal_sent_at", "exited_at", "seconds_to_exit", "within_10s", "forced_kill",
             "kill_sent_at", "stopped_line_seen", "stopped_line_at", "traceback_seen", "traceback_line",
             "traceback_first_at", "data_listing_after_exit", "stop_inspect")
START_KEYS = ("start_sent_at", "app_started_at", "health_at", "health_code", "seconds_to_health",
              "health_elapsed_seconds", "health_observation", "identity_evidence", "prior_exit_evidence",
              "data_listing_after_exit", "data_listing_before_start", "listings_match", "start_audit_ref",
              "audit_started_at", "audit_ended_at", "audit_complete", "listener_present")
LEG_KEYS = frozenset(("leg", "decision", "failure_kind", "started_at", "ended_at", "exit_code", "evidence"))
OPTIONAL_KEYS = frozenset(("exit_status", "data_dir", "data_dev", "data_inode", "data_mode", "data_listing",
                           "app_copy_changes", "tmp_listing", "work_listing", "data_tree_sha256_before",
                           "todo_db_sha256", "todo_db_sha256_after_exit", "todo_db_sha256_before_start",
                           "todo_db_header_18_19", "listener_before", "listener_after_stop",
                           "listener_after_start", "ss_line", "listener_present", "listener_gone",
                           "origin_refused", "same_inode", "listings_match", "commands", "stdout", "stderr",
                           "stdout_sha256", "stderr_sha256", "attempts", "op_status", "app_state", "fwd_state"))
REJECTED_ALIASES = frozenset(("signal_at", "exit_at", "stopped_seen", "answered_at", "data_dir_device",
                              "data_dir_inode", "data_dir_mode", "listing_after_exit", "listing_before_start",
                              "answered_within_30s", "get_root_status", "commands_run", "data_dev_inode_before",
                              "data_dev_inode_after", "oom_killed", "restart_count", "expected_image_id",
                              "image_matches"))
REQUIRED_ROOT = {
    "crash": frozenset(("exit_status", "listener_gone", "origin_refused", "signal", "kill_sent_at", "exited_at",
                        "data_listing_after_exit", "stop_inspect")),
    "start": frozenset(START_KEYS) | {"same_inode"},
    "restart": frozenset(("legs", "listener_gone")),
}
ALLOWED_ROOT = {
    "crash": OPTIONAL_KEYS | frozenset(STOP_KEYS),
    "start": OPTIONAL_KEYS | frozenset(START_KEYS),
    "restart": (OPTIONAL_KEYS - frozenset(START_KEYS) - frozenset(STOP_KEYS) - {"same_inode"}) | {"legs"},
}
OPTIONAL_LISTINGS = ("data_listing", "app_copy_changes", "tmp_listing", "work_listing")
BYTES_KEYS = frozenset(("app_copy", "data", "tmp", "work", "total", "complete", "measured_at"))
LISTING_KEYS = frozenset(("schema", "window_id", "target", "path", "observed_at", "entries", "entry_count",
                          "truncated", "complete", "error", "tree_sha256", "todo_db_sha256", "todo_db_header_18_19"))
ENTRY_KEYS = frozenset(("name", "type", "size", "mtime_ns", "target", "target_truncated", "sha256"))
ENTRY_TYPES = ("regular", "directory", "link", "fifo", "socket", "device")
OBSERVATION_KEYS = frozenset(("method", "path", "host", "outcome", "probe_count", "first_probe_at",
                              "last_probe_at", "observed_until", "elapsed_seconds", "last_http_status",
                              "complete"))
AUDIT_KEYS = frozenset(("schema", "window_id", "writer", "request_id", "sequence", "row", "operation",
                        "commands_run"))
RUN_KEYS = frozenset(("kind", "op", "started_at", "ended_at", "exit_code", "argv", "params", "result"))
IDENTITY_KEYS = frozenset(("container_id", "creation_record", "before_inspect", "after_inspect",
                           "before_matches_creation", "after_matches_creation"))
PRIOR_KEYS = frozenset(("kind", "row", "writer", "request_id", "sequence", "sha256", "byte_length"))
# host-publication-v2 BINDINGS window (O 6.6): the closed armed-window key set.
WINDOW_KEYS = frozenset((
    "window_id", "host_dir", "origin", "binding", "runtime", "row_table", "window_started_at",
    "scheduled_use_minutes", "schedule_source", "schedule_sha256", "window_ttl_minutes", "window_expires_at",
    "bytes_used", "app_container_id", "fwd_container_id", "network_ids", "creation_inspect",
    "calibration_selection", "data_dir", "data_dev", "data_inode", "data_mode", "security_receipt_path",
    "security_receipt_sha256", "controller_sha256", "executor_sha256", "ops_host_sha256", "probe_client_sha256",
    "forward_py_sha256", "case_list_sha256", "case_list_path", "app_copy_path", "receipts_log_path",
    "init_check", "port_copy_map"))
PROJECT_CONTEXT = frozenset(("window", "publication", "m01_record", "m02_record", "security_records",
                             "expected_window_sha256", "expected_binding", "release_roots", "kit_evidence",
                             "record_subjects"))
CALIBRATION_CONTEXT = PROJECT_CONTEXT | {"calibration_manifest", "expected_draft_kit_id",
                                         "expected_calibration_selection"}
# Runtime 23 (ABI A6.3): the 22 immutable members, then env.
IMMUTABLE_RUNTIME = ("image_id", "command", "workdir", "user", "mounts", "tmpfs", "read_only_root", "cap_drop",
                     "cap_add", "security_options", "privileged", "devices", "pid_mode", "ipc_mode", "uts_mode",
                     "init", "limits", "restart_policy", "ports", "networks", "data_bind", "image_env")
TARGETS = ("app", "forwarder")

_HEX = re.compile(r"[0-9a-f]{64}")
_LEAF = re.compile(r"[A-Za-z0-9._-]{1,128}")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
                      r"(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})")
_ORIGIN = re.compile(r"http://100\.110\.162\.4:([0-9]{4})")


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


# The received classes P5 catches by identity; a stranger's .code is never read.
_RECEIVED_REFUSALS = (TargetRefused, _files.TargetRefused, _binding.TargetRefused, _inspect.TargetRefused,
                      _env.TargetRefused)


# ---------------------------------------------------------------------------
# Results.

@dataclass(frozen=True, slots=True, repr=False)
class CandidateWindow:
    """Immutable UNTRUSTED data: the frozen armed window, R2's candidate and the R1 reads."""

    trust: str
    window: Any
    target: Any
    reads: tuple

    def __post_init__(self) -> None:
        if (type(self.trust) is not str or self.trust != TRUST or type(self.window) is not MappingProxyType
                or type(self.target) is not _binding.CandidateTarget or type(self.reads) is not tuple
                or len(self.reads) != len(self.target.reads) + 1
                or not all(type(read) is _files.FileRead for read in self.reads)):
            raise TypeError("a CandidateWindow is UNTRUSTED data with its R1 reads")

    def __repr__(self) -> str:
        return f"CandidateWindow(trust={self.trust!r}, reads={len(self.reads)})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class UntrustedAssessment:
    """An offline comparison result: never counted, never a row PASS."""

    trust: str
    verdict: str
    code: str
    identities: tuple

    def __post_init__(self) -> None:
        ok = type(self.trust) is str and self.trust == TRUST and type(self.verdict) is str \
            and self.verdict in VERDICTS and type(self.code) is str
        if ok:
            ok = self.code == NONE if self.verdict in (PASS, FAIL) else self.code in CODES
        if ok:
            ok = type(self.identities) is tuple and len(self.identities) <= IDENTITIES_MAX and all(
                type(item) is tuple and len(item) == 2 and type(item[0]) is str and _is_hex(item[1])
                for item in self.identities)
        if not ok:
            raise TypeError("PASS and FAIL carry NONE; BLOCKED carries one of the eleven codes")


# ---------------------------------------------------------------------------
# Atoms. Pure: no filesystem call.

def _is_hex(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _is_str(value: object) -> bool:
    return type(value) is str and value != "" and "\x00" not in value


def _is_int(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _is_abs(value: object) -> bool:
    """An absolute canonical path: no empty, '.' or '..' part, no trailing slash."""
    if not _is_str(value) or not value.startswith("/") or value == "/" or value.endswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in value[1:].split("/"))


def _keys(value: object, keys: frozenset | set) -> bool:
    return isinstance(value, Mapping) and set(value) == set(keys)


def _same(a: object, b: object) -> bool:
    """Exact JSON-value equality: types matter (True is not 1), order of arrays matters."""
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return set(a) == set(b) and all(_same(a[key], b[key]) for key in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _unique_pairs(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON name")
        out[key] = value
    return out


def _no_constant(_text: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _loads(raw: object, cap: int, code: str = _EI) -> Any:
    """Strict JSON: exact bytes, UTF-8 without BOM, unique names, no NaN/Infinity.

    A JSON number with a fraction or exponent becomes a Decimal built from its
    original text (TD-1); an integer stays an int.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= cap:
        _refuse(code)
    try:
        text = raw.decode("utf-8")
        if text.startswith("\ufeff"):
            raise ValueError("BOM")
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_float=Decimal, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        _refuse(code)


def _number(value: object, *, low: Decimal | None = Decimal(0)) -> Decimal:
    """A JSON number from its text: int or finite Decimal, never bool, string or null."""
    if type(value) is int:
        number = Decimal(value)
    elif type(value) is Decimal and value.is_finite():
        number = value
    else:
        _refuse(_EI)
    if low is not None and number < low:
        _refuse(_EI)
    return number


def _days_from_civil(year: int, month: int, day: int) -> int:
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _month_days(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _parse_instant(value: object, ms: bool) -> int | None:
    if type(value) is not str:
        return None
    match = _INSTANT.fullmatch(value)
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match[i]) for i in range(1, 7))
    fraction, offset = match[7] or "", match[8]
    if ms and len(fraction) < 3:
        return None
    if not (1 <= month <= 12 and 1 <= day <= _month_days(year, month) and hour <= 23 and minute <= 59
            and second <= 59):
        return None
    shift = 0
    if offset != "Z":
        if offset == "-00:00":
            return None
        oh, om = int(offset[1:3]), int(offset[4:6])
        if oh > 23 or om > 59:
            return None
        shift = (oh * 3600 + om * 60) * (1 if offset[0] == "+" else -1)
    seconds = _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second - shift
    nanos = int((fraction + "000000000")[:9])
    return seconds * _SECOND + nanos // 1000  # integer microseconds (TD-1)


_ZERO_US = _parse_instant(ZERO_INSTANT, False)


def _instant(value: object, *, ms: bool = False) -> int:
    """Offset-aware instant -> integer microseconds since the epoch, else EVIDENCE_INVALID."""
    parsed = _parse_instant(value, ms)
    if parsed is None or parsed == _ZERO_US:
        _refuse(_EI)
    return parsed


def _event(value: object) -> int | None:
    """An inspect state time: integer microseconds, or None for Docker's zero sentinel (no event)."""
    parsed = _parse_instant(value, False)
    if parsed is None:
        _refuse(_EI)
    return None if parsed == _ZERO_US else parsed


def _seconds(delta_us: int) -> Decimal:
    return Decimal(delta_us) / Decimal(_SECOND)


def _uuid(value: object) -> str:
    """A canonical lowercase hyphenated UUID of ANY version (A6.3)."""
    if type(value) is not str or len(value) != 36:
        _refuse(_EI)
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        _refuse(_EI)
    if str(parsed) != value:
        _refuse(_EI)
    return value


def _ref(value: object, cap: int) -> dict:
    if not _keys(value, {"path", "sha256", "byte_length"}) or not _is_str(value["path"]) \
            or not _is_hex(value["sha256"]) or not _is_int(value["byte_length"], 1, cap):
        _refuse(_EI)
    return {"path": value["path"], "sha256": value["sha256"], "byte_length": value["byte_length"]}


def _split(path: str) -> tuple[str, str]:
    root, _, name = path.rpartition("/")
    return root, name


# ---------------------------------------------------------------------------
# Bite seams: each is the one place its rule is decided (F5-BITE-*).

def _decode_inspect(raw: bytes, *, window_id: str, container_id: str, target: str) -> Any:
    """Every inspect edge goes through the received fixed /2 decoder (R3')."""
    return _inspect.parse_inspect2(raw, window_id=window_id, container_id=container_id, target=target).snapshot


def _same_side(reported: Decimal, computed: Decimal, limit: Decimal) -> bool:
    """TD-1 point 1: a limit is decided only when both values fall on the same side of it."""
    return (reported <= limit) == (computed <= limit)


def _deadline_measures(first200_delta: Decimal, seconds_to_health: Decimal, observed_delta: Decimal,
                       health_elapsed: Decimal) -> tuple[Decimal, Decimal]:
    """TD-1 event distinction: only first200 and its own seconds_to_health decide the deadline."""
    return first200_delta, seconds_to_health


def _carry_prior(own: str, prior_failed: bool) -> str:
    """A6.1: a truthful complete prior crash with Env false carries FAIL through the later start."""
    return FAIL if own == FAIL or prior_failed else PASS


def _combine(outcomes: list) -> tuple[str, str]:
    """A6.1 restart precedence: any BLOCKED dominates, else any FAIL, else PASS."""
    for verdict, code in outcomes:
        if verdict == BLOCKED:
            return BLOCKED, code
    if any(verdict == FAIL for verdict, _ in outcomes):
        return FAIL, NONE
    return PASS, NONE


# ---------------------------------------------------------------------------
# A6 / A3.1: the window, read FIRST.

def _load_arguments(path: object, window_sha256: object, data_context: object, uid: object) -> str:
    """Closed shape of every argument, without a filesystem call; returns the route."""
    if not _is_abs(path) or not _is_hex(window_sha256) or not _is_int(uid, 0) or type(data_context) is not dict:
        _refuse(_CM)
    keys = set(data_context)
    route = "project" if keys == PROJECT_CONTEXT else "calibration" if keys == CALIBRATION_CONTEXT else None
    if route is None:
        _refuse(_CM)
    ref = data_context["window"]
    if type(ref) is not dict or set(ref) != {"path", "sha256", "byte_length"} or not _is_abs(ref["path"]) \
            or not _is_hex(ref["sha256"]) or not _is_int(ref["byte_length"], 1, WINDOW_MAX) \
            or not _is_hex(data_context["expected_window_sha256"]):
        _refuse(_CM)
    if ref["path"] != path or ref["sha256"] != window_sha256 or data_context["expected_window_sha256"] != window_sha256:
        _refuse(_BI)
    return route


def _read_window(ref: dict, uid: int) -> Any:
    """P1-read the exact window Ref with its declared length: the first file this module touches."""
    root, name = _split(ref["path"])
    refused = None
    try:
        read = _files.read_private_file(root, {"path": name, "sha256": ref["sha256"],
                                               "byte_length": ref["byte_length"]}, uid=uid, cap=WINDOW_MAX)
    except _files.TargetRefused as exc:
        refused = _SD if exc.code == _SD else _PI
    if refused is not None:
        _refuse(refused)
    return read


def _load_candidate(route: str, data_context: dict, uid: int) -> Any:
    loader = _binding.load_project_candidate if route == "project" else _binding.load_calibration_candidate
    refused = None
    try:
        candidate = loader(data_context, uid=uid)
    except _binding.TargetRefused as exc:
        refused = exc.code
    if refused is not None:
        _refuse(refused)
    return candidate


def _window_ok(window: object, route: str) -> bool:
    """The closed O 6.6 window: every member typed, TTL and bytes consistent."""
    if not _keys(window, WINDOW_KEYS):
        return False
    w = window
    match = _ORIGIN.fullmatch(w["origin"]) if type(w["origin"]) is str else None
    if match is None or not 8970 <= int(match[1]) <= 8979:
        return False
    port = int(match[1])
    if not (_is_str(w["window_id"]) and _is_abs(w["host_dir"]) and type(w["binding"]) is dict
            and type(w["row_table"]) is dict and _is_hex(w["app_container_id"]) and _is_hex(w["fwd_container_id"])
            and w["app_container_id"] != w["fwd_container_id"]):
        return False
    runtime = w["runtime"]
    if not (_keys(runtime, {"image", "command", "internal_port", "workdir", "env"}) and _is_str(runtime["image"])
            and _same(runtime["command"], ["python3", "/app/server.py"]) and _same(runtime["internal_port"], 8000)
            and _same(runtime["workdir"], "/app")
            and _same(runtime["env"], {"HOST": "0.0.0.0", "PORT": "8000", "DATA_DIR": "/data",
                                       "ALLOWED_HOSTS": f"{ADDRESS}:{port},scanapp:8080"})):
        return False
    start = _parse_instant(w["window_started_at"], False)
    end = _parse_instant(w["window_expires_at"], False)
    schedule = (w["scheduled_use_minutes"], w["schedule_source"], w["schedule_sha256"])
    if all(item is None for item in schedule):
        ttl = 480
    elif _is_int(schedule[0], 0) and _is_str(schedule[1]) and _is_hex(schedule[2]):
        ttl = min(schedule[0] + 30, 720)
    else:
        return False
    if start is None or end is None or not _is_int(w["window_ttl_minutes"], 1, 720) \
            or w["window_ttl_minutes"] != ttl or end != start + ttl * 60 * _SECOND:
        return False
    if not _bytes_used_ok(w["bytes_used"]):
        return False
    ids = w["network_ids"]
    if type(ids) is not list or not all(map(_is_hex, ids)) or len(set(ids)) != len(ids):
        return False
    creation = w["creation_inspect"]
    if not _keys(creation, set(TARGETS)) or not all(_evidence_path_ok(w, creation[t], INSPECT_MAX) for t in TARGETS):
        return False
    if not (w["calibration_selection"] is None if route == "project" else type(w["calibration_selection"]) is dict):
        return False
    data_dir = w["data_dir"]
    if not (_is_abs(data_dir) and data_dir.startswith(w["host_dir"] + "/") and data_dir != "/data"
            and _is_int(w["data_dev"], 0) and _is_int(w["data_inode"], 0) and _same(w["data_mode"], 0o700)):
        return False
    if not (_is_abs(w["security_receipt_path"]) and _is_hex(w["security_receipt_sha256"])
            and all(_is_hex(w[key]) for key, _ in _binding.SIX_PINS)
            and all(_is_abs(w[key]) for key in ("case_list_path", "app_copy_path", "receipts_log_path"))):
        return False
    init = w["init_check"]
    if not (_keys(init, {"host_config_init", "docker_top_child", "observed_at"})
            and type(init["host_config_init"]) is bool and type(init["docker_top_child"]) is str
            and _parse_instant(init["observed_at"], False) is not None):
        return False
    copies = w["port_copy_map"]
    if type(copies) is not list or not 1 <= len(copies) <= 10:
        return False
    for item in copies:
        if not (_keys(item, {"port", "copy_id", "sums_sha256"}) and _is_int(item["port"], 8970, 8979)
                and _is_str(item["copy_id"]) and _is_hex(item["sums_sha256"])):
            return False
    ports = [item["port"] for item in copies]
    return len(set(ports)) == len(ports) and port in ports


def _bytes_used_ok(value: object) -> bool:
    if not _keys(value, BYTES_KEYS):
        return False
    parts = [value[key] for key in ("app_copy", "data", "tmp", "work")]
    if not all(item is None or _is_int(item, 0) for item in parts + [value["total"]]):
        return False
    if type(value["complete"]) is not bool or _parse_instant(value["measured_at"], False) is None:
        return False
    if value["complete"]:
        return None not in parts and value["total"] == sum(parts)
    return value["total"] is None


def _evidence_path_ok(window: Mapping, ref: object, cap: int) -> bool:
    if not _keys(ref, {"path", "sha256", "byte_length"}) or not _is_hex(ref["sha256"]) \
            or not _is_int(ref["byte_length"], 1, cap) or type(ref["path"]) is not str:
        return False
    root, name = _split(ref["path"])
    return root == window["host_dir"] + "/evidence" and _LEAF.fullmatch(name) is not None \
        and name not in (".", "..")


def _six_pins(candidate: Any) -> dict:
    """The six window pins re-derived from R2's retained closure (unchanged since load)."""
    closure = candidate.source_closure["closure"]
    owners = {repo["id"]: repo["owner"] for repo in closure["repositories"]}
    pins = {}
    for key, path in _binding.SIX_PINS:
        nodes = [node for node in closure["nodes"] if owners[node["repository"]] == "ops" and node["path"] == path]
        if len(nodes) != 1:
            _refuse(_BI)
        pins[key] = nodes[0]["sha256"]
    return pins


def _cross_check(window: dict, read: Any, candidate: Any, route: str, window_sha256: str) -> None:
    """Window against the candidate: same bytes, hash, binding, selection and six pins."""
    first = candidate.reads[0]
    if first.raw != read.raw or candidate.expected_window_sha256 != window_sha256 \
            or hashlib.sha256(read.raw).hexdigest() != window_sha256:
        _refuse(_BI)
    if not _same(window["binding"], candidate.expected_binding):
        _refuse(_BI)
    if route == "calibration":
        selection = candidate.selection["calibration_selection"]
        if not _same(window["calibration_selection"], selection) \
                or window["origin"] != selection["literal_origin"] \
                or window["security_receipt_path"] != selection["security_receipt_path"] \
                or window["security_receipt_sha256"] != selection["security_receipt_sha256"]:
            _refuse(_BI)
    pins = _six_pins(candidate)
    if any(window[key] != value for key, value in pins.items()):
        _refuse(_BI)


def _recheck_reads(reads: tuple) -> None:
    for start in range(0, len(reads), 65536):
        refused = None
        try:
            _files.recheck_files(reads[start:start + 65536])
        except _files.TargetRefused as exc:
            refused = _SD if exc.code == _SD else _EI
        if refused is not None:
            _refuse(refused)


def _recheck_candidate(candidate: Any, boundary: str) -> None:
    refused = None
    try:
        _binding.recheck_candidate(candidate, boundary)
    except _binding.TargetRefused as exc:
        refused = exc.code
    if refused is not None:
        _refuse(refused)


def load_bound_candidate_window(path: str, window_sha256: str, *, data_context: object, uid: int) -> CandidateWindow:
    """Read the pinned armed window FIRST, then load and cross-check R2's candidate.

    Refuses with this module's TargetRefused; the result is UNTRUSTED data with
    every native check unresolved.
    """
    route = _load_arguments(path, window_sha256, data_context, uid)
    read = _read_window(data_context["window"], uid)
    window = _loads(read.raw, WINDOW_MAX, _PI)
    if type(window) is not dict:
        _refuse(_PI)
    candidate = _load_candidate(route, data_context, uid)
    if not _window_ok(window, route):
        _refuse(_EI)
    _cross_check(window, read, candidate, route, window_sha256)
    _recheck_candidate(candidate, "load-complete")
    _recheck_reads((read,))
    return CandidateWindow(trust=TRUST, window=_freeze(window), target=candidate, reads=(read, *candidate.reads))


# ---------------------------------------------------------------------------
# One judgment: the context every edge goes through.

class _Judge:
    """One receipt judgment; every FILE edge routes through R1, every inspect through R3'."""

    def __init__(self, window: CandidateWindow, now_us: int) -> None:
        self.cw = window
        self.w = window.window
        self.uid = window.reads[0].uid
        self.now_us = now_us
        self.host_dir = self.w["host_dir"]
        self.port = int(_ORIGIN.fullmatch(self.w["origin"])[1])
        self.host = f"{ADDRESS}:{self.port}"
        self.reads: list = []
        self.identities: list = []
        self.cache: dict = {}
        self.creations: dict = {}
        self.ids = {"app": self.w["app_container_id"], "forwarder": self.w["fwd_container_id"]}

    def identity(self, label: str, sha256: str) -> None:
        item = (label, sha256)
        if item not in self.identities and len(self.identities) < IDENTITIES_MAX:
            self.identities.append(item)

    def read(self, root: str, name: str, ref: dict, cap: int, label: str) -> bytes:
        refused = None
        try:
            read = _files.read_private_file(root, {"path": name, "sha256": ref["sha256"],
                                                   "byte_length": ref["byte_length"]}, uid=self.uid, cap=cap)
        except _files.TargetRefused as exc:
            refused = _SD if exc.code == _SD else _EI
        if refused is not None:
            _refuse(refused)
        self.reads.append(read)
        self.identity(label, ref["sha256"])
        return read.raw

    def evidence(self, ref: object, cap: int) -> bytes:
        """A controller snapshot under host_dir/evidence, by its exact ref."""
        if not _evidence_path_ok(self.w, ref, cap):
            _refuse(_EI)
        key = (ref["path"], ref["sha256"], ref["byte_length"])
        if key not in self.cache:
            _, name = _split(ref["path"])
            self.cache[key] = self.read(self.host_dir + "/evidence", name, ref, cap, "evidence")
        return self.cache[key]

    # --- inspect edges (R3') and the runtime23 partition (A6.3)

    def snapshot(self, ref: object, target: str) -> Any:
        raw = self.evidence(ref, INSPECT_MAX)
        return _decode_inspect(raw, window_id=self.w["window_id"], container_id=self.ids[target], target=target)

    def creation(self, target: str) -> Any:
        """The window's recorded creation snapshot, bound to the window's runtime and data."""
        if target not in self.creations:
            snap = self.snapshot(self.w["creation_inspect"][target], target)
            runtime = snap["runtime"]
            if target == "app":
                bind = runtime["data_bind"]
                if not (_same(runtime["command"], self.w["runtime"]["command"])
                        and _same(runtime["workdir"], self.w["runtime"]["workdir"])
                        and bind["source"] == self.w["data_dir"] and bind["destination"] == "/data"):
                    _refuse(_EI)
            # The recorded creation Env must itself be the bound Env (image baseline, plus the
            # four APP overrides): an unbound creation array is evidence, never an Env miss.
            bound = _env.compare_window_env(runtime["image_env"], runtime["env"], runtime["env"], target=target,
                                            port=self.port)
            if bound.env_matches is not True:
                _refuse(_EI)
            self.creations[target] = snap
        return self.creations[target]

    def edge(self, snap: Any, target: str) -> bool:
        """Non-Env runtime22 must equal creation (else BLOCKED); returns R4's env_matches.

        R4 checks the creation array against the expected map and the edge array
        against the creation array, token by token, in one call.
        """
        recorded = self.creation(target)["runtime"]
        runtime = snap["runtime"]
        if any(not _same(runtime[key], recorded[key]) for key in IMMUTABLE_RUNTIME):
            _refuse(_EI)
        env = _env.compare_window_env(recorded["image_env"], recorded["env"], runtime["env"], target=target,
                                      port=self.port)
        return env.env_matches is True

    def terminal(self, ref: object, exit_code: int, exited: int, sent: int, begin: int, end: int) -> bool:
        """The app's own terminal poll for this stop or crash (CORRECTION-1 C87-93)."""
        if ref is None:
            _refuse(_EI)
        snap = self.snapshot(ref, "app")
        state = snap["state"]
        started, finished = _event(state["started_at"]), _event(state["finished_at"])
        observed = _instant(snap["observed_at"], ms=True)
        if state["running"] is not False or state["status"] != "exited" or state["exit_code"] != exit_code \
                or state["oom_killed"] is not False:
            _refuse(_EI)
        # HOME F5-LEG-ORDER-STOP: a real exit, at or after a real start.
        if started is None or finished is None or finished < started or finished != exited:
            _refuse(_EI)
        if not begin <= sent <= exited <= observed <= end:
            _refuse(_EI)
        return self.edge(snap, "app")

    # --- listings

    def listing(self, ref: object, *, data: bool = True) -> Any:
        doc = _loads(self.evidence(ref, LISTING_MAX), LISTING_MAX)
        if not _keys(doc, LISTING_KEYS) or doc["schema"] != LISTING_SCHEMA or doc["window_id"] != self.w["window_id"]:
            _refuse(_EI)
        if data and (doc["target"] != "data" or doc["path"] != self.w["data_dir"]):
            _refuse(_EI)
        _instant(doc["observed_at"])
        if doc["truncated"] is not False or doc["error"] is not None or doc["complete"] is not True:
            _refuse(_EI)
        entries = doc["entries"]
        if type(entries) is not list or not _is_int(doc["entry_count"], 0, LISTING_ENTRIES_MAX) \
                or doc["entry_count"] != len(entries):
            _refuse(_EI)
        names = []
        for entry in entries:
            if not (_keys(entry, ENTRY_KEYS) and _is_str(entry["name"]) and entry["type"] in ENTRY_TYPES
                    and (entry["size"] is None or _is_int(entry["size"], 0))
                    and (entry["mtime_ns"] is None or _is_int(entry["mtime_ns"], 0))
                    and (entry["target"] is None or type(entry["target"]) is str)
                    and type(entry["target_truncated"]) is bool
                    and (entry["sha256"] is None or _is_hex(entry["sha256"]))):
                _refuse(_EI)
            names.append(entry["name"])
        if any(a >= b for a, b in zip(names, names[1:], strict=False)):
            _refuse(_EI)
        tree = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
        header = doc["todo_db_header_18_19"]
        if doc["tree_sha256"] != tree or not (doc["todo_db_sha256"] is None or _is_hex(doc["todo_db_sha256"])) \
                or not (header is None or (type(header) is list and len(header) == 2
                                           and all(_is_int(item, 0, 255) for item in header))):
            _refuse(_EI)
        return doc


# ---------------------------------------------------------------------------
# The request and the receipt envelope (A6.1 first validations).

def _request(judge: _Judge, request_raw: object) -> dict:
    request = _loads(request_raw, REQUEST_MAX)
    if type(request) is not dict:
        _refuse(_EI)
    # A6.3 unsupported dispatch first: fixed SOURCE_MISSING, no permissive extension.
    if request.get("schema") in UNSUPPORTED_REQUEST_SCHEMAS or request.get("receipt_format") in \
            UNSUPPORTED_RECEIPT_SCHEMAS or TARGET2_KEY in request or request.get("row") in UNSUPPORTED_ROWS \
            or request.get("operation") in UNSUPPORTED_OPERATIONS or request.get("host_action") in UNSUPPORTED_OPERATIONS:
        _refuse(_SM)
    if set(request) != REQUEST_KEYS:
        _refuse(_EI)
    for key, literal in (("schema", REQUEST_SCHEMA), ("receipt_format", RECEIPT_SCHEMA)):
        if type(request[key]) is not str:
            _refuse(_EI)
        if request[key] != literal:
            _refuse(_SI)
    w = judge.w
    if not _same(request["binding"], w["binding"]):
        _refuse(_BI)
    writer, row = request["writer"], request["row"]
    operation = ROWS.get(writer, {}).get(row) if type(writer) is str and type(row) is str else None
    table = w["row_table"].get(writer) if type(writer) is str else None
    if operation is None or not isinstance(table, Mapping) or table.get(row) != operation:
        _refuse(_EI)
    if request["window_id"] != w["window_id"] or request["operation"] != operation \
            or request["host_action"] != operation:
        _refuse(_EI)
    _uuid(request["request_id"])
    if not _is_int(request["sequence"], 1) or request["origin"] != w["origin"] \
            or request["receipt_file"] != f"{w['host_dir']}/{row}.json" \
            or not _is_str(request["action"]) or not _is_str(request["expected"]) or request["write"] is not True:
        _refuse(_EI)
    since, begin, end = (_instant(request[key]) for key in ("since", "not_before", "expires_at"))
    if _number(request["wait_seconds"]) <= 0 or not since <= end or not begin < end \
            or end > _instant(w["window_expires_at"]):
        _refuse(_EI)
    judge.identity("request", hashlib.sha256(request_raw).hexdigest())
    return request


def _receipt(judge: _Judge, request: dict, receipt_ref: object) -> dict:
    ref = _ref(receipt_ref, RECEIPT_MAX)
    if ref["path"] != request["receipt_file"]:
        _refuse(_EI)
    root, name = _split(ref["path"])
    raw = judge.read(root, name, ref, RECEIPT_MAX, "receipt")
    receipt = _loads(raw, RECEIPT_MAX)
    if type(receipt) is not dict:
        _refuse(_EI)
    _schema(receipt)
    return receipt


def _schema(receipt: dict) -> None:
    schema = receipt.get("schema")
    if schema in UNSUPPORTED_RECEIPT_SCHEMAS:
        _refuse(_SM)
    if type(schema) is not str:
        _refuse(_EI)
    if schema != RECEIPT_SCHEMA:
        _refuse(_SI)


def _common(judge: _Judge, r: dict, request: dict, operation: str, *, request_raw: bytes | None) -> None:
    """Echoes, counters and the envelope; request_raw is None for a prior receipt (no request bytes)."""
    if not COMMON_KEYS <= set(r):
        _refuse(_EI)
    if not _same(r["binding"], request["binding"]):
        _refuse(_BI)
    for key in ("writer", "request_id", "sequence", "window_id", "row", "operation"):
        if not _same(r[key], request[key]):
            _refuse(_EI)
    w = judge.w
    used, expected = r["sequence_used"], r["expected_sequence"]
    if type(used) is not bool or not _is_int(expected, 1) or (used and expected != r["sequence"] + 1):
        _refuse(_EI)
    if not used and r["decision"] != "REFUSED":
        _refuse(_EI)
    if r["host_action"] != operation:
        _refuse(_EI)
    if request_raw is not None and r["request_sha256"] != hashlib.sha256(request_raw).hexdigest():
        _refuse(_EI)
    if request_raw is None and not _is_hex(r["request_sha256"]):
        _refuse(_EI)
    if r["controller_sha256"] != w["controller_sha256"] or r["executor_sha256"] != w["executor_sha256"] \
            or r["sums_sha256"] != w["binding"]["build_sums_sha256"]:
        _refuse(_EI)
    decision, kind, done = r["decision"], r["failure_kind"], r["done"]
    if decision not in ("DONE", "FAILED", "REFUSED") or kind not in (None, "app", "host") \
            or (decision == "FAILED") != (kind is not None) or type(done) is not bool or done != (decision == "DONE"):
        _refuse(_EI)
    if not all(type(r[key]) is str for key in ("by", "note", "reason")):
        _refuse(_EI)
    begin, end, at, seen = (_instant(r[key]) for key in ("started_at", "ended_at", "at", "seen_at"))
    if not begin <= end <= at or at > judge.now_us or seen > judge.now_us:
        _refuse(_EI)
    if request.get("not_before") is not None and decision != "REFUSED" and begin < _instant(request["not_before"]):
        _refuse(_EI)
    if request.get("expires_at") is not None and at > _instant(request["expires_at"]):
        _refuse(_EI)  # late receipt
    if r["lane"] != "app" or r["app_container_id"] != w["app_container_id"] \
            or r["fwd_container_id"] != w["fwd_container_id"]:
        _refuse(_EI)
    if not _same(r["window_ttl_minutes"], w["window_ttl_minutes"]) \
            or _instant(r["window_expires_at"]) != _instant(w["window_expires_at"]) or not _bytes_used_ok(r["bytes_used"]):
        _refuse(_EI)
    if "exit_code" not in r:
        _refuse(_EI)
    extra = set(r) - COMMON_KEYS
    if extra & REJECTED_ALIASES or extra - ALLOWED_ROOT[operation]:
        _refuse(_EI)
    if decision in ("DONE", "FAILED") and kind != "host" and REQUIRED_ROOT[operation] - set(r):
        _refuse(_EI)
    if decision == "REFUSED" or kind == "host":
        _refuse(_EI)  # F5-REFUSED / F5-HOST-FAULT: BLOCKED, never FAIL, no retry
    for key in OPTIONAL_LISTINGS:
        if r.get(key) is not None:
            judge.listing(r[key], data=key == "data_listing")


def _truth(decision: str, kind: object, done: object, failed: bool) -> str:
    """Ops' decision must agree with the independently computed result (A6.1), else BLOCKED."""
    if failed:
        ok = decision == "FAILED" and kind == "app" and done is False
    else:
        ok = decision == "DONE" and kind is None and done is True
    if not ok:
        _refuse(_EI)
    return FAIL if failed else PASS


# ---------------------------------------------------------------------------
# Crash, stop leg, start leg (A6.1-A6.3).

def _crash(judge: _Judge, r: dict, row: str) -> dict:
    """D-1 / API-D-1: DONE 137 with every physical witness; only an Env miss can FAIL."""
    if not _is_int(r["exit_code"], 0) or r["exit_code"] != 137 or r["signal"] != ROW_SIGNAL[row]:
        _refuse(_EI)
    sent = _instant(r["kill_sent_at"], ms=True)
    if r.get("signal_sent_at") is not None and _instant(r["signal_sent_at"], ms=True) != sent:
        _refuse(_EI)
    exited = _instant(r["exited_at"], ms=True)
    begin, end = _instant(r["started_at"]), _instant(r["ended_at"])
    env_ok = judge.terminal(r["stop_inspect"], 137, exited, sent, begin, end)
    snap = judge.snapshot(r["stop_inspect"], "app")
    if r["exit_status"] != snap["state"]["status"]:
        _refuse(_EI)
    judge.listing(r["data_listing_after_exit"])
    if r["listener_gone"] is not True or r["origin_refused"] is not True:
        _refuse(_EI)
    return {"exited": exited, "listing": r["data_listing_after_exit"], "env_ok": env_ok}


def _stop_leg(judge: _Judge, e: dict, row: str, exit_code: object, begin: int, end: int) -> dict:
    """The restart's stop-graceful leg: misses are app FAILs when the evidence is complete."""
    if not _keys(e, set(STOP_KEYS)) or not _is_int(exit_code, 0) or e["signal"] != ROW_SIGNAL[row]:
        _refuse(_EI)
    sent, exited = _instant(e["signal_sent_at"], ms=True), _instant(e["exited_at"], ms=True)
    daemon = exited - sent
    if daemon < 0:
        _refuse(_EI)
    reported = _number(e["seconds_to_exit"])
    computed, span = _seconds(daemon), _seconds(end - sent)
    # TD-1 point 3: one-sided, bounded by the leg's own end.
    if reported < computed - BAND or reported > span + BAND:
        _refuse(_EI)
    if not _same_side(reported, computed, STOP_LIMIT):
        _refuse(_EI)
    within = type(e["within_10s"]) is bool and e["within_10s"]
    if type(e["within_10s"]) is not bool or within != (computed <= STOP_LIMIT and reported <= STOP_LIMIT):
        _refuse(_EI)
    kill = None if e["kill_sent_at"] is None else _instant(e["kill_sent_at"], ms=True)
    if type(e["forced_kill"]) is not bool or e["forced_kill"] != (kill is not None) or (kill is not None and kill < sent):
        _refuse(_EI)
    seen_at = None if e["stopped_line_at"] is None else _instant(e["stopped_line_at"], ms=True)
    if type(e["stopped_line_seen"]) is not bool or e["stopped_line_seen"] != (seen_at is not None) \
            or (seen_at is not None and seen_at < sent):
        _refuse(_EI)
    line, first = e["traceback_line"], e["traceback_first_at"]
    first_at = None if first is None else _instant(first, ms=True)
    if type(e["traceback_seen"]) is not bool or e["traceback_seen"] != (line is not None) \
            or e["traceback_seen"] != (first_at is not None) or (first_at is not None and first_at < sent) \
            or (line is not None and (type(line) is not str or len(line.encode("utf-8")) > 512)):
        _refuse(_EI)
    env_ok = judge.terminal(e["stop_inspect"], exit_code, exited, sent, begin, end)
    judge.listing(e["data_listing_after_exit"])
    misses = [exit_code != 0, not within, e["forced_kill"], not e["stopped_line_seen"], e["traceback_seen"],
              not env_ok]
    return {"exited": exited, "listing": e["data_listing_after_exit"], "failed": any(misses)}


def _start_audit(judge: _Judge, ref: object, request: dict, prior_exit: int) -> list:
    """start-audit/1, by its exact sibling leaf, every entry typed and in order."""
    ref = _ref(ref, AUDIT_MAX)
    leaf = f"audit-{request['request_id']}-{request['sequence']}.json"
    if ref["path"] != leaf:
        _refuse(_EI)
    doc = _loads(judge.read(judge.host_dir, leaf, ref, AUDIT_MAX, "audit"), AUDIT_MAX)
    if not _keys(doc, AUDIT_KEYS) or doc["schema"] != AUDIT_SCHEMA:
        _refuse(_EI)
    if any(not _same(doc[key], request[key]) for key in ("window_id", "writer", "request_id", "sequence", "row",
                                                          "operation")):
        _refuse(_EI)
    runs = doc["commands_run"]
    if type(runs) is not list or not 1 <= len(runs) <= AUDIT_ENTRIES_MAX:
        _refuse(_EI)
    out, previous = [], prior_exit
    for entry in runs:
        if not _keys(entry, RUN_KEYS):
            _refuse(_EI)
        start, end = _instant(entry["started_at"], ms=True), _instant(entry["ended_at"], ms=True)
        if start < previous or end < start:
            _refuse(_EI)  # ordered, nonoverlapping, after the recorded exit
        previous = end
        out.append(_run(judge, entry, start, end))
    return out


def _run(judge: _Judge, c: dict, start: int, end: int) -> dict:
    op, p, res, kind = c["op"], c["params"], c["result"], c["kind"]
    run = {"op": op, "start": start, "end": end, "params": p, "result": res}
    if op in ("docker-start", "docker-inspect"):
        if not _keys(p, {"target", "container_id"}) or p["target"] not in TARGETS \
                or p["container_id"] != judge.ids[p["target"]] or kind != "process" \
                or not _same(c["argv"], ["docker", op.split("-")[1], p["container_id"]]):
            _refuse(_EI)
        keys = {"outcome", "started", "error"} if op == "docker-start" else {"outcome", "snapshot", "error"}
        if not _keys(res, keys) or res["outcome"] != "ok" or res["error"] is not None or c["exit_code"] != 0 \
                or type(c["exit_code"]) is not int:
            _refuse(_EI)  # a failed host read or start is a host failure: BLOCKED
        if op == "docker-start" and res["started"] is not True:
            _refuse(_EI)
        return run
    if op == "listener" and kind == "process":
        if not _same(c["argv"], ["ss", "-ltnH", "sport", "=", f":{judge.port}"]) or type(c["exit_code"]) is not int:
            _refuse(_EI)
    elif kind != "inprocess" or c["argv"] is not None or c["exit_code"] is not None:
        _refuse(_EI)
    if op == "data-stat":
        if not _same(p, {"path": judge.w["data_dir"], "follow_symlinks": False}) \
                or not _keys(res, {"outcome", "dev", "inode", "mode", "error"}) or res["outcome"] != "ok" \
                or res["error"] is not None or not _same(res["dev"], judge.w["data_dev"]) \
                or not _same(res["inode"], judge.w["data_inode"]) or not _same(res["mode"], 0o700):
            _refuse(_EI)
    elif op == "data-list":
        if not _same(p, {"path": judge.w["data_dir"], "follow_symlinks": False, "max_entries": 10000,
                         "max_depth": 16}) or not _keys(res, {"outcome", "snapshot", "error"}) \
                or res["outcome"] != "ok" or res["error"] is not None:
            _refuse(_EI)
        judge.listing(res["snapshot"])
    elif op == "listener":
        if not _same(p, {"address": ADDRESS, "port": judge.port}) \
                or not _keys(res, {"outcome", "present", "sockets", "error"}) or res["outcome"] != "ok" \
                or res["error"] is not None or type(res["present"]) is not bool or type(res["sockets"]) is not list \
                or res["present"] != bool(res["sockets"]):
            _refuse(_EI)
        for sock in res["sockets"]:
            if not _keys(sock, {"address", "port", "protocol"}) or sock["protocol"] != "tcp" \
                    or not _is_str(sock["address"]) or not _same(sock["port"], judge.port):
                _refuse(_EI)
    elif op == "health":
        _probe(judge, c, run)
    else:
        _refuse(_EI)  # unknown or unreviewed operation
    return run


def _probe(judge: _Judge, c: dict, run: dict) -> None:
    """One serial health probe (OSA): fixed target, Host and 3 s timeout; real times kept."""
    p, res = c["params"], c["result"]
    if not _keys(p, {"method", "url", "host", "timeout_seconds"}) or p["method"] != "GET" \
            or p["url"] != judge.w["origin"] + "/api/items" or p["host"] != judge.host \
            or not _same(p["timeout_seconds"], PROBE_TIMEOUT):
        _refuse(_EI)
    if not _keys(res, {"outcome", "status", "response_at", "elapsed_seconds", "error"}):
        _refuse(_EI)
    elapsed = _number(res["elapsed_seconds"])
    outcome = res["outcome"]
    if outcome == "response":
        if not _is_int(res["status"], 100, 599) or res["error"] is not None:
            _refuse(_EI)
        at = _instant(res["response_at"], ms=True)
        if not run["start"] <= at <= run["end"] or abs(elapsed - _seconds(at - run["start"])) > BAND:
            _refuse(_EI)  # in-flight response kept with its real times, never clamped
        if res["status"] == 400:
            _refuse(_EI)  # E16: the probe asked wrongly; BLOCKED host, never app FAIL
        run["status"], run["at"] = res["status"], at
    elif outcome in ("refused", "timeout", "connection-error"):
        if res["status"] is not None or res["response_at"] is not None or res["error"] != outcome \
                or abs(elapsed - _seconds(run["end"] - run["start"])) > BAND \
                or (outcome == "timeout" and elapsed < PROBE_TIMEOUT):
            _refuse(_EI)  # a timeout cannot end before its own timeout: no synthetic null
        run["status"], run["at"] = None, None
    else:
        _refuse(_EI)  # probe host error


def _health(judge: _Judge, e: dict, probes: list, t0: int, fwd_end: int, leg_end: int) -> tuple[str, int | None]:
    """QA's cadence and TD-1 health rule; returns (healthy|late|miss, first200 instant)."""
    if not probes:
        _refuse(_EI)  # zero probes: host failure, never timeout FAIL
    deadline = t0 + 30 * _SECOND
    previous, first200, last_status = fwd_end, None, None
    for index, run in enumerate(probes):
        if first200 is not None:
            _refuse(_EI)  # no resampling after the first 200
        if index == 0 and (run["start"] < fwd_end or run["start"] - fwd_end > CADENCE_GAP_US):
            _refuse(_EI)  # first-probe rule
        if run["start"] < previous or run["start"] - previous > CADENCE_GAP_US or run["start"] >= deadline:
            _refuse(_EI)  # serial, .750 gap, no new probe at or after D
        if run["status"] is not None:
            last_status = run["status"]
        if run["status"] == 200:
            first200 = run["at"]
        previous = run["end"]
    o = e["health_observation"]
    if not _keys(o, OBSERVATION_KEYS) or "health_at" not in e or "seconds_to_health" not in e:
        _refuse(_EI)
    elapsed = _number(e["health_elapsed_seconds"])
    if _number(o["elapsed_seconds"]) != elapsed:
        _refuse(_EI)  # the same measure in two places: exact Decimal equality
    observed = _instant(o["observed_until"], ms=True)
    observed_delta = _seconds(observed - t0)
    if abs(elapsed - observed_delta) > BAND:
        _refuse(_EI)
    if first200 is not None:
        if e["health_at"] is None or e["seconds_to_health"] is None:
            _refuse(_EI)  # 200 with a null pair
        if _instant(e["health_at"], ms=True) != first200:
            _refuse(_EI)
        reported = _number(e["seconds_to_health"])
        first_delta = _seconds(first200 - t0)
        if abs(reported - first_delta) > BAND:
            _refuse(_EI)
        a, b = _deadline_measures(first_delta, reported, observed_delta, elapsed)
        if not _same_side(a, b, HEALTH_LIMIT):
            _refuse(_EI)
        outcome = "healthy" if a <= HEALTH_LIMIT else "late"
        if observed < first200:
            _refuse(_EI)
    else:
        if e["health_at"] is not None or e["seconds_to_health"] is not None:
            _refuse(_EI)
        # A complete measured miss needs BOTH measures at or past 30.000 (TD-1).
        if not (elapsed >= HEALTH_LIMIT and observed_delta >= HEALTH_LIMIT):
            _refuse(_EI)
        if previous < deadline - CADENCE_GAP_US:
            _refuse(_EI)  # final probe coverage
        outcome = "miss"
    first, last = probes[0], probes[-1]
    if (o["method"], o["path"], o["host"], o["outcome"]) != ("GET", "/api/items", judge.host, outcome) \
            or not _same(o["probe_count"], len(probes)) or o["complete"] is not True \
            or not _same(o["last_http_status"], last_status) or not _same(e["health_code"], last_status) \
            or not first["start"] <= _instant(o["first_probe_at"], ms=True) <= first["end"] \
            or not last["start"] <= _instant(o["last_probe_at"], ms=True) <= last["end"] or observed > leg_end:
        _refuse(_EI)
    return outcome, first200


def _start_leg(judge: _Judge, e: dict, request: dict, prior: dict, begin: int, end: int, *,
               standalone: bool) -> bool:
    """A start (standalone D-5/API-D-5 or the restart's start leg); returns whether it missed."""
    w = judge.w
    if not _same(e["data_listing_after_exit"], prior["listing"]):
        _refuse(_EI)
    after_exit = judge.listing(e["data_listing_after_exit"])
    before_start = judge.listing(e["data_listing_before_start"])
    match = _same(after_exit["entries"], before_start["entries"]) and after_exit["tree_sha256"] == \
        before_start["tree_sha256"]
    if type(e["listings_match"]) is not bool or e["listings_match"] != match or not match:
        _refuse(_EI)
    if _instant(e["audit_started_at"], ms=True) != prior["exited"] or e["audit_complete"] is not True:
        _refuse(_EI)
    audit_end = _instant(e["audit_ended_at"], ms=True)
    runs = _start_audit(judge, e["start_audit_ref"], request, prior["exited"])
    if runs[-1]["end"] > audit_end:
        _refuse(_EI)
    starts = [run for run in runs if run["op"] == "docker-start"]
    if [run["params"]["target"] for run in starts] != ["app", "forwarder"]:
        _refuse(_EI)  # exactly one start each, app then forwarder: no second start as repair
    app_start, fwd_start = starts
    t0 = _instant(e["start_sent_at"], ms=True)
    if not (prior["exited"] <= t0 <= app_start["start"] and begin <= t0):
        _refuse(_EI)
    if t0 < _instant(w["window_started_at"]):
        _refuse(_EI)  # not armed
    if app_start["start"] >= _instant(w["window_expires_at"]):
        _refuse(_EI)  # after TTL
    pre = [run for run in runs if run["end"] <= app_start["start"]]
    post = [run for run in runs if run["start"] >= fwd_start["end"]]
    if len(pre) + len(post) + 2 != len(runs):
        _refuse(_EI)  # something ran between the two starts

    def pick(entries: list, op: str, target: str | None = None, last: bool = True) -> dict:
        found = [run for run in entries if run["op"] == op and (target is None or run["params"]["target"] == target)]
        if not found:
            _refuse(_EI)
        return found[-1] if last else found[0]

    if any(run["op"] == "health" for run in pre):
        _refuse(_EI)
    stat_before, stat_after = pick(pre, "data-stat"), pick(post, "data-stat", last=False)
    same_inode = (stat_before["result"]["dev"], stat_before["result"]["inode"]) == \
        (stat_after["result"]["dev"], stat_after["result"]["inode"])
    if not _same(pick(pre, "data-list")["result"]["snapshot"], e["data_listing_before_start"]):
        _refuse(_EI)
    if any(run["op"] == "listener" and run["result"]["present"] for run in pre):
        _refuse(_EI)
    listener = pick(post, "listener")
    if type(e["listener_present"]) is not bool or e["listener_present"] != listener["result"]["present"]:
        _refuse(_EI)
    identity = e["identity_evidence"]
    if not _keys(identity, {"window_sha256", "app", "forwarder"}) \
            or identity["window_sha256"] != judge.cw.target.expected_window_sha256:
        _refuse(_EI)
    env_ok, after_app = True, None
    for target in TARGETS:
        t = identity[target]
        if not _keys(t, IDENTITY_KEYS) or t["container_id"] != judge.ids[target] \
                or not _same(t["creation_record"], w["creation_inspect"][target]):
            _refuse(_EI)
        if not _same(t["before_inspect"], pick(pre, "docker-inspect", target)["result"]["snapshot"]) \
                or not _same(t["after_inspect"], pick(post, "docker-inspect", target, last=False)["result"]["snapshot"]):
            _refuse(_EI)
        before = judge.snapshot(t["before_inspect"], target)
        if before["state"]["running"] is not False:
            _refuse(_EI)  # both bound IDs must be stopped before the start
        before_ok = judge.edge(before, target)
        after = judge.snapshot(t["after_inspect"], target)
        after_ok = judge.edge(after, target)
        if type(t["before_matches_creation"]) is not bool or t["before_matches_creation"] != before_ok \
                or type(t["after_matches_creation"]) is not bool or t["after_matches_creation"] != after_ok:
            _refuse(_EI)  # matches_creation must be the computed boolean, faithfully echoed
        _running_order(after, t0)
        env_ok = env_ok and before_ok and after_ok
        if target == "app":
            after_app = after
    if _instant(e["app_started_at"]) != _event(after_app["state"]["started_at"]):
        _refuse(_EI)
    outcome, first200 = _health(judge, e, [run for run in post if run["op"] == "health"], t0, fwd_start["end"], end)
    if outcome == "healthy" and not listener["result"]["present"]:
        _refuse(_EI)
    if audit_end < (first200 if first200 is not None else t0 + 30 * _SECOND) or audit_end > end:
        _refuse(_EI)
    if standalone and (type(e.get("same_inode")) is not bool or e["same_inode"] != same_inode):
        _refuse(_EI)
    if not same_inode:
        _refuse(_EI)
    return outcome != "healthy" or not env_ok


def _running_order(snap: Any, t0: int) -> None:
    """HOME F5-LEG-ORDER-START and F5-SENTINEL-NO-EVENT on a start leg's running observation."""
    state = snap["state"]
    started, finished = _event(state["started_at"]), _event(state["finished_at"])
    observed = _instant(snap["observed_at"], ms=True)
    if state["running"] is not True or started is None:
        _refuse(_EI)  # a sentinel started_at means never started
    if not t0 <= started <= observed:
        _refuse(_EI)
    if finished is not None and finished >= started:
        _refuse(_EI)  # running with finished_at at or after started_at: the restart-policy shape


# ---------------------------------------------------------------------------
# Operations.

def _prior(judge: _Judge, r: dict, row: str, start_begin: int) -> dict:
    """Standalone start: the exact prior crash receipt, re-judged as a complete crash."""
    p = r["prior_exit_evidence"]
    if not _keys(p, PRIOR_KEYS) or p["kind"] != "receipt" or (p["row"], p["writer"]) != PRIOR_CRASH[row]:
        _refuse(_EI)
    _uuid(p["request_id"])
    if not _is_int(p["sequence"], 1, r["sequence"] - 1) or not _is_hex(p["sha256"]) \
            or not _is_int(p["byte_length"], 1, RECEIPT_MAX):
        _refuse(_EI)
    raw = judge.read(judge.host_dir, f"{p['row']}.json", p, RECEIPT_MAX, "prior")
    crash = _loads(raw, RECEIPT_MAX)
    if type(crash) is not dict:
        _refuse(_EI)
    _schema(crash)
    echo = {"binding": judge.w["binding"], "writer": p["writer"], "request_id": p["request_id"],
            "sequence": p["sequence"], "window_id": judge.w["window_id"], "row": p["row"], "operation": "crash"}
    if crash.get("operation") != "crash" or crash.get("host_action") != "crash":
        _refuse(_EI)
    _common(judge, crash, echo, "crash", request_raw=None)
    facts = _crash(judge, crash, p["row"])
    _truth(crash["decision"], crash["failure_kind"], crash["done"], not facts["env_ok"])
    if _instant(crash["ended_at"]) > start_begin:
        _refuse(_EI)
    return facts


def _start(judge: _Judge, r: dict, request: dict) -> str:
    if r["exit_code"] is not None:
        _refuse(_EI)
    begin, end = _instant(r["started_at"]), _instant(r["ended_at"])
    prior = _prior(judge, r, request["row"], begin)
    missed = _start_leg(judge, r, request, prior, begin, end, standalone=True)
    own = _truth(r["decision"], r["failure_kind"], r["done"], missed)
    return _carry_prior(own, not prior["env_ok"])


def _crash_row(judge: _Judge, r: dict, request: dict) -> str:
    facts = _crash(judge, r, request["row"])
    return _truth(r["decision"], r["failure_kind"], r["done"], not facts["env_ok"])


def _leg(judge: _Judge, g: object, label: str) -> tuple[int, int]:
    if not _keys(g, LEG_KEYS) or g["leg"] != label:
        _refuse(_EI)
    if g["decision"] not in ("DONE", "FAILED") or (g["decision"] == "FAILED") != (g["failure_kind"] is not None) \
            or g["failure_kind"] not in (None, "app"):
        _refuse(_EI)  # REFUSED or host-failed legs are BLOCKED
    return _instant(g["started_at"]), _instant(g["ended_at"])


def _outcome(call: Any) -> tuple[str, str]:
    try:
        return call(), NONE
    except _RECEIVED_REFUSALS as exc:
        return BLOCKED, exc.code if exc.code in CODES else _EI


def _restart(judge: _Judge, r: dict, request: dict) -> str:
    """R-1 / R-1i: [stop-graceful, start] legs combined BLOCKED over FAIL over PASS."""
    legs = r["legs"]
    if type(legs) is not list or not legs:
        _refuse(_EI)
    begin, end = _instant(r["started_at"]), _instant(r["ended_at"])
    row = request["row"]
    state: dict = {}

    def stop() -> str:
        g = legs[0]
        g_begin, g_end = _leg(judge, g, "stop-graceful")
        if not begin <= g_begin <= g_end <= end:
            _refuse(_EI)
        facts = _stop_leg(judge, g["evidence"], row, g["exit_code"], g_begin, g_end)
        state["stop"] = facts
        state["stop_end"] = g_end
        return _leg_truth(g, facts["failed"])

    def start() -> str:
        if len(legs) != 2:
            _refuse(_EI)  # absent required start leg, or a second start invented as repair
        if "stop" not in state:
            _refuse(_EI)
        g = legs[1]
        g_begin, g_end = _leg(judge, g, "start")
        if not state["stop_end"] <= g_begin <= g_end <= end or g["exit_code"] is not None:
            _refuse(_EI)
        e = g["evidence"]
        if not _keys(e, set(START_KEYS)) or not _same(e["prior_exit_evidence"],
                                                      {"kind": "restart-leg", "leg": "stop-graceful"}):
            _refuse(_EI)
        missed = _start_leg(judge, e, request, state["stop"], g_begin, g_end, standalone=False)
        return _leg_truth(g, missed)

    def parent() -> str:
        if not _same(r["exit_code"], legs[0].get("exit_code") if isinstance(legs[0], Mapping) else None) \
                or r["listener_gone"] is not True:
            _refuse(_EI)
        return PASS

    outcomes = [_outcome(stop), _outcome(start), _outcome(parent)]
    verdict, code = _combine(outcomes)
    if verdict == BLOCKED:
        _refuse(code)
    _truth(r["decision"], r["failure_kind"], r["done"], verdict == FAIL)
    return verdict


def _leg_truth(g: dict, failed: bool) -> str:
    """A leg's decision must be the computed one (legs carry no done flag)."""
    if failed:
        ok = g["decision"] == "FAILED" and g["failure_kind"] == "app"
    else:
        ok = g["decision"] == "DONE" and g["failure_kind"] is None
    if not ok:
        _refuse(_EI)
    return FAIL if failed else PASS


def _assess(judge: _Judge, request_raw: object, receipt_ref: object) -> str:
    """The receipt's offline verdict, PASS or FAIL; any refusal is BLOCKED by the caller."""
    request = _request(judge, request_raw)
    receipt = _receipt(judge, request, receipt_ref)
    operation = request["operation"]
    _common(judge, receipt, request, operation, request_raw=request_raw)
    if operation == "crash":
        return _crash_row(judge, receipt, request)
    if operation == "start":
        return _start(judge, receipt, request)
    return _restart(judge, receipt, request)


def _recheck_window(window: CandidateWindow, boundary: str) -> None:
    _recheck_candidate(window.target, boundary)
    _recheck_reads(window.reads[:1])
    if not _same(_loads(window.reads[0].raw, WINDOW_MAX), window.window):
        _refuse(_EI)


def _now(now: object) -> int:
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        _refuse(_CM)
    text = now.isoformat(timespec="microseconds")
    parsed = _parse_instant(text, False)
    if parsed is None:
        _refuse(_CM)
    return parsed


def judge_candidate_receipt(request_raw: bytes, receipt_ref: dict, *, window: CandidateWindow,
                            now: datetime) -> UntrustedAssessment:
    """Judge one receipt offline against QA's received rules; always returns UNTRUSTED data.

    BLOCKED carries one of the eleven codes; PASS and FAIL carry NONE. Nothing is
    counted, adopted or resolved natively.
    """
    identities: list = []
    try:
        if type(window) is not CandidateWindow:
            _refuse(_CM)
        identities.append(("window", window.target.expected_window_sha256))
        judge = _Judge(window, _now(now))
        judge.identities = identities
        _recheck_window(window, "receiving")
        verdict = _assess(judge, request_raw, receipt_ref)
        _recheck_window(window, "before-count")
        _recheck_reads(tuple(judge.reads))
        return UntrustedAssessment(trust=TRUST, verdict=verdict, code=NONE, identities=tuple(identities))
    except _RECEIVED_REFUSALS as exc:
        code = exc.code if exc.code in CODES else _EI
        return UntrustedAssessment(trust=TRUST, verdict=BLOCKED, code=code, identities=tuple(identities))
    except Exception:  # noqa: BLE001  (bounded: no diagnostic leaves this module)
        return UntrustedAssessment(trust=TRUST, verdict=BLOCKED, code=_EI, identities=tuple(identities))
