"""Tests for OTelBackend to cover uncovered lines.

Uses module-level functions which don't require OTEL imports,
and tests OTelBackend methods by directly constructing mock instances.
"""

import time
from unittest.mock import MagicMock, patch

# Import module-level helpers that don't need opentelemetry
from temper_ai.observability.backends.otel_backend import (
    CLEANUP_THRESHOLD,
    MAX_ACTIVE_SPANS,
    SPAN_TTL_SECONDS,
    _add_event,
    _otel_safe_value,
)


class TestOTelSafeValue:
    """Test _otel_safe_value helper."""

    def test_str_passthrough(self):
        assert _otel_safe_value("hello") == "hello"

    def test_int_passthrough(self):
        assert _otel_safe_value(42) == 42

    def test_float_passthrough(self):
        assert _otel_safe_value(3.14) == 3.14

    def test_bool_passthrough(self):
        assert _otel_safe_value(True) is True

    def test_list_converted_to_str(self):
        assert _otel_safe_value([1, 2, 3]) == "[1, 2, 3]"

    def test_dict_converted_to_str(self):
        result = _otel_safe_value({"key": "value"})
        assert isinstance(result, str)

    def test_none_converted_to_str(self):
        assert _otel_safe_value(None) == "None"


class TestAddEvent:
    """Test _add_event helper."""

    def test_add_event_no_span(self):
        backend = MagicMock()
        backend._active_spans = {}
        _add_event(backend, "nonexistent", "test.event", {"key": "value"})

    def test_add_event_with_span(self):
        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}
        _add_event(backend, "entity-1", "test.event", {"key": "value"})
        mock_span.add_event.assert_called_once()

    def test_add_event_with_none_values(self):
        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}
        _add_event(backend, "entity-1", "test.event", {"key": "value", "empty": None})
        call_args = mock_span.add_event.call_args
        attrs = call_args[1].get("attributes", {})
        assert "empty" not in attrs

    def test_add_event_no_attributes(self):
        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}
        _add_event(backend, "entity-1", "test.event", None)
        mock_span.add_event.assert_called_once()

    def test_add_event_exception_swallowed(self):
        mock_span = MagicMock()
        mock_span.add_event.side_effect = RuntimeError("boom")
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}
        # Should not raise
        _add_event(backend, "entity-1", "test.event", {"key": "value"})


class TestStartSpan:
    """Test _start_span helper."""

    def _patch_otel_imports(self):
        """Return patches for opentelemetry imports inside _start_span."""
        mock_otel_context = MagicMock()
        mock_otel = MagicMock()
        mock_otel.context = mock_otel_context
        return (
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry": mock_otel,
                    "opentelemetry.context": mock_otel_context,
                },
            ),
            mock_otel_context,
        )

    def test_start_span_without_parent(self):
        from temper_ai.observability.backends.otel_backend import _start_span

        backend = MagicMock()
        backend._active_spans = {}
        backend._tracer.start_span.return_value = MagicMock()

        otel_patch, mock_ctx = self._patch_otel_imports()
        with (
            otel_patch,
            patch(
                "temper_ai.observability.backends.otel_backend.otel_trace"
            ) as mock_trace,
        ):
            mock_trace.set_span_in_context.return_value = MagicMock()
            _start_span(backend, "entity-1", "test:span", {"key": "value"})
            backend._tracer.start_span.assert_called_once()
            assert "entity-1" in backend._active_spans

    def test_start_span_with_parent(self):
        from temper_ai.observability.backends.otel_backend import _start_span

        parent_span = MagicMock()
        parent_ctx = MagicMock()
        backend = MagicMock()
        backend._active_spans = {
            "parent-1": (parent_span, parent_ctx, time.monotonic())
        }
        backend._tracer.start_span.return_value = MagicMock()

        otel_patch, mock_ctx = self._patch_otel_imports()
        with (
            otel_patch,
            patch(
                "temper_ai.observability.backends.otel_backend.otel_trace"
            ) as mock_trace,
        ):
            mock_trace.set_span_in_context.return_value = MagicMock()
            _start_span(
                backend, "child-1", "test:child", {"key": "value"}, parent_id="parent-1"
            )
            mock_ctx.attach.assert_called_once_with(parent_ctx)
            assert "child-1" in backend._active_spans

    def test_start_span_with_nonexistent_parent(self):
        from temper_ai.observability.backends.otel_backend import _start_span

        backend = MagicMock()
        backend._active_spans = {}
        backend._tracer.start_span.return_value = MagicMock()

        otel_patch, mock_ctx = self._patch_otel_imports()
        with (
            otel_patch,
            patch(
                "temper_ai.observability.backends.otel_backend.otel_trace"
            ) as mock_trace,
        ):
            mock_trace.set_span_in_context.return_value = MagicMock()
            _start_span(backend, "child-1", "test:child", {}, parent_id="nonexistent")
            assert "child-1" in backend._active_spans

    def test_start_span_triggers_cleanup(self):
        from temper_ai.observability.backends.otel_backend import _start_span

        backend = MagicMock()
        backend._active_spans = {}
        backend._tracer.start_span.return_value = MagicMock()

        for i in range(CLEANUP_THRESHOLD + 1):
            backend._active_spans[f"span-{i}"] = (MagicMock(), None, time.monotonic())

        otel_patch, mock_ctx = self._patch_otel_imports()
        with (
            otel_patch,
            patch(
                "temper_ai.observability.backends.otel_backend.otel_trace"
            ) as mock_trace,
            patch(
                "temper_ai.observability.backends.otel_backend._cleanup_stale_spans"
            ) as mock_cleanup,
        ):
            mock_trace.set_span_in_context.return_value = MagicMock()
            _start_span(backend, "new-span", "test:new", {})
            mock_cleanup.assert_called_once()


