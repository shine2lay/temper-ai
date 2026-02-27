"""Strategy registry and factory for collaboration strategies.

Provides centralized registration and retrieval of:
- Collaboration strategies (Consensus, Debate, etc.)
- Conflict resolvers (MeritWeighted, HighestConfidence, etc.)

Enables config-based strategy selection and plugin architecture.

RELIABILITY FIX (code-high-05): Added thread-safe reset methods to prevent
memory leaks in long-running processes. Use reset() for production cleanup,
reset_for_testing() in test fixtures.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional, Self

from temper_ai.agent.strategies.base import CollaborationStrategy
from temper_ai.agent.strategies.conflict_resolution import ConflictResolutionStrategy
from temper_ai.agent.strategies.constants import (
    STRATEGY_NAME_CONCATENATE,
    STRATEGY_NAME_CONSENSUS,
    STRATEGY_NAME_MERIT_WEIGHTED,
)

logger = logging.getLogger(__name__)


@dataclass
class StrategyMetadata:
    """Metadata about a registered strategy.

    Attributes:
        name: Strategy name
        class_name: Python class name
        description: Brief description
        capabilities: Strategy capabilities dict
        config_schema: Expected configuration schema
    """

    name: str
    class_name: str
    description: str
    capabilities: dict[str, bool]
    config_schema: dict[str, Any]


@dataclass
class ResolverMetadata:
    """Metadata about a registered conflict resolver.

    Attributes:
        name: Resolver name
        class_name: Python class name
        description: Brief description
        capabilities: Resolver capabilities dict
        config_schema: Expected configuration schema
    """

    name: str
    class_name: str
    description: str
    capabilities: dict[str, bool]
    config_schema: dict[str, Any]


class StrategyRegistry:  # noqa: god
    """Registry for collaboration strategies and conflict resolvers.

    Thread-safe singleton pattern ensures single source of truth.
    Provides lifecycle management via reset() and clear() methods
    to prevent memory leaks in long-running processes.

    RELIABILITY FIX (code-high-05): Added reset methods and thread safety
    to prevent unbounded memory growth from strategy registrations.

    Example:
        >>> registry = StrategyRegistry()
        >>> registry.register_strategy("consensus", ConsensusStrategy)
        >>> strategy = registry.get_strategy("consensus")
        >>> StrategyRegistry.reset()  # Clean up custom registrations
    """

    # Class-level lock for thread safety (RLock allows re-entry)
    _lock: threading.RLock = threading.RLock()

    # Singleton instance and state
    _instance: Optional["StrategyRegistry"] = None
    _strategies: dict[str, type[CollaborationStrategy]] = {}
    _resolvers: dict[str, type[ConflictResolutionStrategy]] = {}
    _initialized: bool = False

    # Track default registrations for reset() functionality
    _default_strategies: set[str] = set()
    _default_resolvers: set[str] = set()

    def __new__(cls) -> Self:
        """Thread-safe singleton pattern."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance  # type: ignore[return-value]

    def __init__(self) -> None:
        """Initialize registry (only once due to singleton)."""
        # Double-check locking pattern (safe due to RLock)
        if not self._initialized:
            with self._lock:
                if not self._initialized:  # Check again inside lock
                    self._initialize_defaults()
                    StrategyRegistry._initialized = True

    def _register_strategy(
        self, names: list[str], module_path: str, class_name: str
    ) -> None:
        """Register a strategy with one or more names.

        Args:
            names: Strategy names (e.g., ["debate", "debate_and_synthesize"])
            module_path: Python module path (e.g., "temper_ai.agent.strategies.debate")
            class_name: Class name to import (e.g., "DebateAndSynthesize")
        """
        try:
            module = __import__(module_path, fromlist=[class_name])
            strategy_class = getattr(module, class_name)
            for name in names:
                self._strategies[name] = strategy_class
                self._default_strategies.add(name)
        except ImportError as exc:
            logger.warning(
                "Could not import %s from %s: %s", class_name, module_path, exc
            )
        except AttributeError as exc:
            logger.warning("Could not find %s in %s: %s", class_name, module_path, exc)

    def _register_resolvers(self, resolvers: dict[str, tuple]) -> None:
        """Register multiple resolvers from module definitions.

        Args:
            resolvers: Dict mapping name -> (module_path, class_name)
        """
        for name, (module_path, class_name) in resolvers.items():
            try:
                module = __import__(module_path, fromlist=[class_name])
                resolver_class = getattr(module, class_name)
                self._resolvers[name] = resolver_class
                self._default_resolvers.add(name)
            except (ImportError, AttributeError) as exc:
                logger.warning(
                    "Could not import %s from %s: %s", class_name, module_path, exc
                )

    @staticmethod  # noqa: long
    def _default_resolver_map() -> dict[str, tuple[str, str]]:
        """Return the default resolver name -> (module, class) mapping."""
        return {
            STRATEGY_NAME_MERIT_WEIGHTED: (
                "temper_ai.agent.strategies.merit_weighted",
                "MeritWeightedResolver",
            ),
            "highest_confidence": (
                "temper_ai.agent.strategies.conflict_resolution",
                "HighestConfidenceResolver",
            ),
            "random_tiebreaker": (
                "temper_ai.agent.strategies.conflict_resolution",
                "RandomTiebreakerResolver",
            ),
            "human_escalation": (
                "temper_ai.agent.strategies.merit_weighted",
                "HumanEscalationResolver",
            ),
        }

    def _initialize_defaults(self) -> None:  # noqa: long
        """Register default strategies and resolvers.

        Note: This method is called with lock already held.
        """
        self._default_strategies.clear()
        self._default_resolvers.clear()

        strategies = [
            (
                [STRATEGY_NAME_CONSENSUS],
                "temper_ai.agent.strategies.consensus",
                "ConsensusStrategy",
            ),
            (
                [STRATEGY_NAME_CONCATENATE],
                "temper_ai.agent.strategies.concatenate",
                "ConcatenateStrategy",
            ),
            (
                ["debate", "debate_and_synthesize", "llm_debate_and_synthesize"],
                "temper_ai.agent.strategies.multi_round",
                "MultiRoundStrategy",
            ),
            (
                ["dialogue"],
                "temper_ai.agent.strategies.multi_round",
                "MultiRoundStrategy",
            ),
            (
                ["multi_round"],
                "temper_ai.agent.strategies.multi_round",
                "MultiRoundStrategy",
            ),
            (
                ["leader"],
                "temper_ai.agent.strategies.leader",
                "LeaderCollaborationStrategy",
            ),
        ]
        for names, module_path, class_name in strategies:
            self._register_strategy(names, module_path, class_name)

        self._register_resolvers(self._default_resolver_map())

    def register_strategy(
        self, name: str, strategy_class: type[CollaborationStrategy]
    ) -> None:
        """Register a collaboration strategy (thread-safe).

        Args:
            name: Strategy name (e.g., "consensus", "debate")
            strategy_class: Strategy class implementing CollaborationStrategy

        Raises:
            TypeError: If strategy_class doesn't inherit from CollaborationStrategy
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Strategy name must be non-empty string")

        with self._lock:
            if name in self._strategies:
                raise ValueError(f"Strategy '{name}' already registered")

            # Validate strategy implements interface
            if not issubclass(strategy_class, CollaborationStrategy):
                raise TypeError(
                    f"Strategy class must inherit from CollaborationStrategy, "
                    f"got {strategy_class}"
                )

            self._strategies[name] = strategy_class

    def get_strategy(self, name: str, **config: Any) -> CollaborationStrategy:
        """Get strategy instance by name (thread-safe read).

        Args:
            name: Strategy name
            **config: Configuration passed to strategy constructor

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy name not registered

        Example:
            >>> registry = StrategyRegistry()
            >>> strategy = registry.get_strategy("consensus")
        """
        # Read with lock for formal correctness
        with self._lock:
            if name not in self._strategies:
                available = ", ".join(self.list_strategy_names())
                raise ValueError(
                    f"Unknown strategy '{name}'. " f"Available strategies: {available}"
                )
            strategy_class = self._strategies[name]

        # Instantiate outside lock (don't hold lock during user code execution)
        try:
            return strategy_class(**config) if config else strategy_class()
        except TypeError as e:
            # Strategy doesn't accept these config params
            raise ValueError(
                f"Strategy '{name}' doesn't accept config: {config}. " f"Error: {e}"
            ) from e

    def list_strategy_names(self) -> list[str]:
        """List all registered strategy names (thread-safe).

        Returns:
            List of strategy names
        """
        with self._lock:
            return list(self._strategies.keys())

    def list_strategies(self) -> list[StrategyMetadata]:
        """List all registered strategies with metadata."""
        from temper_ai.agent.strategies._registry_helpers import (
            build_strategy_metadata_list,
        )

        # ST-02: Take snapshot under lock to prevent RuntimeError on dict mutation
        with self._lock:
            strategies_snapshot = dict(self._strategies)
        return build_strategy_metadata_list(strategies_snapshot)

    def register_resolver(
        self, name: str, resolver_class: type[ConflictResolutionStrategy]
    ) -> None:
        """Register a conflict resolver (thread-safe).

        Args:
            name: Resolver name (e.g., "merit_weighted")
            resolver_class: Resolver class implementing ConflictResolutionStrategy

        Raises:
            TypeError: If resolver_class doesn't inherit from ConflictResolutionStrategy
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Resolver name must be non-empty string")

        with self._lock:
            if name in self._resolvers:
                raise ValueError(f"Resolver '{name}' already registered")

            # Validate resolver implements interface
            if not issubclass(resolver_class, ConflictResolutionStrategy):
                raise TypeError(
                    f"Resolver class must inherit from ConflictResolutionStrategy, "
                    f"got {resolver_class}"
                )

            self._resolvers[name] = resolver_class

    def get_resolver(self, name: str, **config: Any) -> ConflictResolutionStrategy:
        """Get resolver instance by name (thread-safe read).

        Args:
            name: Resolver name
            **config: Configuration passed to resolver constructor

        Returns:
            Resolver instance

        Raises:
            ValueError: If resolver name not registered
        """
        with self._lock:
            if name not in self._resolvers:
                available = ", ".join(self.list_resolver_names())
                raise ValueError(
                    f"Unknown resolver '{name}'. " f"Available resolvers: {available}"
                )
            resolver_class = self._resolvers[name]

        try:
            return resolver_class(**config) if config else resolver_class()
        except TypeError as e:
            raise ValueError(
                f"Resolver '{name}' doesn't accept config: {config}. " f"Error: {e}"
            ) from e

    def list_resolver_names(self) -> list[str]:
        """List all registered resolver names (thread-safe).

        Returns:
            List of resolver names
        """
        with self._lock:
            return list(self._resolvers.keys())

    def list_resolvers(self) -> list[ResolverMetadata]:
        """List all registered resolvers with metadata."""
        from temper_ai.agent.strategies._registry_helpers import (
            build_resolver_metadata_list,
        )

        # ST-02: Take snapshot under lock to prevent RuntimeError on dict mutation
        with self._lock:
            resolvers_snapshot = dict(self._resolvers)
        return build_resolver_metadata_list(resolvers_snapshot)

    def unregister_strategy(self, name: str) -> None:
        """Unregister a strategy (thread-safe).

        Args:
            name: Strategy name to remove

        Raises:
            ValueError: If trying to unregister default strategies
        """
        with self._lock:
            if name in self._default_strategies:
                raise ValueError(
                    f"Cannot unregister default strategy '{name}'. "
                    f"Use reset() or clear() to remove defaults."
                )

            if name in self._strategies:
                del self._strategies[name]

    def unregister_resolver(self, name: str) -> None:
        """Unregister a resolver (thread-safe).

        Args:
            name: Resolver name to remove

        Raises:
            ValueError: If trying to unregister default resolvers
        """
        with self._lock:
            if name in self._default_resolvers:
                raise ValueError(
                    f"Cannot unregister default resolver '{name}'. "
                    f"Use reset() or clear() to remove defaults."
                )

            if name in self._resolvers:
                del self._resolvers[name]

    @classmethod
    def reset(cls) -> None:
        """Reset registry to default state (remove custom registrations).

        Removes all custom-registered strategies/resolvers and re-initializes
        defaults. Useful for:
        - Cleaning up after plugin unload
        - Resetting state in long-running processes
        - Test cleanup (prefer reset_for_testing() in fixtures)

        Thread-safe. Can be called even before registry is instantiated.
        Preserves singleton instance.

        Example:
            >>> registry = StrategyRegistry()
            >>> registry.register_strategy("custom", CustomStrategy)
            >>> assert "custom" in registry.list_strategy_names()
            >>> StrategyRegistry.reset()
            >>> assert "custom" not in registry.list_strategy_names()
            >>> assert "debate" in registry.list_strategy_names()  # Default preserved
        """
        with cls._lock:
            # Remove custom registrations (keep defaults)
            custom_strategies = set(cls._strategies.keys()) - cls._default_strategies
            for name in custom_strategies:
                del cls._strategies[name]

            custom_resolvers = set(cls._resolvers.keys()) - cls._default_resolvers
            for name in custom_resolvers:
                del cls._resolvers[name]

            # Re-initialize defaults in case some were manually deleted
            if cls._instance is not None:
                cls._instance._initialize_defaults()

    @classmethod
    def clear(cls) -> None:
        """Clear ALL strategies and resolvers (including defaults).

        Complete cleanup. Registry will be empty until next instantiation
        or explicit re-initialization. Use with caution in production.

        Primarily for:
        - Testing edge cases (empty registry behavior)
        - Complete plugin system reset
        - Memory cleanup before process shutdown

        Thread-safe. Preserves singleton instance but clears all registrations.
        Next instantiation will re-initialize defaults.

        Example:
            >>> StrategyRegistry.clear()
            >>> registry = StrategyRegistry()  # Will re-initialize defaults
        """
        with cls._lock:
            cls._strategies.clear()
            cls._resolvers.clear()
            cls._default_strategies.clear()
            cls._default_resolvers.clear()
            cls._initialized = False

    @classmethod
    def reset_for_testing(cls) -> None:
        """Complete reset including singleton instance (TEST ONLY).

        Destroys singleton instance and clears all registrations.
        Next instantiation creates fresh registry with defaults.

        WARNING: Only use in test fixtures. NOT for production cleanup.
        Production code should use reset() or clear() instead.

        Thread-safe.

        Example:
            >>> # In pytest fixture
            >>> @pytest.fixture(autouse=True)
            >>> def reset_registry():
            >>>     StrategyRegistry.reset_for_testing()
            >>>     yield
            >>>     StrategyRegistry.reset_for_testing()
        """
        with cls._lock:
            cls._instance = None
            cls._strategies.clear()
            cls._resolvers.clear()
            cls._default_strategies.clear()
            cls._default_resolvers.clear()
            cls._initialized = False


