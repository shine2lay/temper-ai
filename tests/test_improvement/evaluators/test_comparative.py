"""Tests for ComparativeEvaluator."""

from unittest.mock import MagicMock

from src.improvement._schemas import EvaluatorConfig
from src.improvement.evaluators.comparative import ComparativeEvaluator


class TestComparativeEvaluator:
    def test_a_better(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "A is clearly better"
        config = EvaluatorConfig(type="comparative", prompt="Compare them")
        evaluator = ComparativeEvaluator(config=config, llm=mock_llm)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == -1

    def test_b_better(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "B is the winner"
        config = EvaluatorConfig(type="comparative")
        evaluator = ComparativeEvaluator(config=config, llm=mock_llm)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 1

    def test_tie(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "TIE - both are equal"
        config = EvaluatorConfig(type="comparative")
        evaluator = ComparativeEvaluator(config=config, llm=mock_llm)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 0

    def test_no_llm_returns_tie(self):
        config = EvaluatorConfig(type="comparative")
        evaluator = ComparativeEvaluator(config=config, llm=None)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 0

    def test_llm_error_returns_tie(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM down")
        config = EvaluatorConfig(type="comparative")
        evaluator = ComparativeEvaluator(config=config, llm=mock_llm)

        result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 0

    def test_evaluate_always_passes(self):
        config = EvaluatorConfig(type="comparative")
        evaluator = ComparativeEvaluator(config=config)

        result = evaluator.evaluate({"x": 1})

        assert result.passed is True
        assert result.score == 1.0
