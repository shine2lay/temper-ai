"""Tests for ScoredEvaluator."""

import pytest
from unittest.mock import MagicMock

from temper_ai.optimization._schemas import EvaluatorConfig
from temper_ai.optimization.evaluators.scored import ScoredEvaluator


class TestScoredEvaluator:
    def test_valid_score(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "0.85"
        config = EvaluatorConfig(type="scored", rubric="Rate quality")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.evaluate({"output": "test"})

        assert result.passed is True
        assert result.score == pytest.approx(0.85)

    def test_low_score_fails(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "0.3"
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
        assert result.score == pytest.approx(0.3)

    def test_score_with_text(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "I'd rate this 0.7 out of 1.0"
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.evaluate({"output": "test"})

        assert result.score == pytest.approx(0.7)

    def test_invalid_response(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "I cannot rate this"
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.evaluate({"output": "test"})

        assert result.score == 0.0
        assert result.passed is False

    def test_no_llm(self):
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=None)

        result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
        assert result.score == 0.0

    def test_compare_by_score(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = ["0.9", "0.4"]
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == -1

    def test_score_clamped_to_1(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "5.0"
        config = EvaluatorConfig(type="scored")
        evaluator = ScoredEvaluator(config=config, llm=mock_llm)

        result = evaluator.evaluate({"output": "test"})

        assert result.score == 1.0
