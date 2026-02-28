"""
Tests for _ensure_session() context manager deduplication in ExecutionTracker.

Validates that track_stage() and track_agent() correctly reuse parent sessions
when available, create new sessions when none exist, and clean up properly on errors.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.observability.tracker import ExecutionTracker, WorkflowTrackingParams


@pytest.fixture
def mock_backend():
    """Create a mock observability backend with session context support."""
    backend = MagicMock()
    mock_session = MagicMock(name="mock_session")

    @contextmanager
    def fake_session_context():
        yield mock_session

    backend.get_session_context = MagicMock(side_effect=fake_session_context)
    return backend


@pytest.fixture
def tracker(mock_backend):
    """Create ExecutionTracker with mock backend and no alert manager."""
    alert_manager = MagicMock()
    return ExecutionTracker(
        backend=mock_backend,
        alert_manager=alert_manager,
    )


class TestEnsureSessionContextManager:
    """Tests for the _ensure_session() helper."""

    def test_with_existing_session_no_new_session(self, tracker, mock_backend):
        """When session stack is non-empty, _ensure_session should not open a new session."""
        tracker._session_stack.append(MagicMock(name="parent_session"))

        with tracker._ensure_session():
            pass

        mock_backend.get_session_context.assert_not_called()
        assert len(tracker._session_stack) == 1

    def test_without_session_creates_and_cleans_up(self, tracker, mock_backend):
        """When session stack is empty, _ensure_session opens a new session and pops on exit."""
        assert len(tracker._session_stack) == 0

        with tracker._ensure_session():
            assert len(tracker._session_stack) == 1

        mock_backend.get_session_context.assert_called_once()
        assert len(tracker._session_stack) == 0

    def test_cleanup_on_exception(self, tracker, mock_backend):
        """Session is popped even when body raises an exception."""
        assert len(tracker._session_stack) == 0

        with pytest.raises(ValueError, match="boom"):
            with tracker._ensure_session():
                assert len(tracker._session_stack) == 1
                raise ValueError("boom")

        assert len(tracker._session_stack) == 0
        mock_backend.get_session_context.assert_called_once()


class TestTrackStageSessionDedup:
    """Tests for track_stage() session deduplication."""

    def test_with_parent_session_no_new_session(self, tracker, mock_backend):
        """track_stage with parent session should not create a new session."""
        tracker._session_stack.append(MagicMock(name="parent_session"))

        with tracker.track_stage("test_stage", {}, "wf-123"):
            pass

        mock_backend.get_session_context.assert_not_called()
        mock_backend.track_stage_start.assert_called_once()
        assert len(tracker._session_stack) == 1

    def test_without_parent_session_creates_new(self, tracker, mock_backend):
        """track_stage without parent session should create a new session."""
        assert len(tracker._session_stack) == 0

        with tracker.track_stage("test_stage", {}, "wf-123") as stage_id:
            assert stage_id is not None
            assert len(tracker._session_stack) == 1

        mock_backend.get_session_context.assert_called_once()
        assert len(tracker._session_stack) == 0

    def test_context_stage_id_cleared_on_exit(self, tracker):
        """track_stage should clear context.stage_id on exit."""
        tracker._session_stack.append(MagicMock())

        with tracker.track_stage("s", {}, "wf-1") as stage_id:
            assert tracker.context.stage_id == stage_id

        assert tracker.context.stage_id is None

    def test_exception_cleans_up_session(self, tracker, mock_backend):
        """track_stage exception path should still clean up session stack."""
        assert len(tracker._session_stack) == 0

        with patch("temper_ai.observability.tracker._handle_stage_error") as mock_err:
            with pytest.raises(RuntimeError, match="stage_fail"):
                with tracker.track_stage("s", {}, "wf-1"):
                    assert len(tracker._session_stack) == 1
                    raise RuntimeError("stage_fail")

        assert len(tracker._session_stack) == 0
        assert tracker.context.stage_id is None
        mock_err.assert_called_once()


class TestTrackAgentSessionDedup:
    """Tests for track_agent() session deduplication."""

    def test_with_parent_session_no_new_session(self, tracker, mock_backend):
        """track_agent with parent session should not create a new session."""
        tracker._session_stack.append(MagicMock(name="parent_session"))

        with tracker.track_agent("test_agent", {}, "stage-123"):
            pass

        mock_backend.get_session_context.assert_not_called()
        assert len(tracker._session_stack) == 1

    def test_without_parent_session_creates_new(self, tracker, mock_backend):
        """track_agent without parent session should create a new session."""
        assert len(tracker._session_stack) == 0

        with tracker.track_agent("test_agent", {}, "stage-123") as agent_id:
            assert agent_id is not None
            assert len(tracker._session_stack) == 1

        mock_backend.get_session_context.assert_called_once()
        assert len(tracker._session_stack) == 0

    def test_context_agent_id_cleared_on_exit(self, tracker):
        """track_agent should clear context.agent_id on exit."""
        tracker._session_stack.append(MagicMock())

        with tracker.track_agent("a", {}, "s-1") as agent_id:
            assert tracker.context.agent_id == agent_id

        assert tracker.context.agent_id is None

    def test_exception_cleans_up_session(self, tracker, mock_backend):
        """track_agent exception path should still clean up session stack."""
        assert len(tracker._session_stack) == 0

        with patch("temper_ai.observability.tracker._handle_agent_error") as mock_err:
            with pytest.raises(RuntimeError, match="agent_fail"):
                with tracker.track_agent("a", {}, "s-1"):
                    assert len(tracker._session_stack) == 1
                    raise RuntimeError("agent_fail")

        assert len(tracker._session_stack) == 0
        assert tracker.context.agent_id is None
        mock_err.assert_called_once()


class TestNestedSessions:
    """Tests for nested session behavior (e.g. track_stage inside track_workflow)."""

    def test_track_stage_inside_workflow_reuses_session(self, tracker, mock_backend):
        """track_stage inside track_workflow should reuse the workflow's session."""
        config = {"workflow": {"name": "test"}}
        params = WorkflowTrackingParams(
            workflow_name="test_wf",
            workflow_config=config,
        )

        with tracker.track_workflow(params) as workflow_id:
            assert len(tracker._session_stack) == 1
            session_before = tracker._session_stack[0]

            with tracker.track_stage("nested_stage", {}, workflow_id) as stage_id:
                assert stage_id is not None
                # Session stack should still be 1 (reused, not pushed again)
                assert len(tracker._session_stack) == 1
                assert tracker._session_stack[0] is session_before

        # After workflow exits, session stack is empty
        assert len(tracker._session_stack) == 0

    def test_track_agent_inside_workflow_reuses_session(self, tracker, mock_backend):
        """track_agent inside track_workflow should reuse the workflow's session."""
        config = {"workflow": {"name": "test"}}
        params = WorkflowTrackingParams(
            workflow_name="test_wf",
            workflow_config=config,
        )

        with tracker.track_workflow(params):
            assert len(tracker._session_stack) == 1

            with tracker.track_agent("nested_agent", {}, "stage-1") as agent_id:
                assert agent_id is not None
                assert len(tracker._session_stack) == 1

        assert len(tracker._session_stack) == 0

    def test_get_session_context_called_once_for_nested(self, tracker, mock_backend):
        """Only one get_session_context call for nested track_workflow > track_stage."""
        config = {"workflow": {"name": "test"}}
        params = WorkflowTrackingParams(
            workflow_name="test_wf",
            workflow_config=config,
        )

        with tracker.track_workflow(params) as workflow_id:
            with tracker.track_stage("s", {}, workflow_id):
                with tracker.track_agent("a", {}, "stage-1"):
                    pass

        # track_workflow opens one session; track_stage and track_agent reuse it
        assert mock_backend.get_session_context.call_count == 1
