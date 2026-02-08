"""Registry for improvement strategies in M5 self-improvement system."""

import logging
from threading import RLock
from typing import Any, Dict, List, Optional

from src.self_improvement.strategies.strategy import ImprovementStrategy

logger = logging.getLogger(__name__)


class ImprovementStrategyRegistry:
    """Central registry for managing improvement strategies.

    The StrategyRegistry maintains a collection of ImprovementStrategy instances
    and provides methods to register, unregister, and retrieve strategies.
    It enables dynamic strategy selection based on performance metrics and
    learned patterns.

    The registry is thread-safe and can be used concurrently by multiple threads.

    Example:
        >>> from src.self_improvement.strategies import ImprovementStrategy
        >>>
        >>> registry = StrategyRegistry()
        >>> registry.register(RandomSearchStrategy())
        >>> registry.register(GradientDescentStrategy())
        >>>
        >>> # Get strategy by name
        >>> strategy = registry.get_strategy("random_search")
        >>>
        >>> # Get all available strategies
        >>> all_strategies = registry.get_all_strategies()
    """

    def __init__(self) -> None:
        """Initialize an empty strategy registry."""
        self._strategies: Dict[str, ImprovementStrategy] = {}
        self._lock = RLock()  # Thread-safe registration/retrieval
        logger.info("Initialized StrategyRegistry")

    def register(self, strategy: ImprovementStrategy) -> None:
        """Register an improvement strategy.

        Args:
            strategy: ImprovementStrategy instance to register

        Raises:
            TypeError: If strategy is not an ImprovementStrategy instance
            ValueError: If a strategy with the same name is already registered

        Note:
            Strategies can be registered at any time, enabling dynamic
            addition of new optimization approaches.
        """
        if not isinstance(strategy, ImprovementStrategy):
            raise TypeError(
                f"strategy must be an ImprovementStrategy instance, "
                f"got {type(strategy).__name__}"
            )

        with self._lock:
            strategy_name = strategy.name

            if strategy_name in self._strategies:
                raise ValueError(
                    f"Strategy with name '{strategy_name}' is already registered. "
                    f"Unregister the existing strategy first."
                )

            self._strategies[strategy_name] = strategy
            logger.info(f"Registered strategy: {strategy_name}")

    def unregister(self, strategy_name: str) -> None:
        """Unregister a strategy by name.

        Args:
            strategy_name: Name of the strategy to remove

        Raises:
            KeyError: If no strategy with the given name is registered

        Note:
            Unregistering a strategy does not affect ongoing experiments
            using that strategy.
        """
        with self._lock:
            if strategy_name not in self._strategies:
                raise KeyError(
                    f"No strategy registered with name '{strategy_name}'"
                )

            del self._strategies[strategy_name]
            logger.info(f"Unregistered strategy: {strategy_name}")

    def get_strategy(self, strategy_name: str) -> Optional[ImprovementStrategy]:
        """Get a registered strategy by name.

        Args:
            strategy_name: Name of the strategy

        Returns:
            ImprovementStrategy: The strategy instance if registered, None otherwise

        Example:
            >>> strategy = registry.get_strategy("random_search")
            >>> if strategy:
            ...     config = strategy.propose_config(agent_name, baseline)
        """
        with self._lock:
            return self._strategies.get(strategy_name)

    def get_all_strategies(self) -> List[ImprovementStrategy]:
        """Get all registered strategies.

        Returns:
            List of all registered strategy instances

        Example:
            >>> strategies = registry.get_all_strategies()
            >>> for strategy in strategies:
            ...     print(f"Strategy: {strategy.name}")
        """
        with self._lock:
            return list(self._strategies.values())

    def list_strategy_names(self) -> List[str]:
        """Get a list of all registered strategy names.

        Returns:
            Sorted list of registered strategy names

        Example:
            >>> names = registry.list_strategy_names()
            >>> print(f"Available strategies: {', '.join(names)}")
        """
        with self._lock:
            return sorted(self._strategies.keys())

    def has_strategy(self, strategy_name: str) -> bool:
        """Check if a strategy is registered.

        Args:
            strategy_name: Name of the strategy to check

        Returns:
            True if strategy is registered, False otherwise

        Example:
            >>> if registry.has_strategy("random_search"):
            ...     strategy = registry.get_strategy("random_search")
        """
        with self._lock:
            return strategy_name in self._strategies

    def clear(self) -> None:
        """Remove all registered strategies.

        Useful for testing or resetting the registry to a clean state.

        Example:
            >>> registry.clear()
            >>> assert len(registry.list_strategy_names()) == 0
        """
        with self._lock:
            count = len(self._strategies)
            self._strategies.clear()
            logger.info(f"Cleared all {count} strategies from registry")

    def health_check(self) -> Dict[str, Any]:
        """Check the health of the strategy registry.

        Returns:
            Health status including:
                - strategies_registered: Number of registered strategies
                - strategy_names: List of registered strategy names

        Note:
            This method can be used for monitoring and debugging.

        Example:
            >>> health = registry.health_check()
            >>> print(f"Registered strategies: {health['strategies_registered']}")
        """
        with self._lock:
            return {
                "strategies_registered": len(self._strategies),
                "strategy_names": sorted(self._strategies.keys()),
            }


# Backward-compatible alias
StrategyRegistry = ImprovementStrategyRegistry
