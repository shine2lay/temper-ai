"""Tests for the OptimizationEngine."""

from unittest.mock import MagicMock

import pytest

from temper_ai.optimization._schemas import (
    EvaluatorConfig,
    OptimizationConfig,
    PipelineStepConfig,
)
from temper_ai.optimization.engine import OptimizationEngine
from temper_ai.optimization.registry import OptimizationRegistry


class TestOptimizationEngine:
    def setup_method(self):
        OptimizationRegistry.reset_for_testing()

    def teardown_method(self):
        OptimizationRegistry.reset_for_testing()

    def _make_runner(self, outputs=None):
        runner = MagicMock()
        if outputs:
            runner.execute.side_effect = outputs
        else:
            runner.execute.return_value = {"result": "ok"}
        return runner

    def test_empty_pipeline_falls_through(self):
        config = OptimizationConfig(pipeline=[])
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output == {"result": "ok"}
        runner.execute.assert_called_once()

    def test_disabled_falls_through(self):
        config = OptimizationConfig(
            enabled=False,
            evaluators={"q": EvaluatorConfig()},
            pipeline=[PipelineStepConfig(evaluator="q")],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output == {"result": "ok"}
        runner.execute.assert_called_once()

    def test_single_step_criteria(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="refinement",
                    evaluator="q",
                    max_iterations=1,
                )
            ],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_multi_step_pipeline(self):
        config = OptimizationConfig(
            evaluators={
                "q1": EvaluatorConfig(type="criteria", checks=[]),
                "q2": EvaluatorConfig(type="criteria", checks=[]),
            },
            pipeline=[
                PipelineStepConfig(
                    optimizer="refinement", evaluator="q1", max_iterations=1
                ),
                PipelineStepConfig(
                    optimizer="selection", evaluator="q2", runs=2
                ),  # noqa
            ],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_missing_evaluator_raises(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig()},
            pipeline=[PipelineStepConfig(evaluator="nonexistent")],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        with pytest.raises(KeyError, match="nonexistent"):
            engine.run(runner, {"input": "data"})

    def test_selection_step(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="selection",
                    evaluator="q",
                    runs=3,  # noqa
                )
            ],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_tuning_step_no_service(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="tuning",
                    evaluator="q",
                    strategies=[{"name": "v1"}, {"name": "v2"}],
                )
            ],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_refinement_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "YES"

        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="refinement",
                    evaluator="q",
                    max_iterations=1,
                )
            ],
        )
        engine = OptimizationEngine(config=config, llm=mock_llm)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_experiment_service_passed_to_all_optimizers(self):
        """Verify experiment_service is passed to all optimizer types."""
        mock_service = MagicMock()
        mock_service.create_experiment.return_value = "exp-test"
        mock_service.get_experiment_results.return_value = {
            "recommended_winner": None,
        }
        mock_service.check_early_stopping.return_value = {"should_stop": False}

        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="selection",
                    evaluator="q",
                    runs=1,
                ),
            ],
        )
        engine = OptimizationEngine(config=config, experiment_service=mock_service)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None
        # SelectionOptimizer should have used the experiment service
        mock_service.create_experiment.assert_called_once()
        mock_service.start_experiment.assert_called_once()
        mock_service.assign_variant.assert_called_once()
        mock_service.track_execution_complete.assert_called_once()

    def test_build_optimizer_kwargs_selection(self):
        """_build_optimizer_kwargs passes experiment_service to SelectionOptimizer."""
        from temper_ai.optimization.optimizers.selection import SelectionOptimizer

        mock_service = MagicMock()
        config = OptimizationConfig()
        engine = OptimizationEngine(config=config, experiment_service=mock_service)

        kwargs = engine._build_optimizer_kwargs(SelectionOptimizer)

        assert kwargs["experiment_service"] is mock_service

    def test_build_optimizer_kwargs_refinement(self):
        """_build_optimizer_kwargs passes llm + experiment_service to RefinementOptimizer."""
        from temper_ai.optimization.optimizers.refinement import RefinementOptimizer

        mock_service = MagicMock()
        mock_llm = MagicMock()
        config = OptimizationConfig()
        engine = OptimizationEngine(
            config=config, llm=mock_llm, experiment_service=mock_service
        )

        kwargs = engine._build_optimizer_kwargs(RefinementOptimizer)

        assert kwargs["experiment_service"] is mock_service
        assert kwargs["llm"] is mock_llm

    def test_evaluate_final_with_evaluators(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[
                PipelineStepConfig(
                    optimizer="refinement",
                    evaluator="q",
                    max_iterations=1,
                )
            ],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        # With empty checks, criteria evaluator returns 1.0
        assert result.score == pytest.approx(1.0)
