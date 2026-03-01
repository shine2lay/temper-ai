"""Tests for agent input curation (agent_input_map, strategy context, output validation).

Covers:
- resolve_agent_inputs: stage.field, agent.output, agent.structured.field
- _resolve_source: all source reference formats
- get_agent_input_map_for_agent: schema extraction
- validate_agent_outputs: declared output validation
- curate_agent_context: base, consensus, concatenate, multi_round, leader
- _apply_agent_input_curation: full integration
- _inject_strategy_context: strategy injection
- StandardAgent._build_prompt: strategy context branch
"""

import logging
from unittest.mock import MagicMock

import pytest

from temper_ai.storage.schemas.agent_config import AgentIODeclaration

# ── _resolve_source ──────────────────────────────────────────────────


class TestResolveSource:
    """Tests for _resolve_source() individual source reference resolution."""

    def test_stage_field(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        stage_inputs = {"topic": "AI safety", "depth": 3}
        assert _resolve_source("stage.topic", stage_inputs, {}) == "AI safety"
        assert _resolve_source("stage.depth", stage_inputs, {}) == 3

    def test_stage_field_missing(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        assert _resolve_source("stage.nonexistent", {}, {}) is None

    def test_agent_output(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        prior = {"researcher": {"output": "Found 3 issues"}}
        assert _resolve_source("researcher.output", {}, prior) == "Found 3 issues"

    def test_agent_output_missing_agent(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        assert _resolve_source("missing_agent.output", {}, {}) is None

    def test_agent_structured_field_from_script_outputs(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        prior = {
            "researcher": {
                "output": "raw text",
                "script_outputs": {"claims": ["c1", "c2"]},
            }
        }
        result = _resolve_source("researcher.structured.claims", {}, prior)
        assert result == ["c1", "c2"]

    def test_agent_structured_field_from_structured(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        prior = {
            "parser": {
                "output": "text",
                "structured": {"entities": [{"name": "Acme"}]},
            }
        }
        result = _resolve_source("parser.structured.entities", {}, prior)
        assert result == [{"name": "Acme"}]

    def test_agent_structured_field_missing(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        prior = {"agent": {"output": "text"}}
        assert _resolve_source("agent.structured.missing", {}, prior) is None

    def test_invalid_source_ref(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        assert _resolve_source("nope", {}, {}) is None

    def test_agent_unknown_field(self):
        from temper_ai.stage.executors._agent_input_helpers import _resolve_source

        prior = {"agent": {"output": "text"}}
        assert _resolve_source("agent.unknown_field", {}, prior) is None


# ── resolve_agent_inputs ─────────────────────────────────────────────


class TestResolveAgentInputs:
    """Tests for resolve_agent_inputs()."""

    def test_basic_resolution(self):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "claims": AgentIODeclaration(type="list", required=True),
                "sources": AgentIODeclaration(type="list", required=False, default=[]),
            },
            "outputs": {},
        }
        aim = {"claims": "researcher.structured.claims"}
        prior = {
            "researcher": {"output": "text", "script_outputs": {"claims": ["c1"]}},
        }
        result = resolve_agent_inputs("checker", interface, aim, {}, prior)
        assert result["claims"] == ["c1"]
        assert result["sources"] == []  # default

    def test_stage_and_agent_sources(self):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "topic": AgentIODeclaration(type="string", required=True),
                "prior_analysis": AgentIODeclaration(type="string", required=True),
            },
            "outputs": {},
        }
        aim = {
            "topic": "stage.topic",
            "prior_analysis": "analyst.output",
        }
        stage_inputs = {"topic": "AI safety"}
        prior = {"analyst": {"output": "Risk assessment..."}}
        result = resolve_agent_inputs("summarizer", interface, aim, stage_inputs, prior)
        assert result["topic"] == "AI safety"
        assert result["prior_analysis"] == "Risk assessment..."

    def test_missing_required_raises(self):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "required_field": AgentIODeclaration(type="string", required=True),
            },
            "outputs": {},
        }
        aim = {}  # no mapping for required_field
        with pytest.raises(ValueError, match="required input 'required_field'"):
            resolve_agent_inputs("agent", interface, aim, {}, {})

    def test_optional_without_mapping_uses_default(self):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "opt": AgentIODeclaration(
                    type="string", required=False, default="fallback"
                ),
            },
            "outputs": {},
        }
        result = resolve_agent_inputs("agent", interface, {}, {}, {})
        assert result["opt"] == "fallback"

    def test_optional_without_default_not_required(self):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "opt": AgentIODeclaration(type="string", required=False),
            },
            "outputs": {},
        }
        result = resolve_agent_inputs("agent", interface, {}, {}, {})
        assert "opt" not in result  # Not required, no default, not in result

    def test_source_resolves_to_none_logged(self, caplog):
        from temper_ai.stage.executors._agent_input_helpers import resolve_agent_inputs

        interface = {
            "inputs": {
                "x": AgentIODeclaration(type="string", required=False, default="d"),
            },
            "outputs": {},
        }
        aim = {"x": "missing_agent.output"}
        with caplog.at_level(logging.WARNING):
            result = resolve_agent_inputs("agent", interface, aim, {}, {})
        assert any("resolved to None" in r.message for r in caplog.records)


