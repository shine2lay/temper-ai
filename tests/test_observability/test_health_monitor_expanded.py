"""Tests for expanded health monitor: DB and backend health checks."""

from unittest.mock import MagicMock, call

import pytest

from temper_ai.observability.health_monitor import (
    ObservabilityHealthMonitor,
    _check_backend_health,
    _check_db_health,
)


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


class TestDbHealthCheck:
    """Tests for _check_db_health helper and integration."""

    def test_db_healthy_when_select_succeeds(self) -> None:
        """DB check returns no issues when SELECT 1 succeeds."""
        session = MagicMock()
        factory = MagicMock(return_value=session)

        issues = _check_db_health(factory)

        assert issues == []
        factory.assert_called_once()
        session.execute.assert_called_once()
        session.close.assert_called_once()

    def test_db_unhealthy_when_connection_fails(self) -> None:
        """DB check returns issue when factory raises."""
        factory = MagicMock(side_effect=ConnectionError("refused"))

        issues = _check_db_health(factory)

        assert len(issues) == 1
        assert "Database connectivity failed: ConnectionError" in issues[0]

    def test_db_unhealthy_when_execute_fails(self) -> None:
        """DB check returns issue when execute raises."""
        session = MagicMock()
        session.execute.side_effect = RuntimeError("query failed")
        factory = MagicMock(return_value=session)

        issues = _check_db_health(factory)

        assert len(issues) == 1
        assert "Database connectivity failed: RuntimeError" in issues[0]

    def test_db_session_close_called_on_error(self) -> None:
        """Session close is called even when execute raises."""
        session = MagicMock()
        session.execute.side_effect = RuntimeError("query failed")
        factory = MagicMock(return_value=session)

        _check_db_health(factory)

        session.close.assert_called_once()

    def test_db_check_skipped_when_no_factory(self) -> None:
        """Monitor without db_session_factory does not run DB check."""
        monitor = ObservabilityHealthMonitor()

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []


class TestBackendHealthCheck:
    """Tests for _check_backend_health helper and integration."""

    def test_backend_healthy_when_get_stats_works(self) -> None:
        """Backend check returns no issues when get_stats succeeds."""
        backend = MagicMock()
        backend.get_stats.return_value = {"ok": True}

        issues = _check_backend_health(backend)

        assert issues == []
        backend.get_stats.assert_called_once()

    def test_backend_unhealthy_when_get_stats_raises(self) -> None:
        """Backend check returns issue when get_stats raises."""
        backend = MagicMock()
        backend.get_stats.side_effect = TimeoutError("timed out")

        issues = _check_backend_health(backend)

        assert len(issues) == 1
        assert "Backend health check failed: TimeoutError" in issues[0]

    def test_backend_no_get_stats_returns_healthy(self) -> None:
        """Backend without get_stats attribute is silently healthy."""
        backend = object()  # no get_stats attr

        issues = _check_backend_health(backend)

        assert issues == []

    def test_backend_check_skipped_when_no_backend(self) -> None:
        """Monitor without backend does not run backend check."""
        monitor = ObservabilityHealthMonitor()

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []


class TestCombinedChecks:
    """Tests for all checks running together."""

    def test_all_three_checks_combine_issues(self) -> None:
        """Issues from DB, backend, and buffer checks all appear."""
        # Failing DB
        db_factory = MagicMock(side_effect=ConnectionError("refused"))

        # Failing backend
        backend = MagicMock()
        backend.get_stats.side_effect = RuntimeError("down")

        # Buffer with DLQ issue
        buf = _make_buffer(dlq_size=200)

        monitor = ObservabilityHealthMonitor(
            buffer=buf,
            backend=backend,
            db_session_factory=db_factory,
        )

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 3
        assert any("Database" in i for i in status.issues)
        assert any("Backend" in i for i in status.issues)
        assert any("DLQ" in i for i in status.issues)

    def test_all_healthy_when_all_pass(self) -> None:
        """All checks pass results in healthy status."""
        session = MagicMock()
        db_factory = MagicMock(return_value=session)

        backend = MagicMock()
        backend.get_stats.return_value = {"ok": True}

        buf = _make_buffer()

        monitor = ObservabilityHealthMonitor(
            buffer=buf,
            backend=backend,
            db_session_factory=db_factory,
        )

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []
        assert "dlq_size" in status.stats

    def test_partial_failure_reported(self) -> None:
        """Only the failing check reports issues; others remain clean."""
        session = MagicMock()
        db_factory = MagicMock(return_value=session)

        backend = MagicMock()
        backend.get_stats.side_effect = RuntimeError("down")

        buf = _make_buffer()

        monitor = ObservabilityHealthMonitor(
            buffer=buf,
            backend=backend,
            db_session_factory=db_factory,
        )

        status = monitor.check_health()

        assert status.healthy is False
        assert len(status.issues) == 1
        assert "Backend" in status.issues[0]


class TestBackwardCompatibility:
    """Ensure existing callers without new params still work."""

    def test_init_without_new_params(self) -> None:
        """Constructor without backend or db_session_factory works."""
        monitor = ObservabilityHealthMonitor(
            buffer=_make_buffer(),
            alert_manager=MagicMock(),
            check_interval=30,
        )

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []

    def test_init_no_args_at_all(self) -> None:
        """Default constructor with no args works."""
        monitor = ObservabilityHealthMonitor()

        status = monitor.check_health()

        assert status.healthy is True
        assert status.issues == []
        assert status.stats == {}

    def test_buffer_only_still_works(self) -> None:
        """Original buffer-only usage still functions correctly."""
        buf = _make_buffer(dlq_size=200)
        monitor = ObservabilityHealthMonitor(buffer=buf)

        status = monitor.check_health()

        assert status.healthy is False
        assert any("DLQ" in i for i in status.issues)
        assert status.stats["dlq_size"] == 200
