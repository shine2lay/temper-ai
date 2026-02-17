"""Tests for KnowledgeGraphMemoryAdapter."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.memory._schemas import MemoryScope
from src.memory.adapters.knowledge_graph_adapter import (
    MEMORY_TYPE_SEMANTIC,
    KnowledgeGraphMemoryAdapter,
)


@pytest.fixture
def scope():
    return MemoryScope(tenant_id="test", workflow_name="wf", agent_name="agent")


def _make_concept(name: str, concept_type: str = "product", cid: str = "c1"):
    """Create a mock KGConceptRecord."""
    concept = MagicMock()
    concept.id = cid
    concept.name = name
    concept.concept_type = concept_type
    concept.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    concept.properties = {}
    return concept


def _make_adapter_with_concepts(concepts):
    """Create a KnowledgeGraphMemoryAdapter with a mocked store."""
    adapter = KnowledgeGraphMemoryAdapter()
    mock_store = MagicMock()
    mock_store.list_concepts.return_value = concepts
    adapter._store = mock_store
    adapter._query = MagicMock()
    return adapter


class TestAdd:
    def test_add_returns_empty_string(self, scope):
        adapter = KnowledgeGraphMemoryAdapter()
        result = adapter.add(scope, "content", "episodic", {"key": "val"})
        assert result == ""

    def test_add_is_noop(self, scope):
        adapter = KnowledgeGraphMemoryAdapter()
        adapter.add(scope, "content", "episodic")
        # No store initialized, no side effects
        assert adapter._store is None


class TestDelete:
    def test_delete_returns_false(self, scope):
        adapter = KnowledgeGraphMemoryAdapter()
        assert adapter.delete(scope, "some-id") is False

    def test_delete_all_returns_zero(self, scope):
        adapter = KnowledgeGraphMemoryAdapter()
        assert adapter.delete_all(scope) == 0


class TestSearch:
    def test_search_returns_matching_concepts(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("web_app", "product", "c1"),
            _make_concept("api", "product", "c2"),
            _make_concept("data_pipeline", "stage", "c3"),
        ])
        results = adapter.search(scope, "api")
        assert len(results) == 1
        assert results[0].metadata["name"] == "api"
        assert results[0].memory_type == MEMORY_TYPE_SEMANTIC
        assert results[0].relevance_score > 0

    def test_search_empty_query_returns_all(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("web_app", "product", "c1"),
            _make_concept("api", "product", "c2"),
        ])
        results = adapter.search(scope, "")
        assert len(results) == 2

    def test_search_no_match_returns_empty(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("web_app", "product", "c1"),
        ])
        results = adapter.search(scope, "nonexistent_xyz")
        assert results == []

    def test_search_respects_limit(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept(f"item_{i}", "product", f"c{i}")
            for i in range(10)
        ])
        results = adapter.search(scope, "item", limit=3)
        assert len(results) == 3

    def test_search_filters_by_threshold(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("this_is_a_very_long_concept_name", "product", "c1"),
        ])
        # Short query against long name => low score, filtered by high threshold
        results = adapter.search(scope, "this", threshold=0.9)
        assert results == []

    def test_search_wrong_memory_type_returns_empty(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("api", "product", "c1"),
        ])
        results = adapter.search(scope, "api", memory_type="episodic")
        assert results == []

    def test_search_semantic_type_allowed(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("api", "product", "c1"),
        ])
        results = adapter.search(scope, "api", memory_type=MEMORY_TYPE_SEMANTIC)
        assert len(results) == 1

    def test_search_results_sorted_by_relevance(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("api_long_name_extra", "product", "c1"),
            _make_concept("api", "product", "c2"),
        ])
        results = adapter.search(scope, "api")
        assert len(results) == 2
        # "api" exact match has higher score than "api_long_name_extra"
        assert results[0].metadata["name"] == "api"

    def test_search_case_insensitive(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("WebApp", "product", "c1"),
        ])
        results = adapter.search(scope, "webapp")
        assert len(results) == 1


class TestGetAll:
    def test_get_all_returns_all_concepts(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("web_app", "product", "c1"),
            _make_concept("api", "product", "c2"),
        ])
        results = adapter.get_all(scope)
        assert len(results) == 2
        assert results[0].content == "product: web_app"
        assert results[1].content == "product: api"

    def test_get_all_empty_store(self, scope):
        adapter = _make_adapter_with_concepts([])
        results = adapter.get_all(scope)
        assert results == []

    def test_get_all_wrong_type_returns_empty(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("api", "product", "c1"),
        ])
        results = adapter.get_all(scope, memory_type="episodic")
        assert results == []

    def test_get_all_semantic_type_allowed(self, scope):
        adapter = _make_adapter_with_concepts([
            _make_concept("api", "product", "c1"),
        ])
        results = adapter.get_all(scope, memory_type=MEMORY_TYPE_SEMANTIC)
        assert len(results) == 1


class TestConceptToEntry:
    def test_concept_converted_correctly(self):
        concept = _make_concept("my_api", "product", "abc123")
        entry = KnowledgeGraphMemoryAdapter._concept_to_entry(concept, score=0.85)
        assert entry.id == "abc123"
        assert entry.content == "product: my_api"
        assert entry.memory_type == MEMORY_TYPE_SEMANTIC
        assert entry.metadata["concept_type"] == "product"
        assert entry.metadata["name"] == "my_api"
        assert entry.relevance_score == 0.85

    def test_concept_default_score_zero(self):
        concept = _make_concept("stage_a", "stage", "s1")
        entry = KnowledgeGraphMemoryAdapter._concept_to_entry(concept)
        assert entry.relevance_score == 0.0


class TestLazyInit:
    def test_store_not_initialized_until_needed(self):
        adapter = KnowledgeGraphMemoryAdapter()
        assert adapter._store is None
        assert adapter._query is None

    @patch("src.portfolio.store.PortfolioStore")
    @patch("src.portfolio.knowledge_graph.KnowledgeQuery")
    def test_ensure_initialized_creates_store(self, mock_query_cls, mock_store_cls):
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        adapter = KnowledgeGraphMemoryAdapter(config={"database_url": "sqlite:///test.db"})
        adapter._ensure_initialized()
        mock_store_cls.assert_called_once_with(database_url="sqlite:///test.db")
        mock_query_cls.assert_called_once_with(mock_store)
        assert adapter._store is mock_store

    def test_ensure_initialized_idempotent(self):
        adapter = _make_adapter_with_concepts([])
        query_ref = adapter._query
        adapter._ensure_initialized()
        # Should not re-create
        assert adapter._query is query_ref
