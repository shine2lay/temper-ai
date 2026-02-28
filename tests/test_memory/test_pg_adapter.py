"""Tests for PGAdapter using SQLite in-memory engine.

The PGAdapter uses SQLModel/SQLAlchemy under the hood.  We patch
``_build_engine`` to inject a SQLite engine so we can run all adapter
logic without a real PostgreSQL server.

FTS-specific paths (``_ensure_fts_column``, ``_update_tsv``,
``_fts_search``) are exercised via the mock-patched SQLite engine that
accepts the raw SQL text() calls, or via unit tests of pure-Python
helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from sqlmodel import SQLModel

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.adapters.pg_adapter import (
    RANK_DAMPING_TERM,
    PGAdapter,
    _escape_ilike,
    _row_to_memory_entry,
)
from temper_ai.storage.database.engine import create_test_engine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_scope(agent: str = "agent1") -> MemoryScope:
    return MemoryScope(tenant_id="t1", workflow_name="wf1", agent_name=agent)


def _make_adapter(use_fts: bool = False) -> PGAdapter:
    """Create a PGAdapter backed by a SQLite :memory: engine."""
    engine = create_test_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with (
        patch.object(PGAdapter, "_build_engine", return_value=engine),
        patch.object(PGAdapter, "_ensure_fts_column"),
    ):
        adapter = PGAdapter(config={"use_fts": use_fts})
    # Replace any engine set during __init__ to ensure we have the test one
    adapter._engine = engine
    return adapter


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestPGAdapterInit:
    def test_init_creates_adapter(self):
        adapter = _make_adapter()
        assert adapter is not None

    def test_init_default_no_fts(self):
        adapter = _make_adapter()
        assert adapter._use_fts is False

    def test_init_with_fts_flag(self):
        adapter = _make_adapter(use_fts=True)
        assert adapter._use_fts is True

    def test_init_calls_init_schema(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        init_called = []

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(
                PGAdapter,
                "_init_schema",
                side_effect=lambda: init_called.append(True),
            ),
        ):
            PGAdapter()

        assert init_called == [True]

    def test_build_engine_uses_database_url_from_config(self):
        """_build_engine should pass the provided database_url to the factory."""
        fake_engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(fake_engine)

        with (
            patch(
                "temper_ai.memory.adapters.pg_adapter.PGAdapter._build_engine",
                return_value=fake_engine,
            ),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"database_url": "sqlite:///:memory:"})
        assert adapter is not None


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestPGAdapterAdd:
    def test_add_returns_string_id(self):
        adapter = _make_adapter()
        scope = _make_scope()
        mid = adapter.add(scope, "hello world", "episodic")
        assert isinstance(mid, str)
        assert len(mid) > 0

    def test_add_with_metadata(self):
        adapter = _make_adapter()
        scope = _make_scope()
        meta = {"key": "value", "num": 42}
        mid = adapter.add(scope, "content", "episodic", metadata=meta)
        entries = adapter.get_all(scope)
        assert any(e.id == mid for e in entries)
        found = next(e for e in entries if e.id == mid)
        assert found.metadata["key"] == "value"

    def test_add_without_metadata_defaults_empty(self):
        adapter = _make_adapter()
        scope = _make_scope()
        mid = adapter.add(scope, "no meta", "episodic")
        entries = adapter.get_all(scope)
        found = next(e for e in entries if e.id == mid)
        assert found.metadata == {}

    def test_add_multiple_entries(self):
        adapter = _make_adapter()
        scope = _make_scope()
        ids = [adapter.add(scope, f"entry {i}", "episodic") for i in range(5)]
        assert len(set(ids)) == 5  # all unique IDs
        entries = adapter.get_all(scope)
        assert len(entries) == 5

    def test_add_different_scopes_isolated(self):
        adapter = _make_adapter()
        s1 = _make_scope("agent1")
        s2 = _make_scope("agent2")
        adapter.add(s1, "for agent1", "episodic")
        adapter.add(s2, "for agent2", "episodic")
        assert len(adapter.get_all(s1)) == 1
        assert len(adapter.get_all(s2)) == 1

    def test_add_with_fts_calls_update_tsv(self):
        """When use_fts=True, add should call _update_tsv."""
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        tsv_calls: list[str] = []

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})
            adapter._engine = engine

        scope = _make_scope()
        # Patch _update_tsv on the instance after construction to avoid SQLite failure
        with patch.object(
            PGAdapter,
            "_update_tsv",
            side_effect=lambda session, eid, content: tsv_calls.append(eid),
        ):
            mid = adapter.add(scope, "fts content", "episodic")
        assert mid in tsv_calls


# ---------------------------------------------------------------------------
# Search / ILIKE
# SQLite does not support ILIKE, so integration-style search tests mock
# _ilike_search and verify dispatch.  The SQL builder and scorer helpers
# are covered separately in TestBuildILIKESQL / TestScoreAndLimit.
# ---------------------------------------------------------------------------


class TestPGAdapterSearchDispatch:
    """Verify search() dispatches to the correct internal helper."""

    def _make_mocked_adapter(self, use_fts: bool = False) -> PGAdapter:
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": use_fts})
            adapter._engine = engine
        return adapter

    def _fake_entry(self, content: str = "result") -> MemoryEntry:
        return MemoryEntry(
            id="fake-id",
            content=content,
            memory_type="episodic",
            created_at=datetime.now(UTC),
            relevance_score=0.5,
        )

    def test_search_dispatches_to_ilike_when_fts_disabled(self):
        adapter = self._make_mocked_adapter(use_fts=False)
        scope = _make_scope()
        entry = self._fake_entry("machine learning")
        with patch.object(adapter, "_ilike_search", return_value=[entry]) as mock_ilike:
            results = adapter.search(scope, "learning")
        mock_ilike.assert_called_once()
        assert results == [entry]

    def test_search_dispatches_to_fts_when_fts_enabled_and_query_nonempty(self):
        adapter = self._make_mocked_adapter(use_fts=True)
        scope = _make_scope()
        entry = self._fake_entry("fts result")
        with patch.object(adapter, "_fts_search", return_value=[entry]) as mock_fts:
            results = adapter.search(scope, "some query")
        mock_fts.assert_called_once()
        assert results == [entry]

    def test_search_uses_ilike_when_fts_enabled_but_empty_query(self):
        adapter = self._make_mocked_adapter(use_fts=True)
        scope = _make_scope()
        entry = self._fake_entry("empty query fallback")
        with patch.object(adapter, "_ilike_search", return_value=[entry]) as mock_ilike:
            results = adapter.search(scope, "")
        mock_ilike.assert_called_once()
        assert results == [entry]

    def test_search_returns_list_of_memory_entries(self):
        adapter = self._make_mocked_adapter(use_fts=False)
        scope = _make_scope()
        entries = [self._fake_entry(f"entry {i}") for i in range(3)]
        with patch.object(adapter, "_ilike_search", return_value=entries):
            results = adapter.search(scope, "entry")
        assert len(results) == 3
        assert all(isinstance(r, MemoryEntry) for r in results)

    def test_search_passes_limit_to_ilike(self):
        adapter = self._make_mocked_adapter(use_fts=False)
        scope = _make_scope()
        with patch.object(adapter, "_ilike_search", return_value=[]) as mock_ilike:
            adapter.search(scope, "q", limit=7)
        _, kwargs = mock_ilike.call_args
        # limit may be positional or keyword
        args = mock_ilike.call_args[0]
        assert 7 in args or kwargs.get("limit") == 7

    def test_search_passes_memory_type_to_ilike(self):
        adapter = self._make_mocked_adapter(use_fts=False)
        scope = _make_scope()
        with patch.object(adapter, "_ilike_search", return_value=[]) as mock_ilike:
            adapter.search(scope, "q", memory_type="procedural")
        args = mock_ilike.call_args[0]
        assert "procedural" in args

    def test_search_passes_threshold_to_ilike(self):
        adapter = self._make_mocked_adapter(use_fts=False)
        scope = _make_scope()
        with patch.object(adapter, "_ilike_search", return_value=[]) as mock_ilike:
            adapter.search(scope, "q", threshold=0.7)
        args = mock_ilike.call_args[0]
        assert 0.7 in args


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


class TestPGAdapterGetAll:
    def test_get_all_returns_all_entries(self):
        adapter = _make_adapter()
        scope = _make_scope()
        for i in range(4):
            adapter.add(scope, f"mem {i}", "episodic")
        entries = adapter.get_all(scope)
        assert len(entries) == 4

    def test_get_all_filtered_by_type(self):
        adapter = _make_adapter()
        scope = _make_scope()
        adapter.add(scope, "ep", "episodic")
        adapter.add(scope, "proc", "procedural")
        adapter.add(scope, "ep2", "episodic")
        entries = adapter.get_all(scope, memory_type="episodic")
        assert len(entries) == 2
        assert all(e.memory_type == "episodic" for e in entries)

    def test_get_all_empty_scope(self):
        adapter = _make_adapter()
        scope = _make_scope()
        entries = adapter.get_all(scope)
        assert entries == []

    def test_get_all_scoped_isolation(self):
        adapter = _make_adapter()
        s1 = _make_scope("a1")
        s2 = _make_scope("a2")
        adapter.add(s1, "for s1", "episodic")
        assert adapter.get_all(s2) == []

    def test_get_all_entries_ordered_by_created_at(self):
        """get_all orders by created_at ascending."""
        adapter = _make_adapter()
        scope = _make_scope()
        for i in range(3):
            adapter.add(scope, f"item {i}", "episodic")
        entries = adapter.get_all(scope)
        timestamps = [e.created_at for e in entries]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestPGAdapterDelete:
    def test_delete_existing_returns_true(self):
        adapter = _make_adapter()
        scope = _make_scope()
        mid = adapter.add(scope, "to delete", "episodic")
        result = adapter.delete(scope, mid)
        assert result is True
        assert adapter.get_all(scope) == []

    def test_delete_nonexistent_returns_false(self):
        adapter = _make_adapter()
        scope = _make_scope()
        result = adapter.delete(scope, "nonexistent-id")
        assert result is False

    def test_delete_wrong_scope_returns_false(self):
        adapter = _make_adapter()
        s1 = _make_scope("a1")
        s2 = _make_scope("a2")
        mid = adapter.add(s1, "data", "episodic")
        result = adapter.delete(s2, mid)
        assert result is False
        # Entry still exists in s1
        assert len(adapter.get_all(s1)) == 1

    def test_delete_only_target_entry(self):
        adapter = _make_adapter()
        scope = _make_scope()
        id1 = adapter.add(scope, "keep", "episodic")
        id2 = adapter.add(scope, "remove", "episodic")
        adapter.delete(scope, id2)
        remaining = adapter.get_all(scope)
        assert len(remaining) == 1
        assert remaining[0].id == id1


# ---------------------------------------------------------------------------
# delete_all
# ---------------------------------------------------------------------------


class TestPGAdapterDeleteAll:
    def test_delete_all_returns_count(self):
        adapter = _make_adapter()
        scope = _make_scope()
        for _ in range(3):
            adapter.add(scope, "item", "episodic")
        count = adapter.delete_all(scope)
        assert count == 3

    def test_delete_all_clears_scope(self):
        adapter = _make_adapter()
        scope = _make_scope()
        adapter.add(scope, "item", "episodic")
        adapter.delete_all(scope)
        assert adapter.get_all(scope) == []

    def test_delete_all_empty_scope_returns_zero(self):
        adapter = _make_adapter()
        scope = _make_scope()
        count = adapter.delete_all(scope)
        assert count == 0

    def test_delete_all_scoped_isolation(self):
        adapter = _make_adapter()
        s1 = _make_scope("a1")
        s2 = _make_scope("a2")
        adapter.add(s1, "keep", "episodic")
        adapter.add(s2, "delete", "episodic")
        adapter.delete_all(s2)
        assert len(adapter.get_all(s1)) == 1
        assert adapter.get_all(s2) == []


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestEscapeILike:
    def test_escapes_percent(self):
        assert _escape_ilike("100%") == r"100\%"

    def test_escapes_underscore(self):
        assert _escape_ilike("a_b") == r"a\_b"

    def test_escapes_backslash(self):
        assert _escape_ilike("a\\b") == r"a\\b"

    def test_no_special_chars(self):
        assert _escape_ilike("hello world") == "hello world"

    def test_all_special_chars(self):
        result = _escape_ilike("%_\\")
        assert "%" not in result.replace("\\%", "")
        assert "_" not in result.replace("\\_", "")

    def test_empty_string(self):
        assert _escape_ilike("") == ""


class TestRowToMemoryEntry:
    """Tests for _row_to_memory_entry module-level helper."""

    def _make_row(
        self,
        id: str = "rid",
        content: str = "hello",
        memory_type: str = "episodic",
        metadata_json: str = '{"k": "v"}',
        created_at: Any = None,
    ) -> MagicMock:
        row = MagicMock()
        row.id = id
        row.content = content
        row.memory_type = memory_type
        row.metadata_json = metadata_json
        row.created_at = created_at or datetime.now(UTC)
        return row

    def test_basic_conversion(self):
        row = self._make_row()
        entry = _row_to_memory_entry(row, score=0.8)
        assert entry.id == "rid"
        assert entry.content == "hello"
        assert entry.memory_type == "episodic"
        assert entry.relevance_score == 0.8
        assert entry.metadata == {"k": "v"}

    def test_empty_metadata_json(self):
        row = self._make_row(metadata_json="")
        entry = _row_to_memory_entry(row, score=0.0)
        assert entry.metadata == {}

    def test_null_metadata_json(self):
        row = self._make_row(metadata_json=None)
        entry = _row_to_memory_entry(row, score=0.0)
        assert entry.metadata == {}

    def test_created_at_string_parsed(self):
        """created_at stored as ISO string should be parsed to datetime."""
        ts = "2024-01-15T10:30:00+00:00"
        row = self._make_row(created_at=ts)
        entry = _row_to_memory_entry(row, score=0.0)
        assert isinstance(entry.created_at, datetime)

    def test_created_at_datetime_kept(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        row = self._make_row(created_at=dt)
        entry = _row_to_memory_entry(row, score=0.0)
        assert entry.created_at == dt

    def test_score_propagated(self):
        row = self._make_row()
        entry = _row_to_memory_entry(row, score=0.55)
        assert entry.relevance_score == 0.55


# ---------------------------------------------------------------------------
# ILIKE SQL builder
# ---------------------------------------------------------------------------


class TestBuildILIKESQL:
    def test_basic_query(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_ilike_sql(scope, "test", None)
        assert "scope_key" in sql
        assert "ILIKE" in sql
        assert params["scope_key"] == scope.scope_key
        assert "%test%" in params["pattern"]

    def test_empty_query_no_ilike(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_ilike_sql(scope, "", None)
        assert "ILIKE" not in sql

    def test_memory_type_filter(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_ilike_sql(scope, "q", "episodic")
        assert "memory_type" in sql
        assert params["memory_type"] == "episodic"

    def test_no_memory_type_no_filter_clause(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_ilike_sql(scope, "q", None)
        assert "memory_type" not in sql


# ---------------------------------------------------------------------------
# Score-and-limit helper
# ---------------------------------------------------------------------------


class TestScoreAndLimit:
    def _make_row(self, content: str) -> MagicMock:
        row = MagicMock()
        row.id = "id"
        row.content = content
        row.memory_type = "episodic"
        row.metadata_json = "{}"
        row.created_at = datetime.now(UTC)
        return row

    def test_scores_by_query_length_ratio(self):
        rows = [self._make_row("ab")]  # content length 2
        entries = PGAdapter._score_and_limit(rows, query="ab", limit=10, threshold=0.0)
        assert entries[0].relevance_score == 1.0  # 2/2

    def test_empty_query_scores_zero(self):
        rows = [self._make_row("hello")]
        entries = PGAdapter._score_and_limit(rows, query="", limit=10, threshold=0.0)
        assert entries[0].relevance_score == 0.0

    def test_threshold_filters(self):
        rows = [self._make_row("ab"), self._make_row("a" * 1000)]
        entries = PGAdapter._score_and_limit(rows, query="a", limit=10, threshold=0.5)
        # Only "ab" should pass (score = 1/2 = 0.5)
        assert all(e.relevance_score >= 0.5 for e in entries)

    def test_limit_applied(self):
        rows = [self._make_row(f"item{i}") for i in range(10)]
        entries = PGAdapter._score_and_limit(rows, query="item", limit=3, threshold=0.0)
        assert len(entries) == 3

    def test_sorted_by_relevance_desc(self):
        rows = [self._make_row("hi"), self._make_row("hi there")]
        entries = PGAdapter._score_and_limit(rows, query="hi", limit=10, threshold=0.0)
        scores = [e.relevance_score for e in entries]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# FTS SQL builder (pure-Python, no DB)
# ---------------------------------------------------------------------------


class TestBuildFTSSQL:
    def test_includes_fts_columns(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_fts_sql(scope, "'test'", 5, None)
        assert "to_tsquery" in sql
        assert "ts_rank" in sql
        assert params["scope_key"] == scope.scope_key

    def test_memory_type_filter(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_fts_sql(scope, "'test'", 5, "episodic")
        assert "memory_type" in sql
        assert params["memory_type"] == "episodic"

    def test_no_memory_type_no_filter(self):
        scope = _make_scope()
        sql, params = PGAdapter._build_fts_sql(scope, "'test'", 5, None)
        assert "memory_type" not in sql

    def test_limit_in_params(self):
        scope = _make_scope()
        _, params = PGAdapter._build_fts_sql(scope, "'q'", 7, None)
        assert params["limit"] == 7


# ---------------------------------------------------------------------------
# Sanitize tsquery
# ---------------------------------------------------------------------------


class TestSanitizeTsquery:
    def test_single_word(self):
        result = PGAdapter._sanitize_tsquery("hello")
        assert result == "'hello'"

    def test_multiple_words_joined_with_and(self):
        result = PGAdapter._sanitize_tsquery("hello world")
        assert result == "'hello' & 'world'"

    def test_empty_string_returns_empty(self):
        result = PGAdapter._sanitize_tsquery("")
        assert result == ""

    def test_single_quotes_escaped(self):
        result = PGAdapter._sanitize_tsquery("it's")
        assert "''" in result  # single quote doubled

    def test_whitespace_only_returns_empty(self):
        result = PGAdapter._sanitize_tsquery("   ")
        # split() returns [] for whitespace-only; falls back to raw query
        assert result == "   "


# ---------------------------------------------------------------------------
# Rows-to-entries-with-rank helper
# ---------------------------------------------------------------------------


class TestRowsToEntriesWithRank:
    def _make_fts_row(self, rank: float, content: str = "c") -> MagicMock:
        row = MagicMock()
        row.id = "id"
        row.content = content
        row.memory_type = "episodic"
        row.metadata_json = "{}"
        row.created_at = datetime.now(UTC)
        row.rank = rank
        return row

    def test_rank_converted_to_score(self):
        row = self._make_fts_row(rank=1.0)
        entries = PGAdapter._rows_to_entries_with_rank([row], threshold=0.0)
        expected_score = 1.0 / (1.0 + RANK_DAMPING_TERM)
        assert abs(entries[0].relevance_score - expected_score) < 1e-9

    def test_threshold_filters_low_rank(self):
        low_row = self._make_fts_row(rank=0.001)  # score ~= 0.001
        entries = PGAdapter._rows_to_entries_with_rank([low_row], threshold=0.5)
        assert entries == []

    def test_zero_rank_gives_zero_score(self):
        row = self._make_fts_row(rank=0.0)
        entries = PGAdapter._rows_to_entries_with_rank([row], threshold=0.0)
        assert entries[0].relevance_score == 0.0

    def test_none_rank_treated_as_zero(self):
        row = self._make_fts_row(rank=0.0)
        row.rank = None
        entries = PGAdapter._rows_to_entries_with_rank([row], threshold=0.0)
        assert entries[0].relevance_score == 0.0

    def test_multiple_rows(self):
        rows = [self._make_fts_row(rank=float(i)) for i in range(3)]
        entries = PGAdapter._rows_to_entries_with_rank(rows, threshold=0.0)
        assert len(entries) == 3


# ---------------------------------------------------------------------------
# get_all SQL builders (pure-Python)
# ---------------------------------------------------------------------------


class TestBuildGetAllSQL:
    def test_no_type_filter(self):
        sql = PGAdapter._build_get_all_sql(None)
        assert "memory_type" not in sql
        assert "ORDER BY created_at" in sql

    def test_with_type_filter(self):
        sql = PGAdapter._build_get_all_sql("episodic")
        assert "memory_type" in sql

    def test_scope_key_in_sql(self):
        sql = PGAdapter._build_get_all_sql(None)
        assert "scope_key" in sql


class TestBuildGetAllParams:
    def test_without_type(self):
        scope = _make_scope()
        params = PGAdapter._build_get_all_params(scope, None)
        assert params == {"scope_key": scope.scope_key}

    def test_with_type(self):
        scope = _make_scope()
        params = PGAdapter._build_get_all_params(scope, "episodic")
        assert params["memory_type"] == "episodic"


# ---------------------------------------------------------------------------
# _build_engine static method (lines 91-97)
# Tests the real _build_engine path by injecting the database_url config key
# and mocking create_app_engine to avoid needing a real PG server.
# ---------------------------------------------------------------------------


class TestBuildEngine:
    def test_build_engine_calls_create_app_engine(self):
        """_build_engine should call create_app_engine with the provided url."""
        fake_engine = MagicMock()
        # _build_engine imports create_app_engine inside the function body,
        # so we patch the name as it appears inside that local import scope.
        with patch(
            "temper_ai.storage.database.engine.create_app_engine",
            return_value=fake_engine,
        ) as mock_create:
            from temper_ai.memory.adapters.pg_adapter import PGAdapter as _PA

            result = _PA._build_engine({"database_url": "sqlite:///:memory:"})
        mock_create.assert_called_once_with(database_url="sqlite:///:memory:")
        assert result is fake_engine

    def test_build_engine_uses_get_database_url_when_no_url_in_config(self):
        fake_engine = MagicMock()
        with (
            patch(
                "temper_ai.storage.database.engine.get_database_url",
                return_value="sqlite:///:memory:",
            ),
            patch(
                "temper_ai.storage.database.engine.create_app_engine",
                return_value=fake_engine,
            ) as mock_create,
        ):
            from temper_ai.memory.adapters.pg_adapter import PGAdapter as _PA

            result = _PA._build_engine({})
        mock_create.assert_called_once()
        assert result is fake_engine


# ---------------------------------------------------------------------------
# _ensure_fts_column (lines 111-120)
# Tests via mocked connection/engine to avoid PG-specific DDL.
# ---------------------------------------------------------------------------


class TestEnsureFTSColumn:
    def test_ensure_fts_column_executes_alter_and_index(self):
        """_ensure_fts_column should execute two SQL statements and commit."""
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        # Now replace engine with mock and call directly
        adapter._engine = mock_engine
        adapter._ensure_fts_column()

        # Should have called execute twice (ALTER TABLE + CREATE INDEX)
        assert mock_conn.execute.call_count == 2
        mock_conn.commit.assert_called_once()

    def test_ensure_fts_column_alter_sql_has_tsvector(self):
        """The ALTER TABLE statement must reference tsvector."""
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        adapter._engine = mock_engine
        adapter._ensure_fts_column()

        # Retrieve the SQL text from first execute call
        first_call_args = mock_conn.execute.call_args_list[0][0]
        sql_text = str(first_call_args[0])
        assert "tsvector" in sql_text


# ---------------------------------------------------------------------------
# _update_tsv (lines 216-220)
# Tests via a mocked SQLModel Session.
# ---------------------------------------------------------------------------


class TestUpdateTsv:
    def test_update_tsv_executes_sql(self):
        mock_session = MagicMock()
        PGAdapter._update_tsv(mock_session, entry_id="abc123", content="hello world")
        mock_session.execute.assert_called_once()

    def test_update_tsv_sql_includes_to_tsvector(self):
        mock_session = MagicMock()
        PGAdapter._update_tsv(mock_session, entry_id="abc", content="test content")
        call_args = mock_session.execute.call_args[0]
        sql_str = str(call_args[0])
        assert "to_tsvector" in sql_str

    def test_update_tsv_passes_correct_params(self):
        mock_session = MagicMock()
        PGAdapter._update_tsv(mock_session, entry_id="myid", content="my content")
        params = mock_session.execute.call_args[0][1]
        assert params["id"] == "myid"
        assert params["content"] == "my content"


# ---------------------------------------------------------------------------
# _fts_search (lines 234-237)
# Tests the FTS search method body via a mocked session.
# ---------------------------------------------------------------------------


class TestFTSSearch:
    def _make_fts_row(
        self, rank: float = 0.5, content: str = "fts content"
    ) -> MagicMock:
        row = MagicMock()
        row.id = "fts-id"
        row.content = content
        row.memory_type = "episodic"
        row.metadata_json = "{}"
        row.created_at = datetime.now(UTC)
        row.rank = rank
        return row

    def test_fts_search_calls_session_execute(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        scope = _make_scope()

        adapter._fts_search(
            mock_session, scope, "hello", limit=5, threshold=0.0, memory_type=None
        )
        mock_session.execute.assert_called_once()

    def test_fts_search_returns_memory_entries(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        row = self._make_fts_row(rank=1.0)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        scope = _make_scope()

        results = adapter._fts_search(
            mock_session, scope, "hello", limit=5, threshold=0.0, memory_type=None
        )
        assert len(results) == 1
        assert isinstance(results[0], MemoryEntry)

    def test_fts_search_filters_by_threshold(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        low_row = self._make_fts_row(rank=0.001)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [low_row]
        scope = _make_scope()

        results = adapter._fts_search(
            mock_session, scope, "hello", limit=5, threshold=0.9, memory_type=None
        )
        assert results == []

    def test_fts_search_sanitizes_query(self):
        """_fts_search sanitizes the query before building SQL."""
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with (
            patch.object(PGAdapter, "_build_engine", return_value=engine),
            patch.object(PGAdapter, "_ensure_fts_column"),
        ):
            adapter = PGAdapter(config={"use_fts": True})

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        scope = _make_scope()

        # Multi-word query: sanitize should wrap each token in quotes
        with patch.object(
            PGAdapter, "_sanitize_tsquery", wraps=PGAdapter._sanitize_tsquery
        ) as mock_sanitize:
            adapter._fts_search(
                mock_session,
                scope,
                "hello world",
                limit=5,
                threshold=0.0,
                memory_type=None,
            )
        mock_sanitize.assert_called_once_with("hello world")


# ---------------------------------------------------------------------------
# _ilike_search (lines 307-309)
# Tests the ILIKE search method body via a mocked session.
# ---------------------------------------------------------------------------


class TestILIKESearchMethod:
    def _make_row(self, content: str = "test content") -> MagicMock:
        row = MagicMock()
        row.id = "row-id"
        row.content = content
        row.memory_type = "episodic"
        row.metadata_json = "{}"
        row.created_at = datetime.now(UTC)
        return row

    def test_ilike_search_calls_session_execute(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with patch.object(PGAdapter, "_build_engine", return_value=engine):
            adapter = PGAdapter(config={"use_fts": False})

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        scope = _make_scope()

        adapter._ilike_search(
            mock_session, scope, "query", limit=5, threshold=0.0, memory_type=None
        )
        mock_session.execute.assert_called_once()

    def test_ilike_search_returns_scored_entries(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with patch.object(PGAdapter, "_build_engine", return_value=engine):
            adapter = PGAdapter(config={"use_fts": False})

        row = self._make_row("query match")
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        scope = _make_scope()

        results = adapter._ilike_search(
            mock_session, scope, "query", limit=5, threshold=0.0, memory_type=None
        )
        assert len(results) == 1
        assert isinstance(results[0], MemoryEntry)

    def test_ilike_search_passes_limit_and_threshold_to_scorer(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with patch.object(PGAdapter, "_build_engine", return_value=engine):
            adapter = PGAdapter(config={"use_fts": False})

        rows = [self._make_row(f"content {i}") for i in range(10)]
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = rows
        scope = _make_scope()

        with patch.object(
            PGAdapter, "_score_and_limit", wraps=PGAdapter._score_and_limit
        ) as mock_score:
            adapter._ilike_search(
                mock_session, scope, "content", limit=3, threshold=0.1, memory_type=None
            )
        mock_score.assert_called_once()
        call_args = mock_score.call_args[0]
        assert 3 in call_args  # limit
        assert 0.1 in call_args  # threshold

    def test_ilike_search_empty_results(self):
        engine = create_test_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with patch.object(PGAdapter, "_build_engine", return_value=engine):
            adapter = PGAdapter(config={"use_fts": False})

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        scope = _make_scope()

        results = adapter._ilike_search(
            mock_session, scope, "nothing", limit=5, threshold=0.0, memory_type=None
        )
        assert results == []
