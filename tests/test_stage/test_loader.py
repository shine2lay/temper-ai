"""Tests for stage/loader.py — config loading and resolution."""

from unittest.mock import MagicMock

import pytest

from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import LoaderError, ValidationError
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.stage_node import StageNode


def _mock_config_store(configs=None):
    """Create a mock ConfigStore with predefined configs."""
    store = MagicMock()
    config_map = configs or {}

    def get(name, config_type):
        key = f"{config_type}:{name}"
        if key in config_map:
            return config_map[key]
        raise Exception(f"Config not found: {key}")

    store.get = MagicMock(side_effect=get)
    return store


class TestGraphLoaderAgentNodes:
    def test_load_agent_node(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{"name": "planner", "type": "agent", "agent": "agents/planner"}],
            },
            "agent:planner": {
                "name": "planner",
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o",
                "system_prompt": "You are a planner",
            },
        })
        loader = GraphLoader(store)
        nodes, config = loader.load_workflow("test")

        assert len(nodes) == 1
        assert isinstance(nodes[0], AgentNode)
        assert nodes[0].name == "planner"
        assert nodes[0].agent_config["provider"] == "openai"

    def test_agent_node_with_overrides(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "reviewer",
                    "type": "agent",
                    "agent": "agents/engineer",
                    "task_template": "Review: {{ code }}",
                    "model": "gpt-4o-mini",
                }],
            },
            "agent:engineer": {
                "name": "engineer",
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o",
                "system_prompt": "You are an engineer",
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        agent_config = nodes[0].agent_config
        # Node overrides win
        assert agent_config["model"] == "gpt-4o-mini"
        assert agent_config["task_template"] == "Review: {{ code }}"
        # Base preserved
        assert agent_config["system_prompt"] == "You are an engineer"
        assert agent_config["provider"] == "openai"


class TestGraphLoaderStageNodes:
    def test_stage_with_strategy(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "code",
                    "type": "stage",
                    "strategy": "parallel",
                    "agents": ["agents/coder_a", "agents/coder_b"],
                }],
            },
            "agent:coder_a": {"name": "coder_a", "type": "llm"},
            "agent:coder_b": {"name": "coder_b", "type": "llm"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        assert len(nodes) == 1
        assert isinstance(nodes[0], StageNode)
        assert len(nodes[0].child_nodes) == 2
        assert all(isinstance(n, AgentNode) for n in nodes[0].child_nodes)

    def test_stage_with_explicit_nodes(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "review",
                    "type": "stage",
                    "nodes": [
                        {"name": "sec", "type": "agent", "agent": "agents/sec_reviewer"},
                        {"name": "qual", "type": "agent", "agent": "agents/qual_reviewer"},
                        {"name": "decider", "type": "agent", "agent": "agents/decider",
                         "depends_on": ["sec", "qual"]},
                    ],
                }],
            },
            "agent:sec_reviewer": {"name": "sec_reviewer", "type": "llm"},
            "agent:qual_reviewer": {"name": "qual_reviewer", "type": "llm"},
            "agent:decider": {"name": "decider", "type": "llm"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        stage = nodes[0]
        assert isinstance(stage, StageNode)
        assert len(stage.child_nodes) == 3
        assert stage.child_nodes[2].name == "decider"
        assert stage.child_nodes[2].depends_on == ["sec", "qual"]

    def test_stage_both_agents_and_nodes_raises(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "bad",
                    "type": "stage",
                    "strategy": "parallel",
                    "agents": ["agents/a"],
                    "nodes": [{"name": "b", "type": "agent"}],
                }],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="both 'agents' and 'nodes'"):
            loader.load_workflow("test")

    def test_stage_neither_agents_nor_nodes_raises(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{"name": "empty", "type": "stage"}],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="needs either"):
            loader.load_workflow("test")

    def test_stage_agents_without_strategy_raises(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "no_strat",
                    "type": "stage",
                    "agents": ["agents/a", "agents/b"],
                }],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="no 'strategy'"):
            loader.load_workflow("test")


