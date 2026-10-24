"""Tests for configs/architecture/bin/ops_host_client_bound.py (P5, Architecture #249).

Every F5 pair ID of the r5 CASE-REQUIREMENTS appendix, and HOME's three per-leg
order additions, gets its own named N test (one fault: the exact verdict and code)
and its own named C test (the clean twin), run through the actual landed R1-R4
modules. All data is synthetic future /2 data, written by this file's own builder
under pytest's tmp_path (0700 folders, 0600 private leaves). No shared fixture,
no conftest, no producer code, nothing from the legacy client or #150.

Restart-leg data is this file's own (Ops R5-A42 A1): Ops' /1 fixtures only model a
running container as a first start. The authority and Security22 review pins are
real hashes of real documents, which a synthetic root cannot reproduce: every test
runs with synthetic pins swapped into R2 for its duration.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import sys
import types
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "architecture" / "bin"
MODULE_PATH = BIN / "ops_host_client_bound.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ops_host_client_bound", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


p5 = _load_module()
R1, R2, R3, R4 = p5._files, p5._binding, p5._inspect, p5._env

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
CM, IU, PI, MS, AM, BI, SI, SM, SD, RM, EI = CODES
P, F = ("PASS", "NONE"), ("FAIL", "NONE")


def B(code: str = EI) -> tuple:
    return ("BLOCKED", code)


def LOAD(code: str) -> tuple:
    return ("LOAD", code)


UID = os.getuid()
ADDRESS = "100.110.162.4"
ORIGIN = f"http://{ADDRESS}:8970"
HOSTHDR = f"{ADDRESS}:8970"
PUB_ID = "p3-inspect2-publication-1"
PROJECT = "three-passing-projects"
BINDING_PATH = "expected-receiver-bindings/p3-inspect2-closed23-env1.json"
MANIFEST_REL = "calibrations/cal-1/manifest.json"
TARGET = {
    "receipt_schema": "ops-host-receipt/1",
    "inspect_schema": "ops-host-inspect/2",
    "runtime_contract": "CLOSED23-ORDERED-ENV/1",
    "semantics_revision": "p3-inspect-env-r3-a5-verdict/1",
    "caller_profiles": ["window-app-forwarder/1", "a5-launch/1"],
}
SIX_PINS = (
    ("ops_host_sha256", "ops-host/hostwin.py", "ops-hostwin", ["receiver"]),
    ("controller_sha256", "ops-host/hostctl.py", "ops-hostctl", ["caller"]),
    ("executor_sha256", "ops-host/hostops.py", "ops-hostops", ["stage"]),
    ("probe_client_sha256", "ops-host/probe/probe_client.py", "ops-probe-client", ["dependency"]),
    ("forward_py_sha256", "ops-host/forward.py", "ops-forward", ["wrapper"]),
    ("case_list_sha256", "ops-host/cases/p3-launch-cases.json", "ops-cases", ["contract"]),
)
SCHEMA_PATHS = {
    "wire_catalog": "catalog/wire.json",
    "inspect": "schemas/inspect-2.schema.json",
    "binding": "schemas/expected-receiver-binding-1.schema.json",
    "source_closure": "schemas/source-closure-1.schema.json",
    "publication": "schemas/publication-3.schema.json",
    "project_kits": "schemas/project-kits-1.schema.json",
    "calibration_manifest": "schemas/calibration-manifest-2.schema.json",
    "cohort_inventory": "schemas/cohort-inventory-1.schema.json",
}
REQUEST1, RECEIPT1, INSPECT1, INSPECT2 = ("ops-host-request/1", "ops-host-receipt/1", "ops-host-inspect/1",
                                          "ops-host-inspect/2")
WINDOW_ID = "p3-window-1"
RID = "7f3c1e2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
PRIOR_RID = "0b6c8a1e-2f3d-4a5b-9c6d-7e8f9a0b1c2d"
V1_RID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"  # a version-1 UUID: any version is valid (A6.3)
ZERO = "0001-01-01T00:00:00Z"
PDT = timezone(timedelta(hours=-7))
BASE = datetime(2026, 10, 23, 9, 0, 0, tzinfo=PDT)
NOW = BASE + timedelta(hours=10)
DATA_DEV, DATA_INODE = 64769, 131073
TARGETS = ("app", "forwarder")
ROW_TABLE = {"checker": {"R-1": "restart", "R-1i": "restart", "D-1": "crash", "D-5": "start"},
             "api-check": {"API-D-1": "crash", "API-D-5": "start"}}
WRITER = {"R-1": "checker", "R-1i": "checker", "D-1": "checker", "D-5": "checker", "API-D-1": "api-check",
          "API-D-5": "api-check"}
OPERATION = {"R-1": "restart", "R-1i": "restart", "D-1": "crash", "D-5": "start", "API-D-1": "crash",
             "API-D-5": "start"}
PRIOR_ROW = {"D-5": "D-1", "API-D-5": "API-D-1"}
SIGNAL = {"R-1": "TERM", "R-1i": "INT"}
IMAGE_ENV_APP = ["PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "PYTHONUNBUFFERED=1"]
APP_OVERRIDES = ["HOST=0.0.0.0", "PORT=8000", "DATA_DIR=/data", f"ALLOWED_HOSTS={ADDRESS}:8970,scanapp:8080"]
IMAGE_ENV_FWD = ["PATH=/usr/bin:/bin"]
LIMITS = {"pids": 256, "memory_bytes": 536870912, "nano_cpus": 1000000000}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


APP_ID, FWD_ID = sha(b"synthetic app container"), sha(b"synthetic forwarder container")
IDS = {"app": APP_ID, "forwarder": FWD_ID}
NET_INNER, NET_EDGE = sha(b"synthetic inner network"), sha(b"synthetic edge network")
APP_IMAGE, FWD_IMAGE = "sha256:" + sha(b"synthetic app image"), "sha256:" + sha(b"synthetic forwarder image")
ENTRIES = [{"name": "todo.db", "type": "regular", "size": 8192, "mtime_ns": 1761235200000000000, "target": None,
            "target_truncated": False, "sha256": sha(b"synthetic todo db")}]


def ref(path: str, raw: bytes) -> dict:
    return {"path": str(path), "sha256": sha(raw), "byte_length": len(raw)}


def dumps(value: Any) -> bytes:
    return json.dumps(value, indent=1, sort_keys=True).encode() + b"\n"


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()  # noqa: S324 (Git object id)


def tree(entries: list) -> str:
    return sha(json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


class Raw(str):
    """A JSON number token written verbatim (TD-1 cases need exact lexemes)."""


def enc(value: Any) -> str:
    if isinstance(value, Raw):
        return str(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key) + ":" + enc(item) for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(enc(item) for item in value) + "]"
    raise TypeError(type(value))


def jb(value: Any) -> bytes:
    return enc(value).encode()


def us(text: Any) -> int:
    """Seconds (text) after BASE -> integer microseconds."""
    return int(Decimal(str(text)) * 1_000_000)


def sec(n: int) -> Decimal:
    return Decimal(n) / Decimal(1_000_000)


def iso(n: int, tz: timezone = PDT) -> str:
    return (BASE + timedelta(microseconds=n)).astimezone(tz).isoformat(timespec="microseconds")


def back(text: str) -> int:
    return round((datetime.fromisoformat(text) - BASE) / timedelta(microseconds=1))


def state(running: bool, status: str, started: int | None, finished: int | None, code: int) -> dict:
    return {"running": running, "status": status, "started_at": ZERO if started is None else iso(started),
            "finished_at": ZERO if finished is None else iso(finished), "exit_code": code, "oom_killed": False,
            "restart_count": 0}


def node(node_id: str, repository: str, path: str, raw: bytes, roles: list) -> dict:
    return {"id": node_id, "repository": repository, "path": path, "git_blob": git_blob(raw), "sha256": sha(raw),
            "byte_length": len(raw), "mode": "100644", "roles": roles}


def runtime(port: int) -> dict:
    return {"image": "synthetic/scanapp:1", "command": ["python3", "/app/server.py"], "internal_port": 8000,
            "workdir": "/app", "env": {"HOST": "0.0.0.0", "PORT": "8000", "DATA_DIR": "/data",
                                       "ALLOWED_HOSTS": f"{ADDRESS}:{port},scanapp:8080"}}


def runtime_sha(value: dict) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _fake_pins() -> tuple[dict, dict, dict]:
    files: dict = {}

    def pin(path: str) -> dict:
        raw = f"synthetic stand-in for {path}\n".encode()
        files[path] = raw
        return ref(path, raw)

    pins = {"base": pin("authority/OPS-SLICE-A-PLAN.md"),
            "correction": pin("authority/OPS-SLICE-A-CORRECTION-1.md"),
            "amendment": {"proposal": pin("authority/340/PROPOSAL.md"), "manifest": pin("authority/340/manifest.json")},
            "binding_revision": {"proposal": pin("authority/346/PROPOSAL.md"),
                                 "manifest": pin("authority/346/manifest.json")},
            "qa_authority_order": pin("authority/qa/AUTHORITY-ORDER-1.md")}
    return pins, pin("authority/security22/REVIEW.md"), files


FAKE_PINS, FAKE_REVIEW, AUTH_RAW = _fake_pins()


@pytest.fixture(autouse=True)
def _synthetic_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R2, "_AUTHORITY_PINS", FAKE_PINS)
    monkeypatch.setattr(R2, "_SECURITY_REVIEW_PIN", FAKE_REVIEW)


# ---------------------------------------------------------------------------
# The builder: one coherent synthetic chain per test; knobs pick the scenario and
# hooks inject one fault into one named document before it is written.

DEFAULTS: dict = {
    "env_edges": (), "fwd_first": False, "rid": RID,
    "f200": "1.040", "reported": None, "observed": None, "elapsed": None, "obs_elapsed": None,
    "probe_start": "1.000", "probe_step": "0.510", "probe_len": "0.010", "probe_until": "30.000",
    "daemon": "1.500", "span": "1.700", "reported_stop": None, "stop_exit": 0, "forced": False, "stopped": True,
    "traceback": False, "window_start": "0", "req_expires": "7200",
}
START_EDGES = ("before-app", "before-forwarder", "after-app", "after-forwarder")


class World:
    def __init__(self, tmp: Path, row: str = "D-5", *, route: str = "project", hooks: dict | None = None,
                 **knobs: Any) -> None:
        assert not set(knobs) - set(DEFAULTS), set(knobs) - set(DEFAULTS)
        self.tmp, self.row, self.route, self.hooks = tmp, row, route, hooks or {}
        self.k = {**DEFAULTS, **knobs}
        self.qa, self.win, self.rec, self.kit = tmp / "qa", tmp / "win", tmp / "rec", tmp / "kit"
        self.ops, self.qar = tmp / "repo-ops", tmp / "repo-qa"
        self.bin, self.std = tmp / "py" / "bin", tmp / "py" / "lib"
        self.host = tmp / "host"
        self.ev = self.host / "evidence"
        self.app_copy, self.data_dir = str(self.host / "app"), str(self.host / "data")
        self.out: dict = {}
        tmp.mkdir(exist_ok=True)
        os.chmod(tmp, 0o700)
        self._publish()
        self._window()
        self._chain()
        for path, (raw, mode) in sorted(self.out.items()):
            self.write(path, raw, mode)

    # --- plumbing

    def hook(self, name: str, value: Any) -> Any:
        fn = self.hooks.get(name)
        if fn is None:
            return value
        out = fn(value, self)
        return value if out is None else out

    def put(self, path: Path, raw: bytes, mode: int = 0o600) -> bytes:
        self.out[path] = (raw, mode)
        return raw

    def qa_put(self, rel: str, raw: bytes) -> dict:
        self.put(self.qa / rel, raw)
        return ref(rel, raw)

    def write(self, path: Path, raw: bytes, mode: int) -> None:
        chain, folder = [], path.parent
        while folder != self.tmp:
            chain.append(folder)
            folder = folder.parent
        for item in reversed(chain):
            item.mkdir(exist_ok=True)
            os.chmod(item, 0o700)
        path.write_bytes(raw)
        os.chmod(path, mode)

    def evidence(self, stem: str, doc: Any) -> dict:
        doc = self.hook(stem, doc)
        raw = doc if isinstance(doc, bytes) else jb(doc)
        path = self.ev / f"{stem}-{sha(raw)[:16]}.json"
        self.put(path, raw)
        return ref(str(path), raw)

    def runtime23(self, target: str) -> dict:
        common = {"read_only_root": True, "cap_drop": ["ALL"], "cap_add": [],
                  "security_options": ["no-new-privileges:true"], "privileged": False, "devices": [], "pid_mode": "",
                  "ipc_mode": "private", "uts_mode": "", "init": True, "limits": dict(LIMITS),
                  "restart_policy": {"name": "no", "maximum_retry_count": 0}}
        if target == "app":
            return {"image_id": APP_IMAGE, "command": ["python3", "/app/server.py"], "workdir": "/app",
                    "env": IMAGE_ENV_APP + APP_OVERRIDES, "user": "1000:1000",
                    "mounts": [{"type": "bind", "source": self.app_copy, "destination": "/app", "rw": False,
                                "propagation": "rprivate"}],
                    "tmpfs": {"/tmp": "rw,size=64m"}, **common, "ports": [],
                    "networks": [{"network_id": NET_INNER, "network_name": "inner-e1", "aliases": ["scanapp"]}],
                    "data_bind": {"source": self.data_dir, "destination": "/data", "rw": True},
                    "image_env": list(IMAGE_ENV_APP)}
        return {"image_id": FWD_IMAGE, "command": ["python3", "/forward.py"], "workdir": "/srv/fwd",
                "env": list(IMAGE_ENV_FWD), "user": "65534:65534", "mounts": [], "tmpfs": {"/tmp": "rw,size=16m"},
                **common, "ports": [{"host_ip": ADDRESS, "host_port": 8970, "container_port": 8080, "protocol": "tcp"}],
                "networks": [{"network_id": NET_EDGE, "network_name": "edge-e1", "aliases": []}], "data_bind": None,
                "image_env": list(IMAGE_ENV_FWD)}

    def snap(self, stem: str, target: str, st: dict, observed: int) -> dict:
        rt = self.runtime23(target)
        if stem in self.k["env_edges"]:
            rt["env"] = ["PATH=/opt/changed/bin"] + rt["env"][1:]
        return self.evidence(stem, {"schema": INSPECT2, "window_id": WINDOW_ID, "container_id": IDS[target],
                                    "runtime": rt, "state": st, "observed_at": iso(observed)})

    def listing(self, observed: int, **changes: Any) -> dict:
        doc = {"schema": "ops-host-listing/1", "window_id": WINDOW_ID, "target": "data", "path": self.data_dir,
               "observed_at": iso(observed), "entries": copy.deepcopy(ENTRIES), "entry_count": len(ENTRIES),
               "truncated": False, "complete": True, "error": None, "tree_sha256": tree(ENTRIES),
               "todo_db_sha256": ENTRIES[0]["sha256"], "todo_db_header_18_19": [1, 1]}
        doc.update(changes)
        return doc

    def bytes_used(self) -> dict:
        return {"app_copy": 4096, "data": 8192, "tmp": 0, "work": 0, "total": 12288, "complete": True,
                "measured_at": iso(us("0.4"))}

    # --- the QA publication and R2's context (the R2 test's shape, host paths under tmp)

    def _publish(self) -> None:
        project = self.route == "project"
        domain = {"app/run.sh": (b"#!/bin/sh\nexec python3 server.py\n", 0o755),
                  "app/server.py": (b"print('synthetic app')\n", 0o644),
                  "static/index.html": (b"<p>synthetic</p>\n", 0o644)}
        sums = "".join(f"{sha(raw)}  {name}\n" for name, (raw, _) in sorted(domain.items())).encode()
        self.sums_sha = sha(sums)
        kit_raw = b"synthetic kit artifact\n"
        self.kit_sha = sha(kit_raw)
        for name, (raw, mode) in domain.items():
            self.put(self.kit / name, raw, mode)
        self.put(self.kit / "SHA256SUMS", sums)
        kit_ref = None
        if project:
            self.put(self.kit / "KIT.tar", kit_raw)
            kit_ref = ref("KIT.tar", kit_raw)
        files = [{"ref": ref(name, domain[name][0]), "mode": domain[name][1]} for name in sorted(domain)]
        self.kit_evidence = {"root": str(self.kit), "kit": kit_ref, "sums": ref("SHA256SUMS", sums), "files": files,
                             "file_count": len(files)}
        spans = {"m01": b"M01-SUBJ", "m02": b"m02sb", "sec1": b"S"}
        raws = {"m01": spans["m01"] + b"|m01 opaque record\n", "m02": b"xx" + spans["m02"] + b"|m02 opaque record\n",
                "sec1": b"sec:" + spans["sec1"] + b"|security opaque record\n"}
        offsets = {"m01": 0, "m02": 2, "sec1": 4}
        self.records, subject_refs = {}, {}
        for key in ("m01", "m02", "sec1"):
            self.put(self.rec / f"{key}.rec", raws[key])
            self.records[key] = ref(str(self.rec / f"{key}.rec"), raws[key])
            self.put(self.rec / f"subject-{key}.bin", spans[key])
            subject_refs[key] = ref(str(self.rec / f"subject-{key}.bin"), spans[key])
        self.record_subjects = [
            {"record": copy.deepcopy(self.records[key]), "byte_offset": offsets[key], "byte_length": len(spans[key]),
             "expected_subject": subject_refs[key]} for key in ("m01", "m02", "sec1")]
        nodes, self.node_sha = [], {}
        for key, path, node_id, roles in SIX_PINS:
            raw = f"# synthetic {path}\n".encode()
            self.put(self.ops / path, raw, 0o644)
            self.node_sha[key] = sha(raw)
            nodes.append(node(node_id, "ops-agent-tools", path, raw, roles))
        schema_raw = {key: dumps({"synthetic_schema": key}) for key in SCHEMA_PATHS}
        for key, path in SCHEMA_PATHS.items():
            self.put(self.qar / path, schema_raw[key], 0o644)
            roles = ["catalog"] if key == "wire_catalog" else ["schema"]
            nodes.append(node("qa-" + key.replace("_", "-"), "qa-publication", path, schema_raw[key], roles))
        nodes.sort(key=lambda item: item["id"])
        edges = sorted([("ops-hostctl", "ops-hostwin", "imports"), ("ops-hostwin", "ops-hostops", "imports"),
                        ("ops-hostctl", "ops-probe-client", "loads"), ("ops-hostwin", "ops-forward", "executes"),
                        ("ops-hostctl", "ops-cases", "compares")])
        edges = [{"from": a, "to": b, "kind": kind} for a, b, kind in edges]
        exe = b"#!synthetic python\n"
        self.put(self.bin / "python3", exe, 0o755)
        stdlib = {"json/__init__.py": b"# synthetic json\n", "os.py": b"# synthetic os\n"}
        for path, raw in stdlib.items():
            self.put(self.std / path, raw, 0o644)
        inventory = [{"path": path, "sha256": sha(raw), "byte_length": len(raw), "mode": "0644", "uid": UID}
                     for path, raw in sorted(stdlib.items())]
        run = {"implementation": "cpython", "version": "3.12.0", "executable": ref(str(self.bin / "python3"), exe),
               "executable_uid": UID, "executable_mode": "0755", "stdlib_root": str(self.std),
               "stdlib_inventory": self.qa_put("runtime/STDLIB-INVENTORY.json", dumps(inventory))}
        cohort_files = {"cohort/fresh/b.json": (dumps({"ref": "cohort/orig/a.json"}), "fresh"),
                        "cohort/neg/empty.json": (b"", "intentional-negative"),
                        "cohort/orig/a.json": (dumps({"original": True}), "original")}
        listed = []
        for path, (raw, kind) in sorted(cohort_files.items()):
            self.put(self.qa / path, raw)
            listed.append({**ref(path, raw), "kind": kind})
        original = cohort_files["cohort/orig/a.json"][0]
        references = [
            {"from": "cohort/fresh/b.json", "pointer": "/ref", "to": "cohort/orig/a.json", "sha256": sha(original),
             "byte_length": len(original), "disposition": "resolved", "failure": "none"},
            {"from": "cohort/neg/empty.json", "pointer": "", "to": None, "sha256": None, "byte_length": None,
             "disposition": "unknown", "failure": "invalid-json"}]
        expectations = [{"original_pointer": "/0", "original_path": "cohort/orig/a.json", "original_label": "a",
                         "observed_original_result": "pass", "new_path": "cohort/fresh/b.json",
                         "new_expected_result": "pass", "reason": "same content"}]
        cohort = {
            "schema": "qa-ops-host-cohort-inventory/1", "publication_id": PUB_ID, "cohort_id": "cohort-1",
            "files": listed, "references": references,
            "original_inventory": self.qa_put("cohort/ORIGINAL-INVENTORY.json",
                                              dumps([ref("cohort/orig/a.json", original)])),
            "original_index": self.qa_put("cohort/ORIGINAL-INDEX.json", dumps({"index": ["cohort/orig/a.json"]})),
            "old_to_new_expectations": self.qa_put("cohort/OLD-TO-NEW.json", dumps(expectations))}
        closure = {
            "schema": "qa-ops-host-source-closure/1", "publication_id": PUB_ID,
            "repositories": [
                {"id": "ops-agent-tools", "owner": "ops", "root": str(self.ops), "commit": "a" * 40, "tree": "b" * 40},
                {"id": "qa-publication", "owner": "qa", "root": str(self.qar), "commit": "c" * 40, "tree": "d" * 40}],
            "nodes": nodes, "edges": edges, "entrypoints": [{"node": "ops-hostctl", "symbol": "main"}],
            "runtime": run, "generated_closure": self.qa_put("COHORT-INVENTORY.json", dumps(cohort))}
        for path, raw in AUTH_RAW.items():
            self.qa_put(path, raw)
        binding = {
            "schema": "qa-ops-host-expected-receiver-binding/1", "issuer": "qa", "project": PROJECT,
            "publication_id": PUB_ID, "binding_id": "p3-inspect2-closed23-env1", "target": copy.deepcopy(TARGET),
            "authority": copy.deepcopy(FAKE_PINS),
            "schemas": {key: self.qa_put(path, schema_raw[key]) for key, path in SCHEMA_PATHS.items()},
            "security_context": {"review": copy.deepcopy(FAKE_REVIEW),
                                 "identity": self.qa_put("authority/security22/IDENTITY.json",
                                                         dumps({"synthetic": "identity"}))},
            "source_closure": self.qa_put("SOURCE-CLOSURE.json", dumps(closure))}
        bref = self.qa_put(BINDING_PATH, dumps(binding))
        table = {"schema": "qa-ops-host-project-kits/1", "publication_id": PUB_ID, "kits": [
            {"project_id": "p3", "kit_id": "kit-0", "kit_sha256": "0" * 64, "build_sums_sha256": "1" * 64,
             "expected_receiver_binding": copy.deepcopy(bref)},
            {"project_id": "p3", "kit_id": "kit-1", "kit_sha256": self.kit_sha, "build_sums_sha256": self.sums_sha,
             "expected_receiver_binding": copy.deepcopy(bref)}]}
        table_ref = self.qa_put("PROJECT-KITS.json", dumps(table))
        rt1, rt2 = runtime(8970), runtime(8971)
        self.rt1 = rt1
        e1 = {"entry": "e1", "build_id": "C0", "purpose": "clean", "copy_id": "c01", "batch_id": "b1",
              "build_path": str(self.kit), "sums_file": str(self.kit) + "/SHA256SUMS", "host_dir": str(self.host),
              "app_copy_path": self.app_copy, "data_dir": self.data_dir, "sums_sha256": self.sums_sha,
              "runtime_sha256": runtime_sha(rt1), "file_count": len(domain), "plant_of": None,
              "diff_sha256": None, "round": 1, "address": ADDRESS, "port": 8970,
              "literal_origin": ORIGIN, "runtime": rt1, "inner_network_name": "inner-e1",
              "edge_network_name": "edge-e1", "reuse_after": [], "scheduled_use_minutes": None,
              "schedule_source": None, "schedule_sha256": None, "expected_receiver_binding": copy.deepcopy(bref)}
        e2 = {"entry": "e2", "build_id": "C1", "purpose": "plant", "copy_id": "c02", "batch_id": "b1",
              "build_path": "/srv/builds/c1", "sums_file": "/srv/builds/c1/SHA256SUMS", "host_dir": "/srv/host/e2",
              "app_copy_path": "/srv/app/e2", "data_dir": "/srv/data/e2", "sums_sha256": "2" * 64,
              "runtime_sha256": runtime_sha(rt2), "file_count": 5, "plant_of": "C0", "diff_sha256": "d" * 64,
              "round": 2, "address": ADDRESS, "port": 8971, "literal_origin": f"http://{ADDRESS}:8971",
              "runtime": rt2, "inner_network_name": "inner-e2", "edge_network_name": "edge-e2",
              "reuse_after": ["e1"], "scheduled_use_minutes": 30, "schedule_source": "schedule-1",
              "schedule_sha256": "e" * 64, "expected_receiver_binding": copy.deepcopy(bref)}
        manifest = {
            "schema": "qa-calibration-manifest/2", "publication_id": PUB_ID, "calibration_id": "cal-1",
            "draft_kit_id": "draft-1", "host_rows": {"R-1": "restart", "R-1i": "restart", "D-1": "crash",
                                                     "D-5": "start", "API-D-1": "crash", "API-D-5": "start",
                                                     "HOST-L": "launch-cases"},
            "entries": [e1, e2]}
        self.manifest_raw = dumps(manifest)
        manifest_ref = self.qa_put(MANIFEST_REL, self.manifest_raw)
        publication = {"schema": "qa-ops-host-publication/3", "issuer": "qa", "project": PROJECT,
                       "publication_id": PUB_ID, "project_kits": table_ref, "calibration_manifests": [manifest_ref]}
        self.publication_raw = dumps(publication)
        self.put(self.qa / "PUBLICATION.json", self.publication_raw)
        if project:
            self.binding = {"mode": "project", "project_id": "p3", "run_id": "run-1",
                            "build_sums_sha256": self.sums_sha, "kit_id": "kit-1", "kit_sha256": self.kit_sha}
            self.selection = None
        else:
            self.binding = {"mode": "calibration", "manifest_sha256": sha(self.manifest_raw), "entry": "e1",
                            "build_sums_sha256": self.sums_sha, "calibration_run": "cal-run-1"}
            self.selection = {"manifest_path": str(self.qa / MANIFEST_REL), "manifest_sha256": sha(self.manifest_raw),
                              "entry": "e1", "build_id": "C0", "sums_sha256": self.sums_sha, "round": 1,
                              "copy_id": "c01", "address": ADDRESS, "port": 8970, "literal_origin": ORIGIN,
                              "runtime_sha256": runtime_sha(rt1), "security_receipt_id": "P3-CAL-1",
                              "security_receipt_path": "/srv/s4/receipt-1.json",
                              "security_receipt_sha256": "f" * 64, "security_selection_message_id": "rm-s4-1"}

    # --- the armed window (host-publication-v2 O 6.6) and its R2 context

    def _window(self) -> None:
        start = us(self.k["window_start"])
        self.creation = {t: self.snap(f"creation-{t}", t, state(False, "created", None, None, 0), us("0.5"))
                         for t in TARGETS}
        window = {
            "window_id": WINDOW_ID, "host_dir": str(self.host), "origin": ORIGIN,
            "binding": copy.deepcopy(self.binding), "runtime": copy.deepcopy(self.rt1),
            "row_table": copy.deepcopy(ROW_TABLE), "window_started_at": iso(start), "scheduled_use_minutes": None,
            "schedule_source": None, "schedule_sha256": None, "window_ttl_minutes": 480,
            "window_expires_at": iso(start + 480 * 60 * 1_000_000), "bytes_used": self.bytes_used(),
            "app_container_id": APP_ID, "fwd_container_id": FWD_ID, "network_ids": [NET_INNER, NET_EDGE],
            "creation_inspect": copy.deepcopy(self.creation), "calibration_selection": copy.deepcopy(self.selection),
            "data_dir": self.data_dir, "data_dev": DATA_DEV, "data_inode": DATA_INODE, "data_mode": 0o700,
            "security_receipt_path": "/srv/s4/receipt-1.json", "security_receipt_sha256": "f" * 64,
            **self.node_sha, "case_list_path": str(self.ops / "ops-host/cases/p3-launch-cases.json"),
            "app_copy_path": self.app_copy, "receipts_log_path": str(self.host / "receipts.log"),
            "init_check": {"host_config_init": True, "docker_top_child": "python3 /app/server.py",
                           "observed_at": iso(us("1.2"))},
            "port_copy_map": [{"port": 8970, "copy_id": "c01", "sums_sha256": self.sums_sha}]}
        self.window = self.hook("window", window)
        raw = dumps(self.window)
        self.window_path = self.win / "WINDOW.json"
        self.put(self.window_path, raw)
        self.window_sha = sha(raw)
        context = {
            "window": ref(str(self.window_path), raw),
            "publication": ref(str(self.qa / "PUBLICATION.json"), self.publication_raw),
            "m01_record": copy.deepcopy(self.records["m01"]), "m02_record": copy.deepcopy(self.records["m02"]),
            "security_records": [copy.deepcopy(self.records["sec1"])], "expected_window_sha256": self.window_sha,
            "expected_binding": copy.deepcopy(self.binding),
            "release_roots": [{"repository": "ops-agent-tools", "root": str(self.ops)},
                              {"repository": "qa-publication", "root": str(self.qar)}],
            "kit_evidence": self.kit_evidence, "record_subjects": self.record_subjects}
        if self.route != "project":
            context.update({"calibration_manifest": ref(str(self.qa / MANIFEST_REL), self.manifest_raw),
                            "expected_draft_kit_id": "draft-1",
                            "expected_calibration_selection": copy.deepcopy(self.selection)})
        self.context = self.hook("context", context)

    # --- requests and receipts

    def request(self, row: str, rid: str, seq: int, since: int) -> dict:
        op = OPERATION[row]
        return {"schema": REQUEST1, "binding": copy.deepcopy(self.binding), "window_id": WINDOW_ID, "row": row,
                "operation": op, "host_action": op, "writer": WRITER[row], "request_id": rid, "origin": ORIGIN,
                "receipt_file": f"{self.host}/{row}.json", "action": f"run {row}", "expected": "the QA host steps",
                "since": iso(since), "not_before": iso(since), "expires_at": iso(us(self.k["req_expires"])),
                "sequence": seq, "wait_seconds": 60, "receipt_format": RECEIPT1, "write": True}

    def common(self, row: str, rid: str, seq: int, begin: int, end: int, failed: bool, exit_code: Any,
               request_raw: bytes) -> dict:
        op = OPERATION[row]
        return {"schema": RECEIPT1, "row": row, "operation": op, "host_action": op, "writer": WRITER[row],
                "request_id": rid, "window_id": WINDOW_ID, "sequence": seq, "sequence_used": True,
                "expected_sequence": seq + 1, "binding": copy.deepcopy(self.binding),
                "request_sha256": sha(request_raw), "controller_sha256": self.node_sha["controller_sha256"],
                "executor_sha256": self.node_sha["executor_sha256"], "sums_sha256": self.sums_sha,
                "done": not failed, "decision": "FAILED" if failed else "DONE",
                "failure_kind": "app" if failed else None, "by": "hostctl", "note": "", "reason": "",
                "at": iso(end + 100_000), "seen_at": iso(end + 200_000), "started_at": iso(begin),
                "ended_at": iso(end), "lane": "app", "app_container_id": APP_ID, "fwd_container_id": FWD_ID,
                "exit_code": exit_code, "window_ttl_minutes": 480,
                "window_expires_at": self.window["window_expires_at"], "bytes_used": self.bytes_used()}

    def crash_receipt(self, row: str, rid: str, seq: int, request_raw: bytes, stem: str) -> tuple[dict, dict]:
        failed = stem in self.k["env_edges"]
        sent, exited, end = us("3001"), us("3001.1"), us("3001.5")
        terminal = self.snap(stem, "app", state(False, "exited", us("1"), exited, 137), us("3001.2"))
        listing = self.evidence("listing-exit", self.listing(exited + 50_000))
        r = self.common(row, rid, seq, us("3000"), end, failed, 137, request_raw)
        r.update({"exit_status": "exited", "listener_gone": True, "origin_refused": True, "signal": "KILL",
                  "kill_sent_at": iso(sent), "exited_at": iso(exited), "data_listing_after_exit": listing,
                  "stop_inspect": terminal})
        return r, {"exited": exited, "listing": listing, "code": 137}

    def probe(self, t0: int, a: int, b: int, status: int | None) -> dict:
        if status is None:
            result = {"outcome": "refused", "status": None, "response_at": None, "elapsed_seconds": sec(b - a),
                      "error": "refused"}
        else:
            result = {"outcome": "response", "status": status, "response_at": iso(t0 + b),
                      "elapsed_seconds": sec(b - a), "error": None}
        return {"kind": "inprocess", "op": "health", "started_at": iso(t0 + a), "ended_at": iso(t0 + b),
                "exit_code": None, "argv": None,
                "params": {"method": "GET", "url": ORIGIN + "/api/items", "host": HOSTHDR, "timeout_seconds": 3},
                "result": result}

    def probes(self, t0: int) -> list:
        k = self.k
        start, step, length = us(k["probe_start"]), us(k["probe_step"]), us(k["probe_len"])
        if k["f200"] is None:
            out, at = [], start
            while at < us(k["probe_until"]):
                out.append(self.probe(t0, at, at + length, None))
                at += step
            return out
        f = us(k["f200"])
        n = (min(f, us("29.999")) - start) // step
        out = [self.probe(t0, start + i * step, start + i * step + length, None) for i in range(n)]
        out.append(self.probe(t0, start + n * step, f, 200))
        return out

    def start_chain(self, row: str, rid: str, seq: int, s_begin: int, prior: dict) -> tuple[dict, int, bool]:
        k = self.k
        t0 = s_begin + 500_000
        runs: list = []

        def add(op: str, a: str, b: str, params: dict, result: dict, *, kind: str = "inprocess",
                argv: Any = None, exit_code: Any = None) -> None:
            runs.append({"kind": kind, "op": op, "started_at": iso(t0 + us(a)), "ended_at": iso(t0 + us(b)),
                         "exit_code": exit_code, "argv": argv, "params": params, "result": result})

        def docker(op: str, target: str, a: str, b: str, result: dict) -> None:
            add(f"docker-{op}", a, b, {"target": target, "container_id": IDS[target]}, result, kind="process",
                argv=["docker", op, IDS[target]], exit_code=0)

        def listener(a: str, b: str, present: bool) -> None:
            sockets = [{"address": ADDRESS, "port": 8970, "protocol": "tcp"}] if present else []
            add("listener", a, b, {"address": ADDRESS, "port": 8970},
                {"outcome": "ok", "present": present, "sockets": sockets, "error": None}, kind="process",
                argv=["ss", "-ltnH", "sport", "=", ":8970"], exit_code=0)

        stat = ({"path": self.data_dir, "follow_symlinks": False},
                {"outcome": "ok", "dev": DATA_DEV, "inode": DATA_INODE, "mode": 0o700, "error": None})
        add("data-stat", "-0.35", "-0.34", *stat)
        listing_before = self.evidence("listing-before", self.listing(t0 - 310_000))
        add("data-list", "-0.33", "-0.30", {"path": self.data_dir, "follow_symlinks": False, "max_entries": 10000,
                                            "max_depth": 16},
            {"outcome": "ok", "snapshot": listing_before, "error": None})
        listener("-0.29", "-0.28", False)
        fwd_exit = None if k["fwd_first"] else prior["exited"] + 50_000
        before = {"app": self.snap("before-app", "app", state(False, "exited", us("1"), prior["exited"],
                                                                prior["code"]), t0 - 262_000),
                  "forwarder": self.snap("before-forwarder", "forwarder",
                                         state(False, "created", None, None, 0) if k["fwd_first"] else
                                         state(False, "exited", us("1.1"), fwd_exit, 0), t0 - 242_000)}
        docker("inspect", "app", "-0.27", "-0.26", {"outcome": "ok", "snapshot": before["app"], "error": None})
        docker("inspect", "forwarder", "-0.25", "-0.24",
               {"outcome": "ok", "snapshot": before["forwarder"], "error": None})
        docker("start", "app", "0", "0.4", {"outcome": "ok", "started": True, "error": None})
        docker("start", "forwarder", "0.5", "0.8", {"outcome": "ok", "started": True, "error": None})
        add("data-stat", "0.85", "0.86", *stat)
        after = {"app": self.snap("after-app", "app", state(True, "running", t0 + 300_000, prior["exited"], 0),
                                  t0 + 875_000),
                 "forwarder": self.snap("after-forwarder", "forwarder",
                                        state(True, "running", t0 + 600_000, fwd_exit, 0), t0 + 895_000)}
        docker("inspect", "app", "0.87", "0.88", {"outcome": "ok", "snapshot": after["app"], "error": None})
        docker("inspect", "forwarder", "0.89", "0.90",
               {"outcome": "ok", "snapshot": after["forwarder"], "error": None})
        f = None if k["f200"] is None else us(k["f200"])
        outcome = "miss" if f is None else ("healthy" if f <= 30_000_000 else "late")
        listener("0.91", "0.92", outcome != "miss")
        probes = self.hook("probes", self.probes(t0))
        runs = self.hook("runs", runs + probes)
        statuses = [p["result"]["status"] for p in probes if p["result"]["status"] is not None]
        last_status = statuses[-1] if statuses else None
        observed = us(k["observed"]) if k["observed"] else (f + 10_000 if f is not None else us("30.050"))
        elapsed = k["elapsed"] or str(sec(observed))
        observation = {"method": "GET", "path": "/api/items", "host": HOSTHDR, "outcome": outcome,
                       "probe_count": len(probes),
                       "first_probe_at": probes[0]["started_at"] if probes else iso(t0),
                       "last_probe_at": probes[-1]["started_at"] if probes else iso(t0),
                       "observed_until": iso(t0 + observed), "elapsed_seconds": Raw(k["obs_elapsed"] or elapsed),
                       "last_http_status": last_status, "complete": True}
        ends = [observed, 920_000, 30_000_000 if f is None else f]
        for item in runs:
            try:
                ends.append(back(item["ended_at"]) - t0)
            except (KeyError, TypeError, ValueError):
                pass
        audit_end = t0 + max(ends) + 50_000
        audit = self.hook("audit", {"schema": "start-audit/1", "window_id": WINDOW_ID, "writer": WRITER[row],
                                    "request_id": rid, "sequence": seq, "row": row, "operation": OPERATION[row],
                                    "commands_run": runs})
        raw = jb(audit)
        leaf = f"audit-{rid}-{seq}.json"
        self.put(self.host / leaf, raw)
        audit_ref = self.hook("audit_ref", {"path": leaf, "sha256": sha(raw), "byte_length": len(raw)})
        identity: dict = {"window_sha256": self.window_sha}
        for t in TARGETS:
            identity[t] = {"container_id": IDS[t], "creation_record": copy.deepcopy(self.creation[t]),
                           "before_inspect": before[t], "after_inspect": after[t],
                           "before_matches_creation": f"before-{t}" not in k["env_edges"],
                           "after_matches_creation": f"after-{t}" not in k["env_edges"]}
        e = {"start_sent_at": iso(t0), "app_started_at": iso(t0 + 300_000),
             "health_at": None if f is None else iso(t0 + f), "health_code": last_status,
             "seconds_to_health": None if f is None else Raw(k["reported"] or k["f200"]),
             "health_elapsed_seconds": Raw(elapsed), "health_observation": observation, "identity_evidence": identity,
             "prior_exit_evidence": None, "data_listing_after_exit": prior["listing"],
             "data_listing_before_start": listing_before, "listings_match": True, "start_audit_ref": audit_ref,
             "audit_started_at": iso(prior["exited"]), "audit_ended_at": iso(audit_end), "audit_complete": True,
             "listener_present": outcome != "miss"}
        missed = outcome != "healthy" or any(edge in k["env_edges"] for edge in START_EDGES)
        return e, audit_end + 100_000, missed

    def start_receipt(self, row: str, request_raw: bytes) -> dict:
        prior_row = PRIOR_ROW[row]
        prior_request = jb(self.request(prior_row, PRIOR_RID, 1, us("2900")))
        crash, facts = self.crash_receipt(prior_row, PRIOR_RID, 1, prior_request, "prior-terminal")
        crash = self.hook("prior", crash)
        raw = crash if isinstance(crash, bytes) else jb(crash)
        self.put(self.host / f"{prior_row}.json", raw)
        prior_ref = self.hook("prior_evidence", {"kind": "receipt", "row": prior_row, "writer": WRITER[prior_row],
                                                 "request_id": PRIOR_RID, "sequence": 1, "sha256": sha(raw),
                                                 "byte_length": len(raw)})
        begin = us("3600")
        e, end, missed = self.start_chain(row, self.k["rid"], 2, begin, facts)
        e["prior_exit_evidence"] = prior_ref
        r = self.common(row, self.k["rid"], 2, begin, end, missed, None, request_raw)
        r.update(e)
        r["same_inode"] = True
        return r

    def restart_receipt(self, row: str, request_raw: bytes) -> dict:
        k = self.k
        g_begin = us("3600")
        sent = g_begin + 100_000
        exited, g_end = sent + us(k["daemon"]), sent + us(k["span"])
        mid = (sent + exited) // 2
        terminal = self.snap("terminal", "app", state(False, "exited", us("1"), exited, k["stop_exit"]),
                             (exited + g_end) // 2)
        listing = self.evidence("listing-exit", self.listing(exited))
        reported = k["reported_stop"] or k["daemon"]
        within = Decimal(k["daemon"]) <= 10 and Decimal(reported) <= 10
        stop_e = {"signal": SIGNAL[row], "signal_sent_at": iso(sent), "exited_at": iso(exited),
                  "seconds_to_exit": Raw(reported), "within_10s": within, "forced_kill": k["forced"],
                  "kill_sent_at": iso(mid) if k["forced"] else None, "stopped_line_seen": k["stopped"],
                  "stopped_line_at": iso(mid) if k["stopped"] else None, "traceback_seen": k["traceback"],
                  "traceback_line": "Traceback (most recent call last):" if k["traceback"] else None,
                  "traceback_first_at": iso(mid) if k["traceback"] else None, "data_listing_after_exit": listing,
                  "stop_inspect": terminal}
        stop_failed = (k["stop_exit"] != 0 or not within or k["forced"] or not k["stopped"] or k["traceback"]
                       or "terminal" in k["env_edges"])
        s_begin = g_end + 100_000
        start_e, s_end, start_failed = self.start_chain(row, k["rid"], 1, s_begin,
                                                        {"exited": exited, "listing": listing,
                                                         "code": k["stop_exit"]})
        start_e["prior_exit_evidence"] = {"kind": "restart-leg", "leg": "stop-graceful"}

        def leg(name: str, failed: bool, a: int, b: int, code: Any, evidence: dict) -> dict:
            return {"leg": name, "decision": "FAILED" if failed else "DONE", "failure_kind": "app" if failed else None,
                    "started_at": iso(a), "ended_at": iso(b), "exit_code": code, "evidence": evidence}

        r = self.common(row, k["rid"], 1, g_begin, s_end + 50_000, stop_failed or start_failed, k["stop_exit"],
                        request_raw)
        r.update({"legs": [leg("stop-graceful", stop_failed, g_begin, g_end, k["stop_exit"], stop_e),
                           leg("start", start_failed, s_begin, s_end, None, start_e)],
                  "listener_gone": True})
        return r

    def _chain(self) -> None:
        row, k = self.row, self.k
        op = OPERATION[row]
        since = us("2900") if op == "crash" else us("3500")
        request = self.hook("request", self.request(row, k["rid"], 2 if op == "start" else 1, since))
        self.request_raw = self.hook("request_raw", jb(request))
        if op == "crash":
            receipt = self.crash_receipt(row, k["rid"], 1, self.request_raw, "terminal")[0]
        elif op == "start":
            receipt = self.start_receipt(row, self.request_raw)
        else:
            receipt = self.restart_receipt(row, self.request_raw)
        receipt = self.hook("receipt", receipt)
        raw = receipt if isinstance(receipt, bytes) else jb(receipt)
        path = self.host / f"{row}.json"
        self.put(path, raw)
        self.receipt_ref = self.hook("receipt_ref", ref(str(path), raw))


def load(world: World) -> Any:
    return p5.load_bound_candidate_window(str(world.window_path), world.window_sha, data_context=world.context,
                                          uid=UID)


def run(world: World, now: datetime = NOW) -> tuple:
    try:
        window = load(world)
    except p5.TargetRefused as exc:
        assert type(exc) is p5.TargetRefused and exc.args == (exc.code,) and exc.code in CODES
        return LOAD(exc.code)
    result = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=window, now=now)
    assert type(result) is p5.UntrustedAssessment and result.trust == "UNTRUSTED"
    assert (result.code == "NONE") is (result.verdict in ("PASS", "FAIL"))
    return result.verdict, result.code


# ---------------------------------------------------------------------------
# Hook helpers: each changes one named document before it is written.

class W:
    """A value that depends on the world (paths under tmp)."""

    def __init__(self, fn: Any) -> None:
        self.fn = fn


def _value(value: Any, world: World) -> Any:
    return value.fn(world) if isinstance(value, W) else copy.deepcopy(value)


def _parent(doc: Any, path: tuple) -> Any:
    for key in path[:-1]:
        doc = doc[key]
    return doc


def _path(path: Any) -> tuple:
    return path if isinstance(path, tuple) else (path,)


def sv(*pairs: Any) -> Any:
    """Set (path, value) pairs."""
    def fn(doc: Any, world: World) -> None:
        for path, value in zip(pairs[::2], pairs[1::2], strict=True):
            path = _path(path)
            _parent(doc, path)[path[-1]] = _value(value, world)
    return fn


def dl(*paths: Any) -> Any:
    """Delete keys."""
    def fn(doc: Any, world: World) -> None:
        for path in map(_path, paths):
            del _parent(doc, path)[path[-1]]
    return fn


def tv(path: tuple, change: Any) -> Any:
    """Transform one value."""
    def fn(doc: Any, world: World) -> None:
        _parent(doc, path)[path[-1]] = change(_parent(doc, path)[path[-1]])
    return fn


def both(*fns: Any) -> Any:
    def fn(doc: Any, world: World) -> Any:
        for item in fns:
            out = item(doc, world)
            doc = doc if out is None else out
        return doc
    return fn


def bump_length(doc: dict, world: World) -> None:
    doc["byte_length"] += 1


def keep_legs(count: int) -> Any:
    def fn(doc: dict, world: World) -> None:
        del doc["legs"][count:]
    return fn


def third_leg(doc: dict, world: World) -> None:
    doc["legs"].append(copy.deepcopy(doc["legs"][1]))


def second_start(runs: list, world: World) -> None:
    """A second docker start of the app, right after the forwarder's start: a repair."""
    index = next(i for i, item in enumerate(runs) if item["op"] == "docker-start"
                 and item["params"]["target"] == "forwarder")
    extra = copy.deepcopy(next(item for item in runs if item["op"] == "docker-start"))
    end = back(runs[index]["ended_at"])
    extra["started_at"], extra["ended_at"] = iso(end + 10_000), iso(end + 40_000)
    runs.insert(index + 1, extra)


