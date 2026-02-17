"""Tests for Mem0Adapter (all mocked — mem0 is not installed in test env)."""

from unittest.mock import MagicMock, patch

import pytest

from src.memory._schemas import MemoryScope
from src.memory.constants import MEMORY_TYPE_EPISODIC, MEMORY_TYPE_PROCEDURAL


# All tests mock mem0 so we can test adapter logic without the dependency.
ADAPTER_MODULE = "src.memory.adapters.mem0_adapter"


def _make_scope():
    return MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")


def _make_adapter(mock_mem0):
    """Import and create a Mem0Adapter with the module mocked."""
    with patch(f"{ADAPTER_MODULE}._ensure_mem0_available", return_value=mock_mem0):
        from src.memory.adapters.mem0_adapter import Mem0Adapter

        return Mem0Adapter()


class TestMem0AdapterInit:
    """Initialization tests."""

    def test_init_default_config(self):
        mock_mem0 = MagicMock()
        adapter = _make_adapter(mock_mem0)
        mock_mem0.Memory.from_config.assert_called_once()
        assert adapter is not None

    def test_init_custom_config(self):
        mock_mem0 = MagicMock()
        custom = {"vector_store": {"provider": "custom"}}
        with patch(f"{ADAPTER_MODULE}._ensure_mem0_available", return_value=mock_mem0):
            from src.memory.adapters.mem0_adapter import Mem0Adapter

            adapter = Mem0Adapter(config=custom)
        mock_mem0.Memory.from_config.assert_called_with(custom)
        assert adapter is not None


class TestMem0AdapterAdd:
    """Add operation tests."""

    def test_add_delegates_to_mem0(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = [{"id": "abc"}]
        adapter = _make_adapter(mock_mem0)

        scope = _make_scope()
        result = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert result == "abc"

    def test_add_returns_id_from_dict(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = {"id": "dict-id"}
        adapter = _make_adapter(mock_mem0)

        scope = _make_scope()
        result = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert result == "dict-id"


class TestMem0AdapterSearch:
    """Search operation tests."""

    def test_search_delegates_to_mem0(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.search.return_value = {
            "results": [
                {
                    "id": "s1",
                    "memory": "found it",
                    "score": 0.9,
                    "metadata": {"memory_type": MEMORY_TYPE_EPISODIC},
                }
            ]
        }
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        results = adapter.search(scope, "test query")
        assert len(results) == 1
        assert results[0].content == "found it"
        assert results[0].relevance_score == 0.9

    def test_search_filters_by_type(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.search.return_value = {
            "results": [
                {"id": "1", "memory": "a", "score": 0.9, "metadata": {"memory_type": MEMORY_TYPE_EPISODIC}},
                {"id": "2", "memory": "b", "score": 0.8, "metadata": {"memory_type": MEMORY_TYPE_PROCEDURAL}},
            ]
        }
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        results = adapter.search(scope, "q", memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(results) == 1
        assert results[0].memory_type == MEMORY_TYPE_PROCEDURAL

    def test_search_filters_by_threshold(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.search.return_value = {
            "results": [
                {"id": "1", "memory": "high", "score": 0.9, "metadata": {"memory_type": "episodic"}},
                {"id": "2", "memory": "low", "score": 0.1, "metadata": {"memory_type": "episodic"}},
            ]
        }
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        results = adapter.search(scope, "q", threshold=0.5)
        assert len(results) == 1
        assert results[0].content == "high"


class TestMem0AdapterGetAll:
    """Get all operation tests."""

    def test_get_all_delegates(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = {
            "results": [
                {"id": "1", "memory": "m1", "metadata": {"memory_type": "episodic"}},
                {"id": "2", "memory": "m2", "metadata": {"memory_type": "procedural"}},
            ]
        }
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        entries = adapter.get_all(scope)
        assert len(entries) == 2


class TestMem0AdapterDelete:
    """Delete operation tests."""

    def test_delete_delegates(self):
        mock_mem0 = MagicMock()
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        result = adapter.delete(scope, "some-id")
        assert result is True

    def test_delete_returns_false_on_error(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.delete.side_effect = RuntimeError("fail")
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        result = adapter.delete(scope, "bad-id")
        assert result is False

    def test_delete_all(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = {
            "results": [
                {"id": "1", "memory": "m1", "metadata": {}},
                {"id": "2", "memory": "m2", "metadata": {}},
            ]
        }
        adapter = _make_adapter(mock_mem0)
        scope = _make_scope()

        count = adapter.delete_all(scope)
        assert count == 2
