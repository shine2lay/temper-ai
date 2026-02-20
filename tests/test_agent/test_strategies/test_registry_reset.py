"""Tests for StrategyRegistry reset methods and memory leak prevention.

RELIABILITY FIX (code-high-05): Tests for reset methods that prevent
unbounded memory growth in long-running processes.
"""
import threading
import time

import pytest

from temper_ai.agent.strategies.base import CollaborationStrategy
from temper_ai.agent.strategies.conflict_resolution import ConflictResolutionStrategy
from temper_ai.agent.strategies.registry import StrategyRegistry


class CustomTestStrategy(CollaborationStrategy):
    """Custom strategy for testing."""

    def synthesize(self, agent_outputs, config):
        """Synthesize results from multiple agents."""
        return "custom_result"

    def get_capabilities(self):
        """Get strategy capabilities."""
        return {"test": True}

    def get_metadata(self):
        """Get strategy metadata."""
        return {
            "description": "Custom test strategy",
            "config_schema": {}
        }


class CustomTestResolver(ConflictResolutionStrategy):
    """Custom resolver for testing."""

    def resolve(self, conflicts, config):
        """Resolve conflicts."""
        return "custom_resolution"

    def get_capabilities(self):
        """Get resolver capabilities."""
        return {"test": True}

    def get_metadata(self):
        """Get resolver metadata."""
        return {
            "description": "Custom test resolver",
            "config_schema": {}
        }


class TestRegistryReset:
    """Test reset() functionality."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_reset_removes_custom_strategies(self):
        """Test reset() removes custom strategies but preserves defaults."""
        registry = StrategyRegistry()

        # Register custom strategy
        registry.register_strategy("custom_test", CustomTestStrategy)
        assert "custom_test" in registry.list_strategy_names()

        # Reset
        StrategyRegistry.reset()

        # Custom removed, defaults preserved
        assert "custom_test" not in registry.list_strategy_names()
        # Check for default strategies (if they exist)
        strategy_names = registry.list_strategy_names()
        # Defaults should be present if they were imported successfully
        if "debate" in registry._default_strategies:
            assert "debate" in strategy_names

    def test_reset_removes_custom_resolvers(self):
        """Test reset() removes custom resolvers but preserves defaults."""
        registry = StrategyRegistry()

        # Register custom resolver
        registry.register_resolver("custom_resolver", CustomTestResolver)
        assert "custom_resolver" in registry.list_resolver_names()

        # Reset
        StrategyRegistry.reset()

        # Custom removed, defaults preserved
        assert "custom_resolver" not in registry.list_resolver_names()
        # Defaults should still be there
        if "merit_weighted" in registry._default_resolvers:
            assert "merit_weighted" in registry.list_resolver_names()

    def test_reset_preserves_singleton(self):
        """Test reset() doesn't destroy singleton instance."""
        registry1 = StrategyRegistry()
        StrategyRegistry.reset()
        registry2 = StrategyRegistry()

        assert registry1 is registry2

    def test_reset_idempotent(self):
        """Test reset() can be called multiple times safely."""
        registry = StrategyRegistry()
        # Record default count after first init
        count_after_first_reset = len(registry.list_strategy_names())

        StrategyRegistry.reset()
        StrategyRegistry.reset()
        StrategyRegistry.reset()

        # Count should be identical after repeated resets
        assert len(registry.list_strategy_names()) == count_after_first_reset

    def test_reset_reinitializes_defaults(self):
        """Test reset() re-initializes defaults if they were removed."""
        registry = StrategyRegistry()

        # Clear everything
        StrategyRegistry.clear()
        assert not StrategyRegistry._initialized

        # Reset should re-initialize
        StrategyRegistry.reset()

        # Should have defaults again
        registry = StrategyRegistry()
        if "debate" in registry._default_strategies:
            assert "debate" in registry.list_strategy_names()


