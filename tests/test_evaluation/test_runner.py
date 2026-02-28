"""Tests for PromptTestRunner."""

from unittest.mock import mock_open, patch

import pytest

from temper_ai.evaluation._schemas import (
    TestCase,
    TestCaseValidator,
    TestSuite,
)
from temper_ai.evaluation.constants import STATUS_ERROR, STATUS_FAIL, STATUS_PASS

# Sample agent config dict (simulates yaml.safe_load output)
SAMPLE_AGENT_CONFIG = {
    "agent": {
        "name": "test_agent",
        "prompt": {"inline": "You are a test agent. Input: {{ suggestion_text }}"},
        "inference": {
            "provider": "vllm",
            "model": "test-model",
            "base_url": "http://localhost:8000",
        },
    }
}


def _make_runner():
    """Create a PromptTestRunner with mocked file loading."""
    with patch("builtins.open", mock_open(read_data="")):
        with patch("yaml.safe_load", return_value=SAMPLE_AGENT_CONFIG):
            from temper_ai.evaluation.runner import PromptTestRunner

            return PromptTestRunner("fake_agent.yaml")


class TestRunCasePassesAllValidators:
    def test_all_validators_pass(self):
        runner = _make_runner()
        llm_output = "<answer>\nDECISION: APPROVE\nCONFIDENCE: 0.9\n</answer>"
        answer = "DECISION: APPROVE\nCONFIDENCE: 0.9"

        case = TestCase(
            name="test_pass",
            input_vars={"suggestion_text": "test suggestion"},
            validators=[
                TestCaseValidator(
                    name="has_decision", pattern=r"DECISION:\s*(APPROVE|REJECT)"
                ),
                TestCaseValidator(
                    name="has_confidence", pattern=r"CONFIDENCE:\s*[01]?\.\d+"
                ),
            ],
        )

        with patch.object(runner, "_call_llm", return_value=(llm_output, answer)):
            result = runner.run_case(case)

        assert result.status == STATUS_PASS
        assert result.test_name == "test_pass"
        assert all(v["passed"] for v in result.validator_results)

    def test_pass_result_has_correct_validator_count(self):
        runner = _make_runner()
        answer = "DECISION: APPROVE\nCONFIDENCE: 0.9"

        case = TestCase(
            name="count_test",
            input_vars={"suggestion_text": "test"},
            validators=[
                TestCaseValidator(name="has_decision", pattern=r"DECISION:"),
                TestCaseValidator(name="has_confidence", pattern=r"CONFIDENCE:"),
            ],
        )

        with patch.object(runner, "_call_llm", return_value=("raw", answer)):
            result = runner.run_case(case)

        assert len(result.validator_results) == 2  # noqa: PLR2004


class TestRunCaseFailsMissingField:
    def test_missing_field_fails(self):
        runner = _make_runner()
        answer = "DECISION: APPROVE"  # missing CONFIDENCE

        case = TestCase(
            name="test_fail",
            input_vars={"suggestion_text": "test"},
            validators=[
                TestCaseValidator(
                    name="has_decision", pattern=r"DECISION:\s*(APPROVE|REJECT)"
                ),
                TestCaseValidator(
                    name="has_confidence", pattern=r"CONFIDENCE:\s*[01]?\.\d+"
                ),
            ],
        )

        with patch.object(runner, "_call_llm", return_value=("raw", answer)):
            result = runner.run_case(case)

        assert result.status == STATUS_FAIL
        failed = [v for v in result.validator_results if not v["passed"]]
        assert len(failed) == 1
        assert failed[0]["name"] == "has_confidence"


class TestRunCaseExtractsAnswerTags:
    def test_answer_extraction_used(self):
        runner = _make_runner()
        raw = "Some thinking...\n<answer>\nDECISION: APPROVE\n</answer>"
        answer = "DECISION: APPROVE"

        case = TestCase(
            name="test_extract",
            input_vars={"suggestion_text": "x"},
            validators=[TestCaseValidator(name="has_decision", pattern=r"DECISION:")],
        )

        with patch.object(runner, "_call_llm", return_value=(raw, answer)):
            result = runner.run_case(case)

        assert result.answer_text == answer
        assert result.raw_output == raw


class TestRunCaseErrorOnLLMFailure:
    def test_llm_error_produces_error_status(self):
        runner = _make_runner()

        case = TestCase(
            name="test_error",
            input_vars={"suggestion_text": "x"},
            validators=[TestCaseValidator(name="v1", pattern=r"test")],
        )

        with patch.object(runner, "_call_llm", side_effect=RuntimeError("LLM failed")):
            result = runner.run_case(case)

        assert result.status == STATUS_ERROR
        assert "LLM failed" in result.error

    def test_os_error_produces_error_status(self):
        runner = _make_runner()

        case = TestCase(
            name="test_os_error",
            input_vars={"suggestion_text": "x"},
            validators=[TestCaseValidator(name="v1", pattern=r"test")],
        )

        with patch.object(runner, "_call_llm", side_effect=OSError("File not found")):
            result = runner.run_case(case)

        assert result.status == STATUS_ERROR
        assert result.error is not None


class TestRunSuiteAggregatesResults:
    def test_suite_aggregation(self):
        runner = _make_runner()

        cases = [
            TestCase(
                name="pass_case",
                input_vars={"suggestion_text": "x"},
                validators=[TestCaseValidator(name="v1", pattern=r"OK")],
            ),
            TestCase(
                name="fail_case",
                input_vars={"suggestion_text": "x"},
                validators=[TestCaseValidator(name="v1", pattern=r"MISSING")],
            ),
        ]
        suite = TestSuite(agent_config="fake.yaml", test_cases=cases)

        def fake_call_llm(prompt):
            return "raw", "OK"

        with patch.object(runner, "_call_llm", fake_call_llm):
            result = runner.run_suite(suite)

        assert result.total == 2  # noqa: PLR2004
        assert result.passed == 1
        assert result.failed == 1

    def test_suite_all_errors(self):
        runner = _make_runner()

        cases = [
            TestCase(
                name="error_case",
                input_vars={"suggestion_text": "x"},
                validators=[TestCaseValidator(name="v1", pattern=r"test")],
            ),
        ]
        suite = TestSuite(agent_config="fake.yaml", test_cases=cases)

        with patch.object(runner, "_call_llm", side_effect=RuntimeError("boom")):
            result = runner.run_suite(suite)

        assert result.total == 1
        assert result.errors == 1
        assert result.passed == 0

    def test_suite_has_correct_agent_name(self):
        runner = _make_runner()
        suite = TestSuite(agent_config="fake.yaml", test_cases=[])

        result = runner.run_suite(suite)

        # Agent name comes from stem of config path
        assert result.agent_name == "fake_agent"


class TestValidatorToGuardrailConversion:
    def test_conversion(self):
        runner = _make_runner()
        answer = "FIELD: value"
        validators = [
            TestCaseValidator(name="has_field", pattern=r"FIELD:", severity="block"),
            TestCaseValidator(
                name="optional_field", pattern=r"OPTIONAL:", severity="warn"
            ),
        ]
        results, status = runner._validate_output(answer, validators)

        assert len(results) == 2  # noqa: PLR2004
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False
        assert status == STATUS_PASS  # warn doesn't block

    def test_block_severity_causes_fail_status(self):
        runner = _make_runner()
        answer = "no match here"
        validators = [
            TestCaseValidator(
                name="required_field", pattern=r"REQUIRED:", severity="block"
            ),
        ]
        results, status = runner._validate_output(answer, validators)

        assert results[0]["passed"] is False
        assert status == STATUS_FAIL

    def test_empty_validators_returns_pass(self):
        runner = _make_runner()
        results, status = runner._validate_output("any text", [])

        assert results == []
        assert status == STATUS_PASS


