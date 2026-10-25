"""Independent handwritten synthetic T1 oracle; never a loader/codec expectation.

All effective defaults, inventories, factory names and values below are literals.
Only ordinary JSON encoding and hashlib assemble identities from those literals.
No test executes the script, opens the schematic native paths, or sends a model.
"""
import hashlib
import json
from copy import deepcopy

WORKFLOW_KEYS = sorted([
    "name", "description", "version", "nodes", "inputs", "outputs", "safety", "memory",
    "defaults", "on_failure", "notify", "starts_runs",
])
NODE_KEYS = sorted([
    "name", "type", "agent", "strategy", "strategy_config", "agents", "nodes", "ref",
    "depends_on", "condition", "loop_to", "max_loops", "loop_condition", "on_max_loops",
    "run_after_failure", "undoes", "on_failure", "required_files", "renamed_from",
    "timeout_seconds", "gate", "skip_policies", "input_map", "inputs", "outputs",
    "task_template", "system_prompt", "role", "model", "provider", "temperature", "max_tokens",
    "token_budget", "tools", "memory",
])
NATIVE_KEYS = sorted([
    "prompt_path", "prompt_sha256", "prompt_bytes", "output_root", "slot", "family", "route",
    "auth_mode", "max_tokens", "output_bound_mode", "deadline_s", "cost_cap_usd", "pricing_path",
    "pricing_sha256", "experiment_id", "binding_id", "source_sha256", "config_sha256", "packet_sha256",
    "token", "temperature", "thinking", "thinking_budget", "effort",
])
SOURCE = {
    # Deliberately synthetic sibling facts, never reported as installed source.
    "engine_commit": "1" * 40, "engine_tree": "2" * 40, "binding_abi": "candidate-admission/v1",
    "field_sets": {"workflow": sorted([*WORKFLOW_KEYS, "_KNOWN_FIELDS"]),
                   "node": sorted([*NODE_KEYS, "_KNOWN_FIELDS"]), "native": NATIVE_KEYS, "request": ["mode"]},
}
NATIVE = {
    "prompt_path": "/synthetic/metadata/input", "prompt_sha256": "0" * 64, "prompt_bytes": 0,
    "output_root": "/synthetic/metadata/output", "slot": "A1", "family": "A",
    "route": "anthropic-oauth-named-token", "auth_mode": "oauth", "max_tokens": 100,
    "output_bound_mode": "request_limit", "deadline_s": 900, "cost_cap_usd": 1,
    "pricing_path": "/synthetic/metadata/pricing", "pricing_sha256": "0" * 64,
    "experiment_id": "synthetic-only", "binding_id": "synthetic-only", "source_sha256": "0" * 64,
    "config_sha256": "0" * 64, "packet_sha256": "0" * 64, "token": "synthetic-name-not-secret",
}
SCRIPT = "printf '%s\\n' {{ label }}"
RAW = {
    ("agent", "caller"): {"agent": {"name": "caller", "type": "single_call", "provider": "anthropic",
                                   "model": "claude-opus-5-5", "single_call": NATIVE}},
    ("agent", "preparer"): {"agent": {"name": "preparer", "type": "script", "script_template": SCRIPT,
                                     "strict_undefined": True}},
    ("stage", "group"): {"stage": {"name": "group", "type": "stage", "nodes": [
        {"name": "prepare", "agent": "agents/preparer", "input_map": {"label": "input.label"}},
        {"name": "call", "agent": "agents/caller", "depends_on": ["prepare"]},
    ]}},
    ("workflow", "sample"): {"workflow": {"name": "sample", "nodes": [
        {"name": "group", "type": "stage", "ref": "stages/group"},
    ]}},
}
NODE_DEFAULTS = {
    "name": "unused", "type": "agent", "agent": None, "strategy": None, "strategy_config": {},
    "agents": None, "nodes": None, "ref": None, "depends_on": [], "condition": None,
    "loop_to": None, "max_loops": 1, "loop_condition": None, "on_max_loops": "silent",
    "run_after_failure": False, "undoes": None, "on_failure": None, "required_files": None,
    "renamed_from": None, "timeout_seconds": None, "gate": False, "skip_policies": None,
    "input_map": None, "inputs": None, "outputs": None, "task_template": None,
    "system_prompt": None, "role": None, "model": None, "provider": None, "temperature": None,
    "max_tokens": None, "token_budget": None, "tools": None, "memory": None, "_KNOWN_FIELDS": NODE_KEYS,
}


def text(value):
    # Fixtures use only exact floats (e.g. 0.5), never approximate binary64 0.1.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hashed(domain, value):
    return hashlib.sha256(b"temper-admission/v1\0" + domain.encode("ascii") + b"\0" + text(value).encode()).hexdigest()


