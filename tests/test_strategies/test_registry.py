"""Tests for strategy registry and factory.

Tests registration, retrieval, and configuration-based instantiation
of collaboration strategies and conflict resolvers.
"""

import pytest

from src.strategies.base import CollaborationStrategy, SynthesisResult
from src.strategies.registry import (
    ResolverMetadata,
    StrategyMetadata,
    StrategyRegistry,
    get_resolver_from_config,
    get_strategy_from_config,
)


# Mock strategy for testing
class MockStrategy(CollaborationStrategy):
    """Mock strategy for testing."""

    def __init__(self, custom_param=None):
        self.custom_param = custom_param

    def synthesize(self, agent_outputs, config):
        return SynthesisResult(
            decision="mock",
            confidence=1.0,
            method="mock",
            votes={},
            conflicts=[],
            reasoning="mock",
            metadata={}
        )

    def get_capabilities(self):
        return {"test": True}


class TestStrategyRegistry:
    """Test suite for StrategyRegistry."""

    def test_singleton_pattern(self):
        """Test registry uses singleton pattern."""
        # Reset singleton for testing
        StrategyRegistry._instance = None
        StrategyRegistry._initialized = False

        registry1 = StrategyRegistry()
        registry2 = StrategyRegistry()

        assert registry1 is registry2

    def test_default_strategies_registered(self):
        """Test default strategies are auto-registered."""
        registry = StrategyRegistry()

        strategy_names = registry.list_strategy_names()

        # Should have at least debate and consensus (if implemented)
        assert len(strategy_names) >= 1
        # Debate should be registered (we implemented it)
        assert "debate" in strategy_names

    def test_default_resolvers_registered(self):
        """Test default resolvers are auto-registered."""
        registry = StrategyRegistry()

        resolver_names = registry.list_resolver_names()

        # Should have at least merit_weighted, highest_confidence, random_tiebreaker
        assert len(resolver_names) >= 1
        assert "merit_weighted" in resolver_names

    def test_register_strategy_valid(self):
        """Test registering custom strategy."""
        registry = StrategyRegistry()

        # Use a unique name to avoid conflicts with existing strategies
        test_name = "test_mock_strategy"
        registry.register_strategy(test_name, MockStrategy)

        assert test_name in registry.list_strategy_names()

        # Clean up
        registry.unregister_strategy(test_name)

    def test_register_strategy_invalid_class(self):
        """Test registering non-CollaborationStrategy class fails."""
        registry = StrategyRegistry()

        class NotAStrategy:
            pass

        with pytest.raises(TypeError, match="inherit from CollaborationStrategy"):
            registry.register_strategy("invalid", NotAStrategy)

    def test_register_strategy_empty_name(self):
        """Test registering with empty name fails."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register_strategy("", MockStrategy)

    def test_register_strategy_duplicate_name(self):
        """Test registering duplicate name fails."""
        registry = StrategyRegistry()

        test_name = "test_mock_dup"
        registry.register_strategy(test_name, MockStrategy)

        with pytest.raises(ValueError, match="already registered"):
            registry.register_strategy(test_name, MockStrategy)

        # Clean up
        registry.unregister_strategy(test_name)

    def test_get_strategy_valid(self):
        """Test getting strategy by name."""
        registry = StrategyRegistry()

        test_name = "test_mock_get"
        registry.register_strategy(test_name, MockStrategy)

        strategy = registry.get_strategy(test_name)

        assert isinstance(strategy, MockStrategy)
        assert isinstance(strategy, CollaborationStrategy)

        # Clean up
        registry.unregister_strategy(test_name)

    def test_get_strategy_with_config(self):
        """Test strategy receives config parameters."""
        registry = StrategyRegistry()

        test_name = "test_mock_config"
        registry.register_strategy(test_name, MockStrategy)

        strategy = registry.get_strategy(test_name, custom_param="test_value")

        assert strategy.custom_param == "test_value"

        # Clean up
        registry.unregister_strategy(test_name)

    def test_get_strategy_unknown_name(self):
        """Test getting unknown strategy raises ValueError."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="Unknown strategy 'nonexistent'"):
            registry.get_strategy("nonexistent")

    def test_get_strategy_default_strategies(self):
        """Test getting default strategies works."""
        registry = StrategyRegistry()

        # Should be able to get debate strategy
        if "debate" in registry.list_strategy_names():
            strategy = registry.get_strategy("debate")
            assert strategy is not None

    def test_list_strategy_names(self):
        """Test listing strategy names."""
        registry = StrategyRegistry()

        names = registry.list_strategy_names()

        assert isinstance(names, list)
        assert len(names) > 0
        assert all(isinstance(n, str) for n in names)

    def test_list_strategies_metadata(self):
        """Test listing strategies with metadata."""
        registry = StrategyRegistry()

        strategies = registry.list_strategies()

        assert isinstance(strategies, list)
        assert len(strategies) > 0
        assert all(isinstance(s, StrategyMetadata) for s in strategies)
        assert all(hasattr(s, "name") for s in strategies)
        assert all(hasattr(s, "class_name") for s in strategies)
        assert all(hasattr(s, "capabilities") for s in strategies)

    def test_unregister_strategy_custom(self):
        """Test unregistering custom strategy."""
        registry = StrategyRegistry()

        test_name = "test_mock_unregister"
        registry.register_strategy(test_name, MockStrategy)

        registry.unregister_strategy(test_name)

        assert test_name not in registry.list_strategy_names()

    def test_unregister_default_strategy_protected(self):
        """Test cannot unregister default strategies."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_strategy("consensus")

        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_strategy("debate")

    def test_unregister_nonexistent_strategy(self):
        """Test unregistering nonexistent strategy doesn't raise error."""
        registry = StrategyRegistry()

        # Should not raise an error
        registry.unregister_strategy("nonexistent_strategy_xyz")
        assert True  # Verifies no exception raised


