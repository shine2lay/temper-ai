"""Tests for loop state manager."""
import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone
from src.self_improvement.loop.state_manager import (
    LoopStateManager,
    StateTransitionError,
    M5LoopStateRecord,
    _record_to_state
)
from src.self_improvement.loop.models import LoopState, LoopStatus, Phase


class TestRecordToState:
    """Test _record_to_state conversion function."""

    def test_record_to_state_basic(self):
        """Test converting record to state."""
        now = datetime.now(timezone.utc)
        record = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="running",
            iteration_number=1,
            phase_data={"key": "value"},
            last_error=None,
            started_at=now,
            updated_at=now
        )

        state = _record_to_state(record)

        assert isinstance(state, LoopState)
        assert state.agent_name == "test_agent"
        assert state.current_phase == Phase.DETECT
        assert state.status == LoopStatus.RUNNING
        assert state.iteration_number == 1
        assert state.phase_data == {"key": "value"}
        assert state.last_error is None
        assert state.started_at == now
        assert state.updated_at == now

    def test_record_to_state_with_error(self):
        """Test converting record with error."""
        now = datetime.now(timezone.utc)
        record = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="analyze",
            status="failed",
            iteration_number=2,
            phase_data=None,
            last_error="Test error",
            started_at=now,
            updated_at=now
        )

        state = _record_to_state(record)

        assert state.status == LoopStatus.FAILED
        assert state.last_error == "Test error"
        assert state.phase_data == {}


class TestStateTransitionError:
    """Test StateTransitionError exception."""

    def test_state_transition_error(self):
        """Test creating StateTransitionError."""
        error = StateTransitionError("Invalid transition")

        assert isinstance(error, Exception)
        assert "Invalid transition" in str(error)


class TestLoopStateManagerInit:
    """Test LoopStateManager initialization."""

    def test_initialization_default(self):
        """Test initialization with default session factory."""
        # This would use get_session in real usage
        manager = LoopStateManager()

        assert manager._session_factory is not None

    def test_initialization_custom_factory(self):
        """Test initialization with custom session factory."""
        mock_factory = Mock()

        manager = LoopStateManager(session_factory=mock_factory)

        assert manager._session_factory is mock_factory


class TestLoopStateManagerState:
    """Test state CRUD operations."""

    def test_get_state_none(self):
        """Test getting state that doesn't exist."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        result = manager.get_state("nonexistent")

        assert result is None

    def test_create_state(self):
        """Test creating initial state."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        state = manager.create_state("test_agent")

        assert isinstance(state, LoopState)
        assert state.agent_name == "test_agent"
        assert state.current_phase == Phase.DETECT
        assert state.status == LoopStatus.RUNNING
        assert state.iteration_number == 1
        mock_session.merge.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_update_state(self):
        """Test updating state."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        now = datetime.now(timezone.utc)
        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.ANALYZE,
            status=LoopStatus.RUNNING,
            iteration_number=2,
            started_at=now,
            updated_at=now
        )

        manager.update_state(state)

        mock_session.merge.assert_called_once()
        mock_session.commit.assert_called_once()
        # Check updated_at was updated
        assert state.updated_at >= now


class TestLoopStateManagerTransitions:
    """Test phase transitions."""

    def test_can_transition_valid(self):
        """Test valid phase transitions."""
        manager = LoopStateManager()

        # Test all valid transitions
        assert manager.can_transition(Phase.DETECT, Phase.ANALYZE) is True
        assert manager.can_transition(Phase.ANALYZE, Phase.STRATEGY) is True
        assert manager.can_transition(Phase.STRATEGY, Phase.EXPERIMENT) is True
        assert manager.can_transition(Phase.EXPERIMENT, Phase.DEPLOY) is True
        assert manager.can_transition(Phase.DEPLOY, Phase.DETECT) is True

    def test_can_transition_invalid(self):
        """Test invalid phase transitions."""
        manager = LoopStateManager()

        # Test invalid transitions
        assert manager.can_transition(Phase.DETECT, Phase.STRATEGY) is False
        assert manager.can_transition(Phase.ANALYZE, Phase.DETECT) is False
        assert manager.can_transition(Phase.DETECT, Phase.DEPLOY) is False

    def test_rollback_phase_not_supported(self):
        """Test rollback phase raises NotImplementedError."""
        manager = LoopStateManager()

        with pytest.raises(NotImplementedError, match="Phase rollback not supported"):
            manager.rollback_phase("test_agent")


class TestLoopStateManagerControl:
    """Test pause/resume/fail operations."""

    def test_pause(self):
        """Test pausing loop."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="running",
            iteration_number=1,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.pause("test_agent")

        # Should have called update (merge + commit)
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_pause_no_state_raises(self):
        """Test pausing without state raises ValueError."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="No state found"):
            manager.pause("nonexistent")

    def test_resume(self):
        """Test resuming paused loop."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="paused",
            iteration_number=1,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.resume("test_agent")

        # Should have called update
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_resume_not_paused_raises(self):
        """Test resuming non-paused loop raises ValueError."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="running",
            iteration_number=1,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="Loop not paused"):
            manager.resume("test_agent")

    def test_mark_failed(self):
        """Test marking loop as failed."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="running",
            iteration_number=1,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.mark_failed("test_agent", "Database connection failed")

        # Should have called update
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_mark_completed(self):
        """Test marking iteration as completed."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="deploy",
            status="running",
            iteration_number=1,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.mark_completed("test_agent")

        # Should have called update
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_reset_state(self):
        """Test resetting (deleting) state."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_record = Mock()
        mock_session.exec.return_value.first.return_value = mock_record
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.reset_state("test_agent")

        mock_session.delete.assert_called_once_with(mock_record)
        mock_session.commit.assert_called_once()

    def test_update_phase_data(self):
        """Test updating phase-specific data."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="experiment",
            status="running",
            iteration_number=1,
            phase_data={"existing": "data"},
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.update_phase_data("test_agent", {"new": "value"})

        # Should have called update
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_update_phase_data_no_state_raises(self):
        """Test update_phase_data raises ValueError when no state exists."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="No state found"):
            manager.update_phase_data("nonexistent", {"key": "val"})

    def test_resume_no_state_raises(self):
        """Test resume raises ValueError when no state exists."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="No state found"):
            manager.resume("nonexistent")

    def test_mark_failed_no_state_raises(self):
        """Test mark_failed raises ValueError when no state exists."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="No state found"):
            manager.mark_failed("nonexistent", "some error")

    def test_mark_completed_no_state_raises(self):
        """Test mark_completed raises ValueError when no state exists."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(ValueError, match="No state found"):
            manager.mark_completed("nonexistent")

    def test_reset_state_no_record(self):
        """Test reset_state when no record exists (no-op)."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        manager.reset_state("nonexistent")

        mock_session.delete.assert_not_called()
        mock_session.commit.assert_not_called()


