"""Shared fixtures for plugin tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from temper_ai.plugins.constants import PLUGIN_TYPE_CREWAI


def _make_agent_config_inner(**overrides: Any) -> MagicMock:
    """Create a mock AgentConfigInner with plugin defaults."""
    inner = MagicMock()
    inner.name = overrides.get("name", "test-agent")
    inner.description = overrides.get("description", "Test agent")
    inner.version = overrides.get("version", "1.0")
    inner.type = overrides.get("type", PLUGIN_TYPE_CREWAI)
    inner.plugin_config = overrides.get(
        "plugin_config",
        {
            "framework": PLUGIN_TYPE_CREWAI,
            "role": "Researcher",
            "goal": "Research things",
            "backstory": "Expert researcher",
        },
    )
    inner.script = None
    inner.inference = None
    inner.prompt = None
    return inner


def _make_agent_config(**overrides: Any) -> MagicMock:
    """Create a mock AgentConfig wrapping AgentConfigInner."""
    config = MagicMock()
    config.agent = _make_agent_config_inner(**overrides)
    return config


@pytest.fixture()
def mock_agent_config() -> MagicMock:
    """Fixture: mock AgentConfig for plugin tests."""
    return _make_agent_config()


@pytest.fixture()
def crewai_plugin_config() -> dict[str, Any]:
    """Fixture: CrewAI plugin config dict."""
    return {
        "framework": PLUGIN_TYPE_CREWAI,
        "role": "Researcher",
        "goal": "Research topics thoroughly",
        "backstory": "Expert researcher with years of experience",
        "allow_delegation": False,
        "verbose": False,
    }
