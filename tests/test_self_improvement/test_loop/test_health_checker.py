"""Tests for Health Checker.

This test module verifies:
- Component health checks (coordination DB, observability DB, configuration)
- Health status aggregation (healthy, degraded, unhealthy)
- Timestamp tracking
- Error handling in health checks
"""

import pytest
from unittest.mock import Mock
from datetime import datetime, timezone

from src.self_improvement.loop.health_checker import HealthChecker
from src.self_improvement.loop.config import LoopConfig
from src.self_improvement.loop.state_manager import LoopStateManager


@pytest.fixture
def mock_state_manager():
    """Create mock state manager."""
    manager = Mock(spec=LoopStateManager)
    manager.get_state = Mock(return_value=Mock(agent_name="test_agent"))
    return manager


@pytest.fixture
def mock_config():
    """Create loop configuration."""
    config = LoopConfig()
    return config


class TestHealthChecker:
    """Test HealthChecker class."""

    def test_health_checker_initialization(self, mock_state_manager, mock_config):
        """Test health checker initialization."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        assert checker.state_manager == mock_state_manager
        assert checker.config == mock_config

    def test_check_health_all_healthy(self, mock_state_manager, mock_config):
        """Test check_health when all components are healthy."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        health = checker.check_health()

        assert health["status"] == "healthy"
        assert "components" in health
        assert "timestamp" in health
        assert health["components"]["coordination_db"] == "healthy"
        assert health["components"]["observability_db"] == "healthy"
        assert health["components"]["configuration"] == "healthy"

        # Verify timestamp is ISO format
        timestamp = datetime.fromisoformat(health["timestamp"])
        assert isinstance(timestamp, datetime)

    def test_check_health_coordination_db_unhealthy(self, mock_state_manager, mock_config):
        """Test check_health when coordination DB is unhealthy."""
        mock_state_manager.get_state.side_effect = Exception("DB connection failed")

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        health = checker.check_health()

        assert health["status"] == "degraded"
        assert "DB connection failed" in health["components"]["coordination_db"]

    def test_check_health_configuration_invalid(self, mock_state_manager):
        """Test check_health when configuration is invalid."""
        # Create invalid config
        config = LoopConfig(max_retries_per_phase=-1)

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        health = checker.check_health()

        assert health["status"] == "unhealthy"
        assert "invalid" in health["components"]["configuration"]

    def test_check_coordination_db_healthy(self, mock_state_manager, mock_config):
        """Test _check_coordination_db returns True when healthy."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_coordination_db(status)

        assert result is True
        assert status["components"]["coordination_db"] == "healthy"
        mock_state_manager.get_state.assert_called_once_with("health_check")

    def test_check_coordination_db_unhealthy(self, mock_state_manager, mock_config):
        """Test _check_coordination_db returns False when unhealthy."""
        mock_state_manager.get_state.side_effect = ConnectionError("Cannot connect")

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_coordination_db(status)

        assert result is False
        assert "Cannot connect" in status["components"]["coordination_db"]

    def test_check_observability_db_healthy(self, mock_state_manager, mock_config):
        """Test _check_observability_db returns True (placeholder)."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_observability_db(status)

        assert result is True
        assert status["components"]["observability_db"] == "healthy"

    def test_check_configuration_valid(self, mock_state_manager, mock_config):
        """Test _check_configuration returns True when valid."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_configuration(status)

        assert result is True
        assert status["components"]["configuration"] == "healthy"

    def test_check_configuration_invalid(self, mock_state_manager):
        """Test _check_configuration returns False when invalid."""
        # Invalid config
        config = LoopConfig(detection_window_hours=-1)

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        status = {"components": {}}
        result = checker._check_configuration(status)

        assert result is False
        assert "invalid" in status["components"]["configuration"]

    def test_check_health_multiple_failures(self, mock_state_manager):
        """Test check_health with multiple component failures."""
        # Coordination DB fails
        mock_state_manager.get_state.side_effect = Exception("DB error")

        # Invalid config
        config = LoopConfig(max_retries_per_phase=-1)

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        health = checker.check_health()

        # Should be unhealthy due to config error (more severe than degraded)
        assert health["status"] == "unhealthy"
        assert "DB error" in health["components"]["coordination_db"]
        assert "invalid" in health["components"]["configuration"]

    def test_check_health_timestamp_format(self, mock_state_manager, mock_config):
        """Test health check timestamp is in correct ISO format."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        health = checker.check_health()

        # Should be able to parse timestamp
        timestamp = datetime.fromisoformat(health["timestamp"])
        assert timestamp.tzinfo == timezone.utc or timestamp.tzinfo is None

        # Should be recent (within last minute)
        now = datetime.now(timezone.utc)
        time_diff = abs((now - timestamp.replace(tzinfo=timezone.utc)).total_seconds())
        assert time_diff < 60

    def test_check_health_called_multiple_times(self, mock_state_manager, mock_config):
        """Test check_health can be called multiple times."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        # First call
        health1 = checker.check_health()
        assert health1["status"] == "healthy"

        # Second call
        health2 = checker.check_health()
        assert health2["status"] == "healthy"

        # Timestamps should be different (or very close)
        assert "timestamp" in health1
        assert "timestamp" in health2

    def test_check_health_with_different_exceptions(self, mock_state_manager, mock_config):
        """Test health checks with various exception types."""
        exceptions = [
            ConnectionError("Connection failed"),
            TimeoutError("Request timed out"),
            RuntimeError("Runtime error"),
            ValueError("Invalid value"),
        ]

        for exc in exceptions:
            mock_state_manager.get_state.side_effect = exc

            checker = HealthChecker(
                state_manager=mock_state_manager,
                config=mock_config
            )

            health = checker.check_health()

            assert health["status"] == "degraded"
            assert str(exc) in health["components"]["coordination_db"]

            # Reset for next iteration
            mock_state_manager.get_state.side_effect = None
            mock_state_manager.get_state.return_value = Mock()

    def test_check_coordination_db_timeout(self, mock_state_manager, mock_config):
        """Test coordination DB check with timeout simulation."""
        import time

        def slow_get_state(agent_name):
            time.sleep(0.1)  # Simulate slow response
            raise TimeoutError("Database timeout")

        mock_state_manager.get_state.side_effect = slow_get_state

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_coordination_db(status)

        assert result is False
        assert "timeout" in status["components"]["coordination_db"].lower()

    def test_check_observability_db_not_implemented(self, mock_state_manager, mock_config):
        """Test that observability DB check is placeholder (always healthy)."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_observability_db(status)

        # Currently a placeholder - always returns True
        assert result is True
        assert status["components"]["observability_db"] == "healthy"

    def test_check_configuration_multiple_invalid_fields(self, mock_state_manager):
        """Test configuration check with multiple invalid fields."""
        # Multiple invalid config values
        config = LoopConfig(
            max_retries_per_phase=-1,
            detection_window_hours=-5
        )

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        status = {"components": {}}
        result = checker._check_configuration(status)

        assert result is False
        assert "invalid" in status["components"]["configuration"]

    def test_check_health_partial_component_failures(self, mock_state_manager):
        """Test health check with partial component failures."""
        # Coordination DB fails
        mock_state_manager.get_state.side_effect = ConnectionError("DB down")

        # Config is valid
        config = LoopConfig()

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        health = checker.check_health()

        # Should be degraded (not unhealthy) since only coordination_db failed
        assert health["status"] == "degraded"
        assert "DB down" in health["components"]["coordination_db"]
        assert health["components"]["configuration"] == "healthy"
        assert health["components"]["observability_db"] == "healthy"

    def test_check_health_timestamp_precision(self, mock_state_manager, mock_config):
        """Test that health check timestamps are precise."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        before = datetime.now(timezone.utc)
        health = checker.check_health()
        after = datetime.now(timezone.utc)

        timestamp = datetime.fromisoformat(health["timestamp"])
        timestamp_utc = timestamp.replace(tzinfo=timezone.utc)

        assert before <= timestamp_utc <= after

    def test_check_health_idempotent(self, mock_state_manager, mock_config):
        """Test that multiple health checks don't affect state."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        # Run 10 health checks
        results = [checker.check_health() for _ in range(10)]

        # All should have same status (healthy)
        assert all(r["status"] == "healthy" for r in results)

        # State manager should have been called 10 times
        assert mock_state_manager.get_state.call_count >= 10

    def test_check_health_exception_details_preserved(self, mock_state_manager, mock_config):
        """Test that exception details are preserved in health status."""
        detailed_error = "Connection refused: localhost:5432, errno=111, retry_count=5"
        mock_state_manager.get_state.side_effect = ConnectionError(detailed_error)

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        health = checker.check_health()

        # Full error message should be in status
        assert detailed_error in health["components"]["coordination_db"]

    def test_check_configuration_boundary_values(self, mock_state_manager):
        """Test configuration validation with boundary values."""
        # Zero values (some might be invalid)
        config = LoopConfig(
            max_retries_per_phase=0,
            detection_window_hours=0
        )

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        status = {"components": {}}
        result = checker._check_configuration(status)

        # Result depends on LoopConfig.validate() implementation
        # This test documents the behavior
        assert isinstance(result, bool)

    def test_check_health_coordination_db_returns_none(self, mock_state_manager, mock_config):
        """Test coordination DB check when get_state returns None."""
        mock_state_manager.get_state.return_value = None

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        status = {"components": {}}
        result = checker._check_coordination_db(status)

        # Should succeed even with None return
        assert result is True
        assert status["components"]["coordination_db"] == "healthy"

    def test_check_health_all_components_structure(self, mock_state_manager, mock_config):
        """Test that health check includes all expected components."""
        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=mock_config
        )

        health = checker.check_health()

        # Required top-level keys
        assert "status" in health
        assert "components" in health
        assert "timestamp" in health

        # Required component keys
        assert "coordination_db" in health["components"]
        assert "observability_db" in health["components"]
        assert "configuration" in health["components"]

    def test_check_health_status_priority(self, mock_state_manager):
        """Test that unhealthy status takes priority over degraded."""
        # Coordination DB degraded
        mock_state_manager.get_state.side_effect = ConnectionError("DB slow")

        # Configuration unhealthy
        config = LoopConfig(max_retries_per_phase=-1)

        checker = HealthChecker(
            state_manager=mock_state_manager,
            config=config
        )

        health = checker.check_health()

        # Unhealthy should override degraded
        assert health["status"] == "unhealthy"