def shift_from(index: int, delta: int) -> Any:
    def fn(probes: list, world: World) -> None:
        for item in probes[index:]:
            item["started_at"] = iso(back(item["started_at"]) + delta)
            item["ended_at"] = iso(back(item["ended_at"]) + delta)
    return fn


def extra_probe(at: str) -> Any:
    def fn(probes: list, world: World) -> None:
        t0 = back(probes[0]["started_at"]) - us(world.k["probe_start"])
        probes.append(world.probe(t0, us(at), us(at) + 10_000, None))
    return fn


def drop_probe(index: int) -> Any:
    def fn(probes: list, world: World) -> None:
        del probes[index]
    return fn


def resample(probes: list, world: World) -> None:
    t0 = back(probes[0]["started_at"]) - us(world.k["probe_start"])
    end = back(probes[-1]["ended_at"]) - t0
    probes.append(world.probe(t0, end + 100_000, end + 140_000, 200))


def clamp_late(probes: list, world: World) -> None:
    t0 = back(probes[0]["started_at"]) - us(world.k["probe_start"])
    probes[-1]["result"]["response_at"] = iso(t0 + us("30.000"))


def synthetic_null(probes: list, world: World) -> None:
    item = probes[-1]
    item["result"] = {"outcome": "timeout", "status": None, "response_at": None,
                      "elapsed_seconds": sec(back(item["ended_at"]) - back(item["started_at"])), "error": "timeout"}


