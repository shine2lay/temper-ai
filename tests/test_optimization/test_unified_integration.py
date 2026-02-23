"""Integration tests for the unified optimization engine.

Verifies that:
- The optimization pipeline works with the new 'prompt' optimizer step
- DSPy imports from the new dspy/ subpackage work
- The registry has all 4 optimizer types
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationRegistry,
    OptimizationResult,
    PipelineStepConfig,
)
from temper_ai.optimization._schemas import EvaluatorConfig


class TestDSPySubpackageImports:
    """Verify DSPy imports from new dspy/ subpackage."""

    def test_import_schemas(self):
        from temper_ai.optimization.dspy._schemas import (  # noqa: F401
            CompilationResult,
            PromptOptimizationConfig,
            TrainingExample,
        )

        assert CompilationResult is not None
        assert PromptOptimizationConfig is not None
        assert TrainingExample is not None

    def test_lazy_getattr(self):
        """Lazy __getattr__ on dspy subpackage works."""
        from temper_ai.optimization import dspy

        # These use __getattr__ lazy loading
        assert hasattr(dspy, "PromptOptimizationConfig")

    def test_dspy_init_raises_for_unknown(self):
        from temper_ai.optimization import dspy

        with pytest.raises(AttributeError, match="no attribute"):
            _ = dspy.NonExistentClass


class TestRegistryCompleteness:
    """Verify the registry has all 4 optimizer types."""

    def setup_method(self):
        OptimizationRegistry.reset_for_testing()

    def test_has_all_optimizer_types(self):
        registry = OptimizationRegistry.get_instance()
        expected = {"refinement", "selection", "tuning", "prompt"}
        for name in expected:
            cls = registry.get_optimizer_class(name)
            assert cls is not None, f"Missing optimizer: {name}"

    def test_has_all_evaluator_types(self):
        registry = OptimizationRegistry.get_instance()
        expected = {"criteria", "comparative", "scored", "human"}
        for name in expected:
            cls = registry.get_evaluator_class(name)
            assert cls is not None, f"Missing evaluator: {name}"

    def test_prompt_optimizer_class(self):
        from temper_ai.optimization.optimizers.prompt import PromptOptimizer

        registry = OptimizationRegistry.get_instance()
        assert registry.get_optimizer_class("prompt") is PromptOptimizer


class TestPipelineWithPromptStep:
    """Test the engine pipeline with a 'prompt' optimizer step."""

    def setup_method(self):
        OptimizationRegistry.reset_for_testing()

    def test_pipeline_config_accepts_prompt(self):
        """PipelineStepConfig validates 'prompt' optimizer type."""
        step = PipelineStepConfig(optimizer="prompt", evaluator="quality")
        assert step.optimizer == "prompt"

    def test_engine_invokes_prompt_optimizer(self):
        """Engine correctly invokes PromptOptimizer via registry."""
        from temper_ai.optimization.optimizers.prompt import PromptOptimizer

        # Register a mock evaluator
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = MagicMock(
            passed=True,
            score=1.0,
        )

        config = OptimizationConfig(
            evaluators={"quality": EvaluatorConfig(type="criteria")},
            pipeline=[
                PipelineStepConfig(optimizer="prompt", evaluator="quality"),
            ],
        )

        # Mock the registry so prompt optimizer is a mock
        mock_optimizer = MagicMock(spec=PromptOptimizer)
        mock_optimizer.optimize.return_value = OptimizationResult(
            output={"result": "optimized"},
            improved=True,
            score=0.95,
        )

        registry = OptimizationRegistry.get_instance()
        registry.register_optimizer("prompt", lambda **kw: mock_optimizer)

        engine = OptimizationEngine(
            config=config,
            registry=registry,
        )
        # Build evaluator manually since config has mock
        engine._evaluator_instances["quality"] = mock_evaluator

        runner = MagicMock()
        result = engine.run(runner, {"input": "test"})

        assert result.output == {"result": "optimized"}
        assert result.improved

    def test_optimization_result_fields(self):
        """OptimizationResult has all expected fields."""
        result = OptimizationResult(
            output={"test": True},
            score=0.9,
            iterations=2,
            improved=True,
            details={"status": "compiled"},
            experiment_id="exp-1",
        )
        assert result.output == {"test": True}
        assert result.score == 0.9
        assert result.improved
        assert result.experiment_id == "exp-1"
