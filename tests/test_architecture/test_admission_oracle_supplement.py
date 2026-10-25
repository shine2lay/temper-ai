"""Fixture structure/predictions only; no compiler, codec or production imports.

Run directly with Python's stdlib, not pytest/conftest, for the isolated campaign.
The expected reader consumes only independently authored EXPECTED data (including
pinned #306 EXPECTED literals). It never resolves candidate INPUT to get answers.
No fixture script, request or model-bound contents appear in assertion messages.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "configs/architecture/stages/context_profile"
OLD = BASE / "admission_oracles"
SUP = BASE / "admission_oracles_v1_supplement"
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
ABSOLUTE_PATH = re.compile(r"/[^\x00]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
# Second literal copy of Temper's closed T2 declaration pins (rm-31e24c00).
REQUEST_FIELDS = ["inputs", "notify", "workflow", "workspace_path"]
REQUEST_SOURCE = {
    "status": "PRE_COMMIT_DECLARATION_REBIND_IF_MOVED",
    "declared_by": "Temper rm-31e24c00, answering Architecture rm-78058d55 (2026-10-25)",
    "document": "/home/shinelay/company-lab/candidate-admission-t2-198/REQUEST-OPTIONS.md",
    "document_sha256": "b6347a80cd927df39430aed954acef561cfcece51b6d3179d73bb10d985b823a",
    "base_commit": "caf5c16f6d9965cbcbc8e10653d75e1c47b27340",
    "base_tree": "726bf8e8a198f1436bf8caf84bbf2a8115601e47",
    "branch": "temper-198-admission-transport",
    "staged_diff_sha256": "59e9ef9e074d896e5e65114e43af61087ac0fd0f1ed787573ad446e1aef93d4d",
    "files": {
        "temper_ai/api/routes.py": {
            "git_blob": "4cd4ec72eece985b7f6c37cdbef6b8c51a044814",
            "sha256": "594b565be89e1b59409cef8a20452ad9052deaa14e5c3a6a170ea84b3abc3222"},
        "temper_ai/runner/admission.py": {
            "git_blob": "7b943da86e62dc2c940f52fc973d9918107e922a",
            "sha256": "cbe67b609e328fccc7f72177e838e077bad8800eebbf16090194bf1ce97481ff"},
    },
}


def require(condition, label):
    if not condition:
        raise AssertionError(label)


def exact(left, right):
    """Equality preserving bool/int/float, absence/null and array order."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(exact(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def same(left, right, label):
    require(exact(left, right), label)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def finite(value):
    if type(value) is float:
        require(math.isfinite(value), "nonfinite JSON number")
    elif type(value) is dict:
        for item in value.values():
            finite(item)
    elif type(value) is list:
        for item in value:
            finite(item)


def strict(text):
    value = json.loads(text, object_pairs_hook=pairs)
    finite(value)
    return value


def load(path):
    return strict(path.read_text(encoding="utf-8"))


def canonical_fixture(value):
    """Deterministic fixture digest encoding, NOT a general CAJ-1 codec.

    This packet has no floats. It never encodes wire digests or authority. A
    consumer must use #192 for wire bytes/digest domains, including float rules.
    """
    def check(item):
        require(type(item) in (dict, list, str, int, bool, type(None)), "fixture exact JSON types")
        if type(item) is dict:
            require(all(type(k) is str for k in item), "fixture string keys")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def table(columns, rows):
    require(len(set(columns)) == len(columns), "table column uniqueness")
    for row in rows:
        require(type(row) is list and len(row) == len(columns), "complete literal row")
        yield dict(zip(columns, copy.deepcopy(row), strict=True))


def input_packet():
    closure = load(SUP / "INPUT/closure.json")
    native = load(SUP / "INPUT/native.json")
    records = copy.deepcopy(closure["records"])
    native_paths = {}
    for row in table(native["columns"], native["rows"]):
        key = row.pop("raw_record_id")
        native_paths[key] = row.pop("node_path")
        require(key not in records, "duplicate raw record")
        records[key] = {**copy.deepcopy(native["envelope"]), "single_call": row}
    return {"schema_version": closure["schema_version"], "origin": closure["origin"],
            "file_base64": closure["file_base64"], "records": records, "native_paths": native_paths}


def expected_packet():
    """Storage decoding only: never reads INPUT or derives expected semantics."""
    graph = load(SUP / "EXPECTED/graph.json")
    identities = load(SUP / "EXPECTED/identities.json")
    facts = load(SUP / "source-facts.json")
    old_positions = load(OLD / "expected-positions.json")["EXPECTED"]
    old_graph = load(OLD / "expected-graph.json")["EXPECTED"]
    natives = {}
    for row in table(old_positions["columns"], old_positions["rows"]):
        old_id = row.pop("position_id")
        path = row.pop("node_path")
        row.pop("predecessor")
        natives[old_id] = {"path": path, "config": {
            **copy.deepcopy(old_positions["native_envelope"]), "single_call": row}}
    positions = []
    factories = {}
    for identity in table(identities["columns"], identities["rows"]):
        old_id = identity.pop("old_position")
        native = natives[old_id]
        same(identities["old_node_paths"][old_id], native["path"], "literal legacy node path mapping")
        position = {**identity, "agent_config": copy.deepcopy(native["config"])}
        positions.append(position)
        factories[tuple(position["node_path"])] = {
            **facts["factories"]["single_call"], "config": copy.deepcopy(native["config"])}
    nodes = {}
    for row in table(graph["columns"], graph["rows"]):
        path = tuple(row.pop("path"))
        require(path not in nodes, "unique expected node path")
        require(not (row.keys() & graph["node_envelope"].keys()), "disjoint literal envelope")
        nodes[path] = {**copy.deepcopy(graph["node_envelope"]), **row}
        if row["type"] == "stage":
            factories[path] = None
    scripts = {}
    roots = list(table(identities["root_columns"], identities["roots"]))
    for root in roots:
        for path, old_key in root["script_expected_bindings"]:
            config = copy.deepcopy(old_graph["script_agents"][old_key])
            config["_KNOWN_FIELDS"] = copy.deepcopy(facts["node_accepted_keys"])
            factories[tuple(path)] = {**facts["factories"]["script"], "config": config}
            scripts[tuple(path)] = {"template_utf8": config["script_template"],
                                    "variables": copy.deepcopy(root["script_variables"])}
    return {"workflow": graph["workflow"], "nodes": nodes, "factories": factories,
            "positions": positions, "scripts": scripts, "roots": roots}


