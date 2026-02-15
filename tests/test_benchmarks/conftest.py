"""Shared fixtures and configuration for performance benchmarks."""

import asyncio
import os
import time
from unittest.mock import MagicMock, Mock

import pytest

from src.agent.llm_providers import BaseLLM, LLMResponse
from src.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)
from src.observability.database import DatabaseManager

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
# Performance Budgets (seconds unless noted)
# ============================================================================

PERFORMANCE_BUDGETS = {
    # Compiler budgets
    "compiler_simple": {"target": 1.0, "alert": 0.9, "fail": 1.5},
    "compiler_medium": {"target": 3.0, "alert": 2.7, "fail": 4.5},
    "compiler_large": {"target": 5.0, "alert": 4.5, "fail": 7.0},
    "compiler_complex": {"target": 15.0, "alert": 13.5, "fail": 20.0},

    # Agent budgets
    "agent_execution": {"target": 0.1, "alert": 0.09, "fail": 0.15},
    "agent_with_tools": {"target": 0.15, "alert": 0.135, "fail": 0.2},

    # Database budgets
    "database_simple_query": {"target": 0.01, "alert": 0.009, "fail": 0.02},
    "database_complex_query": {"target": 0.05, "alert": 0.045, "fail": 0.1},
    "database_write": {"target": 0.02, "alert": 0.018, "fail": 0.04},

    # Tool budgets
    "tool_execution": {"target": 0.05, "alert": 0.045, "fail": 0.1},
    "tool_registry_lookup": {"target": 0.005, "alert": 0.0045, "fail": 0.01},

    # Memory budgets (MB)
    "memory_agent_creation": {"target": 50, "alert": 65, "fail": 75},
    "memory_workflow_compilation": {"target": 100, "alert": 130, "fail": 150},
}


def check_budget(test_name: str, result_seconds: float) -> None:
    """Check if benchmark result exceeds performance budget."""
    budget = PERFORMANCE_BUDGETS.get(test_name)
    if not budget:
        return

    if result_seconds > budget["fail"]:
        pytest.fail(f"BUDGET EXCEEDED: {result_seconds:.3f}s > {budget['fail']}s")
    elif result_seconds > budget["alert"]:
        import warnings
        warnings.warn(f"APPROACHING BUDGET: {result_seconds:.3f}s > {budget['alert']}s")


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
def medium_workflow_config():
    """Medium workflow with 10 stages for benchmarking."""
    return {
        "workflow": {
            "name": "medium_workflow",
            "description": "Medium 10-stage workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(10)]
        }
    }


@pytest.fixture
def large_workflow_config():
    """Large workflow with 50 stages for benchmarking."""
    return {
        "workflow": {
            "name": "large_workflow",
            "description": "Large 50-stage workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(50)]
        }
    }


@pytest.fixture
def complex_workflow_config():
    """Complex workflow with 100 stages for benchmarking."""
    stages = [{"name": f"stage{i}"} for i in range(100)]
    return {
        "workflow": {
            "name": "complex_workflow",
            "description": "Complex 100-stage workflow",
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
def perf_db():
    """Function-scoped in-memory database for benchmarking."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db


@pytest.fixture(scope="session")
def benchmark_db():
    """Session-scoped in-memory database for benchmarks."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db


@pytest.fixture
def clean_db():
    """Function-scoped in-memory database for isolated tests."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    return db


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
def mock_llm_fast():
    """Mock LLM with 10ms latency for fast benchmarks."""
    llm = Mock(spec=BaseLLM)
    llm.complete.return_value = LLMResponse(
        content="<answer>Fast response</answer>",
        model="mock-fast",
        provider="mock",
        total_tokens=10,
    )
    return llm


@pytest.fixture
def mock_llm_realistic():
    """Mock LLM with 100ms latency for realistic benchmarks."""
    def slow_complete(*args, **kwargs):
        time.sleep(0.1)
        return LLMResponse(
            content="<answer>Realistic response</answer>",
            model="mock-realistic",
            provider="mock",
            total_tokens=50,
        )

    llm = Mock(spec=BaseLLM)
    llm.complete.side_effect = slow_complete
    return llm


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
