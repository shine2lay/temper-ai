"""Agent memory module — persistent memory for cross-session learning.

Provides a pluggable memory system with scoped storage (tenant/workflow/agent),
multiple memory types (episodic, procedural, cross-session), and swappable
backends (in-memory for testing, Mem0 for production).
"""

from temper_ai.memory._schemas import MemoryEntry, MemoryScope, MemorySearchResult
from temper_ai.memory.constants import (
    DEFAULT_TENANT_ID,
    LATENCY_BUDGET_MS,
    MAX_MEMORY_CONTEXT_CHARS,
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
    PROVIDER_IN_MEMORY,
    PROVIDER_MEM0,
    PROVIDER_PG,
    PROVIDER_SQLITE,
    SCOPE_SEPARATOR,
)
from temper_ai.memory.extractors import extract_procedural_patterns
from temper_ai.memory.protocols import MemoryStoreProtocol
from temper_ai.memory.registry import MemoryProviderRegistry
from temper_ai.memory.service import MemoryService

__all__ = [
    "DEFAULT_TENANT_ID",
    "LATENCY_BUDGET_MS",
    "MAX_MEMORY_CONTEXT_CHARS",
    "MEMORY_TYPE_CROSS_SESSION",
    "MEMORY_TYPE_EPISODIC",
    "MEMORY_TYPE_PROCEDURAL",
    "MemoryEntry",
    "MemoryProviderRegistry",
    "MemoryScope",
    "MemorySearchResult",
    "MemoryService",
    "MemoryStoreProtocol",
    "extract_procedural_patterns",
    "PROVIDER_IN_MEMORY",
    "PROVIDER_MEM0",
    "PROVIDER_PG",
    "PROVIDER_SQLITE",
    "SCOPE_SEPARATOR",
]
