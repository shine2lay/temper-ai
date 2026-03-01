"""Tests for workflow planning pass (R0.8)."""

from __future__ import annotations

import pytest

from temper_ai.workflow.planning import (
    PlanningConfig,
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