class TestEndSpan:
    """Test _end_span helper."""

    def test_end_span_success(self):
        from temper_ai.observability.backends.otel_backend import _end_span

        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}

        mock_status_code = MagicMock()
        mock_status_code.OK = "OK"
        mock_status_code.ERROR = "ERROR"

        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = mock_status_code

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            _end_span(backend, "entity-1", "completed")
            mock_span.end.assert_called_once()
            assert "entity-1" not in backend._active_spans

    def test_end_span_error(self):
        from temper_ai.observability.backends.otel_backend import _end_span

        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}

        mock_status_code = MagicMock()
        mock_status_code.OK = "OK"
        mock_status_code.ERROR = "ERROR"

        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = mock_status_code

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            _end_span(backend, "entity-1", "failed", "some error")
            mock_span.end.assert_called_once()

    def test_end_span_nonexistent(self):
        from temper_ai.observability.backends.otel_backend import _end_span

        backend = MagicMock()
        backend._active_spans = {}
        _end_span(backend, "nonexistent", "completed")

    def test_end_span_exception_swallowed(self):
        from temper_ai.observability.backends.otel_backend import _end_span

        mock_span = MagicMock()
        mock_span.set_status.side_effect = RuntimeError("boom")
        backend = MagicMock()
        backend._active_spans = {"entity-1": (mock_span, None, time.monotonic())}

        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = MagicMock()

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            _end_span(backend, "entity-1", "completed")


class TestCleanupStaleSpans:
    """Test _cleanup_stale_spans function."""

    def test_ttl_eviction(self):
        from temper_ai.observability.backends.otel_backend import _cleanup_stale_spans

        mock_span = MagicMock()
        backend = MagicMock()
        backend._active_spans = {
            "old-span": (mock_span, None, time.monotonic() - 7200),
        }

        mock_status_code = MagicMock()
        mock_status_code.ERROR = "ERROR"
        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = mock_status_code

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            cleaned = _cleanup_stale_spans(backend, ttl=3600, max_spans=10000)
            assert cleaned == 1
            mock_span.end.assert_called_once()

    def test_capacity_eviction(self):
        from temper_ai.observability.backends.otel_backend import _cleanup_stale_spans

        backend = MagicMock()
        backend._active_spans = {}
        for i in range(10):
            mock_span = MagicMock()
            backend._active_spans[f"span-{i}"] = (mock_span, None, time.monotonic() + i)

        mock_status_code = MagicMock()
        mock_status_code.ERROR = "ERROR"
        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = mock_status_code

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            cleaned = _cleanup_stale_spans(backend, ttl=3600, max_spans=5)
            assert cleaned == 5

    def test_no_cleanup_needed(self):
        from temper_ai.observability.backends.otel_backend import _cleanup_stale_spans

        backend = MagicMock()
        mock_span = MagicMock()
        backend._active_spans = {"span-1": (mock_span, None, time.monotonic())}

        cleaned = _cleanup_stale_spans(backend, ttl=3600, max_spans=10000)
        assert cleaned == 0

    def test_ttl_eviction_exception_swallowed(self):
        from temper_ai.observability.backends.otel_backend import _cleanup_stale_spans

        mock_span = MagicMock()
        mock_span.set_status.side_effect = RuntimeError("boom")
        backend = MagicMock()
        backend._active_spans = {
            "old-span": (mock_span, None, time.monotonic() - 7200),
        }

        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = MagicMock()

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            cleaned = _cleanup_stale_spans(backend, ttl=3600, max_spans=10000)
            assert cleaned == 1

    def test_capacity_eviction_exception_swallowed(self):
        from temper_ai.observability.backends.otel_backend import _cleanup_stale_spans

        backend = MagicMock()
        backend._active_spans = {}
        for i in range(10):
            mock_span = MagicMock()
            mock_span.set_status.side_effect = RuntimeError("boom")
            backend._active_spans[f"span-{i}"] = (mock_span, None, time.monotonic() + i)

        mock_status_code = MagicMock()
        mock_status_code.ERROR = "ERROR"
        mock_otel_trace_mod = MagicMock()
        mock_otel_trace_mod.StatusCode = mock_status_code

        with patch.dict("sys.modules", {"opentelemetry.trace": mock_otel_trace_mod}):
            cleaned = _cleanup_stale_spans(backend, ttl=3600, max_spans=5)
            assert cleaned == 5


