"""Tests for CriteriaEvaluator."""

from unittest.mock import MagicMock, patch

from src.improvement._schemas import CheckConfig, EvaluatorConfig
from src.improvement.evaluators.criteria import CriteriaEvaluator


class TestCriteriaEvaluator:
    def test_no_checks_passes(self):
        config = EvaluatorConfig(type="criteria", checks=[])
        evaluator = CriteriaEvaluator(config=config)
        result = evaluator.evaluate({"output": "test"})
        assert result.passed is True
        assert result.score == 1.0

    def test_all_programmatic_pass(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="check1", method="programmatic", command="true"),
                CheckConfig(name="check2", method="programmatic", command="true"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["checks"]["check1"] is True
        assert result.details["checks"]["check2"] is True

    def test_partial_pass(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="pass_check", method="programmatic", command="true"),
                CheckConfig(name="fail_check", method="programmatic", command="false"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=1),
            ]
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
        assert result.score == 0.5

    def test_all_fail(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="c1", method="programmatic", command="false"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
        assert result.score == 0.0

    def test_subprocess_timeout(self):
        import subprocess

        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="slow", method="programmatic", command="sleep 100"),  # noqa
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 1)):
            result = evaluator.evaluate({"output": "test"})

        assert result.passed is False

    def test_llm_check_yes(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "YES, it looks good."
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="quality", method="llm", prompt="Is it good?"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config, llm=mock_llm)
        result = evaluator.evaluate({"output": "test"})

        assert result.passed is True

    def test_llm_check_no(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "NO, needs work."
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="quality", method="llm", prompt="Is it good?"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config, llm=mock_llm)
        result = evaluator.evaluate({"output": "test"})

        assert result.passed is False

    def test_llm_check_no_llm(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="quality", method="llm", prompt="Is it good?"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config, llm=None)
        result = evaluator.evaluate({"output": "test"})

        assert result.passed is False

    def test_compare_by_score(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="c1", method="programmatic", command="true"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=1),
            ]
            result = evaluator.compare({"a": 1}, {"b": 2})

        assert result == -1

    def test_no_command_fails(self):
        config = EvaluatorConfig(
            type="criteria",
            checks=[
                CheckConfig(name="missing_cmd", method="programmatic"),
            ],
        )
        evaluator = CriteriaEvaluator(config=config)
        result = evaluator.evaluate({"output": "test"})

        assert result.passed is False
