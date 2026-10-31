"""Candidate-only raw and actual-object controls; no execution or model bodies."""
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace

import pytest

from temper_ai.config import candidate_admission as candidate
from temper_ai.config.admission_capture import SnapshotResolver
from temper_ai.config.admission_contract import (
    AdmissionRefused,
    ApprovedCandidateDescriptor,
    DescriptorAuthority,
    FrozenJSON,
    RawClosure,
    RefusalCode,
)
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from tests.test_config.admission_cases import (
    NODE_KEYS,
    SOURCE,
    expectation,
    hashed,
    literals,
    raw_record,
    text,
    typed_case,
)


def assemble(raw, descriptor=None, *, version="1.0"):
    """Authorize test input identities, NEVER compute expected effective semantics."""
    _, codec, _, _, _, _ = typed_case()
    d = deepcopy(descriptor if descriptor is not None else literals()[2])
    records = [raw_record(*key, value, version=version) for key, value in sorted(raw.items())]
    d["records"] = [expectation(r) for r in records]
    authority = DescriptorAuthority(hashed("descriptor", d), hashed("source", d["source"]), "literal-test", "literal-receipt")
    approved = codec.descriptor(text(d).encode(), authority)
    closure = codec.closure(approved, tuple(codec.raw_record(text(r).encode()) for r in records))
    return codec, authority, approved, closure, FrozenJSON(text(d["source"]).encode())


def resolve(case):
    codec, authority, descriptor, closure, source = case
    return candidate.load_candidate(codec, descriptor, closure, authority=authority, source=source)


def raw_check(case):
    codec, authority, descriptor, closure, _ = case
    resolver = SnapshotResolver(codec, descriptor, closure.records, authority=authority)
    candidate.validate_raw(resolver, descriptor)


@pytest.mark.parametrize("switch", ["0", "1"])
def test_loader_protocol_preserves_import_only_config_registration(switch):
    # A fresh process observes registration before server/database initialization.
    # No database, config body, provider or runtime is opened by this control.
    result = subprocess.run(
        [sys.executable, "-c", "import temper_ai.stage.loader; from sqlmodel import SQLModel; assert 'configs' in SQLModel.metadata.tables"],
        env={**os.environ, "TEMPER_PI_AGENT": switch}, capture_output=True,
    )
    assert result.returncode == 0


def test_snapshot_actual_happy_path_equals_independent_literals_and_is_owned(monkeypatch):
    _, codec, authority, descriptor, closure, source = typed_case()
    # No side effect or ordinary source reread can hide behind a passing comparison.
    def forbidden(*args, **kwargs):
        raise AssertionError("outside the owned snapshot")
    monkeypatch.setattr("temper_ai.config.store.ConfigStore.get", forbidden)
    monkeypatch.setattr("temper_ai.agent.script_agent.ScriptAgent.run", forbidden)
    monkeypatch.setattr("temper_ai.agent.single_call_agent.SingleCallAgent.run", forbidden)
    case = (codec, authority, descriptor, closure, source)
    nodes, workflow, graph = resolve(case)
    assert graph.wire == text(literals()[2]["graph"]).encode()
    assert candidate.source_inventory(engine_commit="1" * 40, engine_tree="2" * 40, request_fields=("mode",)) == source
    nodes[0].child_nodes[1].agent_config["single_call"]["slot"] = "A2"
    workflow.description = "mutated caller object"
    assert resolve(case)[2].wire == graph.wire
    resolver = SnapshotResolver(codec, descriptor, closure.records, authority=authority)
    one, two = resolver.get("sample", "workflow"), resolver.get("sample", "workflow")
    assert one == two and one is not two
    one["workflow"]["nodes"].clear()
    assert len(two["workflow"]["nodes"]) == 1
    with pytest.raises(AdmissionRefused, match="^outside_closure$"):
        resolver.get("outside", "agent")
    with pytest.raises(AdmissionRefused, match="^invalid_type$"):
        resolver.get(True, "agent")


