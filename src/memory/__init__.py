"""Agent memory module — persistent memory for cross-session learning.

Provides a pluggable memory system with scoped storage (tenant/workflow/agent),
multiple memory types (episodic, procedural, cross-session), and swappable
backends (in-memory for testing, Mem0 for production).
"""

from src.memory._schemas import MemoryEntry, MemoryScope, MemorySearchResult
from src.memory.constants import (
    DEFAULT_TENANT_ID,
    LATENCY_BUDGET_MS,
    MAX_MEMORY_CONTEXT_CHARS,
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
    PROVIDER_IN_MEMORY,
    PROVIDER_MEM0,
    PROVIDER_SQLITE,
    SCOPE_SEPARATOR,
)
from src.memory.extractors import extract_procedural_patterns
from src.memory.protocols import MemoryStoreProtocol
from src.memory.registry import MemoryProviderRegistry
from src.memory.service import MemoryService

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
    "PROVIDER_SQLITE",
    "SCOPE_SEPARATOR",
]
