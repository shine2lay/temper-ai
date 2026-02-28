"""Targeted tests for agent/_r0_pipeline_helpers.py to improve coverage from 27% to 90%+.

Covers: apply_reasoning, apply_context_management, validate_and_retry_output,
        avalidate_and_retry_output, apply_guardrails, aapply_guardrails.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.agent._r0_pipeline_helpers import (
    aapply_guardrails,
    apply_context_management,
    apply_guardrails,
    apply_reasoning,
    avalidate_and_retry_output,
    validate_and_retry_output,
)

# ---------------------------------------------------------------------------
# apply_reasoning
# ---------------------------------------------------------------------------


class TestApplyReasoning:
    def test_injects_plan_into_prompt(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.reasoning.inject_as = "prefix"

        with patch(
            "temper_ai.agent.reasoning.run_planning_pass",
            return_value="step1. do this\nstep2. do that",
        ):
            with patch(
                "temper_ai.agent.reasoning.inject_plan_into_prompt",
                return_value="[PLAN]\nstep1. do this\nstep2. do that\n\nPrompt",
            ):
                result = apply_reasoning(mock_svc, cfg, "Prompt")

        assert (
            "step1" in result
            or result == "[PLAN]\nstep1. do this\nstep2. do that\n\nPrompt"
        )

    def test_returns_original_when_no_plan(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.reasoning.inject_as = "prefix"

        with patch(
            "temper_ai.agent.reasoning.run_planning_pass",
            return_value=None,
        ):
            result = apply_reasoning(mock_svc, cfg, "Original Prompt")

        assert result == "Original Prompt"


# ---------------------------------------------------------------------------
# apply_context_management
# ---------------------------------------------------------------------------


class TestApplyContextManagement:
    def test_trims_prompt(self):
        cfg = MagicMock()
        cfg.agent.context_management.max_context_tokens = 100
        cfg.agent.context_management.reserved_output_tokens = 50
        cfg.agent.context_management.strategy = "tail"
        cfg.agent.context_management.token_counter = None

        with patch(
            "temper_ai.llm.context_window.trim_to_budget",
            return_value="trimmed prompt",
        ) as mock_trim:
            result = apply_context_management(cfg, "very long prompt text")

        mock_trim.assert_called_once()
        assert result == "trimmed prompt"

    def test_uses_default_context_when_max_tokens_none(self):
        cfg = MagicMock()
        cfg.agent.context_management.max_context_tokens = None
        cfg.agent.context_management.reserved_output_tokens = 512
        cfg.agent.context_management.strategy = "middle"
        cfg.agent.context_management.token_counter = None

        with patch(
            "temper_ai.llm.context_window.trim_to_budget",
            return_value="trimmed",
        ) as mock_trim:
            apply_context_management(cfg, "prompt")

        call_args = mock_trim.call_args
        # Second arg is max_tokens — should use DEFAULT_MODEL_CONTEXT
        from temper_ai.llm.context_window import DEFAULT_MODEL_CONTEXT

        assert call_args[0][1] == DEFAULT_MODEL_CONTEXT


# ---------------------------------------------------------------------------
# validate_and_retry_output
# ---------------------------------------------------------------------------


class TestValidateAndRetryOutput:
    def test_returns_result_when_no_schema(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_schema = None
        result = MagicMock()

        output = validate_and_retry_output(mock_svc, cfg, result, "prompt", {})
        assert output is result

    def test_returns_result_when_no_json_schema(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = None
        result = MagicMock()

        output = validate_and_retry_output(mock_svc, cfg, result, "prompt", {})
        assert output is result

    def test_returns_result_on_first_valid(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = {"type": "object"}
        cfg.agent.output_schema.max_retries = 3
        result = MagicMock()
        result.output = '{"key": "value"}'

        with patch(
            "temper_ai.llm.output_validation.validate_output_against_schema",
            return_value=(True, None),
        ):
            output = validate_and_retry_output(mock_svc, cfg, result, "prompt", {})

        assert output is result
        mock_svc.run.assert_not_called()

    def test_retries_on_invalid_output(self):
        mock_svc = MagicMock()
        fixed_result = MagicMock()
        fixed_result.output = '{"key": "fixed"}'
        mock_svc.run.return_value = fixed_result

        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = {"type": "object"}
        cfg.agent.output_schema.max_retries = 2
        result = MagicMock()
        result.output = "not valid json"

        with patch(
            "temper_ai.llm.output_validation.validate_output_against_schema",
            side_effect=[(False, "Invalid JSON"), (True, None)],
        ):
            with patch(
                "temper_ai.llm.output_validation.build_retry_prompt_with_error",
                return_value="retry prompt",
            ):
                validate_and_retry_output(
                    mock_svc, cfg, result, "prompt", {"prompt": "old"}
                )

        mock_svc.run.assert_called_once()

    def test_returns_last_result_after_max_retries(self):
        last_result = MagicMock()
        last_result.output = "still invalid"
        mock_svc = MagicMock()
        mock_svc.run.return_value = last_result

        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = {"type": "object"}
        cfg.agent.output_schema.max_retries = 2
        result = MagicMock()
        result.output = "invalid"

        with patch(
            "temper_ai.llm.output_validation.validate_output_against_schema",
            return_value=(False, "error"),
        ):
            with patch(
                "temper_ai.llm.output_validation.build_retry_prompt_with_error",
                return_value="retry prompt",
            ):
                output = validate_and_retry_output(mock_svc, cfg, result, "prompt", {})

        # Returns last result (which may be invalid)
        assert output is not None


# ---------------------------------------------------------------------------
# avalidate_and_retry_output
# ---------------------------------------------------------------------------


class TestAValidateAndRetryOutput:
    @pytest.mark.asyncio
    async def test_returns_result_when_no_schema(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_schema = None
        result = MagicMock()

        output = await avalidate_and_retry_output(mock_svc, cfg, result, "prompt", {})
        assert output is result

    @pytest.mark.asyncio
    async def test_returns_result_on_valid(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = {"type": "object"}
        cfg.agent.output_schema.max_retries = 2
        result = MagicMock()
        result.output = '{"key": "value"}'

        with patch(
            "temper_ai.llm.output_validation.validate_output_against_schema",
            return_value=(True, None),
        ):
            output = await avalidate_and_retry_output(
                mock_svc, cfg, result, "prompt", {}
            )

        assert output is result

    @pytest.mark.asyncio
    async def test_retries_async_on_invalid(self):
        fixed_result = MagicMock()
        fixed_result.output = '{"ok": true}'
        mock_svc = MagicMock()
        mock_svc.arun = AsyncMock(return_value=fixed_result)

        cfg = MagicMock()
        cfg.agent.output_schema.json_schema = {"type": "object"}
        cfg.agent.output_schema.max_retries = 2
        result = MagicMock()
        result.output = "bad output"

        with patch(
            "temper_ai.llm.output_validation.validate_output_against_schema",
            side_effect=[(False, "Invalid"), (True, None)],
        ):
            with patch(
                "temper_ai.llm.output_validation.build_retry_prompt_with_error",
                return_value="retry prompt",
            ):
                await avalidate_and_retry_output(mock_svc, cfg, result, "prompt", {})

        mock_svc.arun.assert_called_once()


# ---------------------------------------------------------------------------
# apply_guardrails
# ---------------------------------------------------------------------------


class TestApplyGuardrails:
    def test_passes_when_no_failures(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 3
        cfg.agent.output_guardrails.inject_feedback = True
        cfg.agent.output_guardrails.checks = ["length_check"]
        result = MagicMock()

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[MagicMock(passed=True)],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                return_value=False,
            ):
                output = apply_guardrails(mock_svc, cfg, result, "prompt", {})

        assert output is result
        mock_svc.run.assert_not_called()

    def test_retries_with_feedback_on_failure(self):
        mock_svc = MagicMock()
        fixed_result = MagicMock()
        mock_svc.run.return_value = fixed_result

        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 2
        cfg.agent.output_guardrails.inject_feedback = True
        cfg.agent.output_guardrails.checks = ["toxicity"]
        result = MagicMock()
        failure_mock = MagicMock(passed=False)

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[failure_mock],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                side_effect=[True, False],
            ):
                with patch(
                    "temper_ai.agent.guardrails.build_feedback_injection",
                    return_value="Please fix this.",
                ):
                    apply_guardrails(mock_svc, cfg, result, "prompt", {})

        mock_svc.run.assert_called_once()

    def test_breaks_without_feedback_injection(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 3
        cfg.agent.output_guardrails.inject_feedback = False
        cfg.agent.output_guardrails.checks = ["length"]
        result = MagicMock()

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[MagicMock(passed=False)],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                return_value=True,
            ):
                output = apply_guardrails(mock_svc, cfg, result, "prompt", {})

        # Should break without calling run
        mock_svc.run.assert_not_called()
        assert output is result


# ---------------------------------------------------------------------------
# aapply_guardrails
# ---------------------------------------------------------------------------


class TestAApplyGuardrails:
    @pytest.mark.asyncio
    async def test_passes_when_no_failures(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 2
        cfg.agent.output_guardrails.inject_feedback = True
        cfg.agent.output_guardrails.checks = []
        result = MagicMock()

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                return_value=False,
            ):
                output = await aapply_guardrails(mock_svc, cfg, result, "prompt", {})

        assert output is result

    @pytest.mark.asyncio
    async def test_async_retries_with_feedback(self):
        fixed_result = MagicMock()
        mock_svc = MagicMock()
        mock_svc.arun = AsyncMock(return_value=fixed_result)

        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 2
        cfg.agent.output_guardrails.inject_feedback = True
        cfg.agent.output_guardrails.checks = ["toxicity"]
        result = MagicMock()

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[MagicMock(passed=False)],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                side_effect=[True, False],
            ):
                with patch(
                    "temper_ai.agent.guardrails.build_feedback_injection",
                    return_value="Feedback.",
                ):
                    await aapply_guardrails(mock_svc, cfg, result, "prompt", {})

        mock_svc.arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_breaks_without_feedback(self):
        mock_svc = MagicMock()
        cfg = MagicMock()
        cfg.agent.output_guardrails.max_retries = 3
        cfg.agent.output_guardrails.inject_feedback = False
        cfg.agent.output_guardrails.checks = ["length"]
        result = MagicMock()

        with patch(
            "temper_ai.agent.guardrails.run_guardrail_checks",
            return_value=[MagicMock(passed=False)],
        ):
            with patch(
                "temper_ai.agent.guardrails.has_blocking_failures",
                return_value=True,
            ):
                output = await aapply_guardrails(mock_svc, cfg, result, "prompt", {})

        # No async call made
        assert not hasattr(mock_svc, "arun") or mock_svc.arun.call_count == 0
        assert output is result
