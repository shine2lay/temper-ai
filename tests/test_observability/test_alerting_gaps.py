"""Tests for alerting gaps: cooldown, persistence, history cap, halt callback.

Covers features added in the observability hardening milestone:
- Alert cooldown (duplicate suppression within DEFAULT_ALERT_COOLDOWN_SECONDS)
- Alert history cap at MAX_ALERT_HISTORY
- DB persistence of alerts via _persist_alert / get_persisted_alerts
- Halt callback registration and invocation
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

from temper_ai.observability.alerting import (
    Alert,
    AlertAction,
    AlertManager,
    AlertRule,
    AlertSeverity,
    MetricType,
)
from temper_ai.observability.constants import (
    DEFAULT_ALERT_COOLDOWN_SECONDS,
    MAX_ALERT_HISTORY,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager_with_rule(
    rule_name: str = "test_rule",
    metric_type: MetricType = MetricType.COST_USD,
    threshold: float = 10.0,
    actions: list | None = None,
    severity: AlertSeverity = AlertSeverity.WARNING,
) -> AlertManager:
    """Return an AlertManager with defaults disabled and one custom rule."""
    mgr = AlertManager()
    for name in list(mgr.rules.keys()):
        mgr.disable_rule(name)
    mgr.clear_history()
    mgr.add_rule(
        AlertRule(
            name=rule_name,
            metric_type=metric_type,
            threshold=threshold,
            actions=actions or [AlertAction.LOG_WARNING],
            severity=severity,
            enabled=True,
        )
    )
    return mgr


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


class TestAlertCooldown:
    """Tests for alert cooldown enforcement."""

    def test_duplicate_alerts_suppressed_within_cooldown(self):
        """Duplicate alerts for the same rule within cooldown are skipped."""
        mgr = _make_manager_with_rule()

        first = mgr.check_metric("cost_usd", 15.0)
        assert len(first) == 1

        # Second call within cooldown window -> suppressed
        second = mgr.check_metric("cost_usd", 20.0)
        assert len(second) == 0
        assert len(mgr.alert_history) == 1

    def test_alert_fires_after_cooldown_expires(self):
        """Alert fires again once cooldown has elapsed."""
        mgr = _make_manager_with_rule()

        mgr.check_metric("cost_usd", 15.0)
        assert len(mgr.alert_history) == 1

        # Manually expire the cooldown
        past = datetime.now(UTC) - timedelta(seconds=DEFAULT_ALERT_COOLDOWN_SECONDS + 1)
        mgr._last_alert_times["test_rule"] = past

        second = mgr.check_metric("cost_usd", 20.0)
        assert len(second) == 1
        assert len(mgr.alert_history) == 2

    def test_independent_cooldowns_per_rule(self):
        """Different rules maintain independent cooldown timers."""
        mgr = _make_manager_with_rule(rule_name="rule_a", threshold=10.0)
        mgr.add_rule(
            AlertRule(
                name="rule_b",
                metric_type=MetricType.COST_USD,
                threshold=5.0,
                enabled=True,
            )
        )

        alerts = mgr.check_metric("cost_usd", 15.0)
        assert len(alerts) == 2

        # Both in cooldown now
        alerts = mgr.check_metric("cost_usd", 15.0)
        assert len(alerts) == 0

        # Expire only rule_a
        past = datetime.now(UTC) - timedelta(seconds=DEFAULT_ALERT_COOLDOWN_SECONDS + 1)
        mgr._last_alert_times["rule_a"] = past

        alerts = mgr.check_metric("cost_usd", 15.0)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "rule_a"


# ---------------------------------------------------------------------------
# History cap tests
# ---------------------------------------------------------------------------


class TestAlertHistoryCap:
    """Tests for MAX_ALERT_HISTORY enforcement."""

    def test_history_capped_at_max(self):
        """Alert history never exceeds MAX_ALERT_HISTORY entries."""
        mgr = _make_manager_with_rule()

        # Pre-fill history to near max
        for i in range(MAX_ALERT_HISTORY):
            mgr.alert_history.append(
                Alert(
                    rule_name="prefill",
                    severity=AlertSeverity.INFO,
                    message=f"prefill-{i}",
                    metric_value=float(i),
                    threshold=0.0,
                )
            )

        # Fire one more (need to bypass cooldown)
        mgr.check_metric("cost_usd", 15.0)

        assert len(mgr.alert_history) <= MAX_ALERT_HISTORY


# ---------------------------------------------------------------------------
# DB persistence tests
# ---------------------------------------------------------------------------


class TestAlertPersistence:
    """Tests for _persist_alert and get_persisted_alerts."""

    @patch("temper_ai.observability.alerting.logger")
    def test_persist_alert_writes_to_db(self, _mock_logger):
        """_persist_alert creates an AlertRecord via get_session."""
        mgr = _make_manager_with_rule()
        alert = Alert(
            rule_name="test_rule",
            severity=AlertSeverity.WARNING,
            message="test msg",
            metric_value=15.0,
            threshold=10.0,
            context={"workflow_id": "wf-1"},
        )

        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = Mock(return_value=mock_session)
        mock_cm.__exit__ = Mock(return_value=False)

        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            mgr._persist_alert(alert)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        record = mock_session.add.call_args[0][0]
        assert record.rule_name == "test_rule"
        assert record.metric_value == 15.0

    def test_persist_alert_best_effort_no_crash(self):
        """_persist_alert swallows exceptions gracefully."""
        mgr = _make_manager_with_rule()
        alert = Alert(
            rule_name="r",
            severity=AlertSeverity.INFO,
            message="m",
            metric_value=1.0,
            threshold=0.5,
        )

        with patch(
            "temper_ai.storage.database.get_session",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise — best-effort persistence
            mgr._persist_alert(alert)

        # Alert object should be unchanged after failed persistence
        assert alert.rule_name == "r"
        assert alert.severity == AlertSeverity.INFO
        assert alert.metric_value == 1.0
        assert alert.threshold == 0.5

    def test_get_persisted_alerts_queries_db(self):
        """get_persisted_alerts returns records from DB."""
        mock_record = MagicMock()
        mock_record.rule_name = "some_rule"

        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_record]

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        mock_cm = MagicMock()
        mock_cm.__enter__ = Mock(return_value=mock_session)
        mock_cm.__exit__ = Mock(return_value=False)

        with patch("temper_ai.storage.database.get_session", return_value=mock_cm):
            results = AlertManager.get_persisted_alerts(limit=10)

        assert len(results) == 1
        assert results[0].rule_name == "some_rule"

    def test_get_persisted_alerts_handles_error(self):
        """get_persisted_alerts returns empty list on error."""
        with patch(
            "temper_ai.storage.database.get_session",
            side_effect=RuntimeError("db down"),
        ):
            results = AlertManager.get_persisted_alerts()

        assert results == []


# ---------------------------------------------------------------------------
# Halt callback tests
# ---------------------------------------------------------------------------


class TestHaltCallback:
    """Tests for halt callback registration and invocation."""

    def test_register_halt_callback(self):
        """register_halt_callback stores the callback."""
        mgr = AlertManager()
        cb = Mock()
        mgr.register_halt_callback(cb)
        assert mgr._halt_callback is cb

    @patch("temper_ai.observability.alerting.logger")
    def test_halt_callback_called_on_halt_workflow(self, mock_logger):
        """Registered halt callback is invoked with workflow_id."""
        mgr = _make_manager_with_rule(
            actions=[AlertAction.HALT_WORKFLOW],
            severity=AlertSeverity.CRITICAL,
        )
        cb = Mock()
        mgr.register_halt_callback(cb)

        mgr.check_metric("cost_usd", 15.0, context={"workflow_id": "wf-42"})

        cb.assert_called_once_with("wf-42")
        # Critical log should also fire
        mock_logger.critical.assert_called_once()

    @patch("temper_ai.observability.alerting.logger")
    def test_halt_logs_critical_without_callback(self, mock_logger):
        """Without a callback, _halt_workflow still logs critical."""
        mgr = _make_manager_with_rule(
            actions=[AlertAction.HALT_WORKFLOW],
            severity=AlertSeverity.CRITICAL,
        )
        assert mgr._halt_callback is None

        mgr.check_metric("cost_usd", 15.0, context={"workflow_id": "wf-99"})

        mock_logger.critical.assert_called_once()
        assert "wf-99" in mock_logger.critical.call_args[0][0]