class TestRenderPrompt:
    def test_template_rendering(self):
        runner = _make_runner()
        case = TestCase(
            name="render_test",
            input_vars={"suggestion_text": "Add dark mode"},
            validators=[],
        )
        rendered = runner._render_prompt(case)
        assert "Add dark mode" in rendered

    def test_template_replaces_all_vars(self):
        runner = _make_runner()
        # Override prompt template to use two vars
        runner._prompt_template = "Input: {{ x }} and {{ y }}"
        case = TestCase(
            name="two_vars",
            input_vars={"x": "hello", "y": "world"},
            validators=[],
        )
        rendered = runner._render_prompt(case)
        assert "hello" in rendered
        assert "world" in rendered


class TestRunCaseWarnSeverityDoesNotFail:
    def test_warn_only_passes(self):
        runner = _make_runner()
        answer = "REQUIRED: yes"

        case = TestCase(
            name="warn_only",
            input_vars={"suggestion_text": "x"},
            validators=[
                TestCaseValidator(
                    name="required", pattern=r"REQUIRED:", severity="block"
                ),
                TestCaseValidator(
                    name="nice_to_have", pattern=r"NICE:", severity="warn"
                ),
            ],
        )

        with patch.object(runner, "_call_llm", return_value=("raw", answer)):
            result = runner.run_case(case)

        assert result.status == STATUS_PASS


class TestCallLlm:
    """Tests for _call_llm to cover lines 98-107."""

    def test_call_llm_returns_raw_and_answer(self):
        runner = _make_runner()
        mock_result = type("R", (), {"output": "raw <answer>DECISION: OK</answer>"})()
        mock_llm = object()
        mock_svc = type("S", (), {"run": lambda self, p: mock_result})()

        with (
            patch(
                "temper_ai.llm.providers.factory.create_llm_from_config",
                return_value=mock_llm,
            ),
            patch(
                "temper_ai.llm.service.LLMService",
                return_value=mock_svc,
            ),
            patch(
                "temper_ai.llm.response_parser.extract_final_answer",
                return_value="DECISION: OK",
            ),
        ):
            raw, answer = runner._call_llm("test prompt")

        assert raw == "raw <answer>DECISION: OK</answer>"
        assert answer == "DECISION: OK"

    def test_call_llm_extracts_answer_text(self):
        runner = _make_runner()
        mock_result = type("R", (), {"output": "hello world"})()
        mock_svc = type("S", (), {"run": lambda self, p: mock_result})()

        with (
            patch(
                "temper_ai.llm.providers.factory.create_llm_from_config",
            ),
            patch(
                "temper_ai.llm.service.LLMService",
                return_value=mock_svc,
            ),
            patch(
                "temper_ai.llm.response_parser.extract_final_answer",
                return_value="extracted",
            ) as mock_extract,
        ):
            raw, answer = runner._call_llm("prompt")

        assert answer == "extracted"
        mock_extract.assert_called_once_with("hello world")


class TestEvaluationLazyImport:
    """Tests for temper_ai.evaluation.__init__ lazy import (lines 20-24)."""

    def test_lazy_import_prompt_test_runner(self):
        import temper_ai.evaluation as mod

        cls = mod.__getattr__("PromptTestRunner")
        from temper_ai.evaluation.runner import PromptTestRunner

        assert cls is PromptTestRunner

    def test_lazy_import_unknown_raises(self):
        import temper_ai.evaluation as mod

        with pytest.raises(AttributeError, match="no attribute"):
            mod.__getattr__("NonExistentClass")


class TestRunnerInit:
    def test_loads_config_and_extracts_prompt(self):
        runner = _make_runner()
        assert (
            "test agent" in runner._prompt_template.lower()
            or "suggestion_text" in runner._prompt_template
        )
        assert runner._inference_config is not None

    def test_missing_file_raises(self):
        from temper_ai.evaluation.runner import PromptTestRunner

        with pytest.raises(OSError):
            PromptTestRunner("/nonexistent/path.yaml")

    def test_config_path_stored(self):
        runner = _make_runner()
        assert runner._config_path == "fake_agent.yaml"

    def test_inference_config_has_provider(self):
        runner = _make_runner()
        assert runner._inference_config.provider == "vllm"
