"""Build-bound file client for Ops' host controller; Python stdlib only, no host actions.

H-OPS-HOST-CLIENT-1 (Architecture #126)
- Wrong (evidence): first_app_shared.host_row BLOCKs every D-1 crash (exit 137 is
  read as a failure), and nothing writes ops-host-request/1 or reads
  ops-host-receipt/1 with QA's verdict rule.
- Change: one isolated client: request writer, sequence handling, strict receipt
  and evidence reader, and one pure verdict rule (verdict()).
- Expected: every fixed fixture gets its expected verdict; the Project 2 and
  first_app tests pass unchanged. Measure: one test run.
- Disproved if: any fixture is misclassified.

Contract (QA-HOME accepted 2026-10-20 15:37, QA #39; Ops binding rm via #126 unblock):
- base OPS-SLICE-A-PLAN.md v3 sha256 a9244fd51a3188dbea5242b7b691d7e70ced7b56c2c386c76394292780be29b4
  (sections 3, 6.1-6.4, 6.6);
- OPS-SLICE-A-CORRECTION-1.md 4507269b404e423b2fadae97301c75edd0b6c70275aedfe7aec507014237e540;
- QA host-publication-v2 SHA256SUMS 213c6ac92ab79fa0bb1c77103c607fb5f6067140b61996d04066f5c9c8df6155;
- Security W1 pin for engine-image (rm-935cee04).

The client never runs a controller, subprocess, Docker command, HTTP request or
model. Callers serialize one client per (window_id, writer); an expires_at must
cover any time the controller holds the request behind its lane.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import stat
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

REQUEST_SCHEMA = "ops-host-request/1"
RECEIPT_SCHEMA = "ops-host-receipt/1"
REQUEST_MAX = 65_536
RECEIPT_MAX = 16_384
SNAPSHOT_MAX = 1_048_576
INSPECT_MAX = 16_384
AUDIT_MAX = 262_144
AUDIT_ENTRIES_MAX = 1024
STOP_LIMIT = Decimal("10.000")
HEALTH_LIMIT = Decimal("30.000")
CADENCE_GAP = Decimal("0.750")
# Open with QA (rm-3dbefb0c): seconds_* are monotonic measures, the instants are
# wall-clock milliseconds; a cross-check passes within one millisecond.
CROSSCHECK_TOLERANCE = Decimal("0.001")
ENGINE_PIN = "sha256:b01cb863d9b2ecbdc2b05751a67ee5263978892897557cc98108c48ac9f7a00f"

ROWS = {
    "checker": {"R-1": "restart", "R-1i": "restart", "D-1": "crash", "D-5": "start", "W-IMG": "engine-image"},
    "api-check": {"API-D-1": "crash", "API-D-5": "start"},
    "qa-runner": {"HOST-L": "launch-cases"},
    "qa-scan": {},  # no published scan-state row: refuse rather than invent one
}
ROW_SIGNAL = {"R-1": "TERM", "R-1i": "INT", "D-1": "KILL", "API-D-1": "KILL"}
LANE = {"restart": "app", "crash": "app", "start": "app", "launch-cases": "cases", "engine-image": None}
PRIOR_CRASH = {"D-5": ("D-1", "checker"), "API-D-5": ("API-D-1", "api-check")}

HEX64 = re.compile(r"[0-9a-f]{64}")
INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})")
LEAF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

PROJECT_KEYS = {"mode", "project_id", "run_id", "build_sums_sha256", "kit_id", "kit_sha256"}
CALIBRATION_KEYS = {"mode", "manifest_sha256", "entry", "build_sums_sha256", "calibration_run"}
REQUEST_KEYS = {"schema", "binding", "window_id", "row", "operation", "host_action", "writer", "request_id",
                "origin", "receipt_file", "action", "expected", "since", "not_before", "expires_at", "sequence",
                "wait_seconds", "receipt_format", "write"}
SEQ_KEYS = {"window_id", "writer", "expected_sequence", "last_request_id", "updated_at"}
COMMON_KEYS = {"schema", "row", "operation", "host_action", "writer", "request_id", "window_id", "sequence",
               "sequence_used", "expected_sequence", "binding", "request_sha256", "controller_sha256",
               "executor_sha256", "sums_sha256", "done", "decision", "failure_kind", "by", "note", "reason",
               "at", "seen_at", "started_at", "ended_at", "lane", "app_container_id", "fwd_container_id",
               "exit_code", "window_ttl_minutes", "window_expires_at", "bytes_used"}
STOP_EVIDENCE = ("signal", "signal_sent_at", "exited_at", "seconds_to_exit", "within_10s", "forced_kill",
                 "kill_sent_at", "stopped_line_seen", "stopped_line_at", "traceback_seen", "traceback_line",
                 "traceback_first_at", "data_listing_after_exit", "stop_inspect")
START_EVIDENCE = ("start_sent_at", "app_started_at", "health_at", "health_code", "seconds_to_health",
                  "health_elapsed_seconds", "health_observation", "identity_evidence", "prior_exit_evidence",
                  "data_listing_after_exit", "data_listing_before_start", "listings_match", "start_audit_ref",
                  "audit_started_at", "audit_ended_at", "audit_complete", "listener_present")
LEG_KEYS = {"leg", "decision", "failure_kind", "started_at", "ended_at", "exit_code", "evidence"}
# Optional observations from base section 6.3; anything outside the vocabulary is BLOCKED.
OPTIONAL_KEYS = {"exit_status", "data_dir", "data_dev", "data_inode", "data_mode", "data_listing", "app_copy_changes",
                 "tmp_listing", "work_listing", "data_tree_sha256_before", "todo_db_sha256",
                 "todo_db_sha256_after_exit", "todo_db_sha256_before_start", "todo_db_header_18_19",
                 "listener_before", "listener_after_stop", "listener_after_start", "ss_line", "listener_present",
                 "listener_gone", "origin_refused", "same_inode", "listings_match", "commands", "stdout", "stderr",
                 "stdout_sha256", "stderr_sha256", "attempts", "op_status", "app_state", "fwd_state"}
ENGINE_KEYS = {"image_id", "container_id", "container_started_at", "running"}
REJECTED_ALIASES = {"signal_at", "exit_at", "stopped_seen", "answered_at", "data_dir_device", "data_dir_inode",
                    "data_dir_mode", "listing_after_exit", "listing_before_start", "answered_within_30s",
                    "get_root_status", "commands_run", "data_dev_inode_before", "data_dev_inode_after",
                    "oom_killed", "restart_count", "expected_image_id", "image_matches"}
REQUIRED_ROOT = {
    "crash": {"exit_status", "listener_gone", "origin_refused", "signal", "kill_sent_at", "exited_at",
              "data_listing_after_exit", "stop_inspect"},
    "start": set(START_EVIDENCE) | {"same_inode"},
    "restart": {"legs", "listener_gone"},
    "engine-image": set(ENGINE_KEYS),
    "launch-cases": set(),
}
ALLOWED_ROOT = {
    "crash": OPTIONAL_KEYS | set(STOP_EVIDENCE),
    "start": OPTIONAL_KEYS | set(START_EVIDENCE),
    "restart": (OPTIONAL_KEYS - set(START_EVIDENCE) - set(STOP_EVIDENCE) - {"same_inode"}) | {"legs"},
    "engine-image": set(ENGINE_KEYS),
    "launch-cases": OPTIONAL_KEYS,
}
BYTES_KEYS = {"app_copy", "data", "tmp", "work", "total", "complete", "measured_at"}
INSPECT_RUNTIME = {"image_id", "command", "workdir", "env", "user", "mounts", "tmpfs", "read_only_root", "cap_drop",
                   "cap_add", "security_options", "privileged", "devices", "pid_mode", "ipc_mode", "uts_mode",
                   "init", "limits", "restart_policy", "ports", "networks", "data_bind"}
INSPECT_STATE = {"running", "status", "started_at", "finished_at", "exit_code", "oom_killed", "restart_count"}
LISTING_KEYS = {"schema", "window_id", "target", "path", "observed_at", "entries", "entry_count", "truncated",
                "complete", "error", "tree_sha256", "todo_db_sha256", "todo_db_header_18_19"}
ENTRY_KEYS = {"name", "type", "size", "mtime_ns", "target", "target_truncated", "sha256"}
OBSERVATION_KEYS = {"method", "path", "host", "outcome", "probe_count", "first_probe_at", "last_probe_at",
                    "observed_until", "elapsed_seconds", "last_http_status", "complete"}
AUDIT_KEYS = {"kind", "op", "started_at", "ended_at", "exit_code", "argv", "params", "result"}


class Blocked(ValueError):
    """Unusable host evidence or an unsafe request; the row is BLOCKED with this reason."""


# ---------------------------------------------------------------- small typed readers

def _obj(value, name: str, keys: set | None = None) -> dict:
    if not isinstance(value, dict):
        raise Blocked(f"{name}: expected an object")
    if keys is not None and set(value) != keys:
        missing, extra = sorted(keys - set(value)), sorted(set(value) - keys)
        raise Blocked(f"{name}: wrong keys (missing {missing}, unexpected {extra})")
    return value


def _int(value, name: str, low: int | None = None, high: int | None = None, null: bool = False):
    if value is None and null:
        return None
    if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
        raise Blocked(f"{name}: expected an integer in [{low}, {high}]")
    return value


def _bool(value, name: str, null: bool = False):
    if value is None and null:
        return None
    if type(value) is not bool:
        raise Blocked(f"{name}: expected a JSON boolean")
    return value


def _str(value, name: str, null: bool = False, max_bytes: int | None = None):
    if value is None and null:
        return None
    if not isinstance(value, str) or not value:
        raise Blocked(f"{name}: expected a nonempty string")
    if max_bytes is not None and len(value.encode("utf-8")) > max_bytes:
        raise Blocked(f"{name}: longer than {max_bytes} bytes")
    return value


def _hex(value, name: str, null: bool = False):
    if value is None and null:
        return None
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise Blocked(f"{name}: expected a full lowercase SHA-256 / container id")
    return value


def _num(value, name: str, null: bool = False):
    if value is None and null:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise Blocked(f"{name}: expected a finite number >= 0 (not a boolean)")
    return Decimal(str(value))


def instant(value, name: str, *, ms: bool = False, null: bool = False):
    """Offset-bearing ISO 8601 -> exact Decimal epoch seconds (nanoseconds kept)."""
    if value is None and null:
        return None
    match = INSTANT_RE.fullmatch(value) if isinstance(value, str) else None
    if not match or (ms and len(match[1] or "") < 3):
        raise Blocked(f"{name}: expected ISO 8601 with an explicit offset" + (" and milliseconds" if ms else ""))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Blocked(f"{name}: not a valid instant") from exc
    whole = parsed.replace(microsecond=0) - EPOCH
    return Decimal(whole.days * 86400 + whole.seconds) + Decimal("0." + (match[1] or "0"))


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Blocked("the client clock must carry an explicit offset")
    return value.isoformat(timespec="milliseconds")


def _uuid4(value, name: str) -> str:
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.version != 4 or str(parsed) != value:
        raise Blocked(f"{name}: expected a canonical uuid4")
    return value


def _cross(reported, computed: Decimal, name: str, limit: Decimal | None = None) -> None:
    """seconds_* are cross-checks only: within tolerance and on the same side of the limit."""
    value = _num(reported, name)
    if abs(value - computed) > CROSSCHECK_TOLERANCE or (limit is not None and (value <= limit) != (computed <= limit)):
        raise Blocked(f"{name} {reported} disagrees with the instants ({computed} s)")


def validate_binding(binding) -> dict:
    _obj(binding, "binding")
    keys = {"project": PROJECT_KEYS, "calibration": CALIBRATION_KEYS}.get(binding.get("mode"))
    _obj(binding, "binding", keys or {"mode"})
    if keys is None:
        raise Blocked("binding.mode must be project or calibration")
    for key, value in binding.items():
        (_hex if key.endswith("_sha256") else _str)(value, f"binding.{key}")
    return binding


def _operation(writer: str, row: str) -> str:
    if writer not in ROWS:
        raise Blocked(f"unknown writer {writer!r}")
    if row not in ROWS[writer]:
        raise Blocked(f"row {row!r} is not allowed for writer {writer!r}")
    return ROWS[writer][row]


# ---------------------------------------------------------------- files

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Blocked(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise Blocked(f"non-finite JSON number {value}")


def _encode(obj: dict) -> bytes:
    try:
        return (json.dumps(obj, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Blocked("request is not finite JSON") from exc


def read_bound(directory: Path, leaf: str, cap: int, *, uid: int | None = None,
               sha256: str | None = None, byte_length: int | None = None) -> tuple[dict, bytes, os.stat_result]:
    """Regular 0600 file, no symlink (directory or leaf), owner, cap, exact bytes, strict JSON."""
    if not isinstance(leaf, str) or not LEAF_RE.fullmatch(leaf) or ".." in leaf:
        raise Blocked(f"unsafe file name {leaf!r}")
    dir_fd = fd = None
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Blocked(f"{leaf}: not a regular file")
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != (os.getuid() if uid is None else uid):
            raise Blocked(f"{leaf}: must be mode 0600 and owned by the controller user")
        if info.st_size > cap:
            raise Blocked(f"{leaf}: oversize ({info.st_size} > {cap} bytes)")
        raw = b""
        while len(raw) <= cap:
            chunk = os.read(fd, cap + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        if len(raw) > cap or len(raw) != info.st_size:
            raise Blocked(f"{leaf}: changed while read or oversize")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise Blocked(f"{leaf}: {exc.__class__.__name__}: {exc.strerror or exc}") from exc
    finally:
        for handle in (fd, dir_fd):
            if handle is not None:
                os.close(handle)
    if byte_length is not None and len(raw) != byte_length:
        raise Blocked(f"{leaf}: byte_length {len(raw)} != recorded {byte_length}")
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise Blocked(f"{leaf}: sha256 differs from the recorded reference")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, Blocked):
            raise
        raise Blocked(f"{leaf}: incomplete or invalid JSON") from exc
    if not isinstance(obj, dict):
        raise Blocked(f"{leaf}: expected a JSON object")
    return obj, raw, info


def load_window(path: str | Path, window_sha256: str, *, uid: int | None = None) -> dict:
    """The window file the host script wrote, pinned by the sha256 the caller recorded."""
    path = Path(path)
    _hex(window_sha256, "window_sha256")
    try:
        window, _, _ = read_bound(path.parent, path.name, REQUEST_MAX, uid=uid, sha256=window_sha256)
    except FileNotFoundError as exc:
        raise Blocked("window file is missing") from exc
    need = {"window_id", "host_dir", "origin", "binding", "window_started_at", "window_ttl_minutes",
            "window_expires_at", "bytes_used", "app_container_id", "fwd_container_id", "creation_inspect",
            "data_dir", "data_dev", "data_inode", "data_mode", "controller_sha256", "executor_sha256"}
    if need - set(window):
        raise Blocked(f"window: missing {sorted(need - set(window))}")
    _str(window["window_id"], "window.window_id")
    host_dir = Path(_str(window["host_dir"], "window.host_dir"))
    try:
        real_dir = host_dir.is_absolute() and stat.S_ISDIR(host_dir.lstat().st_mode)
    except OSError:
        real_dir = False
    if not real_dir:
        raise Blocked("window.host_dir must be an absolute real directory")
    origin = urlsplit(_str(window["origin"], "window.origin"))
    if origin.scheme != "http" or origin.hostname != "100.110.162.4" or not origin.port or origin.path:
        raise Blocked("window.origin must be the literal http://100.110.162.4:<port>")
    validate_binding(window["binding"])
    start = instant(window["window_started_at"], "window.window_started_at")
    ttl = _int(window["window_ttl_minutes"], "window.window_ttl_minutes", 1, 720)
    if instant(window["window_expires_at"], "window.window_expires_at") != start + 60 * ttl:
        raise Blocked("window_expires_at is not window_started_at + TTL")
    _bytes_used(window["bytes_used"], "window.bytes_used")
    for key in ("app_container_id", "fwd_container_id", "controller_sha256", "executor_sha256"):
        _hex(window[key], f"window.{key}")
    _obj(window["creation_inspect"], "window.creation_inspect", {"app", "forwarder"})
    for target in ("app", "forwarder"):
        _ref(window["creation_inspect"][target], f"window.creation_inspect.{target}", INSPECT_MAX)
    if not Path(_str(window["data_dir"], "window.data_dir")).is_absolute():
        raise Blocked("window.data_dir must be absolute")
    for key in ("data_dev", "data_inode"):
        _int(window[key], f"window.{key}", 0)
    if window["data_mode"] != 0o700:
        raise Blocked("window.data_mode must be 0700 (448)")
    return {**window, "_sha256": window_sha256, "_path": str(path), "_host": origin.netloc,
            "_port": origin.port}


def _bytes_used(value, name: str) -> dict:
    _obj(value, name, BYTES_KEYS)
    parts = [_int(value[key], f"{name}.{key}", 0, null=True) for key in ("app_copy", "data", "tmp", "work")]
    total = _int(value["total"], f"{name}.total", 0, null=True)
    complete = _bool(value["complete"], f"{name}.complete")
    instant(value["measured_at"], f"{name}.measured_at")
    if complete and (None in parts or total != sum(parts)):
        raise Blocked(f"{name}: complete but parts missing or total != sum")
    if not complete and total is not None:
        raise Blocked(f"{name}: incomplete measurement must have total null")
    return value


def _ref(value, name: str, cap: int) -> dict:
    _obj(value, name, {"path", "sha256", "byte_length"})
    _str(value["path"], f"{name}.path")
    _hex(value["sha256"], f"{name}.sha256")
    _int(value["byte_length"], f"{name}.byte_length", 1, cap)
    return value


# ---------------------------------------------------------------- requests and sequence

def make_request(window: dict, row: str, sequence: int, *, writer: str = "checker", expires_at: str,
                 action: str, expected: str, now: datetime, not_before: str | None = None) -> dict:
    """The row fixes operation and signal; the request never carries either choice."""
    operation = _operation(writer, row)
    end = instant(expires_at, "expires_at")
    now_s = instant(_iso(now), "now")
    window_end = instant(window["window_expires_at"], "window_expires_at")
    if now_s >= window_end:
        raise Blocked("window_expires_at has passed: no request may be written")
    if end > window_end:
        raise Blocked("expires_at is later than window_expires_at")
    if end <= now_s:
        raise Blocked("expires_at has passed")
    host_dir = Path(window["host_dir"])
    request = {"schema": REQUEST_SCHEMA, "binding": dict(window["binding"]), "window_id": window["window_id"],
               "row": row, "operation": operation, "host_action": operation, "writer": writer,
               "request_id": str(uuid.uuid4()), "origin": window["origin"],
               "receipt_file": str(host_dir / f"{row}.json"), "action": action, "expected": expected,
               "since": _iso(now), "not_before": not_before or _iso(now), "expires_at": expires_at,
               "sequence": sequence, "wait_seconds": float(end - now_s), "receipt_format": RECEIPT_SCHEMA,
               "write": True}
    validate_request(request, window)
    return request


def validate_request(request, window: dict) -> dict:
    _obj(request, "request", REQUEST_KEYS)
    if request["schema"] != REQUEST_SCHEMA or request["receipt_format"] != RECEIPT_SCHEMA:
        raise Blocked("request: unknown schema or receipt_format")
    if validate_binding(request["binding"]) != window["binding"] or request["window_id"] != window["window_id"]:
        raise Blocked("request: binding or window_id is not this window's")
    operation = _operation(request["writer"], request["row"])
    if request["operation"] != operation or request["host_action"] != operation:
        raise Blocked("request: operation/host_action differ from the fixed row table")
    _uuid4(request["request_id"], "request.request_id")
    _int(request["sequence"], "request.sequence", 1)
    if request["origin"] != window["origin"]:
        raise Blocked("request: origin is not the window's")
    if request["receipt_file"] != str(Path(window["host_dir"]) / f"{request['row']}.json"):
        raise Blocked("request: receipt_file is not the fixed row path")
    for key in ("action", "expected"):
        _str(request[key], f"request.{key}")
    since = instant(request["since"], "request.since")
    begin = instant(request["not_before"], "request.not_before")
    end = instant(request["expires_at"], "request.expires_at")
    if _num(request["wait_seconds"], "request.wait_seconds") <= 0 or request["write"] is not True:
        raise Blocked("request: wait_seconds must be > 0 and write must be true")
    if not since <= end or not begin < end or end > instant(window["window_expires_at"], "window_expires_at"):
        raise Blocked("request: times out of order or beyond window_expires_at")
    if len(_encode(request)) > REQUEST_MAX:
        raise Blocked("request exceeds 64 KiB")
    return request


def write_request(window: dict, request: dict, *, clock: Callable[[], datetime]) -> bytes:
    """Temporary file in the same folder, fsync, 0600, rename to WAITING-<row>.json."""
    validate_request(request, window)
    raw = _encode(request)
    host_dir = Path(window["host_dir"])
    temporary = host_dir / f".WAITING-{request['row']}.{request['request_id']}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        now = instant(_iso(clock()), "now")
        if now >= min(instant(window["window_expires_at"], "w"), instant(request["expires_at"], "e")):
            raise Blocked("window or request expired before publication")
        os.replace(temporary, host_dir / f"WAITING-{request['row']}.json")
        temporary = None
    except OSError as exc:
        raise Blocked(f"could not publish the request: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return raw


def read_sequence(window: dict, writer: str, *, uid: int | None = None) -> int:
    """Controller's SEQ-<writer>.json, under the receipt file rules; anything else BLOCKED."""
    if writer not in ROWS:
        raise Blocked(f"unknown writer {writer!r}")
    try:
        record, _, _ = read_bound(Path(window["host_dir"]), f"SEQ-{writer}.json", RECEIPT_MAX, uid=uid)
    except FileNotFoundError as exc:
        raise Blocked(f"SEQ-{writer}.json is missing") from exc
    _obj(record, f"SEQ-{writer}", SEQ_KEYS)
    if record["window_id"] != window["window_id"] or record["writer"] != writer:
        raise Blocked(f"SEQ-{writer}.json is for another window or writer")
    if record["last_request_id"] is not None:
        _uuid4(record["last_request_id"], "SEQ.last_request_id")
    instant(record["updated_at"], "SEQ.updated_at")
    return _int(record["expected_sequence"], "SEQ.expected_sequence", 1)


