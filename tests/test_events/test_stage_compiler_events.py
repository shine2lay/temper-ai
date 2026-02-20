"""Tests for event integration in stage_compiler (M9.2)."""
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.stage_compiler import (
    _get_on_complete_config,
    _get_trigger_config,
    _maybe_wrap_on_complete_node,
    _maybe_wrap_trigger_node,
)


def _make_stage_ref_obj(trigger=None, on_complete=None, depends_on=None):
    """Return a simple mock object mimicking WorkflowStageReference."""
    ref = MagicMock()
    ref.trigger = trigger
    ref.on_complete = on_complete
    ref.depends_on = depends_on or []
    return ref


def _make_trigger_config(event_type: str = "data.ready", timeout_seconds: int = 30):
    from temper_ai.events._schemas import StageTriggerConfig

    return StageTriggerConfig(event_type=event_type, timeout_seconds=timeout_seconds)


def _make_emit_config(event_type: str = "stage.done", include_output: bool = False):
    from temper_ai.events._schemas import StageEventEmitConfig

    return StageEventEmitConfig(event_type=event_type, include_output=include_output)


# ---------------------------------------------------------------------------
# _get_trigger_config
# ---------------------------------------------------------------------------


class TestGetTriggerConfig:
    def test_returns_none_for_none_ref(self):
        assert _get_trigger_config(None) is None

    def test_returns_trigger_from_pydantic_ref(self):
        cfg = _make_trigger_config()
        ref = _make_stage_ref_obj(trigger=cfg)
        assert _get_trigger_config(ref) is cfg

    def test_returns_trigger_from_dict_ref(self):
        cfg = _make_trigger_config()
        ref = {"trigger": cfg}
        assert _get_trigger_config(ref) is cfg

    def test_returns_none_when_no_trigger(self):
        ref = _make_stage_ref_obj(trigger=None)
        assert _get_trigger_config(ref) is None


# ---------------------------------------------------------------------------
# _get_on_complete_config
# ---------------------------------------------------------------------------


class TestGetOnCompleteConfig:
    def test_returns_none_for_none_ref(self):
        assert _get_on_complete_config(None) is None

    def test_returns_on_complete_from_pydantic_ref(self):
        cfg = _make_emit_config()
        ref = _make_stage_ref_obj(on_complete=cfg)
        assert _get_on_complete_config(ref) is cfg

    def test_returns_none_when_no_on_complete(self):
        ref = _make_stage_ref_obj(on_complete=None)
        assert _get_on_complete_config(ref) is None


# ---------------------------------------------------------------------------
# _maybe_wrap_trigger_node
# ---------------------------------------------------------------------------


class TestMaybeWrapTriggerNode:
    def test_no_trigger_returns_original_node(self):
        node = MagicMock()
        ref = _make_stage_ref_obj(trigger=None)
        result = _maybe_wrap_trigger_node("s1", node, ref, {})
        assert result is node

    def test_with_trigger_returns_wrapper(self):
        node = MagicMock()
        cfg = _make_trigger_config()
        ref = _make_stage_ref_obj(trigger=cfg)

        wrapper = _maybe_wrap_trigger_node("s1", node, ref, {})
        assert wrapper is not node
        assert callable(wrapper)

    def test_wrapper_uses_event_bus_from_state(self):
        inner = MagicMock(return_value={"stage_outputs": {}})
        cfg = _make_trigger_config()
        ref = _make_stage_ref_obj(trigger=cfg)

        event_bus = MagicMock()
        event_bus.wait_for_event.return_value = {"ok": True}

        wrapper = _maybe_wrap_trigger_node("s1", inner, ref, {})
        wrapper({"event_bus": event_bus})

        event_bus.wait_for_event.assert_called_once()

    def test_trigger_node_runs_immediately_without_event_bus(self):
        inner = MagicMock(return_value={})
        cfg = _make_trigger_config()
        ref = _make_stage_ref_obj(trigger=cfg)

        wrapper = _maybe_wrap_trigger_node("s1", inner, ref, {})
        wrapper({})  # no event_bus key

        inner.assert_called_once()

    def test_normal_stage_compiles_unchanged(self):
        node = MagicMock()
        ref = _make_stage_ref_obj()  # trigger=None

        result = _maybe_wrap_trigger_node("s1", node, ref, {})
        assert result is node


# ---------------------------------------------------------------------------
# _maybe_wrap_on_complete_node
# ---------------------------------------------------------------------------


class TestMaybeWrapOnCompleteNode:
    def test_no_on_complete_returns_original_node(self):
        node = MagicMock()
        ref = _make_stage_ref_obj(on_complete=None)
        result = _maybe_wrap_on_complete_node("s1", node, ref, {})
        assert result is node

    def test_with_on_complete_returns_wrapper(self):
        node = MagicMock(return_value={"stage_outputs": {}})
        cfg = _make_emit_config()
        ref = _make_stage_ref_obj(on_complete=cfg)

        wrapper = _maybe_wrap_on_complete_node("s1", node, ref, {})
        assert wrapper is not node
        assert callable(wrapper)

    def test_on_complete_emits_event(self):
        event_bus = MagicMock()
        inner = MagicMock(return_value={"stage_outputs": {}, "event_bus": event_bus})
        cfg = _make_emit_config(event_type="stage.done")
        ref = _make_stage_ref_obj(on_complete=cfg)

        wrapper = _maybe_wrap_on_complete_node("s1", inner, ref, {})
        wrapper({"event_bus": event_bus, "workflow_id": "wf-1"})

        event_bus.emit.assert_called_once()
        call_kwargs = event_bus.emit.call_args[1]
        assert call_kwargs["event_type"] == "stage.done"
        assert call_kwargs["source_stage_name"] == "s1"

    def test_on_complete_no_event_bus_is_silent(self):
        inner = MagicMock(return_value={"stage_outputs": {}})
        cfg = _make_emit_config()
        ref = _make_stage_ref_obj(on_complete=cfg)

        wrapper = _maybe_wrap_on_complete_node("s1", inner, ref, {})
        result = wrapper({})  # no event_bus in state or result

        assert result == inner.return_value  # no crash

    def test_on_complete_include_output_adds_output_to_payload(self):
        event_bus = MagicMock()
        stage_out = {"answer": 42}
        inner = MagicMock(
            return_value={"stage_outputs": {"s1": stage_out}, "event_bus": event_bus}
        )
        cfg = _make_emit_config(event_type="out.ready", include_output=True)
        ref = _make_stage_ref_obj(on_complete=cfg)

        wrapper = _maybe_wrap_on_complete_node("s1", inner, ref, {})
        wrapper({"event_bus": event_bus})

        call_kwargs = event_bus.emit.call_args[1]
        assert call_kwargs["payload"]["output"] == stage_out
