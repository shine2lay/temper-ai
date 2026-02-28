"""Tests for PromptOptimizer."""

from unittest.mock import MagicMock, patch

from temper_ai.optimization.optimizers.prompt import PromptOptimizer
from temper_ai.optimization.protocols import OptimizerProtocol
from temper_ai.optimization.registry import OptimizationRegistry


class TestPromptOptimizer:

    def test_satisfies_protocol(self):
        """PromptOptimizer satisfies OptimizerProtocol."""
        optimizer = PromptOptimizer()
        assert isinstance(optimizer, OptimizerProtocol)

    def test_missing_agent_name(self):
        """Returns error result when agent_name not provided."""
        optimizer = PromptOptimizer()
        result = optimizer.optimize(
            runner=MagicMock(),
            input_data={"test": "data"},
            evaluator=MagicMock(),
            config={},
        )
        assert not result.improved
        assert "agent_name required" in result.details.get("error", "")

    def test_insufficient_data(self):
        """Returns insufficient_data when not enough examples."""
        optimizer = PromptOptimizer()
        mock_collector = MagicMock()
        mock_collector.collect_examples.return_value = []

        mock_opt_config = MagicMock()
        mock_opt_config.min_training_examples = 10
        mock_opt_config.min_quality_score = 0.7
        mock_opt_config.lookback_hours = 720

        with (
            patch(
                "temper_ai.optimization.optimizers.prompt.TrainingDataCollector",
                return_value=mock_collector,
            ),
            patch(
                "temper_ai.optimization.optimizers.prompt.PromptOptimizationConfig",
                return_value=mock_opt_config,
            ),
        ):
            result = optimizer.optimize(
                runner=MagicMock(),
                input_data={"test": "data"},
                evaluator=MagicMock(),
                config={"agent_name": "researcher", "min_training_examples": 10},
            )
        assert not result.improved
        assert result.details.get("status") == "insufficient_data"

    def test_full_compilation_mocked(self):
        """Full compilation with mocked DSPy classes."""
        optimizer = PromptOptimizer()

        mock_collector = MagicMock()
        mock_examples = [MagicMock() for _ in range(15)]
        mock_collector.collect_examples.return_value = mock_examples

        mock_result = MagicMock()
        mock_result.program_data = {"instruction": "test", "demos": []}
        mock_result.program_id = "prog_1"
        mock_result.optimizer_type = "bootstrap"
        mock_result.val_score = 0.85
        mock_result.num_examples = 15
        mock_result.num_demos = 3

        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = mock_result

        mock_store = MagicMock()

        with (
            patch(
                "temper_ai.optimization.optimizers.prompt.TrainingDataCollector",
                return_value=mock_collector,
            ),
            patch(
                "temper_ai.optimization.optimizers.prompt.DSPyProgramBuilder",
            ),
            patch(
                "temper_ai.optimization.optimizers.prompt.DSPyCompiler",
                return_value=mock_compiler,
            ),
            patch(
                "temper_ai.optimization.optimizers.prompt.CompiledProgramStore",
                return_value=mock_store,
            ),
        ):
            result = optimizer.optimize(
                runner=MagicMock(),
                input_data={"test": "data"},
                evaluator=MagicMock(),
                config={
                    "agent_name": "researcher",
                    "min_training_examples": 10,
                    "provider": "ollama",
                    "model": "qwen3",
                },
            )

        assert result.improved
        assert result.details["status"] == "compiled"
        assert result.details["agent_name"] == "researcher"
        # Verify program_data was saved (not metadata)
        mock_store.save.assert_called_once()
        save_args = mock_store.save.call_args
        assert save_args[1]["program"] == {"instruction": "test", "demos": []}

    def test_registered_in_registry(self):
        """PromptOptimizer accessible via registry."""
        OptimizationRegistry.reset_for_testing()
        registry = OptimizationRegistry()
        cls = registry.get_optimizer_class("prompt")
        assert cls is PromptOptimizer

    def test_pipeline_config_accepts_prompt(self):
        """PipelineStepConfig accepts 'prompt' optimizer type."""
        from temper_ai.optimization._schemas import PipelineStepConfig

        step = PipelineStepConfig(optimizer="prompt", evaluator="quality")
        assert step.optimizer == "prompt"
