"""Fixtures for regression tests."""

import pytest

from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


@pytest.fixture
def minimal_agent_config():
    """Minimal valid agent configuration for testing."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="Test agent",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a test agent"),
            inference=InferenceConfig(provider="ollama", model="llama2"),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )
