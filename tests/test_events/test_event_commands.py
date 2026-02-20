"""Tests for CLI commands in temper_ai.interfaces.cli.event_commands."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.event_commands import events_group
from temper_ai.interfaces.cli.event_constants import (
    MSG_NO_EVENTS,
    MSG_SUBSCRIBED,
    MSG_UNSUBSCRIBED,
    TABLE_TITLE_EVENTS,
    TABLE_TITLE_SUBSCRIPTIONS,
)

_MOCK_BUS_PATH = "temper_ai.interfaces.cli.event_commands._get_event_bus"
_MOCK_REGISTRY_PATH = "temper_ai.interfaces.cli.event_commands._get_subscription_registry"


def _make_event(**kwargs):
    """Build a minimal mock event object."""
    evt = MagicMock()
    evt.id = kwargs.get("id", "evt-001")
    evt.event_type = kwargs.get("event_type", "workflow.completed")
    evt.timestamp = kwargs.get("timestamp", datetime(2026, 1, 1, tzinfo=timezone.utc))
    evt.source_workflow_id = kwargs.get("source_workflow_id", "wf-123")
    evt.payload = kwargs.get("payload", {})
    return evt


def _make_subscription(**kwargs):
    """Build a minimal mock subscription object."""
    sub = MagicMock()
    sub.id = kwargs.get("id", "sub-001")
    sub.event_type = kwargs.get("event_type", "workflow.completed")
    sub.agent_id = kwargs.get("agent_id", "agent-1")
    sub.workflow_to_trigger = kwargs.get("workflow_to_trigger", None)
    sub.handler_ref = kwargs.get("handler_ref", None)
    sub.active = kwargs.get("active", True)
    return sub


class TestEventsListCommand:
    def test_list_no_events(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = []
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(events_group, ["list"])
        assert result.exit_code == 0
        assert MSG_NO_EVENTS in result.output

    def test_list_with_events(self):
        runner = CliRunner()
        evt = _make_event()
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = [evt]
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(events_group, ["list"])
        assert result.exit_code == 0
        assert "workflow.completed" in result.output

    def test_list_with_type_filter(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = []
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(
                events_group, ["list", "--type", "workflow.completed"]
            )
        assert result.exit_code == 0
        mock_bus.replay_events.assert_called_once_with(
            event_type="workflow.completed", since=None, limit=50
        )

    def test_list_invalid_since_date(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(events_group, ["list", "--since", "not-a-date"])
        assert result.exit_code != 0
        assert "Invalid date format" in result.output


class TestEventsSubscribeCommand:
    def test_subscribe_success(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        mock_bus.subscribe_persistent.return_value = "sub-xyz"
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(
                events_group, ["subscribe", "agent-1", "workflow.completed"]
            )
        assert result.exit_code == 0
        assert "sub-xyz" in result.output

    def test_subscribe_with_workflow(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        mock_bus.subscribe_persistent.return_value = "sub-abc"
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(
                events_group,
                ["subscribe", "agent-1", "workflow.completed", "--workflow", "my-wf.yaml"],
            )
        assert result.exit_code == 0
        mock_bus.subscribe_persistent.assert_called_once_with(
            agent_id="agent-1",
            event_type="workflow.completed",
            workflow_to_trigger="my-wf.yaml",
        )


class TestEventsUnsubscribeCommand:
    def test_unsubscribe_success(self):
        runner = CliRunner()
        mock_registry = MagicMock()
        mock_registry.unregister.return_value = True
        with patch(_MOCK_REGISTRY_PATH, return_value=mock_registry):
            result = runner.invoke(events_group, ["unsubscribe", "sub-001"])
        assert result.exit_code == 0
        assert "sub-001" in result.output

    def test_unsubscribe_not_found(self):
        runner = CliRunner()
        mock_registry = MagicMock()
        mock_registry.unregister.return_value = False
        with patch(_MOCK_REGISTRY_PATH, return_value=mock_registry):
            result = runner.invoke(events_group, ["unsubscribe", "ghost-sub"])
        assert result.exit_code != 0


class TestEventsSubscriptionsCommand:
    def test_subscriptions_listed(self):
        runner = CliRunner()
        sub = _make_subscription()
        mock_registry = MagicMock()
        mock_registry.load_active.return_value = [sub]
        with patch(_MOCK_REGISTRY_PATH, return_value=mock_registry):
            result = runner.invoke(events_group, ["subscriptions"])
        assert result.exit_code == 0
        assert TABLE_TITLE_SUBSCRIPTIONS in result.output

    def test_subscriptions_empty(self):
        runner = CliRunner()
        mock_registry = MagicMock()
        mock_registry.load_active.return_value = []
        with patch(_MOCK_REGISTRY_PATH, return_value=mock_registry):
            result = runner.invoke(events_group, ["subscriptions"])
        assert result.exit_code == 0


class TestEventsReplayCommand:
    def test_replay_no_events(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = []
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(events_group, ["replay", "workflow.completed"])
        assert result.exit_code == 0
        assert MSG_NO_EVENTS in result.output

    def test_replay_with_events(self):
        runner = CliRunner()
        evt = _make_event()
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = [evt]
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(events_group, ["replay", "workflow.completed"])
        assert result.exit_code == 0
        assert "Replaying 1 event(s)" in result.output

    def test_replay_invalid_since(self):
        runner = CliRunner()
        mock_bus = MagicMock()
        with patch(_MOCK_BUS_PATH, return_value=mock_bus):
            result = runner.invoke(
                events_group, ["replay", "workflow.completed", "--since", "bad-date"]
            )
        assert result.exit_code != 0
        assert "Invalid date format" in result.output