RAW_REFUSALS = [
    ("workflow", ("workflow", "unknown"), True, RefusalCode.FIELDS),
    ("workflow", ("unrecognized_wrapper",), {}, RefusalCode.SCHEMA),
    ("workflow", ("schema_version",), "other", RefusalCode.VERSION),
    ("workflow", ("schema_version",), None, RefusalCode.VERSION),
    ("workflow", ("workflow", "starts_runs"), True, RefusalCode.SCHEMA),
    ("workflow", ("workflow", "starts_runs"), 1, RefusalCode.TYPE),
    ("workflow", ("workflow", "defaults"), {"token": "synthetic"}, RefusalCode.FIELDS),
    ("workflow", ("workflow", "defaults"), {"temperature": 1}, RefusalCode.TYPE),
    ("workflow", ("workflow", "description"), "${SYNTHETIC}", RefusalCode.SCHEMA),
    ("workflow", ("workflow", "memory"), {"a": ["{{ nested }}"]}, RefusalCode.SCHEMA),
    ("workflow", ("workflow", "name"), "other", RefusalCode.CLOSURE),
    ("stage", ("stage", "nodes", 0, "gate"), 1, RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "max_loops"), True, RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "timeout_seconds"), 1.0, RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "required_files"), {}, RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "renamed_from"), [3], RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "depends_on"), None, RefusalCode.TYPE),
    ("stage", ("stage", "nodes", 0, "type"), "template", RefusalCode.SCHEMA),
    ("stage", ("stage", "nodes", 0, "agent"), "preparer", RefusalCode.CLOSURE),
    ("stage", ("stage", "nodes", 0, "agent"), "agent/preparer", RefusalCode.CLOSURE),
    ("stage", ("stage", "nodes", 0, "agent"), "agents/../preparer", RefusalCode.CLOSURE),
    ("stage", ("stage", "nodes", 0, "agent"), "agents/outside", RefusalCode.LOOKUP),
    ("stage", ("stage", "nodes", 0, "ref"), "stages/group", RefusalCode.SCHEMA),
    ("stage", ("stage", "nodes", 0, "strategy"), None, RefusalCode.SCHEMA),
    ("stage", ("stage", "nodes", 0, "_KNOWN_FIELDS"), NODE_KEYS, RefusalCode.FIELDS),
    ("caller", ("agent", "unknown"), None, RefusalCode.FIELDS),
    ("caller", ("agent", "type"), "llm", RefusalCode.FIELDS),
    ("caller", ("agent", "model"), "{{ label }}", RefusalCode.SCHEMA),
    ("caller", ("agent", "single_call", "unknown"), True, RefusalCode.FIELDS),
    ("caller", ("agent", "single_call", "max_tokens"), True, RefusalCode.TYPE),
    ("caller", ("agent", "single_call", "prompt_bytes"), 0.0, RefusalCode.TYPE),
    ("caller", ("agent", "single_call", "thinking_budget"), None, RefusalCode.TYPE),
    ("caller", ("agent", "single_call", "cost_cap_usd"), False, RefusalCode.TYPE),
    ("caller", ("agent", "single_call", "effort"), {}, RefusalCode.TYPE),
    ("preparer", ("agent", "strict_undefined"), 1, RefusalCode.TYPE),
    ("preparer", ("agent", "log_max_bytes"), False, RefusalCode.TYPE),
    ("preparer", ("agent", "description"), "printf '%s\\n' {{ label }}", RefusalCode.SCHEMA),
]


@pytest.mark.parametrize("which,path,value,code", RAW_REFUSALS)
def test_independent_raw_policy_catches_even_reauthorized_raw_identity(which, path, value, code):
    raw = literals()[0]
    key = {"workflow": ("workflow", "sample"), "stage": ("stage", "group")}.get(which, ("agent", which))
    target = raw[key]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = deepcopy(value)
    with pytest.raises(AdmissionRefused) as exc:
        raw_check(assemble(raw))
    assert exc.value.code == code


def test_closure_extra_missing_cycle_and_schema_controls():
    for shape in ("extra", "missing", "cycle", "version"):
        raw = literals()[0]
        if shape == "extra":
            raw[("agent", "extra")] = {"agent": {"name": "extra", "type": "script", "script_template": "printf '%s\\n' {{ label }}"}}
        elif shape == "missing":
            del raw[("agent", "caller")]
        elif shape == "cycle":
            raw[("stage", "group")]["stage"]["nodes"] = [{"name": "again", "type": "stage", "ref": "stages/group"}]
        with pytest.raises(AdmissionRefused) as exc:
            raw_check(assemble(raw, version="future" if shape == "version" else "1.0"))
        assert exc.value.code in {RefusalCode.CLOSURE, RefusalCode.LOOKUP, RefusalCode.VERSION, RefusalCode.GRAPH}


