"""Tests for EngineRegistry.

Tests registry pattern, singleton behavior, type validation, configuration parsing,
error handling, and thread safety.
"""

import threading
import pytest
from src.compiler.engine_registry import EngineRegistry
from src.compiler.execution_engine import (
    ExecutionEngine,
    CompiledWorkflow,
    ExecutionMode
)
from typing import Dict, Any


# Mock engine for testing
class MockExecutionEngine(ExecutionEngine):
    """Mock engine for testing."""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """Mock compile - not used in registry tests."""
        pass

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        """Mock execute - not used in registry tests."""
        pass

    def supports_feature(self, feature: str) -> bool:
        """Mock feature check."""
        return False


def test_singleton_pattern():
    """Test registry uses singleton pattern."""
    registry1 = EngineRegistry()
    registry2 = EngineRegistry()

    assert registry1 is registry2


def test_default_langgraph_registered():
    """Test langgraph engine is registered by default."""
    registry = EngineRegistry()

    assert "langgraph" in registry.list_engines()


def test_register_engine():
    """Test registering custom engine."""
    registry = EngineRegistry()

    # Clean up if already registered from other tests
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    assert "mock" in registry.list_engines()

    # Clean up
    registry.unregister_engine("mock")


def test_register_engine_invalid_class():
    """Test registering non-ExecutionEngine class fails."""
    registry = EngineRegistry()

    class NotAnEngine:
        pass

    with pytest.raises(TypeError, match="inherit from ExecutionEngine"):
        registry.register_engine("invalid", NotAnEngine)


def test_register_engine_empty_name():
    """Test registering with empty name fails."""
    registry = EngineRegistry()

    with pytest.raises(ValueError, match="must be non-empty string"):
        registry.register_engine("", MockExecutionEngine)


def test_register_engine_duplicate_name():
    """Test registering duplicate name fails."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock1")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock1", MockExecutionEngine)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_engine("mock1", MockExecutionEngine)

    # Clean up
    registry.unregister_engine("mock1")


def test_get_engine():
    """Test getting engine by name."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    engine = registry.get_engine("mock")

    assert isinstance(engine, MockExecutionEngine)

    # Clean up
    registry.unregister_engine("mock")


def test_get_engine_with_kwargs():
    """Test engine constructor receives kwargs."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    engine = registry.get_engine("mock", tool_registry="test_registry")

    assert engine.init_kwargs["tool_registry"] == "test_registry"

    # Clean up
    registry.unregister_engine("mock")


def test_get_engine_unknown_name():
    """Test getting unknown engine raises ValueError."""
    registry = EngineRegistry()

    with pytest.raises(ValueError, match="Unknown engine 'nonexistent'"):
        registry.get_engine("nonexistent")


def test_get_engine_unknown_name_shows_available():
    """Test error message shows available engines."""
    registry = EngineRegistry()

    with pytest.raises(ValueError, match="Available engines:"):
        registry.get_engine("nonexistent")


def test_get_engine_from_config():
    """Test parsing engine from workflow config."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    config = {
        "workflow": {
            "name": "test",
            "engine": "mock",
            "stages": []
        }
    }

    engine = registry.get_engine_from_config(config)

    assert isinstance(engine, MockExecutionEngine)

    # Clean up
    registry.unregister_engine("mock")


def test_get_engine_from_config_default():
    """Test default to langgraph if no engine specified."""
    registry = EngineRegistry()

    config = {
        "workflow": {
            "name": "test",
            "stages": []
        }
    }

    engine = registry.get_engine_from_config(config)

    # Should return langgraph engine
    assert engine is not None


def test_get_engine_from_config_with_engine_config():
    """Test engine_config section passed to constructor."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    config = {
        "workflow": {
            "name": "test",
            "engine": "mock",
            "engine_config": {
                "max_retries": 3,
                "timeout": 30
            },
            "stages": []
        }
    }

    engine = registry.get_engine_from_config(config)

    assert engine.init_kwargs["max_retries"] == 3
    assert engine.init_kwargs["timeout"] == 30

    # Clean up
    registry.unregister_engine("mock")


def test_get_engine_from_config_kwargs_override():
    """Test kwargs override engine_config from workflow."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    config = {
        "workflow": {
            "name": "test",
            "engine": "mock",
            "engine_config": {
                "max_retries": 3
            },
            "stages": []
        }
    }

    engine = registry.get_engine_from_config(config, max_retries=5)

    # kwargs should override engine_config
    assert engine.init_kwargs["max_retries"] == 5

    # Clean up
    registry.unregister_engine("mock")


def test_get_engine_from_config_no_workflow_section():
    """Test parsing config without workflow wrapper."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    config = {
        "name": "test",
        "engine": "mock",
        "stages": []
    }

    engine = registry.get_engine_from_config(config)

    assert isinstance(engine, MockExecutionEngine)

    # Clean up
    registry.unregister_engine("mock")


def test_list_engines():
    """Test listing all registered engines."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock1")
    except (ValueError, KeyError):
        pass
    try:
        registry.unregister_engine("mock2")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock1", MockExecutionEngine)
    registry.register_engine("mock2", MockExecutionEngine)

    engines = registry.list_engines()

    assert "langgraph" in engines
    assert "mock1" in engines
    assert "mock2" in engines

    # Clean up
    registry.unregister_engine("mock1")
    registry.unregister_engine("mock2")


def test_unregister_engine():
    """Test unregistering custom engine."""
    registry = EngineRegistry()

    # Clean up if already registered
    try:
        registry.unregister_engine("mock")
    except (ValueError, KeyError):
        pass

    registry.register_engine("mock", MockExecutionEngine)

    registry.unregister_engine("mock")

    assert "mock" not in registry.list_engines()


def test_unregister_langgraph_protected():
    """Test cannot unregister default langgraph engine."""
    registry = EngineRegistry()

    with pytest.raises(ValueError, match="Cannot unregister"):
        registry.unregister_engine("langgraph")


def test_unregister_nonexistent_engine():
    """Test unregistering non-existent engine does nothing."""
    registry = EngineRegistry()

    # Should not raise error
    registry.unregister_engine("nonexistent")


class TestThreadSafety:
    """Thread safety tests for EngineRegistry."""

    def _make_mock_engine(self, tag: str):
        """Create a uniquely-named MockExecutionEngine subclass."""
        return type(
            f"MockEngine_{tag}",
            (MockExecutionEngine,),
            {},
        )

    def test_singleton_creation_thread_safe(self):
        """Multiple threads calling EngineRegistry() get the same instance."""
        instances = []
        barrier = threading.Barrier(10)

        def get_instance():
            barrier.wait()
            instances.append(EngineRegistry())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)

    def test_concurrent_register_unique_names(self):
        """10 threads each register a unique engine simultaneously."""
        registry = EngineRegistry()
        errors = []
        barrier = threading.Barrier(10)

        # Pre-clean any leftovers
        for i in range(10):
            try:
                registry.unregister_engine(f"thread_eng_{i}")
            except (ValueError, KeyError):
                pass

        def register(idx):
            try:
                barrier.wait()
                engine_cls = self._make_mock_engine(f"t{idx}")
                registry.register_engine(f"thread_eng_{idx}", engine_cls)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"

        engines = registry.list_engines()
        for i in range(10):
            assert f"thread_eng_{i}" in engines

        # Cleanup
        for i in range(10):
            registry.unregister_engine(f"thread_eng_{i}")

    def test_concurrent_reads_during_writes(self):
        """Concurrent reads don't raise while writes are happening."""
        registry = EngineRegistry()
        errors = []
        barrier = threading.Barrier(20)

        # Pre-clean
        for i in range(10):
            try:
                registry.unregister_engine(f"rw_eng_{i}")
            except (ValueError, KeyError):
                pass

        def writer(idx):
            try:
                barrier.wait()
                engine_cls = self._make_mock_engine(f"rw{idx}")
                registry.register_engine(f"rw_eng_{idx}", engine_cls)
            except Exception as e:
                errors.append(("writer", idx, e))

        def reader():
            try:
                barrier.wait()
                for _ in range(50):
                    registry.list_engines()
            except Exception as e:
                errors.append(("reader", e))

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=writer, args=(i,)))
        for _ in range(10):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"

        # Cleanup
        for i in range(10):
            try:
                registry.unregister_engine(f"rw_eng_{i}")
            except (ValueError, KeyError):
                pass

    def test_concurrent_get_engine(self):
        """Multiple threads can get the same engine concurrently."""
        registry = EngineRegistry()
        results = []
        errors = []
        barrier = threading.Barrier(10)

        # Register a test engine
        try:
            registry.unregister_engine("concurrent_get")
        except (ValueError, KeyError):
            pass
        registry.register_engine("concurrent_get", MockExecutionEngine)

        def get(idx):
            try:
                barrier.wait()
                engine = registry.get_engine("concurrent_get")
                results.append(isinstance(engine, MockExecutionEngine))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        assert all(results)
        assert len(results) == 10

        # Cleanup
        registry.unregister_engine("concurrent_get")
