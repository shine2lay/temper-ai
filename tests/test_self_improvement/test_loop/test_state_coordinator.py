"""Tests for state coordinator."""
import pytest
from unittest.mock import Mock
from datetime import datetime, timezone
from src.self_improvement.loop.state_coordinator import StateCoordinator
from src.self_improvement.loop.state_manager import LoopStateManager
from src.self_improvement.loop.metrics import MetricsCollector
from src.self_improvement.loop.models import LoopState, LoopStatus, Phase


class TestStateCoordinator:
    """Test StateCoordinator functionality."""

    def test_initialization(self):
        """Test coordinator initialization."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)

        coordinator = StateCoordinator(state_manager, metrics_collector)

        assert coordinator.state_manager is state_manager
        assert coordinator.metrics_collector is metrics_collector

    def test_get_state_info_with_state(self):
        """Test getting formatted state info."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        now = datetime.now(timezone.utc)
        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.RUNNING,
            iteration_number=3,
            last_error=None,
            started_at=now,
            updated_at=now
        )
        state_manager.get_state.return_value = state

        result = coordinator.get_state_info("test_agent")

        assert result is not None
        assert result["agent_name"] == "test_agent"
        assert result["current_phase"] == "detect"
        assert result["status"] == "running"
        assert result["iteration_number"] == 3
        assert result["last_error"] is None
        assert result["started_at"] == now.isoformat()
        assert result["updated_at"] == now.isoformat()

    def test_get_state_info_with_error(self):
        """Test getting state info with error."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        now = datetime.now(timezone.utc)
        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.ANALYZE,
            status=LoopStatus.FAILED,
            iteration_number=1,
            last_error="Database connection failed",
            started_at=now,
            updated_at=now
        )
        state_manager.get_state.return_value = state

        result = coordinator.get_state_info("test_agent")

        assert result["last_error"] == "Database connection failed"
        assert result["status"] == "failed"

    def test_get_state_info_no_state(self):
        """Test getting state info when no state exists."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        state_manager.get_state.return_value = None

        result = coordinator.get_state_info("nonexistent")

        assert result is None
        state_manager.get_state.assert_called_once_with("nonexistent")

    def test_reset_state_and_metrics(self):
        """Test resetting both state and metrics."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        coordinator.reset_state_and_metrics("test_agent")

        state_manager.reset_state.assert_called_once_with("test_agent")
        metrics_collector.reset_metrics.assert_called_once_with("test_agent")

    def test_pause_execution(self):
        """Test pausing execution."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        coordinator.pause_execution("test_agent")

        state_manager.pause.assert_called_once_with("test_agent")

    def test_resume_execution(self):
        """Test resuming execution."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        coordinator.resume_execution("test_agent")

        state_manager.resume.assert_called_once_with("test_agent")

    def test_get_state_info_all_phases(self):
        """Test state info for different phases."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        now = datetime.now(timezone.utc)

        # Test each phase
        for phase in Phase:
            state = LoopState(
                agent_name="test_agent",
                current_phase=phase,
                status=LoopStatus.RUNNING,
                iteration_number=1,
                started_at=now,
                updated_at=now
            )
            state_manager.get_state.return_value = state

            result = coordinator.get_state_info("test_agent")

            assert result["current_phase"] == phase.value

    def test_get_state_info_all_statuses(self):
        """Test state info for different statuses."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        now = datetime.now(timezone.utc)

        # Test each status
        for status in LoopStatus:
            state = LoopState(
                agent_name="test_agent",
                current_phase=Phase.DETECT,
                status=status,
                iteration_number=1,
                started_at=now,
                updated_at=now
            )
            state_manager.get_state.return_value = state

            result = coordinator.get_state_info("test_agent")

            assert result["status"] == status.value

    def test_multiple_agents_independent(self):
        """Test operations on multiple agents are independent."""
        state_manager = Mock(spec=LoopStateManager)
        metrics_collector = Mock(spec=MetricsCollector)
        coordinator = StateCoordinator(state_manager, metrics_collector)

        # Reset agent1
        coordinator.reset_state_and_metrics("agent1")

        # Pause agent2
        coordinator.pause_execution("agent2")

        # Verify calls were made correctly
        assert state_manager.reset_state.call_count == 1
        assert state_manager.pause.call_count == 1
        state_manager.reset_state.assert_called_with("agent1")
        state_manager.pause.assert_called_with("agent2")
