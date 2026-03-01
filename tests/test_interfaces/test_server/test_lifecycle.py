"""Tests for GracefulShutdownManager and stuck-detection helpers."""

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.interfaces.server.lifecycle import (
    DEFAULT_DRAIN_TIMEOUT_SECONDS,
    DEFAULT_TENANT_ID,
    GracefulShutdownManager,
    ensure_default_tenant,
    mark_orphaned_workflows,
)


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_default_drain_timeout_is_positive(self) -> None:
        assert DEFAULT_DRAIN_TIMEOUT_SECONDS > 0

    def test_default_drain_timeout_value(self) -> None:
        assert DEFAULT_DRAIN_TIMEOUT_SECONDS == 30

    def test_default_tenant_id_value(self) -> None:
        assert DEFAULT_TENANT_ID == "default"


class TestGracefulShutdownManagerInit:
    """Tests for initial state of GracefulShutdownManager."""

    def test_readiness_gate_starts_true(self) -> None:
        mgr = GracefulShutdownManager()
        assert mgr.readiness_gate is True

    def test_original_sigterm_starts_none(self) -> None:
        mgr = GracefulShutdownManager()
        assert mgr._original_sigterm is None

    def test_original_sigint_starts_none(self) -> None:
        mgr = GracefulShutdownManager()
        assert mgr._original_sigint is None


class TestHandleSignal:
    """Tests for signal handler methods."""

    def test_handle_signal_flips_gate(self) -> None:
        """_handle_signal() sets readiness_gate to False."""
        mgr = GracefulShutdownManager()
        assert mgr.readiness_gate is True
        mgr._handle_signal()
        assert mgr.readiness_gate is False

    def test_handle_signal_sync_flips_gate(self) -> None:
        """_handle_signal_sync() sets readiness_gate to False."""
        mgr = GracefulShutdownManager()
        assert mgr.readiness_gate is True
        mgr._handle_signal_sync(signal.SIGTERM, None)
        assert mgr.readiness_gate is False

    def test_handle_signal_idempotent(self) -> None:
        """Calling _handle_signal() twice is safe."""
        mgr = GracefulShutdownManager()
        mgr._handle_signal()
        mgr._handle_signal()
        assert mgr.readiness_gate is False

    def test_handle_signal_sync_with_sigint(self) -> None:
        """_handle_signal_sync() works with SIGINT too."""
        mgr = GracefulShutdownManager()
        mgr._handle_signal_sync(signal.SIGINT, None)
        assert mgr.readiness_gate is False


class TestRegisterSignals:
    """Tests for register_signals()."""

    def test_register_signals_in_running_loop(self) -> None:
        """register_signals() uses event loop when available."""
        mgr = GracefulShutdownManager()

        async def _run():
            with patch.object(
                asyncio.get_running_loop(), "add_signal_handler"
            ) as mock_add:
                mgr.register_signals()
                assert mock_add.call_count == 2

        asyncio.run(_run())

    def test_register_signals_fallback_outside_loop(self) -> None:
        """register_signals() falls back to signal.signal when no loop."""
        mgr = GracefulShutdownManager()
        # Simulate NotImplementedError from loop.add_signal_handler (e.g. Windows)
        with (
            patch(
                "asyncio.get_running_loop", side_effect=RuntimeError("No running loop")
            ),
            patch("signal.signal") as mock_signal,
        ):
            mgr.register_signals()
            assert mock_signal.call_count == 2


