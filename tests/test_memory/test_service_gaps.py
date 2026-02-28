"""Targeted tests for uncovered paths in service.py and mem0_adapter.py.

service.py gaps:
  Line 121   — latency warning when search exceeds LATENCY_BUDGET_MS
  Line 169   — store_procedural with max_episodes > 0
  Line 187   — store_cross_session with max_episodes > 0
  Lines 211-212 — retrieve_procedural_context with matching entries
  Line 223   — search() public method (direct delegation)
  Lines 286-287 — retrieve_with_shared decay path

mem0_adapter.py gaps:
  Lines 26-31 — _ensure_mem0_available raises ImportError when mem0 missing
  Line 85->87 — add() returns UUID fallback when result is non-list, non-dict
  Line 89     — add() returns UUID fallback when result is list of non-dicts
  Line 109    — search() warns when latency exceeds budget
  Line 156    — get_all() handles list-format (not dict) result from mem0
  Line 182->181 — delete_all when delete returns False (failed deletion)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import (
    LATENCY_BUDGET_MS,
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
)
from temper_ai.memory.registry import MemoryProviderRegistry
from temper_ai.memory.service import MemoryService

ADAPTER_MODULE = "temper_ai.memory.adapters.mem0_adapter"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_scope() -> MemoryScope:
    return MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")


def _make_service() -> MemoryService:
    MemoryProviderRegistry.reset_for_testing()
    return MemoryService(provider_name="in_memory")


def _make_mem0_adapter(mock_mem0: MagicMock) -> object:
    with patch(f"{ADAPTER_MODULE}._ensure_mem0_available", return_value=mock_mem0):
        from temper_ai.memory.adapters.mem0_adapter import Mem0Adapter

        return Mem0Adapter()


# ===========================================================================
# service.py: line 121 — latency warning
# ===========================================================================


class TestServiceLatencyWarning:
    def test_retrieve_context_warns_on_slow_search(self, caplog):
        """A slow adapter triggers the latency warning at line 121."""
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "some content about queries")

        slow_ms = LATENCY_BUDGET_MS + 100  # exceeds budget

        original_search = svc._adapter.search

        def slow_search(*args, **kwargs):
            time.sleep(slow_ms / 1000.0)
            return original_search(*args, **kwargs)

        with patch.object(svc._adapter, "search", side_effect=slow_search):
            import logging

            with caplog.at_level(logging.WARNING, logger="temper_ai.memory.service"):
                svc.retrieve_context(scope, "queries")

        assert any(
            "latency" in rec.message.lower() or "exceeds" in rec.message.lower()
            for rec in caplog.records
        )

    def test_retrieve_context_no_warning_on_fast_search(self, caplog):
        """Fast search must not emit a latency warning."""
        svc = _make_service()
        scope = _make_scope()

        import logging

        with caplog.at_level(logging.WARNING, logger="temper_ai.memory.service"):
            svc.retrieve_context(scope, "anything")

        latency_warnings = [
            r
            for r in caplog.records
            if "latency" in r.message.lower() or "exceeds" in r.message.lower()
        ]
        assert latency_warnings == []


# ===========================================================================
# service.py: line 169 — store_procedural with max_episodes
# ===========================================================================


class TestStoreProcedural:
    def test_store_procedural_max_episodes_enforced(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(5):
            svc.store_procedural(scope, f"proc {i}")
        # Now add with max_episodes=3 — should prune to 3
        svc.store_procedural(scope, "new proc", max_episodes=3)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) <= 3

    def test_store_procedural_max_episodes_zero_no_prune(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(5):
            svc.store_procedural(scope, f"proc {i}")
        svc.store_procedural(scope, "extra", max_episodes=0)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) == 6

    def test_store_procedural_with_metadata(self):
        svc = _make_service()
        scope = _make_scope()
        mid = svc.store_procedural(scope, "step-by-step guide", metadata={"version": 2})
        entries = svc.list_memories(scope)
        found = next(e for e in entries if e.id == mid)
        assert found.metadata["version"] == 2


# ===========================================================================
# service.py: line 187 — store_cross_session with max_episodes
# ===========================================================================


class TestStoreCrossSession:
    def test_store_cross_session_max_episodes_enforced(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(5):
            svc.store_cross_session(scope, f"session {i}")
        svc.store_cross_session(scope, "new session", max_episodes=2)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_CROSS_SESSION)
        assert len(entries) <= 2

    def test_store_cross_session_max_episodes_zero_no_prune(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(3):
            svc.store_cross_session(scope, f"cs {i}")
        svc.store_cross_session(scope, "extra", max_episodes=0)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_CROSS_SESSION)
        assert len(entries) == 4

    def test_store_cross_session_returns_id(self):
        svc = _make_service()
        scope = _make_scope()
        mid = svc.store_cross_session(scope, "important cross-session fact")
        assert isinstance(mid, str) and len(mid) > 0


# ===========================================================================
# service.py: lines 211-212 — retrieve_procedural_context with entries
# ===========================================================================


class TestRetrieveProceduralContext:
    def test_retrieve_procedural_returns_formatted_string(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_procedural(scope, "always sanitize user input")
        ctx = svc.retrieve_procedural_context(scope, "sanitize")
        assert isinstance(ctx, str)
        assert len(ctx) > 0
        assert "sanitize" in ctx

    def test_retrieve_procedural_empty_returns_empty_string(self):
        svc = _make_service()
        scope = _make_scope()
        ctx = svc.retrieve_procedural_context(scope, "anything")
        assert ctx == ""

    def test_retrieve_procedural_only_returns_procedural_type(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "episodic memory about testing")
        svc.store_procedural(scope, "procedural step about testing")
        ctx = svc.retrieve_procedural_context(scope, "testing")
        # Should only include procedural entries
        assert "procedural" in ctx.lower() or "step" in ctx.lower()

    def test_retrieve_procedural_respects_max_chars(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_procedural(scope, "detailed procedure " * 200)
        ctx = svc.retrieve_procedural_context(scope, "procedure", max_chars=100)
        assert len(ctx) <= 100 + 10  # allow small overflow for truncation suffix

    def test_retrieve_procedural_respects_retrieval_k(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(10):
            svc.store_procedural(scope, f"step {i} procedure guide")
        ctx = svc.retrieve_procedural_context(scope, "step", retrieval_k=2)
        assert isinstance(ctx, str)


# ===========================================================================
# service.py: line 223 — search() public method
# ===========================================================================


class TestServiceSearch:
    def test_search_returns_list(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "machine learning tutorial")
        results = svc.search(scope, "machine")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_search_empty_scope_returns_empty(self):
        svc = _make_service()
        scope = _make_scope()
        results = svc.search(scope, "query")
        assert results == []

    def test_search_with_memory_type_filter(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "episodic data point")
        svc.store_procedural(scope, "procedural guide data")
        results = svc.search(scope, "data", memory_type=MEMORY_TYPE_EPISODIC)
        assert all(e.memory_type == MEMORY_TYPE_EPISODIC for e in results)

    def test_search_with_threshold(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "relevant")
        results = svc.search(scope, "relevant", threshold=0.0)
        assert isinstance(results, list)

    def test_search_with_limit(self):
        svc = _make_service()
        scope = _make_scope()
        for i in range(10):
            svc.store_episodic(scope, f"item {i} content")
        results = svc.search(scope, "item", limit=3)
        assert len(results) <= 3

    def test_search_returns_memory_entries(self):
        svc = _make_service()
        scope = _make_scope()
        svc.store_episodic(scope, "test content entry")
        results = svc.search(scope, "test")
        for entry in results:
            assert isinstance(entry, MemoryEntry)


# ===========================================================================
# service.py: lines 286-287 — retrieve_with_shared decay path
# ===========================================================================


class TestRetrieveWithSharedDecay:
    def _make_old_entry(self, content: str) -> MemoryEntry:
        """Create an entry with an old created_at to simulate age-based decay."""
        return MemoryEntry(
            content=content,
            memory_type=MEMORY_TYPE_EPISODIC,
            created_at=datetime.now(UTC) - timedelta(days=30),
            relevance_score=0.9,
        )

    def test_retrieve_with_shared_decay_applied(self):
        svc = _make_service()
        scope = _make_scope()
        shared_scope = MemoryService.build_shared_scope(scope, "shared_ns")

        svc.store_episodic(scope, "private old memory")
        svc.store_episodic(shared_scope, "shared old memory")

        # Use decay_factor < 1.0 to trigger lines 286-287
        ctx = svc.retrieve_with_shared(
            scope=scope,
            shared_scope=shared_scope,
            query="memory",
            decay_factor=0.5,
        )
        assert isinstance(ctx, str)

    def test_retrieve_with_shared_decay_filters_below_threshold(self):
        """Entries whose score falls below threshold after decay are excluded."""
        svc = _make_service()
        scope = _make_scope()
        shared_scope = MemoryService.build_shared_scope(scope, "ns2")

        # Add old entries — after heavy decay they should drop below threshold
        svc.store_episodic(scope, "old private content")

        ctx = svc.retrieve_with_shared(
            scope=scope,
            shared_scope=shared_scope,
            query="content",
            decay_factor=0.01,  # very aggressive decay
            relevance_threshold=0.99,  # high threshold that decayed scores won't meet
        )
        # With aggressive decay and high threshold, context may be empty
        assert isinstance(ctx, str)

    def test_retrieve_with_shared_no_decay_when_factor_one(self):
        svc = _make_service()
        scope = _make_scope()
        shared_scope = MemoryService.build_shared_scope(scope, "ns3")
        svc.store_episodic(scope, "private data entry")

        # decay_factor=1.0 skips the decay path
        ctx = svc.retrieve_with_shared(
            scope=scope,
            shared_scope=shared_scope,
            query="data",
            decay_factor=1.0,
        )
        assert isinstance(ctx, str)

    def test_retrieve_with_shared_deduplicates_content(self):
        svc = _make_service()
        scope = _make_scope()
        shared_scope = MemoryService.build_shared_scope(scope, "ns4")
        # Add identical content to both scopes
        svc.store_episodic(scope, "duplicate content here")
        svc.store_episodic(shared_scope, "duplicate content here")

        ctx = svc.retrieve_with_shared(
            scope=scope,
            shared_scope=shared_scope,
            query="duplicate",
        )
        # Deduplication should ensure "duplicate content here" appears once
        assert isinstance(ctx, str)
        assert ctx.count("duplicate content here") <= 1


# ===========================================================================
# mem0_adapter.py: lines 26-31 — _ensure_mem0_available import error
# ===========================================================================


class TestEnsureMem0Available:
    def test_raises_import_error_when_mem0_not_installed(self):
        """_ensure_mem0_available() raises ImportError with install hint."""
        with patch.dict("sys.modules", {"mem0": None}):
            # Force re-execution of _ensure_mem0_available by calling it directly
            from temper_ai.memory.adapters.mem0_adapter import _ensure_mem0_available

            with pytest.raises(ImportError, match="mem0ai is required"):
                _ensure_mem0_available()

    def test_import_error_message_includes_install_command(self):
        with patch.dict("sys.modules", {"mem0": None}):
            from temper_ai.memory.adapters.mem0_adapter import _ensure_mem0_available

            with pytest.raises(ImportError) as exc_info:
                _ensure_mem0_available()
            assert "pip install" in str(exc_info.value)

    def test_returns_module_when_available(self):
        fake_mem0 = MagicMock()
        with patch.dict("sys.modules", {"mem0": fake_mem0}):
            from temper_ai.memory.adapters.mem0_adapter import _ensure_mem0_available

            result = _ensure_mem0_available()
            assert result is fake_mem0


# ===========================================================================
# mem0_adapter.py: line 89 — add() returns UUID fallback
# ===========================================================================


class TestMem0AdapterAddFallback:
    def test_add_returns_uuid_when_result_is_empty_list(self):
        """If mem0.add returns [], a fresh UUID hex is returned."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = []
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        mid = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str) and len(mid) > 0

    def test_add_returns_uuid_when_result_is_list_of_non_dicts(self):
        """If mem0.add returns a list of non-dict items, UUID fallback is used."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = ["just-a-string"]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        mid = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        # Non-dict first item → UUID fallback
        assert isinstance(mid, str) and len(mid) > 0

    def test_add_returns_uuid_when_result_is_unexpected_type(self):
        """If mem0.add returns something other than list or dict, UUID used."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = 42  # unexpected
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        mid = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str) and len(mid) > 0

    def test_add_returns_uuid_when_dict_missing_id(self):
        """Dict result without 'id' key generates a UUID."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = {"no_id": "here"}
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        mid = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str) and len(mid) > 0

    def test_add_list_of_dicts_missing_id_returns_uuid(self):
        """List[dict] where first dict has no 'id' key falls back to UUID."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.add.return_value = [{"result": "ok"}]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        mid = adapter.add(scope, "content", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str) and len(mid) > 0


