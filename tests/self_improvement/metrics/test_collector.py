"""
Tests for MetricCollector interface and MetricRegistry.

Verifies that:
1. Abstract methods are enforced (cannot instantiate base class)
2. Concrete implementations must implement required methods
3. MetricRegistry registers and manages collectors
4. collect_all executes applicable collectors
5. Error handling works correctly
6. Value validation is enforced
"""

import pytest
from unittest.mock import Mock
from typing import Optional

from src.self_improvement.metrics.collector import (
    MetricCollector,
    MetricRegistry,
    ExecutionProtocol,
)
from src.self_improvement.metrics.types import MetricType


# Mock execution for testing
class MockExecution:
    """Mock execution object for testing."""

    def __init__(self, id: str = "test-exec-1", status: str = "completed"):
        self.id = id
        self.status = status
        self.data = {}


class SuccessRateCollector(MetricCollector):
    """Test collector that checks success rate."""

    @property
    def metric_name(self) -> str:
        return "success_rate"

    @property
    def metric_type(self) -> MetricType:
        return MetricType.AUTOMATIC

    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        return 1.0 if execution.status == "completed" else 0.0

    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        return True  # Always applicable


class CostCollector(MetricCollector):
    """Test collector that measures cost efficiency."""

    def __init__(self, max_cost_usd: float = 1.0):
        self.max_cost_usd = max_cost_usd

    @property
    def metric_name(self) -> str:
        return "cost_efficiency"

    @property
    def metric_type(self) -> MetricType:
        return MetricType.DERIVED

    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        # Simulate cost extraction
        if hasattr(execution, "data") and "cost_usd" in execution.data:
            cost = execution.data["cost_usd"]
            return 1.0 - min(cost / self.max_cost_usd, 1.0)
        return None

    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        return hasattr(execution, "data") and "cost_usd" in execution.data


class TestMetricCollector:
    """Test MetricCollector abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Cannot create instance of abstract MetricCollector."""
        with pytest.raises(TypeError):
            MetricCollector()  # type: ignore

    def test_concrete_collector_has_metric_name(self):
        """Concrete collector must implement metric_name property."""
        collector = SuccessRateCollector()
        assert collector.metric_name == "success_rate"

    def test_concrete_collector_has_metric_type(self):
        """Concrete collector must implement metric_type property."""
        collector = SuccessRateCollector()
        assert collector.metric_type == MetricType.AUTOMATIC

    def test_concrete_collector_collects_value(self):
        """Concrete collector must implement collect method."""
        collector = SuccessRateCollector()
        execution = MockExecution(status="completed")

        value = collector.collect(execution)

        assert value == 1.0

    def test_concrete_collector_checks_applicability(self):
        """Concrete collector must implement is_applicable method."""
        collector = SuccessRateCollector()
        execution = MockExecution()

        assert collector.is_applicable(execution) is True

    def test_collector_version_has_default(self):
        """Collector version has default value."""
        collector = SuccessRateCollector()
        assert collector.collector_version == "1.0"

    def test_missing_abstract_method_raises_error(self):
        """Forgetting to implement abstract method raises TypeError."""

        with pytest.raises(TypeError):

            class IncompleteCollector(MetricCollector):  # type: ignore
                @property
                def metric_name(self) -> str:
                    return "incomplete"

                # Missing metric_type, collect, is_applicable

            # Attempting to instantiate should raise TypeError
            IncompleteCollector()


