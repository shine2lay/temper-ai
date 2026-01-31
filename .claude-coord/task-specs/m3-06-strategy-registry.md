# Task: m3-06-strategy-registry - Create Strategy Registry and Factory

**Priority:** HIGH (P1)
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement StrategyRegistry for registering and retrieving collaboration strategies and conflict resolvers by name. Enables config-based strategy selection, auto-discovery, and plugin architecture for custom strategies.

---

## Files to Create

- `src/strategies/registry.py` - Registry and factory (~250 lines)
- `tests/test_strategies/test_registry.py` - Registry tests

---

## Acceptance Criteria

### Core Functionality
- [ ] `StrategyRegistry` singleton class
- [ ] `register_strategy(name, strategy_class)` method
- [ ] `get_strategy(name, **config) -> CollaborationStrategy` factory method
- [ ] `list_strategies() -> List[StrategyMetadata]` method
- [ ] Auto-discovery of strategies from `src/strategies/` module
- [ ] Default strategies auto-registered (Consensus, Debate)

### Conflict Resolver Registry
- [ ] `register_resolver(name, resolver_class)` method
- [ ] `get_resolver(name, **config) -> ConflictResolver` factory method
- [ ] `list_resolvers() -> List[ResolverMetadata]` method
- [ ] Default resolvers auto-registered (MeritWeighted, HumanEscalation)

### Configuration Support
- [ ] Parse strategy name from stage config
- [ ] Instantiate strategy with config parameters
- [ ] Validate strategy class implements interface
- [ ] Runtime type checking with isinstance()

### Testing
- [ ] Test register_strategy with valid strategy
- [ ] Test register_strategy with invalid class (not CollaborationStrategy)
- [ ] Test get_strategy with registered name
- [ ] Test get_strategy with unknown name raises ValueError
- [ ] Test get_strategy passes config to strategy constructor
- [ ] Test list_strategies returns metadata
- [ ] Test auto-discovery finds strategies
- [ ] Test singleton pattern
- [ ] Coverage >90%

---

## Implementation Details

### Class Implementation

```python
"""Strategy registry and factory for collaboration strategies.

Provides centralized registration and retrieval of:
- Collaboration strategies (Consensus, Debate, etc.)
- Conflict resolvers (MeritWeighted, HumanEscalation, etc.)

Enables config-based strategy selection and plugin architecture.
"""
from typing import Dict, Any, Type, List, Optional
from dataclasses import dataclass

from src.strategies.base import CollaborationStrategy
from src.strategies.conflict_resolution import ConflictResolver


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
        >>> strategy = registry.get_strategy("consensus", min_agents=2)
        >>> result = strategy.synthesize(outputs, config)
    """

    _instance: Optional["StrategyRegistry"] = None
    _strategies: Dict[str, Type[CollaborationStrategy]] = {}
    _resolvers: Dict[str, Type[ConflictResolver]] = {}

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_defaults()
        return cls._instance

    def _initialize_defaults(self):
        """Register default strategies and resolvers."""
        # Import here to avoid circular dependencies
        from src.strategies.consensus import ConsensusStrategy
        from src.strategies.debate import DebateAndSynthesize
        from src.strategies.merit_weighted import (
            MeritWeightedResolver,
            HumanEscalationResolver
        )

        # Register default strategies
        self._strategies["consensus"] = ConsensusStrategy
        self._strategies["debate"] = DebateAndSynthesize

        # Register default resolvers
        self._resolvers["merit_weighted"] = MeritWeightedResolver
        self._resolvers["human_escalation"] = HumanEscalationResolver

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
        **config
    ) -> CollaborationStrategy:
        """Get strategy instance by name.

        Args:
            name: Strategy name (default: "consensus")
            **config: Configuration passed to strategy constructor

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy name not registered

        Example:
            >>> registry = StrategyRegistry()
            >>> strategy = registry.get_strategy(
            ...     "consensus",
            ...     min_agents=2,
            ...     min_consensus=0.6
            ... )
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
        resolver_class: Type[ConflictResolver]
    ) -> None:
        """Register a conflict resolver.

        Args:
            name: Resolver name (e.g., "merit_weighted")
            resolver_class: Resolver class implementing ConflictResolver

        Raises:
            TypeError: If resolver_class doesn't inherit from ConflictResolver
            ValueError: If name is empty or already registered
        """
        if not name or not isinstance(name, str):
            raise ValueError("Resolver name must be non-empty string")

        if name in self._resolvers:
            raise ValueError(f"Resolver '{name}' already registered")

        # Validate resolver implements interface
        if not issubclass(resolver_class, ConflictResolver):
            raise TypeError(
                f"Resolver class must inherit from ConflictResolver, "
                f"got {resolver_class}"
            )

        self._resolvers[name] = resolver_class

    def get_resolver(
        self,
        name: str,
        **config
    ) -> ConflictResolver:
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
        """List all registered resolver names."""
        return list(self._resolvers.keys())

    def list_resolvers(self) -> List[ResolverMetadata]:
        """List all registered resolvers with metadata."""
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
        """Unregister a resolver (mainly for testing)."""
        if name in ["merit_weighted", "human_escalation"]:
            raise ValueError(f"Cannot unregister default resolver '{name}'")

        if name in self._resolvers:
            del self._resolvers[name]


# Convenience function for getting from stage config
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
) -> ConflictResolver:
    """Get conflict resolver from stage configuration.

    Args:
        stage_config: Stage configuration dict
        registry: Optional registry instance

    Returns:
        Instantiated resolver
    """
    if registry is None:
        registry = StrategyRegistry()

    conflict_resolution = stage_config.get("conflict_resolution", {})
    resolver_name = conflict_resolution.get("strategy", "merit_weighted")
    resolver_config = conflict_resolution.get("config", {})

    return registry.get_resolver(resolver_name, **resolver_config)
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_registry.py`)

