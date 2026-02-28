"""Tests for server health check models and functions."""

from unittest.mock import MagicMock, patch

from temper_ai.interfaces.server.health import (
    HealthResponse,
    ReadinessResponse,
    check_health,
    check_readiness,
)


class TestHealthResponse:
    """Tests for HealthResponse Pydantic model."""

    def test_defaults(self) -> None:
        """Default status and version are set correctly."""
        resp = HealthResponse(timestamp="2024-01-01T00:00:00+00:00")
        assert resp.status == "healthy"
        assert resp.version == "0.1.0"

    def test_timestamp_is_stored(self) -> None:
        """Provided timestamp is stored as-is."""
        ts = "2024-06-15T12:00:00+00:00"
        resp = HealthResponse(timestamp=ts)
        assert resp.timestamp == ts

    def test_custom_status(self) -> None:
        """Custom status overrides default."""
        resp = HealthResponse(status="degraded", timestamp="ts")
        assert resp.status == "degraded"

    def test_custom_version(self) -> None:
        """Custom version overrides default."""
        resp = HealthResponse(version="2.0.0", timestamp="ts")
        assert resp.version == "2.0.0"

    def test_model_dump(self) -> None:
        """model_dump() produces expected dict."""
        resp = HealthResponse(timestamp="ts")
        d = resp.model_dump()
        assert d["status"] == "healthy"
        assert d["version"] == "0.1.0"
        assert d["timestamp"] == "ts"


class TestReadinessResponse:
    """Tests for ReadinessResponse Pydantic model."""

    def test_ready_state(self) -> None:
        """Ready state stores all fields."""
        resp = ReadinessResponse(status="ready", database_ok=True, active_runs=0)
        assert resp.status == "ready"
        assert resp.database_ok is True
        assert resp.active_runs == 0

    def test_draining_state(self) -> None:
        """Draining state stores active_runs count."""
        resp = ReadinessResponse(status="draining", database_ok=True, active_runs=5)
        assert resp.status == "draining"
        assert resp.active_runs == 5

    def test_database_not_ok(self) -> None:
        """database_ok=False is stored correctly."""
        resp = ReadinessResponse(status="draining", database_ok=False, active_runs=0)
        assert resp.database_ok is False

    def test_model_dump_keys(self) -> None:
        """model_dump() contains expected keys."""
        resp = ReadinessResponse(status="ready", database_ok=True, active_runs=2)
        d = resp.model_dump()
        assert set(d.keys()) == {"status", "database_ok", "active_runs"}


class TestCheckHealth:
    """Tests for check_health() function."""

    def test_returns_health_response(self) -> None:
        """Returns a HealthResponse instance."""
        result = check_health()
        assert isinstance(result, HealthResponse)

    def test_status_is_healthy(self) -> None:
        """Status is always 'healthy'."""
        result = check_health()
        assert result.status == "healthy"

    def test_version_is_set(self) -> None:
        """Version field is non-empty."""
        result = check_health()
        assert result.version == "0.1.0"

    def test_timestamp_contains_T(self) -> None:
        """Timestamp is ISO 8601 format (contains 'T')."""
        result = check_health()
        assert "T" in result.timestamp

    def test_timestamp_is_string(self) -> None:
        """Timestamp field is a string."""
        result = check_health()
        assert isinstance(result.timestamp, str)

    def test_called_twice_returns_different_results(self) -> None:
        """Two calls return independent HealthResponse objects."""
        r1 = check_health()
        r2 = check_health()
        assert r1 is not r2


class TestCheckReadiness:
    """Tests for check_readiness() function."""

    @staticmethod
    def _make_mock_session():
        """Return a context manager mock for get_session."""
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_returns_readiness_response(self) -> None:
        """Returns a ReadinessResponse instance."""
        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness()
        assert isinstance(result, ReadinessResponse)

    def test_no_execution_service_zero_active_runs(self) -> None:
        """Active runs is 0 when no execution service provided."""
        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(execution_service=None, readiness_gate=True)
        assert result.active_runs == 0

    def test_ready_when_db_ok_and_gate_true(self) -> None:
        """Status is 'ready' when gate=True and DB check passes."""
        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(readiness_gate=True)
        assert result.status == "ready"
        assert result.database_ok is True

    def test_draining_when_gate_false(self) -> None:
        """Status is 'draining' when readiness gate is False."""
        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(readiness_gate=False)
        assert result.status == "draining"

    def test_draining_when_db_fails(self) -> None:
        """Status is 'draining' and database_ok=False when DB raises."""
        with patch(
            "temper_ai.storage.database.get_session",
            side_effect=Exception("DB unavailable"),
        ):
            result = check_readiness(readiness_gate=True)
        assert result.database_ok is False
        assert result.status == "draining"

    def test_counts_pending_and_running_only(self) -> None:
        """Active runs counts only 'pending' and 'running' statuses."""
        svc = MagicMock()
        pending = MagicMock()
        pending.status.value = "pending"
        running = MagicMock()
        running.status.value = "running"
        completed = MagicMock()
        completed.status.value = "completed"
        failed = MagicMock()
        failed.status.value = "failed"
        svc._executions = {"a": pending, "b": running, "c": completed, "d": failed}

        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(execution_service=svc, readiness_gate=True)
        assert result.active_runs == 2

    def test_no_active_runs_when_all_completed(self) -> None:
        """Zero active runs when all executions are in terminal states."""
        svc = MagicMock()
        done = MagicMock()
        done.status.value = "completed"
        svc._executions = {"a": done, "b": done}

        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(execution_service=svc, readiness_gate=True)
        assert result.active_runs == 0

    def test_service_without_executions_attr(self) -> None:
        """Service lacking _executions attribute is handled gracefully."""
        svc = MagicMock(spec=[])  # No _executions attribute

        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(execution_service=svc, readiness_gate=True)
        assert result.active_runs == 0

    def test_empty_executions_dict(self) -> None:
        """Empty _executions dict means zero active runs."""
        svc = MagicMock()
        svc._executions = {}

        mock_cm = self._make_mock_session()
        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            result = check_readiness(execution_service=svc, readiness_gate=True)
        assert result.active_runs == 0
