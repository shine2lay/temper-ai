"""
Tests for performance tracker memory cleanup functionality (code-high-04).

Tests the time-based expiration of metrics to prevent unbounded memory growth
in long-running applications.
"""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from temper_ai.observability.performance import LatencyMetrics, PerformanceTracker


class TestMemoryCleanup:
    """Test automatic cleanup of expired metrics (code-high-04)."""

    def test_latency_metrics_tracks_last_updated(self):
        """Test that LatencyMetrics tracks last update time."""
        metrics = LatencyMetrics(operation="test_op")

        # Initial timestamp should be set
        assert hasattr(metrics, "last_updated")
        assert isinstance(metrics.last_updated, datetime)

        initial_time = metrics.last_updated

        # Wait a tiny bit and record
        time.sleep(0.01)
        metrics.record(100.0)

        # Timestamp should be updated
        assert metrics.last_updated > initial_time

    def test_cleanup_expired_metrics_removes_old_operations(self):
        """Test that cleanup removes operations older than expiration threshold."""
        tracker = PerformanceTracker()

        # Create a fixed "now" time
        now = datetime.now(UTC)

        # Create metrics with different ages
        # Operation 1: 25 hours old (should be removed with 24h threshold)
        old_time = now - timedelta(hours=25)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = old_time
            tracker.record("old_operation", 100.0)

        # Operation 2: 12 hours old (should be kept)
        recent_time = now - timedelta(hours=12)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = recent_time
            tracker.record("recent_operation", 200.0)

        # Operation 3: Current (should be kept)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            tracker.record("current_operation", 300.0)

        # Verify all operations exist
        assert len(tracker.metrics) == 3
        assert "old_operation" in tracker.metrics
        assert "recent_operation" in tracker.metrics
        assert "current_operation" in tracker.metrics

        # Run cleanup with current time
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=24)

        # Verify old operation was removed
        assert removed == 1
        assert len(tracker.metrics) == 2
        assert "old_operation" not in tracker.metrics
        assert "recent_operation" in tracker.metrics
        assert "current_operation" in tracker.metrics

    def test_cleanup_with_different_expiration_thresholds(self):
        """Test cleanup with different expiration thresholds."""
        tracker = PerformanceTracker()
        now = datetime.now(UTC)

        # Create operations at different ages
        times = [
            ("op_50h", now - timedelta(hours=50)),
            ("op_30h", now - timedelta(hours=30)),
            ("op_10h", now - timedelta(hours=10)),
            ("op_5h", now - timedelta(hours=5)),
        ]

        for op_name, op_time in times:
            with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
                mock_utcnow.return_value = op_time
                tracker.record(op_name, 100.0)

        # Cleanup with 48 hour threshold - should remove 1 (50h)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=48)
        assert removed == 1
        assert len(tracker.metrics) == 3

        # Cleanup with 24 hour threshold - should remove 1 more (30h)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=24)
        assert removed == 1
        assert len(tracker.metrics) == 2

        # Cleanup with 6 hour threshold - should remove 1 more (10h)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=6)
        assert removed == 1
        assert len(tracker.metrics) == 1
        assert "op_5h" in tracker.metrics

    def test_cleanup_with_no_expired_metrics(self):
        """Test cleanup when no metrics are expired."""
        tracker = PerformanceTracker()

        # Record recent operations
        tracker.record("op1", 100.0)
        tracker.record("op2", 200.0)

        # Cleanup should remove nothing
        removed = tracker.cleanup_expired_metrics(expiration_hours=24)

        assert removed == 0
        assert len(tracker.metrics) == 2

    def test_automatic_cleanup_on_record_interval(self):
        """Test that cleanup runs automatically every N records.

        Note: accesses _cleanup_interval and _record_count because
        PerformanceTracker has no public API to configure cleanup scheduling.
        """
        tracker = PerformanceTracker()
        now = datetime.now(UTC)

        # Set a small cleanup interval for testing
        tracker._cleanup_interval = 20  # Set higher to avoid premature cleanup

        # Create an old operation that should be cleaned up
        old_time = now - timedelta(hours=25)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = old_time
            tracker.record("old_op", 100.0)

        # Reset record count to 0 after creating old operation
        tracker._record_count = 0

        # Record operations up to cleanup interval
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now

            # First 19 records shouldn't trigger cleanup
            for i in range(19):
                tracker.record(f"op{i}", 100.0)

            # Old operation should still exist
            assert "old_op" in tracker.metrics

            # 20th record should trigger cleanup
            tracker.record("op19", 100.0)

            # Old operation should be removed
            assert "old_op" not in tracker.metrics

    def test_cleanup_preserves_recent_metrics(self):
        """Test that cleanup preserves all samples for recent metrics."""
        tracker = PerformanceTracker()

        # Record many samples for a recent operation
        for i in range(100):
            tracker.record("recent_op", float(i))

        # Verify all samples recorded
        assert len(tracker.metrics["recent_op"].samples) == 100

        # Run cleanup (should not affect recent operation)
        removed = tracker.cleanup_expired_metrics(expiration_hours=24)

        # Verify samples preserved
        assert len(tracker.metrics["recent_op"].samples) == 100
        assert removed == 0

    def test_memory_bound_with_many_unique_operations(self):
        """Test memory is bounded even with many unique operation names."""
        tracker = PerformanceTracker()
        # Disable automatic cleanup during data creation
        tracker._cleanup_interval = 10000
        now = datetime.now(UTC)

        # Simulate long-running application with new operation names
        # Create 200 operations spread over 30 hours
        for hour in range(30):
            op_time = now - timedelta(hours=30 - hour)

            with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
                mock_utcnow.return_value = op_time

                # Create multiple operations per hour
                for i in range(10):
                    op_name = f"op_h{hour}_n{i}"
                    tracker.record(op_name, 100.0)

        # Should have 300 operations total (30 hours * 10 ops/hour)
        initial_count = len(tracker.metrics)
        assert initial_count == 300

        # Run cleanup with 24h threshold
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=24)

        # Should have removed ~60 operations (6 hours * 10 ops/hour)
        # (operations older than 24 hours)
        assert removed >= 50
        assert len(tracker.metrics) < initial_count
        assert len(tracker.metrics) <= 250  # Roughly 24 hours worth

    def test_cleanup_returns_correct_count(self):
        """Test that cleanup returns accurate count of removed operations."""
        tracker = PerformanceTracker()
        now = datetime.now(UTC)

        # Create operations at various ages
        ages = [30, 28, 26, 20, 18, 12, 6, 2]
        for i, hours_old in enumerate(ages):
            op_time = now - timedelta(hours=hours_old)
            with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
                mock_utcnow.return_value = op_time
                tracker.record(f"op_{i}", 100.0)

        # Cleanup with 24h threshold should remove 3 operations (30h, 28h, 26h)
        with patch("temper_ai.observability.performance.utcnow") as mock_utcnow:
            mock_utcnow.return_value = now
            removed = tracker.cleanup_expired_metrics(expiration_hours=24)

        assert removed == 3
        assert len(tracker.metrics) == 5
