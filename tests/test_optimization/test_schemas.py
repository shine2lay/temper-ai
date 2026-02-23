"""Tests for optimization schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.optimization.dspy._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)


class TestPromptOptimizationConfig:
    """Tests for PromptOptimizationConfig."""

    def test_defaults(self):
        cfg = PromptOptimizationConfig()
        assert cfg.enabled is False
        assert cfg.optimizer == "bootstrap"
        assert cfg.module_type == "predict"
        assert cfg.input_fields == []
        assert cfg.output_fields == ["output"]
        assert cfg.min_training_examples == 10
        assert cfg.min_quality_score == 0.7
        assert cfg.training_metric == "exact_match"
        assert cfg.lookback_hours == 720
        assert cfg.max_demos == 3
        assert cfg.num_threads == 4
        assert cfg.program_store_dir == "configs/optimization"
        assert cfg.auto_compile is False

    def test_custom_values(self):
        cfg = PromptOptimizationConfig(
            enabled=True,
            optimizer="mipro",
            module_type="chain_of_thought",
            input_fields=["topic", "context"],
            output_fields=["analysis", "summary"],
            min_training_examples=50,
            min_quality_score=0.9,
            max_demos=5,
            auto_compile=True,
        )
        assert cfg.enabled is True
        assert cfg.optimizer == "mipro"
        assert cfg.module_type == "chain_of_thought"
        assert cfg.input_fields == ["topic", "context"]
        assert cfg.output_fields == ["analysis", "summary"]
        assert cfg.min_training_examples == 50

    def test_custom_optimizer_accepted(self):
        # optimizer is now a plain str — any value is accepted
        cfg = PromptOptimizationConfig(optimizer="copro")
        assert cfg.optimizer == "copro"

    def test_custom_module_type_accepted(self):
        # module_type is now a plain str — any value is accepted
        cfg = PromptOptimizationConfig(module_type="react")
        assert cfg.module_type == "react"

    def test_quality_score_bounds(self):
        with pytest.raises(ValidationError):
            PromptOptimizationConfig(min_quality_score=1.5)
        with pytest.raises(ValidationError):
            PromptOptimizationConfig(min_quality_score=-0.1)

    def test_min_training_examples_positive(self):
        with pytest.raises(ValidationError):
            PromptOptimizationConfig(min_training_examples=0)

    def test_from_dict(self):
        data = {"enabled": True, "optimizer": "mipro", "max_demos": 5}
        cfg = PromptOptimizationConfig(**data)
        assert cfg.enabled is True
        assert cfg.optimizer == "mipro"
        assert cfg.max_demos == 5


class TestTrainingExample:
    """Tests for TrainingExample."""

    def test_creation(self):
        ex = TrainingExample(
            input_text="Research AI safety",
            output_text="AI safety analysis...",
            metric_score=0.95,
            agent_name="researcher",
        )
        assert ex.input_text == "Research AI safety"
        assert ex.output_text == "AI safety analysis..."
        assert ex.metric_score == 0.95
        assert ex.agent_name == "researcher"
        assert ex.prompt_template_hash is None

    def test_with_hash(self):
        ex = TrainingExample(
            input_text="input",
            output_text="output",
            metric_score=0.8,
            agent_name="agent",
            prompt_template_hash="abc123",
        )
        assert ex.prompt_template_hash == "abc123"

    def test_metric_score_bounds(self):
        with pytest.raises(ValidationError):
            TrainingExample(
                input_text="x",
                output_text="y",
                metric_score=1.5,
                agent_name="a",
            )
        with pytest.raises(ValidationError):
            TrainingExample(
                input_text="x",
                output_text="y",
                metric_score=-0.1,
                agent_name="a",
            )


class TestCompilationResult:
    """Tests for CompilationResult."""

    def test_creation(self):
        result = CompilationResult(
            program_id="prog-1",
            agent_name="researcher",
            optimizer_type="bootstrap",
            train_score=0.85,
            val_score=0.82,
            num_examples=100,
            num_demos=3,
        )
        assert result.program_id == "prog-1"
        assert result.agent_name == "researcher"
        assert result.optimizer_type == "bootstrap"
        assert result.train_score == 0.85
        assert result.val_score == 0.82
        assert result.num_examples == 100
        assert result.num_demos == 3
        assert result.metadata == {}

    def test_defaults(self):
        result = CompilationResult(
            program_id="p1",
            agent_name="a",
            optimizer_type="bootstrap",
        )
        assert result.train_score is None
        assert result.val_score is None
        assert result.num_examples == 0
        assert result.num_demos == 0
        assert result.metadata == {}


class TestAgentConfigIntegration:
    """Test prompt_optimization field on AgentConfigInner."""

    def test_agent_config_accepts_prompt_optimization_dict(self):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        config = AgentConfig(
            agent={
                "name": "test",
                "description": "test agent",
                "prompt": {"inline": "Do {{ task }}"},
                "inference": {
                    "provider": "ollama",
                    "model": "llama3",
                },
                "error_handling": {},
                "prompt_optimization": {
                    "enabled": True,
                    "optimizer": "bootstrap",
                    "max_demos": 5,
                },
            }
        )
        opt = config.agent.prompt_optimization
        assert isinstance(opt, PromptOptimizationConfig)
        assert opt.enabled is True
        assert opt.optimizer == "bootstrap"
        assert opt.max_demos == 5

    def test_agent_config_none_prompt_optimization(self):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        config = AgentConfig(
            agent={
                "name": "test",
                "description": "test agent",
                "prompt": {"inline": "Do {{ task }}"},
                "inference": {
                    "provider": "ollama",
                    "model": "llama3",
                },
                "error_handling": {},
            }
        )
        assert config.agent.prompt_optimization is None