def app_copy_changes(truncated: bool) -> Any:
    def fn(doc: dict, world: World) -> None:
        doc["app_copy_changes"] = world.evidence("listing-app-copy", world.listing(
            us("3001.3"), target="app_copy", path=world.app_copy, truncated=truncated))
    return fn


def finish_after_start(doc: dict, world: World) -> None:
    doc["state"]["finished_at"] = iso(back(doc["state"]["started_at"]) + 1000)


def start_after_finish(doc: dict, world: World) -> None:
    doc["state"]["started_at"] = iso(back(doc["state"]["finished_at"]) + 1000)


def dup_env(doc: dict, world: World) -> None:
    doc["runtime"]["env"].append(doc["runtime"]["env"][0])


def reorder_env(doc: dict, world: World) -> None:
    env = doc["runtime"]["env"]
    env[0], env[1] = env[1], env[0]


def to_utc(text: str) -> str:
    return datetime.fromisoformat(text).astimezone(UTC).isoformat(timespec="microseconds")


def all_utc(doc: Any, world: World) -> Any:
    """Every offset instant of the receipt, re-rendered in UTC (+00:00)."""
    if isinstance(doc, dict):
        return {key: all_utc(item, world) for key, item in doc.items()}
    if isinstance(doc, list):
        return [all_utc(item, world) for item in doc]
    if type(doc) is str and len(doc) == 32 and doc[10] == "T" and doc[-6] in "+-":
        return to_utc(doc)
    return doc


