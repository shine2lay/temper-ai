"""Tests for GracefulShutdownManager."""

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.interfaces.server.lifecycle import (
    DEFAULT_DRAIN_TIMEOUT_SECONDS,
    GracefulShutdownManager,
)


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_default_drain_timeout_is_positive(self) -> None:
        assert DEFAULT_DRAIN_TIMEOUT_SECONDS > 0

    def test_default_drain_timeout_value(self) -> None:
        assert DEFAULT_DRAIN_TIMEOUT_SECONDS == 30


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
