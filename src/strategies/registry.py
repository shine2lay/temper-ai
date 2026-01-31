"""Strategy registry and factory for collaboration strategies.

Provides centralized registration and retrieval of:
- Collaboration strategies (Consensus, Debate, etc.)
- Conflict resolvers (MeritWeighted, HighestConfidence, etc.)

Enables config-based strategy selection and plugin architecture.
"""

from typing import Dict, Any, Type, List, Optional
from dataclasses import dataclass

from src.strategies.base import CollaborationStrategy
from src.strategies.conflict_resolution import ConflictResolutionStrategy


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
    capabilities: Dict[str, bool]
    config_schema: Dict[str, Any]


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
    capabilities: Dict[str, bool]
    config_schema: Dict[str, Any]


class StrategyRegistry:
    """Registry for collaboration strategies and conflict resolvers.

    Singleton pattern ensures single source of truth for available strategies.

    Example:
        >>> registry = StrategyRegistry()
        >>> registry.register_strategy("consensus", ConsensusStrategy)
        >>> strategy = registry.get_strategy("consensus")
        >>> result = strategy.synthesize(outputs, config)
    """

    _instance: Optional["StrategyRegistry"] = None
    _strategies: Dict[str, Type[CollaborationStrategy]] = {}
    _resolvers: Dict[str, Type[ConflictResolutionStrategy]] = {}
    _initialized: bool = False

    def __new__(cls) -> "StrategyRegistry":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize registry (only once due to singleton)."""
        if not self._initialized:
            self._initialize_defaults()
            StrategyRegistry._initialized = True

    def _initialize_defaults(self) -> None:
        """Register default strategies and resolvers."""
        # Import here to avoid circular dependencies
        try:
            from src.strategies.consensus import ConsensusStrategy
            self._strategies["consensus"] = ConsensusStrategy
        except ImportError:
            pass  # Consensus not yet implemented

        try:
            from src.strategies.debate import DebateAndSynthesize
            self._strategies["debate"] = DebateAndSynthesize
        except ImportError:
            pass  # Debate not yet implemented

        # Register default resolvers
        try:
            from src.strategies.conflict_resolution import (
                HighestConfidenceResolver,
                RandomTiebreakerResolver
            )
            from src.strategies.merit_weighted import (
                MeritWeightedResolver,
                HumanEscalationResolver
            )
            self._resolvers["merit_weighted"] = MeritWeightedResolver
            self._resolvers["highest_confidence"] = HighestConfidenceResolver
            self._resolvers["random_tiebreaker"] = RandomTiebreakerResolver
            self._resolvers["human_escalation"] = HumanEscalationResolver
        except ImportError:
            pass  # Resolvers not yet implemented

    def register_strategy(
        self,
        name: str,
        strategy_class: Type[CollaborationStrategy]
    ) -> None:
        """Register a collaboration strategy.

        Args:
            name: Strategy name (e.g., "consensus", "debate")
            strategy_class: Strategy class implementing CollaborationStrategy

        Raises:
            TypeError: If strategy_class doesn't inherit from CollaborationStrategy
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Strategy name must be non-empty string")

        if name in self._strategies:
            raise ValueError(f"Strategy '{name}' already registered")

        # Validate strategy implements interface
        if not issubclass(strategy_class, CollaborationStrategy):
            raise TypeError(
                f"Strategy class must inherit from CollaborationStrategy, "
                f"got {strategy_class}"
            )

        self._strategies[name] = strategy_class

    def get_strategy(
        self,
        name: str,
        **config: Any
    ) -> CollaborationStrategy:
        """Get strategy instance by name.

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
        if name not in self._strategies:
            available = ", ".join(self.list_strategy_names())
            raise ValueError(
                f"Unknown strategy '{name}'. "
                f"Available strategies: {available}"
            )

        strategy_class = self._strategies[name]

        # Instantiate with config (strategies can have __init__ params)
        try:
            return strategy_class(**config) if config else strategy_class()
        except TypeError as e:
            # Strategy doesn't accept these config params
            raise ValueError(
                f"Strategy '{name}' doesn't accept config: {config}. "
                f"Error: {e}"
            )

    def list_strategy_names(self) -> List[str]:
        """List all registered strategy names.

        Returns:
            List of strategy names
        """
        return list(self._strategies.keys())

    def list_strategies(self) -> List[StrategyMetadata]:
        """List all registered strategies with metadata.

        Returns:
            List of StrategyMetadata objects
        """
        metadata_list = []

        for name, strategy_class in self._strategies.items():
            # Instantiate to get metadata (safe for stateless strategies)
            try:
                instance = strategy_class()
                capabilities = instance.get_capabilities()
                meta = instance.get_metadata()

                metadata_list.append(StrategyMetadata(
                    name=name,
                    class_name=strategy_class.__name__,
                    description=meta.get("description", ""),
                    capabilities=capabilities,
                    config_schema=meta.get("config_schema", {})
                ))
            except Exception:
                # Skip strategies that can't be instantiated without config
                metadata_list.append(StrategyMetadata(
                    name=name,
                    class_name=strategy_class.__name__,
                    description="",
                    capabilities={},
                    config_schema={}
                ))

        return metadata_list

    def register_resolver(
        self,
        name: str,
        resolver_class: Type[ConflictResolutionStrategy]
    ) -> None:
        """Register a conflict resolver.

        Args:
            name: Resolver name (e.g., "merit_weighted")
            resolver_class: Resolver class implementing ConflictResolutionStrategy

        Raises:
            TypeError: If resolver_class doesn't inherit from ConflictResolutionStrategy
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Resolver name must be non-empty string")

        if name in self._resolvers:
            raise ValueError(f"Resolver '{name}' already registered")

        # Validate resolver implements interface
        if not issubclass(resolver_class, ConflictResolutionStrategy):
            raise TypeError(
                f"Resolver class must inherit from ConflictResolutionStrategy, "
                f"got {resolver_class}"
            )

        self._resolvers[name] = resolver_class

    def get_resolver(
        self,
        name: str,
        **config: Any
    ) -> ConflictResolutionStrategy:
        """Get resolver instance by name.

        Args:
            name: Resolver name
            **config: Configuration passed to resolver constructor

        Returns:
            Resolver instance

        Raises:
            ValueError: If resolver name not registered
        """
        if name not in self._resolvers:
            available = ", ".join(self.list_resolver_names())
            raise ValueError(
                f"Unknown resolver '{name}'. "
                f"Available resolvers: {available}"
            )

        resolver_class = self._resolvers[name]

        try:
            return resolver_class(**config) if config else resolver_class()
        except TypeError as e:
            raise ValueError(
                f"Resolver '{name}' doesn't accept config: {config}. "
                f"Error: {e}"
            )

    def list_resolver_names(self) -> List[str]:
        """List all registered resolver names.

        Returns:
            List of resolver names
        """
        return list(self._resolvers.keys())

    def list_resolvers(self) -> List[ResolverMetadata]:
        """List all registered resolvers with metadata.

        Returns:
            List of ResolverMetadata objects
        """
        metadata_list = []

        for name, resolver_class in self._resolvers.items():
            try:
                instance = resolver_class()
                capabilities = instance.get_capabilities()
                meta = instance.get_metadata()

                metadata_list.append(ResolverMetadata(
                    name=name,
                    class_name=resolver_class.__name__,
                    description=meta.get("description", ""),
                    capabilities=capabilities,
                    config_schema=meta.get("config_schema", {})
                ))
            except Exception:
                metadata_list.append(ResolverMetadata(
                    name=name,
                    class_name=resolver_class.__name__,
                    description="",
                    capabilities={},
                    config_schema={}
                ))

        return metadata_list

    def unregister_strategy(self, name: str) -> None:
        """Unregister a strategy (mainly for testing).

        Args:
            name: Strategy name to remove

        Raises:
            ValueError: If trying to unregister default strategies
        """
        if name in ["consensus", "debate"]:
            raise ValueError(f"Cannot unregister default strategy '{name}'")

        if name in self._strategies:
            del self._strategies[name]

    def unregister_resolver(self, name: str) -> None:
        """Unregister a resolver (mainly for testing).

        Args:
            name: Resolver name to remove

        Raises:
            ValueError: If trying to unregister default resolvers
        """
        if name in ["merit_weighted", "highest_confidence", "random_tiebreaker"]:
            raise ValueError(f"Cannot unregister default resolver '{name}'")

        if name in self._resolvers:
            del self._resolvers[name]


