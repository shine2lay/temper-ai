"""Tests for cross-agent knowledge sharing (M9)."""

from unittest.mock import MagicMock

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.cross_pollination import (
    MAX_CONTENT_LENGTH,
    PUBLISHED_KNOWLEDGE_NAMESPACE,
    _build_published_scope,
    format_cross_pollination_context,
    publish_knowledge,
    retrieve_subscribed_knowledge,
)


class TestBuildPublishedScope:
    def test_returns_memory_scope_instance(self):
        scope = _build_published_scope("agent_a")
        assert isinstance(scope, MemoryScope)

    def test_namespace_includes_agent_name(self):
        scope = _build_published_scope("agent_a")
        assert scope.namespace == f"{PUBLISHED_KNOWLEDGE_NAMESPACE}__agent_a"

    def test_agent_name_set_on_scope(self):
        scope = _build_published_scope("my_agent")
        assert scope.agent_name == "my_agent"


class TestPublishKnowledge:
    def _make_service(self, entry_id: str = "test-id") -> MagicMock:
        svc = MagicMock()
        svc.store.return_value = entry_id
        return svc

    def test_returns_entry_id_on_success(self):
        svc = self._make_service("abc123")
        result = publish_knowledge("agent_a", "Some content", svc)
        assert result == "abc123"

    def test_calls_store_with_scope_and_entry(self):
        svc = self._make_service()
        publish_knowledge("agent_a", "content", svc)
        assert svc.store.called
        call_args = svc.store.call_args[0]
        scope = call_args[0]
        entry = call_args[1]
        assert scope.agent_name == "agent_a"
        assert entry.content == "content"

    def test_truncates_content_exceeding_max_length(self):
        svc = self._make_service()
        long_content = "x" * (MAX_CONTENT_LENGTH + 100)
        publish_knowledge("agent_a", long_content, svc)
        call_args = svc.store.call_args[0]
        entry = call_args[1]
        assert len(entry.content) == MAX_CONTENT_LENGTH

    def test_returns_none_on_store_exception(self):
        svc = MagicMock()
        svc.store.side_effect = RuntimeError("store failed")
        result = publish_knowledge("agent_a", "content", svc)
        assert result is None

    def test_passes_metadata_to_entry(self):
        svc = self._make_service()
        meta = {"key": "value"}
        publish_knowledge("agent_a", "content", svc, metadata=meta)
        entry = svc.store.call_args[0][1]
        assert entry.metadata == meta

    def test_uses_custom_memory_type(self):
        svc = self._make_service()
        publish_knowledge("agent_a", "content", svc, memory_type="custom_type")
        entry = svc.store.call_args[0][1]
        assert entry.memory_type == "custom_type"


class TestRetrieveSubscribedKnowledge:
    def _make_entry(self, content: str, score: float) -> MemoryEntry:
        entry = MemoryEntry(content=content, memory_type="published")
        entry.relevance_score = score
        return entry

    def test_returns_results_from_subscribed_agents(self):
        svc = MagicMock()
        svc.search.return_value = [self._make_entry("fact", 0.9)]
        results = retrieve_subscribed_knowledge(["agent_a"], "query", svc)
        assert len(results) == 1
        assert results[0]["agent_name"] == "agent_a"
        assert results[0]["content"] == "fact"

    def test_filters_below_relevance_threshold(self):
        svc = MagicMock()
        svc.search.return_value = [
            self._make_entry("low relevance", 0.5),
            self._make_entry("high relevance", 0.9),
        ]
        results = retrieve_subscribed_knowledge(
            ["agent_a"], "query", svc, relevance_threshold=0.7
        )
        assert len(results) == 1
        assert results[0]["content"] == "high relevance"

    def test_empty_subscribe_to_returns_empty(self):
        svc = MagicMock()
        results = retrieve_subscribed_knowledge([], "query", svc)
        assert results == []
        svc.search.assert_not_called()

    def test_aggregates_from_multiple_agents(self):
        svc = MagicMock()
        svc.search.return_value = [self._make_entry("fact", 0.9)]
        results = retrieve_subscribed_knowledge(["agent_a", "agent_b"], "query", svc)
        assert len(results) == 2
        agent_names = {r["agent_name"] for r in results}
        assert agent_names == {"agent_a", "agent_b"}

    def test_result_includes_relevance_score(self):
        svc = MagicMock()
        svc.search.return_value = [self._make_entry("content", 0.85)]
        results = retrieve_subscribed_knowledge(["agent_a"], "query", svc)
        assert results[0]["relevance_score"] == 0.85

    def test_search_exception_is_caught_gracefully(self):
        svc = MagicMock()
        svc.search.side_effect = RuntimeError("search failed")
        results = retrieve_subscribed_knowledge(["agent_a"], "query", svc)
        assert results == []


class TestFormatCrossPollinationContext:
    def test_empty_results_returns_empty_string(self):
        result = format_cross_pollination_context([])
        assert result == ""

    def test_formats_single_result(self):
        results = [
            {"agent_name": "agent_a", "content": "some fact", "relevance_score": 0.9}
        ]
        text = format_cross_pollination_context(results)
        assert "[From agent_a]: some fact" in text

    def test_formats_multiple_results(self):
        results = [
            {"agent_name": "a1", "content": "fact1", "relevance_score": 0.9},
            {"agent_name": "a2", "content": "fact2", "relevance_score": 0.8},
        ]
        text = format_cross_pollination_context(results)
        assert "a1" in text
        assert "a2" in text

    def test_respects_max_chars(self):
        results = [
            {"agent_name": "agent_a", "content": "x" * 100, "relevance_score": 0.9}
        ]
        text = format_cross_pollination_context(results, max_chars=10)
        assert len(text) == 0 or text == ""

    def test_newline_separator_between_entries(self):
        results = [
            {"agent_name": "a1", "content": "c1", "relevance_score": 0.9},
            {"agent_name": "a2", "content": "c2", "relevance_score": 0.8},
        ]
        text = format_cross_pollination_context(results)
        assert "\n" in text
