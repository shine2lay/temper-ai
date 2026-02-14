"""Tests for M5 self-improvement loop orchestrator."""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from contextlib import nullcontext
from src.self_improvement.loop.orchestrator import M5SelfImprovementLoop
from src.self_improvement.loop.config import LoopConfig
from src.self_improvement.loop.models import (
    Phase,
    LoopStatus,
    LoopState,
    IterationResult,
    ProgressReport
)


@pytest.fixture
def mock_session_factory():
    """Create a mock session factory for testing."""
    def factory():
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        return mock_session
    return factory


@pytest.fixture
def mock_coord_db():
    """Create a mock coord_db with context manager support for transaction()."""
    coord_db = Mock()
    mock_conn = Mock()
    mock_conn.execute = Mock()
    mock_transaction = Mock()
    mock_transaction.__enter__ = Mock(return_value=mock_conn)
    mock_transaction.__exit__ = Mock(return_value=False)
    coord_db.transaction = Mock(return_value=mock_transaction)
    return coord_db


class TestM5SelfImprovementLoopInit:
    """Test orchestrator initialization."""

    def test_initialization_defaults(self, mock_coord_db, mock_session_factory):
        """Test initialization with default config."""
        obs_session = Mock()

        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

            assert loop.coord_db is mock_coord_db
            assert loop.obs_session is obs_session
            assert isinstance(loop.config, LoopConfig)
            assert loop.state_manager is not None
            assert loop.error_recovery is not None
            assert loop.metrics_collector is not None
            assert loop.executor is not None
            assert loop.continuous_executor is not None
            assert loop.progress_reporter is not None
            assert loop.state_coordinator is not None
            assert loop.health_checker is not None

    def test_initialization_custom_config(self, mock_coord_db, mock_session_factory):
        """Test initialization with custom config."""
        obs_session = Mock()
        config = LoopConfig(detection_window_hours=5, analysis_window_hours=10)

        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session, config=config)

            assert loop.config is config
            assert loop.config.detection_window_hours == 5
            assert loop.config.analysis_window_hours == 10


class TestM5SelfImprovementLoopIteration:
    """Test single iteration execution."""

    def test_run_iteration_success(self, mock_coord_db, mock_session_factory):
        """Test successful iteration execution."""
        obs_session = Mock()

        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        # Mock executor
        expected_result = IterationResult(
            agent_name="test_agent",
            iteration_number=1,
            phases_completed=[Phase.DETECT, Phase.ANALYZE],
            success=True
        )
        loop.executor.execute_iteration = Mock(return_value=expected_result)

        # Mock state manager (no paused state)
        loop.state_manager.get_state = Mock(return_value=None)

        result = loop.run_iteration("test_agent")

        assert result is expected_result
        loop.executor.execute_iteration.assert_called_once_with(
            agent_name="test_agent",
            start_phase=Phase.DETECT
        )

    def test_run_iteration_custom_start_phase(self, mock_coord_db, mock_session_factory):
        """Test iteration with custom start phase."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        expected_result = Mock(spec=IterationResult)
        loop.executor.execute_iteration = Mock(return_value=expected_result)
        loop.state_manager.get_state = Mock(return_value=None)

        loop.run_iteration("test_agent", start_phase=Phase.STRATEGY)

        loop.executor.execute_iteration.assert_called_once_with(
            agent_name="test_agent",
            start_phase=Phase.STRATEGY
        )

    def test_run_iteration_paused_raises_error(self, mock_coord_db, mock_session_factory):
        """Test that running paused loop raises error."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        # Mock paused state
        paused_state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.PAUSED,
            iteration_number=1
        )
        loop.state_manager.get_state = Mock(return_value=paused_state)

        with pytest.raises(ValueError, match="Loop is paused.*Call resume"):
            loop.run_iteration("test_agent")


class TestM5SelfImprovementLoopContinuous:
    """Test continuous execution mode."""

    def test_run_continuous(self, mock_coord_db, mock_session_factory):
        """Test continuous execution delegates to executor."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        expected_summary = {"total_iterations": 5, "convergence": True}
        loop.continuous_executor.execute = Mock(return_value=expected_summary)

        result = loop.run_continuous(
            agent_names=["agent1", "agent2"],
            check_interval_minutes=15
        )

        assert result == expected_summary
        loop.continuous_executor.execute.assert_called_once_with(
            ["agent1", "agent2"],
            15
        )

    def test_run_continuous_default_interval(self, mock_coord_db, mock_session_factory):
        """Test continuous execution with default interval."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.continuous_executor.execute = Mock(return_value={})

        loop.run_continuous(agent_names=["agent1"])

        loop.continuous_executor.execute.assert_called_once_with(["agent1"], None)

    def test_run_continuous_empty_agents_list(self, mock_coord_db, mock_session_factory):
        """Test continuous execution with empty agent list."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.continuous_executor.execute = Mock(return_value={})

        loop.run_continuous(agent_names=[])

        loop.continuous_executor.execute.assert_called_once_with([], None)


class TestM5SelfImprovementLoopScheduled:
    """Test scheduled execution mode."""

    def test_run_scheduled_not_implemented(self, mock_coord_db, mock_session_factory):
        """Test scheduled mode raises NotImplementedError."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        with pytest.raises(NotImplementedError, match="Scheduled mode not yet implemented"):
            loop.run_scheduled("0 0 * * *")