def raw_record(kind, name, config, version="1.0"):
    return {"format": "candidate-raw-record/v1", "kind": kind, "name": name,
            "schema_version": version, "origin": {"kind": "db"}, "file_base64": None,
            "config_json": text(config)}


def expectation(record):
    identity = {k: record[k] for k in ("kind", "name", "schema_version", "origin", "config_json")}
    return {k: record[k] for k in ("kind", "name", "schema_version", "origin")} | {"raw_sha256": hashed("raw-record", identity)}


def literals():
    """Fresh independently specified raw and effective meanings (not normalized raw)."""
    raw = deepcopy(RAW)
    prep = deepcopy(NODE_DEFAULTS) | {"name": "prepare", "agent": "agents/preparer", "input_map": {"label": "input.label"}}
    call = deepcopy(NODE_DEFAULTS) | {"name": "call", "agent": "agents/caller", "depends_on": ["prepare"]}
    group = deepcopy(NODE_DEFAULTS) | {"name": "group", "type": "stage", "nodes": [prep, call]}
    workflow = {"name": "sample", "description": "", "version": "1.0", "nodes": [group],
                "inputs": None, "outputs": None, "safety": None, "memory": None, "defaults": None,
                "on_failure": None, "notify": None, "starts_runs": False, "_KNOWN_FIELDS": WORKFLOW_KEYS}
    script_cfg = {"name": "preparer", "type": "script", "script_template": SCRIPT, "strict_undefined": True,
                  "on_max_loops": "silent", "run_after_failure": False, "gate": False, "_KNOWN_FIELDS": NODE_KEYS}
    native_cfg = {"name": "caller", "type": "single_call", "provider": "anthropic", "model": "claude-opus-5-5",
                  "single_call": deepcopy(NATIVE)}
    graph = {"workflow_json": text(workflow), "nodes": [
        {"path": ["group"], "node_json": text(group), "factory": None},
        {"path": ["group", "prepare"], "node_json": text(prep), "factory": {
            "type": "script", "class_name": "temper_ai.agent.script_agent.ScriptAgent", "config_json": text(script_cfg)}},
        {"path": ["group", "call"], "node_json": text(call), "factory": {
            "type": "single_call", "class_name": "temper_ai.agent.single_call_agent.SingleCallAgent", "config_json": text(native_cfg)}},
    ]}
    records = [raw_record(*k, v) for k, v in sorted(raw.items())]
    descriptor = {
        "format": "candidate-admission-descriptor/v1", "profile": "context-profile-admission/v1",
        "mode": "external-db-fresh", "candidate_identity": "synthetic-candidate", "logical_run_id": "synthetic-only",
        "execution_uuid": "00000000-0000-0000-0000-000000000001", "workflow_name": "sample",
        "workspace_path": "/synthetic/metadata", "metadata_inputs_json": text({"label": "synthetic"}),
        "request_options_json": text({"mode": "external-db-fresh"}), "source": deepcopy(SOURCE),
        "records": [expectation(r) for r in records], "graph": graph,
        "positions": [{"position_id": "position-1", "node_path": ["group", "call"],
                       "preparation_path": ["group", "prepare"], "record_id": "synthetic-record",
                       "variant_id": "synthetic-variant", "call_id": "synthetic-call", "slot": "A1",
                       "agent_config_json": text(native_cfg), "root_policy": None}],
        "scripts": [{"node_path": ["group", "prepare"], "template_utf8": SCRIPT,
                     "template_sha256": hashlib.sha256(SCRIPT.encode()).hexdigest(),
                     "variables_json": text({"label": "synthetic", "workspace_path": "/synthetic/metadata",
                                             "run_id": "00000000-0000-0000-0000-000000000001"})}],
    }
    return raw, records, descriptor


def typed_case():
    # The production codec ONLY parses already fixed answers. It constructs no
    # expected semantic values; literal source/graph expectations above own them.
    from pathlib import Path

    from temper_ai.config.admission_contract import (
        ContractCodec,
        DescriptorAuthority,
        FrozenJSON,
    )

    raw, records, d = literals()
    codec = ContractCodec((Path(__file__).parents[2] / "docs/schemas/candidate-admission-v1.schema.json").read_bytes())
    authority = DescriptorAuthority(hashed("descriptor", d), hashed("source", d["source"]), "synthetic-caller", "synthetic-receipt")
    descriptor = codec.descriptor(text(d).encode(), authority)
    closure = codec.closure(descriptor, tuple(codec.raw_record(text(r).encode()) for r in records))
    return raw, codec, authority, descriptor, closure, FrozenJSON(text(SOURCE).encode())