def test_literal_raw_clean_types_and_script_exception():
    raw, _, d = literals()
    prep = raw[("stage", "group")]["stage"]["nodes"][0]
    prep.update({"gate": False, "max_loops": 1, "temperature": 0.5,
                 "timeout_seconds": None, "renamed_from": "old", "undoes": ["old"]})
    # Generic JSON is valid metadata, not permission to enable raw memory.
    d["metadata_inputs_json"] = text({"label": "synthetic", "literal": [True, 1, 1.0, None, "plain"]})
    raw[("agent", "caller")]["agent"]["single_call"].update({"temperature": 1, "cost_cap_usd": "1.25", "thinking": {"type": "disabled"}})
    raw_check(assemble(raw, d))
    # No global value rule: ordinary config still accepts a literal syntactic token.
    raw[("agent", "caller")]["agent"]["single_call"]["token"] = "ordinary-explicit-label"
    raw_check(assemble(raw, d))


@pytest.mark.parametrize("scope", ["nested-node", "stage", "ref-override", "workflow", "defaults", "agent"])
@pytest.mark.parametrize("key,value", [
    pytest.param("tools", None, id="tools-null"),
    pytest.param("tools", [], id="tools-empty"),
    pytest.param("tools", ["bash"], id="tools-nonempty"),
    pytest.param("memory", None, id="memory-null"),
    pytest.param("memory", {}, id="memory-empty"),
    pytest.param("memory", {"literal": [True, 1, 1.0, None, "plain"]}, id="memory-nonempty"),
    pytest.param("fallback", None, id="fallback-null"),
    pytest.param("fallback", [], id="fallback-empty-list"),
    pytest.param("fallback", {}, id="fallback-empty-object"),
    pytest.param("fallback", [{"model": "other"}], id="fallback-nonempty"),
])
def test_raw_profile_presence_refuses_before_snapshot_loading(monkeypatch, scope, key, value):
    """V14: approved raw bytes cannot authorize a prohibited profile setting.

    Expected codes are declared by scope: existing closed-field rejection remains
    FIELDS; recognized node/workflow memory and node tools are profile SCHEMA.
    No resolved graph comparison, expansion or agent validation may do this job.
    """
    raw = literals()[0]
    workflow = raw[("workflow", "sample")]["workflow"]
    scopes = {"nested-node": raw[("stage", "group")]["stage"]["nodes"][0],
              "stage": raw[("stage", "group")]["stage"],
              "ref-override": workflow["nodes"][0], "workflow": workflow,
              "agent": raw[("agent", "preparer")]["agent"]}
    target = workflow.setdefault("defaults", {}) if scope == "defaults" else scopes[scope]
    target[key] = deepcopy(value)
    known = (scope in {"nested-node", "stage", "ref-override"} and key in {"tools", "memory"}
             or scope == "workflow" and key == "memory")
    code = RefusalCode.SCHEMA if known else RefusalCode.FIELDS
    case = assemble(raw)
    with pytest.raises(AdmissionRefused) as exc:
        raw_check(case)
    assert exc.value.code == code
    def forbidden(*args, **kwargs):
        pytest.fail("profile refusal happened after snapshot loader entry")
    monkeypatch.setattr(candidate._SnapshotLoader, "load_workflow", forbidden)
    with pytest.raises(AdmissionRefused) as exc:
        resolve(case)
    assert exc.value.code == code


@pytest.mark.parametrize("target,code", [
    pytest.param("prepare", RefusalCode.SCHEMA, id="real-loop"),
    pytest.param("", RefusalCode.SCHEMA, id="empty-loop-target"),
    pytest.param("../other", RefusalCode.SCHEMA, id="malformed-loop-target"),
    pytest.param([], RefusalCode.TYPE, id="wrong-loop-target-type"),
])
def test_raw_profile_loop_refuses_before_snapshot_loading(monkeypatch, target, code):
    raw = literals()[0]
    raw[("stage", "group")]["stage"]["nodes"][1].update(loop_to=target, max_loops=2)
    case = assemble(raw)
    with pytest.raises(AdmissionRefused) as exc:
        raw_check(case)
    assert exc.value.code == code
    def forbidden(*args, **kwargs):
        pytest.fail("loop refusal happened after snapshot loader entry")
    monkeypatch.setattr(candidate._SnapshotLoader, "load_workflow", forbidden)
    with pytest.raises(AdmissionRefused) as exc:
        resolve(case)
    assert exc.value.code == code


