"""The context-profile candidate's dormant single_call config, through the real loader (#292).

Model-free and offline. The packet inputs are the same synthetic toy as
test_context_profile_candidate.py: no answer key, label, plant or held-out material is
opened, and no model-bound text is printed. Every load runs inside the forbidden-operation
window of tests/test_stage/test_single_call_loader.py (no provider, credential, network,
file or environment access); mappings are compared after the window, because pytest's
assertion explanation itself reads the environment. The preparer runs inside a narrower
window that refuses network, subprocess and environment reads.
"""
from __future__ import annotations

import builtins
import importlib.util
import io
import os
import re
import socket
import subprocess
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

import temper_ai.agent as agents
from temper_ai.agent import single_call_agent as single_call
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.config.importer import config_files, parse_yaml
from temper_ai.llm import providers, token_pool
from temper_ai.llm.providers import anthropic, factory, openai
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage import agent_node, dispatch_validation
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import ValidationError
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.stage_node import StageNode

# The real loader imports the dispatch validator lazily: import it before the window.
assert dispatch_validation.validate_dispatch_block

REPO = Path(__file__).resolve().parents[2]
AGENT_YAML = REPO / "configs/architecture/agents/context_profile_candidate.yaml"
STAGE_YAML = REPO / "configs/architecture/stages/context_profile_candidate.yaml"
CANDIDATE = REPO / "configs/architecture/stages/context_profile/CANDIDATE.md"


def _module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = _module(REPO / "configs/architecture/bin/context_profile_candidate_prepare.py")
SCHEMA = (REPO / p.STAGE / "contract.v2.schema.json").read_bytes()
# What the server's startup import stores for the two checked-in files (temper_ai/config/importer.py).
AGENT_PARSED = parse_yaml(AGENT_YAML)
STAGE_PARSED = parse_yaml(STAGE_YAML)

NAME = "context_profile_candidate"
# The run gates' variable NAME (Security rm-f321865e, Temper rm-1b43ccf4); never a value.
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
WORKFLOW = "offline-context-profile-route"  # Test-only: no checked-in workflow references the stage.
INVARIANTS = {"family": "A", "route": "anthropic-oauth-named-token", "auth_mode": "oauth", "max_tokens": 8192,
              "output_bound_mode": "request_limit", "deadline_s": 900}
PER_CALL = ("prompt_path", "prompt_sha256", "prompt_bytes", "output_root", "slot", "cost_cap_usd", "pricing_path",
            "pricing_sha256", "experiment_id", "binding_id", "source_sha256", "config_sha256", "packet_sha256")
BASE = {"name": NAME, "type": "single_call", "provider": "anthropic", "model": "claude-opus-5-5",
        "single_call": {**dict.fromkeys(PER_CALL), **INVARIANTS, "token": TOKEN_NAME}}
CLOSED = "Node 'context_profile_candidate': single_call requires a closed fixed-input mapping"
UNSUPPORTED = "Node 'context_profile_candidate': single_call has missing or unsupported fixed inputs"
EXTRA = {"tools": ["offline-tool"], "memory": {"enabled": True},
         "fallback": [{"provider": "openai", "model": "placeholder-fallback-model"}]}

