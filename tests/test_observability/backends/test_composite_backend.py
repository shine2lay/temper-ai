"""Tests for CompositeBackend — fan-out, error isolation, read delegation."""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.observability.backend import (
    LLMCallData,
    ObservabilityBackend,
    ToolCallData,
    WorkflowStartData,
)
from src.observability.backends.composite_backend import CompositeBackend
from src.observability.backends.noop_backend import NoOpBackend


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestCompositeBackendFanOut:
    """Verify calls are fanned out to primary + secondaries."""

    def test_track_workflow_start_fans_out(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        backend = CompositeBackend(primary=primary, secondaries=[secondary])

        backend.track_workflow_start(
            "wf-1", "test_wf", {"key": "val"}, _utcnow(),
            data=WorkflowStartData(environment="test"),
        )

        primary.track_workflow_start.assert_called_once()
        secondary.track_workflow_start.assert_called_once()

    def test_track_workflow_end_fans_out(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        backend = CompositeBackend(primary=primary, secondaries=[secondary])

        backend.track_workflow_end("wf-1", _utcnow(), "completed")
        primary.track_workflow_end.assert_called_once()
        secondary.track_workflow_end.assert_called_once()

    def test_track_llm_call_fans_out(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        backend = CompositeBackend(primary=primary, secondaries=[secondary])

        data = LLMCallData(
            prompt="hello", response="world",
            prompt_tokens=10, completion_tokens=20,
            latency_ms=100, estimated_cost_usd=0.01,
        )
        backend.track_llm_call("llm-1", "agent-1", "ollama", "test", _utcnow(), data)
        primary.track_llm_call.assert_called_once()
        secondary.track_llm_call.assert_called_once()


class TestCompositeBackendErrorIsolation:
    """Secondary failures must not propagate."""

    def test_secondary_error_does_not_crash(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        secondary.track_workflow_start.side_effect = RuntimeError("boom")

        backend = CompositeBackend(primary=primary, secondaries=[secondary])
        # Should NOT raise
        backend.track_workflow_start("wf-1", "wf", {}, _utcnow())
        primary.track_workflow_start.assert_called_once()

    def test_secondary_error_logged(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        secondary.track_stage_start.side_effect = RuntimeError("oops")

        backend = CompositeBackend(primary=primary, secondaries=[secondary])
        with patch("src.observability.backends.composite_backend.logger") as mock_logger:
            backend.track_stage_start("s1", "wf-1", "stage", {}, _utcnow())
            mock_logger.warning.assert_called_once()

    def test_primary_error_propagates(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        primary.track_workflow_start.side_effect = RuntimeError("primary down")
        backend = CompositeBackend(primary=primary)

        with pytest.raises(RuntimeError, match="primary down"):
            backend.track_workflow_start("wf-1", "wf", {}, _utcnow())


class TestCompositeBackendReadDelegation:
    """Reads and sessions are primary-only."""

    def test_get_session_context_from_primary(self) -> None:
        primary = NoOpBackend()
        backend = CompositeBackend(primary=primary)

        with backend.get_session_context() as session:
            assert session is None  # NoOpBackend yields None

    def test_get_stats_includes_composite_info(self) -> None:
        primary = NoOpBackend()
        sec1 = NoOpBackend()
        sec2 = NoOpBackend()
        backend = CompositeBackend(primary=primary, secondaries=[sec1, sec2])

        stats = backend.get_stats()
        assert stats["composite"] is True
        assert stats["num_secondaries"] == 2
        assert stats["backend_type"] == "noop"

    def test_cleanup_delegates_to_primary(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        primary.cleanup_old_records.return_value = {"workflows": 5}
        backend = CompositeBackend(primary=primary)

        result = backend.cleanup_old_records(30)
        assert result == {"workflows": 5}
        primary.cleanup_old_records.assert_called_once_with(30, False)

    def test_getattr_forwards_to_primary(self) -> None:
        """aggregate_workflow_metrics and similar are forwarded."""
        primary = MagicMock(spec=NoOpBackend)
        primary.aggregate_workflow_metrics = MagicMock(return_value={"total_tokens": 42})
        backend = CompositeBackend(primary=primary)

        result = backend.aggregate_workflow_metrics("wf-1")
        assert result == {"total_tokens": 42}


class TestCompositeBackendMultipleSecondaries:
    """Multiple secondaries all get called."""

    def test_all_secondaries_called(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        secs = [MagicMock(spec=NoOpBackend) for _ in range(3)]
        backend = CompositeBackend(primary=primary, secondaries=secs)

        backend.track_agent_start("a1", "s1", "agent", {}, _utcnow())
        for s in secs:
            s.track_agent_start.assert_called_once()

    def test_one_secondary_failure_does_not_block_others(self) -> None:
        primary = MagicMock(spec=NoOpBackend)
        sec1 = MagicMock(spec=NoOpBackend)
        sec1.track_agent_end.side_effect = RuntimeError("sec1 down")
        sec2 = MagicMock(spec=NoOpBackend)

        backend = CompositeBackend(primary=primary, secondaries=[sec1, sec2])
        backend.track_agent_end("a1", _utcnow(), "completed")

        # sec2 should still be called despite sec1 failure
        sec2.track_agent_end.assert_called_once()
