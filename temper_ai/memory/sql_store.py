"""SQL memory store — persistence on the database temper already uses.

The default store was `InMemoryStore`, a dict living in one process. That was
survivable when the server ran every workflow itself, but with the
server/worker split each run executes in its own process (often its own
container), so an agent with memory enabled recalled nothing from the run
before — memory silently did nothing while appearing configured.

This backend keeps memories in the same database as events and checkpoints,
so they outlive the process, the container and a restart.

Retrieval is lexical (recency, plus substring matching for `search`), which
is what `InMemoryStore` did too. Semantic recall needs embeddings and belongs
in the mem0 backend.
"""

from __future__ import annotations

import logging

from sqlmodel import col, delete, select

from temper_ai.database import get_session
from temper_ai.memory.base import MemoryEntry, MemoryStoreBase
from temper_ai.memory.models import Memory

logger = logging.getLogger(__name__)


class SqlMemoryStore(MemoryStoreBase):
    """Persistent memory store backed by the application database."""

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        row = Memory(
            agent_name=agent_name,
            scope=scope,
            content=content,
            meta=metadata or {},
        )
        with get_session() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            # Read inside the session: attributes expire on commit and the
            # instance is detached once the context closes.
            return row.id

    def recall(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        with get_session() as session:
            rows = session.exec(
                select(Memory)
                .where(Memory.agent_name == agent_name, Memory.scope == scope)
                .order_by(col(Memory.created_at).desc())
                .limit(limit)
            ).all()
            return [_to_entry(r) for r in rows]

    def search(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Case-insensitive substring match, most recent first.

        Not semantic: an empty query behaves like `recall`.
        """
        term = (query or "").strip()
        with get_session() as session:
            stmt = select(Memory).where(
                Memory.agent_name == agent_name, Memory.scope == scope
            )
            if term:
                stmt = stmt.where(col(Memory.content).ilike(f"%{term}%"))
            rows = session.exec(
                stmt.order_by(col(Memory.created_at).desc()).limit(limit)
            ).all()
            return [_to_entry(r) for r in rows]

    def clear(self, agent_name: str, scope: str) -> int:
        with get_session() as session:
            rows = session.exec(
                select(Memory).where(
                    Memory.agent_name == agent_name, Memory.scope == scope
                )
            ).all()
            count = len(rows)
            if count:
                session.exec(
                    delete(Memory)
                    .where(col(Memory.agent_name) == agent_name)
                    .where(col(Memory.scope) == scope)
                )
                session.commit()
        return count


def _to_entry(row: Memory) -> MemoryEntry:
    return MemoryEntry(
        id=row.id,
        content=row.content,
        metadata=row.meta or {},
        created_at=row.created_at,
    )
