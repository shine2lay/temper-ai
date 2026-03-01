"""Tests for WorkflowRuntime lifecycle observability events."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from temper_ai.observability.constants import (
    EVENT_PIPELINE_PHASE_END,
    EVENT_PIPELINE_PHASE_FAIL,
    EVENT_PIPELINE_PHASE_START,
)
from temper_ai.observability.event_bus import ObservabilityEventBus
from temper_ai.workflow.runtime import (
    InfrastructureBundle,
    WorkflowRuntime,
)


@pytest.fixture
def event_bus():
    """Create a real ObservabilityEventBus."""
    return ObservabilityEventBus()


@pytest.fixture
def captured_events(event_bus):
    """Subscribe to all events and capture them in a list."""
    events = []
    event_bus.subscribe(lambda e: events.append(e))
    return events


@pytest.fixture
def tmp_workflow(tmp_path):
    """Create a schema-valid workflow YAML file."""
    config = {
        "workflow": {
            "name": "test_wf",
            "description": "Test workflow",
            "stages": [
                {"name": "s1", "stage_ref": "stages/s1.yaml"},
                {"name": "s2", "stage_ref": "stages/s2.yaml"},
            ],
            "error_handling": {
                "on_stage_failure": "halt",
                "max_stage_retries": 2,
                "escalation_policy": "log_and_notify",
                "enable_rollback": False,
            },
        }
    }
    path = tmp_path / "test.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


class TestLoadConfigEvents:
    """Test that load_config does not emit direct lifecycle events (moved to run_pipeline)."""

    def test_no_event_without_bus(self, tmp_workflow):
        """load_config succeeds without an event bus and emits no events."""
        rt = WorkflowRuntime()
        config, inputs = rt.load_config(tmp_workflow)

        # Still loads config successfully, just no events emitted
        assert isinstance(config, dict)
        assert "workflow" in config

    def test_no_event_with_bus(self, event_bus, captured_events, tmp_workflow):
        """load_config does not emit direct events; phase events come from run_pipeline."""
        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-test-123")
        rt.load_config(tmp_workflow)

        assert len(captured_events) == 0


class TestAdaptLifecycleEvents:
    """Test that adapt_lifecycle does not emit direct events (moved to run_pipeline)."""

    def test_no_event_when_disabled(self, event_bus, captured_events):
        """adapt_lifecycle emits no events; phase events come from run_pipeline."""
        rt = WorkflowRuntime(event_bus=event_bus)
        config = {"workflow": {"name": "x", "stages": ["s"]}}
        rt.adapt_lifecycle(config, {})

        assert len(captured_events) == 0


class TestCompileEvents:
    """Test that compile does not emit direct events (moved to run_pipeline)."""

    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_no_events_without_bus(self, mock_registry_cls):
        """compile succeeds without a bus and emits no events."""
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_engine.compile.return_value = mock_compiled

        mock_registry = MagicMock()
        mock_registry.get_engine_from_config.return_value = mock_engine
        mock_registry_cls.return_value = mock_registry

        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        engine, compiled = rt.compile({"workflow": {"stages": ["s1"]}}, infra)

        # Compiles successfully, just no events emitted
        assert engine is mock_engine
        assert compiled is mock_compiled

    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_no_events_with_bus(self, mock_registry_cls, event_bus, captured_events):
        """compile emits no direct events; phase events come from run_pipeline."""
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_engine.compile.return_value = mock_compiled

        mock_registry = MagicMock()
        mock_registry.get_engine_from_config.return_value = mock_engine
        mock_registry_cls.return_value = mock_registry

        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-compile")
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        rt.compile({"workflow": {"stages": ["s1"]}}, infra)

        assert len(captured_events) == 0


class TestEventBusIntegration:
    """Integration tests for event bus with runtime."""

    def test_load_config_emits_no_events(
        self, event_bus, captured_events, tmp_workflow
    ):
        """load_config no longer emits direct events; phase events come from run_pipeline."""
        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-full")
        wf_config, inputs = rt.load_config(tmp_workflow)

        # No events from load_config directly
        assert len(captured_events) == 0
        # But the config was loaded correctly
        assert wf_config["workflow"]["name"] == "test_wf"

    def test_subscriber_receives_phase_events_types(self, tmp_workflow):
        """Phase event type constants are strings and can be used with subscribe."""
        bus = ObservabilityEventBus()
        received = []
        bus.subscribe(
            lambda e: received.append(e.event_type),
            event_types={EVENT_PIPELINE_PHASE_START, EVENT_PIPELINE_PHASE_END},
        )

        # load_config alone doesn't trigger phase events
        rt = WorkflowRuntime(event_bus=bus, workflow_id="wf-sub")
        rt.load_config(tmp_workflow)

        assert received == []


class TestLifecycleEventConstants:
    """Test that pipeline phase event constants are defined correctly."""

    def test_constants_are_strings(self):
        """All pipeline phase event constants are non-empty strings."""
        for const in (
            EVENT_PIPELINE_PHASE_START,
            EVENT_PIPELINE_PHASE_END,
            EVENT_PIPELINE_PHASE_FAIL,
        ):
            assert isinstance(const, str)
            assert len(const) > 0

    def test_constants_are_unique(self):
        """All pipeline phase event constants are unique."""
        consts = [
            EVENT_PIPELINE_PHASE_START,
            EVENT_PIPELINE_PHASE_END,
            EVENT_PIPELINE_PHASE_FAIL,
        ]
        assert len(set(consts)) == len(consts)
