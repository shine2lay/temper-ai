"""Tests for agent reasoning/planning pass (R0.7)."""

from unittest.mock import MagicMock, Mock

import pytest

from temper_ai.agent.reasoning import (
    _DEFAULT_PLANNING_TEMPLATE,
    _PLAN_SECTION_END,
    _PLAN_SECTION_START,
    build_planning_prompt,
    inject_plan_into_prompt,
    run_planning_pass,
)
from temper_ai.storage.schemas.agent_config import ReasoningConfig


@pytest.fixture
def default_config():
    """ReasoningConfig with defaults."""
    return ReasoningConfig(enabled=True)


@pytest.fixture
def custom_config():
    """ReasoningConfig with a custom planning prompt."""
    return ReasoningConfig(
        enabled=True,
        planning_prompt="Think step by step about: {prompt}",
        inject_as="system_prefix",
        max_planning_tokens=512,
        temperature=0.3,
    )


class TestBuildPlanningPrompt:
    """Tests for build_planning_prompt."""

    def test_default_template(self, default_config):
        """Should use the default template when no custom prompt is set."""
        result = build_planning_prompt("Solve X", default_config)
        expected = _DEFAULT_PLANNING_TEMPLATE.format(prompt="Solve X")
        assert result == expected

    def test_custom_template(self, custom_config):
        """Should substitute {prompt} in custom planning_prompt."""
        result = build_planning_prompt("Solve X", custom_config)
        assert result == "Think step by step about: Solve X"

    def test_empty_prompt(self, default_config):
        """Should handle empty prompt gracefully."""
        result = build_planning_prompt("", default_config)
        assert "{prompt}" not in result


class TestRunPlanningPass:
    """Tests for run_planning_pass."""

    def test_successful_planning(self, default_config):
        """Should return plan text on successful LLM call."""
        mock_service = MagicMock()
        mock_response = Mock(content="Step 1: Do X\nStep 2: Do Y")
        mock_service.llm.complete.return_value = mock_response

        result = run_planning_pass(mock_service, "Solve X", default_config)

        assert result == "Step 1: Do X\nStep 2: Do Y"
        mock_service.llm.complete.assert_called_once()

    def test_empty_response(self, default_config):
        """Should return None when LLM returns empty content."""
        mock_service = MagicMock()
        mock_response = Mock(content="")
        mock_service.llm.complete.return_value = mock_response

        result = run_planning_pass(mock_service, "Solve X", default_config)

        assert result is None

    def test_whitespace_only_response(self, default_config):
        """Should return None when LLM returns whitespace-only content."""
        mock_service = MagicMock()
        mock_response = Mock(content="   \n  ")
        mock_service.llm.complete.return_value = mock_response

        result = run_planning_pass(mock_service, "Solve X", default_config)

        assert result is None

    def test_llm_failure(self, default_config):
        """Should return None on LLM failure."""
        mock_service = MagicMock()
        mock_service.llm.complete.side_effect = RuntimeError("LLM error")

        result = run_planning_pass(mock_service, "Solve X", default_config)

        assert result is None

    def test_custom_temperature(self, custom_config):
        """Should pass custom temperature to LLM."""
        mock_service = MagicMock()
        mock_response = Mock(content="Plan here")
        mock_service.llm.complete.return_value = mock_response

        run_planning_pass(mock_service, "Solve X", custom_config)

        call_kwargs = mock_service.llm.complete.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["max_tokens"] == 512

    def test_response_without_content_attr(self, default_config):
        """Should handle response without content attribute."""
        mock_service = MagicMock()
        mock_response = Mock(spec=[])  # No content attribute
        mock_service.llm.complete.return_value = mock_response

        result = run_planning_pass(mock_service, "Solve X", default_config)

        assert result is None


class TestInjectPlanIntoPrompt:
    """Tests for inject_plan_into_prompt."""

    def test_context_section_mode(self):
        """Should append plan as context section."""
        result = inject_plan_into_prompt("Original", "The plan", "context_section")
        assert result.startswith("Original")
        assert _PLAN_SECTION_START in result
        assert "The plan" in result
        assert _PLAN_SECTION_END in result

    def test_system_prefix_mode(self):
        """Should prepend plan before original prompt."""
        result = inject_plan_into_prompt("Original", "The plan", "system_prefix")
        assert result.startswith("The plan")
        assert result.endswith("Original")

    def test_unknown_mode_defaults_to_context(self):
        """Unknown inject_as should fall back to context_section."""
        result = inject_plan_into_prompt("Original", "The plan", "unknown")
        assert _PLAN_SECTION_START in result