# ---------------------------------------------------------------- evidence snapshots

class Evidence:
    """Loads controller-written snapshots by reference: exact bytes, under host_dir only."""

    def __init__(self, window: dict, uid: int | None = None):
        self.window, self.uid = window, uid
        self.host_dir = Path(window["host_dir"])

    def load(self, ref, name: str, cap: int) -> dict:
        _ref(ref, name, cap)
        path = ref["path"]
        leaf = path.removeprefix(f"{self.host_dir}/evidence/") if path.startswith("/") else path.removeprefix("evidence/")
        if leaf == path or "/" in leaf:
            raise Blocked(f"{name}: path is not under host_dir/evidence/")
        try:
            obj, _, _ = read_bound(self.host_dir / "evidence", leaf, cap, uid=self.uid,
                                   sha256=ref["sha256"], byte_length=ref["byte_length"])
        except FileNotFoundError as exc:
            raise Blocked(f"{name}: referenced snapshot is missing") from exc
        return obj

    def listing(self, ref, name: str) -> dict:
        snap = _obj(self.load(ref, name, SNAPSHOT_MAX), name, LISTING_KEYS)
        if snap["schema"] != "ops-host-listing/1" or snap["window_id"] != self.window["window_id"]:
            raise Blocked(f"{name}: wrong schema or window")
        if snap["target"] != "data" or snap["path"] != self.window["data_dir"]:
            raise Blocked(f"{name}: not the window's data directory")
        instant(snap["observed_at"], f"{name}.observed_at")
        if _bool(snap["truncated"], f"{name}.truncated") or snap["error"] is not None:
            raise Blocked(f"{name}: data listing truncated or incomplete ({snap['error']})")
        if not _bool(snap["complete"], f"{name}.complete"):
            raise Blocked(f"{name}: data listing incomplete")
        entries = snap["entries"]
        if not isinstance(entries, list) or _int(snap["entry_count"], f"{name}.entry_count", 0, 10_000) != len(entries):
            raise Blocked(f"{name}: entry_count disagrees with entries")
        names = []
        for i, entry in enumerate(entries):
            where = f"{name}.entries[{i}]"
            _obj(entry, where, ENTRY_KEYS)
            names.append(_str(entry["name"], f"{where}.name"))
            if entry["type"] not in ("regular", "directory", "link", "fifo", "socket", "device"):
                raise Blocked(f"{where}.type unknown")
            _int(entry["size"], f"{where}.size", 0, null=True)
            _int(entry["mtime_ns"], f"{where}.mtime_ns", 0, null=True)
            _str(entry["target"], f"{where}.target", null=True)
            _bool(entry["target_truncated"], f"{where}.target_truncated")
            _hex(entry["sha256"], f"{where}.sha256", null=True)
        if names != sorted(names) or len(set(names)) != len(names):
            raise Blocked(f"{name}: entries not sorted by unique name")
        tree = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
        if snap["tree_sha256"] != tree:
            raise Blocked(f"{name}: tree_sha256 does not match its entries")
        return snap

    def inspect(self, ref, name: str, target: str) -> dict:
        snap = _obj(self.load(ref, name, INSPECT_MAX), name,
                    {"schema", "window_id", "container_id", "runtime", "state", "observed_at"})
        expected_id = self.window["app_container_id" if target == "app" else "fwd_container_id"]
        if snap["schema"] != "ops-host-inspect/1" or snap["window_id"] != self.window["window_id"]:
            raise Blocked(f"{name}: wrong schema or window")
        if snap["container_id"] != expected_id:
            raise Blocked(f"{name}: inspect of another container (wrong target)")
        _obj(snap["runtime"], f"{name}.runtime", INSPECT_RUNTIME)
        state = _obj(snap["state"], f"{name}.state", INSPECT_STATE)
        _bool(state["running"], f"{name}.state.running")
        _str(state["status"], f"{name}.state.status")
        instant(state["started_at"], f"{name}.state.started_at")
        instant(state["finished_at"], f"{name}.state.finished_at")
        _int(state["exit_code"], f"{name}.state.exit_code")
        _bool(state["oom_killed"], f"{name}.state.oom_killed")
        _int(state["restart_count"], f"{name}.state.restart_count", 0)
        instant(snap["observed_at"], f"{name}.observed_at", ms=True)
        creation = self.creation(target) if ref != self.window["creation_inspect"][target] else snap
        if snap["runtime"] != creation["runtime"]:
            raise Blocked(f"{name}: inspect drift (runtime differs from creation)")
        return snap

    def creation(self, target: str) -> dict:
        return self.inspect(self.window["creation_inspect"][target], f"creation_inspect.{target}", target)

    def terminal(self, ref, name: str, exit_code: int, exited_at: Decimal, sent_at: Decimal,
                 begin: Decimal, end: Decimal) -> dict:
        """stop_inspect: the app's own terminal poll for this operation (CORRECTION-1 3.2)."""
        if ref is None:
            raise Blocked(f"{name} is null: no terminal inspect")
        snap = self.inspect(ref, name, "app")
        state = snap["state"]
        if state["running"] or state["exit_code"] != exit_code:
            raise Blocked(f"{name}: not this stop's terminal state (running or exit_code differs)")
        if instant(state["finished_at"], "finished_at") != exited_at:
            raise Blocked(f"{name}: finished_at differs from exited_at (stale snapshot)")
        observed = instant(snap["observed_at"], "observed_at")
        if not begin <= sent_at <= exited_at <= observed <= end:
            raise Blocked(f"{name}: not observed inside this operation")
        return snap


