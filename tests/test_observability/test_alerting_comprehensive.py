"""Comprehensive additional tests for real-time alerting system."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call, patch

import pytest

from src.observability.alerting import (
    Alert,
    AlertAction,
    AlertManager,
    AlertRule,
    AlertSeverity,
    MetricType,
)


class TestAlertRuleValidation:
    """Tests for AlertRule validation and edge cases."""

    def test_alert_rule_with_all_metric_types(self):
        """Test creating rules for all metric types."""
        for metric_type in MetricType:
            rule = AlertRule(
                name=f"rule_{metric_type.value}",
                metric_type=metric_type,
                threshold=100.0
            )
            assert rule.metric_type == metric_type

    def test_alert_rule_with_all_severities(self):
        """Test creating rules with all severity levels."""
        for severity in AlertSeverity:
            rule = AlertRule(
                name=f"rule_{severity.value}",
                metric_type=MetricType.COST_USD,
                threshold=10.0,
                severity=severity
            )
            assert rule.severity == severity

    def test_alert_rule_with_all_actions(self):
        """Test creating rules with all action types."""
        for action in AlertAction:
            rule = AlertRule(
                name=f"rule_{action.value}",
                metric_type=MetricType.COST_USD,
                threshold=10.0,
                actions=[action]
            )
            assert action in rule.actions

    def test_alert_rule_with_multiple_actions(self):
        """Test rule with multiple actions."""
        rule = AlertRule(
            name="multi_action",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[
                AlertAction.LOG_WARNING,
                AlertAction.LOG_ERROR,
                AlertAction.WEBHOOK,
                AlertAction.EMAIL
            ]
        )
        assert len(rule.actions) == 4

    def test_alert_rule_with_window_seconds(self):
        """Test rule with time window."""
        rule = AlertRule(
            name="windowed_rule",
            metric_type=MetricType.ERROR_RATE,
            threshold=0.1,
            window_seconds=300  # 5 minutes
        )
        assert rule.window_seconds == 300

    def test_alert_rule_metadata_storage(self):
        """Test metadata can store arbitrary data."""
        metadata = {
            "description": "Test rule",
            "owner": "team-sre",
            "priority": 1,
            "custom_field": {"nested": "value"}
        }
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            metadata=metadata
        )
        assert rule.metadata == metadata
        assert rule.metadata["custom_field"]["nested"] == "value"


class TestAlertCreation:
    """Tests for Alert dataclass and creation."""

    def test_alert_with_minimal_fields(self):
        """Test alert with only required fields."""
        alert = Alert(
            rule_name="test_rule",
            severity=AlertSeverity.INFO,
            message="Test alert",
            metric_value=10.0,
            threshold=5.0
        )
        assert alert.rule_name == "test_rule"
        assert alert.context == {}

    def test_alert_with_complex_context(self):
        """Test alert with complex context data."""
        context = {
            "workflow_id": "wf-123",
            "agent_id": "agent-456",
            "stage": "execution",
            "metadata": {
                "user": "alice",
                "environment": "production"
            }
        }
        alert = Alert(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="Test",
            metric_value=10.0,
            threshold=5.0,
            context=context
        )
        assert alert.context["workflow_id"] == "wf-123"
        assert alert.context["metadata"]["user"] == "alice"

    def test_alert_timestamp_immutability(self):
        """Test alert timestamp is set at creation."""
        alert1 = Alert(
            rule_name="test",
            severity=AlertSeverity.INFO,
            message="Test",
            metric_value=5.0,
            threshold=1.0
        )
        timestamp1 = alert1.timestamp

        # Small delay
        import time
        time.sleep(0.1)

        # Create another alert
        alert2 = Alert(
            rule_name="test",
            severity=AlertSeverity.INFO,
            message="Test",
            metric_value=5.0,
            threshold=1.0
        )

        # Timestamps should be different
        assert alert2.timestamp > timestamp1


class TestAlertManagerAdvanced:
    """Advanced tests for AlertManager."""

    @pytest.fixture
    def clean_manager(self):
        """Create alert manager with all rules disabled."""
        mgr = AlertManager()
        for rule_name in list(mgr.rules.keys()):
            mgr.disable_rule(rule_name)
        mgr.clear_history()
        return mgr

    def test_default_rules_are_created(self):
        """Test default rules are present on initialization."""
        manager = AlertManager()

        # Should have default rules
        assert "high_cost_per_workflow" in manager.rules
        assert "high_error_rate" in manager.rules
        assert "extreme_latency_p99" in manager.rules
        assert "critical_cost_budget" in manager.rules

        # Critical rule should be disabled by default
        assert manager.rules["critical_cost_budget"].enabled is False

    def test_add_rule_overwrites_existing(self, clean_manager):
        """Test adding rule with existing name overwrites."""
        rule1 = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0
        )
        clean_manager.add_rule(rule1)

        rule2 = AlertRule(
            name="test_rule",
            metric_type=MetricType.COST_USD,
            threshold=20.0
        )
        clean_manager.add_rule(rule2)

        # Should have only one rule with updated threshold
        assert len([r for r in clean_manager.rules.values() if r.name == "test_rule"]) == 1
        assert clean_manager.rules["test_rule"].threshold == 20.0

    def test_remove_nonexistent_rule(self, clean_manager):
        """Test removing nonexistent rule does not raise error."""
        # Should not raise
        initial_rules = len(clean_manager.rules)
        clean_manager.remove_rule("nonexistent")
        # State should be unchanged
        assert len(clean_manager.rules) == initial_rules
        assert "nonexistent" not in clean_manager.rules

    def test_enable_nonexistent_rule(self, clean_manager):
        """Test enabling nonexistent rule does not raise error."""
        # Should not raise
        initial_rules = len(clean_manager.rules)
        clean_manager.enable_rule("nonexistent")
        # State should be unchanged
        assert len(clean_manager.rules) == initial_rules
        assert "nonexistent" not in clean_manager.rules

    def test_disable_nonexistent_rule(self, clean_manager):
        """Test disabling nonexistent rule does not raise error."""
        # Should not raise
        initial_rules = len(clean_manager.rules)
        clean_manager.disable_rule("nonexistent")
        # State should be unchanged
        assert len(clean_manager.rules) == initial_rules
        assert "nonexistent" not in clean_manager.rules

    def test_check_metric_with_exact_threshold(self, clean_manager):
        """Test metric exactly at threshold does not trigger."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Exactly at threshold - should NOT trigger
        alerts = clean_manager.check_metric("cost_usd", 10.0)
        assert len(alerts) == 0

        # Just above threshold - should trigger
        alerts = clean_manager.check_metric("cost_usd", 10.001)
        assert len(alerts) == 1

    def test_check_metric_wrong_type_for_rule(self, clean_manager):
        """Test metric of different type does not trigger rule."""
        rule = AlertRule(
            name="cost_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Check different metric type
        alerts = clean_manager.check_metric("error_rate", 0.5)
        assert len(alerts) == 0

    def test_check_metric_multiple_rules_triggered(self, clean_manager):
        """Test multiple rules can trigger for same metric."""
        rule1 = AlertRule(
            name="warning_rule",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
            enabled=True
        )
        rule2 = AlertRule(
            name="critical_rule",
            metric_type=MetricType.COST_USD,
            threshold=50.0,
            severity=AlertSeverity.CRITICAL,
            enabled=True
        )
        clean_manager.add_rule(rule1)
        clean_manager.add_rule(rule2)

        # Trigger both rules
        alerts = clean_manager.check_metric("cost_usd", 60.0)

        assert len(alerts) == 2
        rule_names = {a.rule_name for a in alerts}
        assert "warning_rule" in rule_names
        assert "critical_rule" in rule_names

    def test_alert_history_ordering(self, clean_manager):
        """Test alerts are stored in chronological order."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Trigger multiple alerts
        clean_manager.check_metric("cost_usd", 15.0)
        import time
        time.sleep(0.1)
        clean_manager.check_metric("cost_usd", 20.0)
        time.sleep(0.1)
        clean_manager.check_metric("cost_usd", 25.0)

        # Check ordering
        history = clean_manager.alert_history
        assert len(history) == 3
        assert history[0].metric_value == 15.0
        assert history[1].metric_value == 20.0
        assert history[2].metric_value == 25.0
        assert history[0].timestamp <= history[1].timestamp <= history[2].timestamp

    @patch("src.observability.alerting.logger")
    def test_webhook_action_with_no_url(self, mock_logger, clean_manager):
        """Test webhook action logs warning when URL not configured."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.WEBHOOK],
            enabled=True
            # No webhook_url in metadata
        )
        clean_manager.add_rule(rule)

        clean_manager.check_metric("cost_usd", 15.0)

        # Should log warning
        mock_logger.warning.assert_called()
        assert "No webhook URL" in str(mock_logger.warning.call_args)

    @patch("src.observability.alerting.logger")
    def test_email_action_with_no_recipient(self, mock_logger, clean_manager):
        """Test email action logs warning when recipient not configured."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.EMAIL],
            enabled=True
            # No email_to in metadata
        )
        clean_manager.add_rule(rule)

        clean_manager.check_metric("cost_usd", 15.0)

        # Should log warning
        mock_logger.warning.assert_called()
        assert "No email recipient" in str(mock_logger.warning.call_args)

    def test_webhook_handler_receives_correct_arguments(self, clean_manager):
        """Test webhook handler is called with alert and rule."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.WEBHOOK],
            enabled=True,
            metadata={"webhook_url": "https://example.com/webhook"}
        )
        clean_manager.add_rule(rule)

        mock_handler = Mock()
        clean_manager.register_webhook_handler("test", mock_handler)

        clean_manager.check_metric("cost_usd", 15.0)

        # Verify handler called with correct args
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0]
        assert isinstance(call_args[0], Alert)
        assert isinstance(call_args[1], AlertRule)
        assert call_args[0].metric_value == 15.0
        assert call_args[1].name == "test"

    def test_email_handler_receives_correct_arguments(self, clean_manager):
        """Test email handler is called with alert and rule."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[AlertAction.EMAIL],
            enabled=True,
            metadata={"email_to": "alerts@example.com"}
        )
        clean_manager.add_rule(rule)

        mock_handler = Mock()
        clean_manager.register_email_handler("test", mock_handler)

        clean_manager.check_metric("cost_usd", 15.0)

        # Verify handler called
        mock_handler.assert_called_once()
        assert isinstance(mock_handler.call_args[0][0], Alert)
        assert isinstance(mock_handler.call_args[0][1], AlertRule)

    def test_get_recent_alerts_empty(self, clean_manager):
        """Test get_recent_alerts with no alerts."""
        alerts = clean_manager.get_recent_alerts(hours=24)
        assert len(alerts) == 0

    def test_get_recent_alerts_time_filtering(self, clean_manager):
        """Test get_recent_alerts filters by time window."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Create alert with old timestamp
        old_alert = Alert(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="Old alert",
            metric_value=15.0,
            threshold=10.0,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=48)
        )
        clean_manager.alert_history.append(old_alert)

        # Create recent alert
        clean_manager.check_metric("cost_usd", 20.0)

        # Get last 24 hours
        recent = clean_manager.get_recent_alerts(hours=24)
        assert len(recent) == 1
        assert recent[0].metric_value == 20.0

        # Get last 72 hours
        recent = clean_manager.get_recent_alerts(hours=72)
        assert len(recent) == 2

    def test_get_recent_alerts_severity_filtering(self, clean_manager):
        """Test get_recent_alerts filters by severity."""
        rule1 = AlertRule(
            name="warning",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            severity=AlertSeverity.WARNING,
            enabled=True
        )
        rule2 = AlertRule(
            name="error",
            metric_type=MetricType.ERROR_RATE,
            threshold=0.1,
            severity=AlertSeverity.ERROR,
            enabled=True
        )
        rule3 = AlertRule(
            name="critical",
            metric_type=MetricType.LATENCY_P99,
            threshold=1000.0,
            severity=AlertSeverity.CRITICAL,
            enabled=True
        )
        clean_manager.add_rule(rule1)
        clean_manager.add_rule(rule2)
        clean_manager.add_rule(rule3)

        # Trigger all rules
        clean_manager.check_metric("cost_usd", 15.0)
        clean_manager.check_metric("error_rate", 0.2)
        clean_manager.check_metric("latency_p99", 2000.0)

        # Filter by WARNING
        warnings = clean_manager.get_recent_alerts(hours=24, severity=AlertSeverity.WARNING)
        assert len(warnings) == 1
        assert all(a.severity == AlertSeverity.WARNING for a in warnings)

        # Filter by ERROR
        errors = clean_manager.get_recent_alerts(hours=24, severity=AlertSeverity.ERROR)
        assert len(errors) == 1
        assert all(a.severity == AlertSeverity.ERROR for a in errors)

        # Filter by CRITICAL
        criticals = clean_manager.get_recent_alerts(hours=24, severity=AlertSeverity.CRITICAL)
        assert len(criticals) == 1
        assert all(a.severity == AlertSeverity.CRITICAL for a in criticals)

    def test_clear_history_removes_all(self, clean_manager):
        """Test clear_history removes all alerts."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Generate alerts
        clean_manager.check_metric("cost_usd", 15.0)
        clean_manager.check_metric("cost_usd", 20.0)

        assert len(clean_manager.alert_history) == 2

        clean_manager.clear_history()

        assert len(clean_manager.alert_history) == 0

    @patch("src.observability.alerting.logger")
    def test_action_execution_continues_after_error(self, mock_logger, clean_manager):
        """Test remaining actions execute even if one fails."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            actions=[
                AlertAction.LOG_WARNING,
                AlertAction.WEBHOOK,  # Will fail
                AlertAction.LOG_ERROR
            ],
            enabled=True,
            metadata={"webhook_url": "https://example.com/webhook"}
        )
        clean_manager.add_rule(rule)

        # Register failing webhook handler
        def failing_handler(alert, rule):
            raise Exception("Webhook failed")

        clean_manager.register_webhook_handler("test", failing_handler)

        # Trigger alert
        clean_manager.check_metric("cost_usd", 15.0)

        # Both LOG_WARNING and LOG_ERROR should have been called
        assert mock_logger.warning.called
        assert mock_logger.error.called

    def test_metric_enum_validation(self, clean_manager):
        """Test only valid metric types trigger rules."""
        rule = AlertRule(
            name="test",
            metric_type=MetricType.COST_USD,
            threshold=10.0,
            enabled=True
        )
        clean_manager.add_rule(rule)

        # Valid metric type
        alerts = clean_manager.check_metric("cost_usd", 15.0)
        assert len(alerts) == 1

        # Invalid metric type string (not in enum)
        alerts = clean_manager.check_metric("invalid_metric_type", 15.0)
        assert len(alerts) == 0


