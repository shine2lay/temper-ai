"""F3 cases for configs/architecture/bin/ops_host_inspect.py (Architecture #218).

Each F3 row (CASE-REQUIREMENTS.md in the r3 packet, SHA256SUMS caa69089...) has
its own negative and clean tests, named test_f3_<row>_n_* and test_f3_<row>_c_*.
Clean /2 data here is synthetic future-contract data: the actual producer emits
/1, so nothing here is evidence that anything emits /2.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
MODULE_PATH = BIN / "ops_host_inspect.py"
SPEC = importlib.util.spec_from_file_location("ops_host_inspect", MODULE_PATH)
inspect2 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inspect2
SPEC.loader.exec_module(inspect2)

SI = "TARGET_SCHEMA_MISMATCH"
EI = "TARGET_EVIDENCE_INVALID"
ELEVEN = (
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
RUNTIME23 = (
    "image_id", "command", "workdir", "env", "user", "mounts", "tmpfs",
    "read_only_root", "cap_drop", "cap_add", "security_options", "privileged",
    "devices", "pid_mode", "ipc_mode", "uts_mode", "init", "limits",
    "restart_policy", "ports", "networks", "data_bind", "image_env",
)  # fmt: skip
STATE7 = (
    "running", "status", "started_at", "finished_at", "exit_code", "oom_killed",
    "restart_count",
)  # fmt: skip
OUTER6 = ("schema", "window_id", "container_id", "runtime", "state", "observed_at")

WINDOW = "win-p3-0001"
APP_ID = hashlib.sha256(b"p3-app").hexdigest()
FWD_ID = hashlib.sha256(b"p3-forwarder").hexdigest()
NET_A = hashlib.sha256(b"p3-net-a").hexdigest()
NET_B = hashlib.sha256(b"p3-net-b").hexdigest()
IMAGE = "sha256:" + hashlib.sha256(b"p3-image").hexdigest()
CANARY = "P3CANARY9f1c"  # an Env value; never in a refusal or a repr
ZERO = "0001-01-01T00:00:00Z"

MOUNT_A = {"type": "bind", "source": "/srv/p3/a", "destination": "/a", "rw": True, "propagation": "rprivate"}
MOUNT_B = {"type": "volume", "source": "", "destination": "/b", "rw": False, "propagation": ""}
DEVICE_A = {"path_on_host": "/dev/fuse", "path_in_container": "/dev/fuse", "cgroup_permissions": "rwm"}
DEVICE_B = {"path_on_host": "/dev/null", "path_in_container": "/dev/null", "cgroup_permissions": "r"}
PORT_A = {"host_ip": "100.110.162.4", "host_port": 8970, "container_port": 8000, "protocol": "tcp"}
PORT_B = {"host_ip": "100.110.162.4", "host_port": 8970, "container_port": 8000, "protocol": "udp"}
NET_X = {"network_id": NET_A, "network_name": "p3-window", "aliases": ["app", "scanapp"]}
NET_Y = {"network_id": NET_B, "network_name": "bridge", "aliases": []}
BIND = {"source": "/srv/p3/data", "destination": "/data", "rw": True}


def canonical(member: object) -> bytes:
    return json.dumps(member, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canon_sorted(members: list) -> list:
    return sorted(members, key=canonical)


def drop(member: dict, key: str) -> dict:
    return {k: v for k, v in member.items() if k != key}


def app_doc() -> dict:
    """Synthetic future-contract /2 data for a running app (fresh each call)."""
    return {
        "schema": "ops-host-inspect/2",
        "window_id": WINDOW,
        "container_id": APP_ID,
        "runtime": {
            "image_id": IMAGE,
            "command": ["python", "-m", "scanapp", "--port", "8000"],
            "workdir": "/srv/app",
            "env": [
                "PATH=/usr/local/bin:/usr/bin",
                "LANG=C.UTF-8",
                f"SECRET_TOKEN={CANARY}",
                "HOST=0.0.0.0",
                "PORT=8000",
                "DATA_DIR=/data",
                "ALLOWED_HOSTS=100.110.162.4:8970,scanapp:8080",
            ],
            "user": "1000:1000",
            "mounts": [dict(MOUNT_A)],
            "tmpfs": {"/tmp": "rw,size=64m"},
            "read_only_root": True,
            "cap_drop": ["ALL"],
            "cap_add": [],
            "security_options": ["no-new-privileges:true"],
            "privileged": False,
            "devices": [],
            "pid_mode": "",
            "ipc_mode": "private",
            "uts_mode": "",
            "init": True,
            "limits": {"pids": 256, "memory_bytes": 536870912, "nano_cpus": 1000000000},
            "restart_policy": {"name": "no", "maximum_retry_count": 0},
            "ports": [dict(PORT_A)],
            "networks": [json.loads(json.dumps(NET_X))],
            "data_bind": dict(BIND),
            "image_env": ["PATH=/usr/local/bin:/usr/bin", "LANG=C.UTF-8", f"SECRET_TOKEN={CANARY}"],
        },
        "state": {
            "running": True,
            "status": "running",
            "started_at": "2026-10-23T18:00:00.123456789Z",
            "finished_at": ZERO,
            "exit_code": 0,
            "oom_killed": False,
            "restart_count": 0,
        },
        "observed_at": "2026-10-23T18:00:05.250Z",
    }


def forwarder_doc() -> dict:
    doc = app_doc()
    doc["container_id"] = FWD_ID
    runtime = doc["runtime"]
    runtime["command"] = ["socat", "TCP-LISTEN:8080,fork", "TCP:app:8000"]
    runtime["env"] = ["PATH=/usr/bin"]
    runtime["image_env"] = ["PATH=/usr/bin"]
    runtime["mounts"] = []
    runtime["ports"] = []
    runtime["networks"] = [{"network_id": NET_A, "network_name": "p3-window", "aliases": ["forwarder"]}]
    runtime["data_bind"] = None
    return doc


def stopped_doc() -> dict:
    doc = app_doc()
    doc["state"].update(
        running=False,
        status="exited",
        started_at="2026-10-23T18:00:00.1Z",
        finished_at="2026-10-23T18:00:03Z",
        exit_code=0,
    )
    return doc


def created_doc() -> dict:
    doc = app_doc()
    doc["state"].update(running=False, status="created", started_at=ZERO, finished_at=ZERO)
    return doc


def with_runtime(key: str, value: object, base=app_doc) -> dict:
    doc = base()
    doc["runtime"][key] = value
    return doc


def with_state(key: str, value: object, base=app_doc) -> dict:
    doc = base()
    doc["state"][key] = value
    return doc


def encode(doc: dict) -> bytes:
    return json.dumps(doc).encode("utf-8")  # ASCII escapes, so lone surrogates survive


_AUTO = object()


def parse(doc, *, target="app", window_id=WINDOW, container_id=_AUTO):
    raw = doc if isinstance(doc, bytes) else encode(doc)
    if container_id is _AUTO:
        container_id = FWD_ID if target == "forwarder" else APP_ID
    return inspect2.parse_inspect2(raw, window_id=window_id, container_id=container_id, target=target)


def refused(doc, code: str = EI, **kwargs) -> None:
    with pytest.raises(inspect2.TargetRefused) as info:
        parse(doc, **kwargs)
    assert_exact_refusal(info.value, code)


def assert_exact_refusal(exc: BaseException, code: str) -> None:
    assert type(exc) is inspect2.TargetRefused
    assert exc.code == code
    assert exc.args == (code,)
    assert str(exc) == code
    assert repr(exc) == f"TargetRefused('{code}')"
    assert exc.__cause__ is None and exc.__context__ is None


def accepted(doc, **kwargs):
    result = parse(doc, **kwargs)
    assert type(result) is inspect2.Inspect2Data
    assert result.trust == "UNTRUSTED"
    return result


def thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def disable(monkeypatch, name: str) -> None:
    monkeypatch.setattr(inspect2, name, lambda *args: None)


def v1_23_doc() -> dict:
    """The disclosed /1 shape with the 23 runtime members (what the producer emits)."""
    doc = app_doc()
    doc["schema"] = "ops-host-inspect/1"
    return doc


def v1_22_doc() -> dict:
    """Historical /1 with CLOSED22: env as an object, no image_env."""
    doc = v1_23_doc()
    del doc["runtime"]["image_env"]
    doc["runtime"]["env"] = {"PATH": "/usr/bin", "SECRET_TOKEN": CANARY}
    return doc


def v2_22_doc() -> dict:
    doc = app_doc()
    del doc["runtime"]["image_env"]
    return doc


# ─── F3-VERSION-1 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("target", ["app", "forwarder"])
def test_f3_version_1_n_disclosed_v1_23_refused_schema_mismatch(target):
    doc = v1_23_doc() if target == "app" else forwarder_doc() | {"schema": "ops-host-inspect/1"}
    refused(doc, SI, target=target)


def test_f3_version_1_n_historical_v1_22_refused_schema_mismatch():
    refused(v1_22_doc(), SI)


def test_f3_version_1_c_synthetic_v2_23_accepted_untrusted_not_retagged():
    result = accepted(app_doc())
    assert result.snapshot["schema"] == "ops-host-inspect/2"
    assert tuple(result.snapshot["runtime"]) == RUNTIME23
    assert thaw(result.snapshot) == app_doc()


# ─── F3-VERSION-22 ──────────────────────────────────────────────────────────


def test_f3_version_22_n_v2_without_image_env_refused():
    refused(v2_22_doc(), EI)


def test_f3_version_22_n_v2_with_old_env_object_and_22_members_refused():
    doc = v2_22_doc()
    doc["runtime"]["env"] = {"PATH": "/usr/bin"}
    refused(doc, EI)


def test_f3_version_22_n_v2_with_24_members_refused():
    doc = app_doc()
    doc["runtime"]["image_env_extra"] = []
    refused(doc, EI)


def test_f3_version_22_c_exact_v2_23_accepted():
    result = accepted(app_doc())
    assert set(result.snapshot["runtime"]) == set(RUNTIME23)
    assert len(RUNTIME23) == 23 and len(set(RUNTIME23)) == 23


# ─── F3-VERSION-UNKNOWN ─────────────────────────────────────────────────────

UNKNOWN_SCHEMAS = [
    "ops-host-inspect/3",
    "ops-host-inspect/2 ",
    " ops-host-inspect/2",
    "OPS-HOST-INSPECT/2",
    "ops-host-inspect/02",
    "ops-host-inspect/2.0",
    "ops-host-inspect",
    "ops-host-inspect/2\u0000",
    "",
]


@pytest.mark.parametrize("schema", UNKNOWN_SCHEMAS)
def test_f3_version_unknown_n_typed_unknown_schema_refused_schema_mismatch(schema):
    doc = app_doc()
    doc["schema"] = schema
    refused(doc, SI)


def test_f3_version_unknown_n_unknown_schema_wins_over_other_member_faults():
    doc = app_doc()
    doc["schema"] = "ops-host-inspect/3"
    doc["runtime"] = {}
    doc["window_id"] = "win-other"
    refused(doc, SI)


@pytest.mark.parametrize("schema", [2, None, ["ops-host-inspect/2"], True])
def test_f3_version_unknown_n_untyped_schema_is_evidence_invalid_not_schema(schema):
    doc = app_doc()
    doc["schema"] = schema
    refused(doc, EI)


def test_f3_version_unknown_c_exact_v2_literal_accepted():
    assert inspect2.SCHEMA == "ops-host-inspect/2"
    accepted(app_doc())


# ─── F3-ENVELOPE ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", OUTER6)
def test_f3_envelope_n_each_missing_outer_field_refused(key):
    doc = app_doc()
    del doc[key]
    refused(doc, EI)


def test_f3_envelope_n_unknown_outer_field_refused():
    doc = app_doc()
    doc["image_baseline"] = []
    refused(doc, EI)


def test_f3_envelope_n_duplicate_outer_field_refused():
    text = json.dumps(app_doc()).replace('"window_id": ', '"window_id": "win-other", "window_id": ', 1)
    refused(text.encode("utf-8"), EI)


def test_f3_envelope_n_wrong_window_refused():
    refused(app_doc(), EI, window_id="win-p3-0002")


def test_f3_envelope_n_wrong_full_container_refused():
    refused(app_doc(), EI, container_id=FWD_ID)


@pytest.mark.parametrize("value", [APP_ID[:63], APP_ID.upper(), APP_ID[:12], "", None, 1])
def test_f3_envelope_n_snapshot_container_not_full_lowercase_hex_refused(value):
    doc = app_doc()
    doc["container_id"] = value
    refused(doc, EI)


@pytest.mark.parametrize("value", ["", None, 7, "win\u0000"])
def test_f3_envelope_n_snapshot_window_not_text_refused(value):
    doc = app_doc()
    doc["window_id"] = value
    refused(doc, EI)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"container_id": APP_ID[:12]},
        {"container_id": APP_ID.upper()},
        {"container_id": None},
        {"window_id": ""},
        {"window_id": None},
        {"window_id": b"win-p3-0001"},
    ],
    ids=["short_container", "upper_container", "null_container", "empty_window", "null_window", "bytes_window"],
)
def test_f3_envelope_n_bad_expected_arguments_refused(kwargs):
    refused(app_doc(), EI, **kwargs)


def test_f3_envelope_c_exact_six_fields_and_expected_ids_accepted():
    result = accepted(app_doc())
    assert set(result.snapshot) == set(OUTER6)
    assert result.snapshot["window_id"] == WINDOW
    assert result.snapshot["container_id"] == APP_ID


def test_f3_envelope_c_object_key_order_is_not_identity():
    doc = app_doc()
    reordered = {key: doc[key] for key in reversed(OUTER6)}
    reordered["runtime"] = {key: doc["runtime"][key] for key in reversed(RUNTIME23)}
    accepted(reordered)


def test_f3_envelope_c_exact_size_limit_accepted_one_more_refused():
    raw = encode(app_doc())
    accepted(raw + b" " * (16384 - len(raw)))
    refused(raw + b" " * (16385 - len(raw)), EI)


# ─── F3-TARGET ──────────────────────────────────────────────────────────────


class _StrTarget(str):
    pass


@pytest.mark.parametrize(
    "target",
    [None, "", "APP", "application", "app ", b"app", 1, _StrTarget("app")],
    ids=["absent_none", "empty", "upper", "other_word", "trailing_space", "bytes", "int", "str_subclass"],
)
def test_f3_target_n_absent_or_invalid_refused(target):
    refused(app_doc(), EI, target=target, container_id=APP_ID)


def test_f3_target_n_no_default_target():
    with pytest.raises(TypeError):
        inspect2.parse_inspect2(encode(app_doc()), window_id=WINDOW, container_id=APP_ID)


def test_f3_target_c_explicit_app_and_forwarder_accepted():
    accepted(app_doc(), target="app")
    accepted(forwarder_doc(), target="forwarder")


# ─── F3-APP-BIND ────────────────────────────────────────────────────────────


def test_f3_app_bind_n_app_null_bind_refused():
    refused(with_runtime("data_bind", None), EI, target="app")


@pytest.mark.parametrize("source", ["srv/p3/data", "/srv/p3/data/", "/srv/../data", ""])
def test_f3_app_bind_n_app_bind_not_absolute_canonical_refused(source):
    refused(with_runtime("data_bind", {**BIND, "source": source}), EI, target="app")


def test_f3_app_bind_c_absolute_structural_app_bind_accepted():
    result = accepted(app_doc(), target="app")
    assert thaw(result.snapshot["runtime"]["data_bind"]) == BIND


# ─── F3-FORWARDER-NULL ──────────────────────────────────────────────────────


def _strict_null_mutant(target, data_bind):
    if data_bind is None:
        raise inspect2.TargetRefused(EI)


def test_f3_forwarder_null_n_mutant_refusing_allowed_null_is_caught(monkeypatch):
    accepted(forwarder_doc(), target="forwarder")
    monkeypatch.setattr(inspect2, "_guard_target_bind", _strict_null_mutant)
    refused(forwarder_doc(), EI, target="forwarder")  # the clean twin exposes the mutant


def test_f3_forwarder_null_n_present_forwarder_bind_still_structural():
    refused(with_runtime("data_bind", {**BIND, "source": "relative"}, base=forwarder_doc), EI, target="forwarder")


def test_f3_forwarder_null_c_null_and_present_valid_bind_accepted_no_authority():
    null_result = accepted(forwarder_doc(), target="forwarder")
    present = accepted(with_runtime("data_bind", dict(BIND), base=forwarder_doc), target="forwarder")
    assert null_result.snapshot["runtime"]["data_bind"] is None
    assert thaw(present.snapshot["runtime"]["data_bind"]) == BIND
    for result in (null_result, present):
        assert {f.name for f in dataclasses.fields(result)} == {"trust", "snapshot"}
        assert result.trust == "UNTRUSTED"


# ─── F3-TIME-STRUCT ─────────────────────────────────────────────────────────

BAD_TIMESTAMPS = [
    ("no_offset", "2026-10-23T18:00:00.000"),
    ("unknown_offset", "2026-10-23T18:00:00.000-00:00"),
    ("offset_hour_24", "2026-10-23T18:00:00.000+24:00"),
    ("offset_minute_60", "2026-10-23T18:00:00.000+05:60"),
    ("offset_no_colon", "2026-10-23T18:00:00.000+0530"),
    ("lower_z", "2026-10-23T18:00:00.000z"),
    ("lower_t", "2026-10-23t18:00:00.000Z"),
    ("space_separator", "2026-10-23 18:00:00.000Z"),
    ("feb_30", "2026-02-30T18:00:00.000Z"),
    ("feb_29_not_leap", "2027-02-29T18:00:00.000Z"),
    ("month_13", "2026-13-01T18:00:00.000Z"),
    ("hour_24", "2026-10-23T24:00:00.000Z"),
    ("second_60", "2026-10-23T18:00:60.000Z"),
    ("year_0", "0000-10-23T18:00:00.000Z"),
    ("non_ascii_digits", "\u0662\u0660\u0662\u0666-10-23T18:00:00.000Z"),
    ("ten_fraction_digits", "2026-10-23T18:00:00.0000000000Z"),
    ("empty_fraction", "2026-10-23T18:00:00.Z"),
    ("date_only", "2026-10-23"),
    ("empty", ""),
    ("int", 1761242400),
    ("null", None),
]


@pytest.mark.parametrize("field_name", ["started_at", "finished_at"])
@pytest.mark.parametrize("label,value", BAD_TIMESTAMPS, ids=[label for label, _ in BAD_TIMESTAMPS])
def test_f3_time_struct_n_bad_event_syntax_refused(field_name, label, value):
    refused(with_state(field_name, value, base=stopped_doc), EI)


@pytest.mark.parametrize(
    "label,value",
    [*BAD_TIMESTAMPS, ("no_fraction", "2026-10-23T18:00:05Z"), ("two_fraction_digits", "2026-10-23T18:00:05.25Z"),
     ("zero_sentinel", ZERO), ("zero_sentinel_millis", "0001-01-01T00:00:00.000Z")],
    ids=[label for label, _ in BAD_TIMESTAMPS] + ["no_fraction", "two_fraction_digits", "zero_sentinel", "zero_sentinel_millis"],
)  # fmt: skip
def test_f3_time_struct_n_bad_observed_at_refused(label, value):
    doc = app_doc()
    doc["observed_at"] = value
    refused(doc, EI)


@pytest.mark.parametrize(
    "base,changes",
    [
        (app_doc, {"started_at": "2026-10-23T18:00:06Z"}),
        (app_doc, {"started_at": "2026-10-23T18:00:05.250000001Z"}),
        (app_doc, {"started_at": "2026-10-23T11:00:06-07:00"}),
        (stopped_doc, {"finished_at": "2026-10-23T18:00:06Z"}),
        (stopped_doc, {"started_at": "2026-10-23T18:00:04Z", "finished_at": "2026-10-23T18:00:03Z"}),
        (stopped_doc, {"started_at": "2026-10-24T03:00:03.5+09:00", "finished_at": "2026-10-23T18:00:03Z"}),
    ],
    ids=[
        "start_after_observed",
        "start_one_nanosecond_after_observed",
        "start_after_observed_across_offsets",
        "finish_after_observed",
        "finish_before_start",
        "finish_before_start_across_offsets",
    ],
)
def test_f3_time_struct_n_actual_event_order_refused(base, changes):
    doc = base()
    doc["state"].update(changes)
    refused(doc, EI)


@pytest.mark.parametrize(
    "base,changes,observed_at",
    [
        (stopped_doc, {}, None),
        (app_doc, {"started_at": "2026-10-23T18:00:05.25Z"}, None),
        (stopped_doc, {"started_at": "2026-10-23T18:00:03Z", "finished_at": "2026-10-23T18:00:03Z"}, None),
        (app_doc, {"started_at": "2026-10-23T11:00:00-07:00"}, "2026-10-24T03:00:05.250+09:00"),
        (app_doc, {"started_at": "2028-02-29T00:00:00Z"}, "2028-02-29T00:00:01.000000001Z"),
        (app_doc, {"started_at": "2026-10-23T18:00:00Z"}, "2026-10-23T18:00:05.250+00:00"),
    ],
    ids=["stopped", "start_equals_observed", "finish_equals_start", "offsets", "leap_day_nanos", "plus_zero_offset"],
)
def test_f3_time_struct_c_valid_structural_times_accepted(base, changes, observed_at):
    doc = base()
    doc["state"].update(changes)
    if observed_at is not None:
        doc["observed_at"] = observed_at
    accepted(doc)


# ─── F3-TIME-SENTINEL ───────────────────────────────────────────────────────


def test_f3_time_sentinel_n_mutant_reading_sentinel_as_event_is_caught(monkeypatch):
    accepted(app_doc())
    monkeypatch.setattr(inspect2, "_is_zero_sentinel", lambda value: False)
    refused(app_doc(), EI)  # running app: finished_at sentinel would precede started_at


def test_f3_time_sentinel_n_mutant_refusing_sentinel_is_caught(monkeypatch):
    accepted(created_doc())

    def events_only(value):
        return inspect2._instant(value) is not None and not inspect2._is_zero_sentinel(value)

    monkeypatch.setitem(inspect2.STATE_RULES, "started_at", events_only)
    monkeypatch.setitem(inspect2.STATE_RULES, "finished_at", events_only)
    refused(created_doc(), EI)


@pytest.mark.parametrize("key", ["workdir", "user", "pid_mode", "ipc_mode", "uts_mode"])
def test_f3_time_sentinel_n_mutant_refusing_source_empty_string_is_caught(monkeypatch, key):
    doc = with_runtime(key, "")
    accepted(doc)
    monkeypatch.setitem(inspect2.RUNTIME_RULES, key, inspect2._is_text)
    refused(with_runtime(key, ""), EI)


@pytest.mark.parametrize("key", ["type", "source", "destination", "propagation"])
def test_f3_time_sentinel_n_mutant_refusing_empty_mount_text_is_caught(monkeypatch, key):
    doc = with_runtime("mounts", [{**MOUNT_A, key: ""}])
    accepted(doc)
    monkeypatch.setitem(inspect2._MOUNT, key, inspect2._is_text)
    refused(with_runtime("mounts", [{**MOUNT_A, key: ""}]), EI)


def test_f3_time_sentinel_c_never_started_both_sentinels_accepted():
    result = accepted(created_doc())
    assert result.snapshot["state"]["started_at"] == ZERO
    assert result.snapshot["state"]["finished_at"] == ZERO


def test_f3_time_sentinel_c_running_finished_sentinel_accepted():
    accepted(app_doc())


def test_f3_time_sentinel_c_other_spelling_of_zero_instant_accepted():
    accepted(with_state("finished_at", "0001-01-01T00:00:00.000+00:00"))


def test_f3_time_sentinel_c_disclosed_source_empty_allowances_accepted():
    doc = app_doc()
    runtime = doc["runtime"]
    runtime.update(workdir="", user="", pid_mode="", ipc_mode="", uts_mode="")
    runtime["mounts"] = [{"type": "", "source": "", "destination": "", "rw": False, "propagation": ""}]
    runtime["tmpfs"] = {"/run": ""}
    runtime["env"] = ["EMPTY="]
    runtime["image_env"] = ["EMPTY="]
    result = accepted(doc)
    assert thaw(result.snapshot) == doc


# ─── F3-NONCHRONOLOGY ───────────────────────────────────────────────────────

ALLOWED_IMPORTS = {"__future__", "collections.abc", "dataclasses", "json", "re", "types", "typing"}
FORBIDDEN_NAMES = {
    "open", "print", "input", "exec", "eval", "__import__", "os", "sys", "time", "datetime",
    "subprocess", "socket", "pathlib", "shutil", "importlib", "asyncio", "threading", "random",
    "sleep", "now", "utcnow", "today", "monotonic", "perf_counter", "getenv", "environ",
    "hostproto", "hostops", "hostwin", "hostcases",
}  # fmt: skip
VERDICT_WORDS = ("ttl", "deadline", "verdict", "health", "expire", "timeout", "judge")


def purity_findings(source: str) -> list[str]:
    """Names and imports a pure /2 decoder must not have: clock, I/O, producer, verdicts."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS:
                found.append(f"from {node.module}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.ClassDef):
            if any(word in node.name.lower() for word in VERDICT_WORDS):
                found.append(node.name)
    return found


POLLUTED = {
    "clock_import": "\nimport time\n",
    "datetime_now": "\nfrom datetime import datetime\n_NOW = datetime.now\n",
    "ttl_check": "\ndef _ttl_expired(observed):\n    return False\n",
    "health_verdict": "\ndef _health_verdict(state):\n    return 'PASS'\n",
    "operation_judge": "\ndef _judge_restart(state):\n    return None\n",
    "file_read": "\ndef _peek(path):\n    return open(path).read()\n",
    "environment": "\nimport os\n_HOME = os.environ\n",
    "producer_import": "\nfrom hostproto import validate_inspect\n",
}


@pytest.mark.parametrize("label", sorted(POLLUTED))
def test_f3_nonchronology_n_purity_scan_fails_a_polluted_copy(label):
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert purity_findings(source + POLLUTED[label])


def test_f3_nonchronology_c_real_module_passes_purity_scan():
    assert purity_findings(MODULE_PATH.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "started_at,observed_at",
    [("2001-01-01T00:00:00Z", "2001-01-01T00:00:01.000Z"), ("2099-12-31T23:59:58Z", "2099-12-31T23:59:59.999Z")],
    ids=["long_ago", "far_future"],
)
def test_f3_nonchronology_c_old_or_future_observation_accepted(started_at, observed_at):
    doc = with_state("started_at", started_at)
    doc["observed_at"] = observed_at
    accepted(doc)


def test_f3_nonchronology_c_crash_data_accepted_without_verdict():
    doc = stopped_doc()
    doc["state"].update(status="exited", exit_code=137, oom_killed=False)
    result = accepted(doc)
    assert {f.name for f in dataclasses.fields(result)} == {"trust", "snapshot"}


# ─── F3-RUNTIME-MEMBERS ─────────────────────────────────────────────────────


def _text_set_negatives(low: str, high: str) -> list:
    return [
        ("unsorted", [high, low]),
        ("duplicate", [low, low]),
        ("empty_item", [""]),
        ("int_item", [1]),
        ("nul_item", ["a\u0000"]),
        ("string_not_array", low),
        ("null", None),
    ]


def _bool_negatives() -> list:
    return [("int_1", 1), ("int_0", 0), ("string", "true"), ("null", None)]


def _mode_negatives() -> list:
    return [("null", None), ("int", 0), ("nul", "host\u0000"), ("array", ["host"])]


def _reversed_pair(a: dict, b: dict) -> list:
    return list(reversed(canon_sorted([a, b])))


RUNTIME_NEGATIVES = {
    "image_id": [
        ("short_hex", "sha256:" + "a" * 63),
        ("upper_hex", "sha256:" + "A" * 64),
        ("no_algorithm", "a" * 64),
        ("sha512", "sha512:" + "a" * 64),
        ("upper_repository", "Registry/app@" + IMAGE),
        ("empty_repository", "@" + IMAGE),
        ("tag_not_digest", "registry/app:1.0"),
        ("too_long", "a" * 250 + "@" + IMAGE),
        ("empty", ""),
        ("int", 1),
        ("null", None),
    ],
    "command": [
        ("empty_argv", []),
        ("empty_item", ["python", ""]),
        ("int_item", ["python", 1]),
        ("nul_item", ["py\u0000thon"]),
        ("string_not_array", "python -m scanapp"),
        ("null", None),
    ],
    "workdir": [("null", None), ("int", 0), ("nul", "/srv\u0000"), ("array", ["/srv"])],
    "env": [
        ("object_old_form", {"PATH": "/usr/bin"}),
        ("no_equals", ["PATH"]),
        ("empty_key", ["=value"]),
        ("nul_in_value", ["A=b\u0000"]),
        ("lone_surrogate", ["A=\ud800"]),
        ("int_item", [1]),
        ("null", None),
    ],
    "user": [("null", None), ("int", 1000), ("nul", "app\u0000")],
    "mounts": [
        ("object_not_array", MOUNT_A),
        ("missing_propagation", [drop(MOUNT_A, "propagation")]),
        ("extra_key", [{**MOUNT_A, "mode": "z"}]),
        ("rw_string", [{**MOUNT_A, "rw": "true"}]),
        ("rw_int", [{**MOUNT_A, "rw": 1}]),
        ("type_null", [{**MOUNT_A, "type": None}]),
        ("source_nul", [{**MOUNT_A, "source": "/a\u0000"}]),
        ("unsorted", _reversed_pair(MOUNT_A, MOUNT_B)),
        ("duplicate", [MOUNT_A, MOUNT_A]),
    ],
    "tmpfs": [
        ("array", ["/tmp"]),
        ("empty_key", {"": "rw"}),
        ("int_value", {"/tmp": 1}),
        ("null_value", {"/tmp": None}),
        ("nul_key", {"/t\u0000": ""}),
        ("null", None),
    ],
    "read_only_root": _bool_negatives(),
    "cap_drop": _text_set_negatives("ALL", "NET_RAW"),
    "cap_add": _text_set_negatives("CHOWN", "NET_BIND_SERVICE"),
    "security_options": _text_set_negatives("apparmor=docker-default", "no-new-privileges:true"),
    "privileged": _bool_negatives(),
    "devices": [
        ("object_not_array", DEVICE_A),
        ("missing_permissions", [drop(DEVICE_A, "cgroup_permissions")]),
        ("extra_key", [{**DEVICE_A, "major": 10}]),
        ("empty_host_path", [{**DEVICE_A, "path_on_host": ""}]),
        ("empty_container_path", [{**DEVICE_A, "path_in_container": ""}]),
        ("empty_permissions", [{**DEVICE_A, "cgroup_permissions": ""}]),
        ("unsorted", _reversed_pair(DEVICE_A, DEVICE_B)),
        ("duplicate", [DEVICE_A, DEVICE_A]),
        ("int_member", [1]),
    ],
    "pid_mode": _mode_negatives(),
    "ipc_mode": _mode_negatives(),
    "uts_mode": _mode_negatives(),
    "init": _bool_negatives(),
    "limits": [
        ("missing_pids", {"memory_bytes": 0, "nano_cpus": 0}),
        ("extra_key", {"pids": 0, "memory_bytes": 0, "nano_cpus": 0, "cpu_shares": 0}),
        ("negative_pids", {"pids": -1, "memory_bytes": 0, "nano_cpus": 0}),
        ("bool_memory", {"pids": 0, "memory_bytes": True, "nano_cpus": 0}),
        ("float_nano_cpus", {"pids": 0, "memory_bytes": 0, "nano_cpus": 1.5}),
        ("exponent_nano_cpus", {"pids": 0, "memory_bytes": 0, "nano_cpus": 1e9}),
        ("string_pids", {"pids": "256", "memory_bytes": 0, "nano_cpus": 0}),
        ("array", [256, 0, 0]),
        ("null", None),
    ],
    "restart_policy": [
        ("empty_name", {"name": "", "maximum_retry_count": 0}),
        ("negative_count", {"name": "no", "maximum_retry_count": -1}),
        ("bool_count", {"name": "no", "maximum_retry_count": False}),
        ("missing_count", {"name": "no"}),
        ("extra_key", {"name": "no", "maximum_retry_count": 0, "delay": 1}),
        ("null", None),
    ],
    "ports": [
        ("host_port_0", [{**PORT_A, "host_port": 0}]),
        ("container_port_65536", [{**PORT_A, "container_port": 65536}]),
        ("protocol_sctp", [{**PORT_A, "protocol": "sctp"}]),
        ("protocol_upper", [{**PORT_A, "protocol": "TCP"}]),
        ("empty_host_ip", [{**PORT_A, "host_ip": ""}]),
        ("bool_port", [{**PORT_A, "host_port": True}]),
        ("string_port", [{**PORT_A, "host_port": "8970"}]),
        ("missing_protocol", [drop(PORT_A, "protocol")]),
        ("extra_key", [{**PORT_A, "host_port_end": 8979}]),
        ("unsorted", _reversed_pair(PORT_A, PORT_B)),
        ("duplicate", [PORT_A, PORT_A]),
        ("object_not_array", PORT_A),
    ],
    "networks": [
        ("short_id", [{**NET_X, "network_id": NET_A[:63]}]),
        ("upper_id", [{**NET_X, "network_id": NET_A.upper()}]),
        ("empty_name", [{**NET_X, "network_name": ""}]),
        ("unsorted_aliases", [{**NET_X, "aliases": ["scanapp", "app"]}]),
        ("duplicate_aliases", [{**NET_X, "aliases": ["app", "app"]}]),
        ("empty_alias", [{**NET_X, "aliases": [""]}]),
        ("missing_aliases", [drop(NET_X, "aliases")]),
        ("extra_key", [{**NET_X, "ip": "172.18.0.2"}]),
        ("unsorted", _reversed_pair(NET_X, NET_Y)),
        ("duplicate", [NET_X, NET_X]),
        ("object_not_array", NET_X),
    ],
    "data_bind": [
        ("relative_source", {**BIND, "source": "srv/p3/data"}),
        ("trailing_slash", {**BIND, "source": "/srv/p3/data/"}),
        ("dot_dot", {**BIND, "source": "/srv/../data"}),
        ("dot", {**BIND, "source": "/srv/./data"}),
        ("double_slash", {**BIND, "source": "/srv//data"}),
        ("empty_destination", {**BIND, "destination": ""}),
        ("relative_destination", {**BIND, "destination": "data"}),
        ("rw_string", {**BIND, "rw": "true"}),
        ("missing_rw", drop(BIND, "rw")),
        ("extra_key", {**BIND, "propagation": "rprivate"}),
        ("array", ["/srv/p3/data", "/data"]),
        ("string", "/srv/p3/data:/data"),
    ],
    "image_env": [
        ("duplicate_key", ["A=1", "A=2"]),
        ("duplicate_token", ["A=1", "A=1"]),
        ("no_equals", ["PATH"]),
        ("empty_key", ["=x"]),
        ("object_old_form", {"A": "1"}),
        ("int_item", [1]),
        ("null", None),
    ],
}

RUNTIME_CLEAN = {
    "image_id": [
        ("plain_digest", IMAGE),
        ("repository_prefixed", "registry.example:5000/team/scanapp@" + IMAGE),
        ("max_length", "a" * (255 - len(IMAGE) - 1) + "@" + IMAGE),
    ],
    "command": [
        ("one_item", ["/app/run"]),
        ("spaces_and_unicode", ["sh", "-c", "echo h\u00e9llo w\u00f6rld"]),
        ("order_kept", ["b", "a", "c"]),
    ],
    "workdir": [("empty", ""), ("path", "/srv/app")],
    "env": [
        ("empty_array", []),
        ("empty_value", ["A="]),
        ("extra_equals", ["OPTS=a=b=c"]),
        ("duplicate_kept", ["A=1", "B=2", "A=1"]),
        ("unicode", ["GREETING=h\u00e9llo"]),
    ],
    "user": [("empty", ""), ("name", "app"), ("uid_gid", "1000:1000")],
    "mounts": [
        ("empty_array", []),
        ("two_sorted_unique", canon_sorted([MOUNT_A, MOUNT_B])),
        ("source_empty_allowance", [MOUNT_B]),
    ],
    "tmpfs": [("empty_object", {}), ("empty_value", {"/run": ""}), ("two_keys", {"/run": "", "/tmp": "rw"})],
    "read_only_root": [("true", True), ("false", False)],
    "cap_drop": [("empty_array", []), ("sorted_unique", ["ALL", "NET_RAW"])],
    "cap_add": [("empty_array", []), ("sorted_unique", ["CHOWN", "NET_BIND_SERVICE"])],
    "security_options": [("empty_array", []), ("sorted_unique", ["apparmor=docker-default", "no-new-privileges:true"])],
    "privileged": [("true", True), ("false", False)],
    "devices": [("empty_array", []), ("two_sorted_unique", canon_sorted([DEVICE_A, DEVICE_B]))],
    "pid_mode": [("empty", ""), ("value", "host")],
    "ipc_mode": [("empty", ""), ("value", "private")],
    "uts_mode": [("empty", ""), ("value", "host")],
    "init": [("true", True), ("false", False)],
    "limits": [
        ("zeros", {"pids": 0, "memory_bytes": 0, "nano_cpus": 0}),
        ("large", {"pids": 4194304, "memory_bytes": 2**40, "nano_cpus": 64 * 10**9}),
    ],
    "restart_policy": [
        ("no", {"name": "no", "maximum_retry_count": 0}),
        ("on_failure", {"name": "on-failure", "maximum_retry_count": 5}),
    ],
    "ports": [
        ("empty_array", []),
        ("bounds_1_and_65535", [{**PORT_A, "host_port": 1, "container_port": 65535}]),
        ("two_sorted_unique", canon_sorted([PORT_A, PORT_B])),
    ],
    "networks": [
        ("empty_array", []),
        ("empty_aliases", [NET_Y]),
        ("two_sorted_unique", canon_sorted([NET_X, NET_Y])),
    ],
    "data_bind": [("app_bind", dict(BIND)), ("root_paths", {"source": "/", "destination": "/", "rw": False})],
    "image_env": [
        ("empty_array", []),
        ("ordered_unique", ["Z=1", "A=2"]),
        ("empty_value_extra_equals", ["A=", "B=x=y"]),
    ],
}


def _cases(table: dict) -> list:
    return [pytest.param(key, value, id=f"{key}-{label}") for key, rows in table.items() for label, value in rows]


@pytest.mark.parametrize("key,value", _cases(RUNTIME_NEGATIVES))
def test_f3_runtime_members_n_each_mutation_refused(key, value):
    refused(with_runtime(key, value), EI)


@pytest.mark.parametrize("key", RUNTIME23)
def test_f3_runtime_members_n_each_member_missing_refused(key):
    doc = app_doc()
    del doc["runtime"][key]
    refused(doc, EI)


def test_f3_runtime_members_n_runtime_not_object_refused():
    for value in ([], None, "runtime"):
        doc = app_doc()
        doc["runtime"] = value
        refused(doc, EI)


def test_f3_runtime_members_n_duplicate_nested_name_refused():
    text = json.dumps(app_doc()).replace('"pids": ', '"pids": 1, "pids": ', 1)
    refused(text.encode("utf-8"), EI)


def test_f3_runtime_members_n_duplicate_tmpfs_name_refused():
    text = json.dumps(app_doc()).replace('"/tmp": ', '"/tmp": "", "/tmp": ', 1)
    refused(text.encode("utf-8"), EI)


@pytest.mark.parametrize("key,value", _cases(RUNTIME_CLEAN))
def test_f3_runtime_members_c_each_allowance_accepted(key, value):
    result = accepted(with_runtime(key, value))
    assert thaw(result.snapshot["runtime"][key]) == value


def test_f3_runtime_members_c_tables_cover_all_23():
    assert tuple(RUNTIME_NEGATIVES) == RUNTIME23 == tuple(RUNTIME_CLEAN)
    assert tuple(inspect2.RUNTIME_RULES) == RUNTIME23
    assert all(RUNTIME_NEGATIVES[key] and RUNTIME_CLEAN[key] for key in RUNTIME23)


def test_f3_runtime_members_c_real_utf8_bytes_accepted():
    doc = with_runtime("command", ["echo", "h\u00e9llo \U0001f600"])
    accepted(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


# ─── F3-STATE-MEMBERS ───────────────────────────────────────────────────────

STATE_NEGATIVES = {
    "running": [("int", 1), ("string", "true"), ("null", None)],
    "status": [("empty", ""), ("null", None), ("int", 0), ("nul", "run\u0000")],
    "started_at": [("no_offset", "2026-10-23T18:00:00"), ("space", "2026-10-23 18:00:00Z"), ("null", None)],
    "finished_at": [("no_offset", "2026-10-23T18:00:03"), ("bad_date", "2026-02-30T00:00:00Z"), ("int", 0)],
    "exit_code": [("negative", -1), ("bool", False), ("string", "0"), ("float", 0.5), ("null", None)],
    "oom_killed": [("int", 0), ("string", "false"), ("null", None)],
    "restart_count": [("negative", -1), ("bool", True), ("string", "0"), ("null", None)],
}

STATE_CLEAN = {
    "running": [("true", True), ("false", False)],
    "status": [("exited", "exited"), ("created", "created"), ("restarting", "restarting")],
    "started_at": [("sentinel", ZERO), ("nanos", "2026-10-23T18:00:00.123456789Z"), ("offset", "2026-10-23T11:00:00-07:00")],
    "finished_at": [("sentinel", ZERO), ("millis", "2026-10-23T18:00:03.500Z"), ("offset", "2026-10-24T03:00:03+09:00")],
    "exit_code": [("zero", 0), ("crash_137", 137), ("max_byte", 255)],
    "oom_killed": [("false", False), ("true", True)],
    "restart_count": [("zero", 0), ("five", 5)],
}  # fmt: skip


@pytest.mark.parametrize("key,value", _cases(STATE_NEGATIVES))
def test_f3_state_members_n_each_field_mutation_refused(key, value):
    refused(with_state(key, value, base=stopped_doc), EI)


@pytest.mark.parametrize("key", STATE7)
def test_f3_state_members_n_each_field_missing_refused(key):
    doc = stopped_doc()
    del doc["state"][key]
    refused(doc, EI)


def test_f3_state_members_n_extra_or_non_object_state_refused():
    doc = stopped_doc()
    doc["state"]["pid"] = 1
    refused(doc, EI)
    for value in ([], None):
        doc = stopped_doc()
        doc["state"] = value
        refused(doc, EI)


@pytest.mark.parametrize("key,value", _cases(STATE_CLEAN))
def test_f3_state_members_c_each_field_accepted(key, value):
    result = accepted(with_state(key, value, base=stopped_doc))
    assert result.snapshot["state"][key] == value


def test_f3_state_members_c_tables_cover_all_7():
    assert tuple(STATE_NEGATIVES) == STATE7 == tuple(STATE_CLEAN) == tuple(inspect2.STATE_RULES)


@pytest.mark.parametrize("exit_code,oom_killed", [(137, False), (0, True), (137, True)])
def test_f3_state_members_c_oom_is_the_literal_observation(exit_code, oom_killed):
    doc = stopped_doc()
    doc["state"].update(exit_code=exit_code, oom_killed=oom_killed)
    result = accepted(doc)
    assert result.snapshot["state"]["oom_killed"] is oom_killed
    assert result.snapshot["state"]["exit_code"] == exit_code


# ─── F3-ENV-DUPLICATE ───────────────────────────────────────────────────────

DUPLICATE_ENV = ["A=1", "PATH=/usr/bin", "A=1", "A=2", "EMPTY=", "OPTS=x=y"]


def assert_env_kept(result, expected: list) -> None:
    assert result.snapshot["runtime"]["env"] == tuple(expected)


def test_f3_env_duplicate_n_mutant_rejecting_observed_duplicates_is_caught(monkeypatch):
    monkeypatch.setitem(inspect2.RUNTIME_RULES, "env", inspect2._image_env)
    refused(with_runtime("env", DUPLICATE_ENV), EI)  # the clean twin exposes the mutant


def test_f3_env_duplicate_n_mutant_normalizing_order_is_caught(monkeypatch):
    real_freeze = inspect2._freeze

    def normalizing(value):
        if type(value) is list and value == DUPLICATE_ENV:
            return tuple(sorted(set(value)))
        return real_freeze(value)

    monkeypatch.setattr(inspect2, "_freeze", normalizing)
    with pytest.raises(AssertionError):
        assert_env_kept(parse(with_runtime("env", DUPLICATE_ENV)), DUPLICATE_ENV)


def test_f3_env_duplicate_c_observed_duplicates_kept_in_order():
    assert_env_kept(accepted(with_runtime("env", DUPLICATE_ENV)), DUPLICATE_ENV)


def test_f3_env_duplicate_c_unique_array_kept_in_order():
    unique = ["Z=1", "A=2", "M="]
    result = accepted(with_runtime("env", unique))
    assert_env_kept(result, unique)
    assert result.snapshot["runtime"]["image_env"] == tuple(app_doc()["runtime"]["image_env"])


# ─── F3-ERROR-MAP ───────────────────────────────────────────────────────────


class ProtocolError(ValueError):
    """Shaped like a producer error: a code-like attribute and diagnostic text."""

    def __init__(self, text: str, code: str) -> None:
        super().__init__(text)
        self.code = code


class TargetRefused(ValueError):  # a stranger's class with the same name
    code = SI


def _raiser(exc: BaseException):
    def raise_it(*args):
        raise exc

    return raise_it


@pytest.mark.parametrize(
    "injected",
    [
        ProtocolError(f"inspect schema {CANARY}", SI),
        ProtocolError("inspect schema", "TARGET_SOURCE_DRIFT"),
        TargetRefused(SI),
        RuntimeError(CANARY),
        KeyError("runtime"),
        RecursionError(),
        UnicodeEncodeError("utf-8", "x", 0, 1, CANARY),
    ],
    ids=["producer_error_with_si_code", "producer_error_other_code", "stranger_class_same_name",
         "runtime_error", "key_error", "recursion_error", "unicode_error"],
)  # fmt: skip
@pytest.mark.parametrize("site", ["_check_runtime", "_check_state", "_load"])
def test_f3_error_map_n_injected_error_becomes_fixed_evidence_invalid(monkeypatch, injected, site):
    monkeypatch.setattr(inspect2, site, _raiser(injected))
    refused(app_doc(), EI)


def test_f3_error_map_n_internal_refusal_with_another_code_becomes_evidence_invalid(monkeypatch):
    monkeypatch.setattr(inspect2, "_check_runtime", _raiser(inspect2.TargetRefused("TARGET_SOURCE_DRIFT")))
    refused(app_doc(), EI)


MALFORMED = {
    "empty": b"",
    "truncated": b"{",
    "trailing_garbage": b'{"schema": "ops-host-inspect/2"} x',
    "bom": b"\xef\xbb\xbf" + json.dumps({"schema": "ops-host-inspect/2"}).encode(),
    "invalid_utf8": b'{"schema": "\xff"}',
    "encoded_surrogate": b'{"schema": "\xed\xa0\x80"}',
    "array": b"[]",
    "null": b"null",
    "string": b'"ops-host-inspect/2"',
    "nan": b'{"schema": NaN}',
    "infinity": b'{"schema": -Infinity}',
    "depth_33": b"[" * 33 + b"]" * 33,
    "oversize": b" " * 16385,
}


@pytest.mark.parametrize("label", sorted(MALFORMED))
def test_f3_error_map_n_malformed_snapshot_is_fixed_evidence_invalid(label):
    refused(MALFORMED[label], EI)


@pytest.mark.parametrize("raw", [json.dumps({"schema": 1}), bytearray(b"{}"), memoryview(b"{}"), None])
def test_f3_error_map_n_non_bytes_input_is_fixed_evidence_invalid(raw):
    with pytest.raises(inspect2.TargetRefused) as info:
        inspect2.parse_inspect2(raw, window_id=WINDOW, container_id=APP_ID, target="app")
    assert_exact_refusal(info.value, EI)


def test_f3_error_map_c_actual_local_refusal_exact_code():
    for doc, code in ((v1_23_doc(), SI), (with_runtime("data_bind", None), EI)):
        with pytest.raises(inspect2.TargetRefused) as info:
            parse(doc)
        assert_exact_refusal(info.value, code)
        assert isinstance(info.value, ValueError)
        with pytest.raises(AttributeError):
            info.value.code = EI  # read-only


def test_f3_error_map_c_refusal_needs_one_of_the_eleven_codes():
    for code in ELEVEN:
        assert inspect2.TargetRefused(code).code == code
    for bad in ("TARGET_OTHER", "", None, SI.lower()):
        with pytest.raises(ValueError) as info:
            inspect2.TargetRefused(bad)
        assert type(info.value) is ValueError


# ─── F3-BITE-TARGET ─────────────────────────────────────────────────────────

BITES = {
    "_guard_window": (app_doc, {"window_id": "win-p3-0002"}),
    "_guard_container": (app_doc, {"container_id": FWD_ID}),
    "_guard_target_bind": (lambda: with_runtime("data_bind", None), {}),
}


@pytest.mark.parametrize("guard", sorted(BITES))
def test_f3_bite_target_n_disabling_each_guard_loses_its_own_evidence_invalid(monkeypatch, guard):
    build, kwargs = BITES[guard]
    refused(build(), EI, **kwargs)
    disable(monkeypatch, guard)
    accepted(build(), **kwargs)  # only this guard stood between its own N and acceptance
    for other in sorted(set(BITES) - {guard}):
        other_build, other_kwargs = BITES[other]
        refused(other_build(), EI, **other_kwargs)  # the other guards still hold


@pytest.mark.parametrize("guard", sorted(BITES))
def test_f3_bite_target_c_clean_data_accepted_with_guard_on_or_off(monkeypatch, guard):
    accepted(app_doc())
    accepted(forwarder_doc(), target="forwarder")
    disable(monkeypatch, guard)
    accepted(app_doc())
    accepted(forwarder_doc(), target="forwarder")


# ─── F3-BITE-VERSION ────────────────────────────────────────────────────────


def test_f3_bite_version_n_disabling_fixed_v2_guard_loses_schema_mismatch(monkeypatch):
    refused(v1_23_doc(), SI)
    disable(monkeypatch, "_guard_schema")
    result = accepted(v1_23_doc())  # only the /2 guard stood between /1+23 and acceptance
    assert result.snapshot["schema"] == "ops-host-inspect/1"  # no retag either way


def test_f3_bite_version_c_v2_unchanged_with_guard_on_or_off(monkeypatch):
    on = accepted(app_doc())
    disable(monkeypatch, "_guard_schema")
    off = accepted(app_doc())
    assert thaw(on.snapshot) == thaw(off.snapshot) == app_doc()


# ─── Shared contract checks ─────────────────────────────────────────────────


def test_eleven_code_pin():
    assert inspect2.TARGET_CODES == ELEVEN
    assert len(set(ELEVEN)) == 11
    assert all(getattr(inspect2, code) == code for code in ELEVEN)


@pytest.mark.parametrize("build", [v1_23_doc, v2_22_doc, v1_22_doc], ids=["v1_23", "v2_22", "v1_22"])
def test_v1_23_and_v2_22_refused_without_raw_env(build):
    with pytest.raises(inspect2.TargetRefused) as info:
        parse(build())
    exc = info.value
    assert CANARY not in "".join((str(exc), repr(exc), repr(exc.args)))


def test_result_is_exact_untrusted_frozen_and_fresh():
    first, second = accepted(app_doc()), accepted(app_doc())
    assert {f.name for f in dataclasses.fields(first)} == {"trust", "snapshot"}
    assert CANARY not in repr(first) and CANARY not in str(first)
    with pytest.raises(TypeError):
        inspect2.Inspect2Data(snapshot=first.snapshot, trust="TRUSTED")
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.trust = "TRUSTED"
    assert first.snapshot is not second.snapshot
    assert first.snapshot["runtime"] is not second.snapshot["runtime"]
    runtime = first.snapshot["runtime"]
    assert isinstance(first.snapshot, MappingProxyType) and isinstance(runtime, MappingProxyType)
    assert isinstance(runtime["env"], tuple) and isinstance(runtime["mounts"][0], MappingProxyType)
    assert isinstance(runtime["networks"][0]["aliases"], tuple)
    with pytest.raises(TypeError):
        runtime["env"] = ()
    with pytest.raises(TypeError):
        runtime["limits"]["pids"] = 0


def test_caller_bytes_and_result_share_nothing():
    doc = app_doc()
    raw = bytearray(encode(doc))
    result = accepted(bytes(raw))
    raw[:] = b"{}"
    assert thaw(result.snapshot) == doc
