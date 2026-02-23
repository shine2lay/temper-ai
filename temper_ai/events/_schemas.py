"""Pydantic schemas for events module configuration."""

from typing import Any

from pydantic import BaseModel

from temper_ai.events.constants import (
    DEFAULT_EVENT_RETENTION_DAYS,
    DEFAULT_TRIGGER_TIMEOUT_SECONDS,
)


class EventBusConfig(BaseModel):
    """Configuration for the TemperEventBus."""

    enabled: bool = False
    persist_events: bool = True
    max_event_age_days: int = DEFAULT_EVENT_RETENTION_DAYS


class StageEventEmitConfig(BaseModel):
    """Configuration for events emitted by a stage."""

    event_type: str
    include_output: bool = False


class StageTriggerConfig(BaseModel):
    """Configuration for stages triggered by events."""

    event_type: str
    source_workflow: str | None = None
    payload_filter: dict[str, Any] | None = None
    timeout_seconds: int = DEFAULT_TRIGGER_TIMEOUT_SECONDS
