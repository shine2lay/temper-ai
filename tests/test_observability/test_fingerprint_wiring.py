"""Tests for fingerprint return value wiring and new-error-type alerting.

Covers:
- _record_fingerprint_safe returning bool (True/False/exception)
- handle_stage_error alerting on new fingerprint
- handle_agent_error passing workflow_id and agent_name
- _alert_new_error_type resilience
- Backward compatibility (no new params)
"""
import pytest
from unittest.mock import MagicMock, patch

from temper_ai.observability.backend import ErrorFingerprintData
from temper_ai.observability._tracker_helpers import (
    _alert_new_error_type,
    _record_fingerprint_safe,
    handle_agent_error,
    handle_stage_error,
)


# ============================================================================
# _record_fingerprint_safe — return value
# ============================================================================


class TestRecordFingerprintSafeReturnValue:
    """Verify _record_fingerprint_safe returns bool."""

    def test_returns_true_for_new_fingerprint(self):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = True

        result = _record_fingerprint_safe(backend, ValueError("new error"))

        assert result is True

    def test_returns_false_for_existing_fingerprint(self):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = False

        result = _record_fingerprint_safe(backend, ValueError("seen before"))

        assert result is False

    def test_returns_false_on_exception(self):
        backend = MagicMock()
        backend.record_error_fingerprint.side_effect = RuntimeError("DB down")

        result = _record_fingerprint_safe(backend, ValueError("err"))

        assert result is False

    def test_returns_false_when_backend_lacks_method(self):
        backend = MagicMock(spec=[])  # no record_error_fingerprint

        result = _record_fingerprint_safe(backend, ValueError("err"))

        assert result is False


# ============================================================================
# handle_stage_error — alerting wiring
# ============================================================================


class TestHandleStageErrorAlerting:
    """Verify handle_stage_error integrates fingerprint + alerting."""

    def _make_backend(self, is_new: bool = True):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = is_new
        return backend

    def test_alerts_when_new_fingerprint_and_alert_manager(self):
        backend = self._make_backend(is_new=True)
        emit = MagicMock()
        alert_mgr = MagicMock()

        handle_stage_error(
            backend, emit, "stage-1", ValueError("boom"),
            workflow_id="wf-1", alert_manager=alert_mgr,
        )

        alert_mgr.check_metric.assert_called_once()
        call_kwargs = alert_mgr.check_metric.call_args[1]
        assert call_kwargs["metric_type"] == "new_error_type"
        assert call_kwargs["context"]["error_type"] == "ValueError"
        assert call_kwargs["context"]["workflow_id"] == "wf-1"
        assert call_kwargs["context"]["stage_id"] == "stage-1"

    def test_no_alert_when_fingerprint_not_new(self):
        backend = self._make_backend(is_new=False)
        emit = MagicMock()
        alert_mgr = MagicMock()

        handle_stage_error(
            backend, emit, "stage-1", ValueError("seen"),
            workflow_id="wf-1", alert_manager=alert_mgr,
        )

        alert_mgr.check_metric.assert_not_called()

    def test_no_alert_when_alert_manager_is_none(self):
        backend = self._make_backend(is_new=True)
        emit = MagicMock()

        # Should not raise even though fingerprint is new
        handle_stage_error(
            backend, emit, "stage-1", ValueError("boom"),
            workflow_id="wf-1", alert_manager=None,
        )

        # Just ensure backend was still called
        backend.track_stage_end.assert_called_once()

    def test_backward_compat_no_new_params(self):
        """Calling with only positional args still works (no workflow_id, no alert_manager)."""
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = True
        emit = MagicMock()

        handle_stage_error(backend, emit, "stage-1", ValueError("err"))

        backend.track_stage_end.assert_called_once()
        emit.assert_called_once()


# ============================================================================
# handle_agent_error — alerting wiring
# ============================================================================


class TestHandleAgentErrorAlerting:
    """Verify handle_agent_error integrates fingerprint + alerting."""

    def _make_backend(self, is_new: bool = True):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = is_new
        return backend

    def test_passes_workflow_id_and_agent_name(self):
        backend = self._make_backend(is_new=True)
        emit = MagicMock()
        alert_mgr = MagicMock()

        handle_agent_error(
            backend, emit, "agent-1", ValueError("fail"),
            workflow_id="wf-42", agent_name="researcher", alert_manager=alert_mgr,
        )

        # Verify fingerprint got workflow_id and agent_name
        fp_data = backend.record_error_fingerprint.call_args[0][0]
        assert isinstance(fp_data, ErrorFingerprintData)
        assert fp_data.workflow_id == "wf-42"
        assert fp_data.agent_name == "researcher"

        # Verify alert context includes agent_name (not stage_id)
        alert_call = alert_mgr.check_metric.call_args[1]
        assert alert_call["context"]["agent_name"] == "researcher"
        assert alert_call["context"]["workflow_id"] == "wf-42"
        assert "stage_id" not in alert_call["context"]

    def test_no_alert_when_fingerprint_not_new(self):
        backend = self._make_backend(is_new=False)
        emit = MagicMock()
        alert_mgr = MagicMock()

        handle_agent_error(
            backend, emit, "agent-1", ValueError("seen"),
            alert_manager=alert_mgr,
        )

        alert_mgr.check_metric.assert_not_called()

    def test_backward_compat_no_new_params(self):
        """Calling with only positional args still works."""
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = False
        emit = MagicMock()

        handle_agent_error(backend, emit, "agent-1", ValueError("err"))

        backend.track_agent_end.assert_called_once()
        emit.assert_called_once()


# ============================================================================
# _alert_new_error_type — resilience
# ============================================================================


class TestAlertNewErrorType:
    """Verify _alert_new_error_type is best-effort."""

    def test_does_not_crash_when_alert_manager_raises(self):
        alert_mgr = MagicMock()
        alert_mgr.check_metric.side_effect = RuntimeError("Alert system down")

        # Must not raise
        _alert_new_error_type(
            alert_mgr, ValueError("boom"),
            workflow_id="wf-1", stage_id="s-1",
        )

        alert_mgr.check_metric.assert_called_once()

    def test_includes_all_context_fields(self):
        alert_mgr = MagicMock()

        _alert_new_error_type(
            alert_mgr, TypeError("bad type"),
            workflow_id="wf-99", stage_id="s-5", agent_name="coder",
        )

        ctx = alert_mgr.check_metric.call_args[1]["context"]
        assert ctx["error_type"] == "TypeError"
        assert ctx["workflow_id"] == "wf-99"
        assert ctx["stage_id"] == "s-5"
        assert ctx["agent_name"] == "coder"

    def test_omits_none_context_fields(self):
        alert_mgr = MagicMock()

        _alert_new_error_type(alert_mgr, ValueError("x"))

        ctx = alert_mgr.check_metric.call_args[1]["context"]
        assert ctx == {"error_type": "ValueError"}
