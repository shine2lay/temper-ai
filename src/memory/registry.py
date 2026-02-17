"""Thread-safe singleton registry for memory providers."""

from __future__ import annotations

import threading
from typing import Any, Dict, Type

from src.memory.constants import PROVIDER_IN_MEMORY, PROVIDER_MEM0, PROVIDER_SQLITE

# Sentinel class for lazy-loaded providers
_LAZY_SENTINEL = type("_LazySentinel", (), {})


class MemoryProviderRegistry:
    """Thread-safe singleton registry for memory store providers.

    Built-ins:
      - 'in_memory': InMemoryAdapter (eager)
      - 'mem0': Mem0Adapter (lazy — imported only when requested)
    """

    _instance: MemoryProviderRegistry | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self._providers: Dict[str, Type[Any]] = {}
        self._register_builtins()

    @classmethod
    def get_instance(cls) -> MemoryProviderRegistry:
        """Return the singleton registry instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _register_builtins(self) -> None:
        """Register built-in providers."""
        from src.memory.adapters.in_memory import InMemoryAdapter

        self._providers[PROVIDER_IN_MEMORY] = InMemoryAdapter
        self._providers[PROVIDER_MEM0] = _LAZY_SENTINEL
        self._providers[PROVIDER_SQLITE] = _LAZY_SENTINEL

    def get_provider_class(self, name: str) -> Type[Any]:
        """Get provider class by name. Lazily imports Mem0/SQLite if needed."""
        with self._lock:
            if name not in self._providers:
                raise KeyError(f"Unknown memory provider: {name}")
            cls = self._providers[name]
            if cls is _LAZY_SENTINEL:
                cls = self._lazy_import(name)
                self._providers[name] = cls
            return cls

    @staticmethod
    def _lazy_import(name: str) -> Type[Any]:
        """Lazily import a provider class by name."""
        if name == PROVIDER_MEM0:
            from src.memory.adapters.mem0_adapter import Mem0Adapter
            return Mem0Adapter
        if name == PROVIDER_SQLITE:
            from src.memory.adapters.sqlite_adapter import SQLiteAdapter
            return SQLiteAdapter
        raise KeyError(f"No lazy import for provider: {name}")

    def register_provider(self, name: str, cls: Type[Any]) -> None:
        """Register a custom memory provider class."""
        with self._lock:
            self._providers[name] = cls

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset singleton for test isolation."""
        with cls._lock:
            cls._instance = None
