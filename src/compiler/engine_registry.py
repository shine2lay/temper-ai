"""Registry for execution engine implementations.

This module provides a factory pattern for managing and creating execution engines.
Enables runtime engine selection, A/B testing, and plugin architecture for third-party
engines.

Design Philosophy:
- Singleton registry - single source of truth for available engines
- Type-safe registration - validates engines implement ExecutionEngine interface
- Configuration-based selection - parse engine from workflow YAML
- Default fallback - always have "langgraph" engine available
"""

import threading
from typing import Any, Dict, List, Optional, Type

from src.compiler.execution_engine import ExecutionEngine


class EngineRegistry:
    """Registry for execution engine implementations.

    Provides factory pattern for creating engines by name.
    Enables runtime engine selection and A/B testing.
    Thread-safe singleton with double-checked locking.

    Example:
        >>> registry = EngineRegistry()
        >>> registry.register_engine("custom", CustomEngine)
        >>> engine = registry.get_engine("custom", config_loader=loader)
    """

    _lock: threading.Lock = threading.Lock()
    _instance: Optional["EngineRegistry"] = None
    _engines: Dict[str, Type[ExecutionEngine]]

    def __new__(cls) -> "EngineRegistry":
        """Thread-safe singleton pattern with double-checked locking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._engines = {}
                    instance._initialize_default_engines()
                    cls._instance = instance
        return cls._instance

    def _initialize_default_engines(self) -> None:
        """Register default engines on first instantiation.

        Raises:
            RuntimeError: If default engine cannot be imported/registered
        """
        try:
            from src.compiler.langgraph_engine import LangGraphExecutionEngine
            self._engines["langgraph"] = LangGraphExecutionEngine
        except ImportError as e:
            raise RuntimeError(
                f"Failed to import default LangGraph engine: {e}. "
                "Ensure langgraph dependencies are installed."
            ) from e

    def register_engine(
        self,
        name: str,
        engine_class: Type[ExecutionEngine]
    ) -> None:
        """Register an execution engine (thread-safe).

        Args:
            name: Engine name (e.g., "langgraph", "custom_dynamic")
            engine_class: Engine class implementing ExecutionEngine

        Raises:
            TypeError: If engine_class doesn't inherit from ExecutionEngine
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Engine name must be non-empty string")

        # Validate engine implements ExecutionEngine interface
        if not issubclass(engine_class, ExecutionEngine):
            raise TypeError(
                f"Engine class must inherit from ExecutionEngine, "
                f"got {engine_class}"
            )

        with self._lock:
            if name in self._engines:
                raise ValueError(f"Engine '{name}' already registered")
            self._engines[name] = engine_class

    def get_engine(
        self,
        name: str = "langgraph",
        **kwargs: Any
    ) -> ExecutionEngine:
        """Get engine instance by name (thread-safe).

        Args:
            name: Engine name (default: "langgraph")
            **kwargs: Keyword arguments passed to engine constructor

        Returns:
            Engine instance

        Raises:
            ValueError: If engine name not registered

        Example:
            >>> registry = EngineRegistry()
            >>> engine = registry.get_engine(
            ...     "langgraph",
            ...     tool_registry=registry,
            ...     config_loader=loader
            ... )
        """
        with self._lock:
            if name not in self._engines:
                available = ", ".join(self._engines.keys())
                raise ValueError(
                    f"Unknown engine '{name}'. "
                    f"Available engines: {available}"
                )
            engine_class = self._engines[name]

        # Instantiate outside lock
        return engine_class(**kwargs)

    def list_engines(self) -> List[str]:
        """List all registered engine names (thread-safe).

        Returns:
            List of engine names

        Example:
            >>> registry = EngineRegistry()
            >>> registry.list_engines()
            ['langgraph', 'custom_dynamic']
        """
        with self._lock:
            return list(self._engines.keys())

    def get_engine_from_config(
        self,
        workflow_config: Dict[str, Any],
        **kwargs: Any
    ) -> ExecutionEngine:
        """Create engine from workflow configuration.

        Parses engine name from config and creates instance.

        Args:
            workflow_config: Workflow configuration dict
            **kwargs: Additional kwargs for engine constructor

        Returns:
            Engine instance

        Example:
            workflow.yaml:
            ```yaml
            workflow:
              name: research
              engine: langgraph  # Optional, defaults to langgraph
              stages: [...]
            ```

            >>> config = load_workflow("research")
            >>> engine = registry.get_engine_from_config(
            ...     config,
            ...     tool_registry=registry,
            ...     config_loader=loader
            ... )
        """
        # Get workflow section
        workflow = workflow_config.get("workflow", workflow_config)

        # Extract engine name (default to langgraph)
        engine_name = workflow.get("engine", "langgraph")

        # Extract engine-specific config if present
        engine_config = workflow.get("engine_config", {})

        # Merge engine config with kwargs (kwargs take precedence)
        merged_kwargs = {**engine_config, **kwargs}

        return self.get_engine(engine_name, **merged_kwargs)

    def unregister_engine(self, name: str) -> None:
        """Unregister an engine (thread-safe, mainly for testing).

        Args:
            name: Engine name to remove

        Raises:
            ValueError: If trying to unregister "langgraph" (protected)
        """
        if name == "langgraph":
            raise ValueError("Cannot unregister default 'langgraph' engine")

        with self._lock:
            if name in self._engines:
                del self._engines[name]

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (for testing only).

        CO-02: Without this, singleton state leaks between tests causing
        test pollution. This method is intentionally a classmethod so it
        can be called without holding a reference to the instance.
        """
        with cls._lock:
            cls._instance = None