# Convenience functions for getting from stage config

def get_strategy_from_config(
    stage_config: Dict[str, Any],
    registry: Optional[StrategyRegistry] = None
) -> CollaborationStrategy:
    """Get collaboration strategy from stage configuration.

    Args:
        stage_config: Stage configuration dict
        registry: Optional registry instance (uses singleton if None)

    Returns:
        Instantiated strategy

    Example:
        stage_config = {
            "collaboration": {
                "strategy": "debate",
                "config": {
                    "max_rounds": 3,
                    "convergence_threshold": 0.8
                }
            }
        }

        strategy = get_strategy_from_config(stage_config)
    """
    if registry is None:
        registry = StrategyRegistry()

    collaboration = stage_config.get("collaboration", {})
    strategy_name = collaboration.get("strategy", "consensus")
    strategy_config = collaboration.get("config", {})

    return registry.get_strategy(strategy_name, **strategy_config)


def get_resolver_from_config(
    stage_config: Dict[str, Any],
    registry: Optional[StrategyRegistry] = None
) -> ConflictResolutionStrategy:
    """Get conflict resolver from stage configuration.

    Args:
        stage_config: Stage configuration dict
        registry: Optional registry instance

    Returns:
        Instantiated resolver

    Example:
        stage_config = {
            "conflict_resolution": {
                "strategy": "merit_weighted",
                "config": {}
            }
        }

        resolver = get_resolver_from_config(stage_config)
    """
    if registry is None:
        registry = StrategyRegistry()

    conflict_resolution = stage_config.get("conflict_resolution", {})
    resolver_name = conflict_resolution.get("strategy", "merit_weighted")
    resolver_config = conflict_resolution.get("config", {})

    return registry.get_resolver(resolver_name, **resolver_config)
