"""Tests for the OptimizationEngine."""

from unittest.mock import MagicMock

import pytest

from src.improvement._schemas import (
    EvaluatorConfig,
    OptimizationConfig,
    PipelineStepConfig,
)
from src.improvement.engine import OptimizationEngine
from src.improvement.registry import OptimizationRegistry


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
            pipeline=[PipelineStepConfig(
                optimizer="refinement",
                evaluator="q",
                max_iterations=1,
            )],
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
                PipelineStepConfig(optimizer="refinement", evaluator="q1", max_iterations=1),
                PipelineStepConfig(optimizer="selection", evaluator="q2", runs=2),  # noqa
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
            pipeline=[PipelineStepConfig(
                optimizer="selection",
                evaluator="q",
                runs=3,  # noqa
            )],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_tuning_step_no_service(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[PipelineStepConfig(
                optimizer="tuning",
                evaluator="q",
                strategies=[{"name": "v1"}, {"name": "v2"}],
            )],
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
            pipeline=[PipelineStepConfig(
                optimizer="refinement",
                evaluator="q",
                max_iterations=1,
            )],
        )
        engine = OptimizationEngine(config=config, llm=mock_llm)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        assert result.output is not None

    def test_evaluate_final_with_evaluators(self):
        config = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="criteria", checks=[])},
            pipeline=[PipelineStepConfig(
                optimizer="refinement",
                evaluator="q",
                max_iterations=1,
            )],
        )
        engine = OptimizationEngine(config=config)
        runner = self._make_runner()

        result = engine.run(runner, {"input": "data"})

        # With empty checks, criteria evaluator returns 1.0
        assert result.score == pytest.approx(1.0)