class TestM5SelfImprovementLoopState:
    """Test state management operations."""

    def test_get_state(self, mock_coord_db, mock_session_factory):
        """Test getting state for agent."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        expected_state = {
            "agent_name": "test_agent",
            "current_phase": "detect",
            "status": "running",
            "iteration_number": 1
        }
        loop.state_coordinator.get_state_info = Mock(return_value=expected_state)

        result = loop.get_state("test_agent")

        assert result == expected_state
        loop.state_coordinator.get_state_info.assert_called_once_with("test_agent")

    def test_get_state_none(self, mock_coord_db, mock_session_factory):
        """Test getting state when agent has no state."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.state_coordinator.get_state_info = Mock(return_value=None)

        result = loop.get_state("nonexistent")

        assert result is None

    def test_reset_state(self, mock_coord_db, mock_session_factory):
        """Test resetting state for agent."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.state_coordinator.reset_state_and_metrics = Mock()

        loop.reset_state("test_agent")

        loop.state_coordinator.reset_state_and_metrics.assert_called_once_with("test_agent")

    def test_pause(self, mock_coord_db, mock_session_factory):
        """Test pausing loop for agent."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.state_coordinator.pause_execution = Mock()

        loop.pause("test_agent")

        loop.state_coordinator.pause_execution.assert_called_once_with("test_agent")

    def test_resume(self, mock_coord_db, mock_session_factory):
        """Test resuming paused loop."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.state_coordinator.resume_execution = Mock()

        loop.resume("test_agent")

        loop.state_coordinator.resume_execution.assert_called_once_with("test_agent")


class TestM5SelfImprovementLoopProgress:
    """Test progress reporting."""

    def test_get_progress(self, mock_coord_db, mock_session_factory):
        """Test getting progress report."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        state = Mock(spec=LoopState)
        metrics = Mock()
        expected_report = ProgressReport(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            current_iteration=1,
            total_iterations_completed=0,
            phase_progress={},
            health_status="healthy"
        )

        loop.state_manager.get_state = Mock(return_value=state)
        loop.metrics_collector.get_metrics = Mock(return_value=metrics)
        loop.progress_reporter.build_progress_report = Mock(return_value=expected_report)

        result = loop.get_progress("test_agent")

        assert result is expected_report
        loop.state_manager.get_state.assert_called_once_with("test_agent")
        loop.metrics_collector.get_metrics.assert_called_once_with("test_agent")
        loop.progress_reporter.build_progress_report.assert_called_once_with(
            "test_agent", state, metrics
        )


class TestM5SelfImprovementLoopHistory:
    """Test history retrieval."""

    def test_get_history_not_implemented(self, mock_coord_db, mock_session_factory):
        """Test history returns empty list (not implemented)."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        result = loop.get_history("test_agent")

        assert result == []

    def test_get_history_with_limit(self, mock_coord_db, mock_session_factory):
        """Test history with limit parameter."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        result = loop.get_history("test_agent", limit=10)

        assert result == []


class TestM5SelfImprovementLoopMetrics:
    """Test metrics retrieval."""

    def test_get_metrics(self, mock_coord_db, mock_session_factory):
        """Test getting metrics for agent."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        mock_metrics = Mock()
        expected_dict = {
            "agent_name": "test_agent",
            "total_iterations": 10,
            "success_rate": 0.8
        }
        mock_metrics.to_dict = Mock(return_value=expected_dict)

        loop.metrics_collector.get_metrics = Mock(return_value=mock_metrics)

        result = loop.get_metrics("test_agent")

        assert result == expected_dict
        loop.metrics_collector.get_metrics.assert_called_once_with("test_agent")

    def test_get_metrics_none(self, mock_coord_db, mock_session_factory):
        """Test getting metrics when none exist."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        loop.metrics_collector.get_metrics = Mock(return_value=None)

        result = loop.get_metrics("nonexistent")

        assert result is None


class TestM5SelfImprovementLoopHealth:
    """Test health check."""

    def test_health_check(self, mock_coord_db, mock_session_factory):
        """Test health check delegates to health checker."""
        obs_session = Mock()
        with patch('src.self_improvement.loop.state_manager.get_session', side_effect=mock_session_factory):
            loop = M5SelfImprovementLoop(mock_coord_db, obs_session)

        expected_health = {
            "status": "healthy",
            "components": {"database": "ok", "executor": "ok"}
        }
        loop.health_checker.check_health = Mock(return_value=expected_health)

        result = loop.health_check()

        assert result == expected_health
        loop.health_checker.check_health.assert_called_once()
