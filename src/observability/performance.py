"""
Performance instrumentation and metrics tracking.

Tracks latency percentiles (p50, p95, p99) and detects slow operations
across critical execution paths: stage execution, LLM calls, and tool execution.
"""
import logging
import statistics
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional

from src.database.datetime_utils import utcnow
from src.observability.constants import (
    DEFAULT_CLEANUP_INTERVAL,
    DEFAULT_SLOW_THRESHOLD_MS,
    DEFAULT_THRESHOLDS_MS,
    MAX_LATENCY_SAMPLES,
    MAX_SLOW_OPERATIONS,
)

logger = logging.getLogger(__name__)

# Percentile values for latency tracking
PERCENTILE_P50 = 50
PERCENTILE_P95 = 95
PERCENTILE_P99 = 99


@dataclass
class LatencyMetrics:
    """Latency metrics for a specific operation type."""

    operation: str
    samples: List[float] = field(default_factory=list)
    slow_threshold_ms: float = DEFAULT_SLOW_THRESHOLD_MS
    last_updated: datetime = field(default_factory=utcnow)

    def record(self, latency_ms: float) -> None:
        """Record a latency sample."""
        self.samples.append(latency_ms)
        self.last_updated = utcnow()

        # Keep only recent samples to prevent memory growth
        if len(self.samples) > MAX_LATENCY_SAMPLES:
            self.samples = self.samples[-MAX_LATENCY_SAMPLES:]

    def get_percentiles(self) -> Dict[str, float]:
        """
        Calculate latency percentiles.

        Returns:
            Dict with p50, p95, p99 latencies in milliseconds
        """
        if not self.samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        sorted_samples = sorted(self.samples)
        count = len(sorted_samples)

        return {
            "p50": self._percentile(sorted_samples, PERCENTILE_P50),
            "p95": self._percentile(sorted_samples, PERCENTILE_P95),
            "p99": self._percentile(sorted_samples, PERCENTILE_P99),
            "count": count,
            "min": min(sorted_samples),
            "max": max(sorted_samples),
            "mean": statistics.mean(sorted_samples),
        }

    def _percentile(self, sorted_samples: List[float], percentile: int) -> float:
        """Calculate percentile value."""
        if not sorted_samples:
            return 0.0

        index = int((percentile / 100.0) * len(sorted_samples))
        index = min(index, len(sorted_samples) - 1)
        return sorted_samples[index]

    def is_slow(self, latency_ms: float) -> bool:
        """Check if latency exceeds slow threshold."""
        return latency_ms > self.slow_threshold_ms

    def get_slow_count(self) -> int:
        """Get count of slow operations."""
        return sum(1 for s in self.samples if s > self.slow_threshold_ms)


@dataclass
class SlowOperation:
    """Record of a slow operation for diagnostics."""

    operation: str
    latency_ms: float
    timestamp: datetime
    context: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "operation": self.operation,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }


