"""Tests for create_event_triggered_node in node_builder (M9.2)."""
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.node_builder import STAGE_TIMEOUT_STATUS, create_event_triggered_node


def _make_trigger_config(
    event_type: str = "data.ready",
    timeout_seconds: int = 30,
    source_workflow: Optional[str] = None,
) -> Any:
    from temper_ai.events._schemas import StageTriggerConfig

    return StageTriggerConfig(
        event_type=event_type,
        timeout_seconds=timeout_seconds,
        source_workflow=source_workflow,
    )


def _make_inner_node(return_value: Optional[Dict[str, Any]] = None) -> MagicMock:
    inner = MagicMock()
    inner.return_value = return_value or {"stage_outputs": {}, "current_stage": "s1"}
    return inner


# ---------------------------------------------------------------------------
# Basic wrapping behaviour
# ---------------------------------------------------------------------------


class TestCreateEventTriggeredNode:
    def test_returns_callable(self):
        inner = _make_inner_node()
        event_bus = MagicMock()
        cfg = _make_trigger_config()

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        assert callable(node)

    def test_waits_for_event_with_correct_args(self):
        inner = _make_inner_node()
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = {"key": "value"}
        cfg = _make_trigger_config(event_type="my.event", timeout_seconds=60, source_workflow="wf-a")

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        node({})

        event_bus.wait_for_event.assert_called_once_with(
            event_type="my.event",
            timeout_seconds=60,
            source_workflow_filter="wf-a",
        )

    def test_injects_event_payload_into_state(self):
        payload = {"data": 42}
        inner = _make_inner_node()
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = payload
        cfg = _make_trigger_config()

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        node({"existing": True})

        called_state = inner.call_args[0][0]
        assert called_state["trigger_event"] == payload

    def test_calls_inner_function_after_event(self):
        inner = _make_inner_node({"stage_outputs": {"s1": {"out": 1}}, "current_stage": "s1"})
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = {"k": "v"}
        cfg = _make_trigger_config()

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        result = node({})

        inner.assert_called_once()
        assert result == inner.return_value

    def test_timeout_sets_stage_status(self):
        inner = _make_inner_node()
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = None  # timeout
        cfg = _make_trigger_config()

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        result = node({})

        assert result["stage_status"] == STAGE_TIMEOUT_STATUS
        inner.assert_not_called()

    def test_timeout_does_not_mutate_original_state(self):
        inner = _make_inner_node()
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = None
        cfg = _make_trigger_config()
        original = {"my_key": "original"}

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        result = node(original)

        # Original dict should be unchanged
        assert "stage_status" not in original
        assert result["stage_status"] == STAGE_TIMEOUT_STATUS

    def test_no_event_bus_runs_inner_immediately(self):
        inner = _make_inner_node()
        cfg = _make_trigger_config()

        node = create_event_triggered_node("s1", inner, None, cfg)
        node({"state_key": 1})

        inner.assert_called_once()

    def test_source_workflow_filter_passed_correctly(self):
        inner = _make_inner_node()
        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = {}
        cfg = _make_trigger_config(source_workflow="source-wf")

        node = create_event_triggered_node("s1", inner, event_bus, cfg)
        node({})

        _, kwargs = event_bus.wait_for_event.call_args
        assert kwargs["source_workflow_filter"] == "source-wf"