AS_DONE = sv("decision", "DONE", "failure_kind", None, "done", True)
AS_FAILED = sv("decision", "FAILED", "failure_kind", "app", "done", False)
AS_HOST = sv("decision", "FAILED", "failure_kind", "host", "done", False)
STOP_HOST = sv(("legs", 0, "decision"), "FAILED", ("legs", 0, "failure_kind"), "host")
STOP_REFUSED = sv(("legs", 0, "decision"), "REFUSED", ("legs", 0, "failure_kind"), None)
RUNNING = sv(("state", "running"), True, ("state", "status"), "running")
OTHER_IMAGE = "sha256:" + "9" * 64
ENV_T = ("terminal",)
ENV_PRIOR = ("prior-terminal",)


# ---------------------------------------------------------------------------
# The case table: every F5 pair (and HOME's three additions), N and C, each named.

class Case(NamedTuple):
    fid: str
    kind: str
    name: str
    expect: tuple
    row: str
    route: str
    hooks: dict
    knobs: dict


CASES: list = []


def N(fid: str, name: str, expect: tuple, row: str = "D-5", route: str = "project", h: dict | None = None,
      **knobs: Any) -> None:
    CASES.append(Case(fid, "N", name, expect, row, route, h or {}, knobs))


def C(fid: str, name: str, expect: tuple, row: str = "D-5", route: str = "project", h: dict | None = None,
      **knobs: Any) -> None:
    CASES.append(Case(fid, "C", name, expect, row, route, h or {}, knobs))


# C1: truthful app misses vs evidence faults (clean cases first).
C("F5-ENV-FAIL", "crash-matching-env", P, "D-1")
C("F5-ENV-FAIL", "start-matching-env", P)
N("F5-ENV-FAIL", "crash-terminal-env-differs", F, "D-1", env_edges=ENV_T)
N("F5-ENV-FAIL", "start-after-env-differs", F, env_edges=("after-app",))
C("F5-ENV-NONENV-FAULT", "env-only", F, "D-1", env_edges=ENV_T)
N("F5-ENV-NONENV-FAULT", "env-and-wrong-source", B(), "D-1", env_edges=ENV_T,
  h={"receipt": sv("controller_sha256", "0" * 64)})
N("F5-ENV-NONENV-FAULT", "env-and-no-listener-witness", B(), "D-1", env_edges=ENV_T,
  h={"receipt": sv("listener_gone", False)})
N("F5-ENV-NONENV-FAULT", "env-and-no-origin-witness", B(), "D-1", env_edges=ENV_T,
  h={"receipt": dl("origin_refused")})
C("F5-START-COMPLETE-MISS", "timely-first200", P)
N("F5-START-COMPLETE-MISS", "present-null-complete-miss", F, f200=None)
C("F5-START-200-NULL", "real-200-pair", P)
N("F5-START-200-NULL", "both-null", B(), h={"receipt": sv("health_at", None, "seconds_to_health", None)})
N("F5-START-200-NULL", "health_at-null", B(), h={"receipt": sv("health_at", None)})
N("F5-START-200-NULL", "seconds_to_health-null", B(), h={"receipt": sv("seconds_to_health", None)})
C("F5-START-MISSING-NULL", "present-null-complete-miss", F, f200=None)
N("F5-START-MISSING-NULL", "health_at-absent", B(), f200=None, h={"receipt": dl("health_at")})
N("F5-START-MISSING-NULL", "seconds_to_health-absent", B(), f200=None, h={"receipt": dl("seconds_to_health")})
C("F5-START-LATE200", "both-within-30", P)
N("F5-START-LATE200", "both-over-30", F, f200="31.000")
C("F5-START-DONE-NULL", "failed-app-null-pair", F, f200=None)
N("F5-START-DONE-NULL", "done-with-null-pair", B(), f200=None, h={"receipt": AS_DONE})
C("F5-STOP-OVER10", "timely-stop", P, "R-1")
C("F5-STOP-OVER10", "timely-stop-int", P, "R-1i")
N("F5-STOP-OVER10", "both-over-10", F, "R-1", daemon="10.500", span="10.700")
C("F5-STOP-NONZERO", "exit-0", P, "R-1")
N("F5-STOP-NONZERO", "exit-1", F, "R-1", stop_exit=1)
C("F5-STOP-NO-STOPPED", "stopped-line", P, "R-1")
N("F5-STOP-NO-STOPPED", "no-stopped-line", F, "R-1", stopped=False)
C("F5-STOP-TRACEBACK", "clean-logs", P, "R-1")
N("F5-STOP-TRACEBACK", "traceback", F, "R-1", traceback=True)
C("F5-STOP-FORCEDKILL", "graceful", P, "R-1")
N("F5-STOP-FORCEDKILL", "forced-kill", F, "R-1", forced=True)

# C2: restart precedence and every start guard ("stop appFAIL" is a nonzero stop exit).
C("F5-RESTART-CARRY-FAIL", "stop-pass-start-pass", P, "R-1")
N("F5-RESTART-CARRY-FAIL", "stop-fail-start-pass", F, "R-1", stop_exit=1)
C("F5-RESTART-MISSING", "complete-start-leg", F, "R-1", stop_exit=1)
N("F5-RESTART-MISSING", "start-leg-absent", B(), "R-1", stop_exit=1, h={"receipt": keep_legs(1)})
N("F5-RESTART-MISSING", "start-evidence-missing", B(), "R-1", stop_exit=1,
  h={"receipt": sv(("legs", 1, "evidence"), {})})
C("F5-RESTART-LIE", "truthful-start-and-parent", F, "R-1", stop_exit=1)
N("F5-RESTART-LIE", "start-leg-lies", B(), "R-1", stop_exit=1,
  h={"receipt": sv(("legs", 1, "decision"), "FAILED", ("legs", 1, "failure_kind"), "app")})
N("F5-RESTART-LIE", "parent-lies", B(), "R-1", stop_exit=1, h={"receipt": AS_DONE})
C("F5-RESTART-HOST-START", "independent-valid-chain", P, "R-1")
C("F5-RESTART-HOST-START", "host-stop-no-second-leg-blocked", B(), "R-1", stop_exit=1,
  h={"receipt": both(STOP_HOST, AS_HOST, keep_legs(1))})
N("F5-RESTART-HOST-START", "host-stop-then-start-parent-host", B(), "R-1", stop_exit=1,
  h={"receipt": both(STOP_HOST, AS_HOST)})
N("F5-RESTART-HOST-START", "host-stop-then-start-parent-app", B(), "R-1", stop_exit=1, h={"receipt": STOP_HOST})
C("F5-RESTART-REFUSED-START", "valid-permitted-chain", P, "R-1")
C("F5-RESTART-REFUSED-START", "refused-no-second-leg-blocked", B(), "R-1",
  h={"receipt": both(STOP_REFUSED, keep_legs(1))})
N("F5-RESTART-REFUSED-START", "refused-stop-then-start", B(), "R-1", h={"receipt": STOP_REFUSED})
C("F5-RESTART-IDS-STOPPED", "both-ids-stopped", F, "R-1", stop_exit=1)
N("F5-RESTART-IDS-STOPPED", "app-not-stopped", B(), "R-1", stop_exit=1, h={"before-app": RUNNING})
N("F5-RESTART-IDS-STOPPED", "forwarder-not-stopped", B(), "R-1", stop_exit=1, h={"before-forwarder": RUNNING})
C("F5-RESTART-DRIFT", "no-drift", F, "R-1", stop_exit=1)
N("F5-RESTART-DRIFT", "image-drift-before-start", B(), "R-1", stop_exit=1,
  h={"before-app": sv(("runtime", "image_id"), OTHER_IMAGE)})
C("F5-RESTART-NOT-ARMED", "still-armed", F, "R-1", stop_exit=1)
N("F5-RESTART-NOT-ARMED", "start-before-window", B(), "R-1", stop_exit=1, window_start="3700")
C("F5-RESTART-TTL", "before-ttl", F, "R-1", stop_exit=1)
# This N has receipt-expiry/row/precedence credit (_common); app-start TTL is
# defense-in-depth, with no separately isolated guard credit from this case.
N("F5-RESTART-TTL", "start-after-ttl", B(), "R-1", stop_exit=1, window_start=str(3602 - 28800), req_expires="3602")
C("F5-RESTART-REPAIR", "exactly-one-start", P, "R-1")
N("F5-RESTART-REPAIR", "second-start-leg", B(), "R-1", h={"receipt": third_leg})
N("F5-RESTART-REPAIR", "second-docker-start", B(), "R-1", h={"runs": second_start})
C("F5-RESTART-EXIT", "parent-equals-stop-start-null", P, "R-1")
N("F5-RESTART-EXIT", "parent-differs-from-stop", B(), "R-1", h={"receipt": sv("exit_code", 1)})
N("F5-RESTART-EXIT", "start-leg-non-null", B(), "R-1", h={"receipt": sv(("legs", 1, "exit_code"), 0)})

# C3: QA's exact TD-1 controls.
C("F5-TD-MISS-30", "miss-30.001-30.0014", F, f200=None, elapsed="30.001", observed="30.0014")
C("F5-TD-MISS-30", "timely-health", P)
N("F5-TD-MISS-30", "miss-30.000-30.0004", F, f200=None, elapsed="30.000", observed="30.0004")
C("F5-TD-IN-TIME", "first200-29.998-observation-29.999", P, f200="29.998", reported="29.9985", observed="29.999",
  elapsed="29.9992")
N("F5-TD-IN-TIME", "first200-29.999-observation-30.000", P, f200="29.999", reported="29.9995", observed="30.000",
  elapsed="30.0002")
C("F5-TD-MISS-STRADDLE", "miss-30.000-30.0004", F, f200=None, elapsed="30.000", observed="30.0004")
N("F5-TD-MISS-STRADDLE", "miss-29.9996-30.0004", B(), f200=None, elapsed="29.9996", observed="30.0004")
C("F5-TD-HEALTH-STRADDLE", "first200-30.000-reported-29.9995", P, f200="30.000", reported="29.9995")
N("F5-TD-HEALTH-STRADDLE", "first200-29.9996-reported-30.0004", B(), f200="29.9996", reported="30.0004")
C("F5-TD-OBS-NOT-DEADLINE", "observation-exactly-30.000", P, f200="30.000", reported="30.000", observed="30.000",
  elapsed="30.000")
N("F5-TD-OBS-NOT-DEADLINE", "observation-30.000-elapsed-30.0008", P, f200="30.000", reported="30.000",
  observed="30.000", elapsed="30.0008")
C("F5-TD-ONE-SIDED-LOW", "reported-9.4990", P, "R-1", daemon="9.5000", span="9.6000", reported_stop="9.4990")
N("F5-TD-ONE-SIDED-LOW", "reported-9.4989", B(), "R-1", daemon="9.5000", span="9.6000", reported_stop="9.4989")
C("F5-TD-ONE-SIDED-HIGH", "reported-9.6010", P, "R-1", daemon="9.5000", span="9.6000", reported_stop="9.6010")
N("F5-TD-ONE-SIDED-HIGH", "reported-9.6011", B(), "R-1", daemon="9.5000", span="9.6000", reported_stop="9.6011")
C("F5-TD-STOP-STRADDLE", "clean-10.0000", P, "R-1", daemon="10.0000", span="10.0005", reported_stop="10.0000")
C("F5-TD-STOP-STRADDLE", "contrary-both-over", F, "R-1", daemon="10.0004", span="10.0010",
  reported_stop="10.0004")
N("F5-TD-STOP-STRADDLE", "a-daemon-9.9996-reported-10.0004", B(), "R-1", daemon="9.9996", span="10.0010",
  reported_stop="10.0004")