OFFLINE = [
    (single_call.SingleCallAgent, "run"),
    (single_call._Attempt, "__init__"),
    (single_call._Attempt, "claim_slot"),
    (single_call, "_read_bound"),
    (single_call, "_open_directory"),
    (single_call, "_private_root"),
    (single_call, "_new_file"),
    (single_call, "_write_once"),
    (ExecutionContext, "__init__"),
    (ExecutionContext, "get_llm"),
    (ExecutionContext, "resolve_provider"),
    (agents, "create_agent"),
    (agent_node, "create_agent"),
    (AgentNode, "run"),
    (StageNode, "run"),
    (factory, "create_provider"),
    (providers, "create_provider"),
    (anthropic, "resolve_credential"),
    (anthropic, "named_tokens_from_env"),
    (anthropic.AnthropicLLM, "check_token"),
    (anthropic.AnthropicLLM, "_named_token"),
    (token_pool, "named_tokens_from_env"),
    (token_pool, "tokens_from_env"),
    (token_pool.TokenPool, "__init__"),
    (openai, "resolve_credential"),
    (anthropic.AnthropicLLM, "__init__"),
    (openai.OpenAILLM, "__init__"),
    (anthropic.AnthropicLLM, "complete"),
    (openai.OpenAILLM, "complete"),
    (single_call.ss, "new_http_client"),
    (httpx.Client, "__init__"),
    (httpx.AsyncClient, "__init__"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
    (socket, "create_connection"),
    (subprocess, "Popen"),
    (builtins, "open"),
    (io, "open"),
    (os, "open"),
    (os, "getenv"),
    (os.environ, "get"),
    (type(os.environ), "__getitem__"),
    (type(os.environ), "__contains__"),
    (os, "mkdir"),
    (os, "stat"),
    (Path, "open"),
    *[(cls, attr) for cls in (agents.LLMAgent, agents.ScriptAgent, agents.JevAgent)
      for attr in ("__init__", "validate_config")],
]
# The preparer reads and writes its own files, so its window refuses only these.
QUIET = [
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
    (socket, "create_connection"),
    (subprocess, "Popen"),
    (httpx.Client, "__init__"),
    (httpx.AsyncClient, "__init__"),
    (os, "getenv"),
    (os.environ, "get"),
    (type(os.environ), "__getitem__"),
    (type(os.environ), "__contains__"),
]


def _window(monkeypatch, targets):
    @contextmanager
    def scope():
        # Counts catch even a forbidden operation whose exception was swallowed.
        calls = {}
        with monkeypatch.context() as guard:
            for index, (owner, attr) in enumerate(targets):
                label = f"{index}:{getattr(owner, '__name__', type(owner).__name__)}.{attr}"
                calls[label] = Mock(side_effect=AssertionError(f"forbidden offline operation: {label}"))
                guard.setattr(owner, attr, calls[label])
            yield
        assert {key: value.call_count for key, value in calls.items()} == dict.fromkeys(calls, 0)

    return scope


@pytest.fixture
def offline(monkeypatch):
    return _window(monkeypatch, OFFLINE)


@pytest.fixture
def quiet(monkeypatch):
    return _window(monkeypatch, QUIET)


class _Store:
    """In-memory ConfigStore.get (temper_ai/config/store.py:28-62): wrapped documents as the
    importer stores them, returned through the store's own read-time substitution."""

    def __init__(self, agent=None):
        self.docs = {
            (WORKFLOW, "workflow"): {"workflow": {
                "name": WORKFLOW, "defaults": {},
                "nodes": [{"name": "context_profile", "type": "stage", "ref": "stages/context_profile_candidate"}]}},
            (NAME, "stage"): deepcopy(STAGE_PARSED["config"]),
            (NAME, "agent"): deepcopy(AGENT_PARSED["config"] if agent is None else agent),
        }
        self.lookups = []

    def get(self, name, config_type):
        self.lookups.append((name, config_type))
        return substitute_env_vars(deepcopy(self.docs[(name, config_type)]))


def _changed(place, key, value):
    store = _Store()
    if place == "agent":
        store.docs[(NAME, "agent")]["agent"][key] = value
    elif place == "fixed":
        store.docs[(NAME, "agent")]["agent"]["single_call"][key] = value
    elif place == "node":
        store.docs[(NAME, "stage")]["stage"]["nodes"][0][key] = value
    else:
        store.docs[(WORKFLOW, "workflow")]["workflow"]["defaults"][key] = value
    return store


def _leaf(nodes, config, store):
    assert config.name == WORKFLOW
    assert len(nodes) == 1 and isinstance(nodes[0], StageNode) and nodes[0].name == "context_profile"
    assert len(nodes[0].child_nodes) == 1
    leaf = nodes[0].child_nodes[0]
    assert isinstance(leaf, AgentNode) and leaf.name == NAME and leaf.config.agent == NAME
    assert store.lookups == [(WORKFLOW, "workflow"), (NAME, "stage"), (NAME, "agent")]
    return leaf


def _node_defaults(leaf):
    assert leaf.config.on_max_loops == "silent"
    assert leaf.config.run_after_failure is False
    assert leaf.config.gate is False
    assert leaf.config.timeout_seconds is None


def _store(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def _description(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": p.sha(data)}


def _sandbox(tmp_path, monkeypatch, repetition):
    """test_context_profile_candidate.py's synthetic packet inputs, for one repetition."""
    repo = tmp_path / "synthetic-checkout"
    root = tmp_path / "packets"
    root.mkdir(mode=0o700)
    engine_root = tmp_path / "synthetic-engine-root"
    engine_root.mkdir(mode=0o700)
    schema = _store(repo / p.STAGE / "contract.v2.schema.json", SCHEMA)
    prompt = _store(repo / p.STAGE / "PROMPT-CANDIDATE.md", b"Synthetic instructions; no examples or provider framing.\n")
    brief = _store(repo / p.KNOWN / p.CASES[0] / "brief.md", b"The archive catalogs manuscripts.\n")
    route = _store(tmp_path / "route.json", p.json_bytes({
        "format": "context-profile-candidate-route/v1", "status": "RESOLVED", "agent_type": "single_call",
        "provider": "anthropic", "model": "claude-opus-5-5", "route": "anthropic-oauth-named-token",
        "auth_mode": "oauth", "family": "A", "output_bound_mode": "request_limit",
        "max_tokens": 8192, "deadline_s": 900, "framing_bytes": None, "framing_evidence_sha256": None,
        "route_evidence_sha256": p.sha(b"synthetic route evidence"),
        "request_limit_evidence_sha256": p.sha(b"synthetic request limit evidence"),
        "request_limit_evidence": "https://example.invalid/request-limits"}))
    pricing = _store(tmp_path / "pricing.json", p.json_bytes({"currency": "USD", "models": {
        "claude-opus-5-5": {"input_usd_per_million": 4, "output_usd_per_million": 20,
                            "request_limit_evidence": "https://example.invalid/request-limits"}}}))
    binding = {"format": "context-profile-candidate-binding/v1", "root": str(root), "root_id": "synthetic-root",
               "packet_slot": f"{p.CASES[0]}-r{repetition}", "case_id": p.CASES[0], "repetition": repetition,
               "output_root": str(engine_root), "slot": f"A{repetition}", "family": "A", "cost_cap_usd": "1",
               "source_sha256": p.sha(b"synthetic source evidence"),
               "config_sha256": p.sha(b"synthetic offline config evidence"),
               "packet_sha256": p.sha(b"synthetic admission packet evidence"),
               "experiment_id": "synthetic-experiment", "binding_id": f"synthetic-binding-{repetition}",
               "brief": _description(brief), "instructions": _description(prompt), "schema": _description(schema),
               "route": _description(route), "pricing": _description(pricing)}
    monkeypatch.setattr(p, "REPO", repo)
    monkeypatch.setattr(p, "PROMPT_SHA256", p.sha(prompt.read_bytes()))
    return {"brief": brief, "instructions": prompt, "schema": schema, "route_path": route,
            "pricing_path": pricing, "root": root, "binding": binding}


def test_fixed_values_are_candidate_md_and_the_token_is_the_run_gates_name():
    text = " ".join(CANDIDATE.read_text(encoding="utf-8").split())
    listed = text.split("exact keys:", 1)[1].split(". No token name/value", 1)[0]
    keys = [key.strip() for key in listed.split(",")]
    assert len(keys) == 19 and set(keys) == set(single_call.SINGLE_CALL_REQUIRED) == p.FIXED_INPUTS
    assert ("with single_call, anthropic/claude-opus-5-5, anthropic-oauth-named-token/oauth, family A, "
            "request_limit, max_tokens=8,192, deadline_s=900,") in text
    assert set(BASE["single_call"]) == p.FIXED_INPUTS | {"token"} and len(BASE["single_call"]) == 20
    assert p.PER_CALL_INPUTS == set(PER_CALL) and p.FIXED_INPUTS - p.PER_CALL_INPUTS == set(INVARIANTS)
    assert p.INVARIANT_INPUTS == {**INVARIANTS, "token": TOKEN_NAME}
    assert (p.AGENT_NAME, p.TOKEN_NAME, p.AGENT_FILE) == (NAME, TOKEN_NAME, "agent.json")


def test_checked_in_files_are_an_agent_and_a_stage_the_importer_reads():
    files = config_files(REPO / "configs")
    assert AGENT_YAML in files and STAGE_YAML in files
    assert (AGENT_PARSED["config_type"], AGENT_PARSED["name"]) == ("agent", NAME)
    assert (STAGE_PARSED["config_type"], STAGE_PARSED["name"]) == ("stage", NAME)
    assert STAGE_PARSED["config"] == {"stage": {"name": NAME, "nodes": [{"name": NAME, "type": "agent", "agent": NAME}]}}
    assert p.check_agent_config(deepcopy(AGENT_PARSED["config"]), base=True) == BASE


def test_checked_in_base_loads_through_the_real_loader_with_the_exact_mapping_and_node_defaults(offline):
    store = _Store()
    with offline():
        nodes, config = GraphLoader(store).load_workflow(WORKFLOW)
    leaf = _leaf(nodes, config, store)
    assert leaf.agent_config == BASE
    assert leaf.agent_config["single_call"]["token"] == TOKEN_NAME and "token" not in leaf.agent_config
    _node_defaults(leaf)
    assert p.check_agent_config({"agent": leaf.agent_config}, base=True) == BASE
    assert store.docs[(NAME, "agent")] == AGENT_PARSED["config"]


@pytest.mark.parametrize("repetition", [1, 2, 3])
def test_preparer_writes_the_complete_per_call_config_and_the_real_loader_loads_it(
        repetition, tmp_path, monkeypatch, offline, quiet):
    inputs = _sandbox(tmp_path, monkeypatch, repetition)
    directory = inputs["root"] / inputs["binding"]["packet_slot"]
    with quiet():
        result = p.prepare(**inputs)
        manifest = p.verify_packet(directory, result["manifest_sha256"])
    data = (directory / "agent.json").read_bytes()
    document = p.strict_json(data)
    prompt, pricing = (directory / "prompt.txt").read_bytes(), (directory / "pricing.json").read_bytes()
    binding = inputs["binding"]
    expected = deepcopy(BASE)
    expected["single_call"].update(
        prompt_path=str(directory / "prompt.txt"), prompt_sha256=p.sha(prompt), prompt_bytes=len(prompt),
        output_root=binding["output_root"], slot=f"A{repetition}", cost_cap_usd="1",
        pricing_path=str(directory / "pricing.json"), pricing_sha256=p.sha(pricing),
        experiment_id="synthetic-experiment", binding_id=f"synthetic-binding-{repetition}",
        source_sha256=binding["source_sha256"], config_sha256=binding["config_sha256"],
        packet_sha256=binding["packet_sha256"])
    store = _Store(agent=document)
    with offline():
        nodes, config = GraphLoader(store).load_workflow(WORKFLOW)
    leaf = _leaf(nodes, config, store)
    assert document == {"agent": expected}
    assert leaf.agent_config == expected and len(leaf.agent_config["single_call"]) == 20
    _node_defaults(leaf)
    assert p.check_agent_config({"agent": leaf.agent_config}) == expected

    def invariant(agent):
        return {**{key: agent[key] for key in ("name", "type", "provider", "model")},
                **{key: value for key, value in agent["single_call"].items() if key not in PER_CALL}}

    assert invariant(document["agent"]) == invariant(AGENT_PARSED["config"]["agent"])
    assert result["status"] == "PREPARED" and result["files"] == 9
    assert result["agent_config_sha256"] == p.sha(data)
    assert f"{p.sha(data)}  agent.json\n" in (directory / "SHA256SUMS").read_text(encoding="ascii")
    assert (directory / "agent.json").stat().st_mode & 0o777 == 0o600
    # The manifest stays CANDIDATE.md's token-free 19-field metadata; agent.json is the runnable config.
    assert set(manifest["single_call"]) == p.FIXED_INPUTS and manifest["format"] == p.FORMAT


@pytest.mark.parametrize(("place", "key", "message"), [
    ("agent", "unsupported_outer", CLOSED),
    ("fixed", "unsupported_fixed", UNSUPPORTED),
    *[("agent", key, CLOSED) for key in EXTRA],
    *[("fixed", key, UNSUPPORTED) for key in EXTRA],
    ("node", "tools", CLOSED),
    ("node", "memory", CLOSED),
    ("defaults", "tools", CLOSED),
    ("defaults", "memory", CLOSED),
])
def test_unknown_keys_and_any_tool_memory_or_fallback_are_refused_at_load(place, key, message, offline):
    store = _changed(place, key, deepcopy(EXTRA.get(key, True)))
    with offline(), pytest.raises(ValidationError, match=re.escape(message)):
        GraphLoader(store).load_workflow(WORKFLOW)


@pytest.mark.parametrize("place", ["node", "defaults"])
def test_fallback_outside_the_agent_never_reaches_the_call(place, offline):
    """Not a node field (warned and ignored), and a workflow LLM setting single_call drops."""
    store = _changed(place, "fallback", deepcopy(EXTRA["fallback"]))
    with offline():
        nodes, config = GraphLoader(store).load_workflow(WORKFLOW)
    assert _leaf(nodes, config, store).agent_config == BASE


@pytest.mark.parametrize(("change", "reason"), [
    ("missing-token", "agent_fixed_inputs"),
    ("template", "unrendered_template"),
    ("model", "agent_identity"),
    ("node-model", "agent_identity"),
])
def test_what_the_engine_loader_keeps_as_written_the_candidate_load_check_refuses(change, reason, offline):
    """The #170 loader checks key sets only; token and values stay with single_call's runtime check."""
    store = _Store()
    agent = store.docs[(NAME, "agent")]["agent"]
    if change == "missing-token":
        del agent["single_call"]["token"]
    elif change == "template":
        agent["single_call"]["prompt_path"] = "{{ packet_dir }}/prompt.txt"
    elif change == "model":
        agent["model"] = "placeholder-other-model"
    else:
        store.docs[(NAME, "stage")]["stage"]["nodes"][0]["model"] = "placeholder-other-model"
    written = {**deepcopy(agent), **({"model": "placeholder-other-model"} if change == "node-model" else {})}
    with offline():
        nodes, config = GraphLoader(store).load_workflow(WORKFLOW)
    leaf = _leaf(nodes, config, store)
    assert leaf.agent_config == written
    with pytest.raises(p.Refused, match=f"^{reason}$"):
        p.check_agent_config({"agent": leaf.agent_config}, base=True)


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("token", "${CLAUDE_CODE_OAUTH_TOKEN}", "agent_invariants"),
    ("prompt_path", "${PACKET_DIR}/prompt.txt", "unrendered_template"),
])
def test_environment_reference_is_refused_before_a_store_could_substitute_a_value(field, value, reason):
    document = deepcopy(AGENT_PARSED["config"])
    document["agent"]["single_call"][field] = value
    with pytest.raises(p.Refused, match=f"^{reason}$"):
        p.check_agent_config(document, base=True)


def test_preparer_refuses_a_drifted_agent_config_before_any_write(tmp_path, monkeypatch, quiet):
    inputs = _sandbox(tmp_path, monkeypatch, 1)
    monkeypatch.setattr(p, "TOKEN_NAME", "OTHER_TOKEN_NAME")
    with quiet(), pytest.raises(p.Refused, match="^agent_invariants$"):
        p.prepare(**inputs)
    assert list(inputs["root"].iterdir()) == []


@pytest.mark.parametrize(("sums", "reason"), [(False, "packet_checksum_manifest"), (True, "packet_agent_config_changed")])
def test_verify_packet_refuses_a_changed_agent_config(sums, reason, tmp_path, monkeypatch, quiet):
    inputs = _sandbox(tmp_path, monkeypatch, 1)
    directory = inputs["root"] / inputs["binding"]["packet_slot"]
    with quiet():
        result = p.prepare(**inputs)
    original = (directory / "agent.json").read_bytes()
    document = p.strict_json(original)
    del document["agent"]["single_call"]["token"]
    changed = p.json_bytes(document)
    _store(directory / "agent.json", changed)
    if sums:
        listing = (directory / "SHA256SUMS").read_text(encoding="ascii")
        _store(directory / "SHA256SUMS", listing.replace(p.sha(original), p.sha(changed)).encode("ascii"))
    with quiet(), pytest.raises(p.Refused, match=f"^{reason}$"):
        p.verify_packet(directory, result["manifest_sha256"])
