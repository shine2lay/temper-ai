"""Tests for StrategyRegistry."""

from threading import Thread
from typing import Dict, List, Optional

import pytest

from src.self_improvement.strategies import (
    SIOptimizationConfig,
    ImprovementStrategy,
    LearnedPattern,
    StrategyRegistry,
)


class MockStrategy(ImprovementStrategy):
    """Mock strategy for testing."""

    def __init__(self, name: str = "mock_strategy"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def propose_config(
        self,
        agent_name: str,
        baseline_performance: Dict[str, float],
        learned_patterns: Optional[List[LearnedPattern]] = None,
    ) -> SIOptimizationConfig:
        """Propose a config (mock implementation)."""
        return SIOptimizationConfig(
            agent_name=agent_name,
            inference={"mock": "config"},
        )

    def generate_variants(
        self,
        current_config: SIOptimizationConfig,
        patterns: List[LearnedPattern],
    ) -> List[SIOptimizationConfig]:
        """Generate variants (mock implementation)."""
        return [
            SIOptimizationConfig(
                agent_name=current_config.agent_name,
                inference={"variant": i},
                extra_metadata={"variant_id": i},
            )
            for i in range(1, 3)
        ]

    def is_applicable(self, problem_type: str) -> bool:
        """Check if applicable (mock - always true)."""
        return True


class TestStrategyRegistry:
    """Test StrategyRegistry operations."""

    @pytest.fixture
    def registry(self):
        """Create a fresh StrategyRegistry for each test."""
        return StrategyRegistry()

    @pytest.fixture
    def mock_strategy(self):
        """Create a mock strategy for testing."""
        return MockStrategy(name="test_strategy")

    def test_register_strategy(self, registry, mock_strategy):
        """Test registering a strategy."""
        registry.register(mock_strategy)
        assert "test_strategy" in registry.list_strategy_names()

    def test_register_duplicate_raises_error(self, registry, mock_strategy):
        """Test registering duplicate strategy name raises ValueError."""
        registry.register(mock_strategy)

        # Try to register another strategy with same name
        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_strategy)

    def test_register_non_strategy_raises_error(self, registry):
        """Test registering non-ImprovementStrategy raises TypeError."""
        with pytest.raises(TypeError, match="must be an ImprovementStrategy instance"):
            registry.register("not a strategy")

        with pytest.raises(TypeError, match="must be an ImprovementStrategy instance"):
            registry.register(42)

        with pytest.raises(TypeError, match="must be an ImprovementStrategy instance"):
            registry.register(None)

    def test_unregister_strategy(self, registry, mock_strategy):
        """Test unregistering a strategy."""
        registry.register(mock_strategy)
        assert "test_strategy" in registry.list_strategy_names()

        registry.unregister("test_strategy")
        assert "test_strategy" not in registry.list_strategy_names()

    def test_unregister_nonexistent_raises_error(self, registry):
        """Test unregistering non-existent strategy raises KeyError."""
        with pytest.raises(KeyError, match="No strategy registered"):
            registry.unregister("nonexistent")

    def test_get_strategy(self, registry, mock_strategy):
        """Test getting a registered strategy."""
        registry.register(mock_strategy)
        retrieved = registry.get_strategy("test_strategy")
        assert retrieved is mock_strategy

    def test_get_nonexistent_strategy_returns_none(self, registry):
        """Test getting non-existent strategy returns None."""
        assert registry.get_strategy("nonexistent") is None

    def test_get_all_strategies(self, registry):
        """Test getting all registered strategies."""
        strategy1 = MockStrategy(name="strategy1")
        strategy2 = MockStrategy(name="strategy2")

        registry.register(strategy1)
        registry.register(strategy2)

        strategies = registry.get_all_strategies()
        assert len(strategies) == 2
        assert strategy1 in strategies
        assert strategy2 in strategies

    def test_list_strategy_names(self, registry):
        """Test listing strategy names."""
        assert registry.list_strategy_names() == []

        registry.register(MockStrategy(name="zzz_last"))
        registry.register(MockStrategy(name="aaa_first"))

        names = registry.list_strategy_names()
        assert names == ["aaa_first", "zzz_last"]  # Sorted

    def test_has_strategy(self, registry, mock_strategy):
        """Test checking if strategy is registered."""
        assert not registry.has_strategy("test_strategy")

        registry.register(mock_strategy)
        assert registry.has_strategy("test_strategy")

        registry.unregister("test_strategy")
        assert not registry.has_strategy("test_strategy")

    def test_clear(self, registry):
        """Test clearing all strategies."""
        registry.register(MockStrategy(name="strategy1"))
        registry.register(MockStrategy(name="strategy2"))

        assert len(registry.list_strategy_names()) == 2

        registry.clear()
        assert len(registry.list_strategy_names()) == 0

    def test_health_check(self, registry, mock_strategy):
        """Test health_check returns correct information."""
        health = registry.health_check()
        assert health["strategies_registered"] == 0
        assert health["strategy_names"] == []

        registry.register(mock_strategy)
        health = registry.health_check()
        assert health["strategies_registered"] == 1
        assert health["strategy_names"] == ["test_strategy"]

    def test_thread_safety(self, registry):
        """Test concurrent registration is thread-safe."""

        def register_strategy(n):
            strategy = MockStrategy(name=f"strategy_{n}")
            registry.register(strategy)

        threads = [Thread(target=register_strategy, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(registry.list_strategy_names()) == 10

    def test_get_all_strategies_returns_copy(self, registry):
        """Test get_all_strategies returns a copy, not live list."""
        strategy = MockStrategy(name="test")
        registry.register(strategy)

        strategies1 = registry.get_all_strategies()
        strategies2 = registry.get_all_strategies()

        # Should be equal but not the same object
        assert strategies1 == strategies2
        assert strategies1 is not strategies2

    def test_list_strategy_names_returns_copy(self, registry):
        """Test list_strategy_names returns a copy, not live list."""
        registry.register(MockStrategy(name="test"))

        names1 = registry.list_strategy_names()
        names2 = registry.list_strategy_names()

        # Should be equal but not the same object
        assert names1 == names2
        assert names1 is not names2

    def test_multiple_registrations_and_retrievals(self, registry):
        """Test multiple strategies can be registered and retrieved."""
        strategies = [MockStrategy(name=f"strategy_{i}") for i in range(5)]

        for strategy in strategies:
            registry.register(strategy)

        # Verify all registered
        assert len(registry.list_strategy_names()) == 5

        # Verify all retrievable
        for strategy in strategies:
            retrieved = registry.get_strategy(strategy.name)
            assert retrieved is strategy

    def test_propose_config_through_registry(self, registry):
        """Test using a strategy through the registry."""
        strategy = MockStrategy(name="test")
        registry.register(strategy)

        retrieved = registry.get_strategy("test")
        config = retrieved.propose_config(
            agent_name="test_agent",
            baseline_performance={"metric1": 0.5},
        )

        assert config.agent_name == "test_agent"
        assert config.inference == {"mock": "config"}
