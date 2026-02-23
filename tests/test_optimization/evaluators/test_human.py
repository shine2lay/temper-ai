"""Tests for HumanEvaluator."""

from unittest.mock import patch

from temper_ai.optimization.evaluators.human import HumanEvaluator


class TestHumanEvaluator:
    def test_approve(self):
        evaluator = HumanEvaluator()
        with patch("click.confirm", return_value=True), patch("click.echo"):
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is True
        assert result.score == 1.0

    def test_reject(self):
        evaluator = HumanEvaluator()
        with patch("click.confirm", return_value=False), patch("click.echo"):
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
        assert result.score == 0.0

    def test_compare_a(self):
        evaluator = HumanEvaluator()
        with patch("click.prompt", return_value="A"), patch("click.echo"):
            result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == -1

    def test_compare_b(self):
        evaluator = HumanEvaluator()
        with patch("click.prompt", return_value="B"), patch("click.echo"):
            result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 1

    def test_compare_tie(self):
        evaluator = HumanEvaluator()
        with patch("click.prompt", return_value="tie"), patch("click.echo"):
            result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == 0