# ---------------------------------------------------------------- facts (validation) per operation

def _crash_facts(ev: Evidence, r: dict, row: str) -> dict:
    exit_code = _int(r["exit_code"], "exit_code")
    if r["signal"] != ROW_SIGNAL[row]:
        raise Blocked("signal differs from the fixed row table")
    sent = instant(r["kill_sent_at"], "kill_sent_at", ms=True)
    if r.get("signal_sent_at") is not None and instant(r["signal_sent_at"], "signal_sent_at", ms=True) != sent:
        raise Blocked("signal_sent_at differs from kill_sent_at")
    exited = instant(r["exited_at"], "exited_at", ms=True)
    begin, end = instant(r["started_at"], "started_at"), instant(r["ended_at"], "ended_at")
    snap = ev.terminal(r["stop_inspect"], "stop_inspect", exit_code, exited, sent, begin, end)
    if _str(r["exit_status"], "exit_status") != snap["state"]["status"]:
        raise Blocked("exit_status differs from the terminal inspect's state")
    ev.listing(r["data_listing_after_exit"], "data_listing_after_exit")
    return {"exit_code": exit_code, "listener_gone": _bool(r["listener_gone"], "listener_gone"),
            "origin_refused": _bool(r["origin_refused"], "origin_refused"), "exited_at": exited,
            "data_listing_after_exit": r["data_listing_after_exit"]}


