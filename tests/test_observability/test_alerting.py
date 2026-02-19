"""Tests for real-time alerting system.

Tests cover AlertRule creation, Alert triggering, threshold-based logic,
action execution (LOG_WARNING, LOG_ERROR, HALT_WORKFLOW), alert history,
and edge cases like duplicate alerts and invalid configurations.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from temper_ai.observability.alerting import (
    Alert,
    AlertAction,
    AlertManager,
    AlertRule,
    AlertSeverity,
    MetricType,
)


class TestAlertRule:
    """Tests for AlertRule dataclass."""

    def test_alert_rule_defaults(self):
        """Test alert rule with default values."""
        rule = AlertRule(name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0)
        assert rule.name == "test_rule"
        assert rule.metric_type == MetricType.COST_USD
        assert rule.threshold == 10.0
        assert rule.window_seconds == 0
        assert rule.severity == AlertSeverity.WARNING
        assert rule.actions == [AlertAction.LOG_WARNING]
        assert rule.enabled is True
        assert rule.metadata == {}

    def test_alert_rule_custom_values(self):
        """Test alert rule with custom values."""
        rule = AlertRule(
            name="critical_cost",
            metric_type=MetricType.COST_USD,
            threshold=50.0,
            window_seconds=300,
            severity=AlertSeverity.CRITICAL,
            actions=[AlertAction.LOG_ERROR, AlertAction.HALT_WORKFLOW],
            enabled=False,
            metadata={"description": "Critical threshold"},
        )
        assert rule.name == "critical_cost"
        assert rule.threshold == 50.0
        assert rule.window_seconds == 300
        assert rule.severity == AlertSeverity.CRITICAL
        assert rule.actions == [AlertAction.LOG_ERROR, AlertAction.HALT_WORKFLOW]
        assert rule.enabled is False
        assert rule.metadata["description"] == "Critical threshold"


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        """Test alert instance creation."""
        alert = Alert(
            rule_name="test_rule",
            severity=AlertSeverity.WARNING,
            message="Test alert",
            metric_value=15.0,
            threshold=10.0,
            context={"workflow_id": "wf-123"},
        )
        assert alert.rule_name == "test_rule"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.message == "Test alert"
        assert alert.metric_value == 15.0
        assert alert.threshold == 10.0
        assert alert.context["workflow_id"] == "wf-123"
        assert isinstance(alert.timestamp, datetime)

    def test_alert_timestamp_default(self):
        """Test alert timestamp is automatically set."""
        before = datetime.now(timezone.utc)
        alert = Alert(
            rule_name="test",
            severity=AlertSeverity.INFO,
            message="Test",
            metric_value=5.0,
            threshold=1.0,
        )
        after = datetime.now(timezone.utc)
        assert before <= alert.timestamp <= after


class TestAlertManager:
    """Tests for AlertManager."""

    @pytest.fixture
    def manager(self):
        """Create alert manager with default rules disabled."""
        mgr = AlertManager()
        # Disable default rules for clean tests
        for rule_name in list(mgr.rules.keys()):
            mgr.disable_rule(rule_name)
        mgr.clear_history()
        return mgr

    def test_initialization(self, manager):
        """Test alert manager initialization."""
        # Re-enable to check defaults were added
        full_manager = AlertManager()
        assert len(full_manager.rules) > 0
        assert "high_cost_per_workflow" in full_manager.rules
        assert "high_error_rate" in full_manager.rules
        assert "extreme_latency_p99" in full_manager.rules
        assert "critical_cost_budget" in full_manager.rules

    def test_add_rule(self, manager):
        """Test adding alert rules."""
        rule = AlertRule(name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0)
        manager.add_rule(rule)
        assert "test_rule" in manager.rules
        assert manager.rules["test_rule"].threshold == 10.0

    def test_remove_rule(self, manager):
        """Test removing alert rules."""
        rule = AlertRule(name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0)
        manager.add_rule(rule)
        assert "test_rule" in manager.rules

        manager.remove_rule("test_rule")
        assert "test_rule" not in manager.rules

    def test_enable_disable_rule(self, manager):
        """Test enabling and disabling rules."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=False
        )
        manager.add_rule(rule)
        assert manager.rules["test_rule"].enabled is False

        manager.enable_rule("test_rule")
        assert manager.rules["test_rule"].enabled is True

        manager.disable_rule("test_rule")
        assert manager.rules["test_rule"].enabled is False

    def test_check_metric_triggers_alert(self, manager):
        """Test metric check triggers alert when threshold exceeded."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        alerts = manager.check_metric("cost_usd", 15.0, context={"workflow_id": "wf-123"})

        assert len(alerts) == 1
        assert alerts[0].rule_name == "test_rule"
        assert alerts[0].metric_value == 15.0
        assert alerts[0].threshold == 10.0
        assert alerts[0].context["workflow_id"] == "wf-123"

    def test_check_metric_no_alert_below_threshold(self, manager):
        """Test metric check does not trigger when below threshold."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        alerts = manager.check_metric("cost_usd", 5.0)

        assert len(alerts) == 0

    def test_check_metric_disabled_rule(self, manager):
        """Test disabled rules do not trigger alerts."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=False
        )
        manager.add_rule(rule)

        alerts = manager.check_metric("cost_usd", 15.0)

        assert len(alerts) == 0

    def test_check_metric_unknown_type(self, manager):
        """Test unknown metric types are ignored."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        alerts = manager.check_metric("unknown_metric", 15.0)

        assert len(alerts) == 0

    def test_alert_history_tracking(self, manager):
        """Test alerts are stored in history."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        manager.check_metric("cost_usd", 15.0)
        # Clear cooldown so the same rule can fire again immediately
        manager._last_alert_times.clear()
        manager.check_metric("cost_usd", 20.0)

        assert len(manager.alert_history) == 2
        assert manager.alert_history[0].metric_value == 15.0
        assert manager.alert_history[1].metric_value == 20.0

    @patch("temper_ai.observability.alerting.logger")
    def test_execute_log_warning_action(self, mock_logger, manager):
        """Test LOG_WARNING action execution."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.LOG_WARNING],
            enabled=True,
        )
        manager.add_rule(rule)

        manager.check_metric("cost_usd", 15.0)

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "ALERT" in call_args[0][0]
        assert "test_rule" in call_args[1]["extra"]["rule_name"]

    @patch("temper_ai.observability.alerting.logger")
    def test_execute_log_error_action(self, mock_logger, manager):
        """Test LOG_ERROR action execution."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.ERROR_RATE,
            threshold=0.1,
            actions=[AlertAction.LOG_ERROR],
            severity=AlertSeverity.ERROR,
            enabled=True,
        )
        manager.add_rule(rule)

        manager.check_metric("error_rate", 0.15)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "ALERT" in call_args[0][0]

    @patch("temper_ai.observability.alerting.logger")
    def test_execute_halt_workflow_action(self, mock_logger, manager):
        """Test HALT_WORKFLOW action execution."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=50.0,
            actions=[AlertAction.HALT_WORKFLOW],
            severity=AlertSeverity.CRITICAL,
            enabled=True,
        )
        manager.add_rule(rule)

        manager.check_metric("cost_usd", 60.0, context={"workflow_id": "wf-123"})

        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args
        assert "HALTING WORKFLOW" in call_args[0][0]
        assert "wf-123" in call_args[0][0]

    @patch("temper_ai.observability.alerting.logger")
    def test_halt_workflow_without_workflow_id(self, mock_logger, manager):
        """Test HALT_WORKFLOW logs warning when no workflow_id in context."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=50.0,
            actions=[AlertAction.HALT_WORKFLOW],
            enabled=True,
        )
        manager.add_rule(rule)

        manager.check_metric("cost_usd", 60.0)

        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args
        assert "Cannot halt workflow" in call_args[0][0]

    def test_webhook_action_without_handler(self, manager):
        """Test webhook action without registered handler."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.WEBHOOK],
            enabled=True,
            metadata={"webhook_url": "https://example.com/webhook"},
        )
        manager.add_rule(rule)

        with patch("temper_ai.observability.alerting.logger") as mock_logger:
            manager.check_metric("cost_usd", 15.0)
            mock_logger.info.assert_called()
            assert mock_logger.info.call_count > 0

    def test_webhook_action_with_handler(self, manager):
        """Test webhook action with registered handler."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.WEBHOOK],
            enabled=True,
            metadata={"webhook_url": "https://example.com/webhook"},
        )
        manager.add_rule(rule)

        mock_handler = Mock(spec=callable)
        manager.register_webhook_handler("test_rule", mock_handler)

        manager.check_metric("cost_usd", 15.0)

        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0]
        assert isinstance(call_args[0], Alert)
        assert isinstance(call_args[1], AlertRule)

    def test_email_action_with_handler(self, manager):
        """Test email action with registered handler."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.EMAIL],
            enabled=True,
            metadata={"email_to": "alerts@example.com"},
        )
        manager.add_rule(rule)

        mock_handler = Mock(spec=callable)
        manager.register_email_handler("test_rule", mock_handler)

        manager.check_metric("cost_usd", 15.0)

        mock_handler.assert_called_once()
        assert mock_handler.call_count == 1

    def test_get_recent_alerts(self, manager):
        """Test retrieving recent alerts."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        # Trigger multiple alerts (clear cooldown between calls)
        manager.check_metric("cost_usd", 15.0)
        manager._last_alert_times.clear()
        manager.check_metric("cost_usd", 20.0)

        recent = manager.get_recent_alerts(hours=24)
        assert len(recent) == 2

    def test_get_recent_alerts_with_severity_filter(self, manager):
        """Test retrieving recent alerts filtered by severity."""
        rule1 = AlertRule(
            name="warning_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
            enabled=True,
        )
        rule2 = AlertRule(
            name="error_rule",
            metric_type=MetricType.ERROR_RATE,
            threshold=0.1,
            severity=AlertSeverity.ERROR,
            enabled=True,
        )
        manager.add_rule(rule1)
        manager.add_rule(rule2)

        manager.check_metric("cost_usd", 15.0)
        manager.check_metric("error_rate", 0.15)

        warnings = manager.get_recent_alerts(hours=24, severity=AlertSeverity.WARNING)
        errors = manager.get_recent_alerts(hours=24, severity=AlertSeverity.ERROR)

        assert len(warnings) == 1
        assert len(errors) == 1

    def test_clear_history(self, manager):
        """Test clearing alert history."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        manager.check_metric("cost_usd", 15.0)
        assert len(manager.alert_history) == 1

        manager.clear_history()
        assert len(manager.alert_history) == 0

    def test_multiple_rules_same_metric(self, manager):
        """Test multiple rules for same metric type."""
        rule1 = AlertRule(
            name="warning_threshold",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
            enabled=True,
        )
        rule2 = AlertRule(
            name="critical_threshold",
            metric_type=MetricType.COST_USD,
            threshold=50.0,
            severity=AlertSeverity.CRITICAL,
            enabled=True,
        )
        manager.add_rule(rule1)
        manager.add_rule(rule2)

        # Trigger both rules
        alerts = manager.check_metric("cost_usd", 60.0)

        assert len(alerts) == 2
        assert {a.rule_name for a in alerts} == {"warning_threshold", "critical_threshold"}

    @patch("temper_ai.observability.alerting.logger")
    def test_action_execution_error_handling(self, mock_logger, manager):
        """Test error handling in action execution."""
        rule = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.WEBHOOK],
            enabled=True,
            metadata={"webhook_url": "https://example.com/webhook"},
        )
        manager.add_rule(rule)

        # Register handler that raises exception
        def failing_handler(alert, rule):
            raise Exception("Handler failed")

        manager.register_webhook_handler("test_rule", failing_handler)

        # Should not crash, just log error
        manager.check_metric("cost_usd", 15.0)

        mock_logger.error.assert_called()
        error_call = [
            call for call in mock_logger.error.call_args_list if "Failed to execute" in str(call)
        ]
        assert len(error_call) > 0

    def test_empty_context_handling(self, manager):
        """Test metric check with no context."""
        rule = AlertRule(
            name="test_rule", metric_type=MetricType.COST_USD, threshold=10.0, enabled=True
        )
        manager.add_rule(rule)

        alerts = manager.check_metric("cost_usd", 15.0)

        assert len(alerts) == 1
        assert alerts[0].context == {}