def reachable(packet):
    """Inspect literal reference membership; no loader/factory/default execution."""
    records = packet["records"]
    used = {"workflow:oracle306"}
    paths, calls = [], []
    workflow = records["workflow:oracle306"]
    for root in workflow["nodes"]:
        root_path = (root["name"],)
        paths.append(root_path)
        ref = root["ref"]
        require(type(ref) is str and ref.startswith("stages/"), "qualified stage reference")
        stage_id = "stage:" + ref.removeprefix("stages/")
        require(stage_id in records, "stage reference closure")
        used.add(stage_id)
        for node in records[stage_id]["nodes"]:
            path = (*root_path, node["name"])
            require(path not in paths, "unique raw node path")
            paths.append(path)
            ref = node["agent"]
            require(type(ref) is str and ref.startswith("agents/"), "qualified agent reference")
            agent_id = "agent:" + ref.removeprefix("agents/")
            require(agent_id in records, "agent reference closure")
            used.add(agent_id)
            if records[agent_id]["type"] == "single_call":
                calls.append(path)
    same(used, set(records), "raw closure has neither orphan nor missing record")
    return paths, calls


def check_input(packet, expected):
    facts = load(SUP / "source-facts.json")
    same(packet["schema_version"], "1.0", "source-correct raw schema_version, no coercion")
    same(packet["origin"], {"kind": "db"}, "DB origin is synthetic, not custody")
    same(packet["file_base64"], None, "no invented original YAML")
    paths, calls = reachable(packet)
    same(paths, list(expected["nodes"]), "exact raw/EXPECTED preorder path equality")
    wanted_calls = [tuple(p["node_path"]) for p in expected["positions"]]
    same(calls, wanted_calls, "exact 42 raw/position paths, not cardinality")
    records = packet["records"]
    workflow = records["workflow:oracle306"]
    same(set(workflow), {"name", "description", "version", "inputs", "outputs", "safety",
                         "on_failure", "notify", "starts_runs", "nodes"}, "closed literal workflow raw fields")
    for field, value in workflow.items():
        if field != "nodes":
            same(value, expected["workflow"][field], "literal workflow policy/value")
    same([list(p) for p in paths if len(p) == 1], expected["workflow"]["nodes"], "all root paths")
    for root, root_literal in zip(workflow["nodes"], expected["roots"], strict=True):
        path = (root["name"],)
        same(root["ref"], "stages/" + root_literal["raw_stage_record"].split(":", 1)[1], "explicit raw-stage mapping")
        wanted = expected["nodes"][path]
        root_keys = {"name", "type", "ref"} if path == ("r01",) else {
            "name", "type", "ref", "depends_on", "input_map"}
        same(set(root), root_keys, "root raw absence stays exact")
        for key in root_keys - {"ref"}:
            same(root[key], wanted[key], "root raw policy")
        stage = records[root_literal["raw_stage_record"]]
        same(set(stage), {"name", "nodes"}, "closed raw stage fields")
        same(stage["name"], root_literal["raw_stage_record"].split(":", 1)[1], "raw stage name")
        same([list((*path, n["name"])) for n in stage["nodes"]], wanted["nodes"], "all eight serial children")
        source_key = "record_id" if path == ("r01",) else root["input_map"]["record_id"].removeprefix("input.")
        same(workflow["inputs"][source_key]["default"], root_literal["script_variables"]["record_id"],
             "explicit synthetic script variable mapping")
        for node in stage["nodes"]:
            leaf_path = (*path, node["name"])
            target = expected["nodes"][leaf_path]
            factory = expected["factories"][leaf_path]
            is_native = factory["type"] == "single_call"
            keys = {"name", "agent", "input_map"}
            if node["name"] != "prepare":
                keys.add("depends_on")
            if is_native:
                keys.add("inputs")
            if node["name"] == "receipt":
                keys.add("run_after_failure")
            same(set(node), keys, "closed leaf raw fields/absence")
            for key, value in node.items():
                same(value, target[key], "all literal leaf policies and serial edges")
            for key in set(facts["node_defaults"]) - set(node) - {"nodes", "ref"}:
                same(target[key], facts["node_defaults"][key], "all omitted effective defaults retained")
            agent = records["agent:" + node["agent"].removeprefix("agents/")]
            if is_native:
                agent_id = "agent:" + node["agent"].removeprefix("agents/")
                same(packet["native_paths"][agent_id], list(leaf_path), "literal INPUT native row path")
                same(agent, factory["config"], "full native map at exact node, not sorted bag")
            else:
                wanted_raw = {key: factory["config"][key] for key in (
                    "name", "type", "script_template", "strict_undefined")}
                same(agent, wanted_raw, "exact script bytes and raw metadata")


