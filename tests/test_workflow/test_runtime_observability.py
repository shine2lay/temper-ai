"""Tests for WorkflowRuntime lifecycle observability events."""
import os
import tempfile
from datetime import timezone
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from temper_ai.observability.constants import (
    EVENT_CONFIG_LOADED,
    EVENT_LIFECYCLE_ADAPTED,
    EVENT_WORKFLOW_COMPILED,
    EVENT_WORKFLOW_COMPILING,
)
from temper_ai.observability.event_bus import ObservabilityEvent, ObservabilityEventBus
from temper_ai.workflow.runtime import (
    InfrastructureBundle,
    RuntimeConfig,
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
    """Create a minimal workflow YAML file."""
    config = {
        "workflow": {
            "name": "test_wf",
            "stages": ["s1", "s2"],
        }
    }
    path = tmp_path / "test.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


class TestLoadConfigEvents:
    """Test lifecycle events from load_config."""

    def test_emits_config_loaded(self, event_bus, captured_events, tmp_workflow):
        """load_config emits EVENT_CONFIG_LOADED with path and stage count."""
        rt = WorkflowRuntime(
            event_bus=event_bus,
            workflow_id="wf-test-123",
        )
        rt.load_config(tmp_workflow)

        assert len(captured_events) == 1
        evt = captured_events[0]
        assert evt.event_type == EVENT_CONFIG_LOADED
        assert evt.workflow_id == "wf-test-123"
        assert evt.data["stage_count"] == 2
        assert "test.yaml" in evt.data["workflow_path"]

    def test_no_event_without_bus(self, tmp_workflow):
        """No event emitted when event_bus is None."""
        rt = WorkflowRuntime()
        config, inputs = rt.load_config(tmp_workflow)

        # Still loads config successfully, just no events emitted
        assert isinstance(config, dict)
        assert "workflow" in config

    def test_event_timestamp_is_utc(self, event_bus, captured_events, tmp_workflow):
        """Lifecycle events use UTC timestamps."""
        rt = WorkflowRuntime(event_bus=event_bus)
        rt.load_config(tmp_workflow)

        evt = captured_events[0]
        assert evt.timestamp.tzinfo == timezone.utc


class TestAdaptLifecycleEvents:
    """Test lifecycle events from adapt_lifecycle."""

    def test_no_event_when_disabled(self, event_bus, captured_events):
        """No lifecycle_adapted event when lifecycle is disabled."""
        rt = WorkflowRuntime(event_bus=event_bus)
        config = {"workflow": {"name": "x", "stages": ["s"]}}
        rt.adapt_lifecycle(config, {})

        lifecycle_events = [
            e for e in captured_events
            if e.event_type == EVENT_LIFECYCLE_ADAPTED
        ]
        assert len(lifecycle_events) == 0

    @patch("temper_ai.lifecycle.adapter.LifecycleAdapter")
    @patch("temper_ai.lifecycle.classifier.ProjectClassifier")
    @patch("temper_ai.lifecycle.profiles.ProfileRegistry")
    @patch("temper_ai.lifecycle.store.LifecycleStore")
    def test_emits_lifecycle_adapted(
        self, _store, _registry, _classifier, _adapter,
        event_bus, captured_events,
    ):
        """adapt_lifecycle emits EVENT_LIFECYCLE_ADAPTED on success."""
        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-lc")
        config = {
            "workflow": {
                "name": "x",
                "stages": ["s"],
                "lifecycle": {"enabled": True},
            }
        }
        # Mocked adapter.adapt returns a MagicMock, which triggers the event
        rt.adapt_lifecycle(config, {"topic": "test"})

        lifecycle_events = [
            e for e in captured_events
            if e.event_type == EVENT_LIFECYCLE_ADAPTED
        ]
        assert len(lifecycle_events) == 1
        assert lifecycle_events[0].data["status"] == "adapted"


class TestCompileEvents:
    """Test lifecycle events from compile."""

    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_emits_compiling_and_compiled(
        self, mock_registry_cls, event_bus, captured_events,
    ):
        """compile emits compiling and compiled events."""
        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "DynamicExecutionEngine"
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
        config = {"workflow": {"stages": ["s1"]}}

        engine, compiled = rt.compile(config, infra)

        assert len(captured_events) == 2
        assert captured_events[0].event_type == EVENT_WORKFLOW_COMPILING
        assert captured_events[0].workflow_id == "wf-compile"
        assert captured_events[1].event_type == EVENT_WORKFLOW_COMPILED
        assert isinstance(captured_events[1].data["engine"], str)

    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_no_events_without_bus(self, mock_registry_cls):
        """No events emitted when event_bus is None."""
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


class TestEventBusIntegration:
    """Integration tests for event bus with runtime."""

    def test_full_pipeline_events(self, event_bus, captured_events, tmp_workflow):
        """Full pipeline emits config_loaded event."""
        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-full")
        wf_config, inputs = rt.load_config(tmp_workflow)

        assert len(captured_events) >= 1
        types = [e.event_type for e in captured_events]
        assert EVENT_CONFIG_LOADED in types

    def test_workflow_id_propagated(self, event_bus, captured_events, tmp_workflow):
        """workflow_id is set on all emitted events."""
        rt = WorkflowRuntime(event_bus=event_bus, workflow_id="wf-prop-test")
        rt.load_config(tmp_workflow)

        for evt in captured_events:
            assert evt.workflow_id == "wf-prop-test"

    def test_subscriber_receives_events(self, tmp_workflow):
        """Custom subscriber receives lifecycle events."""
        bus = ObservabilityEventBus()
        received = []
        bus.subscribe(
            lambda e: received.append(e.event_type),
            event_types={EVENT_CONFIG_LOADED},
        )

        rt = WorkflowRuntime(event_bus=bus, workflow_id="wf-sub")
        rt.load_config(tmp_workflow)

        assert received == [EVENT_CONFIG_LOADED]


class TestLifecycleEventConstants:
    """Test that lifecycle event constants are defined correctly."""

    def test_constants_are_strings(self):
        """All lifecycle event constants are non-empty strings."""
        for const in (
            EVENT_CONFIG_LOADED,
            EVENT_LIFECYCLE_ADAPTED,
            EVENT_WORKFLOW_COMPILING,
            EVENT_WORKFLOW_COMPILED,
        ):
            assert isinstance(const, str)
            assert len(const) > 0

    def test_constants_are_unique(self):
        """All lifecycle event constants are unique."""
        consts = [
            EVENT_CONFIG_LOADED,
            EVENT_LIFECYCLE_ADAPTED,
            EVENT_WORKFLOW_COMPILING,
            EVENT_WORKFLOW_COMPILED,
        ]
        assert len(set(consts)) == len(consts)
