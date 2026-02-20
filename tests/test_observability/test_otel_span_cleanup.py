"""Tests for OTEL span lifecycle cleanup (TTL + capacity eviction).

Verifies that stale spans are cleaned up to prevent memory leaks from
abandoned spans, and that the 3-tuple (Span, Context, monotonic_time)
format works correctly across all backend methods.
"""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.observability.backends.otel_backend import (
    CLEANUP_THRESHOLD,
    MAX_ACTIVE_SPANS,
    SPAN_TTL_SECONDS,
    _cleanup_stale_spans,
)


@pytest.fixture
def otel_backend():
    """Create OTelBackend with mocked OTEL SDK using 3-tuple spans."""
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_span.return_value = mock_span

    with patch("temper_ai.observability.backends.otel_backend.otel_trace") as mock_trace:
        mock_trace.set_span_in_context.return_value = MagicMock()
        from temper_ai.observability.backends.otel_backend import OTelBackend

        backend = OTelBackend.__new__(OTelBackend)
        backend._tracer = mock_tracer
        backend._active_spans = {}

        # Create mock metrics
        for attr in [
            "_workflow_counter", "_llm_call_counter", "_tool_call_counter",
            "_llm_latency_histogram", "_cost_counter", "_tokens_counter",
            "_llm_iteration_counter", "_cache_hit_counter", "_cache_miss_counter",
            "_retry_counter", "_cb_state_change_counter",
            "_dialogue_convergence_histogram", "_stage_cost_counter",
            "_failover_counter",
        ]:
            setattr(backend, attr, MagicMock())

        yield backend, mock_span


NOW = datetime.now(timezone.utc)


def _make_mock_span():
    """Create a mock span with required methods."""
    span = MagicMock()
    span.set_status = MagicMock()
    span.set_attribute = MagicMock()
    span.end = MagicMock()
    span.add_event = MagicMock()
    return span


class TestCleanupStaleTTL:
    """TTL-based eviction tests."""

    def test_ttl_eviction_removes_old_spans(self, otel_backend):
        backend, _ = otel_backend
        old_span = _make_mock_span()
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        backend._active_spans["old-1"] = (old_span, MagicMock(), old_time)

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        assert cleaned == 1
        assert "old-1" not in backend._active_spans
        old_span.end.assert_called_once()

    def test_ttl_eviction_marks_error_status(self, otel_backend):
        backend, _ = otel_backend
        old_span = _make_mock_span()
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        backend._active_spans["old-1"] = (old_span, MagicMock(), old_time)

        _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        old_span.set_status.assert_called_once()
        args = old_span.set_status.call_args
        assert "TTL exceeded" in str(args)

    def test_ttl_eviction_sets_ttl_expired_attribute(self, otel_backend):
        backend, _ = otel_backend
        old_span = _make_mock_span()
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        backend._active_spans["old-1"] = (old_span, MagicMock(), old_time)

        _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        old_span.set_attribute.assert_called_once_with("maf.status", "ttl_expired")

    def test_multiple_expired_spans_cleaned(self, otel_backend):
        backend, _ = otel_backend
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        for i in range(5):
            backend._active_spans[f"old-{i}"] = (
                _make_mock_span(), MagicMock(), old_time,
            )

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        assert cleaned == 5
        assert len(backend._active_spans) == 0

    def test_fresh_spans_preserved_during_ttl_eviction(self, otel_backend):
        backend, _ = otel_backend
        fresh_span = _make_mock_span()
        fresh_time = time.monotonic()
        backend._active_spans["fresh-1"] = (fresh_span, MagicMock(), fresh_time)

        old_span = _make_mock_span()
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        backend._active_spans["old-1"] = (old_span, MagicMock(), old_time)

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        assert cleaned == 1
        assert "fresh-1" in backend._active_spans
        assert "old-1" not in backend._active_spans
        fresh_span.end.assert_not_called()

    def test_no_cleanup_when_all_fresh(self, otel_backend):
        backend, _ = otel_backend
        fresh_time = time.monotonic()
        for i in range(10):
            backend._active_spans[f"fresh-{i}"] = (
                _make_mock_span(), MagicMock(), fresh_time,
            )

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        assert cleaned == 0
        assert len(backend._active_spans) == 10


