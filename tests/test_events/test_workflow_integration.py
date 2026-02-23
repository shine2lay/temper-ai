"""Tests for workflow schema integration with events (M9.2)."""

import pytest
from pydantic import ValidationError

from temper_ai.workflow._schemas import WorkflowConfigOptions, WorkflowStageReference


def _make_stage_ref(**kwargs):
    """Helper: build a minimal valid WorkflowStageReference."""
    defaults = {"name": "my_stage", "stage_ref": "configs/stages/my_stage.yaml"}
    defaults.update(kwargs)
    return WorkflowStageReference(**defaults)


# ---------------------------------------------------------------------------
# WorkflowStageReference — on_complete
# ---------------------------------------------------------------------------


class TestWorkflowStageReferenceOnComplete:
    def test_on_complete_none_by_default(self):
        ref = _make_stage_ref()
        assert ref.on_complete is None

    def test_on_complete_dict_is_coerced_to_schema(self):
        from temper_ai.events._schemas import StageEventEmitConfig

        ref = _make_stage_ref(on_complete={"event_type": "stage.done"})
        assert isinstance(ref.on_complete, StageEventEmitConfig)
        assert ref.on_complete.event_type == "stage.done"
        assert ref.on_complete.include_output is False

    def test_on_complete_dict_include_output_true(self):
        from temper_ai.events._schemas import StageEventEmitConfig

        ref = _make_stage_ref(
            on_complete={"event_type": "out.ready", "include_output": True}
        )
        assert isinstance(ref.on_complete, StageEventEmitConfig)
        assert ref.on_complete.include_output is True

    def test_on_complete_already_schema_passes_through(self):
        from temper_ai.events._schemas import StageEventEmitConfig

        cfg = StageEventEmitConfig(event_type="custom.event")
        ref = _make_stage_ref(on_complete=cfg)
        assert ref.on_complete is cfg


# ---------------------------------------------------------------------------
# WorkflowStageReference — trigger
# ---------------------------------------------------------------------------


class TestWorkflowStageReferenceTrigger:
    def test_trigger_none_by_default(self):
        ref = _make_stage_ref()
        assert ref.trigger is None

    def test_trigger_dict_is_coerced_to_schema(self):
        from temper_ai.events._schemas import StageTriggerConfig

        ref = _make_stage_ref(trigger={"event_type": "data.ready"})
        assert isinstance(ref.trigger, StageTriggerConfig)
        assert ref.trigger.event_type == "data.ready"

    def test_trigger_source_workflow_optional(self):
        from temper_ai.events._schemas import StageTriggerConfig

        ref = _make_stage_ref(
            trigger={"event_type": "data.ready", "source_workflow": "wf-a"}
        )
        assert isinstance(ref.trigger, StageTriggerConfig)
        assert ref.trigger.source_workflow == "wf-a"

    def test_trigger_already_schema_passes_through(self):
        from temper_ai.events._schemas import StageTriggerConfig

        cfg = StageTriggerConfig(event_type="ready")
        ref = _make_stage_ref(trigger=cfg)
        assert ref.trigger is cfg

    def test_trigger_and_depends_on_are_mutually_exclusive(self):
        with pytest.raises(
            ValidationError, match="event-triggered stages are DAG roots"
        ):
            _make_stage_ref(
                trigger={"event_type": "my.event"},
                depends_on=["other_stage"],
            )


# ---------------------------------------------------------------------------
# WorkflowConfigOptions — event_bus
# ---------------------------------------------------------------------------


class TestWorkflowConfigOptionsEventBus:
    def test_event_bus_none_by_default(self):
        opts = WorkflowConfigOptions()
        assert opts.event_bus is None

    def test_event_bus_dict_is_coerced_to_schema(self):
        from temper_ai.events._schemas import EventBusConfig

        opts = WorkflowConfigOptions(event_bus={"enabled": True})
        assert isinstance(opts.event_bus, EventBusConfig)
        assert opts.event_bus.enabled is True

    def test_event_bus_persist_events_default(self):
        from temper_ai.events._schemas import EventBusConfig

        opts = WorkflowConfigOptions(event_bus={"enabled": False})
        assert isinstance(opts.event_bus, EventBusConfig)
        assert opts.event_bus.persist_events is True

    def test_event_bus_already_schema_passes_through(self):
        from temper_ai.events._schemas import EventBusConfig

        cfg = EventBusConfig(enabled=True, persist_events=False)
        opts = WorkflowConfigOptions(event_bus=cfg)
        assert opts.event_bus is cfg


# ---------------------------------------------------------------------------
# Backward compatibility — stages without trigger/on_complete still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_stage_without_events_fields_is_valid(self):
        ref = _make_stage_ref(depends_on=[], optional=True)
        assert ref.trigger is None
        assert ref.on_complete is None
        assert ref.name == "my_stage"

    def test_workflow_config_options_without_event_bus(self):
        opts = WorkflowConfigOptions()
        assert opts.event_bus is None
        assert opts.rate_limit is not None
