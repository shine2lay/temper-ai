"""Tests for workflow planning pass (R0.8)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.planning import (
    PlanningConfig,
    build_planning_prompt,
    generate_workflow_plan,
)


# ─── PlanningConfig tests ────────────────────────────────────────────


class TestPlanningConfig:
    """Tests for PlanningConfig defaults and validation."""

    def test_default_disabled(self) -> None:
        config = PlanningConfig()
        assert config.enabled is False

    def test_default_model(self) -> None:
        config = PlanningConfig()
        assert config.model == "gpt-4o-mini"

    def test_default_provider(self) -> None:
        config = PlanningConfig()
        assert config.provider == "openai"

    def test_default_temperature(self) -> None:
        config = PlanningConfig()
        assert config.temperature == 0.3

    def test_default_max_tokens(self) -> None:
        config = PlanningConfig()
        assert config.max_tokens == 2048

    def test_temperature_validation_min(self) -> None:
        with pytest.raises(ValueError):
            PlanningConfig(temperature=-0.1)

    def test_temperature_validation_max(self) -> None:
        with pytest.raises(ValueError):
            PlanningConfig(temperature=2.1)

    def test_max_tokens_validation(self) -> None:
        with pytest.raises(ValueError):
            PlanningConfig(max_tokens=0)

    def test_custom_values(self) -> None:
        config = PlanningConfig(
            enabled=True,
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=4096,
        )
        assert config.enabled is True
        assert config.provider == "ollama"
        assert config.model == "llama3"
        assert config.base_url == "http://localhost:11434"


# ─── build_planning_prompt tests ─────────────────────────────────────


class TestBuildPlanningPrompt:
    """Tests for build_planning_prompt."""

    def test_basic_prompt(self) -> None:
        workflow_config = {
            "workflow": {
                "name": "test-workflow",
                "description": "A test workflow",
                "stages": [
                    {"name": "research"},
                    {"name": "analysis"},
                ],
            }
        }
        inputs = {"query": "test query", "count": 5}

        prompt = build_planning_prompt(workflow_config, inputs)

        assert "test-workflow" in prompt
        assert "A test workflow" in prompt
        assert "research" in prompt
        assert "analysis" in prompt
        assert "test query" in prompt

    def test_empty_stages(self) -> None:
        workflow_config = {
            "workflow": {
                "name": "empty-wf",
                "stages": [],
            }
        }
        prompt = build_planning_prompt(workflow_config, {})
        assert "empty-wf" in prompt

    def test_empty_inputs(self) -> None:
        workflow_config = {
            "workflow": {
                "name": "no-input",
                "stages": [{"name": "step1"}],
            }
        }
        prompt = build_planning_prompt(workflow_config, {})
        assert "(none)" in prompt

    def test_non_scalar_inputs_excluded(self) -> None:
        workflow_config = {
            "workflow": {
                "name": "wf",
                "stages": [{"name": "s1"}],
            }
        }
        inputs = {
            "scalar": "hello",
            "nested": {"key": "value"},
            "list_val": [1, 2, 3],
        }
        prompt = build_planning_prompt(workflow_config, inputs)
        assert "hello" in prompt
        # Nested dict and list should be excluded
        assert "nested" not in prompt
        assert "list_val" not in prompt

    def test_missing_workflow_key(self) -> None:
        prompt = build_planning_prompt({}, {})
        assert "unknown" in prompt


# ─── generate_workflow_plan tests ─────────────────────────────────────


class TestGenerateWorkflowPlan:
    """Tests for generate_workflow_plan."""

    def test_returns_none_when_disabled(self) -> None:
        config = PlanningConfig(enabled=False)
        result = generate_workflow_plan({}, {}, config)
        assert result is None

    @patch("temper_ai.agent.llm.create_llm_provider")
    def test_calls_llm_when_enabled(self, mock_create: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Step 1: Do research\nStep 2: Analyze"
        mock_llm.complete.return_value = mock_response
        mock_create.return_value = mock_llm

        config = PlanningConfig(enabled=True)
        workflow_config = {
            "workflow": {
                "name": "test",
                "stages": [{"name": "s1"}],
            }
        }
        result = generate_workflow_plan(workflow_config, {}, config)

        assert result is not None
        assert "Step 1" in result
        mock_create.assert_called_once()
        call_args = mock_create.call_args[0][0]
        assert call_args.provider == "openai"
        assert call_args.model == "gpt-4o-mini"
        mock_llm.complete.assert_called_once()

    @patch(
        "temper_ai.agent.llm.create_llm_provider",
        side_effect=ImportError("no module"),
    )
    def test_handles_import_error(self, mock_create: MagicMock) -> None:
        config = PlanningConfig(enabled=True)
        result = generate_workflow_plan({}, {}, config)
        assert result is None

    @patch(
        "temper_ai.agent.llm.create_llm_provider",
        side_effect=RuntimeError("connection failed"),
    )
    def test_handles_runtime_error(self, mock_create: MagicMock) -> None:
        config = PlanningConfig(enabled=True)
        result = generate_workflow_plan({}, {}, config)
        assert result is None

    @patch(
        "temper_ai.agent.llm.create_llm_provider",
        side_effect=ConnectionError("timeout"),
    )
    def test_handles_connection_error(self, mock_create: MagicMock) -> None:
        config = PlanningConfig(enabled=True)
        result = generate_workflow_plan({}, {}, config)
        assert result is None

    @patch(
        "temper_ai.agent.llm.create_llm_provider",
        side_effect=ValueError("bad config"),
    )
    def test_handles_value_error(self, mock_create: MagicMock) -> None:
        config = PlanningConfig(enabled=True)
        result = generate_workflow_plan({}, {}, config)
        assert result is None

    @patch("temper_ai.agent.llm.create_llm_provider")
    def test_strips_whitespace_from_plan(self, mock_create: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "  Plan with whitespace  \n  "
        mock_llm.complete.return_value = mock_response
        mock_create.return_value = mock_llm

        config = PlanningConfig(enabled=True)
        result = generate_workflow_plan(
            {"workflow": {"name": "t", "stages": []}}, {}, config
        )

        assert result == "Plan with whitespace"

    @patch("temper_ai.agent.llm.create_llm_provider")
    def test_passes_temperature_and_max_tokens(
        self, mock_create: MagicMock
    ) -> None:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "plan"
        mock_llm.complete.return_value = mock_response
        mock_create.return_value = mock_llm

        config = PlanningConfig(
            enabled=True, temperature=0.5, max_tokens=1024
        )
        generate_workflow_plan(
            {"workflow": {"name": "t", "stages": []}}, {}, config
        )

        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args
        assert call_kwargs.kwargs["temperature"] == 0.5
        assert call_kwargs.kwargs["max_tokens"] == 1024