def _stop_facts(ev: Evidence, e: dict, row: str, exit_code, begin: Decimal, end: Decimal) -> dict:
    exit_code = _int(exit_code, "stop leg exit_code")
    if e["signal"] != ROW_SIGNAL[row]:
        raise Blocked("signal differs from the fixed row table")
    sent = instant(e["signal_sent_at"], "signal_sent_at", ms=True)
    exited = instant(e["exited_at"], "exited_at", ms=True)
    elapsed = exited - sent
    if elapsed < 0:
        raise Blocked("exited_at precedes signal_sent_at")
    _cross(e["seconds_to_exit"], elapsed, "seconds_to_exit", STOP_LIMIT)
    if _bool(e["within_10s"], "within_10s") != (elapsed <= STOP_LIMIT):
        raise Blocked("within_10s disagrees with the instants")
    kill = instant(e["kill_sent_at"], "kill_sent_at", ms=True, null=True)
    if _bool(e["forced_kill"], "forced_kill") != (kill is not None) or (kill is not None and kill < sent):
        raise Blocked("forced_kill / kill_sent_at disagree")
    stopped = _bool(e["stopped_line_seen"], "stopped_line_seen")
    stopped_at = instant(e["stopped_line_at"], "stopped_line_at", ms=True, null=True)
    if stopped != (stopped_at is not None) or (stopped_at is not None and stopped_at < sent):
        raise Blocked("stopped_line_seen / stopped_line_at disagree (line must follow the signal)")
    traceback = _bool(e["traceback_seen"], "traceback_seen")
    line = _str(e["traceback_line"], "traceback_line", null=True, max_bytes=512)
    first = instant(e["traceback_first_at"], "traceback_first_at", ms=True, null=True)
    if traceback != (line is not None) or traceback != (first is not None) or (first is not None and first < sent):
        raise Blocked("traceback_seen / traceback_line / traceback_first_at disagree")
    ev.terminal(e["stop_inspect"], "stop_inspect", exit_code, exited, sent, begin, end)
    ev.listing(e["data_listing_after_exit"], "data_listing_after_exit")
    return {"exit_code": exit_code, "seconds_to_exit": elapsed, "kill_sent": kill is not None,
            "stopped_line_seen": stopped, "traceback_seen": traceback, "exited_at": exited,
            "data_listing_after_exit": e["data_listing_after_exit"]}


