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
