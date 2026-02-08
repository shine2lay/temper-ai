"""Real-time alerting for observability metrics.

Provides configurable alert rules that monitor metrics and trigger actions
when thresholds are breached. Supports log warnings, webhooks, email, and
workflow halting.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.constants.durations import HOURS_PER_DAY, SECONDS_PER_5_MINUTES
from src.observability.constants import DEFAULT_ERROR_RATE_ALERT_THRESHOLD

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertAction(str, Enum):
    """Actions to take when alert is triggered."""
    LOG_WARNING = "log_warning"
    LOG_ERROR = "log_error"
    WEBHOOK = "webhook"
    EMAIL = "email"
    HALT_WORKFLOW = "halt_workflow"


class MetricType(str, Enum):
    """Types of metrics to monitor."""
    COST_USD = "cost_usd"
    ERROR_RATE = "error_rate"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    DURATION = "duration"
    TOKEN_COUNT = "token_count"  # noqa: S105 — not a password


@dataclass
class AlertRule:
    """Configuration for an alert rule.

    Attributes:
        name: Human-readable name for the rule
        metric_type: Type of metric to monitor
        threshold: Threshold value to trigger alert
        window_seconds: Time window to evaluate (0 = single event)
        severity: Severity level of the alert
        actions: List of actions to take when triggered
        enabled: Whether the rule is active
        metadata: Additional metadata for the rule
    """
    name: str
    metric_type: MetricType
    threshold: float
    window_seconds: float = 0
    severity: AlertSeverity = AlertSeverity.WARNING
    actions: List[AlertAction] = field(default_factory=lambda: [AlertAction.LOG_WARNING])
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """Triggered alert instance.

    Attributes:
        rule_name: Name of the rule that triggered
        severity: Severity level
        message: Alert message
        metric_value: Current metric value
        threshold: Threshold that was exceeded
        timestamp: When alert was triggered
        context: Additional context (workflow_id, agent_id, etc.)
    """
    rule_name: str
    severity: AlertSeverity
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)


class AlertManager:
    """Manages alert rules and triggers alerts when thresholds are breached.

    Example:
        >>> manager = AlertManager()
        >>> manager.add_rule(AlertRule(
        ...     name="high_cost",
        ...     metric_type=MetricType.COST_USD,
        ...     threshold=10.0,
        ...     actions=[AlertAction.LOG_WARNING, AlertAction.WEBHOOK]
        ... ))
        >>> manager.check_metric("cost_usd", 15.0, context={"workflow_id": "wf-123"})
    """

    def __init__(self):
        """Initialize alert manager with default rules."""
        self.rules: Dict[str, AlertRule] = {}
        self.alert_history: List[Alert] = []
        self.webhook_handlers: Dict[str, Callable] = {}
        self.email_handlers: Dict[str, Callable] = {}

        # Add built-in default rules
        self._add_default_rules()

    def _add_default_rules(self) -> None:
        """Add default alert rules for common issues."""
        # High cost alert
        self.add_rule(AlertRule(
            name="high_cost_per_workflow",
            metric_type=MetricType.COST_USD,
            threshold=5.0,  # $5 per workflow
            severity=AlertSeverity.WARNING,
            actions=[AlertAction.LOG_WARNING],
            metadata={"description": "Workflow cost exceeds $5"}
        ))

        # High error rate
        self.add_rule(AlertRule(
            name="high_error_rate",
            metric_type=MetricType.ERROR_RATE,
            threshold=DEFAULT_ERROR_RATE_ALERT_THRESHOLD,  # 10% error rate
            window_seconds=SECONDS_PER_5_MINUTES,  # 5 minutes
            severity=AlertSeverity.ERROR,
            actions=[AlertAction.LOG_ERROR],
            metadata={"description": "Error rate exceeds 10% in 5 minute window"}
        ))

        # Extreme latency
        self.add_rule(AlertRule(
            name="extreme_latency_p99",
            metric_type=MetricType.LATENCY_P99,
            threshold=30000,  # 30 seconds
            severity=AlertSeverity.WARNING,
            actions=[AlertAction.LOG_WARNING],
            metadata={"description": "P99 latency exceeds 30 seconds"}
        ))

        # Critical cost threshold
        self.add_rule(AlertRule(
            name="critical_cost_budget",
            metric_type=MetricType.COST_USD,
            threshold=50.0,  # $50 per workflow (critical)
            severity=AlertSeverity.CRITICAL,
            actions=[AlertAction.LOG_ERROR, AlertAction.HALT_WORKFLOW],
            enabled=False,  # Disabled by default (destructive action)
            metadata={"description": "Critical cost budget exceeded - halting workflow"}
        ))

    def add_rule(self, rule: AlertRule) -> None:
        """Add or update an alert rule.

        Args:
            rule: AlertRule to add
        """
        self.rules[rule.name] = rule
        logger.info(f"Added alert rule: {rule.name} ({rule.metric_type.value} > {rule.threshold})")

    def remove_rule(self, rule_name: str) -> None:
        """Remove an alert rule.

        Args:
            rule_name: Name of rule to remove
        """
        if rule_name in self.rules:
            del self.rules[rule_name]
            logger.info(f"Removed alert rule: {rule_name}")

    def enable_rule(self, rule_name: str) -> None:
        """Enable an alert rule.

        Args:
            rule_name: Name of rule to enable
        """
        if rule_name in self.rules:
            self.rules[rule_name].enabled = True
            logger.info(f"Enabled alert rule: {rule_name}")

    def disable_rule(self, rule_name: str) -> None:
        """Disable an alert rule.

        Args:
            rule_name: Name of rule to disable
        """
        if rule_name in self.rules:
            self.rules[rule_name].enabled = False
            logger.info(f"Disabled alert rule: {rule_name}")

    def check_metric(
        self,
        metric_type: str,
        value: float,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Alert]:
        """Check if metric value triggers any alerts.

        Args:
            metric_type: Type of metric (e.g., "cost_usd", "error_rate")
            value: Current metric value
            context: Additional context (workflow_id, agent_id, etc.)

        Returns:
            List of triggered alerts
        """
        triggered_alerts = []
        context = context or {}

        # Normalize metric_type to enum
        try:
            metric_enum = MetricType(metric_type)
        except ValueError:
            # Unknown metric type, skip
            return triggered_alerts

        # Check all rules for this metric type
        for rule in self.rules.values():
            if not rule.enabled:
                continue

            if rule.metric_type != metric_enum:
                continue

            # Check threshold
            if value > rule.threshold:
                alert = Alert(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"{rule.name}: {metric_type} = {value:.2f} exceeds threshold {rule.threshold:.2f}",
                    metric_value=value,
                    threshold=rule.threshold,
                    context=context
                )

                triggered_alerts.append(alert)
                self.alert_history.append(alert)

                # Execute alert actions
                self._execute_actions(alert, rule)

        return triggered_alerts

    def _execute_actions(self, alert: Alert, rule: AlertRule) -> None:
        """Execute actions for triggered alert.

        Args:
            alert: Triggered alert
            rule: Rule that triggered the alert
        """
        for action in rule.actions:
            try:
                if action == AlertAction.LOG_WARNING:
                    logger.warning(
                        f"ALERT [{alert.severity.value.upper()}]: {alert.message}",
                        extra={
                            "rule_name": rule.name,
                            "metric_value": alert.metric_value,
                            "threshold": alert.threshold,
                            "context": alert.context
                        }
                    )

                elif action == AlertAction.LOG_ERROR:
                    logger.error(
                        f"ALERT [{alert.severity.value.upper()}]: {alert.message}",
                        extra={
                            "rule_name": rule.name,
                            "metric_value": alert.metric_value,
                            "threshold": alert.threshold,
                            "context": alert.context
                        }
                    )

                elif action == AlertAction.WEBHOOK:
                    self._trigger_webhook(alert, rule)

                elif action == AlertAction.EMAIL:
                    self._trigger_email(alert, rule)

                elif action == AlertAction.HALT_WORKFLOW:
                    self._halt_workflow(alert, rule)

            except Exception as e:
                logger.error(
                    f"Failed to execute alert action {action.value} for {rule.name}: {e}",
                    exc_info=True
                )

    def _trigger_webhook(self, alert: Alert, rule: AlertRule) -> None:
        """Trigger webhook for alert.

        Args:
            alert: Triggered alert
            rule: Rule configuration
        """
        # Check if webhook handler is registered
        webhook_url = rule.metadata.get("webhook_url")
        if not webhook_url:
            logger.warning(f"No webhook URL configured for rule {rule.name}")
            return

        # Check if custom handler exists
        handler = self.webhook_handlers.get(rule.name)
        if handler:
            handler(alert, rule)
        else:
            logger.info(f"Webhook trigger (no handler): {alert.message} -> {webhook_url}")

    def _trigger_email(self, alert: Alert, rule: AlertRule) -> None:
        """Trigger email for alert.

        Args:
            alert: Triggered alert
            rule: Rule configuration
        """
        # Check if email handler is registered
        email_to = rule.metadata.get("email_to")
        if not email_to:
            logger.warning(f"No email recipient configured for rule {rule.name}")
            return

        # Check if custom handler exists
        handler = self.email_handlers.get(rule.name)
        if handler:
            handler(alert, rule)
        else:
            logger.info(f"Email trigger (no handler): {alert.message} -> {email_to}")

    def _halt_workflow(self, alert: Alert, rule: AlertRule) -> None:
        """Halt workflow execution.

        Args:
            alert: Triggered alert
            rule: Rule configuration
        """
        workflow_id = alert.context.get("workflow_id")
        if workflow_id:
            logger.critical(
                f"HALTING WORKFLOW {workflow_id}: {alert.message}",
                extra={
                    "workflow_id": workflow_id,
                    "rule_name": rule.name,
                    "metric_value": alert.metric_value,
                    "threshold": alert.threshold
                }
            )
            # Note: Actual workflow halting would require integration with execution engine
            # For now, this just logs the critical alert
        else:
            logger.warning(f"Cannot halt workflow - no workflow_id in context for {rule.name}")

    def register_webhook_handler(self, rule_name: str, handler: Callable) -> None:
        """Register custom webhook handler for a rule.

        Args:
            rule_name: Name of rule
            handler: Callable that takes (alert, rule) and sends webhook
        """
        self.webhook_handlers[rule_name] = handler
        logger.info(f"Registered webhook handler for rule: {rule_name}")

    def register_email_handler(self, rule_name: str, handler: Callable) -> None:
        """Register custom email handler for a rule.

        Args:
            rule_name: Name of rule
            handler: Callable that takes (alert, rule) and sends email
        """
        self.email_handlers[rule_name] = handler
        logger.info(f"Registered email handler for rule: {rule_name}")

    def get_recent_alerts(
        self,
        hours: int = HOURS_PER_DAY,
        severity: Optional[AlertSeverity] = None
    ) -> List[Alert]:
        """Get recent alerts within time window.

        Args:
            hours: Number of hours to look back
            severity: Filter by severity (optional)

        Returns:
            List of alerts
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        alerts = [
            alert for alert in self.alert_history
            if alert.timestamp >= cutoff
        ]

        if severity:
            alerts = [alert for alert in alerts if alert.severity == severity]

        return alerts

    def clear_history(self) -> None:
        """Clear alert history."""
        self.alert_history.clear()
        logger.info("Cleared alert history")