class PerformanceTracker:
    """
    Track performance metrics across critical execution paths.

    Features:
    - Latency percentile tracking (p50, p95, p99)
    - Slow operation detection and logging
    - Context manager for easy instrumentation
    - Per-operation metrics

    Example:
        >>> tracker = PerformanceTracker()
        >>> with tracker.measure("llm_call", context={"model": "gpt-4"}):
        ...     response = llm.complete(prompt)
        >>>
        >>> metrics = tracker.get_metrics("llm_call")
        >>> print(f"p95 latency: {metrics['p95']}ms")
    """

    def __init__(self, slow_thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize performance tracker.

        Args:
            slow_thresholds: Custom slow thresholds per operation type (in ms)
                           Default thresholds:
                           - stage_execution: 10000ms (10s)
                           - llm_call: 5000ms (5s)
                           - tool_execution: 3000ms (3s)
        """
        self.metrics: Dict[str, LatencyMetrics] = defaultdict(
            lambda: LatencyMetrics(operation="unknown")
        )

        # Set default slow thresholds
        self.default_thresholds = DEFAULT_THRESHOLDS_MS.copy()
        if slow_thresholds:
            self.default_thresholds.update(slow_thresholds)

        # Track slow operations for diagnostics
        self.slow_operations: List[SlowOperation] = []
        self.max_slow_ops = MAX_SLOW_OPERATIONS

        # Cleanup tracking to prevent unbounded memory growth
        self._record_count = 0
        self._cleanup_interval = DEFAULT_CLEANUP_INTERVAL
        self._expiration_hours = 24  # Remove metrics older than 24 hours

    @contextmanager
    def measure(self, operation: str, context: Optional[Dict[str, Any]] = None) -> Generator[None, None, None]:
        """
        Context manager to measure operation latency.

        Args:
            operation: Operation name (e.g., "llm_call", "stage_execution")
            context: Additional context for diagnostics (model, stage name, etc.)

        Example:
            >>> with tracker.measure("llm_call", {"model": "gpt-4"}):
            ...     result = llm.complete(prompt)
        """
        start_time = time.perf_counter()

        try:
            yield
        finally:
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000.0

            self.record(operation, latency_ms, context or {})

    def record(
        self,
        operation: str,
        latency_ms: float,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a latency measurement.

        Args:
            operation: Operation name
            latency_ms: Latency in milliseconds
            context: Additional context for diagnostics
        """
        # Periodically cleanup expired metrics to prevent unbounded growth
        self._record_count += 1
        if self._record_count >= self._cleanup_interval:
            self.cleanup_expired_metrics(self._expiration_hours)
            self._record_count = 0

        # Initialize metrics for this operation if not exists
        if operation not in self.metrics:
            threshold = self.default_thresholds.get(operation, DEFAULT_SLOW_THRESHOLD_MS)
            self.metrics[operation] = LatencyMetrics(
                operation=operation,
                slow_threshold_ms=threshold
            )

        # Record latency
        metrics = self.metrics[operation]
        metrics.record(latency_ms)

        # Check if slow and log/store
        if metrics.is_slow(latency_ms):
            slow_op = SlowOperation(
                operation=operation,
                latency_ms=latency_ms,
                timestamp=utcnow(),
                context=context or {}
            )

            self.slow_operations.append(slow_op)

            # Keep only recent slow operations
            if len(self.slow_operations) > self.max_slow_ops:
                self.slow_operations = self.slow_operations[-self.max_slow_ops:]

            # Log slow operation
            logger.warning(
                f"Slow operation detected: {operation} took {latency_ms:.2f}ms "
                f"(threshold: {metrics.slow_threshold_ms}ms) - {context}"
            )

    def get_metrics(self, operation: str) -> Dict[str, float]:
        """
        Get latency metrics for a specific operation.

        Args:
            operation: Operation name

        Returns:
            Dict with p50, p95, p99, count, min, max, mean
        """
        if operation not in self.metrics:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        return self.metrics[operation].get_percentiles()

    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        """
        Get metrics for all tracked operations.

        Returns:
            Dict mapping operation name to metrics
        """
        return {
            operation: metrics.get_percentiles()
            for operation, metrics in self.metrics.items()
        }

    def get_slow_operations(
        self,
        operation: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent slow operations.

        Args:
            operation: Filter by operation name (optional)
            limit: Maximum number of results

        Returns:
            List of slow operation records
        """
        ops = self.slow_operations

        if operation:
            ops = [op for op in ops if op.operation == operation]

        # Return most recent first
        return [op.to_dict() for op in reversed(ops[-limit:])]

    def get_summary(self) -> Dict[str, Any]:
        """
        Get performance summary across all operations.

        Returns:
            Summary with total operations, slow count, metrics per operation
        """
        total_operations = sum(
            len(m.samples) for m in self.metrics.values()
        )
        total_slow = len(self.slow_operations)

        return {
            "total_operations": total_operations,
            "total_slow_operations": total_slow,
            "slow_percentage": (
                (total_slow / total_operations * 100) if total_operations > 0 else 0
            ),
            "operations": {
                op: {
                    **metrics.get_percentiles(),
                    "slow_count": metrics.get_slow_count(),
                    "slow_threshold_ms": metrics.slow_threshold_ms,
                }
                for op, metrics in self.metrics.items()
            },
        }

    def reset(self) -> None:
        """Reset all metrics and slow operation records."""
        self.metrics.clear()
        self.slow_operations.clear()

    def cleanup_expired_metrics(self, expiration_hours: int = 24) -> int:
        """
        Remove metrics that haven't been updated in the specified time period.

        This prevents unbounded memory growth in long-running applications
        by removing stale operation metrics.

        Args:
            expiration_hours: Hours of inactivity before metrics are removed (default: 24)

        Returns:
            Number of operations removed

        Example:
            >>> tracker = PerformanceTracker()
            >>> # Record some operations...
            >>> removed = tracker.cleanup_expired_metrics(expiration_hours=24)
            >>> print(f"Removed {removed} expired operations")
        """
        now = utcnow()
        expiration_threshold = now - timedelta(hours=expiration_hours)

        # Find expired operations
        expired_ops = [
            operation
            for operation, metrics in self.metrics.items()
            if metrics.last_updated < expiration_threshold
        ]

        # Remove expired metrics
        for operation in expired_ops:
            del self.metrics[operation]

        if expired_ops:
            logger.info(
                f"Cleaned up {len(expired_ops)} expired operations "
                f"(older than {expiration_hours} hours)"
            )

        return len(expired_ops)

    def set_slow_threshold(self, operation: str, threshold_ms: float) -> None:
        """
        Set custom slow threshold for an operation.

        Args:
            operation: Operation name
            threshold_ms: Threshold in milliseconds
        """
        if operation in self.metrics:
            self.metrics[operation].slow_threshold_ms = threshold_ms

        self.default_thresholds[operation] = threshold_ms


# Global performance tracker instance (OB-06: double-check locking)
_global_tracker: Optional[PerformanceTracker] = None
_perf_tracker_lock = threading.Lock()


def get_performance_tracker() -> PerformanceTracker:
    """
    Get global performance tracker instance.

    Returns:
        Global PerformanceTracker instance
    """
    global _global_tracker

    if _global_tracker is None:
        with _perf_tracker_lock:
            if _global_tracker is None:
                _global_tracker = PerformanceTracker()

    return _global_tracker


def reset_performance_tracker() -> None:
    """Reset global performance tracker (useful for testing)."""
    global _global_tracker
    _global_tracker = None
