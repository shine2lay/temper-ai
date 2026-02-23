"""Tests for per-agent evaluation schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.optimization._evaluation_schemas import (
    DEFAULT_EVALUATION_KEY,
    AgentEvaluationConfig,
    EvaluationMapping,
)
from temper_ai.optimization._schemas import (
    CheckConfig,
    OptimizationConfig,
    PipelineStepConfig,
)


class TestAgentEvaluationConfig:
    """Tests for AgentEvaluationConfig."""

    def test_defaults(self):
        cfg = AgentEvaluationConfig()
        assert cfg.type == "scored"
        assert cfg.checks == []
        assert cfg.rubric is None
        assert cfg.prompt is None
        assert cfg.model is None
        assert cfg.weights == {}

    def test_scored_type(self):
        cfg = AgentEvaluationConfig(
            type="scored",
            rubric="Rate the quality of this research.",
            model="ollama/qwen3",
        )
        assert cfg.type == "scored"
        assert cfg.rubric == "Rate the quality of this research."
        assert cfg.model == "ollama/qwen3"

    def test_criteria_type(self):
        cfg = AgentEvaluationConfig(
            type="criteria",
            checks=[
                CheckConfig(
                    name="concise", method="programmatic", command="python check.py"
                ),
                CheckConfig(
                    name="covers_points",
                    method="llm",
                    prompt="Does it cover all points?",
                ),
            ],
        )
        assert cfg.type == "criteria"
        assert len(cfg.checks) == 2
        assert cfg.checks[0].name == "concise"
        assert cfg.checks[1].method == "llm"

    def test_composite_type(self):
        cfg = AgentEvaluationConfig(
            type="composite",
            rubric="Rate quality",
            weights={"quality": 0.7, "cost": 0.15, "latency": 0.15},
        )
        assert cfg.type == "composite"
        assert cfg.weights["quality"] == 0.7
        assert cfg.weights["cost"] == 0.15

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            AgentEvaluationConfig(type="invalid")

    def test_from_dict(self):
        data = {
            "type": "scored",
            "rubric": "Evaluate depth",
            "model": "gpt-4",
        }
        cfg = AgentEvaluationConfig(**data)
        assert cfg.rubric == "Evaluate depth"
        assert cfg.model == "gpt-4"


class TestEvaluationMapping:
    """Tests for EvaluationMapping."""

    def test_defaults(self):
        mapping = EvaluationMapping()
        assert mapping.evaluations == {}
        assert mapping.agent_evaluations == {}

    def test_full_mapping(self):
        mapping = EvaluationMapping(
            evaluations={
                "research_quality": AgentEvaluationConfig(
                    type="scored",
                    rubric="Rate research depth",
                ),
                "balanced": AgentEvaluationConfig(
                    type="composite",
                    weights={"quality": 0.7, "cost": 0.3},
                ),
            },
            agent_evaluations={
                "researcher": ["research_quality", "balanced"],
                "summarizer": ["balanced"],
                DEFAULT_EVALUATION_KEY: ["balanced"],
            },
        )
        assert len(mapping.evaluations) == 2
        assert "research_quality" in mapping.evaluations
        assert mapping.agent_evaluations["researcher"] == [
            "research_quality",
            "balanced",
        ]
        assert mapping.agent_evaluations[DEFAULT_EVALUATION_KEY] == ["balanced"]

    def test_default_key_constant(self):
        assert DEFAULT_EVALUATION_KEY == "_default"


class TestPipelineStepConfigExtensions:
    """Tests for reads and agents fields on PipelineStepConfig."""

    def test_defaults(self):
        cfg = PipelineStepConfig(evaluator="quality")
        assert cfg.reads is None
        assert cfg.agents == []

    def test_with_reads_and_agents(self):
        cfg = PipelineStepConfig(
            evaluator="quality",
            optimizer="prompt",
            reads="research_quality",
            agents=["researcher"],
        )
        assert cfg.reads == "research_quality"
        assert cfg.agents == ["researcher"]


class TestOptimizationConfigExtensions:
    """Tests for evaluations and agent_evaluations on OptimizationConfig."""

    def test_defaults(self):
        cfg = OptimizationConfig()
        assert cfg.evaluations == {}
        assert cfg.agent_evaluations == {}

    def test_with_evaluations(self):
        cfg = OptimizationConfig(
            evaluations={
                "research_quality": {
                    "type": "scored",
                    "rubric": "Rate depth",
                },
            },
            agent_evaluations={
                "researcher": ["research_quality"],
            },
        )
        assert "research_quality" in cfg.evaluations
        assert cfg.agent_evaluations["researcher"] == ["research_quality"]

    def test_full_config_with_pipeline(self):
        cfg = OptimizationConfig(
            evaluations={
                "quality": {"type": "scored", "rubric": "Rate it"},
            },
            agent_evaluations={
                "researcher": ["quality"],
            },
            pipeline=[
                PipelineStepConfig(
                    optimizer="prompt",
                    evaluator="quality",
                    reads="quality",
                    agents=["researcher"],
                ),
            ],
        )
        assert len(cfg.pipeline) == 1
        assert cfg.pipeline[0].reads == "quality"
