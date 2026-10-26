"""Tests for the metadata-only candidate-admission v1 compiler (Architecture #311).

Expected answers never come from the compiler or the codec under test:
* the tiny case expects Temper #192's handwritten wire bytes and pins;
* the 14x3 case decodes Architecture #306/#316's independent literals by storage
  decoding only, compares the compiler's decoded output with them, and expects
  bytes from a separate test-side stdlib encoder (float-free fixture only).
Fixed-authority controls keep the original out-of-band pins. Semantic-guard
controls are explicitly re-signed by this test, acting as an independent
approver of a deliberately inconsistent candidate, to reach one codec guard;
they are never the authority-substitution control. No engine package, provider,
environment value, network, database or live configuration is used.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import copy
import hashlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
COMPILER_PATH = ROOT / "configs/architecture/bin/context_profile_admission_compile.py"
CODEC_PATH = ROOT / "temper_ai/config/admission_contract.py"
SCHEMA_PATH = ROOT / "docs/schemas/candidate-admission-v1.schema.json"
SPEC_PATH = ROOT / "docs/candidate-admission-contract.md"
FIXTURES = ROOT / "tests/test_config/fixtures/candidate_admission_v1"
ORACLES = ROOT / "configs/architecture/stages/context_profile"
OLD = ORACLES / "admission_oracles"
SUP = ORACLES / "admission_oracles_v1_supplement"
EVIDENCE_DIR = None  # Set only by the explicit --evidence-output campaign below.

# Literal pins of the composed, unchanged dependencies (never computed here).
CONTRACT_FILES = {
    CODEC_PATH: "f9b0f36ed20afaecd12654cd80a203214f3f2d5727f4668fc0c1926fa3df1c34",
    SCHEMA_PATH: "426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d",
    SPEC_PATH: "8932a4b97d0d08bea6a919223f83922804d08486545d94d747886253b5825ba7",
}
OLD_MANIFEST_SHA256 = "65c388386130b7707cb241be6e5ed59cbf5ebab403e7563051e038c34f696161"
SUP_MANIFEST_SHA256 = "689771d91ffe15b4ba219a1fea45a81c1c1b55345623fed91997aa4990962374"
# Synthetic source tuple label: the #306 declaration commit/tree the #316 field
# inventories were read from. Not an installed-source or runtime attestation.
SYNTHETIC_COMMIT = "56b833e6e6e990e966a1e61a204fd92c5c9f690a"
SYNTHETIC_TREE = "7094010accaf2164e2cb54fd9f20ba5f4006f22a"
IDENTITY = ("kind", "name", "schema_version", "origin", "config_json")

spec = importlib.util.spec_from_file_location("context_profile_admission_compile_under_test", COMPILER_PATH)
assert spec is not None and spec.loader is not None
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


# ---------------------------------------------------------------- test-side only
def strict_load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, "duplicate fixture key"
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def caj(value):
    """Independent CAJ-1 bytes for float-free JSON: stdlib only, not the codec."""
    def check(item):
        if type(item) is dict:
            assert all(type(key) is str for key in item), "string keys"
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        else:
            assert type(item) in (str, int, bool, type(None)), "float-free fixture only"
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def pin(domain, data):
    return hashlib.sha256(b"temper-admission/v1\0" + domain.encode("ascii") + b"\0" + data).hexdigest()


def text(value):
    return caj(value).decode("utf-8")


def encode_wire(descriptor, raws):
    """Test-side wire from authoring objects, following #316 wire-mapping.json."""
    d, raws = copy.deepcopy(descriptor), copy.deepcopy(raws)
    for raw in raws:
        raw["config_json"] = text(raw["config_json"])
    raws.sort(key=lambda raw: (raw["kind"], raw["name"]))
    d["records"] = [{**{key: raw[key] for key in IDENTITY[:4]},
                     "raw_sha256": pin("raw-record", caj({key: raw[key] for key in IDENTITY}))}
                    for raw in raws]
    for key in ("metadata_inputs_json", "request_options_json"):
        d[key] = text(d[key])
    d["graph"]["workflow_json"] = text(d["graph"]["workflow_json"])
    for node in d["graph"]["nodes"]:
        node["node_json"] = text(node["node_json"])
        if node["factory"] is not None:
            node["factory"]["config_json"] = text(node["factory"]["config_json"])
    for position in d["positions"]:
        position["agent_config_json"] = text(position["agent_config_json"])
    for script in d["scripts"]:
        script["variables_json"] = text(script["variables_json"])
    return caj(d), caj(raws)


def approve(descriptor, raws, label="synthetic-independent-approver"):
    """Out-of-band authority over independently encoded bytes (never compiler output)."""
    wire, _ = encode_wire(descriptor, raws)
    return {"expected_descriptor_sha256": pin("descriptor", wire),
            "expected_source_sha256": pin("source", caj(descriptor["source"])),
            "authorized_caller_label": label, "receipt_id": "synthetic-receipt-" + label}


def table(columns, rows):
    assert len(set(columns)) == len(columns)
    for row in rows:
        assert type(row) is list and len(row) == len(columns), "complete literal row"
        yield dict(zip(columns, copy.deepcopy(row), strict=True))