def check_expected(candidate, trusted):
    facts = load(SUP / "source-facts.json")
    same(sorted(candidate["workflow"]), facts["workflow_fields"], "full workflow inventory")
    same(candidate["workflow"]["_KNOWN_FIELDS"], facts["workflow_accepted_keys"], "workflow metadata membership")
    for field in ("memory", "defaults"):
        same(candidate["workflow"][field], facts["workflow_defaults"][field], "omitted workflow defaults")
    same(list(candidate["nodes"]), list(trusted["nodes"]), "expected full graph membership/order")
    same(set(candidate["factories"]), set(candidate["nodes"]), "factory for every node")
    for path, node in candidate["nodes"].items():
        same(sorted(node), facts["node_fields"], "full node inventory including metadata")
        same(node["_KNOWN_FIELDS"], facts["node_accepted_keys"], "node metadata membership")
        varied = {"name", "type", "agent", "nodes", "depends_on", "run_after_failure", "input_map", "inputs"}
        for field in set(facts["node_defaults"]) - varied:
            same(node[field], facts["node_defaults"][field], "frozen effective default/policy")
        factory = candidate["factories"][path]
        if node["type"] == "stage":
            same(factory, None, "stage factory null")
        else:
            require(type(factory) is dict, "agent factory required")
            same(set(factory), {"type", "class_name", "config"}, "full factory binding")
            require(factory["type"] in facts["factories"], "supported exact factory type")
            same(factory["class_name"], facts["factories"][factory["type"]]["class_name"], "qualified factory class")
            if factory["type"] == "script":
                same(sorted(factory["config"]), facts["script_effective_fields"], "inherited script metadata fields")
                same(factory["config"]["_KNOWN_FIELDS"], facts["node_accepted_keys"], "inherited script metadata membership")
                same(factory["config"]["run_after_failure"], node["run_after_failure"], "script failure policy")
            else:
                config = factory["config"]
                same(sorted(config), facts["native_envelope_accepted_keys"], "native envelope closed")
                same(set(config["single_call"]), set(facts["native_literal_types"]), "native present/absent fields")
                for key, value in config["single_call"].items():
                    same(type(value).__name__, facts["native_literal_types"][key], "native exact type")
    seen = set()
    for position in candidate["positions"]:
        same(set(position), {"position_id", "node_path", "preparation_path", "record_id", "variant_id",
                             "call_id", "slot", "root_policy", "agent_config"}, "complete identity fields")
        require(type(position["position_id"]) is str and bool(NAME.fullmatch(position["position_id"])), "wire-safe explicit position_id")
        require(position["position_id"] not in seen, "no identity collisions")
        seen.add(position["position_id"])
        for key in ("record_id", "variant_id", "call_id"):
            require(type(position[key]) is str and bool(position[key]), "explicit nonempty label")
        for key in ("node_path", "preparation_path"):
            require(type(position[key]) is list and all(type(x) is str and NAME.fullmatch(x) for x in position[key]), "wire path names")
        same(position["root_policy"], None, "unresolved real custody stays null")
        factory = candidate["factories"][tuple(position["node_path"])]
        same(factory["type"], "single_call", "position names a single_call")
        same(position["agent_config"], factory["config"], "position bound to full map")
        same(candidate["factories"][tuple(position["preparation_path"])]["type"], "script", "preparation names admitted script")
    native_paths = [p for p, f in candidate["factories"].items() if f is not None and f["type"] == "single_call"]
    same([tuple(p["node_path"]) for p in candidate["positions"]], native_paths, "exact expected single_call/position equality")
    same(candidate, trusted, "unchanged independent EXPECTED, including full policies and identities")


def check_request(candidate):
    expected = load(SUP / "EXPECTED/request.json")
    same(sorted(candidate), expected["field_names"], "closed request-options inventory")
    for key, value in candidate.items():
        same(type(value).__name__, expected["literal_types"][key], "request option exact type")
    same(candidate, expected["options"], "complete pinned request options, no defaults filled")


