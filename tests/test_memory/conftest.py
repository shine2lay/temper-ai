"""Shared fixtures for memory module tests."""

import pytest

from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.adapters.in_memory import InMemoryAdapter
from temper_ai.memory.registry import MemoryProviderRegistry
from temper_ai.memory.service import MemoryService


@pytest.fixture
def scope():
    """A standard test scope."""
    return MemoryScope(
        tenant_id="test",
        workflow_name="test_wf",
        agent_name="test_agent",
    )


@pytest.fixture
def adapter():
    """A fresh InMemoryAdapter."""
    return InMemoryAdapter()


@pytest.fixture
def service():
    """A MemoryService using in_memory provider."""
    MemoryProviderRegistry.reset_for_testing()
    return MemoryService(provider_name="in_memory")


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the provider registry before and after each test."""
    MemoryProviderRegistry.reset_for_testing()
    yield
    MemoryProviderRegistry.reset_for_testing()