# ── get_agent_input_map_for_agent ────────────────────────────────────


class TestGetAgentInputMapForAgent:
    """Tests for get_agent_input_map_for_agent()."""

    def test_from_stage_config_object(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._agent_input_helpers import (
            get_agent_input_map_for_agent,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1", "a2"],
                "agent_input_map": {
                    "a2": {"claims": "a1.output"},
                },
            }
        )
        assert get_agent_input_map_for_agent(config, "a2") == {"claims": "a1.output"}
        assert get_agent_input_map_for_agent(config, "a1") is None

    def test_from_raw_dict(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            get_agent_input_map_for_agent,
        )

        config = {
            "name": "test",
            "agents": ["a1"],
            "agent_input_map": {"a1": {"x": "stage.x"}},
        }
        assert get_agent_input_map_for_agent(config, "a1") == {"x": "stage.x"}

    def test_none_config(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            get_agent_input_map_for_agent,
        )

        assert get_agent_input_map_for_agent(None, "a1") is None

    def test_no_agent_input_map(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._agent_input_helpers import (
            get_agent_input_map_for_agent,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1"],
            }
        )
        assert get_agent_input_map_for_agent(config, "a1") is None


# ── validate_agent_outputs ───────────────────────────────────────────


class TestValidateAgentOutputs:
    """Tests for validate_agent_outputs()."""

    def test_extracts_from_script_outputs(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            validate_agent_outputs,
        )

        interface = {
            "outputs": {
                "claims": AgentIODeclaration(type="list"),
            },
        }
        output_data = {
            "output": "raw text",
            "script_outputs": {"claims": ["c1", "c2"]},
        }
        result = validate_agent_outputs("agent", interface, output_data)
        assert result["claims"] == ["c1", "c2"]

    def test_extracts_from_structured(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            validate_agent_outputs,
        )

        interface = {
            "outputs": {
                "entities": AgentIODeclaration(type="list"),
            },
        }
        output_data = {
            "output": "text",
            "structured": {"entities": [{"name": "Acme"}]},
        }
        result = validate_agent_outputs("agent", interface, output_data)
        assert result["entities"] == [{"name": "Acme"}]

    def test_missing_output_warns(self, caplog):
        from temper_ai.stage.executors._agent_input_helpers import (
            validate_agent_outputs,
        )

        interface = {
            "outputs": {
                "summary": AgentIODeclaration(type="string"),
                "score": AgentIODeclaration(type="number"),
            },
        }
        output_data = {"output": "just text"}
        with caplog.at_level(logging.WARNING):
            result = validate_agent_outputs("agent", interface, output_data)
        assert "score" not in result
        assert any("did not produce" in r.message for r in caplog.records)

    def test_no_declared_outputs(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            validate_agent_outputs,
        )

        result = validate_agent_outputs("agent", {"outputs": {}}, {"output": "text"})
        assert result == {}

    def test_single_output_maps_to_raw(self):
        from temper_ai.stage.executors._agent_input_helpers import (
            validate_agent_outputs,
        )

        interface = {
            "outputs": {
                "analysis": AgentIODeclaration(type="string"),
            },
        }
        output_data = {"output": "Detailed analysis here..."}
        result = validate_agent_outputs("agent", interface, output_data)
        assert result["analysis"] == "Detailed analysis here..."