class TestCleanupCapacity:
    """Capacity-based eviction tests."""

    def test_capacity_eviction_trims_oldest(self, otel_backend):
        backend, _ = otel_backend
        base_time = time.monotonic()
        max_spans = 5

        # Create more than max_spans
        for i in range(8):
            backend._active_spans[f"span-{i}"] = (
                _make_mock_span(), MagicMock(), base_time + i,
            )

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, max_spans)

        assert cleaned == 3
        assert len(backend._active_spans) == max_spans
        # Oldest spans should be removed
        assert "span-0" not in backend._active_spans
        assert "span-1" not in backend._active_spans
        assert "span-2" not in backend._active_spans
        # Newest should remain
        assert "span-7" in backend._active_spans
        assert "span-6" in backend._active_spans

    def test_capacity_eviction_ends_evicted_spans(self, otel_backend):
        backend, _ = otel_backend
        base_time = time.monotonic()
        max_spans = 2

        spans = []
        for i in range(4):
            span = _make_mock_span()
            spans.append(span)
            backend._active_spans[f"span-{i}"] = (
                span, MagicMock(), base_time + i,
            )

        _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, max_spans)

        # Oldest 2 should have been ended
        spans[0].end.assert_called_once()
        spans[1].end.assert_called_once()
        # Newest 2 should not
        spans[2].end.assert_not_called()
        spans[3].end.assert_not_called()

    def test_no_capacity_eviction_when_under_limit(self, otel_backend):
        backend, _ = otel_backend
        for i in range(5):
            backend._active_spans[f"span-{i}"] = (
                _make_mock_span(), MagicMock(), time.monotonic(),
            )

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)

        assert cleaned == 0
        assert len(backend._active_spans) == 5


class TestCleanupCombined:
    """TTL + capacity combined tests."""

    def test_ttl_then_capacity(self, otel_backend):
        backend, _ = otel_backend
        old_time = time.monotonic() - SPAN_TTL_SECONDS - 1
        fresh_base = time.monotonic()
        max_spans = 2

        # 2 expired + 4 fresh (capacity 2 -> 2 fresh also evicted)
        backend._active_spans["expired-0"] = (
            _make_mock_span(), MagicMock(), old_time,
        )
        backend._active_spans["expired-1"] = (
            _make_mock_span(), MagicMock(), old_time,
        )
        for i in range(4):
            backend._active_spans[f"fresh-{i}"] = (
                _make_mock_span(), MagicMock(), fresh_base + i,
            )

        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, max_spans)

        # 2 TTL + 2 capacity = 4 total
        assert cleaned == 4
        assert len(backend._active_spans) == max_spans

    def test_returns_zero_on_empty(self, otel_backend):
        backend, _ = otel_backend
        cleaned = _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)
        assert cleaned == 0


