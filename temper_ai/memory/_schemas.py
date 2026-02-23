"""Data classes for memory scope, entries, and search results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from temper_ai.memory.constants import DEFAULT_TENANT_ID, SCOPE_SEPARATOR


@dataclass(frozen=True)
class MemoryScope:
    """Defines the scope for memory storage and retrieval.

    Uses a 3-level hierarchy: tenant > workflow/namespace > agent.
    The scope_key property produces a unique string for adapter keying.
    """

    tenant_id: str = DEFAULT_TENANT_ID
    workflow_name: str = ""
    agent_name: str = ""
    namespace: str | None = None
    agent_id: str | None = None  # M9: persistent agent ID

    @property
    def scope_key(self) -> str:
        """Build scope key: 'tenant:namespace_or_workflow:agent_or_id'."""
        middle = self.namespace if self.namespace else self.workflow_name
        agent_part = self.agent_id if self.agent_id else self.agent_name
        return SCOPE_SEPARATOR.join([self.tenant_id, middle, agent_part])


@dataclass
class MemoryEntry:
    """A single memory record."""

    content: str
    memory_type: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    relevance_score: float = 0.0


@dataclass
class MemorySearchResult:
    """Result of a memory search operation."""

    entries: list[MemoryEntry]
    query: str
    scope: MemoryScope
    search_time_ms: float = 0.0