# ── curate_agent_context (Strategy) ──────────────────────────────────


class TestCurateAgentContext:
    """Tests for curate_agent_context() on strategy classes."""

    def test_base_returns_none(self):
        from temper_ai.agent.strategies.base import CollaborationStrategy

        class Stub(CollaborationStrategy):
            def synthesize(self, a, c):
                pass

            def get_capabilities(self):
                return {}

        assert Stub().curate_agent_context("agent") is None

    def test_concatenate_returns_none(self):
        from temper_ai.agent.strategies.concatenate import ConcatenateStrategy

        assert ConcatenateStrategy().curate_agent_context(agent_name="a") is None

    def test_consensus_curates_prior_outputs(self):
        from temper_ai.agent.strategies.consensus import ConsensusStrategy

        cs = ConsensusStrategy()
        ctx = cs.curate_agent_context(
            "checker",
            prior_outputs={
                "researcher": {"output": "Found vulnerabilities"},
                "analyst": {"output": "Risk is high"},
            },
        )
        assert ctx is not None
        assert "researcher" in ctx
        assert "Found vulnerabilities" in ctx
        assert "analyst" in ctx
        assert "Risk is high" in ctx

    def test_consensus_no_priors_returns_none(self):
        from temper_ai.agent.strategies.consensus import ConsensusStrategy

        assert ConsensusStrategy().curate_agent_context("a") is None
        assert ConsensusStrategy().curate_agent_context("a", prior_outputs={}) is None

    def test_consensus_ignores_empty_outputs(self):
        from temper_ai.agent.strategies.consensus import ConsensusStrategy

        ctx = ConsensusStrategy().curate_agent_context(
            "a", prior_outputs={"b": {"output": ""}}
        )
        assert ctx is None  # empty output text filtered

    def test_multi_round_consensus_returns_none(self):
        from temper_ai.agent.strategies.multi_round import MultiRoundStrategy

        mr = MultiRoundStrategy(mode="consensus")
        assert mr.curate_agent_context("a") is None

    def test_multi_round_dialogue_curates_history(self):
        from temper_ai.agent.strategies.multi_round import MultiRoundStrategy

        mr = MultiRoundStrategy(mode="dialogue")
        history = [
            {
                "agent": "a1",
                "round": 0,
                "output": "Initial view",
                "reasoning": "r",
                "confidence": 0.8,
            },
            {
                "agent": "a2",
                "round": 0,
                "output": "Counter view",
                "reasoning": "r",
                "confidence": 0.7,
            },
        ]
        ctx = mr.curate_agent_context(
            "a1",
            round_number=1,
            dialogue_history=history,
        )
        assert ctx is not None
        assert "Initial view" in ctx or "Counter view" in ctx

    def test_multi_round_no_history_returns_none(self):
        from temper_ai.agent.strategies.multi_round import MultiRoundStrategy

        mr = MultiRoundStrategy(mode="dialogue")
        assert mr.curate_agent_context("a1", dialogue_history=[]) is None
        assert mr.curate_agent_context("a1", dialogue_history=None) is None

    def test_leader_curates_for_leader_only(self):
        from temper_ai.agent.strategies.leader import LeaderCollaborationStrategy

        ls = LeaderCollaborationStrategy(leader_agent="decider")
        # Non-leader gets nothing
        assert (
            ls.curate_agent_context(
                "perspective_agent",
                prior_outputs={"a": {"output": "x"}},
            )
            is None
        )
        # Leader gets team outputs
        ctx = ls.curate_agent_context(
            "decider",
            prior_outputs={
                "analyst": {
                    "output": "Important finding",
                    "reasoning": "Because...",
                    "confidence": 0.9,
                },
            },
        )
        assert ctx is not None
        assert "analyst" in ctx
        assert "Important finding" in ctx