class TestThreeTupleCompat:
    """Verify all backend methods work with 3-tuple (Span, Context, float)."""

    def test_start_span_stores_three_tuple(self, otel_backend):
        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)

        entry = backend._active_spans.get("wf-1")
        assert entry is not None
        assert len(entry) == 3
        span, ctx, created_at = entry
        assert span is mock_span
        assert isinstance(created_at, float)

    def test_end_span_unpacks_three_tuple(self, otel_backend):
        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        # Should not raise on 3-tuple unpack
        backend.track_workflow_end("wf-1", NOW, "completed")
        assert "wf-1" not in backend._active_spans

    def test_add_event_unpacks_three_tuple(self, otel_backend):
        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        mock_span.add_event.reset_mock()
        # track_workflow_end calls _add_event internally
        backend.track_workflow_end("wf-1", NOW, "failed", error_message="boom")
        # Should have added at least one event without error
        assert mock_span.add_event.call_count >= 1

    def test_update_workflow_metrics_three_tuple(self, otel_backend):
        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        # Should not raise on 3-tuple unpack
        backend.update_workflow_metrics("wf-1", 5, 2, 1000, 0.05)
        mock_span.set_attribute.assert_any_call(
            "maf.workflow.total_tokens", 1000,
        )

    def test_track_stage_end_three_tuple(self, otel_backend):
        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        # Should not raise on 3-tuple unpack
        backend.track_stage_end(
            "s-1", NOW, "completed",
            num_agents_executed=3, num_agents_succeeded=2,
            num_agents_failed=1,
        )
        assert "s-1" not in backend._active_spans

    def test_set_agent_output_three_tuple(self, otel_backend):
        from temper_ai.observability.backend import AgentOutputData

        backend, mock_span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        backend.track_agent_start("a-1", "s-1", "optimist", {}, NOW)
        # Should not raise on 3-tuple unpack
        backend.set_agent_output(
            "a-1", {},
            metrics=AgentOutputData(
                total_tokens=500, estimated_cost_usd=0.01,
                confidence_score=0.9,
            ),
        )
        mock_span.set_attribute.assert_any_call("maf.agent.total_tokens", 500)


class TestAmortizedTrigger:
    """Verify cleanup only runs when span count exceeds CLEANUP_THRESHOLD."""

    def test_cleanup_triggers_above_threshold(self, otel_backend):
        backend, mock_span = otel_backend
        # Pre-fill with CLEANUP_THRESHOLD spans
        for i in range(CLEANUP_THRESHOLD):
            backend._active_spans[f"pre-{i}"] = (
                _make_mock_span(), MagicMock(), time.monotonic(),
            )

        # Adding one more should trigger cleanup (>CLEANUP_THRESHOLD)
        with patch(
            "temper_ai.observability.backends.otel_backend._cleanup_stale_spans",
        ) as mock_cleanup:
            mock_cleanup.return_value = 0
            backend.track_workflow_start("trigger-wf", "test", {}, NOW)
            mock_cleanup.assert_called_once()

    def test_cleanup_does_not_trigger_below_threshold(self, otel_backend):
        backend, mock_span = otel_backend
        # Fill with fewer than CLEANUP_THRESHOLD spans
        for i in range(CLEANUP_THRESHOLD - 2):
            backend._active_spans[f"pre-{i}"] = (
                _make_mock_span(), MagicMock(), time.monotonic(),
            )

        with patch(
            "temper_ai.observability.backends.otel_backend._cleanup_stale_spans",
        ) as mock_cleanup:
            mock_cleanup.return_value = 0
            backend.track_workflow_start("trigger-wf", "test", {}, NOW)
            mock_cleanup.assert_not_called()


class TestConstants:
    """Guard tests to detect accidental mutation of span lifecycle constants.

    These verify specific values rather than behavior because the behavioral
    tests (TestCleanupStaleTTL, TestCleanupCapacity, TestAmortizedTrigger)
    use these constants dynamically. These tests catch unintentional edits.
    """

    def test_ttl_is_one_hour(self):
        """Guard: TTL must remain 1 hour to prevent premature span eviction."""
        assert SPAN_TTL_SECONDS == 3600  # noqa: duplicate

    def test_max_active_spans(self):
        """Guard: capacity limit prevents unbounded memory growth."""
        assert MAX_ACTIVE_SPANS == 10000  # noqa: duplicate

    def test_cleanup_threshold(self):
        """Guard: amortized cleanup trigger point."""
        assert CLEANUP_THRESHOLD == 100  # noqa: duplicate

    def test_threshold_less_than_max(self):
        assert CLEANUP_THRESHOLD < MAX_ACTIVE_SPANS