class TestMetricRegistry:
    """Test MetricRegistry class."""

    def test_registry_initialization(self):
        """Can create empty registry."""
        registry = MetricRegistry()
        assert registry.list_collectors() == []

    def test_register_collector(self):
        """Can register a metric collector."""
        registry = MetricRegistry()
        collector = SuccessRateCollector()

        registry.register(collector)

        assert "success_rate" in registry.list_collectors()

    def test_register_multiple_collectors(self):
        """Can register multiple collectors."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())
        registry.register(CostCollector())

        collectors = registry.list_collectors()
        assert len(collectors) == 2
        assert "success_rate" in collectors
        assert "cost_efficiency" in collectors

    def test_register_duplicate_name_raises_error(self):
        """Cannot register two collectors with same metric_name."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(SuccessRateCollector())

    def test_register_non_collector_raises_error(self):
        """Registering non-MetricCollector raises TypeError."""
        registry = MetricRegistry()

        with pytest.raises(TypeError, match="must be a MetricCollector instance"):
            registry.register("not a collector")  # type: ignore

    def test_unregister_collector(self):
        """Can unregister a metric collector."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())

        registry.unregister("success_rate")

        assert "success_rate" not in registry.list_collectors()

    def test_unregister_nonexistent_raises_error(self):
        """Unregistering nonexistent collector raises KeyError."""
        registry = MetricRegistry()

        with pytest.raises(KeyError, match="No collector registered"):
            registry.unregister("nonexistent")

    def test_get_collector(self):
        """Can retrieve registered collector by name."""
        registry = MetricRegistry()
        collector = SuccessRateCollector()
        registry.register(collector)

        retrieved = registry.get_collector("success_rate")

        assert retrieved is collector

    def test_get_nonexistent_collector_returns_none(self):
        """Getting nonexistent collector returns None."""
        registry = MetricRegistry()
        assert registry.get_collector("nonexistent") is None


class TestMetricCollection:
    """Test metric collection with MetricRegistry."""

    def test_collect_all_with_applicable_collector(self):
        """collect_all executes applicable collectors."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())
        execution = MockExecution(status="completed")

        metrics = registry.collect_all(execution)

        assert metrics == {"success_rate": 1.0}

    def test_collect_all_with_multiple_collectors(self):
        """collect_all executes all applicable collectors."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())
        registry.register(CostCollector(max_cost_usd=1.0))

        execution = MockExecution(status="completed")
        execution.data = {"cost_usd": 0.5}

        metrics = registry.collect_all(execution)

        assert "success_rate" in metrics
        assert "cost_efficiency" in metrics
        assert metrics["success_rate"] == 1.0
        assert metrics["cost_efficiency"] == 0.5  # 1.0 - (0.5/1.0)

    def test_collect_all_skips_non_applicable_collectors(self):
        """collect_all skips collectors where is_applicable returns False."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())
        registry.register(CostCollector())  # Requires cost_usd in execution.data

        execution = MockExecution(status="completed")
        # No cost_usd in data, so CostCollector is not applicable

        metrics = registry.collect_all(execution)

        assert "success_rate" in metrics
        assert "cost_efficiency" not in metrics  # Skipped due to inapplicable

    def test_collect_all_handles_none_return_value(self):
        """collect_all omits collectors that return None."""

        class NoneReturningCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "none_metric"

            @property
            def metric_type(self) -> MetricType:
                return MetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return None  # Cannot compute

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry = MetricRegistry()
        registry.register(NoneReturningCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        assert "none_metric" not in metrics

    def test_collect_all_validates_value_range(self):
        """collect_all rejects values outside [0.0, 1.0]."""

        class InvalidCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "invalid_metric"

            @property
            def metric_type(self) -> MetricType:
                return MetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 1.5  # Invalid: > 1.0

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry = MetricRegistry()
        registry.register(InvalidCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        # Invalid collector's value should be rejected
        assert "invalid_metric" not in metrics

    def test_collect_all_handles_collector_exception(self):
        """collect_all continues when a collector raises an exception."""

        class FailingCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "failing_metric"

            @property
            def metric_type(self) -> MetricType:
                return MetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                raise ValueError("Simulated failure")

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry = MetricRegistry()
        registry.register(SuccessRateCollector())  # Should succeed
        registry.register(FailingCollector())  # Should fail gracefully
        execution = MockExecution(status="completed")

        metrics = registry.collect_all(execution)

        # SuccessRateCollector should succeed despite FailingCollector error
        assert "success_rate" in metrics
        assert "failing_metric" not in metrics

    def test_collect_all_with_empty_registry(self):
        """collect_all returns empty dict when no collectors registered."""
        registry = MetricRegistry()
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        assert metrics == {}


class TestMetricRegistryManagement:
    """Test MetricRegistry management methods."""

    def test_list_collectors_returns_sorted_names(self):
        """list_collectors returns alphabetically sorted names."""
        registry = MetricRegistry()
        registry.register(CostCollector())
        registry.register(SuccessRateCollector())

        names = registry.list_collectors()

        assert names == ["cost_efficiency", "success_rate"]  # Alphabetically sorted

    def test_health_check(self):
        """health_check returns registry status."""
        registry = MetricRegistry()
        registry.register(SuccessRateCollector())
        registry.register(CostCollector())

        health = registry.health_check()

        assert health["collectors_registered"] == 2
        assert set(health["collector_names"]) == {"success_rate", "cost_efficiency"}


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_collect_with_minimal_execution(self):
        """Collectors work with minimal execution objects."""

        class MinimalExecution:
            id = "min-1"
            status = "completed"

        collector = SuccessRateCollector()
        execution = MinimalExecution()

        value = collector.collect(execution)  # type: ignore

        assert value == 1.0

    def test_collect_returns_zero(self):
        """Collector can return 0.0 (valid value)."""
        collector = SuccessRateCollector()
        execution = MockExecution(status="failed")

        value = collector.collect(execution)

        assert value == 0.0

    def test_collect_returns_one(self):
        """Collector can return 1.0 (valid value)."""
        collector = SuccessRateCollector()
        execution = MockExecution(status="completed")

        value = collector.collect(execution)

        assert value == 1.0

    def test_collector_with_initialization_parameters(self):
        """Collectors can accept initialization parameters."""
        collector = CostCollector(max_cost_usd=2.0)
        execution = MockExecution()
        execution.data = {"cost_usd": 1.0}

        value = collector.collect(execution)

        assert value == 0.5  # 1.0 - (1.0/2.0)


class TestExecutionProtocol:
    """Test that ExecutionProtocol works as expected."""

    def test_mock_execution_satisfies_protocol(self):
        """MockExecution satisfies ExecutionProtocol."""
        execution = MockExecution(id="test", status="completed")

        # Should be usable as ExecutionProtocol
        assert execution.id == "test"
        assert execution.status == "completed"

    def test_collector_works_with_any_object_with_id_and_status(self):
        """Collectors work with any object that has id and status attributes."""

        class CustomExecution:
            def __init__(self):
                self.id = "custom-1"
                self.status = "completed"

        collector = SuccessRateCollector()
        execution = CustomExecution()

        value = collector.collect(execution)  # type: ignore

        assert value == 1.0
