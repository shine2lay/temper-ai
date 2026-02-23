"""Tests for events/_schemas.py."""

import pytest

from temper_ai.events._schemas import (
    EventBusConfig,
    StageEventEmitConfig,
    StageTriggerConfig,
)
from temper_ai.events.constants import (
    DEFAULT_EVENT_RETENTION_DAYS,
    DEFAULT_TRIGGER_TIMEOUT_SECONDS,
)


class TestEventBusConfig:
    def test_defaults(self):
        cfg = EventBusConfig()
        assert cfg.enabled is False
        assert cfg.persist_events is True
        assert cfg.max_event_age_days == DEFAULT_EVENT_RETENTION_DAYS

    def test_custom_values(self):
        cfg = EventBusConfig(enabled=True, persist_events=False, max_event_age_days=7)
        assert cfg.enabled is True
        assert cfg.persist_events is False
        assert cfg.max_event_age_days == 7

    def test_enabled_true(self):
        cfg = EventBusConfig(enabled=True)
        assert cfg.enabled is True


class TestStageEventEmitConfig:
    def test_required_event_type(self):
        cfg = StageEventEmitConfig(event_type="stage.completed")
        assert cfg.event_type == "stage.completed"

    def test_default_include_output(self):
        cfg = StageEventEmitConfig(event_type="stage.done")
        assert cfg.include_output is False

    def test_include_output_true(self):
        cfg = StageEventEmitConfig(event_type="stage.done", include_output=True)
        assert cfg.include_output is True

    def test_missing_event_type_raises(self):
        with pytest.raises(Exception):
            StageEventEmitConfig()  # type: ignore[call-arg]


class TestStageTriggerConfig:
    def test_required_event_type(self):
        cfg = StageTriggerConfig(event_type="workflow.completed")
        assert cfg.event_type == "workflow.completed"

    def test_defaults(self):
        cfg = StageTriggerConfig(event_type="x")
        assert cfg.source_workflow is None
        assert cfg.payload_filter is None
        assert cfg.timeout_seconds == DEFAULT_TRIGGER_TIMEOUT_SECONDS

    def test_full_config(self):
        cfg = StageTriggerConfig(
            event_type="workflow.completed",
            source_workflow="wf-1",
            payload_filter={"status": "ok"},
            timeout_seconds=60,
        )
        assert cfg.source_workflow == "wf-1"
        assert cfg.payload_filter == {"status": "ok"}
        assert cfg.timeout_seconds == 60