class TestResolverRegistry:
    """Test suite for resolver registration."""

    def test_list_resolver_names(self):
        """Test listing resolver names."""
        registry = StrategyRegistry()

        names = registry.list_resolver_names()

        assert isinstance(names, list)
        assert len(names) > 0
        assert all(isinstance(n, str) for n in names)

    def test_list_resolvers_metadata(self):
        """Test listing resolvers with metadata."""
        registry = StrategyRegistry()

        resolvers = registry.list_resolvers()

        assert isinstance(resolvers, list)
        assert len(resolvers) > 0
        assert all(isinstance(r, ResolverMetadata) for r in resolvers)
        assert all(hasattr(r, "name") for r in resolvers)
        assert all(hasattr(r, "class_name") for r in resolvers)

    def test_get_resolver_valid(self):
        """Test getting resolver by name."""
        registry = StrategyRegistry()

        if "merit_weighted" in registry.list_resolver_names():
            resolver = registry.get_resolver("merit_weighted")
            assert resolver is not None

    def test_get_resolver_unknown_name(self):
        """Test getting unknown resolver raises ValueError."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="Unknown resolver"):
            registry.get_resolver("nonexistent_resolver")

    def test_unregister_default_resolver_protected(self):
        """Test cannot unregister default resolvers."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_resolver("merit_weighted")


class TestConfigBasedRetrieval:
    """Test configuration-based strategy and resolver retrieval."""

    def test_get_strategy_from_config_default(self):
        """Test getting strategy from config with defaults."""
        config = {
            "collaboration": {
                "strategy": "debate",
                "config": {}
            }
        }

        strategy = get_strategy_from_config(config)

        assert strategy is not None
        assert isinstance(strategy, CollaborationStrategy)

    def test_get_strategy_from_config_with_params(self):
        """Test getting strategy with config parameters.

        Note: Most strategies don't accept constructor params,
        they receive config in synthesize() method instead.
        This test just verifies the strategy is instantiated.
        """
        config = {
            "collaboration": {
                "strategy": "debate",
                "config": {}  # Config passed to synthesize(), not __init__
            }
        }

        strategy = get_strategy_from_config(config)

        assert strategy is not None

    def test_get_strategy_from_config_missing_collaboration(self):
        """Test getting strategy when collaboration section missing (uses default)."""
        config = {}

        registry = StrategyRegistry()

        # Should use default strategy (consensus)
        if "consensus" in registry.list_strategy_names():
            strategy = get_strategy_from_config(config)
            assert strategy is not None

    def test_get_resolver_from_config_default(self):
        """Test getting resolver from config with defaults."""
        config = {
            "conflict_resolution": {
                "strategy": "merit_weighted",
                "config": {}
            }
        }

        resolver = get_resolver_from_config(config)

        assert resolver is not None

    def test_get_resolver_from_config_missing_section(self):
        """Test getting resolver when section missing (uses default)."""
        config = {}

        registry = StrategyRegistry()

        # Should use default resolver
        if "merit_weighted" in registry.list_resolver_names():
            resolver = get_resolver_from_config(config)
            assert resolver is not None


class TestRegistryIsolation:
    """Test that registry properly isolates test registrations."""

    def test_multiple_registrations_isolated(self):
        """Test multiple test registrations don't interfere."""
        registry = StrategyRegistry()

        # Register multiple test strategies
        registry.register_strategy("test_1", MockStrategy)
        registry.register_strategy("test_2", MockStrategy)

        assert "test_1" in registry.list_strategy_names()
        assert "test_2" in registry.list_strategy_names()

        # Clean up
        registry.unregister_strategy("test_1")
        registry.unregister_strategy("test_2")

        assert "test_1" not in registry.list_strategy_names()
        assert "test_2" not in registry.list_strategy_names()


class TestDebateAliases:
    """Test debate strategy name aliases (Wave 0 fix)."""

    def test_debate_and_synthesize_alias_registered(self):
        """Verify 'debate_and_synthesize' resolves to DebateAndSynthesize."""
        registry = StrategyRegistry()
        strategy = registry.get_strategy("debate_and_synthesize")
        assert strategy is not None
        from src.strategies.debate import DebateAndSynthesize
        assert isinstance(strategy, DebateAndSynthesize)

    def test_llm_debate_and_synthesize_alias_registered(self):
        """Verify 'llm_debate_and_synthesize' resolves to DebateAndSynthesize."""
        registry = StrategyRegistry()
        strategy = registry.get_strategy("llm_debate_and_synthesize")
        assert strategy is not None
        from src.strategies.debate import DebateAndSynthesize
        assert isinstance(strategy, DebateAndSynthesize)

    def test_aliases_are_default_strategies(self):
        """Verify aliases are protected as default strategies."""
        registry = StrategyRegistry()
        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_strategy("debate_and_synthesize")
        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_strategy("llm_debate_and_synthesize")
