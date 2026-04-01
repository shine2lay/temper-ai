"""Tests for Mem0Store — dependency validation only.

We don't test mem0 internals. We only verify:
1. Constructor raises clear error when mem0ai is not installed
2. The interface is implemented correctly (via mock)
"""

import pytest
from unittest.mock import MagicMock, patch

from temper_ai.memory.exceptions import MemoryDependencyError, MemoryBackendError


class TestMem0DependencyCheck:
    def test_raises_when_mem0_not_installed(self):
        """Verify clear error message when mem0ai is missing."""
        with patch.dict("sys.modules", {"mem0": None}):
            # Force re-import to trigger the check
            with pytest.raises(MemoryDependencyError, match="mem0ai is required"):
                from temper_ai.memory.mem0_store import _ensure_mem0
                _ensure_mem0()


class TestMem0StoreInterface:
    """Test Mem0Store with a mocked mem0 library."""

    @pytest.fixture
    def mock_mem0(self):
        """Mock the mem0 Memory class."""
        mock_memory = MagicMock()
        mock_memory_cls = MagicMock(return_value=mock_memory)
        mock_memory_cls.from_config = MagicMock(return_value=mock_memory)
        return mock_memory, mock_memory_cls

    @pytest.fixture
    def store(self, mock_mem0):
        mock_memory, mock_memory_cls = mock_mem0
        with patch("temper_ai.memory.mem0_store._ensure_mem0", return_value=mock_memory_cls):
            from temper_ai.memory.mem0_store import Mem0Store
            s = Mem0Store(mem0_config={"llm": {}, "vector_store": {}, "embedder": {}})
            s._memory = mock_memory
            return s, mock_memory

    def test_store_calls_mem0_add(self, store):
        s, mock_memory = store
        mock_memory.add.return_value = [{"id": "mem-123"}]

        result = s.store("agent_a", "scope1", "test content", metadata={"key": "val"})

        mock_memory.add.assert_called_once()
        call_args = mock_memory.add.call_args
        assert call_args[0][0] == "test content"
        assert call_args[1]["user_id"] == "scope1:agent_a"
        assert call_args[1]["metadata"] == {"key": "val"}
        assert result == "mem-123"

    def test_store_uses_infer_setting(self, store):
        s, mock_memory = store
        mock_memory.add.return_value = [{"id": "x"}]

        s._infer = False
        s.store("a", "s", "content")
        assert mock_memory.add.call_args[1]["infer"] is False

        s._infer = True
        s.store("a", "s", "content")
        assert mock_memory.add.call_args[1]["infer"] is True

    def test_recall_calls_get_all(self, store):
        s, mock_memory = store
        mock_memory.get_all.return_value = {
            "results": [
                {"id": "1", "memory": "fact 1"},
                {"id": "2", "memory": "fact 2"},
            ]
        }

        entries = s.recall("agent_a", "scope1", limit=10)

        mock_memory.get_all.assert_called_once_with(user_id="scope1:agent_a")
        assert len(entries) == 2
        assert entries[0].content == "fact 1"
        assert entries[1].content == "fact 2"

    def test_recall_respects_limit(self, store):
        s, mock_memory = store
        mock_memory.get_all.return_value = {
            "results": [{"id": str(i), "memory": f"fact {i}"} for i in range(10)]
        }

        entries = s.recall("agent_a", "scope1", limit=3)
        assert len(entries) == 3

    def test_search_calls_mem0_search(self, store):
        s, mock_memory = store
        mock_memory.search.return_value = {
            "results": [{"id": "1", "memory": "FastAPI project", "score": 0.95}]
        }

        entries = s.search("FastAPI", "agent_a", "scope1", limit=5)

        mock_memory.search.assert_called_once_with(
            "FastAPI", user_id="scope1:agent_a", limit=5
        )
        assert len(entries) == 1
        assert entries[0].content == "FastAPI project"
        assert entries[0].relevance_score == 0.95

    def test_clear_deletes_all_entries(self, store):
        s, mock_memory = store
        mock_memory.get_all.return_value = {
            "results": [{"id": "1", "memory": "a"}, {"id": "2", "memory": "b"}]
        }

        count = s.clear("agent_a", "scope1")

        assert count == 2
        assert mock_memory.delete.call_count == 2

    def test_user_id_format(self, store):
        s, _ = store
        assert s._user_id("agent_a", "project:/tmp") == "project:/tmp:agent_a"
        assert s._user_id("reviewer", "workflow:sdlc") == "workflow:sdlc:reviewer"

    def test_store_handles_dict_result(self, store):
        s, mock_memory = store
        mock_memory.add.return_value = {"id": "single-id"}
        result = s.store("a", "s", "content")
        assert result == "single-id"

    def test_store_handles_empty_result(self, store):
        s, mock_memory = store
        mock_memory.add.return_value = None
        result = s.store("a", "s", "content")
        assert result == ""

    def test_recall_handles_list_result(self, store):
        """Some mem0 versions return a list instead of dict."""
        s, mock_memory = store
        mock_memory.get_all.return_value = [
            {"id": "1", "memory": "fact 1"},
        ]
        entries = s.recall("agent_a", "scope1")
        assert len(entries) == 1
