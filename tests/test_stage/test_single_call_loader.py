"""Offline known answers for the supported one-stage/one-agent server workflow.

These are loader/config checks, not run admission. All paths and bindings are
literal placeholders, never opened. No provider, credential or attempt is made.
"""

import builtins
import io
import os
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
from temper_ai.llm import providers
from temper_ai.llm.providers import anthropic, factory, openai
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage import agent_node, dispatch_validation
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import ValidationError
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.stage_node import StageNode

# Import the dispatch validator before the no-file-I/O scope, including on the
# first test: the real loader imports it lazily. It is not replaced by a fake.
assert dispatch_validation.validate_dispatch_block


def _fixed_agent():
    return {
        "name": "fixed-agent",
        "type": "single_call",
        "provider": "openai",
        "model": "gpt-6.1-sol",
        "single_call": {
            "prompt_path": "/offline-placeholder/prompt.txt",
            "prompt_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
            "prompt_bytes": 123,
            "output_root": "/offline-placeholder/output",
            "slot": "B1",
            "family": "B",
            "route": "openai-codex-oauth",
            "auth_mode": "oauth",
            "max_tokens": 1024,
            "output_bound_mode": "documented_max",
            "deadline_s": 900,
            "cost_cap_usd": "0.25",
            "pricing_path": "/offline-placeholder/pricing.json",
            "pricing_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
            "experiment_id": "offline-experiment",
            "binding_id": "offline-binding",
            "source_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
            "config_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
            "packet_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
        },
    }


class _Store:
    """Only two in-memory lookups; never the filesystem-backed ConfigStore."""

    def __init__(self, agent=None, node=None, defaults=None):
        self.agent = deepcopy(_fixed_agent() if agent is None else agent)
        self.workflow = {
            "name": "offline-workflow",
            "defaults": deepcopy(defaults or {}),
            "nodes": [{
                "name": "only-stage", "type": "stage",
                "nodes": [{"name": "only-agent", "type": "agent",
                           "agent": "agents/fixed-agent", **(node or {})}],
            }],
        }
        self.lookups = []

    def get(self, name, config_type):
        self.lookups.append((name, config_type))
        if (name, config_type) == ("offline-workflow", "workflow"):
            return deepcopy(self.workflow)
        assert (name, config_type) == ("fixed-agent", "agent")
        return deepcopy(self.agent)


@pytest.fixture
def offline(monkeypatch):
    @contextmanager
    def scope():
        calls = {}
        # Counts catch even a forbidden operation whose exception was swallowed.
        # The actual config merge and SingleCallAgent.validate_config stay real.
        targets = [
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
            (os, "mkdir"),
            (os, "stat"),
            (Path, "open"),
        ]
        # Other agent types must not suddenly be constructed/validated at load.
        for cls in (agents.LLMAgent, agents.ScriptAgent, agents.JevAgent):
            targets.extend([(cls, "__init__"), (cls, "validate_config")])
        with monkeypatch.context() as guard:
            for index, (owner, attr) in enumerate(targets):
                label = f"{index}:{getattr(owner, '__name__', type(owner).__name__)}.{attr}"
                calls[label] = Mock(side_effect=AssertionError(f"forbidden offline operation: {label}"))
                guard.setattr(owner, attr, calls[label])
            yield
        assert {key: value.call_count for key, value in calls.items()} == dict.fromkeys(calls, 0)

    return scope


def _load(store):
    nodes, config = GraphLoader(store).load_workflow("offline-workflow")
    assert config.name == "offline-workflow"
    assert len(nodes) == 1 and isinstance(nodes[0], StageNode)
    assert len(nodes[0].child_nodes) == 1
    leaf = nodes[0].child_nodes[0]
    assert isinstance(leaf, AgentNode)
    assert store.lookups == [("offline-workflow", "workflow"), ("fixed-agent", "agent")]
    return leaf


def test_load_workflow_complete_one_stage_one_single_call_has_exact_mapping_and_node_defaults(offline):
    """Combined whole-feature happy path; separation-removal mutation bite."""
    expected = _fixed_agent()
    assert set(expected) == {"name", "type", "provider", "model", "single_call"}
    assert len(expected["single_call"]) == 19
    assert set(expected["single_call"]) == single_call.SINGLE_CALL_REQUIRED
    store = _Store()
    with offline():
        leaf = _load(store)
        assert leaf.agent_config == expected
        assert leaf.name == "only-agent" and leaf.agent_config["name"] == "fixed-agent"
        assert leaf.config.on_max_loops == "silent"
        assert leaf.config.run_after_failure is False
        assert leaf.config.gate is False
        assert leaf.config.timeout_seconds is None
        assert store.agent == expected


