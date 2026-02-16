"""Tests for SelectionOptimizer."""

import pytest
from unittest.mock import MagicMock

from src.improvement._schemas import EvaluationResult
from src.improvement.optimizers.selection import SelectionOptimizer


class TestSelectionOptimizer:
    def _make_evaluator(self, results):
        evaluator = MagicMock()
        evaluator.evaluate.side_effect = results
        return evaluator

    def test_best_of_n(self):
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "v1"},
            {"result": "v2"},
            {"result": "v3"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.3),
            EvaluationResult(passed=False, score=0.8),
            EvaluationResult(passed=False, score=0.5),
        ])
        optimizer = SelectionOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"runs": 3}  # noqa
        )

        assert result.output == {"result": "v2"}
        assert result.score == pytest.approx(0.8)
        assert result.details["scores"] == [0.3, 0.8, 0.5]

    def test_early_stop_on_pass(self):
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "v1"},
            {"result": "v2"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.3),
            EvaluationResult(passed=True, score=0.9),
        ])
        optimizer = SelectionOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"runs": 5}  # noqa
        )

        assert result.output == {"result": "v2"}
        assert runner.execute.call_count == 2  # noqa

    def test_all_equal(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "same"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.5),
            EvaluationResult(passed=False, score=0.5),
        ])
        optimizer = SelectionOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"runs": 2}  # noqa
        )

        assert result.score == pytest.approx(0.5)

    def test_single_run(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "only"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=True, score=0.7),
        ])
        optimizer = SelectionOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"runs": 1}
        )

        assert result.output == {"result": "only"}
        assert runner.execute.call_count == 1