# Convenience functions for getting from stage config


def get_strategy_from_config(
    stage_config: dict[str, Any], registry: StrategyRegistry | None = None
) -> CollaborationStrategy:
    """Get collaboration strategy from stage configuration.

    Handles both flat and nested stage config formats:
    - Flat: {"collaboration": {"strategy": "debate", ...}}
    - Nested: {"stage": {"collaboration": {"strategy": "debate", ...}}}

    Args:
        stage_config: Stage configuration dict (flat or nested under "stage")
        registry: Optional registry instance (uses singleton if None)

    Returns:
        Instantiated strategy

    Example:
        stage_config = {
            "stage": {
                "collaboration": {
                    "strategy": "debate",
                    "config": {
                        "max_rounds": 3,
                        "convergence_threshold": 0.8
                    }
                }
            }
        }

        strategy = get_strategy_from_config(stage_config)
    """
    if registry is None:
        registry = StrategyRegistry()

    # Try flat format: {"collaboration": {...}}
    collaboration = stage_config.get("collaboration", None)

    # Try nested format: {"stage": {"collaboration": {...}}}
    if collaboration is None and isinstance(stage_config, dict):
        stage = stage_config.get("stage", {})
        if isinstance(stage, dict):
            collaboration = stage.get("collaboration", None)

    if collaboration is None:
        collaboration = {}

    strategy_name = collaboration.get("strategy", "consensus")
    strategy_config = collaboration.get("config", {})

    return registry.get_strategy(strategy_name, **strategy_config)