def _audit(ev: Evidence, ref, request: dict, prior_exit: Decimal) -> list[dict]:
    """start-audit/1: every read and the only mutations (one docker start per recorded id)."""
    _ref(ref, "start_audit_ref", AUDIT_MAX)
    leaf = f"audit-{request['request_id']}-{request['sequence']}.json"
    if ref["path"] != leaf:
        raise Blocked("start_audit_ref.path is not this request's audit leaf")
    try:
        snap, _, _ = read_bound(ev.host_dir, leaf, AUDIT_MAX, uid=ev.uid, sha256=ref["sha256"],
                                byte_length=ref["byte_length"])
    except FileNotFoundError as exc:
        raise Blocked("start audit file is missing") from exc
    _obj(snap, "start-audit", {"schema", "window_id", "writer", "request_id", "sequence", "row", "operation",
                               "commands_run"})
    if snap["schema"] != "start-audit/1" or any(snap[k] != request[k] for k in
                                                 ("window_id", "writer", "request_id", "sequence", "row", "operation")):
        raise Blocked("start audit is for another request")
    runs = snap["commands_run"]
    if not isinstance(runs, list) or not runs or len(runs) > AUDIT_ENTRIES_MAX:
        raise Blocked("commands_run must be a nonempty list of at most 1024 entries")
    w, previous = ev.window, prior_exit
    ids = {"app": w["app_container_id"], "forwarder": w["fwd_container_id"]}
    for i, c in enumerate(runs):
        where = f"commands_run[{i}]"
        _obj(c, where, AUDIT_KEYS)
        c["_start"], c["_end"] = instant(c["started_at"], where, ms=True), instant(c["ended_at"], where, ms=True)
        if c["_start"] < previous or c["_end"] < c["_start"]:
            raise Blocked(f"{where}: overlapping, out of order, or before the recorded exit")
        previous = c["_end"]
        op, p, res = c["op"], c["params"], c["result"]
        if op in ("docker-start", "docker-inspect"):
            _obj(p, f"{where}.params", {"target", "container_id"})
            if p["target"] not in ids or p["container_id"] != ids[p["target"]]:
                raise Blocked(f"{where}: {op} of an unrecorded container")
            if c["kind"] != "process" or c["argv"] != ["docker", op.split("-")[1], p["container_id"]]:
                raise Blocked(f"{where}: {op} argv is not the fixed command")
            if op == "docker-start":
                _obj(res, f"{where}.result", {"outcome", "started", "error"})
                ok = res["outcome"] == "ok" and res["started"] is True and res["error"] is None and c["exit_code"] == 0
            else:
                _obj(res, f"{where}.result", {"outcome", "snapshot", "error"})
                ok = res["outcome"] == "ok" and res["error"] is None and c["exit_code"] == 0
                if ok:
                    ev.inspect(res["snapshot"], f"{where}.snapshot", p["target"])
        elif op in ("data-stat", "data-list", "health") or op == "listener":
            if op == "listener" and c["kind"] == "process":
                if c["argv"] != ["ss", "-ltnH", "sport", "=", f":{w['_port']}"] or type(c["exit_code"]) is not int:
                    raise Blocked(f"{where}: listener argv is not the fixed ss command")
            elif c["kind"] != "inprocess" or c["argv"] is not None or c["exit_code"] is not None:
                raise Blocked(f"{where}: in-process read must have argv and exit_code null")
            if op == "data-stat":
                _obj(p, f"{where}.params", {"path", "follow_symlinks"})
                _obj(res, f"{where}.result", {"outcome", "dev", "inode", "mode", "error"})
                if p != {"path": w["data_dir"], "follow_symlinks": False}:
                    raise Blocked(f"{where}: data-stat of another path or following links")
                ok = res["outcome"] == "ok" and res["error"] is None
                if ok and (res["dev"], res["inode"], res["mode"]) != (w["data_dev"], w["data_inode"], 0o700):
                    raise Blocked(f"{where}: data dev:inode or mode differs from the window's")
            elif op == "data-list":
                if p != {"path": w["data_dir"], "follow_symlinks": False, "max_entries": 10_000, "max_depth": 16}:
                    raise Blocked(f"{where}: data-list params are not the fixed bounded read")
                _obj(res, f"{where}.result", {"outcome", "snapshot", "error"})
                ok = res["outcome"] == "ok" and res["error"] is None
                if ok:
                    ev.listing(res["snapshot"], f"{where}.snapshot")
            elif op == "listener":
                _obj(p, f"{where}.params", {"address", "port"})
                _obj(res, f"{where}.result", {"outcome", "present", "sockets", "error"})
                if p["port"] != w["_port"]:
                    raise Blocked(f"{where}: listener check of another port")
                ok = res["outcome"] == "ok" and res["error"] is None and type(res["present"]) is bool
                if ok and (not isinstance(res["sockets"], list) or res["present"] != bool(res["sockets"]) or any(
                        _obj(s, f"{where}.sockets", {"address", "port", "protocol"})["protocol"] != "tcp"
                        or s["port"] != w["_port"] for s in res["sockets"])):
                    raise Blocked(f"{where}: listener sockets disagree with present")
            else:
                ok = _probe(c, where, w)
        else:
            raise Blocked(f"{where}: unknown or unreviewed operation {op!r}")
        if not ok and op != "health":
            raise Blocked(f"{where}: host read or start failed ({res.get('error')})")
        c["_ok"] = ok
    return runs


def _probe(c: dict, where: str, w: dict) -> bool:
    _obj(c["params"], f"{where}.params", {"method", "url", "host", "timeout_seconds"})
    if c["params"] != {"method": "GET", "url": w["origin"] + "/api/items", "host": w["_host"], "timeout_seconds": 3}:
        raise Blocked(f"{where}: health probe target, Host or timeout is not the fixed one")
    res = _obj(c["result"], f"{where}.result", {"outcome", "status", "response_at", "elapsed_seconds", "error"})
    _num(res["elapsed_seconds"], f"{where}.elapsed_seconds")
    if res["outcome"] == "response":
        status = _int(res["status"], f"{where}.status", 100, 599)
        at = instant(res["response_at"], f"{where}.response_at", ms=True)
        if res["error"] is not None or not c["_start"] <= at <= c["_end"]:
            raise Blocked(f"{where}: response outside its probe")
        if status == 400:
            raise Blocked(f"{where}: health answered 400 (Host not allowed): the probe asked wrongly")
        c["_at"] = at
    elif res["outcome"] in ("refused", "timeout", "connection-error"):
        if res["status"] is not None or res["response_at"] is not None or res["error"] != res["outcome"]:
            raise Blocked(f"{where}: negative probe must have null status/time and its own error")
    else:
        raise Blocked(f"{where}: health probe host error ({res['error']})")
    return True


def _start_facts(ev: Evidence, e: dict, request: dict, prior: dict, begin: Decimal, end: Decimal,
                 standalone: bool) -> dict:
    w = ev.window
    if e["data_listing_after_exit"] != prior["data_listing_after_exit"]:
        raise Blocked("data_listing_after_exit is not the prior exit's listing")
    after_exit = ev.listing(e["data_listing_after_exit"], "data_listing_after_exit")
    before_start = ev.listing(e["data_listing_before_start"], "data_listing_before_start")
    match = (after_exit["entries"], after_exit["tree_sha256"]) == (before_start["entries"], before_start["tree_sha256"])
    if _bool(e["listings_match"], "listings_match") != match:
        raise Blocked("listings_match disagrees with the listings")
    if not match:
        raise Blocked("data listing before start differs from the listing after exit")
    if instant(e["audit_started_at"], "audit_started_at", ms=True) != prior["exited_at"]:
        raise Blocked("audit_started_at is not the recorded exit")
    if _bool(e["audit_complete"], "audit_complete") is not True:
        raise Blocked("start audit is not complete")
    audit_end = instant(e["audit_ended_at"], "audit_ended_at", ms=True)
    runs = _audit(ev, e["start_audit_ref"], request, prior["exited_at"])
    if runs[-1]["_end"] > audit_end:
        raise Blocked("audit entries run past audit_ended_at")
    starts = [c for c in runs if c["op"] == "docker-start"]
    if [c["params"]["target"] for c in starts] != ["app", "forwarder"]:
        raise Blocked("mutations must be exactly one docker start of the app, then the forwarder")
    app_start, fwd_start = starts
    t0 = instant(e["start_sent_at"], "start_sent_at", ms=True)
    if not (prior["exited_at"] <= t0 <= app_start["_start"] and begin <= t0):
        raise Blocked("start_sent_at is not just before the app start")
    deadline = t0 + HEALTH_LIMIT
    pre = [c for c in runs if c["_end"] <= app_start["_start"]]
    post = [c for c in runs if c["_start"] >= fwd_start["_end"]]
    if any(c not in pre + post + starts for c in runs):
        raise Blocked("an operation ran between the two starts")

    def pick(entries, op, target=None, last=True):
        found = [c for c in entries if c["op"] == op and c["_ok"] and (target is None or c["params"]["target"] == target)]
        if not found:
            raise Blocked(f"required {op}{' ' + target if target else ''} is missing from the start audit")
        return found[-1] if last else found[0]

    stat_before, stat_after = pick(pre, "data-stat"), pick(post, "data-stat", last=False)
    same_inode = (stat_before["result"]["dev"], stat_before["result"]["inode"]) == \
        (stat_after["result"]["dev"], stat_after["result"]["inode"])
    if pick(pre, "data-list")["result"]["snapshot"] != e["data_listing_before_start"]:
        raise Blocked("data_listing_before_start is not the last listing before the app start")
    if any(c["op"] == "listener" and c["result"]["present"] for c in pre):
        raise Blocked("the app port was already listening before the start")
    listener = pick(post, "listener")
    if _bool(e["listener_present"], "listener_present") != listener["result"]["present"]:
        raise Blocked("listener_present disagrees with the audit")
    identity = _obj(e["identity_evidence"], "identity_evidence", {"window_sha256", "app", "forwarder"})
    if identity["window_sha256"] != w["_sha256"]:
        raise Blocked("identity_evidence is bound to another window file")
    after = {}
    for target in ("app", "forwarder"):
        t = _obj(identity[target], f"identity_evidence.{target}",
                 {"container_id", "creation_record", "before_inspect", "after_inspect",
                  "before_matches_creation", "after_matches_creation"})
        if t["container_id"] != w["app_container_id" if target == "app" else "fwd_container_id"]:
            raise Blocked(f"identity_evidence.{target}: another container id")
        if t["creation_record"] != w["creation_inspect"][target]:
            raise Blocked(f"identity_evidence.{target}: creation_record is not the window's")
        if t["before_matches_creation"] is not True or t["after_matches_creation"] is not True:
            raise Blocked(f"identity_evidence.{target}: inspect does not match creation")
        if t["before_inspect"] != pick(pre, "docker-inspect", target)["result"]["snapshot"] or \
                t["after_inspect"] != pick(post, "docker-inspect", target, last=False)["result"]["snapshot"]:
            raise Blocked(f"identity_evidence.{target}: inspect refs are not the audited reads")
        if ev.inspect(t["before_inspect"], f"{target}.before_inspect", target)["state"]["running"]:
            raise Blocked(f"identity_evidence.{target}: was running before the start")
        snap = after[target] = ev.inspect(t["after_inspect"], f"{target}.after_inspect", target)
        started = instant(snap["state"]["started_at"], "state.started_at")
        if not snap["state"]["running"] or not t0 <= started <= instant(snap["observed_at"], "observed_at"):
            raise Blocked(f"identity_evidence.{target}: not running from this start")
    if instant(e["app_started_at"], "app_started_at") != instant(after["app"]["state"]["started_at"], "started_at"):
        raise Blocked("app_started_at differs from the app's after-start inspect")
    health = _health(e, [c for c in runs if c["op"] == "health"], t0, deadline, fwd_start["_end"], w)
    if health["outcome"] == "healthy" and not listener["result"]["present"]:
        raise Blocked("health answered but no listener: contradictory evidence")
    if audit_end < (health["health_at"] if health["health_at"] is not None else deadline) or audit_end > end:
        raise Blocked("audit_ended_at does not cover exit to first 200 or the 30 s deadline")
    if standalone and _bool(e["same_inode"], "same_inode") != same_inode:
        raise Blocked("same_inode disagrees with the audited data-stat reads")
    if not same_inode:
        raise Blocked("data dev:inode changed across the start")
    return health