class TestRecordEventMetrics:
    """Test _record_event_metrics function."""

    def test_retry_event(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(backend, "resilience_retry", {"agent_name": "agent-1"})
        backend._retry_counter.add.assert_called_once()

    def test_circuit_breaker_event(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(
            backend,
            "resilience_circuit_breaker",
            {"breaker_name": "cb-1", "new_state": "open"},
        )
        backend._cb_state_change_counter.add.assert_called_once()

    def test_dialogue_metrics_event(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(
            backend,
            "dialogue_round_metrics",
            {"convergence_speed": 0.85, "stage_name": "analysis"},
        )
        backend._dialogue_convergence_histogram.record.assert_called_once()

    def test_dialogue_metrics_no_speed(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(backend, "dialogue_round_metrics", {})
        backend._dialogue_convergence_histogram.record.assert_not_called()

    def test_failover_event(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(
            backend,
            "resilience_failover_provider",
            {"from_provider": "openai", "to_provider": "anthropic"},
        )
        backend._failover_counter.add.assert_called_once()

    def test_cost_summary_event(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(
            backend,
            "cost_summary",
            {"total_cost_usd": 1.50, "stage_name": "analysis"},
        )
        backend._stage_cost_counter.add.assert_called_once()

    def test_cost_summary_zero_cost(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(backend, "cost_summary", {"total_cost_usd": 0.0})
        backend._stage_cost_counter.add.assert_not_called()

    def test_unknown_event_type(self):
        from temper_ai.observability.backends.otel_backend import _record_event_metrics

        backend = MagicMock()
        _record_event_metrics(backend, "unknown_event", {"key": "value"})


class TestInitMetricsFunctions:
    """Test metric initialization functions."""

    def test_init_core_metrics(self):
        from temper_ai.observability.backends.otel_backend import _init_core_metrics

        mock_backend = MagicMock()
        mock_meter = MagicMock()
        _init_core_metrics(mock_backend, mock_meter)
        assert mock_meter.create_counter.call_count >= 4
        assert mock_meter.create_histogram.call_count >= 1

    def test_init_resilience_metrics(self):
        from temper_ai.observability.backends.otel_backend import (
            _init_resilience_metrics,
        )

        mock_backend = MagicMock()
        mock_meter = MagicMock()
        _init_resilience_metrics(mock_backend, mock_meter)
        assert mock_meter.create_counter.call_count >= 5
        assert mock_meter.create_histogram.call_count >= 1

    def test_init_metrics_all(self):
        from temper_ai.observability.backends.otel_backend import _init_metrics

        mock_backend = MagicMock()
        mock_meter = MagicMock()
        _init_metrics(mock_backend, mock_meter)
        assert mock_meter.create_counter.call_count >= 9


class TestConstants:
    """Test that module-level constants are defined."""

    def test_span_ttl_seconds(self):
        assert SPAN_TTL_SECONDS == 3600

    def test_max_active_spans(self):
        assert MAX_ACTIVE_SPANS == 10000

    def test_cleanup_threshold(self):
        assert CLEANUP_THRESHOLD == 100