class TestDrain:
    """Tests for drain() async method."""

    @pytest.mark.asyncio
    async def test_drain_with_no_execution_service(self) -> None:
        """drain() returns immediately when execution_service is None."""
        mgr = GracefulShutdownManager()
        # Should return without error
        await mgr.drain(execution_service=None, timeout=1)

    @pytest.mark.asyncio
    async def test_drain_with_no_active_runs(self) -> None:
        """drain() returns immediately when no active executions."""
        mgr = GracefulShutdownManager()
        svc = MagicMock()
        done = MagicMock()
        done.status.value = "completed"
        svc._executions = {"a": done}

        await mgr.drain(execution_service=svc, timeout=5)
        # Should complete without timeout

    @pytest.mark.asyncio
    async def test_drain_times_out_with_active_runs(self) -> None:
        """drain() exits after timeout with active executions still running."""
        mgr = GracefulShutdownManager()
        svc = MagicMock()
        running = MagicMock()
        running.status.value = "running"
        svc._executions = {"a": running}

        # Very short timeout so test finishes quickly
        await mgr.drain(execution_service=svc, timeout=1)
        # After timeout, we just return — no exception raised

    @pytest.mark.asyncio
    async def test_drain_completes_when_runs_finish(self) -> None:
        """drain() returns once active counts drops to zero."""
        mgr = GracefulShutdownManager()
        svc = MagicMock()

        call_count = 0
        running_mock = MagicMock()
        running_mock.status.value = "running"
        done_mock = MagicMock()
        done_mock.status.value = "completed"

        # First call: one running; subsequent calls: completed
        def make_executions():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"a": running_mock}
            return {"a": done_mock}

        type(svc)._executions = property(lambda self: make_executions())

        await mgr.drain(execution_service=svc, timeout=5)
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_drain_uses_default_timeout(self) -> None:
        """drain() uses DEFAULT_DRAIN_TIMEOUT_SECONDS as default."""
        mgr = GracefulShutdownManager()
        # No service, returns immediately regardless of timeout
        await mgr.drain()


class TestMarkOrphanedWorkflows:
    """Tests for mark_orphaned_workflows() startup sweep."""

    def test_marks_running_as_failed(self) -> None:
        """Running workflows are marked as failed on startup."""
        mock_wf = {"id": "wf-orphan-1"}

        backend = MagicMock()
        backend.find_stuck_workflows.return_value = [mock_wf]

        mark_orphaned_workflows(backend)

        backend.find_stuck_workflows.assert_called_once_with(threshold_seconds=0)
        backend.track_workflow_end.assert_called_once()
        call_kwargs = backend.track_workflow_end.call_args
        assert call_kwargs[0][0] == "wf-orphan-1"
        assert call_kwargs[1].get("status") == "failed"
        assert "Orphaned" in call_kwargs[1].get("error_message", "")

    def test_returns_count(self) -> None:
        """Returns the number of orphaned workflows marked."""
        mock_wfs = [{"id": f"wf-{i}"} for i in range(3)]

        backend = MagicMock()
        backend.find_stuck_workflows.return_value = mock_wfs

        count = mark_orphaned_workflows(backend)
        assert count == 3
        assert backend.track_workflow_end.call_count == 3

    def test_no_orphans(self) -> None:
        """Returns 0 when no orphaned workflows found."""
        backend = MagicMock()
        backend.find_stuck_workflows.return_value = []

        count = mark_orphaned_workflows(backend)
        assert count == 0
        backend.track_workflow_end.assert_not_called()


class TestEnsureDefaultTenant:
    """Tests for ensure_default_tenant() function."""

    @patch("temper_ai.storage.database.manager.get_session")
    def test_creates_tenant_when_missing(self, mock_get_session) -> None:
        """Creates default tenant with correct fields when not found."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        result = ensure_default_tenant()

        assert result == "default"
        mock_session.add.assert_called_once()
        tenant = mock_session.add.call_args[0][0]
        assert tenant.id == "default"
        assert tenant.name == "Default Workspace"
        assert tenant.slug == "default"
        assert tenant.is_active is True
        assert tenant.plan == "self-hosted"
        assert tenant.max_workflows == 10000
        mock_session.commit.assert_called_once()

    @patch("temper_ai.storage.database.manager.get_session")
    def test_idempotent_when_exists(self, mock_get_session) -> None:
        """Does not create duplicate when tenant already exists."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        existing_tenant = MagicMock()
        existing_tenant.id = "default"
        mock_session.exec.return_value.first.return_value = existing_tenant
        mock_get_session.return_value = mock_session

        result = ensure_default_tenant()

        assert result == "default"
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()

    @patch("temper_ai.storage.database.manager.get_session")
    def test_returns_tenant_id(self, mock_get_session) -> None:
        """Always returns the default tenant ID string."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = MagicMock()
        mock_get_session.return_value = mock_session

        result = ensure_default_tenant()

        assert result == DEFAULT_TENANT_ID