def test_explicit_node_policies_stay_on_node_not_in_closed_single_call_mapping(offline):
    policies = {
        "depends_on": [], "condition": {"source": "only-agent.structured.ok", "operator": "equals", "value": True},
        "loop_to": "only-agent", "max_loops": 3,
        "loop_condition": {"source": "only-agent.structured.again", "operator": "equals", "value": True},
        "on_max_loops": "fail", "run_after_failure": True, "undoes": ["only-agent"],
        "on_failure": "hold", "required_files": ["input.artifact"],
        "renamed_from": ["previous-agent"], "timeout_seconds": 61,
        "gate": True, "skip_policies": ["budget"],
        "input_map": {"label": "input.label"}, "inputs": {"label": "string"},
        "outputs": {"answer": "string"},
    }
    with offline():
        leaf = _load(_Store(node=policies))
        assert leaf.agent_config == _fixed_agent()
        for key, value in policies.items():
            assert getattr(leaf.config, key) == value


@pytest.mark.parametrize("origin", ["agent", "defaults", "overrides"])
def test_unknown_outer_key_is_refused_not_dropped_after_merging(origin, offline):
    """Closed-validation-removal mutation bite, at the final merged boundary."""
    store = _Store()
    loader = GraphLoader(store)
    if origin == "agent":
        store.agent["unsupported_outer"] = True
    elif origin == "defaults":
        store.workflow["defaults"]["unsupported_outer"] = True
    else:
        loader._overrides = {"unsupported_outer": True}
    with offline(), pytest.raises(ValidationError, match="Node 'only-agent': single_call requires a closed fixed-input mapping"):
        loader.load_workflow("offline-workflow")


@pytest.mark.parametrize("key", ["gate", "on_max_loops", "timeout_seconds", "_KNOWN_FIELDS"])
def test_node_policy_key_misplaced_in_agent_is_refused_not_filtered(key, offline):
    store = _Store()
    store.agent[key] = True
    with offline(), pytest.raises(ValidationError, match="single_call requires a closed fixed-input mapping"):
        GraphLoader(store).load_workflow("offline-workflow")


def test_unknown_fixed_key_is_refused_not_dropped(offline):
    """Closed-validation-removal mutation bite for nested unsupported keys."""
    store = _Store()
    store.agent["single_call"]["unsupported_fixed"] = True
    with offline(), pytest.raises(ValidationError, match="Node 'only-agent': single_call has missing or unsupported fixed inputs"):
        GraphLoader(store).load_workflow("offline-workflow")


@pytest.mark.parametrize("key", sorted(single_call.SINGLE_CALL_REQUIRED))
def test_each_required_fixed_key_is_required_by_load_workflow(key, offline):
    store = _Store()
    del store.agent["single_call"][key]
    with offline(), pytest.raises(ValidationError, match="single_call has missing or unsupported fixed inputs"):
        GraphLoader(store).load_workflow("offline-workflow")


@pytest.mark.parametrize("key", ["provider", "model"])
def test_missing_explicit_provider_or_model_is_refused_without_resolution(key, offline):
    store = _Store(defaults={key: "placeholder-default"})
    del store.agent[key]
    with offline(), pytest.raises(ValidationError, match="single_call requires an explicit provider and model"):
        GraphLoader(store).load_workflow("offline-workflow")


def test_single_call_legitimate_node_overrides_and_non_llm_default_filter_are_preserved(offline):
    store = _Store(
        node={"provider": "placeholder-node-provider", "model": "placeholder-node-model"},
        defaults={"provider": "placeholder-default", "model": "placeholder-default",
                  "token": "placeholder-name-not-a-credential", "fallback": [],
                  "description": "offline description", "dispatch": {}, "safety": {}},
    )
    loader = GraphLoader(store)
    loader._overrides = {"provider": "placeholder-run-provider", "model": "placeholder-run-model"}
    expected = {**_fixed_agent(), "provider": "placeholder-node-provider", "model": "placeholder-node-model",
                "description": "offline description"}
    with offline():
        nodes, _ = loader.load_workflow("offline-workflow")
        assert nodes[0].child_nodes[0].agent_config == expected


@pytest.mark.parametrize("agent_type", ["llm", "script", "jev"])
def test_other_agents_keep_legacy_overrides_without_new_constructor_or_validation(agent_type, offline):
    store = _Store(
        agent={"name": "fixed-agent", "type": agent_type, "model": "placeholder-own-model", "own_key": 7},
        node={"model": "placeholder-node-model", "provider": "placeholder-node-provider", "timeout_seconds": 61},
        defaults={"model": "placeholder-default-model", "provider": "placeholder-default-provider"},
    )
    loader = GraphLoader(store)
    loader._overrides = {"model": "placeholder-run-model", "provider": "placeholder-run-provider"}
    with offline():
        nodes, _ = loader.load_workflow("offline-workflow")
        leaf = nodes[0].child_nodes[0]
        config = leaf.agent_config
        assert config["name"] == "fixed-agent" and config["type"] == agent_type
        assert config["own_key"] == 7
        prefix = "node" if agent_type == "jev" else "run"
        assert config["model"] == f"placeholder-{prefix}-model"
        assert config["provider"] == f"placeholder-{prefix}-provider"
        # Some existing agents consume this node field as an agent setting too.
        assert config["timeout_seconds"] == leaf.config.timeout_seconds == 61