def _health(e: dict, probes: list[dict], t0: Decimal, deadline: Decimal, fwd_end: Decimal, w: dict) -> dict:
    """QA's cadence: first probe <= 0.750 s after forwarder start, gaps <= 0.750 s, none at/after deadline."""
    if not probes:
        raise Blocked("no health probe in the audit (host failure)")
    previous, first_200, last_status = fwd_end, None, None
    for i, c in enumerate(probes):
        if c["_start"] < previous or c["_start"] - previous > CADENCE_GAP or c["_start"] >= deadline:
            raise Blocked(f"health probe {i}: cadence gap, overlap or start at/after the deadline")
        if first_200 is not None:
            raise Blocked("health probes continue after the first 200")
        status = c["result"]["status"]
        last_status = status if status is not None else last_status
        if status == 200:
            first_200 = c["_at"]
        previous = c["_end"]
    o = _obj(e["health_observation"], "health_observation", OBSERVATION_KEYS)
    health_at = instant(e["health_at"], "health_at", ms=True, null=True)
    elapsed_total = _num(e["health_elapsed_seconds"], "health_elapsed_seconds")
    if first_200 is not None:
        outcome = "healthy" if first_200 - t0 <= HEALTH_LIMIT else "late"
        if health_at != first_200:
            raise Blocked("health_at is not the first valid 200" if health_at is not None
                          else "health_at is null although a 200 was observed")
        _cross(e["seconds_to_health"], first_200 - t0, "seconds_to_health", HEALTH_LIMIT)
        _cross(e["health_elapsed_seconds"], first_200 - t0, "health_elapsed_seconds", HEALTH_LIMIT)
    else:
        outcome = "miss"
        if "health_at" not in e or "seconds_to_health" not in e or health_at is not None \
                or e["seconds_to_health"] is not None:
            raise Blocked("no 200 observed: health_at and seconds_to_health must be present and null")
        if elapsed_total < HEALTH_LIMIT or previous < deadline - CADENCE_GAP:
            raise Blocked("timeout not measured through the 30 s deadline")
    observed_until = instant(o["observed_until"], "observed_until", ms=True)
    if (o["method"], o["path"], o["host"]) != ("GET", "/api/items", w["_host"]) or o["outcome"] != outcome \
            or o["probe_count"] != len(probes) or o["complete"] is not True \
            or o["elapsed_seconds"] != e["health_elapsed_seconds"] or o["last_http_status"] != last_status \
            or e["health_code"] != last_status \
            or observed_until < (first_200 if first_200 is not None else deadline) \
            or not probes[0]["_start"] <= instant(o["first_probe_at"], "first_probe_at", ms=True) <= probes[0]["_end"] \
            or not probes[-1]["_start"] <= instant(o["last_probe_at"], "last_probe_at", ms=True) <= probes[-1]["_end"]:
        raise Blocked("health_observation disagrees with the audited probes")
    return {"outcome": outcome, "health_at": first_200,
            "seconds_to_health": None if first_200 is None else first_200 - t0}


# ---------------------------------------------------------------- the pure verdict rule

def verdict(operation: str, facts: dict) -> tuple[str, list[str]]:
    """QA's rule (HOST-STEPS, host-publication-v2) on validated facts; no I/O."""
    if operation == "crash":
        misses = [k for k, ok in (("decision DONE", facts["decision"] == "DONE"),
                                  ("exit_code 137", facts["exit_code"] == 137),
                                  ("listener_gone", facts["listener_gone"]),
                                  ("origin_refused", facts["origin_refused"])) if not ok]
        return ("BLOCKED", [f"crash not counted: {m}" for m in misses]) if misses else ("PASS", [])
    if operation == "stop":
        misses = [k for k, ok in (("exit_code 0", facts["exit_code"] == 0),
                                  ("exit within 10.000 s", facts["seconds_to_exit"] <= STOP_LIMIT),
                                  ("no KILL", not facts["kill_sent"]),
                                  ("Stopped. line", facts["stopped_line_seen"]),
                                  ("no traceback", not facts["traceback_seen"]),
                                  ("listener gone", facts["listener_gone"])) if not ok]
        return ("FAIL", [f"stop: {m} missed" for m in misses]) if misses else ("PASS", [])
    if operation == "start":
        if facts["outcome"] == "healthy":
            return "PASS", []
        return "FAIL", ["start: health after 30.000 s" if facts["outcome"] == "late"
                        else "start: no 200 within 30.000 s (measured timeout)"]
    if operation == "restart":
        stop, start = verdict("stop", facts["stop"]), verdict("start", facts["start"])
        reasons = stop[1] + start[1]
        return ("FAIL" if reasons else "PASS"), reasons
    raise Blocked(f"no verdict rule for {operation}")


def _agree(status: str, reasons: list[str], decision: str, failure_kind, label: str) -> tuple[str, list[str]]:
    """Checker and Ops must agree: PASS<->DONE, FAIL<->FAILED app; otherwise BLOCKED with both."""
    ops = "DONE" if decision == "DONE" else f"{decision} {failure_kind}"
    if (status, ops) in (("PASS", "DONE"), ("FAIL", "FAILED app")):
        return status, reasons
    if status == "BLOCKED":
        return status, reasons
    return "BLOCKED", [f"{label}: checker {status} disagrees with Ops {ops}", *reasons]


# ---------------------------------------------------------------- receipts

def _common(ev: Evidence, request: dict, r: dict, request_raw: bytes) -> dict:
    """Echoes and counters first: they decide whether the sequence is known, whatever the verdict."""
    if r.get("schema") != RECEIPT_SCHEMA:
        raise Blocked("unknown receipt schema")
    missing = COMMON_KEYS - set(r)
    if missing:
        raise Blocked(f"receipt missing {sorted(missing)}")
    for key in ("writer", "request_id", "sequence", "binding", "window_id", "row", "operation"):
        if r[key] != request[key] or type(r[key]) is not type(request[key]):
            raise Blocked(f"receipt {key} does not echo the request ({r[key]!r} != {request[key]!r})")
    used = _bool(r["sequence_used"], "sequence_used")
    expected = _int(r["expected_sequence"], "expected_sequence", 1)
    if used and expected != request["sequence"] + 1:
        raise Blocked("sequence_used but expected_sequence is not sequence + 1")
    if not used and r["decision"] != "REFUSED":
        raise Blocked("an unadmitted request must be REFUSED")
    return {"sequence_valid": True, "sequence_used": used, "expected_sequence": expected}


