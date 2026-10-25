"""Packet consistency, NOT engine admission, custody or model execution.

Run directly with stdlib unittest to avoid importing engine conftests. The only
source inspection is AST field-name inventory; no production module is imported.
INPUT is expanded separately from literal EXPECTED tables. All mutations affect
INPUT copies. No listed synthetic absolute path is opened or script rendered.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "configs/architecture/stages/context_profile/admission_oracles"
DATA_FILES = {
    "provenance.json", "octets.json", "inputs.json", "expected-raw.json",
    "expected-graph.json", "expected-positions.json", "cases.json", "manifest.json",
}
ORIGINAL_CASES_SHA256 = "ff88dc34fb688aba281f562c0485ea983a3e9dbb2b0910a1f91188bc057f571a"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def no_constant(_value):
    raise ValueError("NONFINITE_NUMBER")


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("NONFINITE_NUMBER")
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=no_constant, parse_float=finite_float)


def canonical(value):
    # Integrity/type-sensitive equality only, never semantic normalization.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def decode_table(columns, rows):
    if len(columns) != len(set(columns)):
        raise ValueError("DUPLICATE_COLUMN")
    return [dict(zip(columns, row, strict=True)) for row in rows]


def input_native(data):
    result = {}
    for row in decode_table(data["position_columns"], data["positions"]):
        fixed = copy.deepcopy(data["native_constants"])
        for key in ("prompt_path", "output_root", "slot", "binding_id"):
            fixed[key] = row[key]
        if row["node_path"] in result:
            raise ValueError("DUPLICATE_NODE")
        result[row["node_path"]] = {**data["native_envelope"], "single_call": fixed}
    return result


def expected_native(data):
    # Only decode literal cells. No INPUT or source object is accepted here.
    result = {}
    for row in decode_table(data["columns"], data["rows"]):
        row.pop("position_id")
        node = row.pop("node_path")
        row.pop("predecessor")
        if node in result:
            raise ValueError("DUPLICATE_NODE")
        result[node] = {**data["native_envelope"], "single_call": row}
    return result


def at(value, path):
    for key in path:
        value = value[key]
    return value


def mutate(baseline, path, value):
    """Fixture operations only. Does not decide admission or run a consumer."""
    result = copy.deepcopy(baseline)
    op = value.get("op") if isinstance(value, dict) else None
    if op == "keep":
        return result
    if op == "swap":
        left, right = value["left"], value["right"]
        a, b = at(result, left[:-1]), at(result, right[:-1])
        a[left[-1]], b[right[-1]] = b[right[-1]], a[left[-1]]
    elif op == "move_record":
        result[value["to"]] = result.pop(value["from"])
    elif op == "family_B":
        native = at(result, path)
        native["provider"], native["model"] = value["provider"], value["model"]
        native["single_call"].pop("token")
        for key in ("family", "slot", "route", "auth_mode", "output_bound_mode",
                    "pricing_path", "pricing_sha256"):
            native["single_call"][key] = value[key]
    elif op == "merge":
        at(result, path).update({k: v for k, v in value.items() if k != "op"})
    elif op == "append":
        at(result, path).append(value["value"])
    elif op == "remove":
        del at(result, path[:-1])[path[-1]]
    elif op is None:
        at(result, path[:-1])[path[-1]] = copy.deepcopy(value)
    else:
        raise ValueError("UNKNOWN_FIXTURE_OPERATION")
    return result


class AdmissionOraclePacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {name: strict_json((PACKET / name).read_text(encoding="utf-8"))
                     for name in DATA_FILES}
        cls.provenance = cls.files["provenance.json"]
        cls.inventory = cls.provenance["field_inventories"]
        cls.inputs = cls.files["inputs.json"]["INPUT"]
        cls.graph = cls.files["expected-graph.json"]["EXPECTED"]
        cls.positions = cls.files["expected-positions.json"]["EXPECTED"]
        cls.cases = cls.files["cases.json"]["cases"]
        cls.profiles = cls.files["cases.json"]["counter_profiles"]
        cls.actual_native = input_native(cls.inputs)
        cls.literal_native = expected_native(cls.positions)
        cls.actual_raw = copy.deepcopy(cls.inputs["raw_closure"])
        cls.actual_raw.update({record: cls.actual_native[node] for record, node in
                               cls.inputs["raw_native_record_positions"].items()})
        raw = cls.files["expected-raw.json"]["EXPECTED"]
        cls.literal_raw = copy.deepcopy(raw["records"])
        cls.literal_raw.update({record: cls.literal_native[node] for record, node in
                                raw["native_record_positions"].items()})

    def test_strict_json_rejects_duplicate_nonfinite_and_trailing_data(self):
        for text in ('{"x":1,"x":2}', '{"x":{"n":0,"n":1}}', 'NaN',
                     'Infinity', '-Infinity', '1e999', '{} {}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)
        self.assertNotEqual(canonical({"n": True}), canonical({"n": 1}))
        self.assertNotEqual(canonical({"n": 1}), canonical({"n": 1.0}))
        with self.assertRaises(ValueError):
            decode_table(["x", "x"], [[1, 2]])
        with self.assertRaises(ValueError):
            decode_table(["x"], [[1, 2]])

    def test_closed_packet_sections_and_frozen_file_hashes(self):
        self.assertEqual({p.name for p in PACKET.glob("*.json")}, DATA_FILES)
        shapes = {
            "inputs.json": {"format", "INPUT"},
            "expected-raw.json": {"format", "EXPECTED"},
            "expected-graph.json": {"format", "EXPECTED"},
            "expected-positions.json": {"format", "encoding", "EXPECTED"},
            "octets.json": {"format", "provenance", "INPUT", "EXPECTED"},
            "cases.json": {"format", "runtime_status", "mutation_encoding", "counter_columns", "counter_profiles", "cases"},
            "manifest.json": {"format", "files", "canonical_raw_records", "script_template_sha256", "canonical_expected_native_maps_sha256", "canonical_expected_graph_sha256"},
            "provenance.json": {"format", "task", "accountable_lead", "synthetic", "runnable", "runtime_status", "authority", "source", "independence", "paper_placeholders", "custody", "field_inventories", "not_proved", "standing_status"},
        }
        for name, keys in shapes.items():
            self.assertEqual(set(self.files[name]), keys, name)
        formats = {
            "provenance.json": "fixture", "inputs.json": "input", "octets.json": "octets",
            "expected-raw.json": "raw", "expected-graph.json": "graph",
            "expected-positions.json": "literal-table", "cases.json": "scenarios", "manifest.json": "manifest",
        }
        for name, kind in formats.items():
            self.assertEqual(self.files[name]["format"], f"architecture-admission-oracle-{kind}/1")
        self.assertEqual(set(self.inputs), {
            "run_id", "workspace_path", "request_inputs", "schema_version", "native_envelope",
            "native_constants", "position_columns", "positions", "raw_closure",
            "raw_native_record_positions", "prohibited_presence_examples", "runtime_scenario",
        })
        self.assertEqual(set(self.graph), {
            "raw_record_ids", "workflow", "nodes", "native_nodes", "script_agents", "class_metadata",
            "script_metadata", "record_predecessors", "receipt_limits", "runtime_status",
        })
        self.assertEqual(set(self.positions), {"native_envelope", "columns", "rows"})
        self.assertEqual(set(self.files["expected-raw.json"]["EXPECTED"]),
                         {"schema_version", "native_record_positions", "records"})
        self.assertEqual(set(self.positions["columns"]),
                         {"position_id", "node_path", "predecessor", *self.inventory["single_call"]})
        manifest = self.files["manifest.json"]
        self.assertEqual(set(manifest["files"]), (DATA_FILES - {"manifest.json"}) | {"README.md"})
        for name, expected in manifest["files"].items():
            self.assertEqual(digest((PACKET / name).read_bytes()), expected, name)
        self.assertEqual(manifest["canonical_raw_records"],
                         {k: digest(canonical(v)) for k, v in self.literal_raw.items()})
        self.assertEqual(manifest["canonical_expected_native_maps_sha256"], digest(canonical(self.literal_native)))
        self.assertEqual(manifest["canonical_expected_graph_sha256"], digest(canonical(self.graph)))

    def test_original_36_expectations_are_not_weakened(self):
        self.assertEqual([c["id"] for c in self.cases], [f"V{i:02}" for i in range(1, 37)])
        originals = [{"id": c["id"], "original": c["original"]} for c in self.cases]
        self.assertEqual(digest(canonical(originals)), ORIGINAL_CASES_SHA256)
        self.assertEqual(self.provenance["source"]["original_cases_canonical_sha256"], ORIGINAL_CASES_SHA256)
        for case in self.cases:
            self.assertEqual(set(case), {"id", "original", "INPUT", "EXPECTED"})
            self.assertEqual(set(case["original"]), {"change", "first_boundary", "expected"})
            self.assertEqual(case["EXPECTED"]["runtime_status"], "UNEXECUTED")
            self.assertTrue(case["INPUT"]["variants"])
            self.assertIn(case["EXPECTED"]["profile"], self.profiles)
            self.assertIn(case["original"]["first_boundary"], {f"B{i}" for i in range(7)})
            if "variant_outcomes" in case["EXPECTED"]:
                self.assertEqual(set(case["EXPECTED"]["variant_outcomes"]),
                                 {v[0] for v in case["INPUT"]["variants"]})

    def test_complete_policy_field_inventory_without_engine_import(self):
        tree = ast.parse((ROOT / "temper_ai/stage/models.py").read_text(encoding="utf-8"))
        for name, key in (("WorkflowConfig", "workflow"), ("NodeConfig", "node")):
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
            fields = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)
                      and isinstance(n.target, ast.Name) and n.target.id != "_KNOWN_FIELDS"}
            self.assertEqual(fields, set(self.inventory[key]))
        self.assertEqual(set(self.graph["workflow"]), set(self.inventory["workflow"]))
        for path, node in self.graph["nodes"].items():
            self.assertEqual(set(node), set(self.inventory["node"]), path)
            self.assertIs(type(node["max_loops"]), int)
            self.assertIs(type(node["gate"]), bool)
            self.assertIs(type(node["run_after_failure"]), bool)
        metadata = self.graph["class_metadata"]
        self.assertEqual(metadata["name"], "_KNOWN_FIELDS")
        self.assertEqual(metadata["type"], "frozenset")
        self.assertEqual(set(metadata["members"]), set(self.inventory["node"]))

    def test_complete_native_field_inventory_without_engine_import(self):
        tree = ast.parse((ROOT / "temper_ai/agent/single_call_agent.py").read_text(encoding="utf-8"))
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if isinstance(node.targets[0], ast.Name) and node.targets[0].id in {
                    "SINGLE_CALL_REQUIRED", "SINGLE_CALL_AGENT_SETTINGS",
                }:
                    constants[node.targets[0].id] = set(ast.literal_eval(node.value.args[0]))
        self.assertEqual(set(self.inventory["single_call"]), constants["SINGLE_CALL_REQUIRED"] | {"token"})
        self.assertEqual(set(self.inventory["native_envelope"]) | {"single_call"}, constants["SINGLE_CALL_AGENT_SETTINGS"])
        for config in self.literal_native.values():
            self.assertEqual(set(config), constants["SINGLE_CALL_AGENT_SETTINGS"])
            fixed = config["single_call"]
            self.assertEqual(set(fixed), set(self.inventory["single_call"]))
            for key in ("max_tokens", "deadline_s", "prompt_bytes"):
                self.assertIs(type(fixed[key]), int)
            self.assertEqual(fixed["max_tokens"], 8192)
            self.assertEqual(fixed["deadline_s"], 900)
            self.assertEqual(fixed["token"], "CLAUDE_CODE_OAUTH_TOKEN")

    def test_exact_42_full_positions_not_global_slot_uniqueness(self):
        rows = decode_table(self.positions["columns"], self.positions["rows"])
        self.assertEqual(len(rows), 42)
        self.assertEqual({r["position_id"] for r in rows},
                         {f"r{n:02}/{slot}" for n in range(1, 15) for slot in ("A1", "A2", "A3")})
        full = {(self.inputs["run_id"], r["node_path"], r["position_id"], r["output_root"], r["slot"]) for r in rows}
        self.assertEqual(len(full), 42)
        self.assertEqual(len({(r["output_root"], r["slot"]) for r in rows}), 42)
        self.assertEqual(len({r["binding_id"] for r in rows}), 42)
        self.assertEqual(Counter(r["slot"] for r in rows), {"A1": 14, "A2": 14, "A3": 14})
        for row in rows:
            record, slot = row["position_id"].split("/")
            self.assertEqual(row["node_path"], f"{record}.call_{slot}")
            self.assertEqual(row["output_root"], f"/synthetic/306/{record}/{slot}/out")
            predecessor = {"A1": "prepare", "A2": "account_A1", "A3": "account_A2"}[slot]
            self.assertEqual(row["predecessor"], f"{record}.{predecessor}")
        self.assertEqual(set(self.graph["record_predecessors"]), {f"r{n:02}" for n in range(1, 15)})
        for n in range(1, 15):
            self.assertEqual(self.graph["record_predecessors"][f"r{n:02}"], None if n == 1 else f"r{n - 1:02}.receipt")

    def test_input_maps_equal_separately_literal_expected_maps(self):
        self.assertEqual(canonical(self.actual_native), canonical(self.literal_native))
        self.assertEqual(canonical(self.actual_raw), canonical(self.literal_raw))
        self.assertEqual(set(self.literal_raw), set(self.graph["raw_record_ids"]))
        self.assertEqual(len(self.literal_raw), 8)
        self.assertEqual(self.inputs["schema_version"], self.files["expected-raw.json"]["EXPECTED"]["schema_version"])
        input_rows = decode_table(self.inputs["position_columns"], self.inputs["positions"])
        expected_rows = decode_table(self.positions["columns"], self.positions["rows"])
        self.assertEqual({r["node_path"]: r["predecessor"] for r in input_rows},
                         {r["node_path"]: r["predecessor"] for r in expected_rows})

    def test_clean_recursive_graph_and_serial_ready_accounting_edges(self):
        nodes = self.graph["nodes"]
        order = ["r01.prepare", "r01.call_A1", "r01.account_A1", "r01.call_A2",
                 "r01.account_A2", "r01.call_A3", "r01.account_A3", "r01.receipt"]
        self.assertEqual(self.graph["workflow"]["nodes"], ["r01"])
        self.assertEqual(set(nodes), {"r01", *order})
        self.assertEqual(nodes["r01"]["nodes"], order)
        raw_nodes = self.literal_raw["stage:oracle306_r01"]["nodes"]
        self.assertEqual(len(raw_nodes), len(order))
        for index, (path, raw) in enumerate(zip(order, raw_nodes, strict=True)):
            expected = nodes[path]
            self.assertEqual(expected["name"], path.split(".")[-1])
            self.assertEqual(expected["depends_on"], [] if index == 0 else [order[index - 1].split(".")[-1]])
            self.assertEqual(expected["run_after_failure"], path == "r01.receipt")
            self.assertIsNone(expected["nodes"])
            for key, value in raw.items():
                self.assertEqual(canonical(value), canonical(expected[key]), f"{path}:{key}")
        for key, value in self.literal_raw["workflow:oracle306"].items():
            if key != "nodes":
                self.assertEqual(canonical(value), canonical(self.graph["workflow"][key]), key)
        self.assertEqual(set(self.graph["native_nodes"]), {"r01.call_A1", "r01.call_A2", "r01.call_A3"})
        self.assertEqual(set(self.graph["script_agents"]), set(order) - set(self.graph["native_nodes"]))

    def test_script_templates_metadata_and_hashes_are_closed(self):
        hashes = self.files["manifest.json"]["script_template_sha256"]
        self.assertEqual(set(hashes), set(self.graph["script_agents"]))
        for node, expected in self.graph["script_agents"].items():
            ref = self.graph["nodes"][node]["agent"].removeprefix("agents/")
            raw = self.literal_raw[f"agent:{ref}"]
            for key, value in raw.items():
                self.assertEqual(expected[key], value)
            self.assertEqual(set(expected) - set(raw), {"on_max_loops", "run_after_failure", "gate"})
            self.assertEqual(expected["script_template"].count("{{ record_id }}"), 1)
            self.assertTrue(expected["strict_undefined"])
            self.assertEqual(hashes[node], digest(expected["script_template"].encode("utf-8")))
        self.assertEqual(self.graph["script_metadata"]["values"], {"record_id": "r01"})
        self.assertEqual(self.graph["script_metadata"]["private_sources"], [])

    def test_synthetic_octets_and_noncyclic_hash_bindings(self):
        octets = self.files["octets.json"]
        self.assertEqual(set(octets["INPUT"]), set(octets["EXPECTED"]))
        computed = {}
        for name, value in octets["INPUT"].items():
            self.assertIn(set(value), ({"hex"}, {"utf8"}))
            blob = bytes.fromhex(value["hex"]) if "hex" in value else value["utf8"].encode("utf-8")
            computed[name] = digest(blob)
            self.assertEqual(octets["EXPECTED"][name], {"bytes": len(blob), "sha256": digest(blob)})
        self.assertEqual(len(set(computed.values())), len(computed))
        for config in self.literal_native.values():
            for name in ("prompt", "pricing", "source", "config", "packet"):
                self.assertEqual(config["single_call"][f"{name}_sha256"], computed[name])
            self.assertEqual(config["single_call"]["prompt_bytes"], octets["EXPECTED"]["prompt"]["bytes"])
        for pricing_name, model in (("pricing", "claude-opus-5-5"), ("pricing_B", "gpt-6.1-sol")):
            pricing = strict_json(octets["INPUT"][pricing_name]["utf8"])
            self.assertEqual(pricing["currency"], "USD")
            self.assertEqual(pricing["models"][model]["input_usd_per_million"], 0)
            self.assertEqual(pricing["models"][model]["output_usd_per_million"], 0)
        placeholders = self.provenance["paper_placeholders"]
        self.assertEqual(placeholders["classification"], "PAPER_LABEL_NOT_COMPUTED_HASH")
        self.assertNotIn(placeholders["prompt_r01"], computed.values())
        self.assertNotIn(placeholders["prompt_r02"], computed.values())

    def test_every_mutation_is_materializable_and_differs_from_literal_oracle(self):
        ready = self.cases[25]["EXPECTED"]["ready"]
        baselines = {"native": self.actual_native, "raw": self.actual_raw, "runtime": self.inputs["runtime_scenario"]}
        oracles = {"native": self.literal_native, "raw": self.literal_raw, "runtime": ready}
        seen = set()
        for case in self.cases:
            for variant in case["INPUT"]["variants"]:
                self.assertIn(len(variant), (4, 5))
                label, target, path, value = variant[:4]
                identity = f"{case['id']}.{label}"
                with self.subTest(variant=identity):
                    self.assertNotIn(identity, seen)
                    seen.add(identity)
                    self.assertIn(target, baselines)
                    before = canonical(baselines[target])
                    changed = mutate(baselines[target], path, value)
                    self.assertEqual(canonical(baselines[target]), before)
                    if isinstance(value, dict) and value.get("op") == "keep":
                        self.assertEqual(canonical(changed), canonical(oracles[target]))
                    else:
                        self.assertNotEqual(canonical(changed), canonical(oracles[target]))
                    if len(variant) == 5:
                        self.assertIn(variant[4], self.profiles)
        self.assertGreater(len(seen), 100)

    def test_wrong_valid_slot_and_whole_map_swap_are_not_syntax_or_bag_checks(self):
        variant = self.cases[2]["INPUT"]["variants"][0]
        changed = mutate(self.actual_native, variant[2], variant[3])
        self.assertIn(changed["r01.call_A1"]["single_call"]["slot"], {"A1", "A2", "A3"})
        self.assertNotEqual(canonical(changed), canonical(self.literal_native))
        variant = self.cases[3]["INPUT"]["variants"][0]
        swapped = mutate(self.actual_native, variant[2], variant[3])
        self.assertEqual(sorted(map(canonical, swapped.values())), sorted(map(canonical, self.literal_native.values())))
        self.assertNotEqual(canonical(swapped), canonical(self.literal_native))
        variant = self.cases[4]["INPUT"]["variants"][1]
        family_b = mutate(self.actual_native, variant[2], variant[3])["r01.call_A1"]
        self.assertEqual(family_b["provider"], "openai")
        self.assertEqual(family_b["single_call"]["family"], "B")
        self.assertNotIn("token", family_b["single_call"])
        self.assertEqual(family_b["single_call"]["pricing_sha256"], self.files["octets.json"]["EXPECTED"]["pricing_B"]["sha256"])

    def test_phase_counter_and_consumed_claim_predictions_are_explicit(self):
        columns = self.files["cases.json"]["counter_columns"]
        self.assertEqual(columns, self.inventory["counters"])
        for name, profile in self.profiles.items():
            self.assertEqual(set(profile), {"scope", "bounds", "claim_before", "claim_after"})
            self.assertTrue(profile["scope"])
            counters = dict(zip(columns, profile["bounds"], strict=True))
            for low, high in counters.values():
                self.assertIs(type(low), int)
                self.assertIs(type(high), int)
                self.assertLessEqual(0, low)
                self.assertLessEqual(low, high)
            for key in ("ordinary_get", "guard_config", "environment_substitution", "graph_template_expansion"):
                self.assertEqual(counters[key], [0, 0])
            if name.endswith("REFUSE") or name == "B5_CONSUMED":
                for key in ("script_render", "script_process", "factory", "claim_create", "private_read", "provider_send"):
                    self.assertEqual(counters[key], [0, 0])
                self.assertEqual(profile["claim_after"], profile["claim_before"])
            if profile["claim_before"] == "CONSUMED":
                self.assertEqual(profile["claim_after"], "CONSUMED")
        for case in self.cases:
            for name in case["EXPECTED"].get("late_profiles", []) + case["EXPECTED"].get("later_profiles", []):
                self.assertIn(name, self.profiles)
        for name in ("AUTH_B6", "PRICE_B6", "RECEIPT_B6"):
            self.assertEqual(self.profiles[name]["claim_after"], "CONSUMED")
        self.assertFalse(self.cases[27]["EXPECTED"]["real_resume_authorized"])
        self.assertFalse(self.cases[28]["EXPECTED"]["real_resume_authorized"])

    def test_alias_independence_is_only_a_packet_property(self):
        # Demonstrate the fixture reader owns independent JSON parses; not an
        # assertion that a production store or factory already does so.
        frozen = canonical(self.actual_native)
        first, second = strict_json(frozen), strict_json(frozen)
        first["r01.call_A1"]["single_call"]["slot"] = "A2"
        self.assertEqual(canonical(second), frozen)
        self.assertEqual(canonical(self.literal_native), frozen)
        self.assertNotEqual(canonical(first), frozen)

    def test_diagnostic_expected_record_is_metadata_only(self):
        case = self.cases[34]
        record = case["EXPECTED"]["export"]
        self.assertEqual(set(record), set(case["EXPECTED"]["allowed_fields"]))
        self.assertEqual(record["code"], "ADMISSION_REFUSED")
        self.assertEqual(record["position_id"], "r01/A1")
        self.assertNotIn(case["INPUT"]["metadata_canary"].encode(), canonical(record))
        # No caught engine exception, script output or model request is involved.
        self.assertEqual(case["EXPECTED"]["runtime_status"], "UNEXECUTED")

    def test_unknown_custody_never_becomes_runnable(self):
        p = self.provenance
        self.assertTrue(p["synthetic"])
        self.assertFalse(p["runnable"])
        self.assertEqual(p["runtime_status"], "UNEXECUTED")
        custody = p["custody"]
        self.assertEqual(custody["status"], "UNKNOWN")
        self.assertFalse(custody["runnable"])
        for field in ("custodian", "worker_identity", "euid", "mount", "durable_parent", "retention", "live_receipt"):
            self.assertIsNone(custody[field])
        self.assertFalse(self.cases[25]["EXPECTED"]["live_runnable"])
        ready = self.cases[25]["EXPECTED"]["ready"]
        self.assertEqual(ready["kind"], "SYNTHETIC_ONLY")
        self.assertTrue(ready["preparation_complete"])
        self.assertTrue(ready["opened_root_matches_readiness"])
        self.assertEqual(ready["node_path"], "r01.call_A1")
        self.assertEqual(ready["synthetic_custodian"], "fixture-only-custodian-306")
        self.assertEqual(ready["synthetic_mount"], "fixture-only-mount-306")
        self.assertIsNone(ready["live_custody"])
        self.assertEqual(p["standing_status"], {"292": "PARTIAL", "293_sends": "0/42", "binding": "NOT_MET"})

    def test_test_module_has_only_stdlib_imports_and_no_external_io(self):
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {"__future__", "ast", "copy", "hashlib", "json", "math", "unittest", "collections", "pathlib"})
        forbidden = {"getenv", "environ", "exec", "eval", "compile", "__import__", "write_text", "write_bytes", "open", "socket", "connect", "urlopen"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                self.assertNotIn(name, forbidden)


if __name__ == "__main__":
    unittest.main()