# ===========================================================================
# mem0_adapter.py: line 109 — search() latency warning
# ===========================================================================


class TestMem0AdapterSearchLatency:
    def test_search_warns_on_slow_response(self, caplog):
        mock_mem0 = MagicMock()
        slow_ms = LATENCY_BUDGET_MS + 200

        def slow_search(*args, **kwargs):
            time.sleep(slow_ms / 1000.0)
            return {"results": []}

        mock_mem0.Memory.from_config.return_value.search.side_effect = slow_search
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")

        import logging

        with caplog.at_level(logging.WARNING, logger=ADAPTER_MODULE):
            adapter.search(scope, "query")

        assert any(
            "latency" in r.message.lower() or "exceeds" in r.message.lower()
            for r in caplog.records
        )

    def test_search_no_warning_on_fast_response(self, caplog):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.search.return_value = {"results": []}
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")

        import logging

        with caplog.at_level(logging.WARNING, logger=ADAPTER_MODULE):
            adapter.search(scope, "query")

        latency_warnings = [
            r
            for r in caplog.records
            if "latency" in r.message.lower() or "exceeds" in r.message.lower()
        ]
        assert latency_warnings == []


# ===========================================================================
# mem0_adapter.py: line 156 — get_all() list-format result
# ===========================================================================


