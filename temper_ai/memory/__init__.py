"""Memory module — persistent agent memory.

Agents accumulate expertise through memory. Each agent has its own
memory scope (scoped by agent name + project). Memories persist across
workflow runs via the configured backend.

Usage:
    from temper_ai.memory import MemoryService, InMemoryStore

    # Quick start (non-persistent, for dev/testing)
    service = MemoryService(InMemoryStore())

    # Production (requires mem0ai installed)
    from temper_ai.memory.mem0_store import Mem0Store
    service = MemoryService(Mem0Store(config={...}))

    # Store and recall
    service.store("code_reviewer", "project:/path", "Uses FastAPI + SQLModel")
    memories = service.recall("code_reviewer", "project:/path")
"""

from temper_ai.memory.base import MemoryEntry, MemoryStoreBase
from temper_ai.memory.in_memory_store import InMemoryStore
from temper_ai.memory.service import MemoryService

__all__ = [
    "MemoryEntry",
    "MemoryStoreBase",
    "MemoryService",
    "InMemoryStore",
]