def get_resolver_from_config(
    stage_config: dict[str, Any], registry: StrategyRegistry | None = None
) -> ConflictResolutionStrategy:
    """Get conflict resolver from stage configuration.

    Handles both flat and nested stage config formats.

    Args:
        stage_config: Stage configuration dict (flat or nested under "stage")
        registry: Optional registry instance

    Returns:
        Instantiated resolver

    Example:
        stage_config = {
            "stage": {
                "conflict_resolution": {
                    "strategy": "merit_weighted",
                    "config": {}
                }
            }
        }

        resolver = get_resolver_from_config(stage_config)
    """
    if registry is None:
        registry = StrategyRegistry()

    # Try flat format
    conflict_resolution = stage_config.get("conflict_resolution", None)

    # Try nested format: {"stage": {"conflict_resolution": {...}}}
    if conflict_resolution is None and isinstance(stage_config, dict):
        stage = stage_config.get("stage", {})
        if isinstance(stage, dict):
            conflict_resolution = stage.get("conflict_resolution", None)

    if conflict_resolution is None:
        conflict_resolution = {}

    resolver_name = conflict_resolution.get("strategy", STRATEGY_NAME_MERIT_WEIGHTED)
    resolver_config = conflict_resolution.get("config", {})

    return registry.get_resolver(resolver_name, **resolver_config)