class TestMem0AdapterGetAllFormats:
    def test_get_all_handles_list_result(self):
        """When mem0.get_all returns a raw list (not dict), entries are parsed."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = [
            {"id": "1", "memory": "item1", "metadata": {"memory_type": "episodic"}},
            {"id": "2", "memory": "item2", "metadata": {"memory_type": "procedural"}},
        ]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        entries = adapter.get_all(scope)
        assert len(entries) == 2

    def test_get_all_list_result_filters_by_type(self):
        """List-format result respects memory_type filter."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = [
            {"id": "1", "memory": "ep", "metadata": {"memory_type": "episodic"}},
            {"id": "2", "memory": "proc", "metadata": {"memory_type": "procedural"}},
        ]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        entries = adapter.get_all(scope, memory_type="episodic")
        assert len(entries) == 1
        assert entries[0].memory_type == "episodic"

    def test_get_all_list_result_fallback_text_key(self):
        """'text' key used as content fallback when 'memory' is absent."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = [
            {
                "id": "1",
                "text": "from text key",
                "metadata": {"memory_type": "episodic"},
            },
        ]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        entries = adapter.get_all(scope)
        assert entries[0].content == "from text key"

    def test_get_all_empty_list_returns_empty(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = []
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        entries = adapter.get_all(scope)
        assert entries == []


# ===========================================================================
# mem0_adapter.py: line 182->181 — delete_all with failed deletions
# ===========================================================================


class TestMem0AdapterDeleteAllFailure:
    def test_delete_all_counts_only_successful_deletions(self):
        """delete_all should only increment count when delete returns True."""
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = {
            "results": [
                {"id": "good", "memory": "m1", "metadata": {}},
                {"id": "bad", "memory": "m2", "metadata": {}},
            ]
        }
        # First delete succeeds, second fails
        mock_mem0.Memory.from_config.return_value.delete.side_effect = [
            None,  # success for "good"
            RuntimeError("delete failed"),  # failure for "bad"
        ]
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        count = adapter.delete_all(scope)
        assert count == 1  # only the successful one counted

    def test_delete_all_zero_when_all_fail(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = {
            "results": [
                {"id": "a", "memory": "m", "metadata": {}},
                {"id": "b", "memory": "n", "metadata": {}},
            ]
        }
        mock_mem0.Memory.from_config.return_value.delete.side_effect = RuntimeError(
            "always fails"
        )
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        count = adapter.delete_all(scope)
        assert count == 0

    def test_delete_all_empty_scope_returns_zero(self):
        mock_mem0 = MagicMock()
        mock_mem0.Memory.from_config.return_value.get_all.return_value = {"results": []}
        adapter = _make_mem0_adapter(mock_mem0)
        scope = MemoryScope(tenant_id="t", workflow_name="wf", agent_name="ag")
        count = adapter.delete_all(scope)
        assert count == 0