class TestGraphLoaderValidation:
    def test_invalid_depends_on(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent"},
                    {"name": "b", "type": "agent", "depends_on": ["nonexistent"]},
                ],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="doesn't exist"):
            loader.load_workflow("test")

    def test_invalid_loop_to(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent", "loop_to": "nonexistent"},
                ],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="doesn't exist"):
            loader.load_workflow("test")

    def test_invalid_condition_source(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent",
                     "condition": {"source": "ghost.output", "operator": "equals", "value": "x"}},
                ],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="doesn't exist"):
            loader.load_workflow("test")

    def test_valid_workflow_passes(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent"},
                    {"name": "b", "type": "agent", "depends_on": ["a"]},
                    {"name": "c", "type": "agent", "depends_on": ["b"],
                     "condition": {"source": "b.output", "operator": "exists"}},
                ],
            },
        })
        loader = GraphLoader(store)
        nodes, config = loader.load_workflow("test")
        assert len(nodes) == 3


class TestGraphLoaderDefaults:
    def test_defaults_applied_to_agent_node(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{"name": "planner", "type": "agent", "agent": "agents/planner"}],
            },
            "agent:planner": {
                "name": "planner",
                "type": "llm",
                "system_prompt": "You plan.",
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        # Agent config should inherit defaults since it doesn't set provider/model
        assert nodes[0].agent_config["provider"] == "vllm"
        assert nodes[0].agent_config["model"] == "qwen3"

    def test_agent_config_overrides_defaults(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{"name": "planner", "type": "agent", "agent": "agents/planner"}],
            },
            "agent:planner": {
                "name": "planner",
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o",
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        # Agent's own config wins over defaults
        assert nodes[0].agent_config["provider"] == "openai"
        assert nodes[0].agent_config["model"] == "gpt-4o"

    def test_node_override_wins_over_all(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{
                    "name": "planner", "type": "agent",
                    "agent": "agents/planner",
                    "model": "gpt-4o-mini",  # node override
                }],
            },
            "agent:planner": {
                "name": "planner",
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o",
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        # Node override wins
        assert nodes[0].agent_config["model"] == "gpt-4o-mini"
        # Agent config wins over defaults
        assert nodes[0].agent_config["provider"] == "openai"

    def test_defaults_applied_to_strategy_agents(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "temperature": 0.7},
                "nodes": [{
                    "name": "code",
                    "type": "stage",
                    "strategy": "parallel",
                    "agents": ["agents/coder_a", "agents/coder_b"],
                }],
            },
            "agent:coder_a": {"name": "coder_a", "type": "llm"},
            "agent:coder_b": {"name": "coder_b", "type": "llm", "provider": "openai"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")

        stage = nodes[0]
        # coder_a has no provider → gets default
        assert stage.child_nodes[0].agent_config["provider"] == "vllm"
        assert stage.child_nodes[0].agent_config["temperature"] == 0.7
        # coder_b has its own provider → wins over default
        assert stage.child_nodes[1].agent_config["provider"] == "openai"
        assert stage.child_nodes[1].agent_config["temperature"] == 0.7

    def test_no_defaults_works(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {"name": "a", "type": "llm", "provider": "openai"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].agent_config["provider"] == "openai"

    def test_workflow_dispatch_caps_dont_leak_into_agent_config(self):
        """workflow.defaults.dispatch holds SAFETY CAPS (a dict). agent.dispatch
        holds OPS (a list). Same key, different meanings — merging the caps
        dict into an agent config as `dispatch` then trips the dispatch
        renderer into 'dispatch: must be a list, got dict'. Fix: filter
        `dispatch` and `safety` out of workflow defaults when merging into
        per-agent configs."""
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {
                    "provider": "vllm",
                    "dispatch": {"max_children_per_dispatch": 5},
                },
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {"name": "a", "type": "llm"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        # Provider default still cascades
        assert nodes[0].agent_config["provider"] == "vllm"
        # Workflow-scoped dispatch caps don't leak
        assert "dispatch" not in nodes[0].agent_config

    def test_agent_level_dispatch_ops_preserved(self):
        """If the AGENT's own config declares `dispatch: [ops]`, that stays.
        Workflow-level defaults can't clobber it even if they also have a
        `dispatch:` key (the filter runs on defaults, not on agent)."""
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {
                    "provider": "vllm",
                    "dispatch": {"max_children_per_dispatch": 5},
                },
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {
                "name": "a", "type": "llm",
                "dispatch": [{"op": "add", "node": {"name": "c", "agent": "x"}}],
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        # Agent-level ops survived
        assert isinstance(nodes[0].agent_config["dispatch"], list)
        assert nodes[0].agent_config["dispatch"][0]["op"] == "add"

    def test_workflow_safety_doesnt_leak_into_agents(self):
        """Same treatment for `safety` — it's workflow-scoped policy config,
        not agent metadata."""
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {
                    "provider": "vllm",
                    "safety": {"policies": [{"type": "budget", "max_cost_usd": 5}]},
                },
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {"name": "a", "type": "llm"},
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        assert "safety" not in nodes[0].agent_config


class TestGraphLoaderCLIOverrides:
    """CLI flags like --provider / --model set loader._overrides, which must
    win over workflow defaults, agent config, and node-level overrides."""

    def test_override_beats_agent_config(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {
                "name": "a", "type": "llm",
                "provider": "openai", "model": "gpt-4o",
            },
        })
        loader = GraphLoader(store)
        loader._overrides = {"provider": "claude", "model": "opus"}
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].agent_config["provider"] == "claude"
        assert nodes[0].agent_config["model"] == "opus"

    def test_override_beats_node_override(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "a", "type": "agent", "agent": "agents/a",
                    "model": "gpt-4o-mini",
                }],
            },
            "agent:a": {"name": "a", "type": "llm", "provider": "openai"},
        })
        loader = GraphLoader(store)
        loader._overrides = {"provider": "claude", "model": "opus"}
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].agent_config["provider"] == "claude"
        assert nodes[0].agent_config["model"] == "opus"

    def test_partial_override_keeps_other_fields(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {"name": "a", "type": "llm"},
        })
        loader = GraphLoader(store)
        loader._overrides = {"provider": "claude"}  # model left alone
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].agent_config["provider"] == "claude"
        assert nodes[0].agent_config["model"] == "qwen3"

    def test_override_applies_to_strategy_agents(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [{
                    "name": "review", "type": "stage", "strategy": "parallel",
                    "agents": [
                        "agents/a",
                        {"agent": "agents/b", "model": "inline-override"},
                    ],
                }],
            },
            "agent:a": {"name": "a", "type": "llm", "provider": "openai"},
            "agent:b": {"name": "b", "type": "llm", "provider": "openai"},
        })
        loader = GraphLoader(store)
        loader._overrides = {"provider": "claude", "model": "opus"}
        nodes, _ = loader.load_workflow("test")
        stage = nodes[0]
        # String-ref agent: override wins over agent config's provider
        assert stage.child_nodes[0].agent_config["provider"] == "claude"
        assert stage.child_nodes[0].agent_config["model"] == "opus"
        # Dict-ref agent with inline model override: CLI override still wins
        assert stage.child_nodes[1].agent_config["provider"] == "claude"
        assert stage.child_nodes[1].agent_config["model"] == "opus"

    def test_no_overrides_is_noop(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "defaults": {"provider": "vllm", "model": "qwen3"},
                "nodes": [{"name": "a", "type": "agent", "agent": "agents/a"}],
            },
            "agent:a": {"name": "a", "type": "llm"},
        })
        loader = GraphLoader(store)
        # No _overrides set → defaults behavior intact
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].agent_config["provider"] == "vllm"
        assert nodes[0].agent_config["model"] == "qwen3"