class TestMetricTypes:
    """Tests for MetricType enum."""

    def test_all_metric_types_are_strings(self):
        """Test all MetricType values are strings."""
        for metric_type in MetricType:
            assert isinstance(metric_type.value, str)

    def test_metric_type_values(self):
        """Test MetricType enum has expected values."""
        assert MetricType.COST_USD.value == "cost_usd"
        assert MetricType.ERROR_RATE.value == "error_rate"
        assert MetricType.LATENCY_P95.value == "latency_p95"
        assert MetricType.LATENCY_P99.value == "latency_p99"
        assert MetricType.DURATION.value == "duration"
        assert MetricType.TOKEN_COUNT.value == "token_count"


class TestAlertSeverities:
    """Tests for AlertSeverity enum."""

    def test_all_severities_are_strings(self):
        """Test all AlertSeverity values are strings."""
        for severity in AlertSeverity:
            assert isinstance(severity.value, str)

    def test_severity_values(self):
        """Test AlertSeverity enum has expected values."""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.CRITICAL.value == "critical"


class TestAlertActions:
    """Tests for AlertAction enum."""

    def test_all_actions_are_strings(self):
        """Test all AlertAction values are strings."""
        for action in AlertAction:
            assert isinstance(action.value, str)

    def test_action_values(self):
        """Test AlertAction enum has expected values."""
        assert AlertAction.LOG_WARNING.value == "log_warning"
        assert AlertAction.LOG_ERROR.value == "log_error"
        assert AlertAction.WEBHOOK.value == "webhook"
        assert AlertAction.EMAIL.value == "email"
        assert AlertAction.HALT_WORKFLOW.value == "halt_workflow"
