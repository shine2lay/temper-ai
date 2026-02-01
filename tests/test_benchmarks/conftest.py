"""Shared fixtures and configuration for performance benchmarks."""

import pytest
import asyncio
import os
from unittest.mock import Mock, MagicMock
from datetime import datetime

from src.compiler.langgraph_compiler import LangGraphCompiler
from src.observability.database import DatabaseManager
from src.agents.llm_providers import LLMResponse
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    PromptConfig,
    InferenceConfig,
    ErrorHandlingConfig,
)


# ============================================================================
# Test Configuration Constants
# ============================================================================

# M3.3-01 Async LLM Speedup Test Configuration
NUM_PARALLEL_CALLS = 3
MIN_SPEEDUP = 1.9
MAX_SPEEDUP = 3.2
TEST_LLM_LATENCY = float(os.getenv("TEST_LLM_LATENCY", "0.05"))

# M3.3-02 Query Reduction Test Configuration
NUM_OPERATIONS = 100
DEFAULT_BATCH_SIZE = 50

# Concurrent Workflow Test Configuration
NUM_CONCURRENT_WORKFLOWS = 10
WORKFLOW_STAGES = 3
WORKFLOW_LLM_LATENCY = float(os.getenv("WORKFLOW_LLM_LATENCY", "0.1"))


# ============================================================================
# Shared Fixtures
# ============================================================================

@pytest.fixture
def simple_workflow_config():
    """Simple workflow configuration for benchmarking."""
    return {
        "workflow": {
            "name": "simple_workflow",
            "description": "Simple benchmark workflow",
            "version": "1.0",
            "stages": [{"name": "stage1"}]
        }
    }


@pytest.fixture
def complex_workflow_config():
    """Complex workflow with 50+ stages for benchmarking."""
    stages = [{"name": f"stage{i}"} for i in range(50)]
    return {
        "workflow": {
            "name": "complex_workflow",
            "description": "Complex 50-stage workflow",
            "version": "1.0",
            "stages": stages
        }
    }


@pytest.fixture
def mock_llm_provider():
    """Mock LLM provider for benchmarking."""
    provider = MagicMock()
    provider.generate.return_value = {
        "content": "Test response",
        "usage": {"total_tokens": 100}
    }
    return provider


@pytest.fixture
def test_db():
    """In-memory database for benchmarking."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db


@pytest.fixture
def minimal_agent_config():
    """Minimal agent configuration for benchmarking."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="benchmark_agent",
            description="Agent for performance benchmarks",
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
def tool_registry():
    """Tool registry with sample tools."""
    mock_registry = Mock()
    mock_registry.list_tools.return_value = []
    mock_registry.get.return_value = None
    return mock_registry


@pytest.fixture
def mock_async_llm():
    """Shared mock async LLM provider for performance testing."""
    class MockAsyncLLM:
        def __init__(self, latency: float = TEST_LLM_LATENCY):
            self.latency = latency

        async def acomplete(self, prompt: str, **kwargs) -> LLMResponse:
            """Simulate async LLM call with realistic latency."""
            await asyncio.sleep(self.latency)
            return LLMResponse(
                content="Mock response",
                model="mock-model",
                provider="mock",
                total_tokens=10
            )

    return MockAsyncLLM()
