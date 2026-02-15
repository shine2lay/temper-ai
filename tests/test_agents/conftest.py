"""Shared fixtures for agent tests."""
import pytest

from src.llm.providers.base import BaseLLM
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


@pytest.fixture(autouse=True)
def _reset_shared_circuit_breakers():
    """Reset shared circuit breakers between tests to prevent cross-test interference."""
    BaseLLM.reset_shared_circuit_breakers()
    yield
    BaseLLM.reset_shared_circuit_breakers()


@pytest.fixture
def minimal_agent_config():
    """Create minimal agent configuration for testing."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="Test agent for unit tests",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a helpful assistant. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


@pytest.fixture
def agent_config_with_tools():
    """Create agent configuration with tools."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="tool_agent",
            description="Agent with tools",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You have tools available. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=["calculator", "web_scraper"],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )
