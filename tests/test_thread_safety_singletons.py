"""Thread safety tests for singleton and shared-state components.

Tests concurrent access to:
- PricingManager dual-singleton fix
- AgentFactory._agent_types thread safety
- ToolRegistry TOCTOU fix in register()
- core/service.py _sanitizer initialization
"""
import threading

import pytest

from src.agent.utils.agent_factory import AgentFactory
from src.agent.base_agent import BaseAgent
from src.llm.pricing import PricingManager, get_pricing_manager
from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.registry import (
    ToolRegistry,
    clear_global_cache,
    get_global_registry,
)

# ---------- Helpers ----------

class StubAgent(BaseAgent):
    """Minimal agent stub for factory registration tests."""

    def execute(self, inputs, **kwargs):
        return {"result": "stub"}


class StubTool(BaseTool):
    """Minimal tool stub for registry tests."""

    def __init__(self, name: str = "StubTool", version: str = "1.0"):
        self._name = name
        self._version = version
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self._name,
            description="stub",
            version=self._version,
            category="test",
        )

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


# ---------- PricingManager tests ----------

class TestPricingManagerSingleton:
    """Verify PricingManager has a single instance regardless of access path."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        PricingManager.reset_for_testing()
        yield
        PricingManager.reset_for_testing()

    def test_get_pricing_manager_routes_through_class_singleton(self):
        """get_pricing_manager() returns the same object as PricingManager()."""
        a = get_pricing_manager()
        b = PricingManager()
        assert a is b

    def test_concurrent_get_pricing_manager_single_instance(self):
        """10 threads calling get_pricing_manager() all get same instance."""
        instances = []
        barrier = threading.Barrier(10)

        def get_instance():
            barrier.wait()
            instances.append(get_pricing_manager())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)

    def test_reset_for_testing_clears_initialized_flag(self):
        """After reset, next PricingManager() re-initializes."""
        pm1 = PricingManager()
        assert hasattr(pm1, '_initialized')
        PricingManager.reset_for_testing()
        assert PricingManager._instance is None


# ---------- AgentFactory tests ----------

class TestAgentFactoryThreadSafety:
    """Verify AgentFactory._agent_types is protected by lock."""

    @pytest.fixture(autouse=True)
    def reset_factory(self):
        AgentFactory.reset_for_testing()
        yield
        AgentFactory.reset_for_testing()

    def test_concurrent_register_preserves_all_entries(self):
        """10 threads each register a unique type; all survive."""
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        errors = []

        def register_type(idx):
            # Create a unique subclass per thread
            agent_cls = type(f"Agent{idx}", (StubAgent,), {})
            barrier.wait()
            try:
                AgentFactory.register_type(f"type_{idx}", agent_cls)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_type, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        types = AgentFactory.list_types()
        for i in range(num_threads):
            assert f"type_{i}" in types, f"type_{i} missing from registry"

    def test_concurrent_list_types_during_registration(self):
        """list_types() returns consistent snapshot during concurrent writes."""
        results = []
        barrier = threading.Barrier(20)

        def register_and_list(idx):
            agent_cls = type(f"AgentRL{idx}", (StubAgent,), {})
            barrier.wait()
            if idx % 2 == 0:
                try:
                    AgentFactory.register_type(f"rl_type_{idx}", agent_cls)
                except ValueError:
                    pass  # duplicate registration is ok
            else:
                result = AgentFactory.list_types()
                results.append(result)

        threads = [
            threading.Thread(target=register_and_list, args=(i,))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each snapshot should be a valid dict (no partial updates visible)
        for r in results:
            assert isinstance(r, dict)
            assert "standard" in r  # default always present

    def test_reset_for_testing_clears_to_defaults(self):
        """reset_for_testing() restores only the standard type."""
        AgentFactory.register_type("custom", StubAgent)
        assert "custom" in AgentFactory.list_types()
        AgentFactory.reset_for_testing()
        types = AgentFactory.list_types()
        assert "custom" not in types
        assert "standard" in types


# ---------- ToolRegistry tests ----------

class TestToolRegistryThreadSafety:
    """Verify ToolRegistry register/unregister are atomic."""

    def test_concurrent_register_no_duplicates(self):
        """Many threads registering unique tools; no lost entries."""
        registry = ToolRegistry()
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        errors = []

        def register_tool(idx):
            tool = StubTool(name=f"Tool{idx}", version="1.0")
            barrier.wait()
            try:
                registry.register(tool)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_tool, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        assert len(registry) == num_threads

    def test_concurrent_register_same_tool_only_one_wins(self):
        """Multiple threads registering same name+version; exactly one succeeds."""
        registry = ToolRegistry()
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        successes = []
        failures = []

        def register_tool(_idx):
            tool = StubTool(name="SharedTool", version="1.0")
            barrier.wait()
            try:
                registry.register(tool)
                successes.append(True)
            except Exception:
                failures.append(True)

        threads = [
            threading.Thread(target=register_tool, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1
        assert len(failures) == num_threads - 1

    def test_concurrent_register_and_clear(self):
        """Register and clear racing; no exceptions raised."""
        registry = ToolRegistry()
        errors = []

        def register_tools():
            for i in range(50):
                tool = StubTool(name=f"ClearTest{i}", version="1.0")
                try:
                    registry.register(tool, allow_override=True)
                except Exception as exc:
                    errors.append(exc)

        def clear_registry():
            for _ in range(10):
                try:
                    registry.clear()
                except Exception as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=register_tools)
        t2 = threading.Thread(target=clear_registry)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Race condition errors: {errors}"


# ---------- Global registry tests ----------

class TestGlobalRegistryThreadSafety:
    """Verify global registry singleton is thread-safe."""

    @pytest.fixture(autouse=True)
    def reset_global(self):
        clear_global_cache()
        yield
        clear_global_cache()

    def test_concurrent_get_global_registry_same_instance(self):
        """Multiple threads calling get_global_registry() get same instance."""
        instances = []
        barrier = threading.Barrier(10)

        def get_instance():
            barrier.wait()
            instances.append(get_global_registry())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)


# ---------- Service _sanitizer tests ----------

class TestServiceSanitizerThreadSafety:
    """Verify _get_sanitizer() creates exactly one instance under concurrency."""

    @pytest.fixture(autouse=True)
    def reset_sanitizer(self):
        import src.safety.service_mixin as svc
        svc._sanitizer = None
        yield
        svc._sanitizer = None

    def test_concurrent_get_sanitizer_single_instance(self):
        from src.safety.service_mixin import _get_sanitizer

        instances = []
        barrier = threading.Barrier(10)

        def get_instance():
            barrier.wait()
            instances.append(_get_sanitizer())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)
