"""Tests for M5 MetricCollector interface and MetricRegistry."""

from datetime import datetime
from threading import Thread
from typing import Optional

import pytest

from src.self_improvement.metrics import (
    ExecutionProtocol,
    MetricCollector,
    MetricRegistry,
    MetricValue,
    SIMetricType,
)


class MockExecution:
    """Mock execution object for testing."""

    def __init__(self, exec_id="test-123", status="completed", cost=0.5):
        self.id = exec_id
        self.status = status
        self.estimated_cost_usd = cost


class TestMetricCollectorABC:
    """Test abstract base class enforcement."""

    def test_cannot_instantiate_abstract_class(self):
        """Verify MetricCollector cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            MetricCollector()

    def test_must_implement_all_abstract_methods(self):
        """Verify all abstract methods must be implemented."""

        class IncompleteCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "test"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteCollector()

    def test_complete_implementation_works(self):
        """Verify complete implementation can be instantiated."""

        class CompleteCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "complete"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        collector = CompleteCollector()
        assert collector.metric_name == "complete"
        assert collector.metric_type == SIMetricType.AUTOMATIC
        assert collector.collector_version == "1.0"  # Default version


class TestMetricValue:
    """Test MetricValue validation."""

    def test_valid_value_zero(self):
        """Test value = 0.0 is accepted."""
        mv = MetricValue(
            metric_name="test",
            value=0.0,
            metric_type=SIMetricType.AUTOMATIC,
            collected_at=datetime.now(),
        )
        assert mv.value == 0.0

    def test_valid_value_one(self):
        """Test value = 1.0 is accepted."""
        mv = MetricValue(
            metric_name="test",
            value=1.0,
            metric_type=SIMetricType.AUTOMATIC,
            collected_at=datetime.now(),
        )
        assert mv.value == 1.0

    def test_valid_value_middle(self):
        """Test values in (0.0, 1.0) are accepted."""
        mv = MetricValue(
            metric_name="test",
            value=0.5,
            metric_type=SIMetricType.AUTOMATIC,
            collected_at=datetime.now(),
        )
        assert mv.value == 0.5

    def test_invalid_value_below_zero(self):
        """Test value < 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be in range"):
            MetricValue(
                metric_name="test",
                value=-0.1,
                metric_type=SIMetricType.AUTOMATIC,
                collected_at=datetime.now(),
            )

    def test_invalid_value_above_one(self):
        """Test value > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be in range"):
            MetricValue(
                metric_name="test",
                value=1.1,
                metric_type=SIMetricType.AUTOMATIC,
                collected_at=datetime.now(),
            )

    def test_invalid_value_far_below_zero(self):
        """Test very negative values raise ValueError."""
        with pytest.raises(ValueError, match="must be in range"):
            MetricValue(
                metric_name="test",
                value=-999.0,
                metric_type=SIMetricType.AUTOMATIC,
                collected_at=datetime.now(),
            )

    def test_invalid_value_far_above_one(self):
        """Test very large values raise ValueError."""
        with pytest.raises(ValueError, match="must be in range"):
            MetricValue(
                metric_name="test",
                value=999.0,
                metric_type=SIMetricType.AUTOMATIC,
                collected_at=datetime.now(),
            )

    def test_metadata_defaults_to_empty_dict(self):
        """Test metadata defaults to empty dict."""
        mv = MetricValue(
            metric_name="test",
            value=0.5,
            metric_type=SIMetricType.AUTOMATIC,
            collected_at=datetime.now(),
        )
        assert mv.metadata == {}

    def test_metadata_can_be_set(self):
        """Test metadata can be provided."""
        metadata = {"source": "test", "version": "1.0"}
        mv = MetricValue(
            metric_name="test",
            value=0.5,
            metric_type=SIMetricType.AUTOMATIC,
            collected_at=datetime.now(),
            metadata=metadata,
        )
        assert mv.metadata == metadata


class TestMetricRegistry:
    """Test MetricRegistry operations."""

    @pytest.fixture
    def registry(self):
        """Create a fresh MetricRegistry for each test."""
        return MetricRegistry()

    @pytest.fixture
    def mock_collector(self):
        """Create a mock collector for testing."""

        class MockCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "mock_metric"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.8

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        return MockCollector()

    def test_register_collector(self, registry, mock_collector):
        """Test registering a collector."""
        registry.register(mock_collector)
        assert "mock_metric" in registry.list_collectors()

    def test_register_duplicate_raises_error(self, registry, mock_collector):
        """Test registering duplicate metric_name raises ValueError."""
        registry.register(mock_collector)

        # Try to register another collector with same name
        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_collector)

    def test_register_non_collector_raises_error(self, registry):
        """Test registering non-MetricCollector raises TypeError."""
        with pytest.raises(TypeError, match="must be a MetricCollector instance"):
            registry.register("not a collector")

        with pytest.raises(TypeError, match="must be a MetricCollector instance"):
            registry.register(42)

        with pytest.raises(TypeError, match="must be a MetricCollector instance"):
            registry.register(None)

    def test_unregister_collector(self, registry, mock_collector):
        """Test unregistering a collector."""
        registry.register(mock_collector)
        assert "mock_metric" in registry.list_collectors()

        registry.unregister("mock_metric")
        assert "mock_metric" not in registry.list_collectors()

    def test_unregister_nonexistent_raises_error(self, registry):
        """Test unregistering non-existent collector raises KeyError."""
        with pytest.raises(KeyError, match="No collector registered"):
            registry.unregister("nonexistent")

    def test_get_collector(self, registry, mock_collector):
        """Test getting a registered collector."""
        registry.register(mock_collector)
        retrieved = registry.get_collector("mock_metric")
        assert retrieved is mock_collector

    def test_get_nonexistent_collector_returns_none(self, registry):
        """Test getting non-existent collector returns None."""
        assert registry.get_collector("nonexistent") is None

    def test_list_collectors_empty(self, registry):
        """Test list_collectors on empty registry."""
        assert registry.list_collectors() == []

    def test_list_collectors_sorted(self, registry):
        """Test list_collectors returns sorted names."""

        class Collector1(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "zzz_last"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        class Collector2(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "aaa_first"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry.register(Collector1())
        registry.register(Collector2())

        names = registry.list_collectors()
        assert names == ["aaa_first", "zzz_last"]

    def test_collect_all_with_valid_collector(self, registry, mock_collector):
        """Test collect_all with working collector."""
        registry.register(mock_collector)
        execution = MockExecution()

        metrics = registry.collect_all(execution)
        assert metrics["mock_metric"] == 0.8

    def test_collect_all_with_multiple_collectors(self, registry):
        """Test collect_all with multiple collectors."""

        class Collector1(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "metric1"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.7

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        class Collector2(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "metric2"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.9

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry.register(Collector1())
        registry.register(Collector2())
        execution = MockExecution()

        metrics = registry.collect_all(execution)
        assert len(metrics) == 2
        assert metrics["metric1"] == 0.7
        assert metrics["metric2"] == 0.9

    def test_collect_all_handles_collector_exception(self, registry):
        """Test collect_all continues when collector raises exception."""

        class FailingCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "failing"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                raise RuntimeError("Collector failure")

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        class WorkingCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "working"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.9

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry.register(FailingCollector())
        registry.register(WorkingCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        # Should only have working collector's metric
        assert "working" in metrics
        assert "failing" not in metrics
        assert metrics["working"] == 0.9

    def test_collect_all_handles_invalid_value(self, registry):
        """Test collect_all skips collectors that return invalid values."""

        class InvalidCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "invalid"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 1.5  # Invalid: > 1.0

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        class ValidCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "valid"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry.register(InvalidCollector())
        registry.register(ValidCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        # Should only have valid collector's metric
        assert "valid" in metrics
        assert "invalid" not in metrics

    def test_collect_all_skips_non_applicable_collectors(self, registry):
        """Test collect_all skips collectors where is_applicable returns False."""

        class ApplicableCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "applicable"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.8

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        class NonApplicableCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "non_applicable"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.6

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return False  # Not applicable

        registry.register(ApplicableCollector())
        registry.register(NonApplicableCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        assert "applicable" in metrics
        assert "non_applicable" not in metrics

    def test_collect_all_handles_none_return_value(self, registry):
        """Test collect_all handles collectors that return None."""

        class NoneCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "none_metric"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return None  # Cannot compute metric

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry.register(NoneCollector())
        execution = MockExecution()

        metrics = registry.collect_all(execution)

        # None values should not be included
        assert "none_metric" not in metrics
        assert len(metrics) == 0

    def test_thread_safety(self, registry):
        """Test concurrent registration is thread-safe."""

        def register_collector(n):
            class TestCollector(MetricCollector):
                @property
                def metric_name(self) -> str:
                    return f"metric_{n}"

                @property
                def metric_type(self) -> SIMetricType:
                    return SIMetricType.AUTOMATIC

                def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                    return 0.5

                def is_applicable(self, execution: ExecutionProtocol) -> bool:
                    return True

            registry.register(TestCollector())

        threads = [Thread(target=register_collector, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(registry.list_collectors()) == 10

    def test_health_check(self, registry, mock_collector):
        """Test health_check returns correct information."""
        health = registry.health_check()
        assert health["collectors_registered"] == 0
        assert health["collector_names"] == []

        registry.register(mock_collector)
        health = registry.health_check()
        assert health["collectors_registered"] == 1
        assert health["collector_names"] == ["mock_metric"]


class TestExecutionProtocol:
    """Test ExecutionProtocol compatibility."""

    def test_mock_execution_satisfies_protocol(self):
        """Test MockExecution satisfies ExecutionProtocol."""

        class TestCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "test"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                # Should be able to access id and status
                assert hasattr(execution, "id")
                assert hasattr(execution, "status")
                return 1.0 if execution.status == "completed" else 0.0

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        collector = TestCollector()
        execution = MockExecution(exec_id="test", status="completed")

        value = collector.collect(execution)
        assert value == 1.0

    def test_protocol_allows_additional_attributes(self):
        """Test ExecutionProtocol allows objects with additional attributes."""

        class ExtendedExecution:
            def __init__(self):
                self.id = "extended-123"
                self.status = "completed"
                self.extra_field = "extra"
                self.another_field = 42

        class TestCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "test"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.AUTOMATIC

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        collector = TestCollector()
        execution = ExtendedExecution()

        # Should work even with extra fields
        value = collector.collect(execution)
        assert value == 0.5


class TestSIMetricType:
    """Test SIMetricType enum."""

    def test_metric_type_values(self):
        """Test SIMetricType enum has correct values."""
        assert SIMetricType.AUTOMATIC.value == "automatic"
        assert SIMetricType.DERIVED.value == "derived"
        assert SIMetricType.CUSTOM.value == "custom"

    def test_metric_type_membership(self):
        """Test SIMetricType enum membership."""
        assert SIMetricType.AUTOMATIC in SIMetricType
        assert SIMetricType.DERIVED in SIMetricType
        assert SIMetricType.CUSTOM in SIMetricType