class TestTransitionToPhase:
    """Test transition_to_phase method."""

    def _make_manager_with_state(self, phase="detect", status="running", iteration=1):
        """Helper to create manager with a mocked existing state."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        now = datetime.now(timezone.utc)
        mock_session.exec.return_value.first.return_value = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase=phase,
            status=status,
            iteration_number=iteration,
            phase_data={},
            started_at=now,
            updated_at=now,
        )
        mock_factory = Mock(return_value=mock_session)
        manager = LoopStateManager(session_factory=mock_factory)
        return manager, mock_session

    def test_transition_valid(self):
        """Test valid transition from DETECT to ANALYZE."""
        manager, mock_session = self._make_manager_with_state(phase="detect")

        state = manager.transition_to_phase("test_agent", Phase.ANALYZE)

        assert state.current_phase == Phase.ANALYZE
        assert mock_session.merge.call_count >= 1
        assert mock_session.commit.call_count >= 1

    def test_transition_no_state_raises(self):
        """Test transition raises StateTransitionError when no state."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_factory = Mock(return_value=mock_session)

        manager = LoopStateManager(session_factory=mock_factory)

        with pytest.raises(StateTransitionError, match="No state found"):
            manager.transition_to_phase("nonexistent", Phase.ANALYZE)

    def test_transition_invalid_raises(self):
        """Test invalid transition raises StateTransitionError."""
        manager, _ = self._make_manager_with_state(phase="detect")

        with pytest.raises(StateTransitionError, match="Invalid transition"):
            manager.transition_to_phase("test_agent", Phase.DEPLOY)

    def test_transition_deploy_to_detect_increments_iteration(self):
        """Test looping back to DETECT increments iteration number."""
        manager, mock_session = self._make_manager_with_state(
            phase="deploy", iteration=3
        )

        state = manager.transition_to_phase("test_agent", Phase.DETECT)

        assert state.current_phase == Phase.DETECT
        assert state.iteration_number == 4

    def test_transition_non_detect_does_not_increment(self):
        """Test non-DETECT transition does not change iteration number."""
        manager, _ = self._make_manager_with_state(phase="analyze", iteration=2)

        state = manager.transition_to_phase("test_agent", Phase.STRATEGY)

        assert state.iteration_number == 2


class TestRecordToStateEdgeCases:
    """Test _record_to_state edge cases."""

    def test_record_with_json_string_phase_data(self):
        """Test converting record when phase_data is a JSON string."""
        now = datetime.now(timezone.utc)
        record = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="detect",
            status="running",
            iteration_number=1,
            phase_data='{"key": "value"}',
            last_error=None,
            started_at=now,
            updated_at=now,
        )

        state = _record_to_state(record)

        assert state.phase_data == {"key": "value"}

    def test_record_with_empty_dict_phase_data(self):
        """Test converting record when phase_data is empty dict."""
        now = datetime.now(timezone.utc)
        record = M5LoopStateRecord(
            agent_name="test_agent",
            current_phase="strategy",
            status="running",
            iteration_number=1,
            phase_data={},
            last_error=None,
            started_at=now,
            updated_at=now,
        )

        state = _record_to_state(record)

        assert state.phase_data == {}