def check_request_declaration(candidate):
    """Structure of the expected request/descriptor metadata; no runtime claim."""
    same(candidate["runtime_status"], "UNEXECUTED", "request declaration is not runtime proof")
    source = candidate["source"]
    for key, value in REQUEST_SOURCE.items():
        same(source[key], value, "closed T2 declaration source pin")
    same(set(source), set(REQUEST_SOURCE) | {"declaration", "limits"}, "closed source pin fields")
    same(candidate["field_names"], REQUEST_FIELDS, "closed sorted request inventory")
    same(sorted(candidate["field_declarations"]), REQUEST_FIELDS, "every option declared")
    same(sorted(candidate["literal_types"]), REQUEST_FIELDS, "every option typed")
    same(sorted(candidate["options"]), REQUEST_FIELDS, "all four keys always present")
    names = {"dict": "dict", "str": "str", "None": "NoneType"}
    for key, declaration in candidate["field_declarations"].items():
        require(type(declaration["required"]) is bool, "required flag is a bool")
        same("default" in declaration, not declaration["required"], "default present exactly when optional")
        same(declaration["always_present"], True, "dump key always present")
        require(declaration["explicit_null"] in ("invalid", "same as absent"), "declared null semantics")
        allowed = {names[part] for part in declaration["source_type"].split(" | ")}
        same("NoneType" in allowed, declaration["explicit_null"] == "same as absent", "null semantics match source type")
        literal = candidate["literal_types"][key]
        require(literal in allowed, "literal type allowed by source type")
        same(type(candidate["options"][key]).__name__, literal, "literal option exact type")
        if "default" in declaration:
            require(type(declaration["default"]).__name__ in allowed, "default allowed by source type")
    same(candidate["field_declarations"]["workflow"]["canonical_key"], "workflow", "alias dumps as workflow")
    require("admission" in candidate["excluded_from_options"] and "admission" not in REQUEST_FIELDS, "admission excluded")
    require(not set(candidate["not_option_keys"]) & set(REQUEST_FIELDS), "identities are not options")
    metadata = candidate["descriptor_metadata"]
    same(set(metadata), {"labelled", "mode", "candidate_identity", "logical_run_id", "execution_uuid",
                         "workflow_name", "workspace_path"}, "closed descriptor metadata")
    same(metadata["labelled"], "SYNTHETIC_FIXTURE_IDENTITIES_NOT_REAL_RUN_DECLARATIONS", "synthetic label")
    same(metadata["mode"], "external-db-fresh", "only supported mode")
    for key in ("candidate_identity", "workflow_name"):
        require(type(metadata[key]) is str and bool(NAME.fullmatch(metadata[key])), "wire name")
    require(type(metadata["logical_run_id"]) is str and bool(metadata["logical_run_id"]), "nonempty label")
    require(type(metadata["execution_uuid"]) is str and bool(UUID.fullmatch(metadata["execution_uuid"])), "lowercase UUID")
    require(metadata["execution_uuid"] != metadata["logical_run_id"], "logical run id is not the execution UUID")
    require(type(metadata["workspace_path"]) is str and bool(ABSOLUTE_PATH.fullmatch(metadata["workspace_path"])), "absolute path")
    same(candidate["options"]["workspace_path"], metadata["workspace_path"], "ingress exact workspace equality")
    same(candidate["options"]["workflow"], metadata["workflow_name"], "options name the descriptor workflow")
    same(candidate["metadata_inputs"], candidate["options"]["inputs"], "metadata inputs = caller inputs, no defaults")
    left = candidate["inputs_left_to_workflow_defaults"]
    require(type(left) is list and left == sorted(set(left)), "sorted unique default-left inputs")
    require(not set(left) & set(candidate["metadata_inputs"]), "defaults never filled into metadata")


def check_field_sets(candidate):
    """Literal v1 source.field_sets correspondence; never derived from a descriptor."""
    wanted = load(SUP / "source-facts.json")["wire_field_sets"]
    same(sorted(candidate), ["native", "node", "request", "workflow"], "closed v1 fieldSets members")
    for names in candidate.values():
        require(type(names) is list and all(type(n) is str and n for n in names), "field set is a names array")
        same(names, sorted(set(names)), "sorted unique field names")
    same(candidate["workflow"], wanted["workflow"], "workflow inventory includes _KNOWN_FIELDS")
    same(candidate["node"], wanted["node"], "node inventory includes _KNOWN_FIELDS")
    same(candidate["native"], wanted["native"], "native is the permitted inner single_call set")
    same(candidate["request"], load(SUP / "EXPECTED/request.json")["field_names"], "closed request inventory")


def source_class(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)


def declaration_fields(tree, name):
    return {n.target.id: n for n in source_class(tree, name).body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}


def literal_default(node):
    """Read known declaration syntax; never compile, eval or import source."""
    value = node.value
    if isinstance(value, ast.Call):
        require(isinstance(value.func, ast.Name) and value.func.id == "field", "known dataclass default form")
        require(len(value.keywords) == 1 and value.keywords[0].arg == "default_factory", "known factory keyword")
        factory = value.keywords[0].value
        require(isinstance(factory, ast.Name) and factory.id in ("dict", "list"), "plain default factory declaration")
        return {} if factory.id == "dict" else []
    return ast.literal_eval(value)


