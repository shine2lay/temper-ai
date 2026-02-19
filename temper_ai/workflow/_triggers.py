"""Trigger configuration schemas (event, cron, threshold)."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from temper_ai.shared.constants.durations import (
    SECONDS_PER_5_MINUTES,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    SECONDS_PER_WEEK,
)
from temper_ai.shared.constants.limits import (
    MEDIUM_ITEM_LIMIT,
    SMALL_ITEM_LIMIT,
    SMALL_QUEUE_SIZE,
)
from temper_ai.shared.constants.retries import DEFAULT_MAX_RETRIES


class EventSourceConfig(BaseModel):
    """Event source configuration."""
    type: Literal["message_queue", "webhook", "database_poll", "file_watch"]
    connection: Optional[str] = None
    queue_name: Optional[str] = None
    consumer_group: Optional[str] = None
    max_connections: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    reconnect_delay_seconds: int = Field(default=SMALL_ITEM_LIMIT, gt=0)


class EventFilterCondition(BaseModel):
    """Event filter condition."""
    field: str
    operator: Literal["in", "eq", "ne", "gt", "lt", "gte", "lte", "contains"]
    values: Optional[List[Any]] = None
    value: Optional[Any] = None


class EventFilter(BaseModel):
    """Event filter configuration."""
    event_type: str
    conditions: List[EventFilterCondition] = Field(default_factory=list)


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration."""
    max_parallel_executions: int = Field(default=SMALL_ITEM_LIMIT, gt=0)
    queue_when_busy: bool = True
    max_queue_size: int = Field(default=SMALL_QUEUE_SIZE, gt=0)
    deduplicate: bool = True
    dedup_window_seconds: int = Field(default=SECONDS_PER_5_MINUTES, gt=0)
    dedup_key: Optional[str] = None


class TriggerRetryConfig(BaseModel):
    """Retry configuration for triggers."""
    enabled: bool = True
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    retry_delay_seconds: int = Field(default=SECONDS_PER_MINUTE, gt=0)
    exponential_backoff: bool = True


class TriggerMetadata(BaseModel):
    """Trigger metadata."""
    owner: Optional[str] = None
    alert_on_failure: bool = True
    alert_channels: List[str] = Field(default_factory=list)
    notify_on_completion: bool = False
    notification_channels: List[str] = Field(default_factory=list)


class EventTriggerInner(BaseModel):
    """Inner event trigger configuration."""
    name: str
    description: str
    type: Literal["EventTrigger"]
    source: EventSourceConfig
    filter: EventFilter
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    retry: TriggerRetryConfig = Field(default_factory=TriggerRetryConfig)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class CronTriggerInner(BaseModel):
    """Inner cron trigger configuration."""
    name: str
    description: str
    type: Literal["CronTrigger"]
    schedule: str  # Cron format
    timezone: str = "UTC"
    skip_on_holiday: bool = True
    skip_if_recent_execution: bool = True
    min_hours_between_runs: int = Field(default=SECONDS_PER_WEEK // SECONDS_PER_HOUR, gt=0)
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class MetricConfig(BaseModel):
    """Metric configuration for threshold triggers."""
    source: Literal["prometheus", "datadog", "custom", "database"]
    query: str
    evaluation_interval_seconds: int = Field(default=SECONDS_PER_MINUTE, gt=0)


class CompoundCondition(BaseModel):
    """Compound condition for threshold triggers."""
    metric: str
    operator: str
    value: float


class CompoundConditions(BaseModel):
    """Compound conditions configuration."""
    operator: Literal["AND", "OR"]
    conditions: List[CompoundCondition]


class ThresholdTriggerInner(BaseModel):
    """Inner threshold trigger configuration."""
    name: str
    description: str
    type: Literal["ThresholdTrigger"]
    metric: MetricConfig
    condition: Literal["greater_than", "less_than", "equals"]
    threshold: float
    duration_minutes: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    compound_conditions: Optional[CompoundConditions] = None
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class EventTrigger(BaseModel):
    """Event trigger configuration schema."""
    trigger: EventTriggerInner


class CronTrigger(BaseModel):
    """Cron trigger configuration schema."""
    trigger: CronTriggerInner


class ThresholdTrigger(BaseModel):
    """Threshold trigger configuration schema."""
    trigger: ThresholdTriggerInner


TriggerConfig = Union[EventTrigger, CronTrigger, ThresholdTrigger]