N("F5-TD-STOP-STRADDLE", "b-daemon-10.0004-reported-9.9999", B(), "R-1", daemon="10.0004", span="10.0010",
  reported_stop="9.9999")
C("F5-TD-WITHIN10", "agreement-at-10.000", P, "R-1", daemon="10.000", span="10.200")
N("F5-TD-WITHIN10", "within-10s-lies-at-10.000", B(), "R-1", daemon="10.000", span="10.200",
  h={"receipt": sv(("legs", 0, "evidence", "within_10s"), False)})
C("F5-TD-SAME-MEASURE", "exact-decimal-equality", P)
N("F5-TD-SAME-MEASURE", "observation-elapsed-differs", B(), obs_elapsed="1.0501")
C("F5-TD-OVER-BAND", "elapsed-band-exactly-1ms", P, observed="1.050", elapsed="1.051")
C("F5-TD-OVER-BAND", "reported-band-exactly-1ms", P, reported="1.041")
N("F5-TD-OVER-BAND", "elapsed-over-1ms", B(), observed="1.050", elapsed="1.0511")
N("F5-TD-OVER-BAND", "reported-over-1ms", B(), reported="1.0411")
C("F5-TD-DECIMAL-1MS", "a-miss-both-30.001", F, f200=None, elapsed="30.001", observed="30.001")
C("F5-TD-DECIMAL-1MS", "b-late-both-30.002", F, f200="30.002", reported="30.002")
C("F5-TD-DECIMAL-1MS", "contrary-twin-both-30.000", P, f200="30.000", reported="30.000")
N("F5-TD-DECIMAL-1MS", "a-miss-elapsed-30.001-observed-30.000", F, f200=None, elapsed="30.001", observed="30.000")
N("F5-TD-DECIMAL-1MS", "b-late-30.001-reported-30.002", F, f200="30.001", reported="30.002")
N("F5-TD-DECIMAL-1MS", "contrary-30.000-reported-30.001", B(), f200="30.000", reported="30.001")
N("F5-TD-DECIMAL-1MS", "contrary-30.001-reported-30.000", B(), f200="30.001", reported="30.000")
C("F5-TD-JSON-TEXT", "raw-30.000", P, f200="30.000000", reported="30.000")
N("F5-TD-JSON-TEXT", "raw-30.0000000000000000001", B(), f200="30.000000", reported="30.0000000000000000001")
C("F5-TD-NUMBER-TYPE", "plain-numbers-start", P)
C("F5-TD-NUMBER-TYPE", "plain-numbers-stop", P, "R-1")
for _label, _bad in (("true", True), ("false", False), ("string", "1.040"), ("null", None)):
    N("F5-TD-NUMBER-TYPE", f"seconds_to_health-{_label}", B(), h={"receipt": sv("seconds_to_health", _bad)})
    N("F5-TD-NUMBER-TYPE", f"health_elapsed_seconds-{_label}", B(), h={"receipt": sv("health_elapsed_seconds", _bad)})
    N("F5-TD-NUMBER-TYPE", f"observation-elapsed_seconds-{_label}", B(),
      h={"receipt": sv(("health_observation", "elapsed_seconds"), _bad)})
    N("F5-TD-NUMBER-TYPE", f"seconds_to_exit-{_label}", B(), "R-1",
      h={"receipt": sv(("legs", 0, "evidence", "seconds_to_exit"), _bad)})
C("F5-TD-OFFSET", "equivalent-offsets", P,
  h={"receipt": both(tv(("health_at",), to_utc), tv(("health_observation", "observed_until"), to_utc))})
C("F5-TD-OFFSET", "all-utc-twin", P, h={"receipt": all_utc})
for _label, _change in (("naive", lambda s: s[:-6]), ("plus-24", lambda s: s[:-6] + "+24:00"),
                        ("malformed", lambda s: s[:-6] + "-0700")):
    N("F5-TD-OFFSET", f"start_sent_at-{_label}", B(), h={"receipt": tv(("start_sent_at",), _change)})
    N("F5-TD-OFFSET", f"health_at-{_label}", B(), h={"receipt": tv(("health_at",), _change)})
    N("F5-TD-OFFSET", f"observed_until-{_label}", B(),
      h={"receipt": tv(("health_observation", "observed_until"), _change)})
    N("F5-TD-OFFSET", f"signal_sent_at-{_label}", B(), "R-1",
      h={"receipt": tv(("legs", 0, "evidence", "signal_sent_at"), _change)})
    N("F5-TD-OFFSET", f"exited_at-{_label}", B(), "R-1",
      h={"receipt": tv(("legs", 0, "evidence", "exited_at"), _change)})
    N("F5-TD-OFFSET", f"ended_at-{_label}", B(), "D-1", h={"receipt": tv(("ended_at",), _change)})

# C4: truth, prior chain, Host, cadence, E16, crash and unsupported predicates.
C("F5-TRUTH-DONE", "truthful-failed-app", F, "D-1", env_edges=ENV_T)
N("F5-TRUTH-DONE", "done-despite-env-failure", B(), "D-1", env_edges=ENV_T, h={"receipt": AS_DONE})
N("F5-TRUTH-DONE", "done-despite-start-miss", B(), f200=None, h={"receipt": AS_DONE})
C("F5-TRUTH-FAILED", "clean-done", P, "D-1")
N("F5-TRUTH-FAILED", "crash-failed-app-without-failure", B(), "D-1", h={"receipt": AS_FAILED})
N("F5-TRUTH-FAILED", "start-failed-app-without-failure", B(), h={"receipt": AS_FAILED})
C("F5-TRUTH-KIND", "exact-truthful-kind", F, "D-1", env_edges=ENV_T)
N("F5-TRUTH-KIND", "app-swapped-to-host", B(), "D-1", env_edges=ENV_T, h={"receipt": sv("failure_kind", "host")})
N("F5-TRUTH-KIND", "app-swapped-to-null", B(), "D-1", env_edges=ENV_T, h={"receipt": sv("failure_kind", None)})
N("F5-TRUTH-KIND", "null-swapped-to-app", B(), "D-1", h={"receipt": sv("failure_kind", "app")})
C("F5-MATCHES-BEFORE", "before-true-echoed", P)
C("F5-MATCHES-BEFORE", "before-false-echoed", F, env_edges=("before-app",))
N("F5-MATCHES-BEFORE", "before-false-lie", B(),
  h={"receipt": sv(("identity_evidence", "app", "before_matches_creation"), False)})
N("F5-MATCHES-BEFORE", "before-true-lie", B(), env_edges=("before-app",),
  h={"receipt": sv(("identity_evidence", "app", "before_matches_creation"), True)})
C("F5-MATCHES-AFTER", "after-true-echoed", P)
C("F5-MATCHES-AFTER", "after-false-echoed", F, env_edges=("after-app",))
N("F5-MATCHES-AFTER", "after-false-lie", B(),
  h={"receipt": sv(("identity_evidence", "forwarder", "after_matches_creation"), False)})
N("F5-MATCHES-AFTER", "after-true-lie", B(), env_edges=("after-app",),
  h={"receipt": sv(("identity_evidence", "app", "after_matches_creation"), True)})
C("F5-PRIOR-ENV-CARRY", "env-true-prior-clean-start", P)
N("F5-PRIOR-ENV-CARRY", "env-false-prior-clean-start", F, env_edges=ENV_PRIOR)
C("F5-PRIOR-ORIGIN", "complete-physical-137-prior", F, env_edges=ENV_PRIOR)
N("F5-PRIOR-ORIGIN", "origin-refused-false", B(), env_edges=ENV_PRIOR, h={"prior": sv("origin_refused", False)})
N("F5-PRIOR-ORIGIN", "origin-refused-absent", B(), env_edges=ENV_PRIOR, h={"prior": dl("origin_refused")})
C("F5-PRIOR-STOP-INSPECT", "complete-terminal-prior", F, env_edges=ENV_PRIOR)
N("F5-PRIOR-STOP-INSPECT", "stop-inspect-null", B(), env_edges=ENV_PRIOR, h={"prior": sv("stop_inspect", None)})
N("F5-PRIOR-STOP-INSPECT", "stop-inspect-absent", B(), env_edges=ENV_PRIOR, h={"prior": dl("stop_inspect")})
C("F5-PRIOR-ROW-WRITER", "bound-checker-row-writer", P)
C("F5-PRIOR-ROW-WRITER", "bound-api-check-row-writer", P, "API-D-5")
N("F5-PRIOR-ROW-WRITER", "wrong-row", B(), h={"prior_evidence": sv("row", "API-D-1")})
N("F5-PRIOR-ROW-WRITER", "wrong-writer", B(), h={"prior_evidence": sv("writer", "api-check")})
C("F5-PRIOR-RAW-HASH", "exact-raw-ref", P)
N("F5-PRIOR-RAW-HASH", "wrong-sha256", B(), h={"prior_evidence": sv("sha256", "0" * 64)})
N("F5-PRIOR-RAW-HASH", "wrong-length", B(), h={"prior_evidence": bump_length})
C("F5-PRIOR-WINDOW", "same-armed-window", P)
N("F5-PRIOR-WINDOW", "other-window-id", B(), h={"prior": sv("window_id", "p3-window-2")})
N("F5-PRIOR-WINDOW", "other-window-expiry", B(), h={"prior": sv("window_expires_at", iso(us("28801")))})
C("F5-PRIOR-BINDING", "full-project-binding", P)
C("F5-PRIOR-BINDING", "full-calibration-binding", P, route="calibration")
for _key, _bad in (("mode", "calibration"), ("project_id", "p4"), ("run_id", "run-2"), ("build_sums_sha256", "1" * 64),
                   ("kit_id", "kit-0"), ("kit_sha256", "0" * 64)):
    N("F5-PRIOR-BINDING", f"project-{_key}", B(BI), h={"prior": sv(("binding", _key), _bad)})
for _key, _bad in (("mode", "project"), ("manifest_sha256", "0" * 64), ("entry", "e2"), ("build_sums_sha256", "1" * 64),
                   ("calibration_run", "cal-run-2")):
    N("F5-PRIOR-BINDING", f"calibration-{_key}", B(BI), route="calibration", h={"prior": sv(("binding", _key), _bad)})
C("F5-PRIOR-IDENTITIES", "all-bound-identities", P)
N("F5-PRIOR-IDENTITIES", "app-container-id", B(), h={"prior": sv("app_container_id", "1" * 64)})
N("F5-PRIOR-IDENTITIES", "fwd-container-id", B(), h={"prior": sv("fwd_container_id", "2" * 64)})
N("F5-PRIOR-IDENTITIES", "terminal-container-id", B(), h={"prior-terminal": sv("container_id", FWD_ID)})
N("F5-PRIOR-IDENTITIES", "terminal-image-id", B(), h={"prior-terminal": sv(("runtime", "image_id"), OTHER_IMAGE)})
N("F5-PRIOR-IDENTITIES", "executor-sha256", B(), h={"prior": sv("executor_sha256", "3" * 64)})
N("F5-PRIOR-IDENTITIES", "controller-sha256", B(), h={"prior": sv("controller_sha256", "4" * 64)})
N("F5-PRIOR-IDENTITIES", "sums-sha256", B(), h={"prior": sv("sums_sha256", "5" * 64)})
C("F5-PRIOR-SEQ", "exact-echo-and-order", P)
N("F5-PRIOR-SEQ", "evidence-sequence-not-earlier", B(), h={"prior_evidence": sv("sequence", 2)})
N("F5-PRIOR-SEQ", "receipt-sequence-echo", B(), h={"prior": sv("sequence", 3, "expected_sequence", 4)})
N("F5-PRIOR-SEQ", "receipt-request-id-echo", B(), h={"prior": sv("request_id", V1_RID)})
N("F5-PRIOR-SEQ", "expected-sequence", B(), h={"prior": sv("expected_sequence", 5)})
N("F5-PRIOR-SEQ", "prior-ends-after-start-begins", B(),
  h={"prior": sv("ended_at", iso(us("3600.5")), "at", iso(us("3600.6")), "seen_at", iso(us("3600.7")))})
C("F5-PRIOR-ACTION", "complete-crash-137", P)
N("F5-PRIOR-ACTION", "exit-0-not-137", B(),
  h={"prior": sv("exit_code", 0), "prior-terminal": sv(("state", "exit_code"), 0)})
N("F5-PRIOR-ACTION", "signal-term", B(), h={"prior": sv("signal", "TERM")})
N("F5-PRIOR-ACTION", "operation-start", B(), h={"prior": sv("operation", "start", "host_action", "start")})
C("F5-PRIOR-SELECTION", "same-calibration-selection", P, route="calibration")
C("F5-PRIOR-SELECTION", "same-project-tuple", P)
N("F5-PRIOR-SELECTION", "calibration-entry", B(BI), route="calibration", h={"prior": sv(("binding", "entry"), "e2")})
N("F5-PRIOR-SELECTION", "calibration-manifest", B(BI), route="calibration",
  h={"prior": sv(("binding", "manifest_sha256"), "0" * 64)})
N("F5-PRIOR-SELECTION", "project-tuple", B(BI), h={"prior": sv(("binding", "project_id"), "p4", ("binding", "kit_id"),
                                                            "kit-0")})
C("F5-PRIOR-PATH", "controller-derived-rooted-ref", P)
N("F5-PRIOR-PATH", "extra-path-member", B(), h={"prior_evidence": sv("path", "/etc/passwd")})
N("F5-PRIOR-PATH", "unrooted-row-path", B(), h={"prior_evidence": sv("row", "../D-1")})
C("F5-HOST-FAULT", "truthful-app-fail", F, "D-1", env_edges=ENV_T)
C("F5-HOST-FAULT", "truthful-app-pass", P, "D-1")
N("F5-HOST-FAULT", "crash-failed-host", B(), "D-1", h={"receipt": AS_HOST})
N("F5-HOST-FAULT", "start-failed-host", B(), h={"receipt": AS_HOST})
C("F5-REFUSED", "admitted-done-offline-pass", P, "D-1")
N("F5-REFUSED", "refused", B(), "D-1", h={"receipt": sv("decision", "REFUSED", "failure_kind", None, "done", False,
                                                     "sequence_used", False, "expected_sequence", 1)})