```python
import pytest
from src.strategies.registry import StrategyRegistry
from src.strategies.base import CollaborationStrategy
from src.strategies.conflict_resolution import ConflictResolver


# Mock strategy for testing
class MockStrategy(CollaborationStrategy):
    def __init__(self, custom_param=None):
        self.custom_param = custom_param

    def synthesize(self, agent_outputs, config):
        pass

    def get_capabilities(self):
        return {"test": True}


def test_singleton_pattern():
    """Test registry uses singleton pattern."""
    registry1 = StrategyRegistry()
    registry2 = StrategyRegistry()

    assert registry1 is registry2


def test_default_strategies_registered():
    """Test default strategies are auto-registered."""
    registry = StrategyRegistry()

    assert "consensus" in registry.list_strategy_names()
    assert "debate" in registry.list_strategy_names()


def test_default_resolvers_registered():
    """Test default resolvers are auto-registered."""
    registry = StrategyRegistry()

    assert "merit_weighted" in registry.list_resolver_names()
    assert "human_escalation" in registry.list_resolver_names()


def test_register_strategy():
    """Test registering custom strategy."""
    registry = StrategyRegistry()
    registry.register_strategy("mock", MockStrategy)

    assert "mock" in registry.list_strategy_names()


def test_register_strategy_invalid_class():
    """Test registering non-CollaborationStrategy class fails."""
    registry = StrategyRegistry()

    class NotAStrategy:
        pass

    with pytest.raises(TypeError, match="inherit from CollaborationStrategy"):
        registry.register_strategy("invalid", NotAStrategy)


def test_register_strategy_duplicate_name():
    """Test registering duplicate name fails."""
    registry = StrategyRegistry()
    registry.register_strategy("mock1", MockStrategy)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_strategy("mock1", MockStrategy)


def test_get_strategy():
    """Test getting strategy by name."""
    registry = StrategyRegistry()
    registry.register_strategy("mock", MockStrategy)

    strategy = registry.get_strategy("mock")

    assert isinstance(strategy, MockStrategy)


def test_get_strategy_with_config():
    """Test strategy receives config parameters."""
    registry = StrategyRegistry()
    registry.register_strategy("mock", MockStrategy)

    strategy = registry.get_strategy("mock", custom_param="test_value")

    assert strategy.custom_param == "test_value"


def test_get_strategy_unknown_name():
    """Test getting unknown strategy raises ValueError."""
    registry = StrategyRegistry()

    with pytest.raises(ValueError, match="Unknown strategy 'nonexistent'"):
        registry.get_strategy("nonexistent")


def test_list_strategies():
    """Test listing strategies with metadata."""
    registry = StrategyRegistry()

    strategies = registry.list_strategies()

    assert len(strategies) >= 2  # At least consensus and debate
    assert all(hasattr(s, "name") for s in strategies)
    assert all(hasattr(s, "capabilities") for s in strategies)


def test_unregister_strategy():
    """Test unregistering custom strategy."""
    registry = StrategyRegistry()
    registry.register_strategy("mock", MockStrategy)

    registry.unregister_strategy("mock")

    assert "mock" not in registry.list_strategy_names()


def test_unregister_default_strategy_protected():
    """Test cannot unregister default strategies."""
    registry = StrategyRegistry()

    with pytest.raises(ValueError, match="Cannot unregister"):
        registry.unregister_strategy("consensus")
```

---

## Success Metrics

- [ ] File created: `src/strategies/registry.py`
- [ ] All tests pass: `pytest tests/test_strategies/test_registry.py -v`
- [ ] Code coverage >90%
- [ ] Can retrieve strategies: `registry.get_strategy("consensus")`
- [ ] Config-based selection works
- [ ] Singleton pattern verified

---

## Dependencies

**Blocked by:**
- m3-03-consensus-strategy (needs implementation to register)
- m3-04-debate-strategy (needs implementation to register)
- m3-05-merit-weighted-resolution (needs implementation to register)

**Blocks:**
- m3-07-parallel-stage-execution (needs registry for strategy lookup)
- m3-09-synthesis-node (needs registry for strategy instantiation)

---

## Design References

- [Engine Registry Pattern](./m2.5-03-engine-registry.md) (similar pattern)
- [Vision Document - Modularity](../../META_AUTONOMOUS_FRAMEWORK_VISION.md#the-modularity-philosophy)

---

## Notes

**Why Strategy Registry:**
- Single source of truth for available strategies
- Enables config-based selection (YAML → strategy)
- Supports plugin architecture (custom strategies)
- Runtime strategy discovery and validation

**Design Decisions:**
- Singleton pattern (one registry globally)
- Auto-registration of defaults (convenience)
- Type checking at registration (fail early)
- Config forwarding to strategy constructor (flexibility)

**Critical:**
- Must validate strategy/resolver implements interface
- Protect default strategies from unregistration
- Clear error messages for unknown names
- Thread-safe if needed in M3+ (locks for _strategies dict)

**Future Extensions (M4+):**
- Auto-discovery via module scanning
- Strategy versioning and migration
- Performance profiling per strategy
- Strategy recommendation based on task characteristics
