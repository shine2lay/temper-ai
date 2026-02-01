"""
Tests for performance instrumentation and metrics tracking.
"""
import time
import pytest
from src.observability.performance import (
    PerformanceTracker,
    LatencyMetrics,
    SlowOperation,
    get_performance_tracker,
    reset_performance_tracker,
)


class TestLatencyMetrics:
    """Test LatencyMetrics class."""

    def test_record_samples(self):
        """Test recording latency samples."""
        metrics = LatencyMetrics(operation="test_op")

        metrics.record(100.0)
        metrics.record(200.0)
        metrics.record(300.0)

        assert len(metrics.samples) == 3
        assert metrics.samples == [100.0, 200.0, 300.0]

    def test_get_percentiles(self):
        """Test percentile calculation."""
        metrics = LatencyMetrics(operation="test_op")

        # Add 100 samples (0-99ms)
        for i in range(100):
            metrics.record(float(i))

        percentiles = metrics.get_percentiles()

        assert percentiles["count"] == 100
        assert percentiles["min"] == 0.0
        assert percentiles["max"] == 99.0
        assert 48 <= percentiles["p50"] <= 52  # Around 50th percentile
        assert 93 <= percentiles["p95"] <= 97  # Around 95th percentile
        assert 97 <= percentiles["p99"] <= 99  # Around 99th percentile

    def test_get_percentiles_empty(self):
        """Test percentiles with no samples."""
        metrics = LatencyMetrics(operation="test_op")

        percentiles = metrics.get_percentiles()

        assert percentiles["count"] == 0
        assert percentiles["p50"] == 0.0
        assert percentiles["p95"] == 0.0
        assert percentiles["p99"] == 0.0

    def test_is_slow(self):
        """Test slow operation detection."""
        metrics = LatencyMetrics(operation="test_op", slow_threshold_ms=500.0)

        assert not metrics.is_slow(100.0)
        assert not metrics.is_slow(500.0)
        assert metrics.is_slow(501.0)
        assert metrics.is_slow(1000.0)

    def test_get_slow_count(self):
        """Test counting slow operations."""
        metrics = LatencyMetrics(operation="test_op", slow_threshold_ms=500.0)

        metrics.record(100.0)
        metrics.record(600.0)  # Slow
        metrics.record(200.0)
        metrics.record(700.0)  # Slow
        metrics.record(300.0)

        assert metrics.get_slow_count() == 2

    def test_sample_limit(self):
        """Test that samples are limited to prevent memory growth."""
        metrics = LatencyMetrics(operation="test_op")

        # Record 1500 samples
        for i in range(1500):
            metrics.record(float(i))

        # Should keep only last 1000
        assert len(metrics.samples) == 1000
        assert metrics.samples[0] == 500.0  # First of last 1000