# ── _apply_agent_input_curation ──────────────────────────────────────


class TestApplyAgentInputCuration:
    """Tests for _apply_agent_input_curation() in sequential helpers."""

    def test_no_stage_config_passthrough(self):
        from temper_ai.stage.executors._sequential_helpers import (
            _apply_agent_input_curation,
        )

        agent = MagicMock()
        input_data = {"x": 1, "y": 2}
        result = _apply_agent_input_curation(agent, "a", input_data, {}, None)
        assert result is input_data  # unchanged

    def test_no_agent_input_map_passthrough(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _apply_agent_input_curation,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1"],
            }
        )
        agent = MagicMock()
        input_data = {"x": 1}
        result = _apply_agent_input_curation(agent, "a1", input_data, {}, config)
        assert result is input_data

    def test_agent_without_declared_inputs_passthrough(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _apply_agent_input_curation,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1"],
                "agent_input_map": {"a1": {"x": "stage.x"}},
            }
        )
        agent = MagicMock()
        agent.get_interface.return_value = {"inputs": {}, "outputs": {}}
        input_data = {"x": 1}
        result = _apply_agent_input_curation(agent, "a1", input_data, {}, config)
        assert result is input_data

    def test_curated_input_resolution(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _apply_agent_input_curation,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["researcher", "checker"],
                "agent_input_map": {
                    "checker": {"claims": "researcher.structured.claims"},
                },
            }
        )
        agent = MagicMock()
        agent.get_interface.return_value = {
            "inputs": {
                "claims": AgentIODeclaration(type="list", required=True),
            },
            "outputs": {},
        }
        input_data = {
            "topic": "AI",
            "depth": 3,
            "tracker": "t",
            "tool_executor": "te",
        }
        prior = {"researcher": {"output": "text", "script_outputs": {"claims": ["c1"]}}}
        result = _apply_agent_input_curation(
            agent, "checker", input_data, prior, config
        )
        assert result["claims"] == ["c1"]
        # Infrastructure keys preserved
        assert result["tool_executor"] == "te"
        # Original full-state keys NOT present (curated)
        assert "topic" not in result

    def test_resolution_failure_falls_back(self, caplog):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _apply_agent_input_curation,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1"],
                "agent_input_map": {"a1": {}},  # no mapping for required input
            }
        )
        agent = MagicMock()
        agent.get_interface.return_value = {
            "inputs": {
                "required_thing": AgentIODeclaration(type="string", required=True),
            },
            "outputs": {},
        }
        input_data = {"full_state": True}
        with caplog.at_level(logging.WARNING):
            result = _apply_agent_input_curation(agent, "a1", input_data, {}, config)
        assert result is input_data  # fallback to full input


# ── _inject_strategy_context ─────────────────────────────────────────


class TestInjectStrategyContext:
    """Tests for _inject_strategy_context()."""

    def test_no_stage_config(self):
        from temper_ai.stage.executors._sequential_helpers import (
            _inject_strategy_context,
        )

        input_data = {}
        _inject_strategy_context(input_data, "a", {}, None)
        assert "_strategy_context" not in input_data

    def test_no_collaboration(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _inject_strategy_context,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1"],
            }
        )
        input_data = {}
        _inject_strategy_context(input_data, "a1", {}, config)
        assert "_strategy_context" not in input_data

    def test_with_collaboration_and_prior_outputs(self):
        from temper_ai.stage._schemas import StageConfig
        from temper_ai.stage.executors._sequential_helpers import (
            _inject_strategy_context,
        )

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1", "a2"],
                "collaboration": {
                    "strategy": "consensus",
                },
            }
        )
        prior = {"a1": {"output": "My analysis says..."}}
        input_data = {}
        _inject_strategy_context(input_data, "a2", prior, config)
        assert "_strategy_context" in input_data
        assert "a1" in input_data["_strategy_context"]


# ── StandardAgent._build_prompt strategy branch ──────────────────────


