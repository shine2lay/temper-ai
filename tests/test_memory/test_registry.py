"""Tests for MemoryProviderRegistry."""

import threading

import pytest

from src.memory.adapters.in_memory import InMemoryAdapter
from src.memory.constants import PROVIDER_IN_MEMORY
from src.memory.registry import MemoryProviderRegistry


class TestMemoryProviderRegistry:
    """Tests for the singleton provider registry."""

    def test_singleton_same_instance(self):
        inst1 = MemoryProviderRegistry.get_instance()
        inst2 = MemoryProviderRegistry.get_instance()
        assert inst1 is inst2

    def test_singleton_thread_safety(self):
        """Concurrent calls to get_instance() should return the same object."""
        instances = []
        barrier = threading.Barrier(4)

        def get_it():
            barrier.wait()
            instances.append(MemoryProviderRegistry.get_instance())

        threads = [threading.Thread(target=get_it) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 4
        assert all(inst is instances[0] for inst in instances)

    def test_get_in_memory_provider(self):
        reg = MemoryProviderRegistry.get_instance()
        cls = reg.get_provider_class(PROVIDER_IN_MEMORY)
        assert cls is InMemoryAdapter

    def test_get_unknown_provider_raises(self):
        reg = MemoryProviderRegistry.get_instance()
        with pytest.raises(KeyError, match="Unknown memory provider"):
            reg.get_provider_class("nonexistent")

    def test_register_custom_provider(self):

        class CustomAdapter:
            pass

        reg = MemoryProviderRegistry.get_instance()
        reg.register_provider("custom", CustomAdapter)
        assert reg.get_provider_class("custom") is CustomAdapter

    def test_reset_for_testing(self):
        inst1 = MemoryProviderRegistry.get_instance()
        MemoryProviderRegistry.reset_for_testing()
        inst2 = MemoryProviderRegistry.get_instance()
        assert inst1 is not inst2

    def test_reset_creates_new_instance(self):
        MemoryProviderRegistry.reset_for_testing()
        assert MemoryProviderRegistry._instance is None

    def test_builtin_providers_registered(self):
        reg = MemoryProviderRegistry.get_instance()
        # in_memory should be eagerly registered
        assert reg.get_provider_class(PROVIDER_IN_MEMORY) is InMemoryAdapter

    def test_custom_provider_overrides_builtin(self):

        class Override:
            pass

        reg = MemoryProviderRegistry.get_instance()
        reg.register_provider(PROVIDER_IN_MEMORY, Override)
        assert reg.get_provider_class(PROVIDER_IN_MEMORY) is Override
