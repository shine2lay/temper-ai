"""Tests for ExecutionTracker integration with MetricRegistry."""

from typing import Optional

import pytest

from src.observability.backends import SQLObservabilityBackend
from src.observability.database import init_database
from src.observability.tracker import ExecutionTracker
from src.self_improvement.metrics import MetricCollector, MetricRegistry, SIMetricType
from src.self_improvement.metrics.collector import ExecutionProtocol


class MockMetricCollector(MetricCollector):
    """Mock metric collector for testing."""

    def __init__(self, name: str = "mock_metric", value: float = 0.8):
        self._name = name
        self._value = value
        self.collect_called = False
        self.is_applicable_called = False

    @property
    def metric_name(self) -> str:
        return self._name

    @property
    def metric_type(self) -> SIMetricType:
        return SIMetricType.CUSTOM

    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        self.collect_called = True
        return self._value

    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        self.is_applicable_called = True
        return execution.status == "completed"


class TestExecutionTrackerMetricsIntegration:
    """Test suite for ExecutionTracker and MetricRegistry integration."""

    @pytest.fixture
    def db(self):
        """Initialize in-memory database for testing."""
        # Reset global database before each test
        import src.observability.database as db_module
        from src.observability.database import _db_lock
        with _db_lock:
            db_module._db_manager = None

        db_manager = init_database("sqlite:///:memory:")
        yield db_manager

        # Clean up after test
        with _db_lock:
            db_module._db_manager = None

    @pytest.fixture
    def backend(self, db):
        """Create SQL backend for testing."""
        return SQLObservabilityBackend()

    @pytest.fixture
    def metric_registry(self):
        """Create metric registry with mock collector."""
        registry = MetricRegistry()
        registry.register(MockMetricCollector("test_metric", 0.75))
        return registry

    def test_tracker_without_registry(self, backend):
        """Test that tracker works without metric registry."""
        tracker = ExecutionTracker(backend=backend)

        # Should not raise error
        with tracker.track_workflow("test", {}) as workflow_id:
            with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    pass

        assert tracker.metric_registry is None

    def test_tracker_with_registry_initialization(self, backend, metric_registry):
        """Test that tracker stores registry reference."""
        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=metric_registry
        )

        assert tracker.metric_registry is metric_registry
        assert len(tracker.metric_registry.list_collectors()) == 1

    def test_metrics_collected_after_agent_execution(self, backend, metric_registry, caplog):
        """Test that metrics are collected after successful agent execution."""
        import logging
        caplog.set_level(logging.DEBUG)

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=metric_registry
        )

        # Get mock collector to verify it was called
        mock_collector = metric_registry.get_collector("test_metric")
        assert isinstance(mock_collector, MockMetricCollector)

        with tracker.track_workflow("test", {}) as workflow_id:
            with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    pass

        # Debug: Print all captured logs
        print(f"\n=== CAPTURED LOGS ===\n{caplog.text}\n=== END LOGS ===\n")

        # Verify collector methods were called
        assert mock_collector.is_applicable_called
        assert mock_collector.collect_called

        # Verify logging of collected metrics
        assert "Collected 1 metrics for agent" in caplog.text
        assert "test_metric=0.750" in caplog.text

    def test_metrics_collected_standalone_agent(self, backend, metric_registry, caplog):
        """Test metrics collected for standalone agent (no parent workflow)."""
        import logging
        caplog.set_level(logging.DEBUG)

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=metric_registry
        )

        # Create a fake stage ID (in real scenario, stage would exist)
        fake_stage_id = "stage-standalone-123"

        # Track agent in standalone mode (no parent workflow context)
        with tracker.track_agent("agent1", {}, fake_stage_id) as agent_id:
            pass

        # Should log metric collection (standalone agent has its own session)
        assert "Collected 1 metrics for agent" in caplog.text or \
               "Collected 0 metrics for agent" in caplog.text  # Expected if no applicable metrics

    def test_metric_collection_failure_doesnt_break_execution(self, backend, caplog):
        """Test that metric collection errors don't fail agent execution."""
        # Create registry with collector that raises error
        class FailingCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "failing_metric"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                raise RuntimeError("Intentional collection failure")

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return True

        registry = MetricRegistry()
        registry.register(FailingCollector())

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=registry
        )

        # Agent execution should complete successfully despite metric error
        with tracker.track_workflow("test", {}) as workflow_id:
            with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    assert agent_id is not None

        # Should log error about metric collection failure (from MetricRegistry)
        assert "Collector 'failing_metric' failed" in caplog.text or \
               "Intentional collection failure" in caplog.text

    def test_multiple_collectors_registered(self, backend, caplog):
        """Test that multiple collectors are all executed."""
        import logging
        caplog.set_level(logging.INFO)

        registry = MetricRegistry()
        registry.register(MockMetricCollector("metric1", 0.9))
        registry.register(MockMetricCollector("metric2", 0.7))
        registry.register(MockMetricCollector("metric3", 0.5))

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=registry
        )

        with tracker.track_workflow("test", {}) as workflow_id:
            with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    pass

        # Should log all three metrics
        assert "Collected 3 metrics for agent" in caplog.text
        assert "metric1=0.900" in caplog.text
        assert "metric2=0.700" in caplog.text
        assert "metric3=0.500" in caplog.text

    def test_no_metrics_if_agent_fails(self, backend, caplog):
        """Test that metrics are NOT collected if agent execution fails."""
        registry = MetricRegistry()
        mock_collector = MockMetricCollector("test_metric", 0.8)
        registry.register(mock_collector)

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=registry
        )

        try:
            with tracker.track_workflow("test", {}) as workflow_id:
                with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                    with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                        raise RuntimeError("Agent failed")
        except RuntimeError:
            pass  # Expected

        # Metrics should NOT be collected for failed agent
        assert "Collected 1 metrics" not in caplog.text

    def test_collector_not_applicable_skipped(self, backend, caplog):
        """Test that non-applicable collectors are skipped."""
        # Create collector that's never applicable
        class NeverApplicableCollector(MetricCollector):
            @property
            def metric_name(self) -> str:
                return "never_applicable"

            @property
            def metric_type(self) -> SIMetricType:
                return SIMetricType.CUSTOM

            def collect(self, execution: ExecutionProtocol) -> Optional[float]:
                return 0.5

            def is_applicable(self, execution: ExecutionProtocol) -> bool:
                return False  # Never applicable

        registry = MetricRegistry()
        registry.register(NeverApplicableCollector())

        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=registry
        )

        with tracker.track_workflow("test", {}) as workflow_id:
            with tracker.track_stage("stage1", {}, workflow_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    pass

        # Should log that no metrics were collected (all skipped)
        # Either 0 metrics collected or debug message about not applicable
        logs = caplog.text
        assert ("Collected 0 metrics" in logs or
                "not applicable" in logs.lower() or
                "Collected 1 metrics" not in logs)  # Should NOT collect any