def _envelope(ev: Evidence, request: dict, r: dict, request_raw: bytes, seen: Decimal | None) -> None:
    w = ev.window
    if r["host_action"] != r["operation"]:
        raise Blocked("host_action differs from operation")
    if r["request_sha256"] != hashlib.sha256(request_raw).hexdigest():
        raise Blocked("request_sha256 is not the published request's")
    if (r["controller_sha256"], r["executor_sha256"]) != (w["controller_sha256"], w["executor_sha256"]):
        raise Blocked("controller or executor hash is not the window's")
    _hex(r["sums_sha256"], "sums_sha256")
    if r["decision"] not in ("DONE", "FAILED", "REFUSED") or r["failure_kind"] not in (None, "app", "host") \
            or (r["decision"] == "FAILED") == (r["failure_kind"] is None) or _bool(r["done"], "done") != (r["decision"] == "DONE"):
        raise Blocked("decision, failure_kind and done are inconsistent")
    for key in ("by", "note", "reason"):
        if not isinstance(r[key], str):
            raise Blocked(f"{key} must be a string")
    begin, end = instant(r["started_at"], "started_at"), instant(r["ended_at"], "ended_at")
    at = instant(r["at"], "at")
    instant(r["seen_at"], "seen_at")
    if not begin <= end <= at:
        raise Blocked("started_at, ended_at and at are not in order")
    if r["decision"] != "REFUSED" and begin < instant(request["not_before"], "not_before"):
        raise Blocked("operation started before not_before")
    if at > instant(request["expires_at"], "expires_at") or (seen is not None and seen > instant(request["expires_at"], "e")):
        raise Blocked("late receipt (after expires_at)")
    if r["lane"] != LANE[r["operation"]]:
        raise Blocked("lane is not the operation's")
    if (r["app_container_id"], r["fwd_container_id"]) != (w["app_container_id"], w["fwd_container_id"]):
        raise Blocked("container ids are not the window's")
    if _int(r["window_ttl_minutes"], "window_ttl_minutes", 1, 720) != w["window_ttl_minutes"] or \
            instant(r["window_expires_at"], "window_expires_at") != instant(w["window_expires_at"], "w"):
        raise Blocked("window_ttl_minutes / window_expires_at differ from the window")
    _bytes_used(r["bytes_used"], "bytes_used")
    operation = r["operation"]
    keys = set(r) - COMMON_KEYS
    aliases = keys & REJECTED_ALIASES
    if aliases:
        raise Blocked(f"legacy or retired field names {sorted(aliases)}")
    stray = keys - ALLOWED_ROOT[operation]
    if stray:
        raise Blocked(f"fields not allowed on a {operation} receipt root {sorted(stray)}")
    if r["decision"] in ("DONE", "FAILED") and r["failure_kind"] != "host":
        need = REQUIRED_ROOT[operation] - set(r)
        if need:
            raise Blocked(f"{operation} receipt missing {sorted(need)}")


def judge_receipt(window: dict, request: dict, receipt, request_raw: bytes, *, uid: int | None = None,
                  seen: datetime | None = None, prior_crash_sha256: str | None = None) -> dict:
    """Authenticated receipt -> PASS / FAIL / BLOCKED, with the counters and window fields recorded."""
    ev = Evidence(window, uid)
    result = {"row": request["row"], "writer": request["writer"], "operation": request["operation"],
              "request_id": request["request_id"], "sequence": request["sequence"], "sequence_valid": False,
              "receipt": receipt}
    try:
        result.update(_common(ev, request, _obj(receipt, "receipt"), request_raw))
        r = receipt
        result.update(decision=r["decision"], failure_kind=r["failure_kind"],
                      window_ttl_minutes=r["window_ttl_minutes"], window_expires_at=r["window_expires_at"],
                      bytes_used=r["bytes_used"])
        _envelope(ev, request, r, request_raw, None if seen is None else instant(_iso(seen), "seen"))
        if r["decision"] == "REFUSED" or r["failure_kind"] == "host":
            raise Blocked(f"Ops {r['decision']}{' host' if r['failure_kind'] else ''}: {r['reason']}")
        status, reasons, facts = _judge(ev, request, r, prior_crash_sha256)
    except Blocked as exc:
        return {**result, "status": "BLOCKED", "reasons": [str(exc)]}
    return {**result, "status": status, "reasons": reasons, "facts": facts}