def oracle_inputs():
    """Storage decoding of #306/#316 literals into authoring form; no inference."""
    mapping = strict_load(SUP / "wire-mapping.json")
    closure = strict_load(SUP / "INPUT/closure.json")
    native = strict_load(SUP / "INPUT/native.json")
    graph = strict_load(SUP / "EXPECTED/graph.json")
    identities = strict_load(SUP / "EXPECTED/identities.json")
    request = strict_load(SUP / "EXPECTED/request.json")
    facts = strict_load(SUP / "source-facts.json")
    old_positions = strict_load(OLD / "expected-positions.json")["EXPECTED"]
    old_graph = strict_load(OLD / "expected-graph.json")["EXPECTED"]

    def raw(key, config):
        kind, name = key.split(":", 1)  # Only the explicit namespace is removed.
        return {"format": mapping["rawRecord"]["format"]["literal"], "kind": kind, "name": name,
                "schema_version": closure["schema_version"], "origin": copy.deepcopy(closure["origin"]),
                "config_json": config, "file_base64": closure["file_base64"]}

    raws = [raw(key, copy.deepcopy(config)) for key, config in closure["records"].items()]
    for row in table(native["columns"], native["rows"]):
        key = row.pop("raw_record_id")
        row.pop("node_path")
        raws.append(raw(key, {**copy.deepcopy(native["envelope"]), "single_call": row}))

    rows = {}
    for row in table(graph["columns"], graph["rows"]):
        path = tuple(row.pop("path"))
        assert path not in rows and not row.keys() & graph["node_envelope"].keys()
        rows[path] = {**copy.deepcopy(graph["node_envelope"]), **row}

    def node_object(path):
        node = copy.deepcopy(rows[path])
        if node["nodes"] is not None:  # Explicit child references only.
            node["nodes"] = [node_object(tuple(child)) for child in node["nodes"]]
        return node

    workflow = copy.deepcopy(graph["workflow"])
    workflow["nodes"] = [node_object(tuple(child)) for child in workflow["nodes"]]

    natives = {}
    for row in table(old_positions["columns"], old_positions["rows"]):
        old_id = row.pop("position_id")
        row.pop("node_path")
        row.pop("predecessor")
        natives[old_id] = {**copy.deepcopy(old_positions["native_envelope"]), "single_call": row}
    factories, positions, scripts = {}, [], {}
    for identity in table(identities["columns"], identities["rows"]):
        config = natives[identity.pop("old_position")]
        factories[tuple(identity["node_path"])] = {**facts["factories"]["single_call"],
                                                   "config_json": copy.deepcopy(config)}
        positions.append({**identity, "agent_config_json": copy.deepcopy(config)})
    for root in table(identities["root_columns"], identities["roots"]):
        for path, old_key in root["script_expected_bindings"]:
            config = {**copy.deepcopy(old_graph["script_agents"][old_key]),
                      "_KNOWN_FIELDS": copy.deepcopy(facts["node_accepted_keys"])}
            factories[tuple(path)] = {**facts["factories"]["script"], "config_json": config}
            template = config["script_template"]
            scripts[tuple(path)] = {"node_path": list(path), "template_utf8": template,
                                    "template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
                                    "variables_json": copy.deepcopy(root["script_variables"])}
    meta = request["descriptor_metadata"]
    descriptor = {
        "format": mapping["descriptor"]["format"]["literal"],
        "profile": mapping["descriptor"]["profile"]["literal"],
        **{key: meta[key] for key in ("mode", "candidate_identity", "logical_run_id", "execution_uuid",
                                      "workflow_name", "workspace_path")},
        "metadata_inputs_json": copy.deepcopy(request["metadata_inputs"]),
        "request_options_json": copy.deepcopy(request["options"]),
        "source": {"engine_commit": SYNTHETIC_COMMIT, "engine_tree": SYNTHETIC_TREE,
                   "binding_abi": mapping["source"]["binding_abi"]["literal"],
                   "field_sets": {"workflow": facts["wire_field_sets"]["workflow"],
                                  "node": facts["wire_field_sets"]["node"],
                                  "native": facts["wire_field_sets"]["native"],
                                  "request": request["field_names"]}},
        "graph": {"workflow_json": workflow,
                  "nodes": [{"path": list(path), "node_json": node_object(path),
                             "factory": None if rows[path]["type"] == "stage" else factories[path]}
                            for path in rows]},
        "positions": positions,
        "scripts": [scripts[path] for path in rows if path in scripts],
    }
    return descriptor, raws


def fixture_inputs():
    """Authoring form of #192's handwritten wire: decode its JSON-text members."""
    descriptor = json.loads((FIXTURES / "descriptor.json").read_bytes())
    del descriptor["records"]
    for key in ("metadata_inputs_json", "request_options_json"):
        descriptor[key] = json.loads(descriptor[key])
    descriptor["graph"]["workflow_json"] = json.loads(descriptor["graph"]["workflow_json"])
    for node in descriptor["graph"]["nodes"]:
        node["node_json"] = json.loads(node["node_json"])
        if node["factory"] is not None:
            node["factory"]["config_json"] = json.loads(node["factory"]["config_json"])
    for position in descriptor["positions"]:
        position["agent_config_json"] = json.loads(position["agent_config_json"])
    for script in descriptor["scripts"]:
        script["variables_json"] = json.loads(script["variables_json"])
    raws = []
    for name in ("raw-call.json", "raw-prepare.json", "raw-workflow.json"):
        raw = json.loads((FIXTURES / name).read_bytes())
        raw["config_json"] = json.loads(raw["config_json"])
        raws.append(raw)
    return descriptor, raws


def exact(left, right):
    """Equality that also distinguishes bool/int/float/null and key sets."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(exact(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def decoded(artifacts):
    """Decode actual output for semantic comparison (stdlib json only)."""
    d = json.loads(artifacts["descriptor.json"])
    for key in ("metadata_inputs_json", "request_options_json"):
        d[key] = json.loads(d[key])
    d["graph"]["workflow_json"] = json.loads(d["graph"]["workflow_json"])
    for node in d["graph"]["nodes"]:
        node["node_json"] = json.loads(node["node_json"])
        if node["factory"] is not None:
            node["factory"]["config_json"] = json.loads(node["factory"]["config_json"])
    for position in d["positions"]:
        position["agent_config_json"] = json.loads(position["agent_config_json"])
    for script in d["scripts"]:
        script["variables_json"] = json.loads(script["variables_json"])
    raws = json.loads(artifacts["raw-records.json"])
    for raw in raws:
        raw["config_json"] = json.loads(raw["config_json"])
    return d, raws


def node(descriptor, path):
    return next(n for n in descriptor["graph"]["nodes"] if n["path"] == path)


def position(descriptor, position_id):
    return next(p for p in descriptor["positions"] if p["position_id"] == position_id)


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controls = []
        cls.compiler = subject.Compiler(CODEC_PATH, SCHEMA_PATH)
        cls.pins = strict_load(FIXTURES / "pins.json")
        cls.fixture_authority = {
            "expected_descriptor_sha256": cls.pins["descriptor"],
            "expected_source_sha256": cls.pins["source"],
            "authorized_caller_label": "synthetic-independent-reviewer",
            "receipt_id": "synthetic-independent-receipt",
        }
        descriptor, raws = oracle_inputs()
        cls.expected_descriptor, cls.expected_raws = encode_wire(descriptor, raws)
        cls.authority = approve(descriptor, raws)
        cls.clean = cls.compiler.compile(descriptor, raws, cls.authority)

    @classmethod
    def tearDownClass(cls):
        if EVIDENCE_DIR is not None:
            with (EVIDENCE_DIR / "controls.json").open("xb") as stream:
                stream.write(json.dumps(cls.controls, indent=1).encode())

    def retain(self, label, artifacts):
        """Retain ACTUAL outputs in the explicit campaign; nothing is regenerated."""
        if EVIDENCE_DIR is not None:
            directory = EVIDENCE_DIR / label
            directory.mkdir()
            for name, data in artifacts.items():
                with (directory / name).open("xb") as stream:
                    stream.write(data)

    def refused(self, code, operation, why):
        try:
            operation()
        except (subject.CompilerRefused, self.compiler.contract.AdmissionRefused) as exc:
            observed = str(exc)
        else:
            observed = "accepted_unexpectedly"
        result = {"test": self.id().split(".")[-1], "control": why,
                  "expected_code": code, "observed_code": observed}
        self.controls.append(result)
        print("CONTROL", json.dumps(result, separators=(",", ":")))  # Fixed codes only.
        self.assertEqual(observed, code, why)

    def compile_fixed(self, descriptor, raws):
        return lambda: self.compiler.compile(descriptor, raws, self.authority)

    def compile_signed(self, descriptor, raws):
        authority = approve(descriptor, raws, "semantic-guard-control")
        return lambda: self.compiler.compile(descriptor, raws, authority)

    # ------------------------------------------------------------ clean cases
    def test_00_contract_fixture_exact_handwritten_wire(self):
        descriptor, raws = fixture_inputs()
        first = self.compiler.compile(descriptor, raws, self.fixture_authority)
        self.retain("contract-192-clean", first)
        self.assertEqual(first["descriptor.json"], (FIXTURES / "descriptor.json").read_bytes())
        self.assertEqual(first["raw-records.json"], b"[" + b",".join(
            (FIXTURES / name).read_bytes() for name in ("raw-call.json", "raw-prepare.json", "raw-workflow.json")) + b"]")
        manifest = json.loads(first["manifest.json"])
        self.assertEqual(manifest["digests"], {"descriptor": self.pins["descriptor"], "source": self.pins["source"],
                                               "raw_closure": self.pins["closure"], "graph": self.pins["graph"]})
        self.assertIs(manifest["runnable"], False)
        self.assertEqual((manifest["custody"], manifest["unresolved_root_policies"]), ("unresolved", 1))
        # The handwritten root variant: supplied synthetic policy is still not runnable.
        descriptor["positions"][0]["root_policy"] = strict_load(FIXTURES / "root-policy.json")
        authority = {**self.fixture_authority, "expected_descriptor_sha256": self.pins["root-descriptor"]}
        manifest = json.loads(self.compiler.compile(descriptor, raws, authority)["manifest.json"])
        self.assertEqual((manifest["custody"], manifest["runnable"]), ("supplied_not_verified", False))

    def test_01_oracle_14x3_exact_semantics_and_independent_bytes(self):
        descriptor, raws = oracle_inputs()
        before = json.dumps([descriptor, raws], sort_keys=True)
        repeat = self.compiler.compile(descriptor, raws, self.authority)
        self.retain("oracle-14x3-clean", self.clean)
        self.retain("oracle-14x3-repeat", repeat)
        self.assertEqual(json.dumps([descriptor, raws], sort_keys=True), before, "input ownership")
        self.assertEqual(self.clean, repeat, "byte-identical repeat")
        self.assertEqual(self.clean["descriptor.json"], self.expected_descriptor)
        self.assertEqual(self.clean["raw-records.json"], self.expected_raws)
        actual, actual_raws = decoded(self.clean)
        records = actual.pop("records")
        self.assertTrue(exact(actual, descriptor), "decoded descriptor equals independent literals")
        self.assertTrue(exact(actual_raws, sorted(raws, key=lambda r: (r["kind"], r["name"]))))
        self.assertEqual([(r["kind"], r["name"]) for r in records], [(r["kind"], r["name"]) for r in actual_raws])
        # Literal inventory counts (independent of compiler and #316 helpers).
        types = Counter(n["node_json"]["type"] if n["factory"] is None else n["factory"]["type"]
                        for n in actual["graph"]["nodes"])
        self.assertEqual((len(actual_raws), len(actual["graph"]["nodes"]), len(actual["positions"]),
                          len(actual["scripts"])), (60, 126, 42, 70))
        self.assertEqual(types, {"stage": 14, "single_call": 42, "script": 70})
        self.assertEqual(Counter(r["kind"] for r in actual_raws), {"workflow": 1, "stage": 14, "agent": 45})
        # Repeated slot labels across distinct output roots are permitted.
        self.assertEqual(Counter(p["slot"] for p in actual["positions"]), {"A1": 14, "A2": 14, "A3": 14})
        self.assertEqual(len({p["agent_config_json"]["single_call"]["output_root"] for p in actual["positions"]}), 42)
        # Full metadata: _KNOWN_FIELDS projection, null/absence preserved, custody unresolved.
        facts = strict_load(SUP / "source-facts.json")
        self.assertEqual(actual["graph"]["workflow_json"]["_KNOWN_FIELDS"], facts["workflow_accepted_keys"])
        for n in actual["graph"]["nodes"]:
            self.assertEqual(n["node_json"]["_KNOWN_FIELDS"], facts["node_accepted_keys"])
            if n["factory"] is not None and n["factory"]["type"] == "script":
                self.assertEqual(n["factory"]["config_json"]["_KNOWN_FIELDS"], facts["node_accepted_keys"])
        for p in actual["positions"]:
            self.assertIsNone(p["root_policy"])
            self.assertFalse(set(facts["native_absent_optional_keys"]) & set(p["agent_config_json"]["single_call"]))
        manifest = json.loads(self.clean["manifest.json"])
        self.assertEqual(manifest["digests"]["descriptor"], self.authority["expected_descriptor_sha256"])
        self.assertEqual(manifest["digests"]["source"], self.authority["expected_source_sha256"])
        self.assertEqual(manifest["digests"]["raw_closure"], pin("raw-closure", self.expected_raws))
        self.assertEqual(manifest["digests"]["graph"],
                         pin("graph", caj(json.loads(self.expected_descriptor)["graph"])))
        self.assertEqual((manifest["status"], manifest["runnable"], manifest["custody"],
                          manifest["unresolved_root_policies"], manifest["mode"]),
                         ("metadata_verified_not_admitted", False, "unresolved", 42, "external-db-fresh"))
        self.assertEqual(manifest["files"], {"descriptor.json": hashlib.sha256(self.expected_descriptor).hexdigest(),
                                             "raw-records.json": hashlib.sha256(self.expected_raws).hexdigest()})
        self.assertEqual(self.compiler.verify(dict(self.clean), self.authority), self.clean)

    def test_02_authoring_order_and_formatting_do_not_change_bytes(self):
        descriptor, raws = oracle_inputs()
        shuffled = json.loads(json.dumps(descriptor, indent=3), object_pairs_hook=lambda p: dict(reversed(p)))
        self.assertEqual(self.compiler.compile(shuffled, list(reversed(raws)), self.authority), self.clean)

    # ------------------------------------------- fixed out-of-band authority
    def test_03_fixed_authority_rejects_every_changed_tuple(self):
        def mutate(change):
            descriptor, raws = oracle_inputs()
            change(descriptor, raws)
            return descriptor, raws

        def native_value(d, value):
            for target in (position(d, "r01_A1")["agent_config_json"],
                           node(d, ["r01", "call_A1"])["factory"]["config_json"]):
                target["single_call"]["max_tokens"] = value

        def absent_as_null(d):
            for target in (position(d, "r01_A1")["agent_config_json"],
                           node(d, ["r01", "call_A1"])["factory"]["config_json"]):
                target["single_call"]["temperature"] = None

        def drop_raw(raws, name):
            raws.remove(next(r for r in raws if r["name"] == name))

        cases = {
            "candidate_identity": lambda d, r: d.update(candidate_identity="other_candidate"),
            "logical_run_id": lambda d, r: d.update(logical_run_id="other-run"),
            "execution_uuid": lambda d, r: d.update(execution_uuid="00000000-0000-4000-8000-000000000999"),
            "workspace_path": lambda d, r: d.update(workspace_path="/synthetic/other"),
            "metadata_inputs": lambda d, r: d["metadata_inputs_json"].update(record_id="r02"),
            "request_options": lambda d, r: d["request_options_json"].update(notify="x"),
            "source_commit": lambda d, r: d["source"].update(engine_commit="3" * 40),
            "source_tree": lambda d, r: d["source"].update(engine_tree="4" * 40),
            "source_field_set": lambda d, r: d["source"]["field_sets"]["native"].remove("effort"),
            "workflow_json": lambda d, r: d["graph"]["workflow_json"].update(description="changed"),
            "node_json": lambda d, r: node(d, ["r01", "prepare"])["node_json"].update(gate=True),
            "factory_class": lambda d, r: node(d, ["r01", "prepare"])["factory"].update(class_name="other.Agent"),
            "native_int_to_float": lambda d, r: native_value(d, 8192.0),
            "native_int_to_bool": lambda d, r: native_value(d, True),
            "native_absent_to_null": lambda d, r: absent_as_null(d),
            "script_variables": lambda d, r: d["scripts"][0]["variables_json"].update(record_id="r02"),
            "position_call_id": lambda d, r: position(d, "r01_A1").update(call_id="other"),
            "position_variant": lambda d, r: position(d, "r01_A1").update(variant_id="V02_other"),
            "duplicate_position": lambda d, r: d["positions"].append(copy.deepcopy(d["positions"][0])),
            "position_order": lambda d, r: d["positions"].reverse(),
            "root_policy_invented": lambda d, r: position(d, "r01_A1").update(root_policy={
                **strict_load(FIXTURES / "root-policy.json"), "path": "/synthetic/306/r01/A1/out",
                "permitted_parent": "/synthetic/306/r01/A1"}),
            "raw_config": lambda d, r: r[0]["config_json"].update(description="changed"),
            "raw_schema_version": lambda d, r: [x.update(schema_version="1.1") for x in r[:1]],
            "raw_missing_agent": lambda d, r: drop_raw(r, "oracle306_r01_A1"),
            "raw_extra_orphan": lambda d, r: r.append({**copy.deepcopy(r[-1]), "name": "oracle306_orphan"}),
            "raw_duplicate": lambda d, r: r.append(copy.deepcopy(r[-1])),
        }
        for why, change in cases.items():
            with self.subTest(why=why):
                descriptor, raws = mutate(change)
                self.refused("descriptor_authority", self.compile_fixed(descriptor, raws), why)

    def test_04_authority_must_be_external_and_complete(self):
        artifacts = dict(self.clean)
        for key, code in (("expected_source_sha256", "source_drift"),
                          ("expected_descriptor_sha256", "descriptor_authority")):
            self.refused(code, lambda: self.compiler.verify(artifacts, {**self.authority, key: "0" * 64}),
                         "substituted " + key)
        plain = hashlib.sha256(self.clean["descriptor.json"]).hexdigest()
        self.refused("descriptor_authority", lambda: self.compiler.verify(
            artifacts, {**self.authority, "expected_descriptor_sha256": plain}), "file hash for domain digest")
        manifest = json.loads(self.clean["manifest.json"])
        for why, authority in (("empty", {}), ("manifest_as_authority", manifest),
                               ("digests_as_authority", manifest["digests"]),
                               ("extra_member", {**self.authority, "extra": "x"}),
                               ("null_receipt", {**self.authority, "receipt_id": None}),
                               ("empty_label", {**self.authority, "authorized_caller_label": ""})):
            self.refused("compiler_authority", lambda: self.compiler.verify(artifacts, authority), why)
        # A self-consistent changed candidate with a rewritten manifest is still refused.
        changed = json.loads(self.clean["descriptor.json"])
        changed["logical_run_id"] = "self-approved"
        artifacts["descriptor.json"] = self.compiler.contract.canonical_bytes(changed)
        manifest["files"]["descriptor.json"] = hashlib.sha256(artifacts["descriptor.json"]).hexdigest()
        artifacts["manifest.json"] = self.compiler.contract.canonical_bytes(manifest)
        self.refused("descriptor_authority", lambda: self.compiler.verify(artifacts, self.authority),
                     "candidate-derived authority")

    def test_05_verify_raw_closure_and_canonical_bytes(self):
        records = json.loads(self.clean["raw-records.json"])
        extra = json.loads((FIXTURES / "raw-call.json").read_bytes())

        def raw_bytes(values):
            return self.compiler.contract.canonical_bytes(values)

        cases = {
            "missing_record": (raw_bytes(records[1:]), "closure_mismatch"),
            "extra_record": (raw_bytes([extra, *records]), "closure_mismatch"),
            "duplicate_record": (raw_bytes([copy.deepcopy(records[0]), *records]), "closure_mismatch"),
            "reordered_records": (raw_bytes([records[1], records[0], *records[2:]]), "closure_mismatch"),
            "int_to_float_in_raw": (self.clean["raw-records.json"].replace(
                b'\\"max_tokens\\":8192', b'\\"max_tokens\\":8192.0', 1), "digest_mismatch"),
            "noncanonical_raw": (self.clean["raw-records.json"] + b"\n", "noncanonical_bytes"),
        }
        for why, (data, code) in cases.items():
            artifacts = {**self.clean, "raw-records.json": data}
            self.assertNotEqual(data, self.clean["raw-records.json"])
            self.refused(code, lambda: self.compiler.verify(artifacts, self.authority), why)
        self.refused("noncanonical_bytes", lambda: self.compiler.verify(
            {**self.clean, "descriptor.json": self.clean["descriptor.json"] + b"\n"}, self.authority),
            "noncanonical_descriptor")
        manifest = json.loads(self.clean["manifest.json"])
        manifest["runnable"] = True
        self.refused("compiler_manifest", lambda: self.compiler.verify(
            {**self.clean, "manifest.json": self.compiler.contract.canonical_bytes(manifest)}, self.authority),
            "manifest_claims_runnable")
        self.refused("compiler_input", lambda: self.compiler.verify(
            {k: v for k, v in self.clean.items() if k != "manifest.json"}, self.authority), "missing_manifest")

    # ------------------------------ independently re-signed semantic guards
    def test_06_signed_inconsistent_candidates_reach_codec_guards(self):
        classified = json.loads((FIXTURES / "raw-classified.json").read_bytes())
        classified["config_json"] = json.loads(classified["config_json"])

        def same_root_and_slot(d):
            for target in (position(d, "r02_A1")["agent_config_json"],
                           node(d, ["r02", "call_A1"])["factory"]["config_json"]):
                target["single_call"]["output_root"] = "/synthetic/306/r01/A1/out"

        def native_extra(d):
            for target in (position(d, "r01_A1")["agent_config_json"],
                           node(d, ["r01", "call_A1"])["factory"]["config_json"]):
                target["single_call"]["undeclared"] = 1

        def workflow_name(d):
            d["graph"]["workflow_json"]["name"] = "other"

        def node_extra_field(d):
            # Consistently in workflow_json and the flattened node: only the field set differs.
            d["graph"]["workflow_json"]["nodes"][0]["extra"] = None
            node(d, ["r01"])["node_json"]["extra"] = None

        def stage_factory(d):
            node(d, ["r01"])["factory"] = copy.deepcopy(node(d, ["r01", "prepare"])["factory"])

        def root_outside(d):
            position(d, "r01_A1")["root_policy"] = {
                **strict_load(FIXTURES / "root-policy.json"), "path": "/synthetic/elsewhere/out",
                "permitted_parent": "/synthetic/elsewhere"}

        def drop_raw(r, kind):
            r.remove(next(x for x in r if x["kind"] == kind))

        cases = {
            "missing_workflow_record": (lambda d, r: drop_raw(r, "workflow"), "closure_mismatch"),
            "file_origin_record": (lambda d, r: r.append(classified), "unsupported_mode"),
            "request_field_set_unsorted": (lambda d, r: d["source"]["field_sets"]["request"].reverse(),
                                           "field_set_drift"),
            "request_option_extra": (lambda d, r: d["request_options_json"].update(admission=None),
                                     "field_set_drift"),
            "node_extra_field": (lambda d, r: node_extra_field(d), "field_set_drift"),
            "workflow_name": (lambda d, r: workflow_name(d), "graph_mismatch"),
            "node_json_differs_from_workflow": (
                lambda d, r: node(d, ["r01", "prepare"])["node_json"].update(gate=True), "graph_mismatch"),
            "node_order": (lambda d, r: d["graph"]["nodes"].insert(0, d["graph"]["nodes"].pop(1)),
                           "graph_mismatch"),
            "stage_factory": (lambda d, r: stage_factory(d), "graph_mismatch"),
            "factory_type_mismatch": (
                lambda d, r: node(d, ["r01", "prepare"])["factory"].update(type="single_call"), "graph_mismatch"),
            "script_template_differs": (lambda d, r: d["scripts"][0].update(
                template_utf8="other", template_sha256=hashlib.sha256(b"other").hexdigest()), "graph_mismatch"),
            "script_template_hash": (lambda d, r: d["scripts"][0].update(template_sha256="0" * 64),
                                     "digest_mismatch"),
            "script_missing": (lambda d, r: d["scripts"].pop(), "graph_mismatch"),
            "duplicate_position_id": (lambda d, r: d["positions"].append(copy.deepcopy(d["positions"][0])),
                                      "position_mismatch"),
            "position_missing": (lambda d, r: d["positions"].pop(), "position_mismatch"),
            "same_root_and_slot": (lambda d, r: same_root_and_slot(d), "position_mismatch"),
            "slot_differs_from_native": (lambda d, r: position(d, "r01_A1").update(slot="B1"),
                                         "position_mismatch"),
            "position_config_differs": (lambda d, r: position(d, "r01_A1")["agent_config_json"].update(
                description="other"), "position_mismatch"),
            "native_undeclared_field": (lambda d, r: native_extra(d), "position_mismatch"),
            "preparation_not_script": (lambda d, r: position(d, "r01_A1").update(
                preparation_path=["r01", "call_A2"]), "position_mismatch"),
            "root_policy_outside_output": (lambda d, r: root_outside(d), "position_mismatch"),
        }
        for why, (change, code) in cases.items():
            with self.subTest(why=why):
                descriptor, raws = oracle_inputs()
                change(descriptor, raws)
                self.refused(code, self.compile_signed(descriptor, raws), why)

    def test_07_raw_and_descriptor_shape_type_null_and_absence(self):
        cases = {}

        def raw_case(why, change, code):
            cases[why] = (lambda d, r: change(r[0]), code)

        raw_case("raw_missing_file_base64", lambda x: x.pop("file_base64"), "wire_schema")
        raw_case("raw_extra_field", lambda x: x.update(extra=None), "wire_schema")
        raw_case("raw_schema_version_int", lambda x: x.update(schema_version=1), "wire_schema")
        raw_case("raw_schema_version_null", lambda x: x.update(schema_version=None), "wire_schema")
        raw_case("raw_format", lambda x: x.update(format="candidate-raw-record/v2"), "unsupported_version")
        raw_case("raw_db_with_file_bytes", lambda x: x.update(file_base64="e30="), "source_origin")
        raw_case("raw_config_as_text", lambda x: x.update(config_json="{}"), "compiler_input")
        raw_case("raw_known_fields", lambda x: x["config_json"].update(_KNOWN_FIELDS=["name"]),
                 "compiler_known_fields")
        cases["descriptor_missing_scripts"] = (lambda d, r: d.pop("scripts"), "wire_schema")
        cases["descriptor_extra_member"] = (lambda d, r: d.update(extra=None), "wire_schema")
        cases["descriptor_supplies_records"] = (lambda d, r: d.update(records=[]), "compiler_input")
        cases["root_policy_absent"] = (lambda d, r: d["positions"][0].pop("root_policy"), "wire_schema")
        cases["slot_outside_enum"] = (lambda d, r: d["positions"][0].update(slot="C1"), "wire_schema")
        cases["descriptor_format"] = (lambda d, r: d.update(format="candidate-admission-descriptor/v2"),
                                      "unsupported_version")
        cases["options_as_text"] = (lambda d, r: d.update(request_options_json="{}"), "compiler_input")
        cases["known_fields_unsorted"] = (lambda d, r: node(d, ["r01"])["node_json"]["_KNOWN_FIELDS"].reverse(),
                                          "compiler_known_fields")
        cases["known_fields_not_list"] = (
            lambda d, r: d["graph"]["workflow_json"].update(_KNOWN_FIELDS="name"), "compiler_known_fields")
        cases["known_fields_duplicate"] = (
            lambda d, r: d["graph"]["workflow_json"]["_KNOWN_FIELDS"].insert(0, "description"),
            "compiler_known_fields")
        for mode in ("sealed", "resume", "fork", "rerun", "direct", "inprocess", "cli", "preview",
                     "cleanup", "replacement", "recovery", "external-db-fresh ", None, True):
            cases["mode_" + repr(mode)] = (lambda d, r, mode=mode: d.update(mode=mode), "unsupported_mode")
        for why, (change, code) in cases.items():
            with self.subTest(why=why):
                descriptor, raws = oracle_inputs()
                change(descriptor, raws)
                self.refused(code, self.compile_fixed(descriptor, raws), why)
        # File identity is domain-checked at the raw-record boundary (#192 literal).
        for field, value in (("file_sha256", "0" * 64), ("git_blob_sha1", "0" * 40)):
            classified = json.loads((FIXTURES / "raw-classified.json").read_bytes())
            classified["origin"][field] = value
            self.refused("digest_mismatch", lambda: self.compiler.codec.raw_record(
                self.compiler.contract.canonical_bytes(classified)), "file_origin_" + field)

    def test_08_absent_custody_is_reported_never_synthesized(self):
        approved = self.compiler.codec.descriptor(self.clean["descriptor.json"],
                                                  self.compiler.authority(self.authority))
        self.refused("unresolved_custody", lambda: self.compiler.contract.require_custody(approved),
                     "null root policies")
        decoded_descriptor, _ = decoded(self.clean)
        self.assertTrue(all(p["root_policy"] is None for p in decoded_descriptor["positions"]))

    def test_09_aliases_strict_authoring_json_and_canonical_answers(self):
        descriptor, raws = oracle_inputs()
        descriptor["scripts"].append(descriptor["scripts"][0])
        self.refused("aliased_or_cyclic_value", self.compile_fixed(descriptor, raws), "shared container")
        for case in strict_load(FIXTURES / "canonical.json"):
            self.assertEqual(self.compiler.contract.canonical_bytes(case["input"]), case["wire"].encode())
        for data, code in ((b'{"x":1,"x":2}', "duplicate_key"), (b'{"a":{"x":1,"x":2}}', "duplicate_key"),
                           (b"NaN", "nonfinite_number"), (b"1e999", "nonfinite_number"),
                           (b"{} {}", "invalid_json"), (b"\xff", "invalid_json")):
            self.refused(code, lambda: subject.strict_json(data), "authoring json " + repr(data))
        for data, kind in ((b"1", int), (b"1.0", float), (b"true", bool), (b"null", type(None))):
            self.assertIs(type(subject.strict_json(data)), kind)

    # ------------------------------------------------- compiler window guards
    def test_10_contract_pins_checked_before_any_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            changed = Path(temp) / "codec.py"
            changed.write_bytes(b'raise RuntimeError("must never execute")\n')
            self.refused("compiler_contract_pin", lambda: subject.Compiler(changed, SCHEMA_PATH), "codec pin")
            schema = Path(temp) / "schema.json"
            schema.write_bytes(SCHEMA_PATH.read_bytes() + b"\n")
            self.refused("compiler_contract_pin", lambda: subject.Compiler(CODEC_PATH, schema), "schema pin")

    def test_11_compiler_window_reads_only_explicit_contract_files(self):
        descriptor, raws = oracle_inputs()
        original_import, original_open = builtins.__import__, io.open
        reads = []

        def forbidden(*args, **kwargs):
            raise AssertionError("FORBIDDEN_IN_COMPILER_WINDOW")

        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] not in sys.stdlib_module_names:
                raise AssertionError("NON_STDLIB_IMPORT")
            return original_import(name, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if Path(file) not in {CODEC_PATH, SCHEMA_PATH} or mode != "rb":
                raise AssertionError("UNDECLARED_FILE_ACCESS")
            reads.append(Path(file))
            return original_open(file, mode, *args, **kwargs)

        class NoEnvironment:
            __getitem__ = __iter__ = __len__ = __contains__ = get = keys = values = items = copy = forbidden

        with ExitStack() as stack:
            for target, name, replacement in (
                    (builtins, "__import__", guarded_import), (io, "open", guarded_open),
                    (builtins, "open", forbidden), (os, "environ", NoEnvironment()), (os, "getenv", forbidden),
                    (os, "system", forbidden), (os, "listdir", forbidden), (os, "scandir", forbidden),
                    (socket, "socket", forbidden), (socket, "create_connection", forbidden),
                    (socket, "getaddrinfo", forbidden), (subprocess, "Popen", forbidden)):
                stack.enter_context(patch.object(target, name, replacement))
            compiler = subject.Compiler(CODEC_PATH, SCHEMA_PATH)
            result = compiler.compile(descriptor, raws, self.authority)
            compiler.verify(result, self.authority)
        self.assertEqual(reads, [SCHEMA_PATH, CODEC_PATH])
        self.assertEqual(result, self.clean)

    def test_12_compiler_source_imports_stdlib_only(self):
        tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
        imports = set()
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in item.names)
            elif isinstance(item, ast.ImportFrom):
                imports.add(item.module.split(".")[0])
        self.assertLessEqual(imports, set(sys.stdlib_module_names) | {"__future__"})

    def test_13_cli_round_trip_safe_codes_and_no_overwrite(self):
        descriptor, raws = oracle_inputs()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            incoming = root / "input"
            incoming.mkdir()
            (incoming / "descriptor.json").write_text(json.dumps(descriptor, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")
            (incoming / "raw-records.json").write_text(json.dumps(raws, indent=2, ensure_ascii=False),
                                                       encoding="utf-8")
            authority = root / "authority.json"
            authority.write_text(json.dumps(self.authority))
            contract = ["--codec", str(CODEC_PATH), "--schema", str(SCHEMA_PATH)]

            def run(*args, authority_path=authority):
                with redirect_stdout(io.StringIO()) as output:
                    code = subject.main([*args, *contract, "--authority", str(authority_path)])
                return code, output.getvalue()

            code, out = run("compile", "--input", str(incoming), "--output", str(root / "out"))
            self.retain("cli-compile", {"stdout.json": out.encode(), "exit-code.txt": str(code).encode()})
            self.assertEqual((code, json.loads(out)), (0, {"code": "metadata_verified_not_admitted", "runnable": False}))
            for name in subject.ARTIFACTS:
                self.assertEqual((root / "out" / name).read_bytes(), self.clean[name])
            code, out = run("verify", "--input", str(root / "out"), "--output", str(root / "verified"))
            self.retain("cli-verify", {"stdout.json": out.encode(), "exit-code.txt": str(code).encode()})
            self.assertEqual(code, 0)
            self.assertEqual((root / "verified/verification.json").read_bytes(), self.clean["manifest.json"])
            outputs = {}
            code, outputs["no-overwrite"] = run("compile", "--input", str(incoming), "--output", str(root / "out"))
            self.assertEqual((code, json.loads(outputs["no-overwrite"])["code"]), (2, "compiler_output_exists"))
            wrong = root / "wrong-authority.json"
            wrong.write_text(json.dumps({**self.authority, "expected_descriptor_sha256": "0" * 64}))
            code, outputs["wrong-authority"] = run("verify", "--input", str(root / "out"), "--output",
                                                   str(root / "v2"), authority_path=wrong)
            self.assertEqual((code, json.loads(outputs["wrong-authority"])["code"]), (2, "descriptor_authority"))
            self.assertFalse((root / "v2").exists())
            (incoming / "unexpected.json").write_text("{}")
            code, outputs["extra-input"] = run("compile", "--input", str(incoming), "--output", str(root / "o3"))
            self.assertEqual(json.loads(outputs["extra-input"])["code"], "compiler_input")
            code, outputs["missing-authority"] = run("verify", "--input", str(root / "out"), "--output",
                                                     str(root / "o4"), authority_path=root / "absent.json")
            self.assertEqual(json.loads(outputs["missing-authority"])["code"], "compiler_io")
            with redirect_stdout(io.StringIO()) as output:
                code = subject.main(["untrusted-argument-canary"])
            outputs["usage"] = output.getvalue()
            self.assertEqual((code, json.loads(outputs["usage"])), (2, {"code": "compiler_usage", "runnable": False}))
            self.retain("cli-refusals", {name + ".json": value.encode() for name, value in outputs.items()})
            for value in outputs.values():
                self.assertNotIn(str(root), value)
                self.assertNotIn("untrusted-argument-canary", value)
                self.assertNotIn(self.authority["receipt_id"], value)
                self.assertEqual(set(json.loads(value)), {"code", "runnable"})

    def test_14_dependencies_are_the_pinned_unchanged_inputs(self):
        for path, expected in CONTRACT_FILES.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, path.name)
        for directory, manifest_sha in ((OLD, OLD_MANIFEST_SHA256), (SUP, SUP_MANIFEST_SHA256)):
            data = (directory / "manifest.json").read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest_sha)
            for name, expected in json.loads(data)["files"].items():
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), expected, name)
        self.assertEqual((subject.CODEC_SHA256, subject.SCHEMA_SHA256),
                         (CONTRACT_FILES[CODEC_PATH], CONTRACT_FILES[SCHEMA_PATH]))


if __name__ == "__main__":
    evidence_parser = argparse.ArgumentParser(add_help=False)
    evidence_parser.add_argument("--evidence-output", type=Path)
    evidence_args, unittest_args = evidence_parser.parse_known_args()
    EVIDENCE_DIR = evidence_args.evidence_output
    if EVIDENCE_DIR is None:
        unittest.main(argv=[sys.argv[0], *unittest_args])
    else:
        EVIDENCE_DIR.mkdir()  # Existing evidence is never overwritten.
        with (EVIDENCE_DIR / "unittest.log").open("x") as log:
            runner = unittest.TextTestRunner(stream=log, verbosity=2)
            program = unittest.main(argv=[sys.argv[0], *unittest_args], testRunner=runner, exit=False)
        print(json.dumps({"tests_run": program.result.testsRun, "failures": len(program.result.failures),
                          "errors": len(program.result.errors)}))
        raise SystemExit(not program.result.wasSuccessful())
