"""Tests for prompt-test CLI commands."""
import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from temper_ai.interfaces.cli.prompt_test_commands import prompt_test_group


@pytest.fixture
def cli_runner():
    return CliRunner()


class TestListCommand:
    def test_list_shows_suites(self, cli_runner, tmp_path):
        suite_file = tmp_path / "test_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/test.yaml\n"
            "test_cases:\n"
            "  - name: t1\n"
            "    input_vars:\n"
            "      x: y\n"
            "    validators: []\n"
        )

        result = cli_runner.invoke(prompt_test_group, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "test_suite.yaml" in result.output

    def test_list_empty_dir(self, cli_runner, tmp_path):
        result = cli_runner.invoke(prompt_test_group, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No test suite files found" in result.output

    def test_list_shows_agent_config(self, cli_runner, tmp_path):
        suite_file = tmp_path / "my_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/vcs_triage_decider.yaml\n"
            "test_cases: []\n"
        )

        result = cli_runner.invoke(prompt_test_group, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "vcs_triage_decider.yaml" in result.output

    def test_list_multiple_files(self, cli_runner, tmp_path):
        for name in ("suite_a.yaml", "suite_b.yaml"):
            (tmp_path / name).write_text(
                "agent_config: test.yaml\ntest_cases: []\n"
            )

        result = cli_runner.invoke(prompt_test_group, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "suite_a.yaml" in result.output
        assert "suite_b.yaml" in result.output


class TestRunCommand:
    def test_run_with_valid_suite(self, cli_runner, tmp_path):
        suite_file = tmp_path / "test_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/vcs_triage_decider.yaml\n"
            "test_cases:\n"
            "  - name: test1\n"
            "    input_vars:\n"
            "      suggestion_text: test\n"
            "      team_outputs: test\n"
            "    validators:\n"
            "      - name: has_decision\n"
            "        pattern: 'DECISION:'\n"
        )

        from temper_ai.evaluation._schemas import SuiteResult, TestResult
        mock_result = SuiteResult(
            agent_name="test",
            agent_config="test.yaml",
            total=1,
            passed=1,
            failed=0,
            errors=0,
            results=[TestResult(test_name="test1", status="PASS", duration_seconds=1.0)],
            duration_seconds=1.0,
        )

        mock_runner = MagicMock()
        mock_runner.run_suite.return_value = mock_result

        with patch(
            "temper_ai.evaluation.runner.PromptTestRunner",
            return_value=mock_runner,
        ):
            result = cli_runner.invoke(prompt_test_group, ["run", str(suite_file)])

        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_run_with_failures_exits_1(self, cli_runner, tmp_path):
        suite_file = tmp_path / "test_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/vcs_triage_decider.yaml\n"
            "test_cases:\n"
            "  - name: test1\n"
            "    input_vars:\n"
            "      suggestion_text: test\n"
            "      team_outputs: test\n"
            "    validators:\n"
            "      - name: has_decision\n"
            "        pattern: 'DECISION:'\n"
        )

        from temper_ai.evaluation._schemas import SuiteResult, TestResult
        mock_result = SuiteResult(
            agent_name="test",
            agent_config="test.yaml",
            total=1,
            passed=0,
            failed=1,
            errors=0,
            results=[
                TestResult(
                    test_name="test1",
                    status="FAIL",
                    duration_seconds=1.0,
                    validator_results=[
                        {
                            "name": "has_decision",
                            "passed": False,
                            "severity": "block",
                            "message": "not found",
                        }
                    ],
                )
            ],
            duration_seconds=1.0,
        )

        mock_runner = MagicMock()
        mock_runner.run_suite.return_value = mock_result

        with patch(
            "temper_ai.evaluation.runner.PromptTestRunner",
            return_value=mock_runner,
        ):
            result = cli_runner.invoke(prompt_test_group, ["run", str(suite_file)])

        assert result.exit_code == 1

    def test_run_invalid_file(self, cli_runner):
        result = cli_runner.invoke(prompt_test_group, ["run", "/nonexistent.yaml"])
        assert result.exit_code == 1

    def test_run_verbose_shows_output(self, cli_runner, tmp_path):
        suite_file = tmp_path / "test_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/test.yaml\n"
            "test_cases:\n"
            "  - name: test1\n"
            "    input_vars:\n"
            "      x: y\n"
            "    validators:\n"
            "      - name: v1\n"
            "        pattern: 'test'\n"
        )

        from temper_ai.evaluation._schemas import SuiteResult, TestResult
        mock_result = SuiteResult(
            agent_name="test",
            agent_config="test.yaml",
            total=1,
            passed=1,
            failed=0,
            errors=0,
            results=[
                TestResult(
                    test_name="test1",
                    status="PASS",
                    duration_seconds=1.0,
                    raw_output="some raw output",
                    answer_text="extracted answer",
                )
            ],
            duration_seconds=1.0,
        )

        mock_runner = MagicMock()
        mock_runner.run_suite.return_value = mock_result

        with patch(
            "temper_ai.evaluation.runner.PromptTestRunner",
            return_value=mock_runner,
        ):
            result = cli_runner.invoke(
                prompt_test_group, ["run", str(suite_file), "-v"]
            )

        assert result.exit_code == 0
        assert "Raw Output" in result.output
        assert "Extracted Answer" in result.output

    def test_run_errors_exits_1(self, cli_runner, tmp_path):
        suite_file = tmp_path / "test_suite.yaml"
        suite_file.write_text(
            "agent_config: configs/agents/test.yaml\n"
            "test_cases:\n"
            "  - name: error_case\n"
            "    input_vars:\n"
            "      x: y\n"
            "    validators:\n"
            "      - name: v1\n"
            "        pattern: 'test'\n"
        )

        from temper_ai.evaluation._schemas import SuiteResult, TestResult
        mock_result = SuiteResult(
            agent_name="test",
            agent_config="test.yaml",
            total=1,
            passed=0,
            failed=0,
            errors=1,
            results=[
                TestResult(
                    test_name="error_case",
                    status="ERROR",
                    duration_seconds=0.1,
                    error="LLM timeout",
                )
            ],
            duration_seconds=0.1,
        )

        mock_runner = MagicMock()
        mock_runner.run_suite.return_value = mock_result

        with patch(
            "temper_ai.evaluation.runner.PromptTestRunner",
            return_value=mock_runner,
        ):
            result = cli_runner.invoke(prompt_test_group, ["run", str(suite_file)])

        assert result.exit_code == 1