def _judge(ev: Evidence, request: dict, r: dict, prior_crash_sha256: str | None):
    operation, row = r["operation"], r["row"]
    begin, end = instant(r["started_at"], "started_at"), instant(r["ended_at"], "ended_at")
    if operation == "engine-image":
        if r["decision"] != "DONE" or r["exit_code"] is not None:
            raise Blocked("engine-image reading must be DONE with exit_code null")
        if not isinstance(r["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", r["image_id"]):
            raise Blocked("image_id must be the full sha256 image ID")
        _hex(r["container_id"], "container_id")
        instant(r["container_started_at"], "container_started_at")
        _bool(r["running"], "running")
        return "PASS", [], {key: r[key] for key in ENGINE_KEYS}
    if operation == "launch-cases":
        raise Blocked("launch-cases verdicts belong to QA's runner, not this client")
    if operation == "crash":
        facts = {**_crash_facts(ev, r, row), "decision": r["decision"]}
        status, reasons = verdict("crash", facts)
        return status, reasons, facts
    if operation == "start":
        if r["exit_code"] is not None:
            raise Blocked("a start's exit_code must be null")
        prior = _prior_crash(ev, r, row, prior_crash_sha256)
        facts = _start_facts(ev, r, request, prior, begin, end, standalone=True)
        status, reasons = verdict("start", facts)
        return (*_agree(status, reasons, r["decision"], r["failure_kind"], "start"), facts)
    # restart: stop-graceful leg, then start leg (CORRECTION-1 3.2)
    legs = r["legs"]
    if not isinstance(legs, list) or [_obj(g, "leg", LEG_KEYS)["leg"] for g in legs] != ["stop-graceful", "start"]:
        raise Blocked("restart legs must be exactly [stop-graceful, start] (a stop-only restart is a host failure)")
    stop_leg, start_leg = legs
    previous = begin
    for g in legs:
        g_begin, g_end = instant(g["started_at"], "leg.started_at"), instant(g["ended_at"], "leg.ended_at")
        if not previous <= g_begin <= g_end <= end:
            raise Blocked("restart legs are not in order inside the restart")
        previous = g_end
        if g["decision"] not in ("DONE", "FAILED") or (g["decision"] == "FAILED") == (g["failure_kind"] is None) \
                or g["failure_kind"] == "host":
            raise Blocked(f"{g['leg']} leg: {g['decision']} {g['failure_kind']} (host failure or inconsistent)")
    if r["exit_code"] != stop_leg["exit_code"] or start_leg["exit_code"] is not None:
        raise Blocked("restart exit_code must equal the stop leg's; the start leg's must be null")
    stop_e = _obj(stop_leg["evidence"], "stop-graceful.evidence", set(STOP_EVIDENCE))
    start_e = _obj(start_leg["evidence"], "start.evidence", set(START_EVIDENCE))
    stop = _stop_facts(ev, stop_e, row, stop_leg["exit_code"], instant(stop_leg["started_at"], "s"),
                       instant(stop_leg["ended_at"], "e"))
    stop["listener_gone"] = _bool(r["listener_gone"], "listener_gone")
    if start_e["prior_exit_evidence"] != {"kind": "restart-leg", "leg": "stop-graceful"}:
        raise Blocked("start leg prior_exit_evidence must name its own stop-graceful leg")
    start = _start_facts(ev, start_e, request, stop, instant(start_leg["started_at"], "s"),
                         instant(start_leg["ended_at"], "e"), standalone=False)
    legs_status = [_agree(*verdict(op, f), g["decision"], g["failure_kind"], g["leg"])
                   for op, f, g in (("stop", stop, stop_leg), ("start", start, start_leg))]
    if any(s == "BLOCKED" for s, _ in legs_status):
        return "BLOCKED", [m for _, rs in legs_status for m in rs], {"stop": stop, "start": start}
    status, reasons = verdict("restart", {"stop": stop, "start": start})
    return (*_agree(status, reasons, r["decision"], r["failure_kind"], "restart"), {"stop": stop, "start": start})


def _prior_crash(ev: Evidence, r: dict, row: str, prior_crash_sha256: str | None) -> dict:
    """Standalone start: load the exact earlier crash receipt it names and re-check it."""
    p = _obj(r["prior_exit_evidence"], "prior_exit_evidence",
             {"kind", "row", "writer", "request_id", "sequence", "sha256", "byte_length"})
    if p["kind"] != "receipt" or (p["row"], p["writer"]) != PRIOR_CRASH[row]:
        raise Blocked("prior_exit_evidence must name this writer's crash row")
    _uuid4(p["request_id"], "prior_exit_evidence.request_id")
    _int(p["sequence"], "prior_exit_evidence.sequence", 1, r["sequence"] - 1)
    _hex(p["sha256"], "prior_exit_evidence.sha256")
    if prior_crash_sha256 is not None and p["sha256"] != prior_crash_sha256:
        raise Blocked("prior_exit_evidence is not the crash receipt this client recorded")
    try:
        crash, _, _ = read_bound(ev.host_dir, f"{p['row']}.json", RECEIPT_MAX, uid=ev.uid, sha256=p["sha256"],
                                 byte_length=_int(p["byte_length"], "prior byte_length", 1, RECEIPT_MAX))
    except FileNotFoundError as exc:
        raise Blocked("the prior crash receipt is missing") from exc
    for key in ("window_id", "binding", "app_container_id", "fwd_container_id"):
        if crash.get(key) != r[key]:
            raise Blocked(f"prior crash receipt {key} differs")
    if (crash.get("schema"), crash.get("row"), crash.get("writer"), crash.get("operation"),
            crash.get("request_id"), crash.get("sequence")) != (RECEIPT_SCHEMA, p["row"], p["writer"], "crash",
                                                               p["request_id"], p["sequence"]):
        raise Blocked("prior crash receipt does not match prior_exit_evidence")
    if crash.get("decision") != "DONE" or REQUIRED_ROOT["crash"] - set(crash):
        raise Blocked("prior crash receipt is not a complete DONE crash")
    facts = {**_crash_facts(ev, crash, p["row"]), "decision": "DONE"}
    if verdict("crash", facts)[0] != "PASS" or instant(crash["ended_at"], "prior ended_at") > instant(r["started_at"], "s"):
        raise Blocked("prior crash was not a counted exit 137 before this start")
    return facts


def compare_engine(before: dict | None, after: dict | None, expected: str = ENGINE_PIN) -> dict:
    """W1: two judged engine-image readings against the full pin; any change is BLOCKED."""
    try:
        if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
            raise Blocked("the expected engine pin must be a full image ID, never a prefix")
        readings = []
        for label, reading in (("before", before), ("after", after)):
            if not isinstance(reading, dict) or reading.get("operation") != "engine-image":
                raise Blocked(f"{label}: missing engine reading")
            if reading.get("status") != "PASS":
                raise Blocked(f"{label}: engine reading not DONE: {'; '.join(reading.get('reasons', []))}")
            facts = reading["facts"]
            if facts["running"] is not True:
                raise Blocked(f"{label}: engine container is not running")
            if facts["image_id"] != expected:
                raise Blocked(f"{label}: new image: tell Security before use ({facts['image_id']}; pin {expected})")
            readings.append(facts)
        for key in ("image_id", "container_id", "container_started_at"):
            if readings[0][key] != readings[1][key]:
                raise Blocked(f"engine {key} changed between before and after")
    except Blocked as exc:
        return {"status": "BLOCKED", "reasons": [str(exc)], "expected": expected}
    return {"status": "PASS", "reasons": [], "expected": expected, "image_id": expected}


# ---------------------------------------------------------------- the client

class HostClient:
    """One writer in one build-bound window. Never guesses a sequence number."""

    def __init__(self, window_path: str | Path, window_sha256: str, *, writer: str = "checker",
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 sleep: Callable[[float], Awaitable] = asyncio.sleep, poll_seconds: float = 0.25,
                 uid: int | None = None):
        if writer not in ROWS:
            raise Blocked(f"unknown writer {writer!r}")
        self.uid, self.writer, self.clock, self.sleep, self.poll = uid, writer, clock, sleep, poll_seconds
        self.window = load_window(window_path, window_sha256, uid=uid)
        self.host_dir = Path(self.window["host_dir"])
        self.expected_sequence: int | None = None
        self.crash_sha256: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> Decimal:
        return instant(_iso(self.clock()), "now")

    def _read(self, leaf: str, cap: int = RECEIPT_MAX):
        try:
            return read_bound(self.host_dir, leaf, cap, uid=self.uid)
        except FileNotFoundError:
            return None

    async def _wait(self, request: dict, request_raw: bytes, ignore: bytes | None) -> dict:
        """Poll <row>.json until expires_at; ignore only the unchanged earlier receipt's bytes."""
        end = min(instant(request["expires_at"], "e"), instant(self.window["window_expires_at"], "w"))
        leaf = f"{request['row']}.json"
        while True:
            try:
                found = self._read(leaf)
            except Blocked as exc:
                return {"status": "BLOCKED", "reasons": [str(exc)], "row": request["row"], "sequence_valid": False}
            if found is not None and hashlib.sha256(found[1]).digest() != ignore:
                prior = PRIOR_CRASH.get(request["row"])
                result = judge_receipt(self.window, request, found[0], request_raw, uid=self.uid,
                                       seen=self.clock(), prior_crash_sha256=self.crash_sha256.get(prior[0]) if prior else None)
                result["receipt_sha256"] = hashlib.sha256(found[1]).hexdigest()
                return result
            remaining = end - self._now()
            if remaining <= 0:
                return {"status": "BLOCKED", "reasons": ["missing receipt by expires_at"], "row": request["row"],
                        "sequence_valid": False}
            await self.sleep(float(min(Decimal(str(self.poll)), remaining)))

    async def initialize(self) -> int:
        """Drain this writer's pending WAITING files (to their own deadlines), then read SEQ."""
        async with self._lock:
            return await self._initialize()

    async def _initialize(self) -> int:
        if self._now() >= instant(self.window["window_expires_at"], "w"):
            raise Blocked("window_expires_at has passed")
        for row in ROWS[self.writer]:
            pending = self._read(f"WAITING-{row}.json", REQUEST_MAX)
            if pending is None:
                continue
            request, raw, _ = pending
            validate_request(request, self.window)
            if request["writer"] != self.writer or request["row"] != row:
                raise Blocked(f"WAITING-{row}.json is not this writer's")
            receipt = self._read(f"{row}.json")
            ignore = None
            if receipt is not None and receipt[0].get("request_id") != request["request_id"]:
                ignore = hashlib.sha256(receipt[1]).digest()  # an older receipt: wait for the pending one
            result = await self._wait(request, raw, ignore)
            if result["sequence_valid"] is not True and result["reasons"] != ["missing receipt by expires_at"]:
                raise Blocked(f"pending {row}: {'; '.join(result['reasons'])}")
        self.expected_sequence = read_sequence(self.window, self.writer, uid=self.uid)
        return self.expected_sequence

    async def execute(self, row: str, *, expires_at: str, action: str, expected: str,
                      not_before: str | None = None) -> dict:
        """Publish one request for a fixed row and return its PASS/FAIL/BLOCKED result."""
        async with self._lock:
            try:
                _operation(self.writer, row)
                if self.expected_sequence is None:
                    await self._initialize()
                request = make_request(self.window, row, self.expected_sequence, writer=self.writer,
                                       expires_at=expires_at, action=action, expected=expected, now=self.clock(),
                                       not_before=not_before)
                ignore = self._prior(request)
                raw = write_request(self.window, request, clock=self.clock)
            except Blocked as exc:
                self.expected_sequence = None
                return {"status": "BLOCKED", "reasons": [str(exc)], "row": row, "sequence_valid": False}
            result = await self._wait(request, raw, ignore)
            self.expected_sequence = result.get("expected_sequence") if result.get("sequence_valid") else None
            if request["operation"] == "crash" and result["status"] == "PASS":
                self.crash_sha256[row] = result["receipt_sha256"]
            return result

    def _prior(self, request: dict) -> bytes | None:
        """An earlier receipt at the row path must be this window's, writer's and older; else BLOCKED."""
        found = self._read(f"{request['row']}.json")
        if found is None:
            return None
        old, raw, _ = found
        for key in ("schema", "window_id", "binding", "row", "writer", "operation"):
            if old.get(key) != (RECEIPT_SCHEMA if key == "schema" else request[key]):
                raise Blocked(f"existing {request['row']}.json is not an earlier receipt of this row ({key})")
        # A request refused at identity/sequence keeps its number, so its receipt may carry this sequence.
        unadmitted = old.get("sequence_used") is False and old.get("decision") == "REFUSED"
        if type(old.get("sequence")) is not int or old.get("request_id") == request["request_id"] \
                or old["sequence"] > request["sequence"] or (old["sequence"] == request["sequence"] and not unadmitted):
            raise Blocked(f"existing {request['row']}.json is not older than this request")
        return hashlib.sha256(raw).digest()
