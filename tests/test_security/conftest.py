"""Shared fixtures for security tests."""
# Reuse existing agent config fixtures
from tests.test_agents.conftest import minimal_agent_config, agent_config_with_tools

__all__ = ['minimal_agent_config', 'agent_config_with_tools']
