"""Shared fixtures for security tests."""

# Reuse existing agent config fixtures
from tests.test_agent.conftest import agent_config_with_tools, minimal_agent_config

__all__ = ["minimal_agent_config", "agent_config_with_tools"]
