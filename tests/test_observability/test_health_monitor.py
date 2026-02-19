"""Tests for the ObservabilityHealthMonitor."""
import threading
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.observability.health_monitor import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    HealthStatus,
    ObservabilityHealthMonitor,
)
from temper_ai.shared.constants.limits import THRESHOLD_LARGE_COUNT, THRESHOLD_MEDIUM_COUNT


def _make_buffer(
    dlq_size: int = 0,
    retry_queue_size: int = 0,
    pending_ids: int = 0,
) -> MagicMock:
    """Create a mock buffer with configurable stats."""
    buf = MagicMock()
    buf.get_stats.return_value = {
        "dlq_size": dlq_size,
        "retry_queue_size": retry_queue_size,
        "pending_ids": pending_ids,
        "llm_calls_buffered": 0,
        "tool_calls_buffered": 0,
        "total_buffered": 0,
    }
    return buf


class TestCheckHealth:
    """Tests for check_health method."""

    def test_healthy_buffer_all_below_thresholds(self) -> None:
        """All stats below thresholds produces healthy status."""
        buf = _make_buffer(dlq_size=0, retry_queue_size=0, pending_ids=0)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []
        assert status.stats["dlq_size"] == 0

    def test_dlq_warning_above_medium_threshold(self) -> None:
        """DLQ above THRESHOLD_MEDIUM_COUNT triggers warning."""
        buf = _make_buffer(dlq_size=THRESHOLD_MEDIUM_COUNT + 5)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 1
        assert "WARNING" in status.issues[0]
        assert "DLQ" in status.issues[0]

    def test_dlq_critical_above_large_threshold(self) -> None:
        """DLQ above THRESHOLD_LARGE_COUNT triggers critical."""
        buf = _make_buffer(dlq_size=THRESHOLD_LARGE_COUNT + 50)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 1
        assert "CRITICAL" in status.issues[0]
        assert "DLQ" in status.issues[0]

    def test_retry_queue_warning(self) -> None:
        """Retry queue above THRESHOLD_MEDIUM_COUNT triggers warning."""
        buf = _make_buffer(retry_queue_size=THRESHOLD_MEDIUM_COUNT + 5)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 1
        assert "Retry queue" in status.issues[0]

    def test_pending_ids_warning(self) -> None:
        """Pending IDs above THRESHOLD_LARGE_COUNT triggers warning."""
        buf = _make_buffer(pending_ids=THRESHOLD_LARGE_COUNT + 50)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 1
        assert "Pending IDs" in status.issues[0]

    def test_multiple_issues_reported(self) -> None:
        """Multiple threshold breaches all appear in issues."""
        buf = _make_buffer(
            dlq_size=THRESHOLD_LARGE_COUNT + 1,
            retry_queue_size=THRESHOLD_MEDIUM_COUNT + 1,
            pending_ids=THRESHOLD_LARGE_COUNT + 1,
        )
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 3

    def test_no_buffer_returns_healthy(self) -> None:
        """No buffer configured returns healthy status without crash."""
        monitor = ObservabilityHealthMonitor(buffer=None)

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []
        assert status.stats == {}


class TestPeriodicCheck:
    """Tests for start/stop lifecycle."""

    def test_start_and_stop_lifecycle(self) -> None:
        """Thread starts and stops cleanly."""
        monitor = ObservabilityHealthMonitor(
            buffer=_make_buffer(),
            check_interval=1,
        )

        monitor.start_periodic_check()
        assert monitor._check_thread is not None
        assert monitor._check_thread.is_alive()

        monitor.stop()
        assert monitor._check_thread is None

    def test_start_idempotent(self) -> None:
        """Calling start_periodic_check twice does not create a second thread."""
        monitor = ObservabilityHealthMonitor(
            buffer=_make_buffer(),
            check_interval=1,
        )

        monitor.start_periodic_check()
        first_thread = monitor._check_thread

        monitor.start_periodic_check()
        assert monitor._check_thread is first_thread

        monitor.stop()

    def test_stop_without_start_is_safe(self) -> None:
        """Calling stop without start does not raise."""
        monitor = ObservabilityHealthMonitor(buffer=_make_buffer())
        monitor.stop()
        assert monitor._check_thread is None


class TestHealthAlerts:
    """Tests for alert firing behavior."""

    def test_alert_fires_when_unhealthy(self) -> None:
        """Alert manager check_metric is called for unhealthy status."""
        alert_mgr = MagicMock()
        buf = _make_buffer(dlq_size=THRESHOLD_LARGE_COUNT + 1)
        monitor = ObservabilityHealthMonitor(
            buffer=buf, alert_manager=alert_mgr
        )

        status = monitor.check_health()
        monitor._fire_health_alert(status)

        alert_mgr.check_metric.assert_called_once()
        call_kwargs = alert_mgr.check_metric.call_args
        assert call_kwargs[1]["metric_type"] == "observability_health"
        assert call_kwargs[1]["value"] == len(status.issues)

    def test_no_alert_when_no_alert_manager(self) -> None:
        """No crash when alert_manager is None."""
        monitor = ObservabilityHealthMonitor(
            buffer=_make_buffer(dlq_size=THRESHOLD_LARGE_COUNT + 1),
            alert_manager=None,
        )

        status = monitor.check_health()
        monitor._fire_health_alert(status)  # Should not raise
        assert not status.healthy

    def test_alert_failure_does_not_propagate(self) -> None:
        """Alert manager exception is swallowed (best-effort)."""
        alert_mgr = MagicMock()
        alert_mgr.check_metric.side_effect = RuntimeError("alert backend down")
        monitor = ObservabilityHealthMonitor(
            buffer=_make_buffer(dlq_size=THRESHOLD_LARGE_COUNT + 1),
            alert_manager=alert_mgr,
        )

        status = monitor.check_health()
        monitor._fire_health_alert(status)  # Should not raise
        assert alert_mgr.check_metric.called


class TestHealthStatusDataclass:
    """Tests for the HealthStatus dataclass defaults."""

    def test_defaults(self) -> None:
        """HealthStatus has sensible defaults."""
        status = HealthStatus(healthy=True)
        assert status.issues == []
        assert status.stats == {}

    def test_default_check_interval_constant(self) -> None:
        """DEFAULT_CHECK_INTERVAL_SECONDS is 60."""
        assert DEFAULT_CHECK_INTERVAL_SECONDS == 60