C("F5-CADENCE-ZERO", "complete-measured-miss", F, f200=None)
N("F5-CADENCE-ZERO", "zero-probes", B(), f200=None, h={"probes": lambda probes, world: []})
C("F5-CADENCE-GAP", "complete-coverage", F, f200=None)
C("F5-CADENCE-GAP", "gap-exactly-750", F, f200=None, probe_step="0.760")
C("F5-CADENCE-GAP", "healthy-cadence", P)
N("F5-CADENCE-GAP", "first-probe-late", B(), f200=None, probe_start="1.600")
N("F5-CADENCE-GAP", "first-probe-before-forwarder-started", B(), f200=None, probe_start="0.700")
N("F5-CADENCE-GAP", "gap-over-750", B(), f200=None, probe_step="0.761")
N("F5-CADENCE-GAP", "deadline-coverage-missing", B(), f200=None, probe_until="29.000")
N("F5-CADENCE-GAP", "new-probe-at-deadline", B(), f200=None, h={"probes": extra_probe("30.000")})
N("F5-CADENCE-GAP", "serial-overlap", B(), f200=None, probe_len="0.600")
N("F5-CADENCE-GAP", "timeout-not-3s", B(), f200=None, h={"probes": sv((5, "params", "timeout_seconds"), 5)})
N("F5-CADENCE-GAP", "host-scheduling-gap", B(), f200=None, h={"probes": shift_from(10, 300_000)})
C("F5-CADENCE-FIRST200", "ordered-through-first200", P, f200="5.000")
C("F5-CADENCE-FIRST200", "late-response-kept-with-real-times", F, f200="30.400")
N("F5-CADENCE-FIRST200", "earlier-non200-omitted", B(), f200="5.000", h={"probes": drop_probe(3)})
N("F5-CADENCE-FIRST200", "resampled-after-first200", B(), f200="5.000", h={"probes": resample})
N("F5-CADENCE-FIRST200", "late-response-clamped", B(), f200="30.400", h={"probes": clamp_late})
N("F5-CADENCE-FIRST200", "late-response-synthetic-null", B(), f200="30.400", h={"probes": synthetic_null})
C("F5-AUDIT-REF", "exact-sibling-audit", P)
N("F5-AUDIT-REF", "wrong-filename", B(), h={"audit_ref": sv("path", f"audit-{RID}-3.json")})
N("F5-AUDIT-REF", "rooted-path", B(), h={"audit_ref": sv("path", W(lambda w: f"{w.host}/audit-{RID}-2.json"))})
N("F5-AUDIT-REF", "wrong-sha256", B(), h={"audit_ref": sv("sha256", "0" * 64)})
N("F5-AUDIT-REF", "wrong-length", B(), h={"audit_ref": bump_length})
C("F5-HOST-LITERAL", "exact-literal-host", P)
N("F5-HOST-LITERAL", "probe-host-wrong-with-200", B(), h={"probes": sv((-1, "params", "host"), "localhost:8970")})
N("F5-HOST-LITERAL", "observation-host-wrong", B(),
  h={"receipt": sv(("health_observation", "host"), "localhost:8970")})
C("F5-E16-400", "allowed-200", P)
N("F5-E16-400", "status-400", B(), h={"probes": sv((-1, "result", "status"), 400)})
C("F5-CRASH-LISTENER", "complete-witnesses", P, "D-1")
N("F5-CRASH-LISTENER", "listener-gone-false", B(), "D-1", h={"receipt": sv("listener_gone", False)})
N("F5-CRASH-LISTENER", "listener-gone-absent", B(), "D-1", h={"receipt": dl("listener_gone")})
C("F5-CRASH-ORIGIN", "complete-witnesses", P, "D-1")
N("F5-CRASH-ORIGIN", "origin-refused-false", B(), "D-1", h={"receipt": sv("origin_refused", False)})
N("F5-CRASH-ORIGIN", "origin-refused-absent", B(), "D-1", h={"receipt": dl("origin_refused")})
C("F5-CRASH-NONENV-APP", "done-137", P, "D-1")
N("F5-CRASH-NONENV-APP", "failed-app-listener-not-gone", B(), "D-1",
  h={"receipt": both(sv("listener_gone", False), AS_FAILED)})
N("F5-CRASH-NONENV-APP", "failed-app-without-env-cause", B(), "D-1", h={"receipt": AS_FAILED})
C("F5-CRASH-EXIT", "exact-137", P, "D-1")
N("F5-CRASH-EXIT", "exit-1", B(), "D-1", h={"receipt": sv("exit_code", 1), "terminal": sv(("state", "exit_code"), 1)})
N("F5-CRASH-EXIT", "exit-missing", B(), "D-1", h={"receipt": sv("exit_code", None)})
N("F5-CRASH-EXIT", "exit-143", B(), "D-1",
  h={"receipt": sv("exit_code", 143), "terminal": sv(("state", "exit_code"), 143)})
C("F5-CRASH-OOM", "observed-oom-false", P, "D-1")
N("F5-CRASH-OOM", "root-oom-alias", B(), "D-1", h={"receipt": sv("oom_killed", True)})
N("F5-CRASH-OOM", "terminal-oom-true", B(), "D-1", h={"terminal": sv(("state", "oom_killed"), True)})
C("F5-CRASH-TERMINAL", "exact-terminal-chain", P, "D-1")
N("F5-CRASH-TERMINAL", "terminal-missing", B(), "D-1", h={"receipt": sv("stop_inspect", None)})
N("F5-CRASH-TERMINAL", "terminal-after-leg-end", B(), "D-1", h={"terminal": sv("observed_at", iso(us("3001.6")))})
N("F5-CRASH-TERMINAL", "terminal-exit-time-differs", B(), "D-1",
  h={"terminal": sv(("state", "finished_at"), iso(us("3001.05")))})
N("F5-CRASH-TERMINAL", "terminal-identity", B(), "D-1", h={"terminal": sv("container_id", FWD_ID)})
C("F5-CRASH-NONENV", "env-only-false", F, "D-1", env_edges=ENV_T)
N("F5-CRASH-NONENV", "physical-listener", B(), "D-1", env_edges=ENV_T, h={"receipt": sv("listener_gone", False)})
N("F5-CRASH-NONENV", "immutable-image", B(), "D-1", env_edges=ENV_T,
  h={"terminal": sv(("runtime", "image_id"), OTHER_IMAGE)})
N("F5-CRASH-NONENV", "source-executor", B(), "D-1", env_edges=ENV_T, h={"receipt": sv("executor_sha256", "3" * 64)})
N("F5-CRASH-NONENV", "identity-app-container", B(), "D-1", env_edges=ENV_T,
  h={"receipt": sv("app_container_id", "1" * 64)})
N("F5-CRASH-NONENV", "chronology-kill-after-exit", B(), "D-1", env_edges=ENV_T,
  h={"receipt": sv("kill_sent_at", iso(us("3001.15")))})
C("F5-STANDALONE-STOP", "graceful-evidence-as-restart-leg", P, "R-1")
N("F5-STANDALONE-STOP", "stop-graceful-request", B(SM), "R-1",
  h={"request": sv("operation", "stop-graceful", "host_action", "stop-graceful")})
N("F5-STANDALONE-STOP", "stop-request", B(SM), "R-1", h={"request": sv("operation", "stop", "host_action", "stop")})
C("F5-ENGINE-UNSUPPORTED", "supported-crash", P, "D-1")
C("F5-ENGINE-UNSUPPORTED", "supported-start", P)
C("F5-ENGINE-UNSUPPORTED", "supported-restart", P, "R-1")
N("F5-ENGINE-UNSUPPORTED", "engine-image-wimg", B(SM), "D-1",
  h={"request": sv("row", "W-IMG", "operation", "engine-image", "host_action", "engine-image")})
N("F5-ENGINE-UNSUPPORTED", "launch-cases-s5", B(SM), "D-1",
  h={"request": sv("row", "HOST-L", "operation", "launch-cases", "host_action", "launch-cases")})
N("F5-ENGINE-UNSUPPORTED", "list", B(SM), "D-1", h={"request": sv("row", "LIST", "operation", "list",
                                                                "host_action", "list")})
N("F5-ENGINE-UNSUPPORTED", "target2-operation-binding", B(SM), "D-1",
  h={"request": sv("operation_binding", {"schema": "ops-host-target/2"})})
N("F5-ENGINE-UNSUPPORTED", "request2", B(SM), "D-1", h={"request": sv("schema", "ops-host-request/2")})
N("F5-ENGINE-UNSUPPORTED", "receipt3-format", B(SM), "D-1", h={"request": sv("receipt_format", "ops-host-receipt/3")})
N("F5-ENGINE-UNSUPPORTED", "receipt3-document", B(SM), "D-1", h={"receipt": sv("schema", "ops-host-receipt/3")})
C("F5-START-FLAT", "exact-flat-root", P)
N("F5-START-FLAT", "root-stop-inspect", B(), h={"receipt": sv("stop_inspect", W(lambda w: w.creation["app"]))})
N("F5-START-FLAT", "root-origin-answer", B(), h={"receipt": sv("origin_answer", {"status": 200})})
N("F5-START-FLAT", "root-alias-answered-at", B(), h={"receipt": sv("answered_at", iso(us("3601")))})
C("F5-UUID-INVALID", "version-4", P)
C("F5-UUID-INVALID", "non-v4-version-1", P, rid=V1_RID)
N("F5-UUID-INVALID", "uppercase", B(), rid=RID.upper())
N("F5-UUID-INVALID", "no-hyphens", B(), rid=RID.replace("-", ""))
N("F5-UUID-INVALID", "invalid-character", B(), rid=RID[:-1] + "z")

# Retained protocol, bound edges, complete equality.
C("F5-PROTOCOL", "valid-crash", P, "D-1")
C("F5-PROTOCOL", "valid-calibration-crash", P, "D-1", route="calibration")
C("F5-PROTOCOL", "valid-ld1-app-copy-changes", P, "D-1", h={"receipt": app_copy_changes(False)})
N("F5-PROTOCOL", "receipt-row-echo", B(), "D-1", h={"receipt": sv("row", "API-D-1")})
N("F5-PROTOCOL", "receipt-writer-echo", B(), "D-1", h={"receipt": sv("writer", "api-check")})
N("F5-PROTOCOL", "expected-sequence", B(), "D-1", h={"receipt": sv("expected_sequence", 3)})
N("F5-PROTOCOL", "sequence-unused-but-done", B(), "D-1", h={"receipt": sv("sequence_used", False)})
N("F5-PROTOCOL", "ttl-minutes", B(), "D-1", h={"receipt": sv("window_ttl_minutes", 481)})
N("F5-PROTOCOL", "ttl-expires-at", B(), "D-1", h={"receipt": sv("window_expires_at", iso(us("28801")))})
N("F5-PROTOCOL", "late-receipt", B(), "D-1", req_expires="3001.55")
N("F5-PROTOCOL", "receipt-ref-path", B(), "D-1", h={"receipt_ref": sv("path", W(lambda w: f"{w.host}/D-5.json"))})
N("F5-PROTOCOL", "receipt-ref-sha256", B(), "D-1", h={"receipt_ref": sv("sha256", "0" * 64)})
N("F5-PROTOCOL", "receipt-ref-length", B(), "D-1", h={"receipt_ref": bump_length})
N("F5-PROTOCOL", "envelope-lane", B(), "D-1", h={"receipt": sv("lane", "forwarder")})
N("F5-PROTOCOL", "envelope-controller", B(), "D-1", h={"receipt": sv("controller_sha256", "0" * 64)})
N("F5-PROTOCOL", "envelope-request-sha256", B(), "D-1", h={"receipt": sv("request_sha256", "0" * 64)})
N("F5-PROTOCOL", "ld1-app-copy-changes-truncated", B(), "D-1", h={"receipt": app_copy_changes(True)})
N("F5-PROTOCOL", "listing-tree-sha256", B(), "D-1", h={"listing-exit": sv("tree_sha256", "0" * 64)})
N("F5-PROTOCOL", "s4-security-receipt", LOAD(BI), "D-1", route="calibration",
  h={"window": sv("security_receipt_sha256", "e" * 64)})
N("F5-PROTOCOL", "request-binding", B(BI), "D-1", h={"request": sv(("binding", "run_id"), "run-2")})
N("F5-PROTOCOL", "request-window-id", B(), "D-1", h={"request": sv("window_id", "p3-window-2")})
N("F5-PROTOCOL", "request-schema", B(SI), "D-1", h={"request": sv("schema", "ops-host-request/0")})
N("F5-PROTOCOL", "receipt-schema", B(SI), "D-1", h={"receipt": sv("schema", "ops-host-receipt/0")})
EDGES = (("creation", "creation-app", "D-1"), ("before", "before-app", "D-5"), ("after", "after-app", "D-5"),
         ("terminal", "terminal", "D-1"), ("prior", "prior-terminal", "D-5"), ("restart-leg", "terminal", "R-1"))
C("F5-EDGE-VERSION", "v2-23-crash-edges", P, "D-1")
C("F5-EDGE-VERSION", "v2-23-start-edges", P)
C("F5-EDGE-VERSION", "v2-23-restart-edges", P, "R-1")
C("F5-EDGE-IDENTITY", "exact-crash-identities", P, "D-1")
C("F5-EDGE-IDENTITY", "exact-start-identities", P)
C("F5-EDGE-IDENTITY", "exact-restart-identities", P, "R-1")
for _label, _stem, _row in EDGES:
    N("F5-EDGE-VERSION", f"{_label}-v1-23", B(SI), _row, h={_stem: sv("schema", INSPECT1)})
    N("F5-EDGE-VERSION", f"{_label}-v2-22", B(), _row, h={_stem: dl(("runtime", "image_env"))})
    N("F5-EDGE-IDENTITY", f"{_label}-window-id", B(), _row, h={_stem: sv("window_id", "p3-window-2")})
    N("F5-EDGE-IDENTITY", f"{_label}-container-id", B(), _row, h={_stem: sv("container_id", "7" * 64)})
N("F5-EDGE-VERSION", "creation-v1-22-mixed", B(SI), "D-1",
  h={"creation-app": both(sv("schema", INSPECT1), dl(("runtime", "image_env")))})
N("F5-EDGE-IDENTITY", "identity-creation-record", B(),
  h={"receipt": sv(("identity_evidence", "app", "creation_record"), W(lambda w: w.creation["forwarder"]))})
N("F5-EDGE-IDENTITY", "identity-window-sha256", B(), h={"receipt": sv(("identity_evidence", "window_sha256"), "0" * 64)})
N("F5-EDGE-IDENTITY", "identity-container-id", B(),
  h={"receipt": sv(("identity_evidence", "forwarder", "container_id"), APP_ID)})
C("F5-EDGE-ENV", "exact-start-arrays", P)
C("F5-EDGE-ENV", "exact-crash-arrays", P, "D-1")
for _stem, _row in (("before-app", "D-5"), ("before-forwarder", "D-5"), ("after-app", "D-5"),
                    ("after-forwarder", "D-5"), ("terminal", "D-1"), ("prior-terminal", "D-5"), ("terminal", "R-1")):
    N("F5-EDGE-ENV", f"{_row}-{_stem}-env-differs", F, _row, env_edges=(_stem,))
N("F5-EDGE-ENV", "env-duplicate-token", F, h={"after-app": dup_env, "receipt": both(
    AS_FAILED, sv(("identity_evidence", "app", "after_matches_creation"), False))})
N("F5-EDGE-ENV", "env-order", F, h={"after-app": reorder_env, "receipt": both(
    AS_FAILED, sv(("identity_evidence", "app", "after_matches_creation"), False))})
N("F5-EDGE-ENV", "env-malformed", B(), h={"after-app": sv(("runtime", "env", 0), "NOEQUALSSIGN")})
N("F5-EDGE-ENV", "env-missing", B(), h={"after-app": dl(("runtime", "env"))})
N("F5-EDGE-ENV", "env-lying-receipt", B(), env_edges=("after-app",), h={"receipt": AS_DONE})
N("F5-EDGE-ENV", "env-unbound-creation-app", B(), env_edges=("creation-app",))
N("F5-EDGE-ENV", "env-unbound-creation-forwarder", B(), env_edges=("creation-forwarder",))
DRIFT = {
    "image_id": OTHER_IMAGE,
    "command": ["python3", "/app/other.py"],
    "workdir": "/srv",
    "user": "1001:1001",
    "mounts": [],
    "tmpfs": {"/tmp": "rw,size=32m"},
    "read_only_root": False,
    "cap_drop": [],
    "cap_add": ["NET_ADMIN"],
    "security_options": [],
    "privileged": True,
    "devices": [{"path_on_host": "/dev/fuse", "path_in_container": "/dev/fuse", "cgroup_permissions": "rwm"}],
    "pid_mode": "host",
    "ipc_mode": "shareable",
    "uts_mode": "host",
    "init": False,
    "limits": {"pids": 128, "memory_bytes": 536870912, "nano_cpus": 1000000000},
    "restart_policy": {"name": "always", "maximum_retry_count": 0},
    "ports": [{"host_ip": ADDRESS, "host_port": 8971, "container_port": 8000, "protocol": "tcp"}],
    "networks": [{"network_id": NET_INNER, "network_name": "inner-e1", "aliases": ["other"]}],
    "data_bind": W(lambda w: {"source": w.data_dir, "destination": "/data", "rw": False}),
    "image_env": IMAGE_ENV_APP + ["TZ=UTC"],
}
C("F5-RUNTIME-EQUALITY", "complete-runtime-equals-creation", P)
for _member, _bad in DRIFT.items():
    N("F5-RUNTIME-EQUALITY", f"after-app-{_member}", B(), h={"after-app": sv(("runtime", _member), _bad)})