class TestPerformanceTracker:
    """Test PerformanceTracker class."""

    def test_init_default_thresholds(self):
        """Test initialization with default thresholds."""
        tracker = PerformanceTracker()

        assert tracker.default_thresholds["stage_execution"] == 10000.0
        assert tracker.default_thresholds["llm_call"] == 5000.0
        assert tracker.default_thresholds["tool_execution"] == 3000.0

    def test_init_custom_thresholds(self):
        """Test initialization with custom thresholds."""
        tracker = PerformanceTracker(
            slow_thresholds={"llm_call": 1000.0, "custom_op": 500.0}
        )

        assert tracker.default_thresholds["llm_call"] == 1000.0
        assert tracker.default_thresholds["custom_op"] == 500.0
        assert tracker.default_thresholds["stage_execution"] == 10000.0  # Still default

    def test_measure_context_manager(self):
        """Test measure context manager."""
        tracker = PerformanceTracker()

        with tracker.measure("test_op"):
            time.sleep(0.01)  # 10ms

        metrics = tracker.get_metrics("test_op")
        assert metrics["count"] == 1
        assert metrics["p50"] >= 10.0  # At least 10ms
        assert metrics["p50"] < 50.0   # But not too long

    def test_measure_with_context(self):
        """Test measure with context data."""
        tracker = PerformanceTracker()

        with tracker.measure("llm_call", context={"model": "gpt-4"}):
            time.sleep(0.001)

        metrics = tracker.get_metrics("llm_call")
        assert metrics["count"] == 1

    def test_record_latency(self):
        """Test manual latency recording."""
        tracker = PerformanceTracker()

        tracker.record("test_op", 100.0)
        tracker.record("test_op", 200.0)
        tracker.record("test_op", 300.0)

        metrics = tracker.get_metrics("test_op")
        assert metrics["count"] == 3
        assert metrics["p50"] == 200.0

    def test_get_metrics_nonexistent(self):
        """Test getting metrics for non-existent operation."""
        tracker = PerformanceTracker()

        metrics = tracker.get_metrics("nonexistent")
        assert metrics["count"] == 0
        assert metrics["p50"] == 0.0

    def test_get_all_metrics(self):
        """Test getting all metrics."""
        tracker = PerformanceTracker()

        tracker.record("op1", 100.0)
        tracker.record("op2", 200.0)
        tracker.record("op1", 150.0)

        all_metrics = tracker.get_all_metrics()

        assert "op1" in all_metrics
        assert "op2" in all_metrics
        assert all_metrics["op1"]["count"] == 2
        assert all_metrics["op2"]["count"] == 1

    def test_slow_operation_detection(self):
        """Test slow operation detection and logging."""
        tracker = PerformanceTracker(slow_thresholds={"test_op": 100.0})

        tracker.record("test_op", 50.0)   # Not slow
        tracker.record("test_op", 150.0)  # Slow
        tracker.record("test_op", 200.0)  # Slow

        assert len(tracker.slow_operations) == 2
        assert tracker.slow_operations[0].latency_ms == 150.0
        assert tracker.slow_operations[1].latency_ms == 200.0

    def test_slow_operations_limit(self):
        """Test that slow operations list is limited."""
        tracker = PerformanceTracker(slow_thresholds={"test_op": 10.0})
        tracker.max_slow_ops = 10

        # Record 20 slow operations
        for i in range(20):
            tracker.record("test_op", 100.0, context={"iteration": i})

        # Should keep only last 10
        assert len(tracker.slow_operations) == 10
        assert tracker.slow_operations[0].context["iteration"] == 10

    def test_get_slow_operations(self):
        """Test retrieving slow operations."""
        tracker = PerformanceTracker(slow_thresholds={"test_op": 100.0, "other_op": 100.0})

        tracker.record("test_op", 150.0, context={"id": 1})
        tracker.record("test_op", 200.0, context={"id": 2})
        tracker.record("other_op", 250.0, context={"id": 3})

        # Get all slow operations
        slow_ops = tracker.get_slow_operations(limit=10)
        assert len(slow_ops) == 3

        # Get slow operations for specific operation
        test_slow = tracker.get_slow_operations(operation="test_op", limit=10)
        assert len(test_slow) == 2
        assert test_slow[0]["context"]["id"] == 2  # Most recent first

    def test_get_summary(self):
        """Test performance summary."""
        tracker = PerformanceTracker(slow_thresholds={"test_op": 100.0})

        tracker.record("test_op", 50.0)
        tracker.record("test_op", 150.0)  # Slow
        tracker.record("other_op", 200.0)

        summary = tracker.get_summary()

        assert summary["total_operations"] == 3
        assert summary["total_slow_operations"] == 1
        assert summary["slow_percentage"] == pytest.approx(33.33, rel=0.1)
        assert "test_op" in summary["operations"]
        assert summary["operations"]["test_op"]["count"] == 2
        assert summary["operations"]["test_op"]["slow_count"] == 1

    def test_reset(self):
        """Test resetting tracker."""
        tracker = PerformanceTracker()

        tracker.record("test_op", 100.0)
        tracker.record("test_op", 200.0)

        assert tracker.get_metrics("test_op")["count"] == 2

        tracker.reset()

        assert tracker.get_metrics("test_op")["count"] == 0
        assert len(tracker.slow_operations) == 0

    def test_set_slow_threshold(self):
        """Test setting custom slow threshold."""
        tracker = PerformanceTracker()

        tracker.record("test_op", 100.0)
        tracker.set_slow_threshold("test_op", 50.0)

        tracker.record("test_op", 75.0)  # Should be slow now

        assert len(tracker.slow_operations) == 1
        assert tracker.slow_operations[0].latency_ms == 75.0

    def test_multiple_operations(self):
        """Test tracking multiple different operations."""
        tracker = PerformanceTracker()

        tracker.record("llm_call", 1000.0)
        tracker.record("tool_execution", 500.0)
        tracker.record("stage_execution", 5000.0)
        tracker.record("llm_call", 1200.0)

        assert tracker.get_metrics("llm_call")["count"] == 2
        assert tracker.get_metrics("tool_execution")["count"] == 1
        assert tracker.get_metrics("stage_execution")["count"] == 1


