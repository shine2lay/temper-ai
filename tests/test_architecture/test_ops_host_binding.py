"""Tests for configs/architecture/bin/ops_host_binding.py (P2, Architecture #244).

Every F2 case ID of the r5 CASE-REQUIREMENTS appendix gets, per variant, its own
N test (one fault, exactly one code, or the stated pass) and its own C test (the
same route's clean twin, UNTRUSTED). All data is synthetic: this file's own
builder writes it under pytest's tmp_path with 0700 folders and exact leaf modes.
No shared fixture, no conftest, no producer code.

The authority and Security22 review pins are real hashes of real documents, which a
synthetic root cannot reproduce: loads swap in synthetic pins for their duration.
F2-GRAMMAR tests use the real pins, unpatched.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "architecture" / "bin"
MODULE_PATH = BIN / "ops_host_binding.py"
R1_PATH = BIN / "ops_host_binding_files.py"
R1_SHA256 = "01d42445051f2e6393a1c82e9ed7adf8395c3a1c0b37b5ab80c9e4efcaec029e"


def _load_module():
    spec = importlib.util.spec_from_file_location("ops_host_binding", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()

CM, IU, PI, MS, AM, BI, SI, SM, SD, RM, EI = (
    "TARGET_CONTEXT_MISSING", "TARGET_ISSUER_UNTRUSTED", "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING", "TARGET_SELECTOR_AMBIGUOUS", "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH", "TARGET_SOURCE_MISSING", "TARGET_SOURCE_DRIFT", "TARGET_REVIEW_MISSING",
    "TARGET_EVIDENCE_INVALID")
PASS = "PASS"
NATIVE = (
    "NATIVE_ISSUER_SCOPE_SUBJECT_CONDITIONS",
    "INDEPENDENT_JOB_KIT_CALIBRATION_SELECTION",
    "REVIEWED_BOOTSTRAP_COMPLETE_DEPENDENCIES_GIT_MEMBERSHIP_AND_ACTUAL_LOADED_SOURCE",
    "SELECTED_RUNTIME_UID_NAMESPACE_CONTAINER_MOUNTS_GRANTS_AND_BOTH_ROOTS_ACCESS",
    "EXACT_QA_PUBLICATION_COHORT_ALL_ORIGINAL_EXPECTATIONS_M02_AND_SECURITY_RECEIVING",
)
UID = os.getuid()
ADDRESS = "100.110.162.4"
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


def _pin(path: str, sha256: str, byte_length: int) -> dict:
    return {"path": path, "sha256": sha256, "byte_length": byte_length}


# The real M01 pins, written here independently of the module.
REAL_AUTHORITY = {
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
REAL_REVIEW = _pin("authority/security22/REVIEW.md",
                   "9f4ff6ec6b7af39fd4e605fa0be3933b29f2c5e57c9a59490f015232065f33af", 27348)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ref(path: str, raw: bytes) -> dict:
    return {"path": str(path), "sha256": sha(raw), "byte_length": len(raw)}


def dumps(value: Any) -> bytes:
    return json.dumps(value, indent=1, sort_keys=True).encode() + b"\n"


def jraw(value: Any) -> bytes:
    return json.dumps(value).encode()


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()  # noqa: S324 (Git object id)


def runtime(port: int) -> dict:
    return {"image": "synthetic/scanapp:1", "command": ["python3", "/app/server.py"], "internal_port": 8000,
            "workdir": "/app", "env": {"HOST": "0.0.0.0", "PORT": "8000", "DATA_DIR": "/data",
                                       "ALLOWED_HOSTS": f"{ADDRESS}:{port},scanapp:8080"}}


def runtime_sha(value: dict) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _fake_pins() -> tuple[dict, dict, dict]:
    pins, review, files = copy.deepcopy(REAL_AUTHORITY), copy.deepcopy(REAL_REVIEW), {}

    def fix(item: dict) -> None:
        raw = f"synthetic stand-in for {item['path']}\n".encode()
        files[item["path"]] = raw
        item.update(ref(item["path"], raw))

    for key in ("base", "correction", "qa_authority_order"):
        fix(pins[key])
    for key in ("amendment", "binding_revision"):
        fix(pins[key]["proposal"])
        fix(pins[key]["manifest"])
    fix(review)
    return pins, review, files


FAKE_PINS, FAKE_REVIEW, AUTH_RAW = _fake_pins()


# ---------------------------------------------------------------------------
# The builder: one coherent synthetic data set per test; hooks inject one fault.

class Fx:
    def __init__(self, tmp: Path, route: str, hooks: dict | None = None) -> None:
        self.tmp, self.route, self.hooks = tmp, route, hooks or {}
        self.qa, self.win, self.rec, self.kit = tmp / "qa", tmp / "win", tmp / "rec", tmp / "kit"
        self.ops, self.qar = tmp / "repo-ops", tmp / "repo-qa"
        self.bin, self.std = tmp / "py" / "bin", tmp / "py" / "lib"
        self.out: dict = {}
        tmp.mkdir(exist_ok=True)
        os.chmod(tmp, 0o700)
        self._build()
        for path, (raw, mode) in sorted(self.out.items()):
            self.write(path, raw, mode)
        self.hook("after", self)

    def hook(self, stage: str, value: Any) -> Any:
        fn = self.hooks.get(stage)
        return value if fn is None else fn(value, self)

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

    def _build(self) -> None:
        project = self.route == "project"
        # kit_evidence: domain, SUMS, artifact.
        domain = self.hook("domain", {
            "app/run.sh": (b"#!/bin/sh\nexec python3 server.py\n", 0o755),
            "app/server.py": (b"print('synthetic app')\n", 0o644),
            "static/index.html": (b"<p>synthetic</p>\n", 0o644)})
        sums = self.hook("sums", "".join(f"{sha(raw)}  {name}\n" for name, (raw, _) in sorted(domain.items())).encode())
        self.sums_sha = sha(sums)
        sums_written = self.hook("sums_raw", sums)
        kit_raw = b"synthetic kit artifact\n"
        self.kit_sha = sha(kit_raw)
        kit_written = self.hook("kit_raw", kit_raw)
        written = self.hook("domain_written", dict(domain))
        for name, (raw, mode) in written.items():
            self.put(self.kit / name, raw, mode)
        self.put(self.kit / "SHA256SUMS", sums_written)
        kit_ref = None
        if project:
            self.put(self.kit / "KIT.tar", kit_written)
            kit_ref = ref("KIT.tar", kit_written)
        files = [{"ref": ref(name, written[name][0]), "mode": written[name][1]} for name in sorted(written)]
        self.kit_evidence = self.hook("kit_evidence", {
            "root": str(self.kit), "kit": kit_ref, "sums": ref("SHA256SUMS", sums_written), "files": files,
            "file_count": len(files)})
        # Opaque records and their bound subjects.
        spans = self.hook("spans", {"m01": b"M01-SUBJ", "m02": b"m02sb", "sec1": b"S"})
        raws = self.hook("records", {"m01": spans["m01"] + b"|m01 opaque record\n",
                                     "m02": b"xx" + spans["m02"] + b"|m02 opaque record\n",
                                     "sec1": b"sec:" + spans["sec1"] + b"|security opaque record\n"})
        subjects = self.hook("subjects", dict(spans))
        offsets = {"m01": 0, "m02": 2, "sec1": 4}
        self.records, self.subject_refs = {}, {}
        for key in ("m01", "m02", "sec1"):
            self.put(self.rec / f"{key}.rec", raws[key])
            self.records[key] = ref(str(self.rec / f"{key}.rec"), raws[key])
            self.put(self.rec / f"subject-{key}.bin", subjects[key])
            self.subject_refs[key] = ref(str(self.rec / f"subject-{key}.bin"), subjects[key])
        self.record_subjects = self.hook("record_subjects", [
            {"record": copy.deepcopy(self.records[key]), "byte_offset": offsets[key], "byte_length": len(spans[key]),
             "expected_subject": self.subject_refs[key]} for key in ("m01", "m02", "sec1")])
        # Sources: two repositories.
        nodes, node_sha = [], {}
        for key, path, node_id, roles in SIX_PINS:
            raw = f"# synthetic {path}\n".encode()
            self.put(self.ops / path, raw, 0o644)
            node_sha[key] = sha(raw)
            nodes.append(self._node(node_id, "ops-agent-tools", path, raw, roles))
        schema_raw = {key: dumps({"synthetic_schema": key}) for key in SCHEMA_PATHS}
        repo_raw = self.hook("repo_schema_raw", dict(schema_raw))
        for key, path in SCHEMA_PATHS.items():
            self.put(self.qar / path, repo_raw[key], 0o644)
            roles = ["catalog"] if key == "wire_catalog" else ["schema"]
            nodes.append(self._node("qa-" + key.replace("_", "-"), "qa-publication", path, repo_raw[key], roles))
        nodes.sort(key=lambda node: node["id"])
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
        # The QA cohort.
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
        cohort = self.hook("cohort", {
            "schema": "qa-ops-host-cohort-inventory/1", "publication_id": PUB_ID, "cohort_id": "cohort-1",
            "files": listed, "references": references,
            "original_inventory": self.qa_put("cohort/ORIGINAL-INVENTORY.json",
                                              dumps([ref("cohort/orig/a.json", original)])),
            "original_index": self.qa_put("cohort/ORIGINAL-INDEX.json", dumps({"index": ["cohort/orig/a.json"]})),
            "old_to_new_expectations": self.qa_put("cohort/OLD-TO-NEW.json", dumps(expectations))})
        closure = self.hook("closure", {
            "schema": "qa-ops-host-source-closure/1", "publication_id": PUB_ID,
            "repositories": [
                {"id": "ops-agent-tools", "owner": "ops", "root": str(self.ops), "commit": "a" * 40, "tree": "b" * 40},
                {"id": "qa-publication", "owner": "qa", "root": str(self.qar), "commit": "c" * 40, "tree": "d" * 40}],
            "nodes": nodes, "edges": edges, "entrypoints": [{"node": "ops-hostctl", "symbol": "main"}],
            "runtime": run, "generated_closure": self.qa_put("COHORT-INVENTORY.json", dumps(cohort))})
        # The binding and what it reaches.
        for path, raw in AUTH_RAW.items():
            self.qa_put(path, raw)
        binding = self.hook("binding", {
            "schema": "qa-ops-host-expected-receiver-binding/1", "issuer": "qa", "project": PROJECT,
            "publication_id": PUB_ID, "binding_id": "p3-inspect2-closed23-env1", "target": copy.deepcopy(TARGET),
            "authority": copy.deepcopy(FAKE_PINS),
            "schemas": {key: self.qa_put(path, schema_raw[key]) for key, path in SCHEMA_PATHS.items()},
            "security_context": {"review": copy.deepcopy(FAKE_REVIEW),
                                 "identity": self.qa_put("authority/security22/IDENTITY.json",
                                                         dumps({"synthetic": "identity"}))},
            "source_closure": self.qa_put("SOURCE-CLOSURE.json", dumps(closure))})
        bref = self.qa_put(BINDING_PATH, dumps(binding))
        table = self.hook("table", {"schema": "qa-ops-host-project-kits/1", "publication_id": PUB_ID, "kits": [
            {"project_id": "p3", "kit_id": "kit-0", "kit_sha256": "0" * 64, "build_sums_sha256": "1" * 64,
             "expected_receiver_binding": copy.deepcopy(bref)},
            {"project_id": "p3", "kit_id": "kit-1", "kit_sha256": self.kit_sha, "build_sums_sha256": self.sums_sha,
             "expected_receiver_binding": copy.deepcopy(bref)}]})
        table_ref = self.qa_put("PROJECT-KITS.json", dumps(table))
        rt1, rt2 = runtime(8970), runtime(8971)
        e1 = {"entry": "e1", "build_id": "C0", "purpose": "clean", "copy_id": "c01", "batch_id": "b1",
              "build_path": str(self.kit), "sums_file": str(self.kit) + "/SHA256SUMS", "host_dir": "/srv/host/e1",
              "app_copy_path": "/srv/app/e1", "data_dir": "/srv/data/e1", "sums_sha256": self.sums_sha,
              "runtime_sha256": runtime_sha(rt1), "file_count": len(written), "plant_of": None,
              "diff_sha256": None, "round": 1, "address": ADDRESS, "port": 8970,
              "literal_origin": f"http://{ADDRESS}:8970", "runtime": rt1, "inner_network_name": "inner-e1",
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
        manifest = self.hook("manifest", {
            "schema": "qa-calibration-manifest/2", "publication_id": PUB_ID, "calibration_id": "cal-1",
            "draft_kit_id": "draft-1", "host_rows": {"R-1": "restart", "R-1i": "restart", "D-1": "crash",
                                                     "D-5": "start", "API-D-1": "crash", "API-D-5": "start",
                                                     "HOST-L": "launch-cases"},
            "entries": [e1, e2]})
        manifest_raw = dumps(manifest)
        manifest_ref = self.qa_put(MANIFEST_REL, manifest_raw)
        publication = self.hook("publication", {
            "schema": "qa-ops-host-publication/3", "issuer": "qa", "project": PROJECT, "publication_id": PUB_ID,
            "project_kits": table_ref, "calibration_manifests": [manifest_ref]})
        publication_raw = dumps(publication)
        self.put(self.qa / "PUBLICATION.json", publication_raw)
        # The independent expected data and the window.
        if project:
            binding_data = {"mode": "project", "project_id": "p3", "run_id": "run-1",
                            "build_sums_sha256": self.sums_sha, "kit_id": "kit-1", "kit_sha256": self.kit_sha}
            selection = None
        else:
            binding_data = {"mode": "calibration", "manifest_sha256": sha(manifest_raw), "entry": "e1",
                            "build_sums_sha256": self.sums_sha, "calibration_run": "cal-run-1"}
            selection = {"manifest_path": str(self.qa / MANIFEST_REL), "manifest_sha256": sha(manifest_raw),
                         "entry": "e1", "build_id": "C0", "sums_sha256": self.sums_sha, "round": 1,
                         "copy_id": "c01", "address": ADDRESS, "port": 8970,
                         "literal_origin": f"http://{ADDRESS}:8970", "runtime_sha256": runtime_sha(rt1),
                         "security_receipt_id": "P3-CAL-1", "security_receipt_path": "/srv/s4/receipt-1.json",
                         "security_receipt_sha256": "f" * 64, "security_selection_message_id": "rm-s4-1"}
        expected = self.hook("expected", {"binding": binding_data, "selection": selection})
        window = {"schema": "synthetic-window", "binding": copy.deepcopy(expected["binding"])}
        window.update(node_sha)
        if not project:
            window.update({"calibration_selection": copy.deepcopy(expected["selection"]),
                           "security_receipt_path": "/srv/s4/receipt-1.json", "security_receipt_sha256": "f" * 64,
                           "runtime": copy.deepcopy(rt1), "origin": f"http://{ADDRESS}:8970",
                           "host_dir": "/srv/host/e1", "app_copy_path": "/srv/app/e1", "data_dir": "/srv/data/e1",
                           "scheduled_use_minutes": None, "schedule_source": None, "schedule_sha256": None})
        window_raw = dumps(self.hook("window", window))
        self.put(self.win / "WINDOW.json", window_raw)
        window_ref = ref(str(self.win / "WINDOW.json"), window_raw)
        context = {
            "window": window_ref, "publication": ref(str(self.qa / "PUBLICATION.json"), publication_raw),
            "m01_record": copy.deepcopy(self.records["m01"]), "m02_record": copy.deepcopy(self.records["m02"]),
            "security_records": [copy.deepcopy(self.records["sec1"])],
            "expected_window_sha256": window_ref["sha256"], "expected_binding": copy.deepcopy(expected["binding"]),
            "release_roots": [{"repository": "ops-agent-tools", "root": str(self.ops)},
                              {"repository": "qa-publication", "root": str(self.qar)}],
            "kit_evidence": self.kit_evidence, "record_subjects": self.record_subjects}
        if not project:
            context.update({"calibration_manifest": ref(str(self.qa / MANIFEST_REL), manifest_raw),
                            "expected_draft_kit_id": "draft-1",
                            "expected_calibration_selection": copy.deepcopy(expected["selection"])})
        self.context = self.hook("context", context)

    @staticmethod
    def _node(node_id: str, repository: str, path: str, raw: bytes, roles: list) -> dict:
        return {"id": node_id, "repository": repository, "path": path, "git_blob": git_blob(raw), "sha256": sha(raw),
                "byte_length": len(raw), "mode": "100644", "roles": roles}


def load(fx: Fx, patches: dict | None = None):
    fn = mod.load_project_candidate if fx.route == "project" else mod.load_calibration_candidate
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "_AUTHORITY_PINS", FAKE_PINS)
        mp.setattr(mod, "_SECURITY_REVIEW_PIN", FAKE_REVIEW)
        for name, value in (patches or {}).items():
            mp.setattr(mod, name, value)
        return fn(fx.context, uid=UID)


def refusal(call) -> str:
    with pytest.raises(mod.TargetRefused) as info:
        call()
    assert type(info.value) is mod.TargetRefused
    assert info.value.args == (info.value.code,)
    return info.value.code


def assert_untrusted(candidate) -> None:
    assert type(candidate) is mod.CandidateTarget
    assert candidate.trust == "UNTRUSTED"
    assert candidate.required_native_checks == NATIVE


# Hook helpers. Each returns {stage: fn(value, fx) -> value}.

def edit(stage: str, fn) -> dict:
    def run(value, fx):
        fn(value, fx)
        return value
    return {stage: run}


def swap(stage: str, fn) -> dict:
    return {stage: fn}


def join(*parts: dict) -> dict:
    out: dict = {}
    for part in parts:
        out.update(part)
    return out


def ctx(fn) -> dict:
    return edit("context", lambda c, fx: fn(c))


def after(fn) -> dict:
    return edit("after", lambda fx, _: fn(fx))


def append(path: Path, extra: bytes = b" ") -> None:
    with path.open("ab") as handle:
        handle.write(extra)


def setkey(obj: dict, key: str, value: Any) -> None:
    obj[key] = value


def sorted_nodes(closure: dict) -> None:
    closure["nodes"].sort(key=lambda node: node["id"])


def sorted_edges(closure: dict) -> None:
    closure["edges"].sort(key=lambda edge: (edge["from"], edge["to"], edge["kind"]))


def add_edge(a: str, b: str, kind: str):
    def fn(closure, fx):
        closure["edges"].append({"from": a, "to": b, "kind": kind})
        sorted_edges(closure)
    return edit("closure", fn)


def sums_extra_line(raw: bytes, fx) -> bytes:
    return raw + f"{'7' * 64}  extra/undeclared.txt\n".encode()


class Case(NamedTuple):
    fid: str
    variant: str
    route: str
    code: str
    hooks: dict
    check: Any = None


P, K = "project", "calibration"
CASES: list[Case] = []


def case(fid: str, variant: str, route: str, code: str, hooks: dict, check=None) -> None:
    CASES.append(Case(fid, variant, route, code, hooks, check))


# F2-CONTEXT
case("F2-CONTEXT", "none", P, CM, swap("context", lambda c, fx: None))
case("F2-CONTEXT", "not-dict", P, CM, swap("context", lambda c, fx: [c]))
case("F2-CONTEXT", "unknown-key", P, CM, ctx(lambda c: setkey(c, "extra", 1)))
case("F2-CONTEXT", "legacy-only", P, CM,
     swap("context", lambda c, fx: {"binding_path": BINDING_PATH, "publication_root": str(fx.qa)}))
case("F2-CONTEXT", "record-subjects-absent", P, CM, ctx(lambda c: c.pop("record_subjects")))
case("F2-CONTEXT", "calibration-key-absent", K, CM, ctx(lambda c: c.pop("expected_calibration_selection")))

# F2-WINDOW-REF
case("F2-WINDOW-REF", "key-absent", P, CM, ctx(lambda c: c.pop("window")))
case("F2-WINDOW-REF", "alias-only", P, CM, ctx(lambda c: setkey(c, "window_path", c.pop("window")["path"])))
case("F2-WINDOW-REF", "path-relative", P, CM, ctx(lambda c: setkey(c["window"], "path", "win/WINDOW.json")))
case("F2-WINDOW-REF", "hash-upper", P, CM, ctx(lambda c: setkey(c["window"], "sha256", c["window"]["sha256"].upper())))
case("F2-WINDOW-REF", "length-bool", P, CM, ctx(lambda c: setkey(c["window"], "byte_length", True)))
case("F2-WINDOW-REF", "length-zero", P, CM, ctx(lambda c: setkey(c["window"], "byte_length", 0)))
case("F2-WINDOW-REF", "length-over-cap", P, CM, ctx(lambda c: setkey(c["window"], "byte_length", 16777217)))
case("F2-WINDOW-REF", "sha-not-expected", P, BI, ctx(lambda c: setkey(c, "expected_window_sha256", "0" * 64)))


def _same_length_change(path: Path) -> None:
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b" ")


case("F2-WINDOW-REF", "bytes-differ", P, PI, after(lambda fx: _same_length_change(fx.win / "WINDOW.json")))
case("F2-WINDOW-REF", "length-differ", P, PI,
     ctx(lambda c: setkey(c["window"], "byte_length", c["window"]["byte_length"] + 1)))

# F2-SELECT-ZERO
case("F2-SELECT-ZERO", "project", P, MS, edit("expected", lambda e, fx: setkey(e["binding"], "kit_id", "kit-9")))


def _entry_e9(e, fx):
    e["binding"]["entry"] = "e9"
    e["selection"]["entry"] = "e9"


case("F2-SELECT-ZERO", "calibration-entry", K, MS, edit("expected", _entry_e9))

# F2-SELECT-NONSEL-DUP (non-selected rows)
case("F2-SELECT-NONSEL-DUP", "identical", P, AM,
     edit("table", lambda t, fx: t["kits"].append(copy.deepcopy(t["kits"][0]))))


def _contradictory_copy(table, index):
    row = copy.deepcopy(table["kits"][index])
    row["expected_receiver_binding"]["sha256"] = "9" * 64
    table["kits"].append(row)


case("F2-SELECT-NONSEL-DUP", "contradictory", P, AM, edit("table", lambda t, fx: _contradictory_copy(t, 0)))

# F2-PROJECT-NONSEL-BAD
for _variant, _fn in (
        ("missing-key", lambda row: row.pop("kit_id")),
        ("extra-key", lambda row: setkey(row, "note", "x")),
        ("builtin", lambda row: setkey(row, "project_id", ["p3"])),
        ("bool", lambda row: setkey(row, "kit_id", True)),
        ("bad-kit-sha", lambda row: setkey(row, "kit_sha256", "A" * 64)),
        ("bad-sums-sha", lambda row: setkey(row, "build_sums_sha256", "1" * 63)),
        ("bad-binding-ref", lambda row: setkey(row["expected_receiver_binding"], "path",
                                               "expected-receiver-bindings/other.json"))):
    case("F2-PROJECT-NONSEL-BAD", _variant, P, BI, edit("table", lambda t, fx, fn=_fn: fn(t["kits"][0])))

# F2-SELECT-AMBIGUOUS (selected row twice)
case("F2-SELECT-AMBIGUOUS", "identical", P, AM,
     edit("table", lambda t, fx: t["kits"].append(copy.deepcopy(t["kits"][1]))))
case("F2-SELECT-AMBIGUOUS", "conflicting-refs", P, AM, edit("table", lambda t, fx: _contradictory_copy(t, 1)))

# F2-MANIFEST-SCHEMA
case("F2-MANIFEST-SCHEMA", "misprint", K, SI,
     edit("manifest", lambda m, fx: setkey(m, "schema", "qa-ops-host-calibration-manifest/2")))
case("F2-MANIFEST-SCHEMA", "other", K, SI, edit("manifest", lambda m, fx: setkey(m, "schema", "qa-calibration-manifest/1")))

# F2-MANIFEST-NONSEL-BAD (entry e2)
for _variant, _fn in (
        ("missing-key", lambda e: e.pop("purpose")),
        ("extra-key", lambda e: setkey(e, "note", "x")),
        ("bad-port", lambda e: setkey(e, "port", 8980)),
        ("bad-runtime", lambda e: setkey(e["runtime"], "command", ["python3"]))):
    case("F2-MANIFEST-NONSEL-BAD", _variant, K, BI, edit("manifest", lambda m, fx, fn=_fn: fn(m["entries"][1])))


def _manifest_nonselected_pair(m, fx):
    twin = copy.deepcopy(m["entries"][1])
    twin["data_dir"] = "/srv/data/e3"
    m["entries"].append(twin)


case("F2-MANIFEST-DUP-ID", "nonselected-pair", K, AM, edit("manifest", _manifest_nonselected_pair))
case("F2-MANIFEST-DUP-ID", "selected-id", K, AM, edit("manifest", lambda m, fx: setkey(m["entries"][1], "entry", "e1")))
case("F2-MANIFEST-PATH-ID", "path-id", K, BI, edit("manifest", lambda m, fx: setkey(m, "calibration_id", "cal-2")))

# F2-BINDING-REF-PATH / BYTES
case("F2-BINDING-REF-PATH", "project", P, BI, edit("table", lambda t, fx: setkey(
    t["kits"][1]["expected_receiver_binding"], "path", "expected-receiver-bindings/other.json")))
case("F2-BINDING-REF-PATH", "calibration", K, BI, edit("manifest", lambda m, fx: setkey(
    m["entries"][0]["expected_receiver_binding"], "path", "expected-receiver-bindings/other.json")))


def _all_rows(t, fx):
    for row in t["kits"]:
        row["expected_receiver_binding"]["sha256"] = "9" * 64


def _all_entries(m, fx):
    for entry in m["entries"]:
        entry["expected_receiver_binding"]["byte_length"] += 1


case("F2-BINDING-REF-BYTES", "hash", P, PI, edit("table", _all_rows))
case("F2-BINDING-REF-BYTES", "length", K, PI, edit("manifest", _all_entries))

# F2-MANIFEST-UNLISTED
case("F2-MANIFEST-UNLISTED", "path", K, BI, edit("context", lambda c, fx: setkey(
    c["calibration_manifest"], "path", str(fx.qa / "calibrations/cal-9/manifest.json"))))
case("F2-MANIFEST-UNLISTED", "hash", K, BI, ctx(lambda c: setkey(c["calibration_manifest"], "sha256", "9" * 64)))


# F2-ROOT-LISTED-DUP
def _listed_twice(p, fx, conflict):
    other = copy.deepcopy(p["calibration_manifests"][0])
    if conflict:
        other["sha256"] = "9" * 64
    p["calibration_manifests"].append(other)


case("F2-ROOT-LISTED-DUP", "same-twice", P, PI, edit("publication", lambda p, fx: _listed_twice(p, fx, False)))
case("F2-ROOT-LISTED-DUP", "conflicting-twice", P, PI, edit("publication", lambda p, fx: _listed_twice(p, fx, True)))
case("F2-ROOT-LISTED-DUP", "reachable-conflict", P, PI, edit("table", lambda t, fx: setkey(
    t["kits"][0]["expected_receiver_binding"], "sha256", "9" * 64)))

# F2-PROJECT-SIX
_SIX_KEYS = ("mode", "project_id", "run_id", "build_sums_sha256", "kit_id", "kit_sha256")
_SIX_OTHER = {"mode": "calibration", "project_id": "p9", "run_id": "run-9", "build_sums_sha256": "9" * 64,
              "kit_id": "kit-9", "kit_sha256": "9" * 64}
for _key in _SIX_KEYS:
    case("F2-PROJECT-SIX", f"absent-{_key}", P, BI, ctx(lambda c, key=_key: c["expected_binding"].pop(key)))
case("F2-PROJECT-SIX", "extra", P, BI, ctx(lambda c: setkey(c["expected_binding"], "extra", "x")))
case("F2-PROJECT-SIX", "wrong-type", P, BI, ctx(lambda c: setkey(c["expected_binding"], "run_id", 7)))
for _key in _SIX_KEYS:
    case("F2-PROJECT-SIX", f"window-different-{_key}", P, BI,
         edit("window", lambda w, fx, key=_key: setkey(w["binding"], key, _SIX_OTHER[key])))

# F2-CALIB-FIVE
_FIVE_KEYS = ("mode", "manifest_sha256", "entry", "build_sums_sha256", "calibration_run")
_FIVE_OTHER = {"mode": "project", "manifest_sha256": "9" * 64, "entry": "e9", "build_sums_sha256": "9" * 64,
               "calibration_run": "cal-run-9"}
for _key in _FIVE_KEYS:
    case("F2-CALIB-FIVE", f"absent-{_key}", K, BI, ctx(lambda c, key=_key: c["expected_binding"].pop(key)))
case("F2-CALIB-FIVE", "extra", K, BI, ctx(lambda c: setkey(c["expected_binding"], "extra", "x")))
for _key in _FIVE_KEYS:
    case("F2-CALIB-FIVE", f"window-different-{_key}", K, BI,
         edit("window", lambda w, fx, key=_key: setkey(w["binding"], key, _FIVE_OTHER[key])))

# F2-CALIB-FIFTEEN: entry-comparable fields changed in both copies; S4 fields in the context only;
# the window's top-level receipt values alone.
_FIFTEEN_ENTRY = {
    "manifest_path": lambda fx: str(fx.qa / "calibrations/cal-1/other.json"), "manifest_sha256": lambda fx: "9" * 64,
    "entry": lambda fx: "e2", "build_id": lambda fx: "C9", "sums_sha256": lambda fx: "9" * 64,
    "round": lambda fx: 2, "copy_id": lambda fx: "c09", "address": lambda fx: "100.110.162.5",
    "port": lambda fx: 8975, "literal_origin": lambda fx: f"http://{ADDRESS}:8979",
    "runtime_sha256": lambda fx: "9" * 64}
for _key, _value in _FIFTEEN_ENTRY.items():
    case("F2-CALIB-FIFTEEN", _key, K, BI,
         edit("expected", lambda e, fx, key=_key, value=_value: setkey(e["selection"], key, value(fx))))
for _key, _value in (("security_receipt_id", "P3-CAL-9"), ("security_receipt_path", "/srv/s4/other.json"),
                     ("security_receipt_sha256", "9" * 64), ("security_selection_message_id", "rm-s4-9")):
    case("F2-CALIB-FIFTEEN", _key, K, BI,
         ctx(lambda c, key=_key, value=_value: setkey(c["expected_calibration_selection"], key, value)))
case("F2-CALIB-FIFTEEN", "window-receipt-path", K, BI,
     edit("window", lambda w, fx: setkey(w, "security_receipt_path", "/srv/s4/other.json")))
case("F2-CALIB-FIFTEEN", "window-receipt-sha", K, BI,
     edit("window", lambda w, fx: setkey(w, "security_receipt_sha256", "9" * 64)))


# F2-CALIB-ENTRY (selected entry e1)
def _e1(fn):
    return edit("manifest", lambda m, fx: fn(m["entries"][0], m))


def _runtime_env(entry, m):
    entry["runtime"]["env"]["ALLOWED_HOSTS"] = f"{ADDRESS}:8977,scanapp:8080"
    entry["runtime_sha256"] = runtime_sha(entry["runtime"])


case("F2-CALIB-ENTRY", "draft", K, BI, ctx(lambda c: setkey(c, "expected_draft_kit_id", "draft-9")))
case("F2-CALIB-ENTRY", "build-path", K, BI, _e1(lambda e, m: setkey(e, "build_path", "/srv/other-kit")))
case("F2-CALIB-ENTRY", "sums-file", K, BI, _e1(lambda e, m: setkey(e, "sums_file", "/srv/other/SHA256SUMS")))
case("F2-CALIB-ENTRY", "file-count", K, BI, _e1(lambda e, m: setkey(e, "file_count", 4)))
case("F2-CALIB-ENTRY", "runtime-hash", K, BI, _e1(lambda e, m: setkey(e, "runtime_sha256", "9" * 64)))
case("F2-CALIB-ENTRY", "runtime-env", K, BI, _e1(_runtime_env))
case("F2-CALIB-ENTRY", "fresh-data", K, BI, _e1(lambda e, m: setkey(m["entries"][1], "data_dir", e["data_dir"])))
case("F2-CALIB-ENTRY", "reuse", K, BI, _e1(lambda e, m: setkey(e, "reuse_after", ["e2"])))
case("F2-CALIB-ENTRY", "schedule", K, BI, _e1(lambda e, m: setkey(e, "scheduled_use_minutes", 5)))
case("F2-CALIB-ENTRY", "network", K, BI, _e1(lambda e, m: setkey(e, "edge_network_name", e["inner_network_name"])))

# F2-KIT-ABSENT
case("F2-KIT-ABSENT", "key-absent", P, CM, ctx(lambda c: c.pop("kit_evidence")))
case("F2-KIT-ABSENT", "sums-absent", P, SM, after(lambda fx: (fx.kit / "SHA256SUMS").unlink()))
case("F2-KIT-ABSENT", "kit-absent", P, SM, after(lambda fx: (fx.kit / "KIT.tar").unlink()))
case("F2-KIT-ABSENT", "domain-file-absent", P, SM, after(lambda fx: (fx.kit / "app/server.py").unlink()))


# F2-KIT-SHAPE (all CM, before any read)
def _kit(fn):
    return edit("kit_evidence", lambda k, fx: fn(k, fx))


_KIT_SHAPE = (
    ("missing-key", lambda k, fx: k.pop("file_count")),
    ("extra-key", lambda k, fx: setkey(k, "extra", 1)),
    ("root-relative", lambda k, fx: setkey(k, "root", "kit")),
    ("root-dotdot", lambda k, fx: setkey(k, "root", str(fx.kit) + "/../kit")),
    ("sums-absolute", lambda k, fx: setkey(k["sums"], "path", "/x/SHA256SUMS")),
    ("sums-zero", lambda k, fx: setkey(k["sums"], "byte_length", 0)),
    ("kit-null-project", lambda k, fx: setkey(k, "kit", None)),
    ("kit-string", lambda k, fx: setkey(k, "kit", "KIT.tar")),
    ("files-not-list", lambda k, fx: setkey(k, "files", {"a": k["files"][0]})),
    ("files-over-bound", lambda k, fx: setkey(k, "files", [k["files"][0]] * 65537)),
    ("files-unsorted", lambda k, fx: k["files"].reverse()),
    ("files-dup-path", lambda k, fx: k["files"].__setitem__(1, copy.deepcopy(k["files"][0]))),
    ("entry-keys", lambda k, fx: setkey(k["files"][0], "extra", 1)),
    ("ref-not-closed", lambda k, fx: setkey(k["files"][0]["ref"], "extra", 1)),
    ("mode-bool", lambda k, fx: setkey(k["files"][0], "mode", True)),
    ("mode-str", lambda k, fx: setkey(k["files"][0], "mode", "0644")),
    ("mode-high", lambda k, fx: setkey(k["files"][0], "mode", 0o10000)),
    ("count-bool", lambda k, fx: setkey(k, "file_count", True)),
    ("count-str", lambda k, fx: setkey(k, "file_count", "3")),
    ("count-zero", lambda k, fx: setkey(k, "file_count", 0)),
    ("count-not-len", lambda k, fx: setkey(k, "file_count", 4)),
)
for _variant, _fn in _KIT_SHAPE:
    case("F2-KIT-SHAPE", _variant, P, CM, _kit(_fn))
case("F2-KIT-SHAPE", "calib-kit-nonnull", K, CM,
     _kit(lambda k, fx: setkey(k, "kit", {"path": "KIT.tar", "sha256": "0" * 64, "byte_length": 1})))


# F2-KIT-BYTE / F2-SUMS-BYTE / F2-SUMS-MEMBER / F2-KIT-EXTRA-DOMAIN
def _change_domain(d, fx):
    d["app/server.py"] = (b"print('changed app')\n", 0o644)
    return d


case("F2-KIT-BYTE", "kit", P, BI, swap("kit_raw", lambda raw, fx: b"changed kit artifact\n"))
case("F2-KIT-BYTE", "domain-file", P, BI, swap("domain_written", _change_domain))
case("F2-SUMS-BYTE", "reordered", P, BI,
     swap("sums_raw", lambda raw, fx: b"".join(reversed(raw.splitlines(keepends=True)))))
case("F2-SUMS-BYTE", "trailing-newline", P, BI, swap("sums_raw", lambda raw, fx: raw + b"\n"))


def _drop_written(d, fx):
    d.pop("static/index.html")
    return d


def _duplicate_line(raw, fx):
    lines = raw.splitlines(keepends=True)
    return b"".join([lines[0], *lines])


def _add_declared(d, fx):
    d["extra/declared.txt"] = (b"declared but not in SUMS\n", 0o644)
    return d


case("F2-SUMS-MEMBER", "missing", P, BI, swap("domain_written", _drop_written))
case("F2-SUMS-MEMBER", "duplicate", P, BI, swap("sums", _duplicate_line))
case("F2-SUMS-MEMBER", "aliased", P, BI, swap("sums", lambda raw, fx: raw.replace(b"  app/run.sh", b"  ./app/run.sh")))
case("F2-SUMS-MEMBER", "count", P, BI, swap("sums", sums_extra_line))
case("F2-SUMS-MEMBER", "calib-entry-count", K, BI, swap("sums", sums_extra_line))


def _extra_present(fx):
    fx.write(fx.kit / "extra" / "unlisted.txt", b"physically present, outside the domain\n", 0o644)


def _extra_not_read(candidate, fx):
    assert all(not read.root.startswith(str(fx.kit / "extra")) and "unlisted" not in read.ref["path"]
               for read in candidate.reads)
    assert candidate.selection["kit_evidence"]["file_count"] == 3


case("F2-KIT-EXTRA-DOMAIN", "extra-present", P, PASS, after(_extra_present), _extra_not_read)
case("F2-KIT-EXTRA-DOMAIN", "extra-declared", P, BI, swap("domain_written", _add_declared))


# F2-SUBJECT-*
def _subject(key: str, raw: bytes) -> dict:
    return edit("subjects", lambda s, fx: setkey(s, key, raw))


case("F2-SUBJECT-UNEQUAL", "m01", P, RM, _subject("m01", b"M01-SUBX"))
case("F2-SUBJECT-UNEQUAL", "security", P, RM, _subject("sec1", b"T"))


def _subjects(fn):
    return edit("record_subjects", lambda s, fx: fn(s, fx))


case("F2-SUBJECT-ABSENT", "association-missing", P, RM, _subjects(lambda s, fx: s.pop(2)))
case("F2-SUBJECT-ABSENT", "association-extra", P, RM, _subjects(lambda s, fx: s.append(
    {"record": {"path": str(fx.rec / "other.rec"), "sha256": "9" * 64, "byte_length": 9}, "byte_offset": 0,
     "byte_length": 1, "expected_subject": copy.deepcopy(s[2]["expected_subject"])})))
case("F2-SUBJECT-ABSENT", "association-duplicate", P, RM, _subjects(lambda s, fx: s.append(copy.deepcopy(s[0]))))
case("F2-SUBJECT-ABSENT", "subject-file-absent", P, RM, after(lambda fx: (fx.rec / "subject-m01.bin").unlink()))
case("F2-SUBJECT-ABSENT", "record-file-absent", P, RM, after(lambda fx: (fx.rec / "m02.rec").unlink()))

_SUBJECT_SHAPE = (
    ("not-list", lambda s, fx: None, lambda s: {"m01": s[0]}),
    ("over-bound", lambda s, fx: None, lambda s: [s[0]] * 4097),
    ("missing-key", lambda s, fx: s[0].pop("byte_offset"), None),
    ("extra-key", lambda s, fx: setkey(s[0], "extra", 1), None),
    ("record-bad-hash", lambda s, fx: setkey(s[0]["record"], "sha256", s[0]["record"]["sha256"].upper()), None),
    ("record-not-its-ref", lambda s, fx: setkey(s[0]["record"], "sha256", "9" * 64), None),
    ("offset-bool", lambda s, fx: setkey(s[0], "byte_offset", False), None),  # valid offset is 0 (QA N1)
    ("offset-str", lambda s, fx: setkey(s[0], "byte_offset", "0"), None),
    ("offset-negative", lambda s, fx: setkey(s[1], "byte_offset", -1), None),
    ("length-bool", lambda s, fx: setkey(s[2], "byte_length", True), None),  # valid length is 1 (QA N1)
    ("length-str", lambda s, fx: setkey(s[2], "byte_length", "1"), None),
    ("length-zero", lambda s, fx: setkey(s[1], "byte_length", 0), None),
    ("span-past-end", lambda s, fx: setkey(s[1], "byte_offset", s[1]["record"]["byte_length"]), None),  # redundant (N1)
    ("subject-bad-ref", lambda s, fx: setkey(s[0]["expected_subject"], "path", "rec/subject-m01.bin"), None),
    ("subject-length", lambda s, fx: setkey(s[0]["expected_subject"], "byte_length", 9), None),  # redundant (N1)
)
for _variant, _fn, _replace in _SUBJECT_SHAPE:
    if _replace is None:
        case("F2-SUBJECT-SHAPE", _variant, P, RM, _subjects(_fn))
    else:
        case("F2-SUBJECT-SHAPE", _variant, P, RM, swap("record_subjects", lambda s, fx, r=_replace: r(s)))


def _normalize(span: bytes, subject: bytes) -> dict:
    return join(edit("spans", lambda s, fx: setkey(s, "m02", span)), _subject("m02", subject))


case("F2-SUBJECT-NORMALIZE", "whitespace", P, RM, _normalize(b"ab cd", b"ab\tcd"))
case("F2-SUBJECT-NORMALIZE", "newline", P, RM, _normalize(b"ab\ncd", b"ab\rcd"))
case("F2-SUBJECT-NORMALIZE", "unicode", P, RM,
     _normalize(b"a" + chr(0x212B).encode() + b"b", b"a" + ("A" + chr(0x030A)).encode() + b"b"))  # ANGSTROM SIGN vs A + ring


def _claims_authority(r, fx):
    r["m01"] = r["m01"][:8] + b'{"trust":"TRUSTED","verdict":"ACCEPT","issuer":"native"}\n'
    return r


def _still_untrusted(candidate, fx):
    assert candidate.trust == "UNTRUSTED"
    assert candidate.required_native_checks == NATIVE
    assert "TRUSTED" not in repr(candidate).replace("UNTRUSTED", "")


case("F2-OPAQUE-AUTHORITY", "record-claims-authority", P, PASS, swap("records", _claims_authority), _still_untrusted)

# F2-CLOSURE: control bytes (PI), supplied source (SM), equalities (BI), kept cells (pass).
for _variant, _route, _rel in (
        ("publication", P, "PUBLICATION.json"), ("table", P, "PROJECT-KITS.json"),
        ("binding-authority", P, "authority/OPS-SLICE-A-PLAN.md"), ("schema", P, "schemas/inspect-2.schema.json"),
        ("security-identity", P, "authority/security22/IDENTITY.json"), ("source-closure", P, "SOURCE-CLOSURE.json"),
        ("cohort", P, "COHORT-INVENTORY.json"), ("original-inventory", P, "cohort/ORIGINAL-INVENTORY.json"),
        ("original-index", P, "cohort/ORIGINAL-INDEX.json"), ("expectations", P, "cohort/OLD-TO-NEW.json"),
        ("stdlib-inventory", P, "runtime/STDLIB-INVENTORY.json"), ("cohort-file", P, "cohort/orig/a.json")):
    case("F2-CLOSURE", _variant, _route, PI, after(lambda fx, rel=_rel: append(fx.qa / rel)))
case("F2-CLOSURE", "source-absent", P, SM, after(lambda fx: (fx.ops / "ops-host/forward.py").unlink()))
case("F2-CLOSURE", "source-bytes", P, SM, after(lambda fx: append(fx.ops / "ops-host/hostctl.py", b"#")))
case("F2-CLOSURE", "executable", P, SM, after(lambda fx: append(fx.bin / "python3", b"#")))
case("F2-CLOSURE", "stdlib-file", P, SM, after(lambda fx: (fx.std / "os.py").unlink()))
case("F2-CLOSURE", "release-root-missing", P, SM, ctx(lambda c: c["release_roots"].pop(1)))
case("F2-CLOSURE", "six-pin", P, BI, edit("window", lambda w, fx: setkey(w, "ops_host_sha256", "9" * 64)))
case("F2-CLOSURE", "schema-copy", P, BI,
     edit("repo_schema_raw", lambda r, fx: setkey(r, "inspect", dumps({"synthetic_schema": "changed"}))))

_KEPT_CELL = {"from": "cohort/orig/a.json", "pointer": "/x", "to": "cohort/missing.json", "sha256": "9" * 64,
              "byte_length": 3, "disposition": "intentional-negative", "failure": "missing-target"}


def _cells_kept(candidate, fx):
    references = candidate.source_closure["cohort"]["references"]
    assert [dict(item) for item in references][-1] == _KEPT_CELL
    assert references[1]["disposition"] == "unknown"


case("F2-CLOSURE", "bad-cells-kept", P, PASS,
     edit("cohort", lambda c, fx: c["references"].append(copy.deepcopy(_KEPT_CELL))), _cells_kept)


# F2-GRAPH
def _dup_node(closure, fx):
    closure["nodes"].append(copy.deepcopy(closure["nodes"][0]))
    sorted_nodes(closure)


def _dup_edge(closure, fx):
    closure["edges"].append(copy.deepcopy(closure["edges"][0]))
    sorted_edges(closure)


case("F2-GRAPH", "dup-node", P, BI, edit("closure", _dup_node))
case("F2-GRAPH", "dup-edge", P, BI, edit("closure", _dup_edge))
case("F2-GRAPH", "cycle", P, BI, add_edge("ops-hostwin", "ops-hostctl", "loads"))
case("F2-GRAPH", "bound", P, BI,
     edit("closure", lambda c, fx: setkey(c, "edges", [{"from": "a", "to": "b", "kind": "loads"}] * 65537)))
case("F2-GRAPH", "unresolved", P, SM, add_edge("ops-hostwin", "ops-missing", "imports"))
case("F2-GRAPH", "mode", P, BI, after(lambda fx: os.chmod(fx.ops / "ops-host/hostwin.py", 0o755)))
case("F2-GRAPH", "blob", P, BI, edit("closure", lambda c, fx: setkey(c["nodes"][0], "git_blob", "0" * 40)))


# ---------------------------------------------------------------------------
# F2-GRAMMAR: the four standalone APIs, real pins, no files.

def clean_publication() -> dict:
    return {"schema": "qa-ops-host-publication/3", "issuer": "qa", "project": PROJECT, "publication_id": PUB_ID,
            "project_kits": {"path": "PROJECT-KITS.json", "sha256": "a" * 64, "byte_length": 10},
            "calibration_manifests": [
                {"path": "calibrations/cal-1/manifest.json", "sha256": "b" * 64, "byte_length": 20},
                {"path": "calibrations/cal-2/manifest.json", "sha256": "c" * 64, "byte_length": 30}]}


def clean_binding() -> dict:
    return {"schema": "qa-ops-host-expected-receiver-binding/1", "issuer": "qa", "project": PROJECT,
            "publication_id": PUB_ID, "binding_id": "p3-inspect2-closed23-env1", "target": copy.deepcopy(TARGET),
            "authority": copy.deepcopy(REAL_AUTHORITY),
            "schemas": {key: {"path": path, "sha256": "e" * 64, "byte_length": 40}
                        for key, path in SCHEMA_PATHS.items()},
            "security_context": {"review": copy.deepcopy(REAL_REVIEW), "identity": {
                "path": "authority/security22/IDENTITY.json", "sha256": "f" * 64, "byte_length": 50}},
            "source_closure": {"path": "SOURCE-CLOSURE.json", "sha256": "1" * 64, "byte_length": 60}}


class DictSubclass(dict):
    pass


def _deep(levels: int) -> list:
    value: list = []
    for _ in range(levels):
        value = [value]
    return value


def _mutated(make, fn):
    value = make()
    fn(value)
    return value


class GCase(NamedTuple):
    api: str
    variant: str
    code: str
    make: Any  # () -> raw bytes or value


G: list[GCase] = []
_PUB_RAW = jraw(clean_publication())
_BIND_RAW = jraw(clean_binding())

for _variant, _code, _make in (
        ("dup-top", PI, lambda: b'{"issuer": "qa", ' + _PUB_RAW[1:]),
        ("dup-nested", PI, lambda: _PUB_RAW.replace(b'"project_kits": {', b'"project_kits": {"path": "x", ', 1)),
        ("unknown-key", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(v, "extra", 1)))),
        ("missing-key", PI, lambda: jraw(_mutated(clean_publication, lambda v: v.pop("project")))),
        ("issuer-literal", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(v, "issuer", "ops")))),
        ("builtin-list", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v, "calibration_manifests", {"a": v["calibration_manifests"][0]})))),
        ("bool-length", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v["project_kits"], "byte_length", True)))),
        ("bad-hash", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v["project_kits"], "sha256", "A" * 64)))),
        ("ref-extra-key", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v["project_kits"], "extra", 1)))),
        ("bad-path", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v["calibration_manifests"][0], "path", "calibrations/../manifest.json")))),
        ("unsorted", PI, lambda: jraw(_mutated(clean_publication, lambda v: v["calibration_manifests"].reverse()))),
        ("over-cap", PI, lambda: _PUB_RAW + b" " * (16777217 - len(_PUB_RAW))),
        ("depth", PI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v, "calibration_manifests", _deep(40))))),
        ("invalid-utf8", PI, lambda: _PUB_RAW.replace(b'"qa"', b'"q\xff"', 1)),
        ("nonfinite", PI, lambda: _PUB_RAW.replace(b'"byte_length": 10', b'"byte_length": NaN', 1)),
        ("not-bytes", PI, lambda: _PUB_RAW.decode()),
        ("schema-version", SI, lambda: jraw(_mutated(clean_publication, lambda v: setkey(
            v, "schema", "qa-ops-host-publication/2"))))):
    G.append(GCase("loads_publication", _variant, _code, _make))

for _variant, _code, _make in (
        ("unknown-key", PI, lambda: _mutated(clean_publication, lambda v: setkey(v, "extra", 1))),
        ("missing-key", PI, lambda: _mutated(clean_publication, lambda v: v.pop("project"))),
        ("bool-length", PI, lambda: _mutated(clean_publication, lambda v: setkey(v["project_kits"], "byte_length", True))),
        ("dict-subclass", PI, lambda: DictSubclass(clean_publication())),
        ("not-dict", PI, lambda: [clean_publication()]),
        ("schema-version", SI, lambda: _mutated(clean_publication, lambda v: setkey(
            v, "schema", "qa-ops-host-publication/2")))):
    G.append(GCase("validate_publication", _variant, _code, _make))

for _variant, _code, _make in (
        ("dup-top", BI, lambda: b'{"issuer": "qa", ' + _BIND_RAW[1:]),
        ("dup-nested", BI, lambda: _BIND_RAW.replace(b'"source_closure": {', b'"source_closure": {"path": "x", ', 1)),
        ("unknown-key", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(v, "extra", 1)))),
        ("missing-key", BI, lambda: jraw(_mutated(clean_binding, lambda v: v.pop("schemas")))),
        ("binding-id-literal", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(v, "binding_id", "other")))),
        ("builtin-list", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v, "schemas", list(v["schemas"].values()))))),
        ("bool-length", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["source_closure"], "byte_length", True)))),
        ("bad-hash", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["source_closure"], "sha256", "A" * 64)))),
        ("authority-pin", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["authority"]["base"], "sha256", "0" * 64)))),
        ("schema-path", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["schemas"]["inspect"], "path", "schemas/inspect-3.schema.json")))),
        ("closure-path", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["source_closure"], "path", "OTHER.json")))),
        ("security-pin", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["security_context"]["review"], "byte_length", 1)))),
        ("over-cap", BI, lambda: _BIND_RAW + b" " * (65537 - len(_BIND_RAW))),
        ("depth", BI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(v, "schemas", _deep(40))))),
        ("invalid-utf8", BI, lambda: _BIND_RAW.replace(b'"qa"', b'"q\xff"', 1)),
        ("not-bytes", BI, lambda: _BIND_RAW.decode()),
        ("schema-version", SI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v, "schema", "qa-ops-host-expected-receiver-binding/2")))),
        ("target-literal", SI, lambda: jraw(_mutated(clean_binding, lambda v: setkey(
            v["target"], "receipt_schema", "ops-host-receipt/2")))),
        ("caller-profiles-order", SI, lambda: jraw(_mutated(clean_binding, lambda v: v["target"][
            "caller_profiles"].reverse())))):
    G.append(GCase("loads_expected_binding", _variant, _code, _make))

for _variant, _code, _make in (
        ("unknown-key", BI, lambda: _mutated(clean_binding, lambda v: setkey(v, "extra", 1))),
        ("missing-key", BI, lambda: _mutated(clean_binding, lambda v: v.pop("schemas"))),
        ("bool-length", BI, lambda: _mutated(clean_binding, lambda v: setkey(v["source_closure"], "byte_length", True))),
        ("dict-subclass", BI, lambda: DictSubclass(clean_binding())),
        ("not-dict", BI, lambda: [clean_binding()]),
        ("schema-version", SI, lambda: _mutated(clean_binding, lambda v: setkey(
            v, "schema", "qa-ops-host-expected-receiver-binding/2")))):
    G.append(GCase("validate_expected_binding", _variant, _code, _make))

_GRAMMAR_CLEAN = {"loads_publication": lambda: jraw(clean_publication()), "validate_publication": clean_publication,
                  "loads_expected_binding": lambda: jraw(clean_binding()), "validate_expected_binding": clean_binding}

# ---------------------------------------------------------------------------
# F2-DRIFT: every observation kind at every boundary.

DRIFT_KINDS = (
    ("window", P, lambda fx: fx.win / "WINDOW.json"),
    ("publication", P, lambda fx: fx.qa / "PUBLICATION.json"),
    ("table", P, lambda fx: fx.qa / "PROJECT-KITS.json"),
    ("manifest", K, lambda fx: fx.qa / MANIFEST_REL),
    ("binding", P, lambda fx: fx.qa / BINDING_PATH),
    ("authority", P, lambda fx: fx.qa / "authority/OPS-SLICE-A-PLAN.md"),
    ("schema", P, lambda fx: fx.qa / "schemas/inspect-2.schema.json"),
    ("closure", P, lambda fx: fx.qa / "SOURCE-CLOSURE.json"),
    ("source", P, lambda fx: fx.ops / "ops-host/hostwin.py"),
    ("executable", P, lambda fx: fx.bin / "python3"),
    ("stdlib", P, lambda fx: fx.std / "os.py"),
    ("cohort", P, lambda fx: fx.qa / "COHORT-INVENTORY.json"),
    ("kit", P, lambda fx: fx.kit / "KIT.tar"),
    ("sums", P, lambda fx: fx.kit / "SHA256SUMS"),
    ("domain", P, lambda fx: fx.kit / "app/server.py"),
    ("record", P, lambda fx: fx.rec / "m01.rec"),
    ("subject", P, lambda fx: fx.rec / "subject-m01.bin"),
)
BOUNDARIES = ("load-complete", "receiving", "before-count")
DRIFT = [(kind, route, path, boundary) for kind, route, path in DRIFT_KINDS for boundary in BOUNDARIES]

# Bites: the actual guard switched off loses exactly that refusal; the clean twin is unchanged.
_BITE_TABLE = next(c for c in CASES if (c.fid, c.variant) == ("F2-SELECT-NONSEL-DUP", "identical"))
_BITE_MANIFEST = next(c for c in CASES if (c.fid, c.variant) == ("F2-MANIFEST-DUP-ID", "nonselected-pair"))
_BITE_SUBJECT = next(c for c in CASES if (c.fid, c.variant) == ("F2-SUBJECT-UNEQUAL", "m01"))
BITES = (
    ("F2-BITE-SELECT", "table", _BITE_TABLE, {"_table_selectors_unique": lambda rows: None}),
    ("F2-BITE-SELECT", "manifest", _BITE_MANIFEST, {"_manifest_ids_unique": lambda entries: None}),
    ("F2-BITE-SUBJECT", "subject", _BITE_SUBJECT, {"_subject_equal": lambda *args: True}),
)

# The planned table of H-P3-P2-1, checked at collection.
EXPECTED_VARIANTS = {
    "F2-CONTEXT": 6, "F2-WINDOW-REF": 10, "F2-GRAMMAR": 48, "F2-SELECT-ZERO": 2, "F2-SELECT-NONSEL-DUP": 2,
    "F2-PROJECT-NONSEL-BAD": 7, "F2-SELECT-AMBIGUOUS": 2, "F2-MANIFEST-SCHEMA": 2, "F2-MANIFEST-NONSEL-BAD": 4,
    "F2-MANIFEST-DUP-ID": 2, "F2-MANIFEST-PATH-ID": 1, "F2-BINDING-REF-PATH": 2, "F2-BINDING-REF-BYTES": 2,
    "F2-MANIFEST-UNLISTED": 2, "F2-ROOT-LISTED-DUP": 3, "F2-PROJECT-SIX": 14, "F2-CALIB-FIVE": 11,
    "F2-CALIB-FIFTEEN": 17, "F2-CALIB-ENTRY": 10, "F2-KIT-ABSENT": 4, "F2-KIT-SHAPE": 22, "F2-KIT-BYTE": 2,
    "F2-SUMS-BYTE": 2, "F2-SUMS-MEMBER": 5, "F2-KIT-EXTRA-DOMAIN": 2, "F2-SUBJECT-UNEQUAL": 2,
    "F2-SUBJECT-ABSENT": 5, "F2-SUBJECT-SHAPE": 15, "F2-SUBJECT-NORMALIZE": 3, "F2-OPAQUE-AUTHORITY": 1,
    "F2-CLOSURE": 20, "F2-GRAPH": 7, "F2-DRIFT": 51, "F2-BITE-SELECT": 2, "F2-BITE-SUBJECT": 1,
}
_ACTUAL = Counter(c.fid for c in CASES)
_ACTUAL["F2-GRAMMAR"] = len(G)
_ACTUAL["F2-DRIFT"] = len(DRIFT)
_ACTUAL.update(fid for fid, *_ in BITES)
assert dict(_ACTUAL) == EXPECTED_VARIANTS, (dict(_ACTUAL), EXPECTED_VARIANTS)
assert len({(c.fid, c.variant) for c in CASES}) == len(CASES)


def _ids(items, key):
    return [key(item) for item in items]


# ---------------------------------------------------------------------------
# N and C tests per variant.

@pytest.mark.parametrize("c", CASES, ids=_ids(CASES, lambda c: f"{c.fid}-{c.variant}-N"))
def test_load_n(tmp_path, c):
    fx = Fx(tmp_path, c.route, c.hooks)
    if c.code == PASS:
        candidate = load(fx)
        assert_untrusted(candidate)
        c.check(candidate, fx)
    else:
        assert refusal(lambda: load(fx)) == c.code


@pytest.mark.parametrize("c", CASES, ids=_ids(CASES, lambda c: f"{c.fid}-{c.variant}-C"))
def test_load_c(tmp_path, c):
    fx = Fx(tmp_path, c.route)
    candidate = load(fx)
    assert_untrusted(candidate)
    assert candidate.route == c.route
    mod.recheck_candidate(candidate, "load-complete")


@pytest.mark.parametrize("g", G, ids=_ids(G, lambda g: f"F2-GRAMMAR-{g.api}-{g.variant}-N"))
def test_grammar_n(g):
    api = getattr(mod, g.api)
    value = g.make()
    assert refusal(lambda: api(value)) == g.code


@pytest.mark.parametrize("g", G, ids=_ids(G, lambda g: f"F2-GRAMMAR-{g.api}-{g.variant}-C"))
def test_grammar_c(g):
    result = getattr(mod, g.api)(_GRAMMAR_CLEAN[g.api]())
    assert result["trust"] == "UNTRUSTED"
    assert set(result) == {"trust", "value"}
    expected = clean_publication() if "publication" in g.api else clean_binding()
    assert result["value"] == expected


@pytest.mark.parametrize("d", DRIFT, ids=_ids(DRIFT, lambda d: f"F2-DRIFT-{d[0]}-{d[3]}-N"))
def test_drift_n(tmp_path, d):
    kind, route, path, boundary = d
    fx = Fx(tmp_path, route)
    candidate = load(fx)
    append(path(fx), b"x")
    assert refusal(lambda: mod.recheck_candidate(candidate, boundary)) == SD
    assert candidate.trust == "UNTRUSTED"


@pytest.mark.parametrize("d", DRIFT, ids=_ids(DRIFT, lambda d: f"F2-DRIFT-{d[0]}-{d[3]}-C"))
def test_drift_c(tmp_path, d):
    kind, route, path, boundary = d
    fx = Fx(tmp_path, route)
    candidate = load(fx)
    assert path(fx).exists()
    assert mod.recheck_candidate(candidate, boundary) is None
    assert_untrusted(candidate)


@pytest.mark.parametrize("b", BITES, ids=_ids(BITES, lambda b: f"{b[0]}-{b[1]}-N"))
def test_bite_n(tmp_path, b):
    fid, variant, c, patches = b
    with_guard = Fx(tmp_path / "with", c.route, c.hooks)
    assert refusal(lambda: load(with_guard)) == c.code
    without_guard = Fx(tmp_path / "without", c.route, c.hooks)
    assert_untrusted(load(without_guard, patches))  # the switched-off guard was the one firing


@pytest.mark.parametrize("b", BITES, ids=_ids(BITES, lambda b: f"{b[0]}-{b[1]}-C"))
def test_bite_c(tmp_path, b):
    fid, variant, c, patches = b
    plain = load(Fx(tmp_path / "plain", c.route))
    bitten = load(Fx(tmp_path / "bitten", c.route), patches)
    assert_untrusted(plain)
    assert_untrusted(bitten)
    assert len(plain.reads) == len(bitten.reads)
    # Different folders, so absolute paths (and hashes of documents naming them) differ; names must not.
    assert [read.ref["path"] for read in plain.reads] == [read.ref["path"] for read in bitten.reads]
    assert plain.selection["record_subjects"][0]["byte_length"] == bitten.selection["record_subjects"][0]["byte_length"]
    if c.route == "project":  # kit and SUMS hashes hold no path
        assert dict(plain.expected_binding) == dict(bitten.expected_binding)


# ---------------------------------------------------------------------------
# The 14 extras.

def test_codes_pin():
    assert mod.CODES == (CM, IU, PI, MS, AM, BI, SI, SM, SD, RM, EI)
    assert mod.CODES == mod._files.CODES
    assert mod.TargetRefused is not mod._files.TargetRefused


def test_refusal_text_is_only_the_code():
    error = mod.TargetRefused(BI)
    assert (str(error), error.args, error.code, repr(error)) == (BI, (BI,), BI, f"TargetRefused('{BI}')")
    assert isinstance(error, ValueError)


def test_unknown_code_is_not_a_refusal():
    for code in ("TARGET_OTHER", 1, None):
        with pytest.raises(TypeError):
            mod.TargetRefused(code)


def test_native_checks_constant():
    assert mod.REQUIRED_NATIVE_CHECKS == NATIVE
    assert type(mod.REQUIRED_NATIVE_CHECKS) is tuple
    assert mod.BOUNDARIES == BOUNDARIES


def test_candidate_is_immutable_untrusted_data(tmp_path):
    candidate = load(Fx(tmp_path, P))
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.trust = "TRUSTED"
    with pytest.raises(TypeError):
        candidate.binding["target"] = {}
    with pytest.raises(TypeError):
        dataclasses.replace(candidate, trust="TRUSTED")
    with pytest.raises(TypeError):
        dataclasses.replace(candidate, required_native_checks=())
    assert [field.name for field in dataclasses.fields(candidate)] == [
        "trust", "route", "target", "publication", "binding", "source_closure", "expected_window_sha256",
        "expected_binding", "selection", "reads", "required_native_checks"]


def test_candidate_repr_holds_no_data(tmp_path):
    candidate = load(Fx(tmp_path, P))
    text = f"CandidateTarget(trust='UNTRUSTED', route='project', reads={len(candidate.reads)})"
    assert repr(candidate) == str(candidate) == text
    assert str(tmp_path) not in repr(candidate)


def test_no_input_mutation_or_alias(tmp_path):
    fx = Fx(tmp_path, P)
    before = copy.deepcopy(fx.context)
    candidate = load(fx)
    assert fx.context == before
    fx.context["expected_binding"]["kit_id"] = "changed"
    fx.context["kit_evidence"]["files"].clear()
    assert candidate.expected_binding["kit_id"] == "kit-1"
    assert len(candidate.selection["kit_evidence"]["files"]) == 3


def test_r1_is_the_received_reader():
    assert Path(mod._files.__file__).resolve() == R1_PATH
    assert sha(R1_PATH.read_bytes()) == R1_SHA256
    assert mod.CandidateTarget.__module__ == "ops_host_binding"


def test_static_source_has_no_exec_subprocess_git_or_producer():
    tree = ast.parse(MODULE_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported == {"__future__", "hashlib", "json", "re", "sys", "dataclasses", "pathlib", "types", "typing",
                        "ops_host_binding_files"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    banned = {"exec", "eval", "__import__", "system", "popen", "subprocess", "listdir", "scandir", "walk",
              "glob", "iterdir", "open", "read_bytes", "read_text", "import_module"}
    assert not names & banned
    source = MODULE_PATH.read_text()
    for word in ("hostbinding_schema", "stage_binding_schema", "agent_tools", "first_app_p3"):
        assert word not in source


def test_grammar_apis_copy_and_never_mutate():
    for api, make in (("validate_publication", clean_publication), ("validate_expected_binding", clean_binding)):
        value = make()
        before = copy.deepcopy(value)
        result = getattr(mod, api)(value)
        assert value == before and result["value"] == value
        assert result["value"] is not value
        assert all(result["value"][key] is not value[key] for key in value if isinstance(value[key], (dict, list)))
    first = mod.loads_publication(jraw(clean_publication()))
    second = mod.loads_publication(jraw(clean_publication()))
    assert first == second and first["value"] is not second["value"]
    assert mod.loads_expected_binding(jraw(clean_binding()))["value"] == clean_binding()


def test_recheck_refuses_an_unknown_boundary(tmp_path):
    candidate = load(Fx(tmp_path, P))
    for boundary in ("later", "", None, b"receiving"):
        assert refusal(lambda b=boundary: mod.recheck_candidate(candidate, b)) == EI


def test_recheck_refuses_what_is_not_a_candidate(tmp_path):
    candidate = load(Fx(tmp_path, P))
    fake = {field.name: getattr(candidate, field.name) for field in dataclasses.fields(candidate)}
    for value in (None, fake, object()):
        assert refusal(lambda v=value: mod.recheck_candidate(v, "receiving")) == EI


def test_trust_never_changes_across_boundaries(tmp_path):
    candidate = load(Fx(tmp_path, P))
    for boundary in BOUNDARIES:
        assert mod.recheck_candidate(candidate, boundary) is None
        assert_untrusted(candidate)
    assert not hasattr(candidate, "verified")


def test_calibration_clean_full(tmp_path):
    fx = Fx(tmp_path, K)
    candidate = load(fx)
    assert_untrusted(candidate)
    assert candidate.route == "calibration"
    assert dict(candidate.selection["entry"])["entry"] == "e1"
    assert candidate.selection["calibration_selection"]["security_receipt_id"] == "P3-CAL-1"
    assert candidate.target["caller_profiles"] == tuple(TARGET["caller_profiles"])
    assert candidate.reads[0].ref["path"] == "WINDOW.json"
    assert candidate.selection["kit_evidence"]["kit"] is None
    assert candidate.expected_binding["entry"] == "e1"