# HOME additions (A6.1 chronology, for QA's R5 receiving).
C("F5-LEG-ORDER-START", "first-start-finished-sentinel", P, fwd_first=True)
C("F5-LEG-ORDER-START", "restart-previous-exit-before-start", P, "R-1")
N("F5-LEG-ORDER-START", "standalone-finished-after-started", B(), h={"after-app": finish_after_start})
N("F5-LEG-ORDER-START", "restart-finished-after-started", B(), "R-1", h={"after-app": finish_after_start})
C("F5-LEG-ORDER-STOP", "restart-stop-real-exit", P, "R-1")
C("F5-LEG-ORDER-STOP", "crash-real-exit", P, "D-1")
N("F5-LEG-ORDER-STOP", "restart-stop-finished-before-started", B(), "R-1", h={"terminal": start_after_finish})
N("F5-LEG-ORDER-STOP", "crash-finished-sentinel", B(), "D-1", h={"terminal": sv(("state", "finished_at"), ZERO)})
N("F5-LEG-ORDER-STOP", "restart-stop-finished-sentinel", B(), "R-1",
  h={"terminal": sv(("state", "finished_at"), ZERO)})
C("F5-SENTINEL-NO-EVENT", "first-start-never-exited", P, fwd_first=True)
N("F5-SENTINEL-NO-EVENT", "running-started-sentinel", B(), h={"after-app": sv(("state", "started_at"), ZERO)})


@pytest.mark.parametrize("case", CASES, ids=[f"{c.fid}:{c.kind}:{c.name}" for c in CASES])
def test_pair(case: Case, tmp_path: Path) -> None:
    world = World(tmp_path, case.row, route=case.route, hooks=case.hooks, **case.knobs)
    assert run(world) == case.expect


# ---------------------------------------------------------------------------
# Pairs that need their own test (detectors, constructors, bites).

def test_eleven_code_pin() -> None:
    assert p5.CODES == CODES and len(set(CODES)) == 11 and R4.REFUSAL_CODES == CODES
    for code in CODES:
        exc = p5.TargetRefused(code)
        assert exc.args == (code,) and str(exc) == code and exc.code == code and code in repr(exc)
    with pytest.raises(TypeError):
        p5.TargetRefused("TARGET_OTHER")


@pytest.mark.parametrize("code", CODES)
def test_code_verdict_n(code: str) -> None:
    for verdict in ("PASS", "FAIL"):
        with pytest.raises(TypeError):
            p5.UntrustedAssessment(trust="UNTRUSTED", verdict=verdict, code=code, identities=())


@pytest.mark.parametrize("code", CODES)
def test_code_verdict_c(code: str) -> None:
    assert p5.UntrustedAssessment(trust="UNTRUSTED", verdict="BLOCKED", code=code, identities=()).code == code
    assert p5.UntrustedAssessment(trust="UNTRUSTED", verdict="PASS", code="NONE", identities=()).code == "NONE"
    with pytest.raises(TypeError):
        p5.UntrustedAssessment(trust="UNTRUSTED", verdict="BLOCKED", code="NONE", identities=())


def test_native_nonconversion_c(tmp_path: Path) -> None:
    world = World(tmp_path)
    window = load(world)
    assert window.trust == "UNTRUSTED" and window.target.trust == "UNTRUSTED"
    result = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=window, now=NOW)
    assert (result.trust, result.verdict, result.code) == ("UNTRUSTED", "PASS", "NONE")
    assert ("window", world.window_sha) in result.identities
    assert p5.UNRESOLVED_NATIVE_CHECKS == R2.REQUIRED_NATIVE_CHECKS + (
        "NATIVE_PRIOR_RECEIPT_ISSUER_SCOPE_AND_JOB",
        "ACTUAL_INSPECT2_PRODUCER_VALIDATOR_CORPUS_AND_CALLER_COMPATIBILITY",
        "COUNTED_ADMISSION_AND_ROW_RESULT")
    assert len(R2.REQUIRED_NATIVE_CHECKS) == 5


def test_native_nonconversion_n(tmp_path: Path) -> None:
    world = World(tmp_path)
    window = load(world)
    for bare in ({"trust": "VERIFIED", "window": dict(world.window)}, window.target):
        result = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=bare, now=NOW)
        assert (result.verdict, result.code) == B(CM)
    naive = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=window, now=NOW.replace(tzinfo=None))
    assert (naive.verdict, naive.code) == B(CM)
    for trust, inner, target in (("VERIFIED", window.window, window.target),
                                 ("UNTRUSTED", dict(window.window), window.target),
                                 ("UNTRUSTED", window.window, {"trust": "VERIFIED"})):
        with pytest.raises(TypeError):
            p5.CandidateWindow(trust=trust, window=inner, target=target, reads=window.reads)
    with pytest.raises(TypeError):
        p5.UntrustedAssessment(trust="VERIFIED", verdict="PASS", code="NONE", identities=())
    with pytest.raises(AttributeError):
        window.trust = "VERIFIED"


def record_reads(monkeypatch: pytest.MonkeyPatch) -> list:
    """Every R1 observation, R2's load and the window cross-check, in order."""
    log: list = []
    for name in ("read_private_file", "read_release_file"):
        real = getattr(R1, name)

        def wrapper(root: str, ref_: dict, *, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            log.append((_name, root, ref_.get("path") if isinstance(ref_, dict) else None))
            return _real(root, ref_, **kw)
        monkeypatch.setattr(R1, name, wrapper)
    for name, mark in (("_load_candidate", "R2"), ("_cross_check", "cross")):
        real = getattr(p5, name)

        def marked(*args: Any, _real: Any = real, _mark: str = mark, **kw: Any) -> Any:
            if _mark == "R2":
                log.append((_mark,))
            out = _real(*args, **kw)
            if _mark == "cross":
                log.append((_mark,))
            return out
        monkeypatch.setattr(p5, name, marked)
    return log


def window_first(log: list, world: World) -> bool:
    """The suite's ordering check: the window FIRST, then R2, then cross-checks, then any host evidence."""
    if not log or log[0] != ("read_private_file", str(world.win), "WINDOW.json"):
        return False
    if ("R2",) not in log or log.index(("R2",)) != 1 or ("cross",) not in log:
        return False
    host = [i for i, item in enumerate(log) if item[0] == "read_private_file" and item[1].startswith(str(world.host))]
    return bool(host) and min(host) > log.index(("cross",))


def test_window_first_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path)
    log = record_reads(monkeypatch)
    assert run(world) == P
    assert window_first(log, world)


def test_window_first_n(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path)
    log = record_reads(monkeypatch)
    real = p5._read_window

    def other_first(ref_: dict, uid: int) -> Any:
        R1.read_private_file(str(world.qa), {"path": "PUBLICATION.json", "sha256": sha(world.publication_raw),
                                             "byte_length": len(world.publication_raw)}, uid=uid, cap=1 << 20)
        return real(ref_, uid)
    monkeypatch.setattr(p5, "_read_window", other_first)
    run(world)
    assert not window_first(log, world)


ALLOWED_IMPORTS = {"__future__", "hashlib", "json", "re", "sys", "uuid", "collections.abc", "dataclasses", "datetime",
                   "decimal", "pathlib", "types", "typing", "ops_host_binding", "ops_host_env", "ops_host_inspect"}
FORBIDDEN_NAMES = {"open", "float", "eval", "exec", "compile", "__import__", "os", "subprocess", "socket"}
FORBIDDEN_ATTRS = {"stat", "lstat", "fstat", "read_bytes", "read_text", "write_bytes", "write_text", "system", "popen",
                   "judge_receipt", "Evidence", "_audit", "_prior_crash", "inspect"}


def findings(source: str) -> list:
    """Static scan: imports, direct file/stat/float use and legacy entry points."""
    out = []
    for item in ast.walk(ast.parse(source)):
        if isinstance(item, ast.Import):
            out += [f"import {alias.name}" for alias in item.names if alias.name not in ALLOWED_IMPORTS]
        elif isinstance(item, ast.ImportFrom) and item.module not in ALLOWED_IMPORTS:
            out.append(f"from {item.module}")
        elif isinstance(item, ast.Name) and item.id in FORBIDDEN_NAMES:
            out.append(f"name {item.id}")
        elif isinstance(item, ast.Attribute) and item.attr in FORBIDDEN_ATTRS:
            out.append(f"attribute {item.attr}")
    return out


SOURCE = MODULE_PATH.read_text()
READ_WINDOW = "def _read_window(ref: dict, uid: int) -> Any:\n"


def test_window_first_static_c() -> None:
    assert findings(SOURCE) == []
    assert SOURCE.count(READ_WINDOW) == 1


@pytest.mark.parametrize("body", ("    import os\n    os.stat(ref['path']).st_size\n",
                                  "    Path(ref['path']).read_bytes()\n",
                                  "    open(ref['path'], 'rb').read()\n"))
def test_window_first_static_n(body: str) -> None:
    mutated = SOURCE.replace(READ_WINDOW, READ_WINDOW + body)
    assert mutated != SOURCE and findings(mutated)


def test_helper_audit_c() -> None:
    """Fresh implementation: nothing imported from the legacy client (c537bed9)."""
    names = {alias.name for item in ast.walk(ast.parse(SOURCE)) if isinstance(item, ast.Import) for alias in item.names}
    modules = {item.module for item in ast.walk(ast.parse(SOURCE)) if isinstance(item, ast.ImportFrom)}
    assert "ops_host_client" not in names | modules and findings(SOURCE) == []


@pytest.mark.parametrize("line", ("from ops_host_client import judge_receipt\n", "import ops_host_client\n",
                                  "from ops_host_client import _audit, _prior_crash\n"))
def test_helper_audit_n(line: str) -> None:
    assert findings(SOURCE + "\n" + line)


def trap_module() -> types.ModuleType:
    """A deliberate legacy trap: records any use of the old read paths."""
    trap = types.ModuleType("ops_host_client")
    calls: list = []

    class Evidence:
        def __init__(self, *args: Any, **kw: Any) -> None:
            calls.append("Evidence")

        def inspect(self, *args: Any, **kw: Any) -> None:
            calls.append("Evidence.inspect")

    def recorder(name: str) -> Any:
        return lambda *args, **kw: calls.append(name)

    trap.Evidence = Evidence
    for name in ("judge_receipt", "_audit", "_prior_crash"):
        setattr(trap, name, recorder(name))
    trap.calls = calls
    return trap


def test_direct_read_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trap = trap_module()
    monkeypatch.setitem(sys.modules, "ops_host_client", trap)
    assert run(World(tmp_path / "start")) == P
    assert run(World(tmp_path / "restart", "R-1")) == P
    assert run(World(tmp_path / "crash", "D-1")) == P
    assert trap.calls == []


def test_direct_read_n(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trap = trap_module()
    monkeypatch.setitem(sys.modules, "ops_host_client", trap)
    real = p5._assess

    def legacy(judge: Any, request_raw: Any, receipt_ref: Any) -> Any:
        old = sys.modules["ops_host_client"]
        old.Evidence().inspect("app")
        old.judge_receipt(request_raw, receipt_ref)
        old._audit()
        old._prior_crash()
        return real(judge, request_raw, receipt_ref)
    monkeypatch.setattr(p5, "_assess", legacy)
    run(World(tmp_path))
    assert trap.calls == ["Evidence", "Evidence.inspect", "judge_receipt", "_audit", "_prior_crash"]


RECHECK_FILES = {"source": lambda w: w.ops / "ops-host/hostwin.py", "root": lambda w: w.qa / "PUBLICATION.json",
                 "window": lambda w: w.window_path, "kit": lambda w: w.kit / "app/server.py",
                 "subject": lambda w: w.rec / "subject-m01.bin"}


def drift(path: Path) -> None:
    raw, mode = path.read_bytes(), os.stat(path).st_mode & 0o7777
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0x01]))
    os.chmod(path, mode)


@pytest.mark.parametrize("boundary", ("load-complete", "receiving", "before-count"))
@pytest.mark.parametrize("kind", tuple(RECHECK_FILES))
def test_recheck_n(kind: str, boundary: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path)
    target = RECHECK_FILES[kind](world)
    seam = {"load-complete": "_load_candidate", "before-count": "_assess"}.get(boundary)
    if seam is not None:
        real = getattr(p5, seam)

        def drifted(*args: Any, **kw: Any) -> Any:
            out = real(*args, **kw)
            drift(target)
            return out
        monkeypatch.setattr(p5, seam, drifted)
    if boundary == "load-complete":
        assert run(world) == LOAD(SD)
        return
    window = load(world)
    if boundary == "receiving":
        drift(target)
    result = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=window, now=NOW)
    assert (result.verdict, result.code) == B(SD)


def test_recheck_c(tmp_path: Path) -> None:
    world = World(tmp_path)
    window = load(world)
    for _ in range(2):  # unchanged observations at every boundary, judged twice
        result = p5.judge_candidate_receipt(world.request_raw, world.receipt_ref, window=window, now=NOW)
        assert (result.verdict, result.code) == P


def worlds(tmp_path: Path, name: str, *args: Any, **kw: Any) -> Any:
    count = iter(range(100))
    return lambda: World(tmp_path / f"{name}{next(count)}", *args, **kw)


def test_bite_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = worlds(tmp_path, "n", "D-1", hooks={"creation-app": sv("schema", INSPECT1)})
    c = worlds(tmp_path, "c", "D-1")
    assert run(n()) == B(SI) and run(c()) == P
    monkeypatch.setattr(p5, "_decode_inspect", lambda raw, **kw: p5._freeze(json.loads(raw)))
    assert run(n()) == P  # the mixed-schema N loses its refusal
    assert run(c()) == P


def test_bite_carry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = worlds(tmp_path, "n", env_edges=ENV_PRIOR)
    c = worlds(tmp_path, "c")
    assert run(n()) == F and run(c()) == P
    monkeypatch.setattr(p5, "_carry_prior", lambda own, prior_failed: own)
    assert run(n()) == P
    assert run(c()) == P


def test_bite_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = worlds(tmp_path, "n", "R-1", stop_exit=1, hooks={"receipt": keep_legs(1)})
    c = worlds(tmp_path, "c", "R-1", stop_exit=1)
    assert run(n()) == B() and run(c()) == F

    real = p5._combine

    def fail_first(outcomes: list) -> tuple:
        """The bite: FAIL wins over BLOCKED."""
        if any(verdict == "FAIL" for verdict, _ in outcomes):
            return "FAIL", "NONE"
        return real(outcomes)
    monkeypatch.setattr(p5, "_combine", fail_first)
    assert run(n()) == F
    assert run(c()) == F


def test_bite_td_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = worlds(tmp_path, "n", f200="30.000", reported="30.000", observed="30.000", elapsed="30.0008")
    c = worlds(tmp_path, "c", f200="30.000", reported="30.000", observed="30.000", elapsed="30.000")
    assert run(n()) == P and run(c()) == P
    monkeypatch.setattr(p5, "_deadline_measures", lambda first, reported, observed, elapsed: (observed, elapsed))
    assert run(n()) == B()
    assert run(c()) == P


