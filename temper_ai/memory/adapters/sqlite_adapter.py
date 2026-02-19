"""SQLite-backed memory adapter with optional FTS5 full-text search.

Zero external dependencies — uses Python's built-in sqlite3 module.
Data is stored in a separate ``memory.db`` file (configurable via
``config["db_path"]``) so it never pollutes the observability DB.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import DEFAULT_MEMORY_DB_PATH, DEFAULT_RETRIEVAL_LIMIT

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS memory_records (
    id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    relevance_score REAL DEFAULT 0.0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_records(scope_key);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_records(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_records(created_at);
"""

_FTS_SCHEMA_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    id UNINDEXED, scope_key UNINDEXED, content, memory_type UNINDEXED
);
"""


class SQLiteAdapter:
    """SQLite-backed memory store. Thread-safe via RLock.

    Search uses ``LIKE`` by default.  Set ``config["use_fts"] = True``
    to create an FTS5 virtual table and use ``MATCH`` for search.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}
        self._db_path: str = config.get("db_path", DEFAULT_MEMORY_DB_PATH)
        self._use_fts: bool = config.get("use_fts", False)
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection / Schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a new connection with WAL mode and row_factory."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """Create tables and optional FTS5 virtual table."""
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            if self._use_fts:
                conn.executescript(_FTS_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # MemoryStoreProtocol
    # ------------------------------------------------------------------

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory and return its ID."""
        entry_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO memory_records"
                    " (id, scope_key, content, memory_type, metadata_json, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (entry_id, scope.scope_key, content, memory_type, meta_json, now),
                )
                if self._use_fts:
                    conn.execute(
                        "INSERT INTO memory_fts (id, scope_key, content, memory_type)"
                        " VALUES (?, ?, ?, ?)",
                        (entry_id, scope.scope_key, content, memory_type),
                    )
                conn.commit()
            finally:
                conn.close()
        return entry_id

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Search memories within a scope. Uses FTS5 MATCH when enabled."""
        with self._lock:
            conn = self._connect()
            try:
                if self._use_fts and query:
                    entries = self._fts_search(conn, scope, query, limit, threshold, memory_type)
                else:
                    entries = self._like_search(conn, scope, query, limit, threshold, memory_type)
            finally:
                conn.close()
        return entries

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Return all memories for a scope, optionally filtered by type."""
        with self._lock:
            conn = self._connect()
            try:
                sql = "SELECT * FROM memory_records WHERE scope_key = ?"
                params: list = [scope.scope_key]
                if memory_type:
                    sql += " AND memory_type = ?"
                    params.append(memory_type)
                sql += " ORDER BY created_at"
                rows = conn.execute(sql, params).fetchall()
                entries = [self._row_to_entry(row) for row in rows]
            finally:
                conn.close()
        return entries

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """Delete a single memory by ID. Returns True if found."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM memory_records WHERE id = ? AND scope_key = ?",
                    (memory_id, scope.scope_key),
                )
                if self._use_fts:
                    conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope. Returns count deleted."""
        with self._lock:
            conn = self._connect()
            try:
                if self._use_fts:
                    ids = conn.execute(
                        "SELECT id FROM memory_records WHERE scope_key = ?",
                        (scope.scope_key,),
                    ).fetchall()
                    for row in ids:
                        conn.execute("DELETE FROM memory_fts WHERE id = ?", (row["id"],))
                cursor = conn.execute(
                    "DELETE FROM memory_records WHERE scope_key = ?",
                    (scope.scope_key,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _like_search(
        self, conn: sqlite3.Connection, scope: MemoryScope,
        query: str, limit: int, threshold: float,
        memory_type: Optional[str],
    ) -> List[MemoryEntry]:
        """Substring search via SQL LIKE with relevance scoring."""
        sql = "SELECT * FROM memory_records WHERE scope_key = ?"
        params: list = [scope.scope_key]
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        if query:
            sql += " AND content LIKE ? ESCAPE '\\'"
            params.append(f"%{self._escape_like(query)}%")

        rows = conn.execute(sql, params).fetchall()
        query_len = len(query) if query else 0
        entries: List[MemoryEntry] = []
        for row in rows:
            score = query_len / max(len(row["content"]), 1) if query_len else 0.0
            score = min(score, 1.0)
            if score >= threshold:
                entries.append(self._row_to_entry(row, score))

        entries.sort(key=lambda e: e.relevance_score, reverse=True)
        return entries[:limit]

    def _fts_search(
        self, conn: sqlite3.Connection, scope: MemoryScope,
        query: str, limit: int, threshold: float,
        memory_type: Optional[str],
    ) -> List[MemoryEntry]:
        """Full-text search via FTS5 MATCH."""
        sql = (
            "SELECT r.*, f.rank FROM memory_fts f"
            " JOIN memory_records r ON f.id = r.id"
            " WHERE memory_fts MATCH ? AND r.scope_key = ?"
        )
        safe_query = '"' + query.replace('"', '""') + '"'
        params: list = [safe_query, scope.scope_key]
        if memory_type:
            sql += " AND r.memory_type = ?"
            params.append(memory_type)
        sql += " ORDER BY f.rank LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        entries: List[MemoryEntry] = []
        for row in rows:
            rank_val = abs(row["rank"]) if row["rank"] else 1.0
            score = 1.0 / (1.0 + rank_val)
            if score >= threshold:
                entries.append(self._row_to_entry(row, score))
        return entries

    @staticmethod
    def _row_to_entry(row: sqlite3.Row, score: float = 0.0) -> MemoryEntry:
        """Convert a database row to a MemoryEntry."""
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            metadata=meta,
            created_at=datetime.fromisoformat(row["created_at"]),
            relevance_score=score,
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape special LIKE characters."""
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
