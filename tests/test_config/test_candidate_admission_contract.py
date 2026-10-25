"""Inert wire tests. Expected answers are literal fixtures, never loader output.

Stdlib dump/repin below construct INPUT mutations only; repin intentionally
bypasses the external pin comparison to reach semantic guards. The separate
self-certification control NEVER repins its trusted authority.
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "candidate_admission_v1"
SPEC = importlib.util.spec_from_file_location("_candidate_wire_contract", ROOT / "temper_ai/config/admission_contract.py")
assert SPEC and SPEC.loader
c = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c
SPEC.loader.exec_module(c)


def load(name):
    return json.loads((FIXTURES / name).read_bytes())


def dump(value):
    # Integer-only test INPUT assembler. Not the CAJ-1 oracle/codec under test.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


PINS = load("pins.json")
SCHEMA = (ROOT / "docs/schemas/candidate-admission-v1.schema.json").read_bytes()
DESCRIPTOR = (FIXTURES / "descriptor.json").read_bytes()
RAW = tuple((FIXTURES / f"raw-{name}.json").read_bytes() for name in ("call", "prepare", "workflow"))


@pytest.fixture
def codec():
    return c.ContractCodec(SCHEMA)


def authority(root=False):
    return c.DescriptorAuthority(PINS["root-descriptor" if root else "descriptor"],
                                 PINS["source"], "synthetic-author", "synthetic-receipt")


def root_descriptor():
    v = json.loads(DESCRIPTOR)
    v["positions"][0]["root_policy"] = load("root-policy.json")
    return dump(v)


def record_input(root=False, running=False, ready=False):
    v = load("record-layout.json")
    i = v["immutable"]
    i["descriptor_json"] = (root_descriptor() if root else DESCRIPTOR).decode()
    i["descriptor_sha256"] = PINS["root-descriptor" if root else "descriptor"]
    i["effective_graph_sha256"] = PINS["graph"]
    i["raw_records"] = [json.loads(b) for b in RAW]
    v["immutable_sha256"] = PINS["root-immutable" if root else "immutable"]
    if running:
        v["dispatch"] = {"phase": "running", "dispatch_nonce": "00000000-0000-4000-8000-000000000003",
                         "previous_nonce": "00000000-0000-4000-8000-000000000002",
                         "running_attempt": 1, "worker_label": "synthetic-worker"}
    if ready:
        v["readiness"] = [load("readiness.json")]
    return v


def repin(value):
    def independent_hash(domain, data):
        return hashlib.sha256(b"temper-admission/v1\0" + domain + b"\0" + data).hexdigest()
    return c.DescriptorAuthority(independent_hash(b"descriptor", dump(value)),
                                 independent_hash(b"source", dump(value["source"])),
                                 "synthetic-author", "synthetic-receipt")


def refused(code, action):
    with pytest.raises(c.AdmissionRefused) as caught:
        action()
    assert caught.value.code.value == code
    assert str(caught.value) == code
    assert caught.value.__suppress_context__


def test_combined_literal_descriptor_closure_transport_happy_path(codec):
    """Opening combined test: owned bytes, canonical/domain pins, all sections."""
    d = codec.descriptor(DESCRIPTOR, authority())
    assert d.wire == DESCRIPTOR
    assert d.sha256 == PINS["descriptor"]
    assert c.canonical_bytes(d.value()) == DESCRIPTOR
    raw = tuple(codec.raw_record(b) for b in RAW)
    closure = codec.closure(d, raw)
    assert closure.sha256 == PINS["closure"]
    assert [r.sha256 for r in raw] == [r["raw_sha256"] for r in load("descriptor.json")["records"]]
    first, second = closure.get("agent", "call"), closure.get("agent", "call")
    first["single_call"]["slot"] = "A2"
    assert second == {"single_call": {"output_root": "/synthetic/wire-fixture/out", "slot": "A1"}, "type": "single_call"}
    assert closure.get("agent", "call") == second
    q = codec.record(dump(record_input()), authority())
    r = codec.record(dump(record_input(running=True)), authority())
    c.check_preserved(q, codec.record(q.wire, authority()))
    c.check_dispatch_transition(q, r)
    c.require_source(d, c.FrozenJSON(dump(load("descriptor.json")["source"])))
    c.require_mode("external-db-fresh")
    c.require_admission(designated_candidate=False, has_record=False, supported_code=False)
    refused("unresolved_custody", lambda: c.require_custody(d))
    rooted = codec.descriptor(root_descriptor(), authority(root=True))
    c.require_custody(rooted)  # Synthetic structural data, NOT a permission.
    running = codec.record(dump(record_input(root=True, running=True)), authority(root=True))
    ready = codec.record(dump(record_input(root=True, running=True, ready=True)), authority(root=True))
    receipt = codec.readiness(dump(load("readiness.json")))
    c.check_readiness_transition(running, ready, receipt)
    c.check_readiness_transition(ready, ready, receipt)
    binding = c.CandidateInvocationBinding(rooted, closure, PINS["graph"],
        c.DispatchIdentity("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000003", 1),
        ("call",), "p01", c.FrozenJSON(b'{"name":"call"}'), c.FrozenJSON(dump(second)), receipt)
    assert binding.node_path == ("call",)
    for field, value in (("node_path", ["call"]), ("node_path", ("bad.path",)),
                         ("position_id", []), ("expected_node", {}), ("expected_agent", {}),
                         ("readiness", {}), ("descriptor", {}), ("closure", []), ("dispatch", {})):
        refused("invalid_type", lambda: replace(binding, **{field: value}))
    refused("digest_mismatch", lambda: replace(binding, graph_sha256="bad"))
    assert c.OpenedRoot(7, (c.FrozenJSON(b'{"inode":3}'),)).fd == 7  # No fd opened.
    for frozen, attr in ((d, "wire"), (closure, "records"), (binding, "position_id"), (d.authority, "receipt_id")):
        with pytest.raises(FrozenInstanceError):
            setattr(frozen, attr, None)
    leaked = d.value()
    leaked["positions"][0]["slot"] = "B1"
    assert d.value()["positions"][0]["slot"] == "A1"
    assert codec.raw_record((FIXTURES / "raw-classified.json").read_bytes()).value()["file_base64"] == "e30K"


@pytest.mark.parametrize("case", load("canonical.json"), ids=lambda v: v["case"])
def test_independent_literal_canonical_answers(case):
    wire = case["wire"].encode()
    assert c.canonical_bytes(case["input"]) == wire
    assert c.canonical_bytes(c.decode_canonical(wire)) == wire


@pytest.mark.parametrize("case", load("refusals.json"), ids=lambda v: v["case"])
def test_independent_literal_byte_refusals(case):
    refused(case["code"], lambda: c.decode_canonical(case["wire"].encode()))


def test_number_extremes_exact_types_and_invalid_utf8():
    for number in (float.fromhex("0x0.0000000000001p-1022"), sys.float_info.max, -sys.float_info.max):
        wire = c.canonical_bytes(number)
        assert b"e" not in wire and b"." in wire
        assert c.decode_canonical(wire).hex() == number.hex()
    for value in (float("nan"), float("inf"), float("-inf")):
        refused("nonfinite_number", lambda: c.canonical_bytes(value))
    for value in ({1: "x"}, (1,), b"x", {1}, bytearray(b"x")):
        refused("invalid_type", lambda: c.canonical_bytes(value))
    class IntSubclass(int):
        pass
    refused("invalid_type", lambda: c.canonical_bytes(IntSubclass(1)))
    for wire in (bytearray(b"{}"), memoryview(b"{}"), "{}"):
        refused("invalid_type", lambda: c.decode_canonical(wire))
    refused("invalid_json", lambda: c.decode_canonical(b'"\xff"'))
    refused("invalid_json", lambda: c.canonical_bytes("\ud800"))
    assert len({c.canonical_bytes(v) for v in (1, 1.0, True, None, "1", -0.0, 0.0, 0)}) == 8


def test_aliases_cycles_absence_and_owned_bytes():
    shared = {"a": []}
    refused("aliased_or_cyclic_value", lambda: c.canonical_bytes([shared, shared]))
    cycle = []
    cycle.append(cycle)
    refused("aliased_or_cyclic_value", lambda: c.canonical_bytes(cycle))
    original = {"x": [{"a": 1}]}
    frozen = c.FrozenJSON(c.canonical_bytes(original))
    original["x"][0]["a"] = 2
    assert frozen.wire == b'{"x":[{"a":1}]}'
    assert c.canonical_bytes({}) != c.canonical_bytes({"x": None})
    refused("invalid_type", lambda: c.FrozenJSON(b"[]"))
    refused("invalid_type", lambda: c.RawClosure([]))
    refused("invalid_type", lambda: c.RawClosure(({},)))
    refused("closure_mismatch", lambda: c.RawClosure(()))


def test_schema_pin_domains_and_source_drift(codec):
    refused("digest_mismatch", lambda: c.ContractCodec(SCHEMA + b" "))
    refused("invalid_type", lambda: c.ContractCodec(bytearray(SCHEMA)))
    assert c.digest(c.DigestDomain.RAW_RECORD, b"{}") == PINS["raw-domain-empty-object"]
    assert c.digest(c.DigestDomain.DESCRIPTOR, b"{}") == PINS["descriptor-domain-empty-object"]
    refused("invalid_type", lambda: c.digest("descriptor", b"{}"))
    refused("noncanonical_bytes", lambda: c.digest(c.DigestDomain.GRAPH, b"{}\n"))
    d = codec.descriptor(DESCRIPTOR, authority())
    source = d.value()["source"]
    source["engine_tree"] = "0" * 40
    refused("source_drift", lambda: c.require_source(d, c.FrozenJSON(dump(source))))
    refused("wire_schema", lambda: codec.validate_shape({}, "does-not-exist"))


@pytest.mark.parametrize("mode", ["sealed", "resume", "fork", "rerun", "replacement", "inprocess", "cli", "preview", "cleanup", "", None, 1])
def test_unsupported_modes_refuse_before_any_adapter(mode, codec):
    refused("unsupported_mode", lambda: c.require_mode(mode))
    d = load("descriptor.json")
    d["mode"] = mode
    refused("unsupported_mode", lambda: codec.descriptor(dump(d), authority()))


@pytest.mark.parametrize("field,value,code", [
    ("format", "candidate-admission-descriptor/v2", "unsupported_version"),
    ("extra", 1, "wire_schema"), ("execution_uuid", "not-a-uuid", "wire_schema"),
    ("workflow_name", "other", "descriptor_authority"),
    ("logical_run_id", "other", "descriptor_authority"),
    ("metadata_inputs_json", '{"record_id":"r02"}', "descriptor_authority"),
    ("workspace_path", "/synthetic/other", "descriptor_authority"),
])
def test_outer_changed_values_keep_original_authority(field, value, code, codec):
    d = load("descriptor.json")
    d[field] = value
    refused(code, lambda: codec.descriptor(dump(d), authority()))


def test_trust_is_not_self_certification(codec):
    d = load("descriptor.json")
    d["positions"][0]["record_id"] = "other"
    claimed = repin(d)  # Candidate knows its own digest. It is NOT caller authority.
    assert claimed.expected_descriptor_sha256 != authority().expected_descriptor_sha256
    refused("descriptor_authority", lambda: codec.descriptor(dump(d), authority()))
    for a in (None, {}, replace(authority(), receipt_id=""), replace(authority(), authorized_caller_label=1),
              replace(authority(), expected_descriptor_sha256="A" * 64)):
        refused("descriptor_authority", lambda: codec.descriptor(DESCRIPTOR, a))
    refused("source_drift", lambda: codec.descriptor(DESCRIPTOR, replace(authority(), expected_source_sha256="0" * 64)))


def _objects(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from _objects(v, (*path, k))
    elif isinstance(value, list):
        for k, v in enumerate(value):
            yield from _objects(v, (*path, k))


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def test_standard_schema_matches_literal_structural_cases(codec):
    schema = json.loads(SCHEMA)
    Draft202012Validator.check_schema(schema)
    standard = Draft202012Validator(schema)
    for clean in (load("descriptor.json"), load("raw-classified.json"), record_input(), load("readiness.json")):
        assert standard.is_valid(clean)
        unknown = copy.deepcopy(clean)
        unknown["unknown"] = None
        assert not standard.is_valid(unknown)
        absent = copy.deepcopy(clean)
        del absent["format"]
        assert not standard.is_valid(absent)
    # JSON Schema has mathematical integers; CAJ-1 is an additional exact-type rule.
    r = load("readiness.json")
    r["running_attempt"] = 1.0
    assert standard.is_valid(r)
    refused("wire_schema", lambda: codec.readiness(dump(r)))


def test_every_object_is_closed_every_property_required_and_exact_typed(codec):
    # Expected refusals fixed by the closed v1 contract, not generated by codec.
    for definition, clean in (("descriptor", load("descriptor.json")),
                              ("rawRecord", load("raw-classified.json")),
                              ("record", record_input(root=True, running=True, ready=True))):
        codec.validate_shape(clean, definition)
        for path, obj in _objects(clean):
            extra = copy.deepcopy(clean)
            _at(extra, path)["unexpected"] = None
            refused("wire_schema", lambda: codec.validate_shape(extra, definition))
            for key, value in obj.items():
                absent = copy.deepcopy(clean)
                del _at(absent, path)[key]
                refused("wire_schema", lambda: codec.validate_shape(absent, definition))
                # String format/mode get dedicated fence codes at the top level.
                if not path and key in ("format", "mode"):
                    continue
                wrong = copy.deepcopy(clean)
                _at(wrong, path)[key] = [] if not isinstance(value, list) else {}
                refused("wire_schema", lambda: codec.validate_shape(wrong, definition))
                if value is not None and key not in ("factory", "root_policy", "worker_label", "previous_nonce", "file_base64"):
                    null = copy.deepcopy(clean)
                    _at(null, path)[key] = None
                    refused("wire_schema", lambda: codec.validate_shape(null, definition))
    for value in (True, 1.0, -1):
        r = load("readiness.json")
        r["running_attempt"] = value
        refused("wire_schema", lambda: codec.readiness(dump(r)))


@pytest.mark.parametrize("path,value,code", [
    (("workspace_path",), "/synthetic/../other", "source_origin"),
    (("metadata_inputs_json",), "[]", "invalid_type"),
    (("metadata_inputs_json",), "{} ", "noncanonical_bytes"),
    (("request_options_json",), "{}", "field_set_drift"),
    (("source", "field_sets", "workflow"), ["nodes", "name"], "field_set_drift"),
    (("graph", "workflow_json"), '{"name":"other","nodes":[]}', "graph_mismatch"),
    (("graph", "nodes", 0, "path"), ["other"], "graph_mismatch"),
    (("graph", "nodes", 0, "factory"), None, "graph_mismatch"),
    (("graph", "nodes", 0, "factory", "config_json"), '{"type":"single_call"}', "graph_mismatch"),
    (("positions", 0, "node_path"), ["prepare"], "position_mismatch"),
    (("positions", 0, "preparation_path"), ["call"], "position_mismatch"),
    (("positions", 0, "agent_config_json"), "{}", "position_mismatch"),
    (("positions", 0, "slot"), "A2", "position_mismatch"),
    (("positions",), [], "position_mismatch"),
    (("scripts", 0, "node_path"), ["call"], "graph_mismatch"),
    (("scripts", 0, "template_utf8"), "x", "graph_mismatch"),
    (("scripts", 0, "template_sha256"), "0" * 64, "digest_mismatch"),
    (("scripts", 0, "variables_json"), "null", "invalid_type"),
    (("scripts",), [], "graph_mismatch"),
])
def test_independently_repinned_semantic_guard_bites(path, value, code, codec):
    d = load("descriptor.json")
    _at(d, path[:-1])[path[-1]] = value
    refused(code, lambda: codec.descriptor(dump(d), repin(d)))


def test_cross_node_closure_and_factory_guards(codec):
    def check(d, code):
        refused(code, lambda: codec.descriptor(dump(d), repin(d)))
    d = load("descriptor.json")
    d["records"].reverse()
    check(d, "closure_mismatch")
    d = load("descriptor.json")
    d["records"] = d["records"][:-1]
    check(d, "closure_mismatch")
    d = load("descriptor.json")
    d["records"][0]["origin"] = load("raw-classified.json")["origin"]
    check(d, "unsupported_mode")
    d = load("descriptor.json")
    d["positions"].append(copy.deepcopy(d["positions"][0]))
    check(d, "position_mismatch")
    d = load("descriptor.json")
    d["scripts"].append(copy.deepcopy(d["scripts"][0]))
    check(d, "graph_mismatch")
    for native in ({"slot": "A1"}, {"output_root": True, "slot": "A1"},
                   {"output_root": "/synthetic/out", "slot": "A1", "extra": None}, []):
        d = load("descriptor.json")
        cfg = dump({"single_call": native, "type": "single_call"}).decode()
        d["graph"]["nodes"][1]["factory"]["config_json"] = cfg
        d["positions"][0]["agent_config_json"] = cfg
        check(d, "position_mismatch")
    for key, value in (("path", "/synthetic/other"), ("permitted_parent", "/wrong")):
        d = json.loads(root_descriptor())
        d["positions"][0]["root_policy"][key] = value
        check(d, "position_mismatch")
    for change, code in (("extra-field", "field_set_drift"), ("non-list", "graph_mismatch"),
                          ("duplicate-path", "graph_mismatch"), ("unknown-type", "graph_mismatch")):
        d = load("descriptor.json")
        wf = json.loads(d["graph"]["workflow_json"])
        if change == "extra-field":
            wf["nodes"][0]["ignored"] = None
        elif change == "non-list":
            wf["nodes"] = {}
        elif change == "duplicate-path":
            wf["nodes"].append(copy.deepcopy(wf["nodes"][0]))
            d["graph"]["nodes"].append(copy.deepcopy(d["graph"]["nodes"][0]))
        else:
            wf["nodes"][0]["type"] = "template"
            d["graph"]["nodes"][0]["node_json"] = dump(wf["nodes"][0]).decode()
        d["graph"]["workflow_json"] = dump(wf).decode()
        check(d, code)


def test_recursive_stage_and_same_slot_different_roots(codec):
    d = load("descriptor.json")
    wf = json.loads(d["graph"]["workflow_json"])
    group = {"agent": None, "name": "group", "nodes": wf["nodes"], "type": "stage"}
    wf["nodes"] = [group]
    d["graph"]["workflow_json"] = dump(wf).decode()
    for node in d["graph"]["nodes"]:
        node["path"].insert(0, "group")
    d["graph"]["nodes"].insert(0, {"path": ["group"], "node_json": dump(group).decode(), "factory": None})
    d["positions"][0]["node_path"].insert(0, "group")
    d["positions"][0]["preparation_path"].insert(0, "group")
    d["scripts"][0]["node_path"].insert(0, "group")
    assert codec.descriptor(dump(d), repin(d)).value()["positions"][0]["node_path"] == ["group", "call"]
    d["graph"]["nodes"][0]["factory"] = copy.deepcopy(d["graph"]["nodes"][1]["factory"])
    refused("graph_mismatch", lambda: codec.descriptor(dump(d), repin(d)))

    d = load("descriptor.json")
    wf = json.loads(d["graph"]["workflow_json"])
    leaf = copy.deepcopy(wf["nodes"][1])
    leaf["name"] = "second"
    wf["nodes"].append(leaf)
    d["graph"]["workflow_json"] = dump(wf).decode()
    node = copy.deepcopy(d["graph"]["nodes"][1])
    node["path"] = ["second"]
    node["node_json"] = dump(leaf).decode()
    d["graph"]["nodes"].append(node)
    pos = copy.deepcopy(d["positions"][0])
    pos["position_id"], pos["node_path"] = "p02", ["second"]
    d["positions"].append(pos)
    refused("position_mismatch", lambda: codec.descriptor(dump(d), repin(d)))  # Same root AND slot.
    cfg = {"single_call": {"output_root": "/synthetic/wire-fixture/other", "slot": "A1"}, "type": "single_call"}
    pos["agent_config_json"] = node["factory"]["config_json"] = dump(cfg).decode()
    assert len(codec.descriptor(dump(d), repin(d)).value()["positions"]) == 2  # No global slot uniqueness.


@pytest.mark.parametrize("path,value,code", [
    (("origin", "relative_path"), "../agent.yaml", "source_origin"),
    (("origin", "relative_path"), "/agent.yaml", "source_origin"),
    (("origin", "file_sha256"), "0" * 64, "digest_mismatch"),
    (("origin", "git_blob_sha1"), "0" * 40, "digest_mismatch"),
    (("file_base64",), None, "source_origin"),
    (("file_base64",), "e30K\n", "source_origin"),
    (("file_base64",), "e30=", "digest_mismatch"),
    (("config_json",), "[]", "invalid_type"),
    (("config_json",), '{"x":null,"x":null}', "duplicate_key"),
])
def test_classified_file_exact_byte_identity(path, value, code, codec):
    raw = load("raw-classified.json")
    _at(raw, path[:-1])[path[-1]] = value
    refused(code, lambda: codec.raw_record(dump(raw)))


def test_db_closure_raw_mutation_and_no_fallback(codec):
    d = codec.descriptor(DESCRIPTOR, authority())
    records = tuple(codec.raw_record(b) for b in RAW)
    for altered in (records[:-1], (records[1], records[0], records[2]), (*records, records[0])):
        refused("closure_mismatch", lambda: codec.closure(d, altered))
    closure = codec.closure(d, records)
    refused("outside_closure", lambda: closure.get("agent", "missing"))
    for key, value, code in (("config_json", "{}", "digest_mismatch"),
                             ("schema_version", "fixture-2", "closure_mismatch"),
                             ("name", "another", "closure_mismatch")):
        raw = json.loads(RAW[0])
        raw[key] = value
        changed = (codec.raw_record(dump(raw)), *records[1:])
        refused(code, lambda: codec.closure(d, changed))
    raw = json.loads(RAW[0])
    raw["file_base64"] = ""
    refused("source_origin", lambda: codec.raw_record(dump(raw)))
    raw["origin"] = {"kind": "candidate_oracle"}
    refused("wire_schema", lambda: codec.raw_record(dump(raw)))


@pytest.mark.parametrize("field,value,code", [
    ("descriptor_sha256", "0" * 64, "digest_mismatch"),
    ("effective_graph_sha256", "0" * 64, "digest_mismatch"),
    ("raw_closure_sha256", "0" * 64, "digest_mismatch"),
    ("authorized_caller_label", "other", "descriptor_authority"),
    ("authority_receipt_id", "other", "descriptor_authority"),
])
def test_protected_immutable_semantic_guards(field, value, code, codec):
    r = record_input()
    r["immutable"][field] = value
    refused(code, lambda: codec.record(dump(r), authority()))


@pytest.mark.parametrize("running,field,value", [
    (False, "running_attempt", 1), (False, "previous_nonce", "00000000-0000-4000-8000-000000000009"),
    (False, "worker_label", "synthetic-worker"), (True, "running_attempt", 0),
    (True, "previous_nonce", None), (True, "worker_label", ""),
    (True, "previous_nonce", "00000000-0000-4000-8000-000000000003"),
])
def test_dispatch_shape_semantics(running, field, value, codec):
    r = record_input(running=running)
    r["dispatch"][field] = value
    refused("dispatch_generation", lambda: codec.record(dump(r), authority()))


def test_record_version_hash_and_dispatch_transition_guards(codec):
    q = codec.record(dump(record_input()), authority())
    r = codec.record(dump(record_input(running=True)), authority())
    refused("protected_metadata", lambda: c.check_preserved(q, r))
    for key, value, code in (("format", "candidate-admission-record/v0", "unsupported_version"),
                             ("immutable_sha256", "0" * 64, "digest_mismatch")):
        v = record_input()
        v[key] = value
        refused(code, lambda: codec.record(dump(v), authority()))
    for section, key, value, code in (("immutable", "authority_receipt_id", "other", "protected_metadata"),
        ("dispatch", "previous_nonce", "00000000-0000-4000-8000-000000000009", "dispatch_generation"),
        ("dispatch", "dispatch_nonce", "00000000-0000-4000-8000-000000000002", "dispatch_generation"),
        ("dispatch", "phase", "queued", "dispatch_generation"),
        ("dispatch", "running_attempt", 2, "dispatch_generation"),
        ("dispatch", "worker_label", "", "dispatch_generation")):
        v = record_input(running=True)
        v[section][key] = value
        refused(code, lambda: c.check_dispatch_transition(q, c.AdmissionRecord(dump(v))))
    refused("dispatch_generation", lambda: c.check_dispatch_transition(r, r))
    v = record_input(running=True)
    v["readiness"] = [load("readiness.json")]
    refused("dispatch_generation", lambda: c.check_dispatch_transition(q, c.AdmissionRecord(dump(v))))
    v = record_input()
    v["dispatch"]["running_attempt"] = 1
    proposed = record_input(running=True)
    proposed["dispatch"]["running_attempt"] = 2
    refused("dispatch_generation", lambda: c.check_dispatch_transition(c.AdmissionRecord(dump(v)), c.AdmissionRecord(dump(proposed))))


@pytest.mark.parametrize("path,value", [
    (("position_id",), "other"), (("preparation_path",), ["other"]),
    (("descriptor_sha256",), "0" * 64), (("graph_sha256",), "0" * 64),
    (("execution_uuid",), "00000000-0000-4000-8000-000000000009"),
    (("dispatch_nonce",), "00000000-0000-4000-8000-000000000009"), (("running_attempt",), 2),
    (("root", "path"), "/synthetic/other"), (("root", "uid"), 9),
    (("root", "gid"), 9), (("root", "mode"), 511),
])
def test_readiness_bound_identity_mutations(path, value, codec):
    r = record_input(root=True, running=True, ready=True)
    _at(r["readiness"][0], path[:-1])[path[-1]] = value
    refused("root_readiness", lambda: codec.record(dump(r), authority(root=True)))


def test_readiness_transition_and_missing_custody_guards(codec):
    a = authority(root=True)
    v = record_input(root=True, running=True, ready=True)
    ready = codec.record(dump(v), a)
    receipt = codec.readiness(dump(load("readiness.json")))
    v["readiness"].append(copy.deepcopy(v["readiness"][0]))
    refused("root_readiness", lambda: codec.record(dump(v), a))
    v = record_input(root=True, running=True, ready=True)
    v["dispatch"]["worker_label"] = "wrong"
    refused("root_readiness", lambda: codec.record(dump(v), a))
    v = record_input(running=True, ready=True)
    refused("root_readiness", lambda: codec.record(dump(v), authority()))
    v = record_input(root=True, ready=True)
    refused("dispatch_generation", lambda: codec.record(dump(v), a))
    altered = load("readiness.json")
    altered["root"]["inode"] = 99
    changed = codec.readiness(dump(altered))
    refused("root_readiness", lambda: c.check_readiness_transition(ready, ready, changed))
    empty = codec.record(dump(record_input(root=True, running=True)), a)
    refused("root_readiness", lambda: c.check_readiness_transition(empty, empty, receipt))
    refused("protected_metadata", lambda: c.check_readiness_transition(ready, c.AdmissionRecord(dump(v)), receipt))
    for field, value in (("dispatch_nonce", "00000000-0000-4000-8000-000000000009"), ("running_attempt", 2)):
        stale = load("readiness.json")
        stale[field] = value
        refused("root_readiness", lambda: c.check_readiness_transition(ready, ready, codec.readiness(dump(stale))))
    queued = codec.record(dump(record_input(root=True)), a)
    refused("root_readiness", lambda: c.check_readiness_transition(queued, queued, receipt))
    altered["parents"][0]["path"] = "/synthetic/../other"
    refused("source_origin", lambda: codec.readiness(dump(altered)))


def test_compatibility_rollback_and_frozen_local_interface_types():
    for designated, present, supported, code in (
        (True, False, True, "admission_required"), (True, False, False, "admission_required"),
        (True, True, False, "rollback_fence"), (False, True, False, "rollback_fence")):
        refused(code, lambda: c.require_admission(designated_candidate=designated, has_record=present, supported_code=supported))
    c.require_admission(designated_candidate=True, has_record=True, supported_code=True)
    for attempt in (True, 0, -1, 1.0):
        refused("dispatch_generation", lambda: c.DispatchIdentity("00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002", attempt))
    refused("dispatch_generation", lambda: c.DispatchIdentity("wrong", "wrong", 1))
    refused("invalid_type", lambda: c.require_admission(designated_candidate=1, has_record=False, supported_code=True))
    for fd, traversal in ((True, ()), (-1, ()), (1, []), (1, ({},)), (1, ())):
        refused("invalid_type", lambda: c.OpenedRoot(fd, traversal))


def test_standalone_import_has_no_runtime_provider_or_io_side_effects():
    # Separate process observes import membership, not model request data.
    script = """
import builtins, importlib.util, sys
p = sys.argv[1]
s = importlib.util.spec_from_file_location('_pure_contract', p)
m = importlib.util.module_from_spec(s)
sys.modules[s.name] = m
s.loader.exec_module(m)
assert not any(n == 'temper_ai' or n.startswith(('sqlalchemy', 'httpx', 'anthropic', 'openai')) for n in sys.modules)
def no_io(*a, **kw):
    raise AssertionError('unexpected I/O')
builtins.open = no_io
assert m.canonical_bytes({'a': 1}) == b'{"a":1}'
assert m.decode_canonical(b'{"a":1}') == {'a': 1}
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script,
                             str(ROOT / "temper_ai/config/admission_contract.py")], capture_output=True)
    assert result.returncode == 0, "standalone pure import failed"