class TestBuildPromptStrategyContext:
    """Tests for StandardAgent._build_prompt() strategy context branch.

    Uses ScriptAgent (no LLM needed) to test the prompt rendering pipeline
    since _build_prompt is inherited from BaseAgent.
    """

    def test_strategy_context_appended(self):
        """When _strategy_context is in input_data, it replaces legacy injection."""
        from temper_ai.agent.standard_agent import StandardAgent

        # Test the method directly by constructing a minimal agent
        agent = MagicMock(spec=StandardAgent)
        agent._render_template = (
            lambda data: f"You are helpful. {data.get('topic', '')}"
        )
        agent._inject_input_context = lambda t, d, k: t + "\n## Legacy"
        agent._inject_dialogue_context = lambda t, d: t
        agent._inject_memory_context = lambda t, d, c: t
        agent._inject_optimization_context = lambda t: t
        agent._inject_persistent_context = lambda t, c: t

        input_data = {
            "topic": "AI safety",
            "_strategy_context": "# Prior Agent Outputs\n\n## researcher\nFindings...",
        }
        # Call the real _build_prompt method
        prompt = StandardAgent._build_prompt(agent, input_data)
        assert "You are helpful. AI safety" in prompt
        assert "Prior Agent Outputs" in prompt
        assert "Findings..." in prompt
        # Legacy injection NOT called (no "## Legacy" in output)
        assert "## Legacy" not in prompt

    def test_no_strategy_context_uses_legacy(self):
        """Without _strategy_context, legacy injection methods are used."""
        from temper_ai.agent.standard_agent import StandardAgent

        agent = MagicMock(spec=StandardAgent)
        agent._render_template = (
            lambda data: f"You are helpful. {data.get('topic', '')}"
        )
        agent._inject_input_context = lambda t, d, k: t + "\n## Legacy Input"
        agent._inject_dialogue_context = lambda t, d: t
        agent._inject_memory_context = lambda t, d, c: t
        agent._inject_optimization_context = lambda t: t
        agent._inject_persistent_context = lambda t, c: t

        input_data = {"topic": "AI safety"}
        prompt = StandardAgent._build_prompt(agent, input_data)
        assert "You are helpful. AI safety" in prompt
        assert "## Legacy Input" in prompt


# ── _validate_and_store_agent_outputs ────────────────────────────────


class TestValidateAndStoreAgentOutputs:
    """Tests for _validate_and_store_agent_outputs()."""

    def test_stores_extracted_structured(self):
        from temper_ai.stage.executors._sequential_helpers import (
            _validate_and_store_agent_outputs,
        )

        agent = MagicMock()
        agent.get_interface.return_value = {
            "outputs": {"claims": AgentIODeclaration(type="list")},
        }
        result = {
            "output_data": {
                "output": "text",
                "script_outputs": {"claims": ["c1", "c2"]},
            }
        }
        _validate_and_store_agent_outputs(agent, "researcher", result)
        assert result["output_data"]["structured"]["claims"] == ["c1", "c2"]

    def test_no_declared_outputs_noop(self):
        from temper_ai.stage.executors._sequential_helpers import (
            _validate_and_store_agent_outputs,
        )

        agent = MagicMock()
        agent.get_interface.return_value = {"outputs": {}}
        result = {"output_data": {"output": "text"}}
        _validate_and_store_agent_outputs(agent, "agent", result)
        assert "structured" not in result["output_data"]

    def test_exception_handled_gracefully(self):
        from temper_ai.stage.executors._sequential_helpers import (
            _validate_and_store_agent_outputs,
        )

        agent = MagicMock()
        agent.get_interface.side_effect = Exception("boom")
        result = {"output_data": {"output": "text"}}
        # Should not raise
        _validate_and_store_agent_outputs(agent, "agent", result)
        assert "structured" not in result["output_data"]


# ── StageConfigInner.agent_input_map ─────────────────────────────────