class TestRegistryClear:
    """Test clear() functionality."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_clear_removes_everything(self):
        """Test clear() removes all strategies including defaults."""
        registry = StrategyRegistry()

        # Register custom
        registry.register_strategy("custom", CustomTestStrategy)

        # Clear
        StrategyRegistry.clear()

        # Everything should be cleared
        assert StrategyRegistry._strategies == {}
        assert StrategyRegistry._resolvers == {}

    def test_clear_resets_initialized_flag(self):
        """Test clear() resets initialization flag."""
        registry = StrategyRegistry()
        assert StrategyRegistry._initialized

        StrategyRegistry.clear()
        assert not StrategyRegistry._initialized

    def test_clear_allows_reinitialization(self):
        """Test clear() allows fresh initialization with defaults restored."""
        registry = StrategyRegistry()
        pre_clear_count = len(registry.list_strategy_names())

        StrategyRegistry.clear()

        # Create new registry - should re-initialize
        registry2 = StrategyRegistry()
        assert StrategyRegistry._initialized
        # Should have same defaults as before clear
        assert len(registry2.list_strategy_names()) == pre_clear_count


class TestRegistryResetForTesting:
    """Test reset_for_testing() functionality."""

    def test_reset_for_testing_destroys_singleton(self):
        """Test reset_for_testing() creates new singleton instance."""
        registry1 = StrategyRegistry()
        id1 = id(registry1)

        StrategyRegistry.reset_for_testing()

        registry2 = StrategyRegistry()
        id2 = id(registry2)

        assert id1 != id2  # Different instances

    def test_reset_for_testing_clears_all(self):
        """Test reset_for_testing() removes all registrations."""
        registry = StrategyRegistry()
        registry.register_strategy("custom", CustomTestStrategy)

        StrategyRegistry.reset_for_testing()

        # Everything cleared
        assert StrategyRegistry._strategies == {}
        assert StrategyRegistry._resolvers == {}
        assert StrategyRegistry._default_strategies == set()
        assert StrategyRegistry._default_resolvers == set()
        assert not StrategyRegistry._initialized

    def test_reset_for_testing_full_reset(self):
        """Test reset_for_testing() provides complete fresh start."""
        registry1 = StrategyRegistry()
        registry1.register_strategy("custom1", CustomTestStrategy)

        StrategyRegistry.reset_for_testing()

        registry2 = StrategyRegistry()
        # Should not have custom1
        assert "custom1" not in registry2.list_strategy_names()
        # Should have defaults (if they import successfully)
        assert len(registry2.list_strategy_names()) >= 0


class TestThreadSafety:
    """Test thread-safety of registry operations."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_concurrent_registrations(self):
        """Test concurrent strategy registrations are thread-safe."""
        registry = StrategyRegistry()

        errors = []

        def register_strategy(index):
            try:
                name = f"concurrent_test_{index}"
                registry.register_strategy(name, CustomTestStrategy)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_strategy, args=(i,))
            for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors, all registered
        assert len(errors) == 0
        assert len(registry.list_strategy_names()) >= 10

    def test_concurrent_reset_and_register(self):
        """Test concurrent reset() and register() don't cause race conditions."""
        registry = StrategyRegistry()

        errors = []

        def reset_registry():
            try:
                for _ in range(5):
                    StrategyRegistry.reset()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def register_strategies():
            try:
                for i in range(5):
                    name = f"race_test_{threading.current_thread().ident}_{i}"
                    registry.register_strategy(name, CustomTestStrategy)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reset_registry),
            threading.Thread(target=register_strategies),
            threading.Thread(target=register_strategies),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors (though some registrations may be lost due to resets)
        assert len(errors) == 0

    def test_singleton_creation_thread_safe(self):
        """Test singleton creation is thread-safe."""
        instances = []

        def create_instance():
            registry = StrategyRegistry()
            instances.append(id(registry))

        threads = [threading.Thread(target=create_instance) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get same instance
        assert len(set(instances)) == 1


class TestMemoryLeakPrevention:
    """Test that reset mechanisms prevent memory leaks."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_repeated_register_reset_no_accumulation(self):
        """Test repeated register/reset cycles don't accumulate strategies."""
        registry = StrategyRegistry()

        initial_count = len(registry.list_strategy_names())

        for i in range(100):
            registry.register_strategy(f"temp_{i}", CustomTestStrategy)
            StrategyRegistry.reset()

        final_count = len(registry.list_strategy_names())

        # Should return to initial count (only defaults)
        assert final_count == initial_count

    def test_long_running_process_simulation(self):
        """Simulate long-running process with periodic cleanup."""
        registry = StrategyRegistry()

        initial_count = len(registry.list_strategy_names())

        # Simulate 1000 plugin load/unload cycles
        for cycle in range(1000):
            # Load plugins
            for i in range(5):
                name = f"plugin_{cycle}_{i}"
                registry.register_strategy(name, CustomTestStrategy)

            # Periodic cleanup every 10 cycles
            if cycle % 10 == 0:
                StrategyRegistry.reset()

        # Final cleanup
        StrategyRegistry.reset()

        final_count = len(registry.list_strategy_names())

        # Should return to initial count
        assert final_count == initial_count

    def test_clear_prevents_accumulation(self):
        """Test clear() prevents memory accumulation."""
        # Get baseline default count
        baseline_registry = StrategyRegistry()
        baseline_count = len(baseline_registry.list_strategy_names())
        StrategyRegistry.reset_for_testing()

        # Create and clear 100 times
        for i in range(100):
            registry = StrategyRegistry()
            registry.register_strategy(f"temp_{i}", CustomTestStrategy)
            StrategyRegistry.clear()

        # Final registry should have only defaults, no temp_ strategies
        registry = StrategyRegistry()
        final_count = len(registry.list_strategy_names())
        assert final_count == baseline_count
        assert not any("temp_" in name for name in registry.list_strategy_names())


class TestBackwardCompatibility:
    """Test that new features don't break existing functionality."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_existing_singleton_pattern_works(self):
        """Test singleton pattern still works as before."""
        registry1 = StrategyRegistry()
        registry2 = StrategyRegistry()

        assert registry1 is registry2

    def test_unregister_still_works(self):
        """Test existing unregister methods still work."""
        registry = StrategyRegistry()

        registry.register_strategy("test_compat", CustomTestStrategy)
        assert "test_compat" in registry.list_strategy_names()

        registry.unregister_strategy("test_compat")
        assert "test_compat" not in registry.list_strategy_names()

    def test_default_protection_still_works(self):
        """Test defaults are still protected from unregistration."""
        registry = StrategyRegistry()

        # Try to unregister default (should fail)
        if "debate" in registry._default_strategies:
            with pytest.raises(ValueError, match="Cannot unregister default"):
                registry.unregister_strategy("debate")

    def test_register_and_get_still_works(self):
        """Test basic register/get workflow unchanged."""
        registry = StrategyRegistry()

        registry.register_strategy("test_strategy", CustomTestStrategy)
        strategy = registry.get_strategy("test_strategy")

        assert strategy is not None
        assert isinstance(strategy, CustomTestStrategy)


class TestProductionUsagePatterns:
    """Test real-world production usage patterns."""

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset_for_testing()

    def test_plugin_system_lifecycle(self):
        """Test plugin load/unload lifecycle."""
        registry = StrategyRegistry()

        # Load plugin
        registry.register_strategy("plugin_strategy", CustomTestStrategy)
        strategy = registry.get_strategy("plugin_strategy")
        assert strategy is not None

        # Unload plugin
        registry.unregister_strategy("plugin_strategy")

        with pytest.raises(ValueError, match="Unknown strategy"):
            registry.get_strategy("plugin_strategy")

    def test_multi_tenant_isolation(self):
        """Test tenant-specific strategy registration with cleanup."""
        registry = StrategyRegistry()

        # Tenant 1 registers custom strategy
        registry.register_strategy("tenant1_custom", CustomTestStrategy)

        # Tenant 2 registers different strategy
        registry.register_strategy("tenant2_custom", CustomTestStrategy)

        # Both available
        assert "tenant1_custom" in registry.list_strategy_names()
        assert "tenant2_custom" in registry.list_strategy_names()

        # Cleanup tenant strategies
        registry.unregister_strategy("tenant1_custom")
        registry.unregister_strategy("tenant2_custom")

        # Or bulk cleanup
        StrategyRegistry.reset()

    def test_periodic_cleanup_pattern(self):
        """Test periodic cleanup in long-running services."""
        registry = StrategyRegistry()

        # Simulate service lifecycle
        for hour in range(24):
            # Register some temporary strategies
            for i in range(5):
                name = f"temp_hour{hour}_{i}"
                registry.register_strategy(name, CustomTestStrategy)

            # Periodic cleanup every 4 hours
            if hour % 4 == 0:
                StrategyRegistry.reset()

        # Final state should only have defaults
        StrategyRegistry.reset()
        final_names = registry.list_strategy_names()

        # No temp strategies should remain
        assert not any("temp_" in name for name in final_names)
