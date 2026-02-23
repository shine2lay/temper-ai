"""PostgreSQL-backed memory adapter with optional full-text search.

Uses SQLAlchemy + SQLModel with the centralized engine factory.
Supports PostgreSQL ``to_tsvector``/``to_tsquery`` for FTS when enabled,
and standard ``ILIKE`` for substring search (the default).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, Index, String, Text, text
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import DEFAULT_RETRIEVAL_LIMIT

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------

FTS_CONFIG = "english"
"""PostgreSQL text search configuration used for to_tsvector / to_tsquery."""

RANK_DAMPING_TERM = 1.0
"""Added to ts_rank to prevent division by zero: score = rank / (rank + 1)."""

LIKE_ESCAPE_CHAR = "\\"
"""Escape character used in ILIKE patterns."""

_WHERE_MEMORY_TYPE = " AND memory_type = :memory_type"
"""Reusable SQL clause for filtering by memory_type."""


# -- SQLModel table -----------------------------------------------------------


class MemoryRecord(SQLModel, table=True):
    """SQLModel table for persistent memory records."""

    __tablename__ = "memory_records"
    __table_args__ = (
        Index("idx_mr_scope_key", "scope_key"),
        Index("idx_mr_memory_type", "memory_type"),
        Index("idx_mr_created_at", "created_at"),
    )

    id: str = Field(primary_key=True)
    scope_key: str = Field(sa_column=Column(String, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    memory_type: str = Field(sa_column=Column(String, nullable=False))
    metadata_json: str = Field(default="{}", sa_column=Column(Text, default="{}"))
    relevance_score: float = Field(default=0.0, sa_column=Column(Float, default=0.0))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


# -- Adapter ------------------------------------------------------------------


class PGAdapter:
    """PostgreSQL-backed memory store.

    Search uses ``ILIKE`` by default.  Set ``config["use_fts"] = True``
    to use PostgreSQL full-text search with ``to_tsvector`` / ``to_tsquery``.

    The FTS approach uses raw SQL ``text()`` with bind parameters because
    tsvector/tsquery are PostgreSQL-specific and not modelled in SQLModel.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self._use_fts: bool = config.get("use_fts", False)
        self._engine: Engine = self._build_engine(config)
        self._init_schema()

    # ------------------------------------------------------------------
    # Engine / Schema
    # ------------------------------------------------------------------

    @staticmethod
    def _build_engine(config: dict[str, Any]) -> Engine:
        """Create the SQLAlchemy engine via the centralized factory."""
        from temper_ai.storage.database.engine import (
            create_app_engine,
            get_database_url,
        )

        database_url = config.get("database_url") or get_database_url()
        return create_app_engine(database_url=database_url)

    def _init_schema(self) -> None:
        """Ensure the memory_records table exists."""
        SQLModel.metadata.create_all(self._engine, tables=[MemoryRecord.__table__])  # type: ignore[attr-defined]
        if self._use_fts:
            self._ensure_fts_column()

    def _ensure_fts_column(self) -> None:
        """Add a tsvector column and GIN index if not already present.

        Uses raw DDL because SQLModel has no native tsvector type.
        Idempotent — safe to call on every startup.
        """
        add_column_sql = text(
            "ALTER TABLE memory_records " "ADD COLUMN IF NOT EXISTS tsv tsvector"
        )
        create_index_sql = text(
            "CREATE INDEX IF NOT EXISTS idx_mr_tsv " "ON memory_records USING gin(tsv)"
        )
        with self._engine.connect() as conn:
            conn.execute(add_column_sql)
            conn.execute(create_index_sql)
            conn.commit()

    # ------------------------------------------------------------------
    # MemoryStoreProtocol
    # ------------------------------------------------------------------

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a memory and return its ID."""
        entry_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        meta_json = json.dumps(metadata or {})

        record = MemoryRecord(
            id=entry_id,
            scope_key=scope.scope_key,
            content=content,
            memory_type=memory_type,
            metadata_json=meta_json,
            created_at=now,
        )

        with Session(self._engine) as session:
            session.add(record)
            if self._use_fts:
                self._update_tsv(session, entry_id, content)
            session.commit()
        return entry_id

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories within a scope.

        Uses PostgreSQL full-text search when ``use_fts`` is enabled and
        a non-empty query is provided; otherwise falls back to ILIKE.
        """
        with Session(self._engine) as session:
            if self._use_fts and query:
                return self._fts_search(
                    session, scope, query, limit, threshold, memory_type
                )
            return self._ilike_search(
                session, scope, query, limit, threshold, memory_type
            )

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Return all memories for a scope, optionally filtered by type."""
        with Session(self._engine) as session:
            stmt = text(self._build_get_all_sql(memory_type))
            params = self._build_get_all_params(scope, memory_type)
            rows = session.execute(stmt, params).fetchall()
            return [_row_to_memory_entry(row, score=0.0) for row in rows]

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """Delete a single memory by ID. Returns True if found."""
        with Session(self._engine) as session:
            stmt = text(
                "DELETE FROM memory_records "
                "WHERE id = :id AND scope_key = :scope_key"
            )
            result = session.execute(
                stmt, {"id": memory_id, "scope_key": scope.scope_key}
            )
            session.commit()
            return bool(getattr(result, "rowcount", 0) > 0)

    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope. Returns count deleted."""
        with Session(self._engine) as session:
            stmt = text("DELETE FROM memory_records WHERE scope_key = :scope_key")
            result = session.execute(stmt, {"scope_key": scope.scope_key})
            session.commit()
            return int(getattr(result, "rowcount", 0))

    # ------------------------------------------------------------------
    # FTS helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_tsv(session: Session, entry_id: str, content: str) -> None:
        """Populate the tsvector column for a single record."""
        stmt = text(
            "UPDATE memory_records SET tsv = to_tsvector(:config, :content) "
            "WHERE id = :id"
        )
        session.execute(
            stmt, {"config": FTS_CONFIG, "content": content, "id": entry_id}
        )

    def _fts_search(
        self,
        session: Session,
        scope: MemoryScope,
        query: str,
        limit: int,
        threshold: float,
        memory_type: str | None,
    ) -> list[MemoryEntry]:
        """Full-text search via PostgreSQL to_tsvector / to_tsquery."""
        safe_query = self._sanitize_tsquery(query)
        sql, params = self._build_fts_sql(scope, safe_query, limit, memory_type)
        rows = session.execute(text(sql), params).fetchall()
        return self._rows_to_entries_with_rank(rows, threshold)

    @staticmethod
    def _build_fts_sql(
        scope: MemoryScope,
        safe_query: str,
        limit: int,
        memory_type: str | None,
    ) -> tuple[str, dict[str, Any]]:
        """Build the FTS SQL and parameter dict."""
        sql = (
            "SELECT *, ts_rank(tsv, to_tsquery(:config, :query)) AS rank "
            "FROM memory_records "
            "WHERE scope_key = :scope_key "
            "AND tsv @@ to_tsquery(:config, :query)"
        )
        params: dict[str, Any] = {
            "config": FTS_CONFIG,
            "query": safe_query,
            "scope_key": scope.scope_key,
        }
        if memory_type:
            sql += _WHERE_MEMORY_TYPE
            params["memory_type"] = memory_type
        sql += " ORDER BY rank DESC LIMIT :limit"
        params["limit"] = limit
        return sql, params

    @staticmethod
    def _rows_to_entries_with_rank(
        rows: Sequence[Any],
        threshold: float,
    ) -> list[MemoryEntry]:
        """Convert ranked FTS result rows into MemoryEntry list."""
        entries: list[MemoryEntry] = []
        for row in rows:
            rank_val = row.rank if row.rank else 0.0
            score = rank_val / (rank_val + RANK_DAMPING_TERM)
            if score >= threshold:
                entries.append(_row_to_memory_entry(row, score))
        return entries

    @staticmethod
    def _sanitize_tsquery(query: str) -> str:
        """Sanitize a user query for safe use with ``to_tsquery``.

        Wraps each whitespace-delimited token in single quotes and joins
        with ``&`` so that ``to_tsquery`` treats them as AND-ed lexemes.
        Falls back to the raw query when empty after split.
        """
        tokens = query.split()
        if not tokens:
            return query
        escaped = ["'" + token.replace("'", "''") + "'" for token in tokens]
        return " & ".join(escaped)

    # ------------------------------------------------------------------
    # ILIKE helpers
    # ------------------------------------------------------------------

    def _ilike_search(
        self,
        session: Session,
        scope: MemoryScope,
        query: str,
        limit: int,
        threshold: float,
        memory_type: str | None,
    ) -> list[MemoryEntry]:
        """Substring search via ILIKE with client-side relevance scoring."""
        sql, params = self._build_ilike_sql(scope, query, memory_type)
        rows = session.execute(text(sql), params).fetchall()
        return self._score_and_limit(rows, query, limit, threshold)

    @staticmethod
    def _build_ilike_sql(
        scope: MemoryScope,
        query: str,
        memory_type: str | None,
    ) -> tuple[str, dict[str, Any]]:
        """Build the ILIKE SQL and parameter dict."""
        sql = "SELECT * FROM memory_records WHERE scope_key = :scope_key"
        params: dict[str, Any] = {"scope_key": scope.scope_key}
        if memory_type:
            sql += _WHERE_MEMORY_TYPE
            params["memory_type"] = memory_type
        if query:
            escaped = _escape_ilike(query)
            sql += " AND content ILIKE :pattern ESCAPE :escape"
            params["pattern"] = f"%{escaped}%"
            params["escape"] = LIKE_ESCAPE_CHAR
        return sql, params

    @staticmethod
    def _score_and_limit(
        rows: Sequence[Any],
        query: str,
        limit: int,
        threshold: float,
    ) -> list[MemoryEntry]:
        """Apply relevance scoring and limit to ILIKE results."""
        query_len = len(query) if query else 0
        entries: list[MemoryEntry] = []
        for row in rows:
            content_len = max(len(row.content), 1)
            score = query_len / content_len if query_len else 0.0
            score = min(score, 1.0)
            if score >= threshold:
                entries.append(_row_to_memory_entry(row, score))
        entries.sort(key=lambda e: e.relevance_score, reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # get_all helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_get_all_sql(memory_type: str | None) -> str:
        """Build SQL for get_all query."""
        sql = "SELECT * FROM memory_records WHERE scope_key = :scope_key"
        if memory_type:
            sql += _WHERE_MEMORY_TYPE
        sql += " ORDER BY created_at"
        return sql

    @staticmethod
    def _build_get_all_params(
        scope: MemoryScope,
        memory_type: str | None,
    ) -> dict[str, Any]:
        """Build parameter dict for get_all query."""
        params: dict[str, Any] = {"scope_key": scope.scope_key}
        if memory_type:
            params["memory_type"] = memory_type
        return params


# -- Module-level helpers --------------------------------------------------


def _row_to_memory_entry(row: Any, score: float) -> MemoryEntry:
    """Convert a SQLAlchemy result row into a MemoryEntry."""
    meta = json.loads(row.metadata_json) if row.metadata_json else {}
    created = row.created_at
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    return MemoryEntry(
        id=row.id,
        content=row.content,
        memory_type=row.memory_type,
        metadata=meta,
        created_at=created,
        relevance_score=score,
    )


def _escape_ilike(value: str) -> str:
    """Escape special ILIKE pattern characters."""
    return (
        value.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR + LIKE_ESCAPE_CHAR)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )
