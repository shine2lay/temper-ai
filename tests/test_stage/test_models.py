"""Tests for stage/models.py — NodeConfig and WorkflowConfig."""

import logging

import pytest

from temper_ai.stage.models import NodeConfig, WorkflowConfig


class TestNodeConfig:
    def test_from_dict_minimal_agent(self):
        nc = NodeConfig.from_dict({"name": "planner", "type": "agent"})
        assert nc.name == "planner"
        assert nc.type == "agent"
        assert nc.depends_on == []
        assert nc.agent is None
        assert nc.nodes is None

    def test_from_dict_agent_with_ref(self):
        nc = NodeConfig.from_dict({
            "name": "planner",
            "type": "agent",
            "agent": "agents/planner",
        })
        assert nc.agent == "agents/planner"

    def test_from_dict_agent_with_overrides(self):
        nc = NodeConfig.from_dict({
            "name": "reviewer",
            "type": "agent",
            "agent": "agents/senior_engineer",
            "task_template": "Review: {{ code }}",
            "model": "gpt-4o",
            "temperature": 0.2,
        })
        assert nc.task_template == "Review: {{ code }}"
        assert nc.model == "gpt-4o"
        assert nc.temperature == 0.2

    def test_from_dict_stage_with_strategy(self):
        nc = NodeConfig.from_dict({
            "name": "code",
            "type": "stage",
            "strategy": "parallel",
            "agents": ["agents/coder_a", "agents/coder_b"],
            "depends_on": ["planner"],
        })
        assert nc.type == "stage"
        assert nc.strategy == "parallel"
        assert nc.agents == ["agents/coder_a", "agents/coder_b"]
        assert nc.depends_on == ["planner"]
        assert nc.nodes is None

    def test_from_dict_stage_with_explicit_nodes(self):
        nc = NodeConfig.from_dict({
            "name": "review",
            "type": "stage",
            "nodes": [
                {"name": "security", "type": "agent", "agent": "agents/sec"},
                {"name": "quality", "type": "agent", "agent": "agents/qual"},
            ],
        })
        assert nc.nodes is not None
        assert len(nc.nodes) == 2
        assert nc.nodes[0].name == "security"
        assert nc.nodes[1].agent == "agents/qual"

    def test_from_dict_with_condition(self):
        nc = NodeConfig.from_dict({
            "name": "ship",
            "type": "agent",
            "condition": {
                "source": "review.structured.verdict",
                "operator": "equals",
                "value": "PASS",
            },
        })
        assert nc.condition is not None
        assert nc.condition["source"] == "review.structured.verdict"

    def test_from_dict_with_loop(self):
        nc = NodeConfig.from_dict({
            "name": "quality_gate",
            "type": "stage",
            "strategy": "leader",
            "agents": ["agents/checker"],
            "loop_to": "code",
            "max_loops": 3,
        })
        assert nc.loop_to == "code"
        assert nc.max_loops == 3

    def test_from_dict_with_context_boundary(self):
        nc = NodeConfig.from_dict({
            "name": "review",
            "type": "stage",
            "strategy": "leader",
            "agents": ["agents/a"],
            "inputs": {"code_output": "code.output"},
            "outputs": {"verdict": "structured.verdict"},
        })
        assert nc.inputs == {"code_output": "code.output"}
        assert nc.outputs == {"verdict": "structured.verdict"}

    def test_from_dict_skip_policies(self):
        nc = NodeConfig.from_dict({
            "name": "cleanup",
            "type": "agent",
            "skip_policies": ["budget"],
        })
        assert nc.skip_policies == ["budget"]

    def test_from_dict_skip_policies_default_none(self):
        nc = NodeConfig.from_dict({"name": "x"})
        assert nc.skip_policies is None

    def test_from_dict_defaults(self):
        nc = NodeConfig.from_dict({"name": "x"})
        assert nc.type == "agent"
        assert nc.max_loops == 1
        assert nc.depends_on == []
        assert nc.strategy_config == {}

    def test_from_dict_nested_stages(self):
        nc = NodeConfig.from_dict({
            "name": "outer",
            "type": "stage",
            "nodes": [
                {
                    "name": "inner",
                    "type": "stage",
                    "strategy": "parallel",
                    "agents": ["agents/a", "agents/b"],
                },
                {"name": "final", "type": "agent"},
            ],
        })
        assert len(nc.nodes) == 2
        assert nc.nodes[0].type == "stage"
        assert nc.nodes[0].strategy == "parallel"


class TestWorkflowConfig:
    def test_from_dict_minimal(self):
        wc = WorkflowConfig.from_dict({
            "name": "test_workflow",
            "nodes": [{"name": "step1", "type": "agent"}],
        })
        assert wc.name == "test_workflow"
        assert wc.version == "1.0"
        assert len(wc.nodes) == 1

    def test_from_dict_full(self):
        wc = WorkflowConfig.from_dict({
            "name": "sdlc",
            "description": "Full SDLC pipeline",
            "version": "2.0",
            "inputs": {"task": {"type": "string", "required": True}},
            "safety": {"policies": [{"type": "budget", "max_cost_usd": 1.0}]},
            "memory": {"enabled": True},
            "defaults": {"provider": "openai"},
            "nodes": [
                {"name": "plan", "type": "agent"},
                {"name": "code", "type": "stage", "strategy": "parallel",
                 "agents": ["a", "b"], "depends_on": ["plan"]},
            ],
        })
        assert wc.description == "Full SDLC pipeline"
        assert wc.version == "2.0"
        assert wc.inputs is not None
        assert wc.safety is not None
        assert wc.memory is not None
        assert len(wc.nodes) == 2
        assert wc.nodes[1].depends_on == ["plan"]

    def test_from_dict_empty_nodes(self):
        wc = WorkflowConfig.from_dict({"name": "empty"})
        assert wc.nodes == []


class TestUnknownKeyWarnings:
    """Verify that unknown keys in YAML produce warnings (catches typos)."""

    def test_node_unknown_field_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.stage.models"):
            nc = NodeConfig.from_dict({
                "name": "test",
                "type": "agent",
                "dependson": ["a"],  # typo: missing underscore
            })
        assert nc.depends_on == []  # typo was ignored, default used
        assert "unknown fields" in caplog.text
        assert "dependson" in caplog.text

    def test_node_multiple_unknown_fields_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.stage.models"):
            NodeConfig.from_dict({
                "name": "test",
                "stratgey": "parallel",  # typo
                "max_loop": 3,  # typo: missing s
            })
        assert "stratgey" in caplog.text
        assert "max_loop" in caplog.text

    def test_node_known_fields_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.stage.models"):
            NodeConfig.from_dict({
                "name": "test",
                "type": "agent",
                "depends_on": ["a"],
                "model": "gpt-4o",
                "temperature": 0.5,
            })
        assert "unknown fields" not in caplog.text

    def test_workflow_unknown_field_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.stage.models"):
            WorkflowConfig.from_dict({
                "name": "test",
                "safty": {"policies": []},  # typo
            })
        assert "unknown fields" in caplog.text
        assert "safty" in caplog.text

    def test_workflow_known_fields_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.stage.models"):
            WorkflowConfig.from_dict({
                "name": "test",
                "description": "ok",
                "safety": {"policies": []},
                "defaults": {"provider": "openai"},
            })
        assert "unknown fields" not in caplog.text