def change_script(d, template):
    # Alter the handwritten expected script fields, not a production projection.
    d["scripts"][0]["template_utf8"] = template
    d["scripts"][0]["template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
    cfg = json.loads(d["graph"]["nodes"][1]["factory"]["config_json"])
    cfg["script_template"] = template
    d["graph"]["nodes"][1]["factory"]["config_json"] = text(cfg)


@pytest.mark.parametrize("template,passes", [
    ("printf '%s' {{ label | env }}", True), ("printf static", True),
    ("{{ missing }}", False), ("{{ label.upper() }}", False),
    ("{% if label %}yes{% endif %}", False), ("{{ label | safe }}", False),
    ("${SYNTHETIC}", False), ("{# hidden #}", False),
])
def test_script_exception_exact_template_metadata_grammar(template, passes):
    raw, _, d = literals()
    raw[("agent", "preparer")]["agent"]["script_template"] = template
    change_script(d, template)
    case = assemble(raw, d)
    if passes:
        assert resolve(case)[2].wire == text(d["graph"]).encode()
    else:
        with pytest.raises(AdmissionRefused):
            raw_check(case)


@pytest.mark.parametrize("variables", [
    {"label": []}, {"label": "${SYNTHETIC}"}, {"label": {"nested": "not scalar"}},
])
def test_script_variables_remain_metadata(variables):
    raw, _, d = literals()
    d["scripts"][0]["variables_json"] = text(variables)
    with pytest.raises(AdmissionRefused, match="^wire_schema$"):
        raw_check(assemble(raw, d))


def test_raw_mutation_recompute_digest_cannot_self_authorize():
    raw, codec, authority, descriptor, closure, source = typed_case()
    changed = descriptor.value()
    changed["candidate_identity"] = "forged"
    self_auth = replace(authority, expected_descriptor_sha256=hashed("descriptor", changed))
    forged = ApprovedCandidateDescriptor(text(changed).encode(), self_auth)
    with pytest.raises(AdmissionRefused, match="^descriptor_authority$"):
        candidate.load_candidate(codec, forged, closure, authority=authority, source=source)
    with pytest.raises(AdmissionRefused, match="^descriptor_authority$"):
        SnapshotResolver(codec, forged, closure.records, authority=authority)
    raw[("agent", "caller")]["agent"]["single_call"]["slot"] = "A2"
    changed_records = tuple(codec.raw_record(text(raw_record(*key, v)).encode()) for key, v in sorted(raw.items()))
    with pytest.raises(AdmissionRefused, match="^digest_mismatch$"):
        candidate.load_candidate(codec, descriptor, RawClosure(changed_records), authority=authority, source=source)


def test_actual_field_projection_preserves_null_absence_numeric_types():
    cfg = NodeConfig(name="n")
    got = candidate.project_node(cfg, source=FrozenJSON(text(SOURCE).encode())).value()
    assert set(got) == {*NODE_KEYS, "_KNOWN_FIELDS"}
    assert got["max_loops"] == 1 and type(got["max_loops"]) is int
    assert got["run_after_failure"] is False and got["timeout_seconds"] is None
    values = candidate.project_agent({"bool": True, "int": 1, "float": 1.0, "null": None}).wire
    assert values == b'{"bool":true,"float":1.0,"int":1,"null":null}'
    assert candidate.project_agent({}).wire != candidate.project_agent({"optional": None}).wire
    with pytest.raises(AdmissionRefused, match="^invalid_type$"):
        candidate.project_node(replace(cfg, max_loops=True), source=FrozenJSON(text(SOURCE).encode()))
    with pytest.raises(AdmissionRefused, match="^invalid_type$"):
        candidate.project_node(replace(cfg, temperature=1), source=FrozenJSON(text(SOURCE).encode()))


@pytest.mark.parametrize("value", [NODE_KEYS, set(NODE_KEYS), frozenset({"name"}), frozenset({1})])
def test_known_fields_only_actual_complete_frozenset(value):
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        candidate.project_node(replace(NodeConfig(name="n"), _KNOWN_FIELDS=value), source=FrozenJSON(text(SOURCE).encode()))
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        candidate.project_agent({"_KNOWN_FIELDS": value})


def test_alias_and_unlisted_runtime_attributes_refuse():
    nested = {"one": 1}
    with pytest.raises(AdmissionRefused, match="^aliased_or_cyclic_value$"):
        candidate.project_agent({"left": nested, "right": nested})
    cfg = NodeConfig(name="n")
    cfg.future_field = None
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        candidate.project_node(cfg, source=FrozenJSON(text(SOURCE).encode()))


@pytest.mark.parametrize("component", ["engine_commit", "engine_tree", "binding_abi", "native", "request"])
def test_changed_actual_source_never_borrows_descriptor_expectation(component):
    _, codec, authority, descriptor, closure, _ = typed_case()
    actual = deepcopy(SOURCE)
    if component in {"native", "request"}:
        actual["field_sets"][component] = sorted([*actual["field_sets"][component], "future"])
    else:
        actual[component] = "changed"
    with pytest.raises(AdmissionRefused, match="^source_drift$"):
        candidate.load_candidate(codec, descriptor, closure, authority=authority, source=FrozenJSON(text(actual).encode()))


def test_current_native_and_accepted_key_inventory_drift_refuse(monkeypatch):
    raw, _, d = literals()
    d["source"]["field_sets"]["native"].append("zzz_future")
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        resolve(assemble(raw, d))
    # Even without a new dataclass field, accepted key drift is not hidden.
    monkeypatch.setattr(WorkflowConfig, "_KNOWN_FIELDS", WorkflowConfig._KNOWN_FIELDS | {"future"})
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        resolve(assemble(raw))


def test_changed_factory_and_actual_graph_mutations(monkeypatch):
    _, codec, authority, descriptor, closure, source = typed_case()
    nodes, workflow, original = resolve((codec, authority, descriptor, closure, source))
    nodes[0].child_nodes[1].config.gate = True
    changed = candidate.project_graph(nodes, workflow, source=source)
    assert changed.wire != original.wire  # aliased workflow configs still cannot evade independent pin
    nodes[0].child_nodes[1].config.gate = False
    nodes[0].child_nodes[1].name = "different"
    with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
        candidate.project_graph(nodes, workflow, source=source)
    class StructuralTwin(candidate.SingleCallAgent):
        pass

    monkeypatch.setitem(candidate.AGENT_TYPES, "single_call", StructuralTwin)
    with pytest.raises(AdmissionRefused, match="^source_drift$"):
        resolve((codec, authority, descriptor, closure, source))


def test_node_override_cannot_expand_native_accepted_keys():
    raw = literals()[0]
    raw[("stage", "group")]["stage"]["nodes"][1]["max_tokens"] = 200
    # NodeConfig owns this typed setting, but it is not a native agent setting.
    # The complete actual factory mapping must be checked after override merging.
    case = assemble(raw)
    raw_check(case)
    with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
        resolve(case)  # unchanged structural loader refuses this first
    _, codec, auth, desc, closure, source = typed_case()
    nodes, workflow, _ = resolve((codec, auth, desc, closure, source))
    nodes[0].child_nodes[1].agent_config["max_tokens"] = 200
    with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
        candidate.project_graph(nodes, workflow, source=source)
    for invalid in ([], {"type": []}, {"type": None}):
        nodes[0].child_nodes[1].agent_config = invalid
        with pytest.raises(AdmissionRefused, match="^invalid_type$"):
            candidate.project_graph(nodes, workflow, source=source)


def test_unpinned_template_and_default_input_transformation_refuse():
    raw = literals()[0]
    raw[("agent", "preparer")]["agent"]["script_template"] = "printf other"
    with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
        raw_check(assemble(raw))
    raw = literals()[0]
    raw[("workflow", "sample")]["workflow"]["inputs"] = {"extra": {"type": "string", "default": "unapproved"}}
    with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
        resolve(assemble(raw))


@pytest.mark.parametrize("boundary", ["markers", "types", "script", "current-native-inventory"])
def test_specific_raw_and_current_inventory_guard_removal_bites(monkeypatch, boundary):
    raw, _, d = literals()
    if boundary == "markers":
        raw[("workflow", "sample")]["workflow"]["description"] = "${SYNTHETIC}"
        with pytest.raises(AdmissionRefused, match="^wire_schema$"):
            raw_check(assemble(raw))
        monkeypatch.setattr(candidate, "_markers", lambda *args, **kw: None)
        raw_check(assemble(raw))
    elif boundary == "types":
        raw[("stage", "group")]["stage"]["nodes"][0]["max_loops"] = True
        with pytest.raises(AdmissionRefused, match="^invalid_type$"):
            raw_check(assemble(raw))
        monkeypatch.setattr(candidate, "_typed", lambda *args: True)
        raw_check(assemble(raw))
    elif boundary == "script":
        raw[("agent", "preparer")]["agent"]["script_template"] = "{{ label.upper() }}"
        with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
            raw_check(assemble(raw))
        monkeypatch.setattr(candidate, "_script", lambda *args: None)
        raw_check(assemble(raw))
    else:
        d["source"]["field_sets"]["native"].append("zzz_future")
        case = assemble(raw, d)
        with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
            resolve(case)
        monkeypatch.setattr(candidate, "source_inventory", lambda **kw: FrozenJSON(text(d["source"]).encode()))
        assert resolve(case)[2].wire == text(d["graph"]).encode()


@pytest.mark.parametrize("mutation", ["raw-policy", "projection", "source", "authority", "known-fields"])
def test_removed_guard_has_specific_literal_negative_bite(monkeypatch, mutation):
    """Each disabled boundary makes its otherwise-refused control visibly pass.

    These controlled mutants run only in memory. No repository file or external
    state is changed; passing a suite without these guards is not accepted.
    """
    raw, _, d = literals()
    if mutation == "raw-policy":
        # An ignored unknown key leaves the independently fixed effective graph identical.
        raw[("workflow", "sample")]["workflow"]["typo_ignored"] = True
        case = assemble(raw, d)
        with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
            resolve(case)
        monkeypatch.setattr(candidate, "validate_raw", lambda *args: None)
        assert resolve(case)[2].wire == text(d["graph"]).encode()
    elif mutation == "projection":
        raw[("workflow", "sample")]["workflow"]["description"] = "different"
        case = assemble(raw, d)
        with pytest.raises(AdmissionRefused, match="^graph_mismatch$"):
            resolve(case)
        monkeypatch.setattr(candidate, "project_graph", lambda *args, **kw: FrozenJSON(text(d["graph"]).encode()))
        assert resolve(case)[2].wire == text(d["graph"]).encode()
    elif mutation == "source":
        codec, auth, desc, closure, _ = assemble(raw, d)
        source = deepcopy(SOURCE) | {"engine_commit": "3" * 40}
        case = codec, auth, desc, closure, FrozenJSON(text(source).encode())
        with pytest.raises(AdmissionRefused, match="^source_drift$"):
            resolve(case)
        monkeypatch.setattr(candidate, "require_source", lambda *args: None)
        assert resolve(case)[2].wire == text(d["graph"]).encode()
    elif mutation == "authority":
        codec, auth, desc, closure, source = assemble(raw, d)
        wrong = replace(auth, expected_descriptor_sha256="0" * 64)
        case = codec, wrong, desc, closure, source
        with pytest.raises(AdmissionRefused, match="^descriptor_authority$"):
            resolve(case)
        parse = codec.descriptor
        monkeypatch.setattr(codec, "descriptor", lambda wire, supplied: parse(wire, auth))
        assert resolve(case)[2].wire == text(d["graph"]).encode()
    else:
        cfg = NodeConfig(name="n", _KNOWN_FIELDS=NODE_KEYS)
        source = FrozenJSON(text(SOURCE).encode())
        with pytest.raises(AdmissionRefused, match="^field_set_drift$"):
            candidate.project_node(cfg, source=source)
        # A malicious normalizer would erase the distinguishing runtime type.
        project = candidate._dataclass_projection
        monkeypatch.setattr(candidate, "_dataclass_projection", lambda value, cls, inventory:
                            project(replace(value, _KNOWN_FIELDS=NodeConfig._KNOWN_FIELDS), cls, inventory))
        assert candidate.project_node(cfg, source=source).value()["_KNOWN_FIELDS"] == NODE_KEYS