class SupplementTests(unittest.TestCase):
    def test_00_clean_full_graph_and_native_mapping(self):
        trusted = expected_packet()
        check_expected(copy.deepcopy(trusted), trusted)
        packet = input_packet()
        check_input(packet, trusted)
        paths, calls = reachable(packet)
        same(len(packet["records"]), 60, "60 closed raw records")
        same(len(paths), 126, "126 nodes in preorder")
        same(len(calls), 42, "42 literal call paths")
        same(len(trusted["scripts"]), 70, "70 script occurrences")
        same(len(trusted["roots"]), 14, "14 complete roots")
        sequence = ["prepare", "call_A1", "account_A1", "call_A2", "account_A2", "call_A3", "account_A3", "receipt"]
        roots = ["r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08", "r09", "r10", "r11", "r12", "r13", "r14"]
        same([r["path"][0] for r in trusted["roots"]], roots, "literal fourteen-root inventory")
        for i, root in enumerate(trusted["roots"]):
            path = root["path"][0]
            same([p[-1] for p in trusted["nodes"][(path,)]["nodes"]], sequence, "every preparation/accounting/receipt present")
            same(trusted["nodes"][(path,)]["depends_on"], [] if i == 0 else [roots[i - 1]], "serial record predecessors")
            for j, name in enumerate(sequence):
                same(trusted["nodes"][(path, name)]["depends_on"], [] if j == 0 else [sequence[j - 1]], "serial intra-record predecessor")
        same({slot: sum(p["slot"] == slot for p in trusted["positions"]) for slot in ("A1", "A2", "A3")},
             {"A1": 14, "A2": 14, "A3": 14}, "preserved V02 slot inventory")

    def test_01_source_declarations_and_exact_defaults(self):
        facts = load(SUP / "source-facts.json")
        # Byte pins are provenance at the basis commit, checked at open/close by git;
        # a lasting suite asserts the declarations themselves (AST), not bytes.
        same(facts["declarations"]["commit"], "56b833e6e6e990e966a1e61a204fd92c5c9f690a", "declaration basis")
        same(len(facts["declarations"]["files"]), 7, "seven declaration files")
        for name, digest in facts["declarations"]["files"].items():
            require((ROOT / name).is_file() and bool(SHA256.fullmatch(digest)), "declaration file and provenance pin")
        tree = ast.parse((ROOT / "temper_ai/stage/models.py").read_text())
        for cls, prefix in (("WorkflowConfig", "workflow"), ("NodeConfig", "node")):
            fields = declaration_fields(tree, cls)
            same(sorted(fields), facts[prefix + "_fields"], "source dataclass fields")
            same({name: ast.unparse(node.annotation) for name, node in fields.items()},
                 facts[prefix + "_annotations"], "all source field type annotations")
            metadata = fields["_KNOWN_FIELDS"]
            same(ast.unparse(metadata.annotation), "frozenset", "source runtime metadata declaration")
            same(metadata.value.func.id, "frozenset", "exact metadata constructor declaration")
            same(sorted(ast.literal_eval(metadata.value.args[0])), facts[prefix + "_accepted_keys"], "source accepted-key membership")
            for name, expected in facts[prefix + "_defaults"].items():
                same(literal_default(fields[name]), expected, "source default exact type/value")
        config = ast.parse((ROOT / "temper_ai/config/models.py").read_text())
        version = declaration_fields(config, "Config")["schema_version"]
        same(ast.unparse(version.annotation), "str", "Config version type")
        same(ast.literal_eval(version.value.keywords[0].value), "1.0", "Config version default")
        store = ast.parse((ROOT / "temper_ai/config/store.py").read_text())
        save = next(n for n in ast.walk(store) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "put")
        args = list(save.args.args)
        defaults = [None] * (len(args) - len(save.args.defaults)) + list(save.args.defaults)
        version_arg = next((arg, default) for arg, default in zip(args, defaults, strict=True) if arg.arg == "schema_version")
        same(ast.unparse(version_arg[0].annotation), "str", "ConfigStore version type")
        same(ast.literal_eval(version_arg[1]), "1.0", "ConfigStore version default")

    def test_02_native_and_factory_declarations(self):
        facts = load(SUP / "source-facts.json")
        tree = ast.parse((ROOT / "temper_ai/agent/single_call_agent.py").read_text())
        assignments = {n.targets[0].id: n.value for n in tree.body
                       if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
        required = ast.literal_eval(assignments["SINGLE_CALL_REQUIRED"].args[0])
        envelope = ast.literal_eval(assignments["SINGLE_CALL_AGENT_SETTINGS"].args[0])
        optional = ast.literal_eval(assignments["SINGLE_CALL_SETTINGS"].right)
        same(sorted(required), facts["native_required_keys"], "native required declaration")
        same(sorted(envelope), facts["native_envelope_accepted_keys"], "native envelope declaration")
        same(sorted(required | optional), facts["native_permitted_keys"], "full optional inventory, not just fixture keys")
        tree = ast.parse((ROOT / "temper_ai/agent/__init__.py").read_text())
        registry = next(n.value for n in tree.body if isinstance(n, ast.AnnAssign) and n.target.id == "AGENT_TYPES")
        imports = {a.asname or a.name: n.module + "." + a.name for n in tree.body
                   if isinstance(n, ast.ImportFrom) for a in n.names}
        classes = {ast.literal_eval(k): imports[v.id] for k, v in zip(registry.keys, registry.values, strict=True)}
        for kind in ("script", "single_call"):
            same(classes[kind], facts["factories"][kind]["class_name"], "full qualified factory declaration")

    def test_03_old306_all_eleven_paths_unchanged(self):
        facts = load(SUP / "source-facts.json")
        manifest = load(OLD / "manifest.json")
        same(manifest["files"], facts["old306_files"], "eight-member original manifest")
        same(load(OLD / "inputs.json")["INPUT"]["schema_version"], 1, "historical integer mismatch retained")
        for name, digest in facts["old306_files"].items():
            same(sha((OLD / name).read_bytes()), digest, "old306 artifact equality")
        same(sha((OLD / "manifest.json").read_bytes()), facts["old306_manifest_sha256"], "original manifest unchanged")
        for name, digest in facts["old306_other_paths"].items():
            same(sha((ROOT / name).read_bytes()), digest, "original test/report unchanged")

    def test_04_request_fields_exact(self):
        check_request(load(SUP / "INPUT/request.json"))
        declaration = load(SUP / "EXPECTED/request.json")
        check_request_declaration(declaration)
        same(declaration["descriptor_metadata"]["workflow_name"], expected_packet()["workflow"]["name"],
             "descriptor names the independently expected workflow")
        workflow_inputs = input_packet()["records"]["workflow:oracle306"]["inputs"]
        same(sorted(set(workflow_inputs) - set(declaration["metadata_inputs"])),
             declaration["inputs_left_to_workflow_defaults"], "every undeclared caller input is left to defaults")
        require(set(declaration["metadata_inputs"]) <= set(workflow_inputs), "caller inputs are declared inputs")

    def test_05_raw_missing_root_or_call_is_not_cardinality_only(self):
        expected = expected_packet()
        for label in ("missing-root", "missing-call", "extra-call", "orphan-record", "wrong-valid-call"):
            with self.subTest(defect=label):
                packet = input_packet()
                nodes = packet["records"]["stage:oracle306_r14"]["nodes"]
                if label == "missing-root":
                    packet["records"]["workflow:oracle306"]["nodes"].pop()
                elif label == "missing-call":
                    nodes.pop(5)
                elif label == "extra-call":
                    extra = copy.deepcopy(nodes[5])
                    extra["name"] = "call_A4"
                    nodes.append(extra)
                elif label == "orphan-record":
                    packet["records"]["agent:orphan"] = {"type": "single_call"}
                else:
                    nodes[5]["name"] = "call_A4"
                with self.assertRaises(AssertionError):
                    check_input(packet, expected)

    def test_06_each_serial_edge_and_policy_is_checked(self):
        expected = expected_packet()
        for root in expected["roots"]:
            for index in range(8):
                with self.subTest(root=root["path"][0], child=index):
                    packet = input_packet()
                    node = packet["records"][root["raw_stage_record"]]["nodes"][index]
                    node["depends_on"] = ["receipt"]
                    with self.assertRaises(AssertionError):
                        check_input(packet, expected)
        for field, value in (("on_failure", "cleanup"), ("gate", True), ("timeout_seconds", 1),
                             ("run_after_failure", False), ("inputs", {})):
            candidate = expected_packet()
            candidate["nodes"][("r14", "receipt")][field] = value
            with self.assertRaises(AssertionError):
                check_expected(candidate, expected)

    def test_07_raw_version_rejects_int_bool_float_null(self):
        expected = expected_packet()
        for value in (1, True, 1.0, None, "1"):
            packet = input_packet()
            packet["schema_version"] = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(AssertionError):
                check_input(packet, expected)

    def test_08_metadata_omission_wrong_members_and_types(self):
        trusted = expected_packet()
        for target in ("workflow", "node", "script"):
            for defect in ("missing", "membership", "null", "unordered"):
                candidate = expected_packet()
                obj = candidate["workflow"] if target == "workflow" else (
                    candidate["nodes"][("r01", "prepare")] if target == "node" else
                    candidate["factories"][("r01", "prepare")]["config"])
                if defect == "missing":
                    del obj["_KNOWN_FIELDS"]
                elif defect == "membership":
                    obj["_KNOWN_FIELDS"].append("invented")
                elif defect == "null":
                    obj["_KNOWN_FIELDS"] = None
                else:
                    obj["_KNOWN_FIELDS"].reverse()
                with self.subTest(target=target, defect=defect), self.assertRaises(AssertionError):
                    check_expected(candidate, trusted)
        packet = input_packet()
        packet["records"]["stage:oracle306_r01"]["nodes"][0]["_KNOWN_FIELDS"] = []
        with self.assertRaises(AssertionError):
            check_input(packet, trusted)

    def test_09_full_factory_and_native_identity(self):
        trusted = expected_packet()
        for field, value in (("type", "script"), ("class_name", "SingleCallAgent"), ("config", {})):
            candidate = expected_packet()
            candidate["factories"][("r14", "call_A3")][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                check_expected(candidate, trusted)
        candidate = expected_packet()
        candidate["factories"].pop(("r14", "receipt"))
        with self.assertRaises(AssertionError):
            check_expected(candidate, trusted)

    def test_10_request_missing_extra_and_wrong_type(self):
        original = load(SUP / "INPUT/request.json")
        for key in original:
            candidate = copy.deepcopy(original)
            del candidate[key]
            with self.subTest(defect="missing", field=key), self.assertRaises(AssertionError):
                check_request(candidate)
            candidate = copy.deepcopy(original)
            candidate[key] = 1 if type(original[key]) is not int else True
            with self.subTest(defect="type", field=key), self.assertRaises(AssertionError):
                check_request(candidate)
        candidate = {**original, "invented_request_option": None}
        with self.assertRaises(AssertionError):
            check_request(candidate)
        defects = {
            "filled_default": {**original, "inputs": {**original["inputs"], "record_r02": "r02"}},
            "inputs_null": {**original, "inputs": None},
            "inputs_empty": {**original, "inputs": {}},
            "workspace_null": {**original, "workspace_path": None},
            "workspace_old306": {**original, "workspace_path": "/synthetic/306/workspace"},
            "notify_empty_map": {**original, "notify": {}},
            "alias_not_canonical": {**{k: v for k, v in original.items() if k != "workflow"},
                                    "workflow_name": original["workflow"]},
            "admission_included": {**original, "admission": None},
        }
        for label, candidate in defects.items():
            with self.subTest(defect=label), self.assertRaises(AssertionError):
                check_request(candidate)

    def test_11_missing_colliding_wrong_valid_and_invalid_identity(self):
        trusted = expected_packet()
        for key in ("position_id", "record_id", "variant_id", "call_id", "preparation_path"):
            candidate = expected_packet()
            del candidate["positions"][0][key]
            with self.subTest(field=key), self.assertRaises(AssertionError):
                check_expected(candidate, trusted)
        for key, value in (("position_id", "r01_A2"), ("position_id", "r01/A1"),
                           ("record_id", "r02"), ("variant_id", "V02_inventory"),
                           ("call_id", "A2"), ("preparation_path", ["r02", "prepare"])):
            candidate = expected_packet()
            candidate["positions"][0][key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                check_expected(candidate, trusted)

    def test_12_position_missing_extra_and_whole_map_swap(self):
        trusted = expected_packet()
        for defect in ("missing", "extra", "slot", "whole_maps", "coordinated_graph"):
            candidate = expected_packet()
            if defect == "missing":
                candidate["positions"].pop()
            elif defect == "extra":
                candidate["positions"].append(copy.deepcopy(candidate["positions"][0]))
            elif defect == "slot":
                candidate["positions"][0]["agent_config"]["single_call"]["slot"] = "A2"
            else:
                first, second = candidate["positions"][0], candidate["positions"][3]
                first["agent_config"], second["agent_config"] = second["agent_config"], first["agent_config"]
                if defect == "coordinated_graph":
                    for pos in (first, second):
                        candidate["factories"][tuple(pos["node_path"])]["config"] = copy.deepcopy(pos["agent_config"])
            with self.subTest(defect=defect), self.assertRaises(AssertionError):
                check_expected(candidate, trusted)

    def test_13_changed_input_and_recomputed_self_hash_not_an_answer(self):
        trusted = expected_packet()
        packet = input_packet()
        before = sha(canonical_fixture(packet))
        before_bag = sorted(sha(canonical_fixture(record)) for record in packet["records"].values())
        one, two = "agent:oracle306_r01_A1", "agent:oracle306_r02_A1"
        packet["records"][one], packet["records"][two] = packet["records"][two], packet["records"][one]
        same(sorted(sha(canonical_fixture(record)) for record in packet["records"].values()),
             before_bag, "whole-map bag and valid A1 slots unchanged")
        forged_self_hash = sha(canonical_fixture(packet))
        require(before != forged_self_hash, "mutation changes input digest")
        same(forged_self_hash, sha(canonical_fixture(packet)), "coordinated input self-hash control")
        with self.assertRaises(AssertionError):
            check_input(packet, trusted)
        check_input(input_packet(), trusted)

    def test_14_old36_case_semantics_and_all_explicit_variants(self):
        old = load(OLD / "cases.json")
        mapping = load(SUP / "EXPECTED/case-mapping.json")
        same(sha((OLD / "cases.json").read_bytes()),
             "4ea19e447ae944db27fc151365b89c587a1138ff69b599cfbe3387c9c52afc8b", "all old meanings/counters retained")
        same(list(mapping["cases"]), [case["id"] for case in old["cases"]], "all36 original cases mapped")
        same(len(old["cases"]), 36, "36 cases")
        seen = set()
        for case in old["cases"]:
            mapped = mapping["cases"][case["id"]]
            same([x[0] for x in mapped], [x[0] for x in case["INPUT"]["variants"]], "each variant explicitly mapped")
            for _, variant_id in mapped:
                require(NAME.fullmatch(variant_id) and variant_id not in seen, "unique wire-safe synthetic variant")
                seen.add(variant_id)
            same(case["EXPECTED"]["runtime_status"], "UNEXECUTED", "old predictions remain unexecuted")
        same(mapping["runtime_status"], "UNEXECUTED", "no runtime claim")

    def test_15_strict_json_and_exact_type_negatives(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e400}'):
            with self.assertRaises(AssertionError):
                strict(text)
        require(not exact(True, 1) and not exact(1, 1.0) and not exact({}, {"x": None}), "exact types and absence")
        for path in SUP.rglob("*.json"):
            load(path)

    def test_16_stdlib_only_expected_independence(self):
        tree = ast.parse(Path(__file__).read_text())
        allowed = {"__future__", "ast", "copy", "hashlib", "json", "math", "re", "sys", "unittest", "pathlib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                require(all(a.name in allowed for a in node.names), "stdlib imports only")
            elif isinstance(node, ast.ImportFrom):
                require(node.module in allowed, "stdlib imports only")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                require(node.func.id not in {"eval", "exec", "compile", "__import__"}, "no production/source execution")
        expected_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "expected_packet")
        for node in ast.walk(expected_fn):
            if isinstance(node, ast.Constant) and type(node.value) is str:
                require("INPUT/" not in node.value and node.value not in {"inputs.json", "closure.json", "native.json"},
                        "EXPECTED never loads INPUT")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                require(node.func.id not in {"input_packet", "reachable", "check_input"}, "EXPECTED never uses INPUT adapter")
        if __name__ == "__main__":
            require(not any(name == "temper_ai" or name.startswith("temper_ai.") for name in sys.modules),
                    "standalone campaign imported no production module")
        facts = load(SUP / "source-facts.json")
        for key in ("authority", "custody", "installed_source_attestation"):
            same(facts[key], None, "no invented runtime authority")
        same(facts["runnable"], False, "fixture-only")

    def test_17_supplement_manifest_and_wire_mapping(self):
        manifest = load(SUP / "manifest.json")
        for name, digest in manifest["files"].items():
            same(sha((SUP / name).read_bytes()), digest, "supplement file hash")
        actual = {str(p.relative_to(SUP)) for p in SUP.rglob("*") if p.is_file()}
        same(actual, set(manifest["files"]) | {"manifest.json"}, "complete supplemental manifest")
        mapping = load(SUP / "wire-mapping.json")
        same(mapping["binding_abi"], "candidate-admission/v1", "one frozen wire contract")
        same(mapping["runtime_status"], "UNEXECUTED", "wire mapping not runtime")
        same(mapping["schema_sha256"], "426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d", "frozen schema pin")
        # Literal frozen-schema field correspondence, not a substitute validator.
        fields = {
            "rawRecord": ["format", "kind", "name", "schema_version", "origin", "config_json", "file_base64"],
            "expectedRaw": ["kind", "name", "schema_version", "origin", "raw_sha256"],
            "graph": ["workflow_json", "nodes"],
            "node": ["path", "node_json", "factory"],
            "factory": ["type", "class_name", "config_json"],
            "position": ["position_id", "node_path", "preparation_path", "record_id", "variant_id", "call_id", "slot", "agent_config_json", "root_policy"],
            "script": ["node_path", "template_utf8", "template_sha256", "variables_json"],
            "source": ["engine_commit", "engine_tree", "binding_abi", "field_sets"],
            "descriptor": ["format", "profile", "mode", "candidate_identity", "logical_run_id", "execution_uuid", "workflow_name", "workspace_path", "metadata_inputs_json", "request_options_json", "source", "records", "graph", "positions", "scripts"],
        }
        for section, names in fields.items():
            same(list(mapping[section]), names, "every frozen wire field mapped, no competing field")

    def test_19_request_declaration_and_descriptor_metadata_negatives(self):
        clean = load(SUP / "EXPECTED/request.json")
        check_request_declaration(copy.deepcopy(clean))

        def filled(c):
            c["metadata_inputs"]["record_r02"] = "r02"

        def coordinated_filled(c):
            c["metadata_inputs"]["record_r02"] = "r02"
            c["options"]["inputs"]["record_r02"] = "r02"

        def required_default(c):
            c["field_declarations"]["workflow"]["default"] = "oracle306"

        def optional_without_default(c):
            del c["field_declarations"]["notify"]["default"]

        def null_invalid_as_absent(c):
            c["field_declarations"]["inputs"]["explicit_null"] = "same as absent"

        def missing_declaration(c):
            del c["field_declarations"]["notify"]

        def admission_option(c):
            c["field_names"] = sorted(c["field_names"] + ["admission"])

        def literal_type(c):
            c["literal_types"]["notify"] = "int"

        mutations = {
            "metadata_inputs_filled_default": filled,
            "coordinated_filled_default": coordinated_filled,
            "workspace_mismatch": lambda c: c["descriptor_metadata"].update(workspace_path="/synthetic/306/workspace"),
            "relative_workspace": lambda c: c["descriptor_metadata"].update(workspace_path="synthetic/316"),
            "uppercase_uuid": lambda c: c["descriptor_metadata"].update(execution_uuid="00000000-0000-4000-8000-00000000031A"),
            "logical_run_as_uuid": lambda c: c["descriptor_metadata"].update(logical_run_id=c["descriptor_metadata"]["execution_uuid"]),
            "invalid_candidate_name": lambda c: c["descriptor_metadata"].update(candidate_identity="oracle/316"),
            "other_mode": lambda c: c["descriptor_metadata"].update(mode="external-db"),
            "unlabelled": lambda c: c["descriptor_metadata"].pop("labelled"),
            "workflow_mismatch": lambda c: c["descriptor_metadata"].update(workflow_name="oracle316"),
            "required_with_default": required_default,
            "optional_without_default": optional_without_default,
            "null_semantics": null_invalid_as_absent,
            "missing_declaration": missing_declaration,
            "admission_option": admission_option,
            "literal_type": literal_type,
            "document_hash": lambda c: c["source"].update(document_sha256="0" * 64),
            "routes_blob": lambda c: c["source"]["files"]["temper_ai/api/routes.py"].update(git_blob="0" * 40),
            "claimed_committed": lambda c: c["source"].update(status="COMMITTED"),
            "runtime_claim": lambda c: c.update(runtime_status="PASS"),
            "defaults_overlap": lambda c: c["inputs_left_to_workflow_defaults"].append("record_id"),
        }
        for label, mutate in mutations.items():
            candidate = copy.deepcopy(clean)
            mutate(candidate)
            with self.subTest(defect=label), self.assertRaises(AssertionError):
                check_request_declaration(candidate)

    def test_18_v1_field_sets_native_is_inner_permitted_set(self):
        facts = load(SUP / "source-facts.json")
        sets = facts["wire_field_sets"]
        same(sets["workflow"], facts["workflow_fields"], "workflow field set = dataclass inventory")
        same(sets["node"], facts["node_fields"], "node field set = dataclass inventory")
        same(sets["native"], facts["native_permitted_keys"], "native = SINGLE_CALL_SETTINGS")
        same(len(sets["native"]), 24, "24 permitted inner keys")
        require(not set(sets["native"]) & set(facts["native_envelope_accepted_keys"]), "envelope keys are not native keys")
        require(set(facts["native_required_keys"]) < set(sets["native"]), "required keys inside permitted set")
        for position in expected_packet()["positions"]:
            present = set(position["agent_config"]["single_call"])
            require(present <= set(sets["native"]), "each present per-call set is a permitted subset")
            same(present, set(facts["native_literal_types"]), "present set keeps exact absence")
        clean = {"workflow": sets["workflow"], "node": sets["node"], "native": sets["native"],
                 "request": load(SUP / "EXPECTED/request.json")["field_names"]}
        check_field_sets(copy.deepcopy(clean))
        envelope = facts["native_envelope_accepted_keys"]
        for label, value in (("envelope", envelope),
                             ("flattened_union", sorted(set(envelope) | set(sets["native"]))),
                             ("present_only", sorted(facts["native_literal_types"])),
                             ("required_only", facts["native_required_keys"]),
                             ("unsorted", list(reversed(sets["native"]))),
                             ("tiny_contract_fixture", ["output_root", "slot"])):
            candidate = copy.deepcopy(clean)
            candidate["native"] = value
            with self.subTest(defect=label), self.assertRaises(AssertionError):
                check_field_sets(candidate)
        for key in ("workflow", "node"):
            candidate = copy.deepcopy(clean)
            candidate[key] = [n for n in candidate[key] if n != "_KNOWN_FIELDS"]
            with self.subTest(defect="metadata-" + key), self.assertRaises(AssertionError):
                check_field_sets(candidate)
        candidate = copy.deepcopy(clean)
        candidate["request"] = sorted(candidate["request"] + ["zz_invented_request_option"])
        with self.assertRaises(AssertionError):
            check_field_sets(candidate)
        candidate = {key: value for key, value in clean.items() if key != "request"}
        with self.assertRaises(AssertionError):
            check_field_sets(candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
