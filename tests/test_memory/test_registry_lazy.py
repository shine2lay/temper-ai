"""Tests for MemoryProviderRegistry lazy-import paths.

Covers lines 60-61, 67-81 in registry.py:
- Lazy import of PGAdapter (PROVIDER_PG)
- Lazy import of Mem0Adapter (PROVIDER_MEM0)
- Lazy import of KnowledgeGraphMemoryAdapter (PROVIDER_KNOWLEDGE_GRAPH)
- Caching: lazy import result is stored so it is not re-imported
- _lazy_import raises KeyError for unknown name
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from temper_ai.memory.constants import (
    PROVIDER_KNOWLEDGE_GRAPH,
    PROVIDER_MEM0,
    PROVIDER_PG,
)
from temper_ai.memory.registry import MemoryProviderRegistry


# Helpers
def _fresh_registry() -> MemoryProviderRegistry:
    """Return a brand-new (non-singleton) registry instance for isolation."""
    MemoryProviderRegistry.reset_for_testing()
    return MemoryProviderRegistry.get_instance()


# ---------------------------------------------------------------------------
# Lazy import — PROVIDER_PG
# ---------------------------------------------------------------------------


class TestLazyImportPG:
    def test_get_pg_provider_returns_pg_adapter_class(self):
        reg = _fresh_registry()

        class FakePGAdapter:
            pass

        with patch(
            "temper_ai.memory.registry.MemoryProviderRegistry._lazy_import",
            return_value=FakePGAdapter,
        ):
            cls = reg.get_provider_class(PROVIDER_PG)

        assert cls is FakePGAdapter

    def test_lazy_import_pg_returns_real_class(self):
        """_lazy_import('pg') should import and return PGAdapter."""
        from temper_ai.memory.adapters.pg_adapter import PGAdapter

        result = MemoryProviderRegistry._lazy_import(PROVIDER_PG)
        assert result is PGAdapter

    def test_pg_class_cached_after_first_load(self):
        """Second call to get_provider_class for 'pg' must not re-import."""
        reg = _fresh_registry()

        import_count = [0]

        original_lazy = MemoryProviderRegistry._lazy_import

        def counting_lazy(name: str):
            import_count[0] += 1
            return original_lazy(name)

        with patch.object(
            MemoryProviderRegistry, "_lazy_import", side_effect=counting_lazy
        ):
            cls1 = reg.get_provider_class(PROVIDER_PG)
            cls2 = reg.get_provider_class(PROVIDER_PG)

        # Should only import once; second call hits the cached value
        assert import_count[0] == 1
        assert cls1 is cls2


# ---------------------------------------------------------------------------
# Lazy import — PROVIDER_MEM0
# ---------------------------------------------------------------------------


class TestLazyImportMem0:
    def test_lazy_import_mem0_returns_mem0_adapter_class(self):
        from temper_ai.memory.adapters.mem0_adapter import Mem0Adapter

        result = MemoryProviderRegistry._lazy_import(PROVIDER_MEM0)
        assert result is Mem0Adapter

    def test_get_mem0_provider_via_registry(self):
        reg = _fresh_registry()
        from temper_ai.memory.adapters.mem0_adapter import Mem0Adapter

        cls = reg.get_provider_class(PROVIDER_MEM0)
        assert cls is Mem0Adapter

    def test_mem0_class_cached_after_first_load(self):
        reg = _fresh_registry()

        import_count = [0]
        original_lazy = MemoryProviderRegistry._lazy_import

        def counting_lazy(name: str):
            import_count[0] += 1
            return original_lazy(name)

        with patch.object(
            MemoryProviderRegistry, "_lazy_import", side_effect=counting_lazy
        ):
            reg.get_provider_class(PROVIDER_MEM0)
            reg.get_provider_class(PROVIDER_MEM0)

        assert import_count[0] == 1


# ---------------------------------------------------------------------------
# Lazy import — PROVIDER_KNOWLEDGE_GRAPH
# ---------------------------------------------------------------------------


class TestLazyImportKnowledgeGraph:
    def test_lazy_import_kg_returns_kg_adapter_class(self):
        from temper_ai.memory.adapters.knowledge_graph_adapter import (
            KnowledgeGraphMemoryAdapter,
        )

        result = MemoryProviderRegistry._lazy_import(PROVIDER_KNOWLEDGE_GRAPH)
        assert result is KnowledgeGraphMemoryAdapter

    def test_get_knowledge_graph_provider_via_registry(self):
        reg = _fresh_registry()
        from temper_ai.memory.adapters.knowledge_graph_adapter import (
            KnowledgeGraphMemoryAdapter,
        )

        cls = reg.get_provider_class(PROVIDER_KNOWLEDGE_GRAPH)
        assert cls is KnowledgeGraphMemoryAdapter

    def test_kg_class_cached_after_first_load(self):
        reg = _fresh_registry()

        import_count = [0]
        original_lazy = MemoryProviderRegistry._lazy_import

        def counting_lazy(name: str):
            import_count[0] += 1
            return original_lazy(name)

        with patch.object(
            MemoryProviderRegistry, "_lazy_import", side_effect=counting_lazy
        ):
            reg.get_provider_class(PROVIDER_KNOWLEDGE_GRAPH)
            reg.get_provider_class(PROVIDER_KNOWLEDGE_GRAPH)

        assert import_count[0] == 1


# ---------------------------------------------------------------------------
# _lazy_import unknown name
# ---------------------------------------------------------------------------


class TestLazyImportUnknown:
    def test_lazy_import_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="No lazy import for provider"):
            MemoryProviderRegistry._lazy_import("totally_unknown_provider")

    def test_lazy_import_empty_string_raises_key_error(self):
        with pytest.raises(KeyError):
            MemoryProviderRegistry._lazy_import("")


# ---------------------------------------------------------------------------
# Sentinel caching: value is replaced after first lazy load
# ---------------------------------------------------------------------------


class TestSentinelReplacement:
    def test_sentinel_is_replaced_with_real_class(self):
        """After get_provider_class, the sentinel should be replaced."""
        reg = _fresh_registry()
        # Force lazy load
        reg.get_provider_class(PROVIDER_PG)
        # Now the stored value should NOT be the sentinel anymore
        from temper_ai.memory.adapters.pg_adapter import PGAdapter
        from temper_ai.memory.registry import _LAZY_SENTINEL

        stored = reg._providers[PROVIDER_PG]
        assert stored is not _LAZY_SENTINEL
        assert stored is PGAdapter