def test_bite_td_same_side(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = worlds(tmp_path, "n", f200="29.9996", reported="30.0004")
    c = worlds(tmp_path, "c", f200="30.000", reported="29.9995")
    assert run(n()) == B() and run(c()) == P
    monkeypatch.setattr(p5, "_same_side", lambda *args: True)
    assert run(n()) == P
    assert run(c()) == P


def test_bite_leg_order_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HOME addition: disabling the per-leg start order lets its N pass."""
    n = worlds(tmp_path, "n", hooks={"after-forwarder": sv(("state", "started_at"), ZERO)})
    c = worlds(tmp_path, "c", fwd_first=True)
    assert run(n()) == B() and run(c()) == P
    monkeypatch.setattr(p5, "_running_order", lambda snap, t0: None)
    assert run(n()) == P
    assert run(c()) == P


def test_td_offset_equivalence() -> None:
    start = p5._instant("2026-10-23T10:00:00.000000-07:00", ms=True)
    health = p5._instant("2026-10-23T17:00:29.999000+00:00", ms=True)
    assert health - start == 29_999_000 and p5._instant("2026-10-23T17:00:00.000000Z") == start
    assert p5._seconds(health - start) == Decimal("29.999")


def test_runtime_members_are_the_22() -> None:
    assert tuple(DRIFT) == p5.IMMUTABLE_RUNTIME and len(DRIFT) == 22


RECEIVED = {"ops_host_binding_files.py": ("5c0319be", "01d42445051f2e6393a1c82e9ed7adf8395c3a1c0b37b5ab80c9e4efcaec029e"),
            "ops_host_binding.py": ("ab21d2d6", "db321275fe51fbc425517bce40d2733ab0e4c3c62c1d675bd6ff407a43653be5"),
            "ops_host_inspect.py": ("835fc3d7", "d75cef1093d049160e3ce211cca9490c3e3c03c5770f96c9d496a139584ab976"),
            "ops_host_env.py": ("9b4e0308", "9c21b5062988bc8188bd2c9fa2a05b6a06a5aa7f7cee22ace40d874c88df6a69"),
            "ops_host_client.py": ("1dadcaba", "c537bed9bd6fb7ac8180f5ae098e18ad683885756ba219ff38121e614355d31a")}


def test_received_modules_unchanged() -> None:
    for name, (blob, digest) in RECEIVED.items():
        raw = (BIN / name).read_bytes()
        assert git_blob(raw).startswith(blob) and sha(raw) == digest, name
    assert [Path(module.__file__).name for module in (R1, R2, R3, R4)] == [
        "ops_host_binding_files.py", "ops_host_binding.py", "ops_host_inspect.py", "ops_host_env.py"]


F5_IDS = (
    "F5-ENV-FAIL", "F5-ENV-NONENV-FAULT", "F5-START-COMPLETE-MISS", "F5-START-200-NULL", "F5-START-MISSING-NULL",
    "F5-START-LATE200", "F5-START-DONE-NULL", "F5-STOP-OVER10", "F5-STOP-NONZERO", "F5-STOP-NO-STOPPED",
    "F5-STOP-TRACEBACK", "F5-STOP-FORCEDKILL", "F5-CODE-VERDICT",
    "F5-RESTART-CARRY-FAIL", "F5-RESTART-MISSING", "F5-RESTART-LIE", "F5-RESTART-HOST-START",
    "F5-RESTART-REFUSED-START", "F5-RESTART-IDS-STOPPED", "F5-RESTART-DRIFT", "F5-RESTART-NOT-ARMED",
    "F5-RESTART-TTL", "F5-RESTART-REPAIR", "F5-RESTART-EXIT",
    "F5-TD-MISS-30", "F5-TD-IN-TIME", "F5-TD-MISS-STRADDLE", "F5-TD-HEALTH-STRADDLE", "F5-TD-OBS-NOT-DEADLINE",
    "F5-TD-ONE-SIDED-LOW", "F5-TD-ONE-SIDED-HIGH", "F5-TD-STOP-STRADDLE", "F5-TD-WITHIN10", "F5-TD-SAME-MEASURE",
    "F5-TD-OVER-BAND", "F5-TD-DECIMAL-1MS", "F5-TD-JSON-TEXT", "F5-TD-NUMBER-TYPE", "F5-TD-OFFSET",
    "F5-TD-HELPER-AUDIT",
    "F5-TRUTH-DONE", "F5-TRUTH-FAILED", "F5-TRUTH-KIND", "F5-MATCHES-BEFORE", "F5-MATCHES-AFTER",
    "F5-PRIOR-ENV-CARRY", "F5-PRIOR-ORIGIN", "F5-PRIOR-STOP-INSPECT", "F5-PRIOR-ROW-WRITER", "F5-PRIOR-RAW-HASH",
    "F5-PRIOR-WINDOW", "F5-PRIOR-BINDING", "F5-PRIOR-IDENTITIES", "F5-PRIOR-SEQ", "F5-PRIOR-ACTION",
    "F5-PRIOR-SELECTION", "F5-PRIOR-PATH", "F5-HOST-FAULT", "F5-REFUSED", "F5-CADENCE-ZERO", "F5-CADENCE-GAP",
    "F5-CADENCE-FIRST200", "F5-AUDIT-REF", "F5-HOST-LITERAL", "F5-E16-400", "F5-CRASH-LISTENER", "F5-CRASH-ORIGIN",
    "F5-CRASH-NONENV-APP", "F5-CRASH-EXIT", "F5-CRASH-OOM", "F5-CRASH-TERMINAL", "F5-CRASH-NONENV",
    "F5-STANDALONE-STOP", "F5-ENGINE-UNSUPPORTED", "F5-START-FLAT", "F5-UUID-INVALID",
    "F5-WINDOW-FIRST", "F5-PROTOCOL", "F5-EDGE-VERSION", "F5-EDGE-IDENTITY", "F5-EDGE-ENV", "F5-RUNTIME-EQUALITY",
    "F5-DIRECT-READ", "F5-RECHECK", "F5-NATIVE-NONCONVERSION", "F5-BITE-DISPATCH", "F5-BITE-CARRY",
    "F5-BITE-RESTART", "F5-BITE-TD",
)
HOME_IDS = ("F5-LEG-ORDER-START", "F5-LEG-ORDER-STOP", "F5-SENTINEL-NO-EVENT")
# Pairs proven by their own tests: (N tests, C tests), by function name.
SPECIAL = {
    "F5-CODE-VERDICT": (("test_code_verdict_n",), ("test_code_verdict_c",)),
    "F5-TD-HELPER-AUDIT": (("test_helper_audit_n",), ("test_helper_audit_c",)),
    "F5-WINDOW-FIRST": (("test_window_first_n", "test_window_first_static_n"),
                        ("test_window_first_c", "test_window_first_static_c")),
    "F5-DIRECT-READ": (("test_direct_read_n",), ("test_direct_read_c",)),
    "F5-RECHECK": (("test_recheck_n",), ("test_recheck_c",)),
    "F5-NATIVE-NONCONVERSION": (("test_native_nonconversion_n",), ("test_native_nonconversion_c",)),
    "F5-BITE-DISPATCH": (("test_bite_dispatch",), ("test_bite_dispatch",)),
    "F5-BITE-CARRY": (("test_bite_carry",), ("test_bite_carry",)),
    "F5-BITE-RESTART": (("test_bite_restart",), ("test_bite_restart",)),
    "F5-BITE-TD": (("test_bite_td_event", "test_bite_td_same_side"), ("test_bite_td_event", "test_bite_td_same_side")),
}


def test_every_pair_has_named_n_and_c() -> None:
    assert len(F5_IDS) == 89 and len(set(F5_IDS)) == 89
    have: dict = {}
    for case in CASES:
        have.setdefault(case.fid, set()).add(case.kind)
    for fid, (n_tests, c_tests) in SPECIAL.items():
        assert all(callable(globals().get(name)) for name in n_tests + c_tests), fid
        have.setdefault(fid, set()).update("NC")
    assert set(have) == set(F5_IDS) | set(HOME_IDS)
    assert all(kinds == {"N", "C"} for kinds in have.values())
    names = [f"{c.fid}:{c.kind}:{c.name}" for c in CASES]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# R5′ repair controls (#259): a separate inventory, so the 465 original tests
# and their expected verdicts/codes remain unchanged. All times are supplied.

REPAIR_NOW = BASE + timedelta(seconds=3602)


def repair_extra_inspect(target: str = "app", *, post: bool = False, fault: str = "valid",
                         env_miss: bool = False) -> Any:
    """One additional inspect; neither last-pre nor first-post selection changes."""
    def fn(runs: list, world: World) -> None:
        starts = [item for item in runs if item["op"] == "docker-start"]
        t0 = back(starts[0]["started_at"])
        selected = [item for item in runs if item["op"] == "docker-inspect"
                    and item["params"]["target"] == target]
        extra = copy.deepcopy(selected[1 if post else 0])
        a, b = ((882_000, 888_000) if post else
                ((-277_000, -275_000) if target == "app" else (-257_000, -255_000)))
        extra["started_at"], extra["ended_at"] = iso(t0 + a), iso(t0 + b)
        if fault == "scalar":
            snapshot: Any = 42
        elif fault == "wrong-container":
            snapshot = copy.deepcopy(next(item["result"]["snapshot"] for item in runs
                                           if item["op"] == "docker-inspect"
                                           and item["params"]["target"] == "forwarder"))
        elif fault == "missing-file":
            snapshot = ref(str(world.ev / "r5r-missing.json"), b"missing evidence\n")
        else:
            assert fault == "valid"
            original = Path(extra["result"]["snapshot"]["path"])
            doc = json.loads(world.out[original][0])
            doc["observed_at"] = iso(t0 + (a + b) // 2)
            doc["runtime"] = world.runtime23(target)
            if env_miss:
                doc["runtime"]["env"][0] = "PATH=/opt/changed/bin"
            snapshot = world.evidence("r5r-extra", doc)
        extra["result"]["snapshot"] = snapshot
        runs.append(extra)
        runs.sort(key=lambda item: back(item["started_at"]))
    return fn


def repair_finished_change(doc: dict, world: World) -> None:
    """A completed intervening restart: t0 < F1 < the already recorded S2."""
    doc["state"]["finished_at"] = iso(back(doc["state"]["started_at"]) - 200_000)


REPAIR_CASES = (
    Case("R5R-F1", "N1", "extra-pre-app-scalar", B(), "D-5", "project",
         {"runs": repair_extra_inspect(fault="scalar")}, {}),
    Case("R5R-F1", "N2", "extra-pre-app-wrong-container", B(), "D-5", "project",
         {"runs": repair_extra_inspect(fault="wrong-container")}, {}),
    Case("R5R-F1", "N3", "extra-post-app-scalar", B(), "D-5", "project",
         {"runs": repair_extra_inspect(post=True, fault="scalar")}, {}),
    Case("R5R-F1", "N4", "extra-pre-app-missing-file", B(), "D-5", "project",
         {"runs": repair_extra_inspect(fault="missing-file")}, {}),
    Case("R5R-F1", "N5", "extra-pre-app-env-miss", B(), "D-5", "project",
         {"runs": repair_extra_inspect(env_miss=True)}, {}),
    Case("R5R-F1", "N6", "extra-pre-forwarder-scalar", B(), "D-5", "project",
         {"runs": repair_extra_inspect("forwarder", fault="scalar")}, {}),
    Case("R5R-F1", "N7", "restart-extra-pre-app-scalar", B(), "R-1", "project",
         {"runs": repair_extra_inspect(fault="scalar")}, {}),
    Case("R5R-F1", "N8", "truthful-miss-extra-env-match", B(), "D-5", "project",
         {"runs": repair_extra_inspect()}, {"env_edges": ("before-app", "after-app")}),
    Case("R5R-F1", "C1", "valid-extra-pre-app", P, "D-5", "project",
         {"runs": repair_extra_inspect()}, {}),
    Case("R5R-F1", "C2", "valid-extra-post-app", P, "D-5", "project",
         {"runs": repair_extra_inspect(post=True)}, {}),
    Case("R5R-F1", "C3", "valid-extra-pre-forwarder", P, "D-5", "project",
         {"runs": repair_extra_inspect("forwarder")}, {}),
    Case("R5R-F1", "C4", "restart-valid-extra", P, "R-1", "project",
         {"runs": repair_extra_inspect()}, {}),
    Case("R5R-F1", "C5", "truthful-miss-extra-env-miss", F, "D-5", "project",
         {"runs": repair_extra_inspect(env_miss=True)}, {"env_edges": ("before-app", "after-app")}),
    Case("R5R-F1", "C6", "no-extra-clean", P, "D-5", "project", {}, {}),
    Case("R5R-F2", "N1", "app-finished-changed", B(), "D-5", "project",
         {"after-app": repair_finished_change}, {}),
    Case("R5R-F2", "N2", "app-sentinel-to-finished", B(), "D-5", "project",
         {"before-app": sv(("state", "finished_at"), ZERO), "after-app": repair_finished_change}, {}),
    Case("R5R-F2", "N3", "forwarder-finished-changed", B(), "D-5", "project",
         {"after-forwarder": repair_finished_change}, {}),
    Case("R5R-F2", "N4", "restart-finished-changed", B(), "R-1", "project",
         {"after-app": repair_finished_change}, {}),
    Case("R5R-F2", "C1", "first-start-sentinel", P, "D-5", "project", {}, {"fwd_first": True}),
    Case("R5R-F2", "C2", "previous-exit-equal", P, "D-5", "project", {}, {}),
    Case("R5R-F2", "C3", "restart-finished-equal", P, "R-1", "project", {}, {}),
    Case("R5R-F2", "C4", "equivalent-offset-finished", P, "D-5", "project",
         {"after-app": tv(("state", "finished_at"), to_utc)}, {}),
    Case("R5R-GR2", "N1", "at-one-us-future", B(), "D-5", "project",
         {"receipt": sv("at", iso(us("3602") + 1), "seen_at", iso(us("3602")))}, {}),
    Case("R5R-GR2", "N2", "seen-one-us-future", B(), "D-5", "project",
         {"receipt": sv("at", iso(us("3602")), "seen_at", iso(us("3602") + 1))}, {}),
    Case("R5R-GR2", "C1", "both-equal-now", P, "D-5", "project",
         {"receipt": sv("at", iso(us("3602")), "seen_at", iso(us("3602")))}, {}),
    Case("R5R-GR4", "N1", "r1-listener-false", B(), "R-1", "project",
         {"receipt": sv("listener_gone", False)}, {}),
    Case("R5R-GR4", "C1", "r1-listener-true", P, "R-1", "project", {}, {}),
    Case("R5R-GR4", "N2", "r1i-listener-false", B(), "R-1i", "project",
         {"receipt": sv("listener_gone", False)}, {}),
    Case("R5R-GR4", "C2", "r1i-listener-true", P, "R-1i", "project", {}, {}),
)


@pytest.mark.parametrize("case", REPAIR_CASES, ids=[f"{c.fid}:{c.kind}:{c.name}" for c in REPAIR_CASES])
def test_repair_r5r(case: Case, tmp_path: Path, record_property: Any) -> None:
    world = World(tmp_path, case.row, route=case.route, hooks=case.hooks, **case.knobs)
    now = REPAIR_NOW if case.fid == "R5R-GR2" else NOW
    actual = run(world, now=now)
    record_property("case_id", f"{case.fid}:{case.kind}:{case.name}")
    record_property("actual_verdict", actual[0])
    record_property("actual_code", actual[1])
    assert actual == case.expect
