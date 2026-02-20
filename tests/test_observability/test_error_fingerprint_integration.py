"""Integration tests for error fingerprinting with SQL backend.

Tests the record_error_fingerprint() upsert, get_top_errors() queries,
and the _record_fingerprint_safe() tracker hook.
"""
import pytest
from unittest.mock import MagicMock, patch

from temper_ai.observability.backend import ErrorFingerprintData
from temper_ai.observability.error_fingerprinting import (
    ErrorClassification,
    compute_error_fingerprint,
)
from temper_ai.observability._tracker_helpers import _record_fingerprint_safe


# ============================================================================
# _record_fingerprint_safe
# ============================================================================


class TestRecordFingerprintSafe:
    """Tests for the _record_fingerprint_safe helper in _tracker_helpers."""

    def test_calls_backend_record(self):
        backend = MagicMock()
        backend.record_error_fingerprint = MagicMock(return_value=True)

        error = ValueError("Test error message")
        _record_fingerprint_safe(backend, error, workflow_id="wf-123", agent_name="test_agent")

        backend.record_error_fingerprint.assert_called_once()
        fp_data = backend.record_error_fingerprint.call_args[0][0]
        assert isinstance(fp_data, ErrorFingerprintData)
        assert fp_data.workflow_id == "wf-123"
        assert fp_data.agent_name == "test_agent"
        assert fp_data.error_type == "ValueError"
        assert len(fp_data.fingerprint) == 16

    def test_never_raises_on_backend_error(self):
        backend = MagicMock()
        backend.record_error_fingerprint.side_effect = RuntimeError("DB down")

        error = ValueError("Test error")
        # Should not raise despite backend error — exception is swallowed
        _record_fingerprint_safe(backend, error)
        backend.record_error_fingerprint.assert_called_once()

    def test_never_raises_on_missing_method(self):
        backend = MagicMock(spec=[])  # No methods

        error = ValueError("Test error")
        # Should not raise despite missing method — hasattr check prevents call
        _record_fingerprint_safe(backend, error)
        assert not hasattr(backend, 'record_error_fingerprint')

    def test_passes_classification(self):
        backend = MagicMock()
        backend.record_error_fingerprint = MagicMock(return_value=True)

        from temper_ai.shared.utils.exceptions import LLMError, ErrorCode
        error = LLMError("Timed out", error_code=ErrorCode.LLM_TIMEOUT)
        _record_fingerprint_safe(backend, error)

        fp_data = backend.record_error_fingerprint.call_args[0][0]
        assert fp_data.classification == ErrorClassification.TRANSIENT.value


# ============================================================================
# Composite backend delegation
# ============================================================================


class TestCompositeBackendFingerprinting:
    """Tests for CompositeBackend error fingerprint delegation."""

    def test_record_error_fingerprint_fans_out(self):
        from temper_ai.observability.backends.composite_backend import CompositeBackend

        primary = MagicMock()
        primary.record_error_fingerprint = MagicMock(return_value=True)
        secondary = MagicMock()
        secondary.record_error_fingerprint = MagicMock(return_value=False)

        composite = CompositeBackend(primary, [secondary])
        fp_data = ErrorFingerprintData(
            fingerprint="a1b2c3d4e5f67890",
            error_type="ValueError",
            error_code="VALUE_ERROR",
            classification="permanent",
            normalized_message="Invalid input",
            sample_message="Invalid input: value=42",
        )
        result = composite.record_error_fingerprint(fp_data)

        assert result is True  # Returns primary's result
        primary.record_error_fingerprint.assert_called_once()
        secondary.record_error_fingerprint.assert_called_once()

    def test_get_top_errors_from_primary(self):
        from temper_ai.observability.backends.composite_backend import CompositeBackend

        primary = MagicMock()
        primary.get_top_errors = MagicMock(return_value=[{"fingerprint": "abc"}])
        secondary = MagicMock()

        composite = CompositeBackend(primary, [secondary])
        result = composite.get_top_errors(limit=5)

        assert len(result) == 1
        assert result[0]["fingerprint"] == "abc"
        primary.get_top_errors.assert_called_once_with(5, None, None)

    def test_secondary_failure_does_not_propagate(self):
        from temper_ai.observability.backends.composite_backend import CompositeBackend

        primary = MagicMock()
        primary.record_error_fingerprint = MagicMock(return_value=True)
        secondary = MagicMock()
        secondary.record_error_fingerprint = MagicMock(
            side_effect=RuntimeError("Secondary down")
        )

        composite = CompositeBackend(primary, [secondary])
        fp_data = ErrorFingerprintData(
            fingerprint="a1b2c3d4e5f67890",
            error_type="ValueError",
            error_code="VALUE_ERROR",
            classification="permanent",
            normalized_message="Error",
            sample_message="Error",
        )
        # Should not raise
        result = composite.record_error_fingerprint(fp_data)
        assert result is True


# ============================================================================
# NoOp backend
# ============================================================================


class TestNoOpBackendFingerprinting:
    """Tests for NoOpBackend error fingerprint methods."""

    def test_record_returns_false(self):
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        fp_data = ErrorFingerprintData(
            fingerprint="a1b2c3d4e5f67890",
            error_type="ValueError",
            error_code="VALUE_ERROR",
            classification="permanent",
            normalized_message="Error",
            sample_message="Error",
        )
        result = backend.record_error_fingerprint(fp_data)
        assert result is False

    def test_get_top_errors_returns_empty(self):
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        result = backend.get_top_errors()
        assert result == []


# ============================================================================
# Error result fingerprint in _sequential_helpers
# ============================================================================


class TestBuildErrorResultFingerprint:
    """Tests that _build_error_result includes error fingerprint."""

    def test_build_error_result_includes_fingerprint(self):
        from temper_ai.stage.executors._sequential_helpers import _build_error_result

        error = ValueError("Invalid agent config")
        result = _build_error_result("test_agent", error, 1.5)

        assert result["status"] == "failed"
        assert result["output_data"]["error_fingerprint"] is not None
        assert len(result["output_data"]["error_fingerprint"]) == 16

    def test_build_error_result_deterministic(self):
        from temper_ai.stage.executors._sequential_helpers import _build_error_result

        error1 = ValueError("Invalid agent config")
        error2 = ValueError("Invalid agent config")
        result1 = _build_error_result("agent1", error1, 1.0)
        result2 = _build_error_result("agent2", error2, 2.0)

        # Same error type and message → same fingerprint
        assert result1["output_data"]["error_fingerprint"] == result2["output_data"]["error_fingerprint"]


# ============================================================================
# Alerting integration
# ============================================================================


class TestAlertingErrorTypes:
    """Tests for new MetricType entries in alerting."""

    def test_new_error_type_metric_exists(self):
        from temper_ai.observability.alerting import MetricType
        assert MetricType.NEW_ERROR_TYPE == "new_error_type"

    def test_error_spike_metric_exists(self):
        from temper_ai.observability.alerting import MetricType
        assert MetricType.ERROR_SPIKE == "error_spike"

    def test_default_rules_include_new_error_type(self):
        from temper_ai.observability.alerting import AlertManager
        manager = AlertManager()
        assert "new_error_type_detected" in manager.rules
        rule = manager.rules["new_error_type_detected"]
        assert rule.threshold == 0

    def test_default_rules_include_error_spike(self):
        from temper_ai.observability.alerting import AlertManager
        manager = AlertManager()
        assert "error_spike" in manager.rules
        rule = manager.rules["error_spike"]
        assert rule.threshold == 10