class TestStageConfigAgentInputMap:
    """Tests for agent_input_map on StageConfigInner."""

    def test_default_none(self):
        from temper_ai.stage._schemas import StageConfigInner

        s = StageConfigInner(name="test", description="test", agents=["a"])
        assert s.agent_input_map is None

    def test_valid_agent_input_map(self):
        from temper_ai.stage._schemas import StageConfigInner

        s = StageConfigInner(
            name="test",
            description="test",
            agents=["researcher", "checker"],
            agent_input_map={
                "checker": {"claims": "researcher.output", "ctx": "stage.context"},
            },
        )
        assert s.agent_input_map["checker"]["claims"] == "researcher.output"
        assert s.agent_input_map["checker"]["ctx"] == "stage.context"

    def test_serialization_roundtrip(self):
        from temper_ai.stage._schemas import StageConfig

        config = StageConfig(
            stage={
                "name": "test",
                "description": "test",
                "agents": ["a1", "a2"],
                "agent_input_map": {"a2": {"x": "a1.output"}},
            }
        )
        dumped = config.model_dump()
        assert dumped["stage"]["agent_input_map"]["a2"]["x"] == "a1.output"
        # Reconstruct
        config2 = StageConfig(**dumped)
        assert config2.stage.agent_input_map["a2"]["x"] == "a1.output"


# ── End-to-end integration ───────────────────────────────────────────


class TestEndToEndAgentInputCuration:
    """Integration test: 3 agents with agent_input_map wiring."""

    def test_three_agent_pipeline(self):
        """Researcher → Checker → Summarizer pipeline with curated inputs."""
        from temper_ai.stage.executors._agent_input_helpers import (
            resolve_agent_inputs,
            validate_agent_outputs,
        )

        # Agent interfaces
        researcher_interface = {
            "inputs": {"topic": AgentIODeclaration(type="string", required=True)},
            "outputs": {"claims": AgentIODeclaration(type="list")},
        }
        checker_interface = {
            "inputs": {
                "claims": AgentIODeclaration(type="list", required=True),
                "sources": AgentIODeclaration(type="list", required=False, default=[]),
            },
            "outputs": {"verified": AgentIODeclaration(type="list")},
        }
        summarizer_interface = {
            "inputs": {
                "analysis": AgentIODeclaration(type="string", required=True),
                "verification": AgentIODeclaration(type="string", required=True),
            },
            "outputs": {"summary": AgentIODeclaration(type="string")},
        }

        # Stage inputs
        stage_inputs = {"topic": "AI safety", "sources": ["paper1.pdf"]}

        # Agent input maps
        researcher_aim = {"topic": "stage.topic"}
        checker_aim = {
            "claims": "researcher.structured.claims",
            "sources": "stage.sources",
        }
        summarizer_aim = {
            "analysis": "researcher.output",
            "verification": "checker.output",
        }

        # Step 1: Researcher
        r1 = resolve_agent_inputs(
            "researcher", researcher_interface, researcher_aim, stage_inputs, {}
        )
        assert r1["topic"] == "AI safety"

        # Simulate researcher output
        researcher_output = {
            "output": "Research analysis text...",
            "script_outputs": {"claims": ["LLMs can hallucinate", "RLHF helps"]},
        }
        extracted = validate_agent_outputs(
            "researcher", researcher_interface, researcher_output
        )
        researcher_output["structured"] = extracted
        assert extracted["claims"] == ["LLMs can hallucinate", "RLHF helps"]

        prior_outputs = {"researcher": researcher_output}

        # Step 2: Checker
        r2 = resolve_agent_inputs(
            "checker", checker_interface, checker_aim, stage_inputs, prior_outputs
        )
        assert r2["claims"] == ["LLMs can hallucinate", "RLHF helps"]
        assert r2["sources"] == ["paper1.pdf"]

        # Simulate checker output
        checker_output = {
            "output": "Verification complete: both claims verified",
            "script_outputs": {"verified": [True, True]},
        }
        prior_outputs["checker"] = checker_output

        # Step 3: Summarizer
        r3 = resolve_agent_inputs(
            "summarizer",
            summarizer_interface,
            summarizer_aim,
            stage_inputs,
            prior_outputs,
        )
        assert r3["analysis"] == "Research analysis text..."
        assert r3["verification"] == "Verification complete: both claims verified"