class TestGraphLoaderInputMapValidation:
    def test_valid_input_map(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent"},
                    {"name": "b", "type": "agent", "depends_on": ["a"],
                     "input_map": {"code": "a.output"}},
                ],
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        assert len(nodes) == 2

    def test_input_map_workflow_source(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent",
                     "input_map": {"task": "workflow.task", "ctx": "input.context"}},
                ],
            },
        })
        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("test")
        assert len(nodes) == 1

    def test_input_map_invalid_format(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent",
                     "input_map": {"task": "bad_no_dot"}},
                ],
            },
        })
        loader = GraphLoader(store)
        # Bare identifiers are valid — resolver treats them as workflow-input
        # keys at runtime, else as literals. No error at load time.
        nodes, _ = loader.load_workflow("test")
        assert nodes[0].config.input_map == {"task": "bad_no_dot"}

    def test_input_map_nonexistent_source_node(self):
        store = _mock_config_store({
            "workflow:test": {
                "name": "test",
                "nodes": [
                    {"name": "a", "type": "agent",
                     "input_map": {"code": "ghost.output"}},
                ],
            },
        })
        loader = GraphLoader(store)
        with pytest.raises(ValidationError, match="references.*ghost.*doesn't exist"):
            loader.load_workflow("test")


class TestGraphLoaderNoStore:
    def test_no_store_raises(self):
        loader = GraphLoader(config_store=None)
        with pytest.raises(LoaderError, match="no config store"):
            loader.load_workflow("anything")