class TestSlowOperation:
    """Test SlowOperation dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        from datetime import datetime

        slow_op = SlowOperation(
            operation="test_op",
            latency_ms=1500.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            context={"model": "gpt-4", "tokens": 100},
        )

        result = slow_op.to_dict()

        assert result["operation"] == "test_op"
        assert result["latency_ms"] == 1500.0
        assert "2024-01-01" in result["timestamp"]
        assert result["context"]["model"] == "gpt-4"


class TestGlobalTracker:
    """Test global tracker functions."""

    def test_get_global_tracker(self):
        """Test getting global tracker instance."""
        reset_performance_tracker()

        tracker1 = get_performance_tracker()
        tracker2 = get_performance_tracker()

        # Should return same instance
        assert tracker1 is tracker2

    def test_reset_global_tracker(self):
        """Test resetting global tracker."""
        tracker1 = get_performance_tracker()
        tracker1.record("test_op", 100.0)

        reset_performance_tracker()

        tracker2 = get_performance_tracker()

        # Should be new instance
        assert tracker1 is not tracker2
        assert tracker2.get_metrics("test_op")["count"] == 0


class TestPerformanceMetrics:
    """Integration tests for performance metrics."""

    def test_performance_real_world_workflow(self):
        """Test realistic performance tracking workflow."""
        tracker = PerformanceTracker()

        # Simulate workflow with multiple operations
        with tracker.measure("workflow_execution"):
            for i in range(3):
                with tracker.measure("stage_execution", context={"stage": i}):
                    # Simulate LLM calls
                    for j in range(2):
                        tracker.record(
                            "llm_call",
                            100.0 + (i * 50),
                            context={"model": "gpt-4", "stage": i, "call": j}
                        )

                    # Simulate tool execution
                    tracker.record(
                        "tool_execution",
                        50.0,
                        context={"tool": "calculator", "stage": i}
                    )

        summary = tracker.get_summary()

        # 1 workflow + 3 stages + 6 llm + 3 tools = 13 total
        assert summary["total_operations"] == 13
        assert tracker.get_metrics("workflow_execution")["count"] == 1
        assert tracker.get_metrics("stage_execution")["count"] == 3
        assert tracker.get_metrics("llm_call")["count"] == 6
        assert tracker.get_metrics("tool_execution")["count"] == 3

    def test_percentile_accuracy(self):
        """Test accuracy of percentile calculations."""
        tracker = PerformanceTracker()

        # Record 1000 samples: 0-999ms
        for i in range(1000):
            tracker.record("test_op", float(i))

        metrics = tracker.get_metrics("test_op")

        # p50 should be around 500
        assert 490 <= metrics["p50"] <= 510

        # p95 should be around 950
        assert 940 <= metrics["p95"] <= 960

        # p99 should be around 990
        assert 980 <= metrics["p99"] <= 999
