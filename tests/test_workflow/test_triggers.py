"""Tests for trigger configuration schemas — EventTrigger, CronTrigger, ThresholdTrigger.

Covers all Pydantic models in temper_ai/workflow/_triggers.py:
- EventSourceConfig, EventFilterCondition, EventFilter
- ConcurrencyConfig, TriggerRetryConfig, TriggerMetadata
- MetricConfig, CompoundCondition, CompoundConditions
- EventTriggerInner, CronTriggerInner, ThresholdTriggerInner
- EventTrigger, CronTrigger, ThresholdTrigger wrappers
"""

import pytest
from pydantic import ValidationError

from temper_ai.workflow._triggers import (
    CompoundCondition,
    CompoundConditions,
    ConcurrencyConfig,
    CronTrigger,
    CronTriggerInner,
    EventFilter,
    EventFilterCondition,
    EventSourceConfig,
    EventTrigger,
    EventTriggerInner,
    MetricConfig,
    ThresholdTrigger,
    ThresholdTriggerInner,
    TriggerMetadata,
    TriggerRetryConfig,
)


class TestEventSourceConfig:
    """Tests for EventSourceConfig model."""

    def test_message_queue_type(self):
        cfg = EventSourceConfig(type="message_queue")
        assert cfg.type == "message_queue"

    def test_webhook_type(self):
        cfg = EventSourceConfig(type="webhook")
        assert cfg.type == "webhook"

    def test_database_poll_type(self):
        cfg = EventSourceConfig(type="database_poll")
        assert cfg.type == "database_poll"

    def test_file_watch_type(self):
        cfg = EventSourceConfig(type="file_watch")
        assert cfg.type == "file_watch"

    def test_invalid_type_raises(self):
        """Unsupported type strings must fail validation."""
        with pytest.raises(ValidationError):
            EventSourceConfig(type="kafka")

    def test_default_max_connections(self):
        """max_connections defaults to MEDIUM_ITEM_LIMIT (10)."""
        cfg = EventSourceConfig(type="webhook")
        assert cfg.max_connections == 10

    def test_default_reconnect_delay(self):
        """reconnect_delay_seconds defaults to SMALL_ITEM_LIMIT (5)."""
        cfg = EventSourceConfig(type="webhook")
        assert cfg.reconnect_delay_seconds == 5

    def test_max_connections_gt0_enforced(self):
        with pytest.raises(ValidationError):
            EventSourceConfig(type="webhook", max_connections=0)

    def test_reconnect_delay_gt0_enforced(self):
        with pytest.raises(ValidationError):
            EventSourceConfig(type="webhook", reconnect_delay_seconds=0)

    def test_optional_fields_default_none(self):
        cfg = EventSourceConfig(type="file_watch")
        assert cfg.connection is None
        assert cfg.queue_name is None
        assert cfg.consumer_group is None

    def test_with_all_optional_fields(self):
        cfg = EventSourceConfig(
            type="message_queue",
            connection="amqp://localhost",
            queue_name="events",
            consumer_group="cg1",
            max_connections=5,
            reconnect_delay_seconds=10,
        )
        assert cfg.connection == "amqp://localhost"
        assert cfg.queue_name == "events"
        assert cfg.consumer_group == "cg1"


class TestEventFilterCondition:
    """Tests for EventFilterCondition model."""

    def test_in_operator(self):
        cond = EventFilterCondition(field="status", operator="in", values=["a", "b"])
        assert cond.operator == "in"
        assert cond.values == ["a", "b"]

    def test_eq_operator(self):
        cond = EventFilterCondition(field="x", operator="eq", value=42)
        assert cond.operator == "eq"
        assert cond.value == 42

    def test_all_valid_operators(self):
        for op in ("in", "eq", "ne", "gt", "lt", "gte", "lte", "contains"):
            cond = EventFilterCondition(field="f", operator=op)
            assert cond.operator == op

    def test_invalid_operator_raises(self):
        with pytest.raises(ValidationError):
            EventFilterCondition(field="f", operator="like")

    def test_values_and_value_default_none(self):
        cond = EventFilterCondition(field="f", operator="eq")
        assert cond.values is None
        assert cond.value is None


class TestEventFilter:
    """Tests for EventFilter model."""

    def test_minimal_construction(self):
        f = EventFilter(event_type="order.created")
        assert f.event_type == "order.created"
        assert f.conditions == []

    def test_with_conditions(self):
        cond = EventFilterCondition(field="status", operator="eq", value="active")
        f = EventFilter(event_type="order.updated", conditions=[cond])
        assert len(f.conditions) == 1
        assert f.conditions[0].field == "status"

    def test_multiple_conditions(self):
        conds = [
            EventFilterCondition(field="a", operator="eq", value=1),
            EventFilterCondition(field="b", operator="gt", value=0),
        ]
        f = EventFilter(event_type="evt", conditions=conds)
        assert len(f.conditions) == 2


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig model defaults and constraints."""

    def test_defaults(self):
        """All defaults match named constants."""
        cfg = ConcurrencyConfig()
        assert cfg.max_parallel_executions == 5  # SMALL_ITEM_LIMIT
        assert cfg.queue_when_busy is True
        assert cfg.max_queue_size == 100  # SMALL_QUEUE_SIZE
        assert cfg.deduplicate is True
        assert cfg.dedup_window_seconds == 300  # SECONDS_PER_5_MINUTES
        assert cfg.dedup_key is None

    def test_max_parallel_executions_gt0(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_parallel_executions=0)

    def test_max_queue_size_gt0(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_queue_size=0)

    def test_dedup_window_gt0(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(dedup_window_seconds=0)

    def test_custom_values(self):
        cfg = ConcurrencyConfig(
            max_parallel_executions=3,
            queue_when_busy=False,
            dedup_key="order_id",
        )
        assert cfg.max_parallel_executions == 3
        assert cfg.queue_when_busy is False
        assert cfg.dedup_key == "order_id"


class TestTriggerRetryConfig:
    """Tests for TriggerRetryConfig model."""

    def test_defaults(self):
        cfg = TriggerRetryConfig()
        assert cfg.enabled is True
        assert cfg.max_retries == 3  # DEFAULT_MAX_RETRIES
        assert cfg.retry_delay_seconds == 60  # SECONDS_PER_MINUTE
        assert cfg.exponential_backoff is True

    def test_max_retries_zero_is_valid(self):
        """ge=0 allows zero retries."""
        cfg = TriggerRetryConfig(max_retries=0)
        assert cfg.max_retries == 0

    def test_max_retries_negative_raises(self):
        with pytest.raises(ValidationError):
            TriggerRetryConfig(max_retries=-1)

    def test_retry_delay_gt0_enforced(self):
        with pytest.raises(ValidationError):
            TriggerRetryConfig(retry_delay_seconds=0)

    def test_disabled_retry(self):
        cfg = TriggerRetryConfig(enabled=False, max_retries=0)
        assert cfg.enabled is False


class TestTriggerMetadata:
    """Tests for TriggerMetadata model."""

    def test_defaults(self):
        meta = TriggerMetadata()
        assert meta.owner is None
        assert meta.alert_on_failure is True
        assert meta.alert_channels == []
        assert meta.notify_on_completion is False
        assert meta.notification_channels == []

    def test_with_owner_and_channels(self):
        meta = TriggerMetadata(
            owner="team-platform",
            alert_channels=["#alerts", "#oncall"],
            notify_on_completion=True,
            notification_channels=["#deploys"],
        )
        assert meta.owner == "team-platform"
        assert "#alerts" in meta.alert_channels
        assert meta.notify_on_completion is True
        assert meta.notification_channels == ["#deploys"]


class TestMetricConfig:
    """Tests for MetricConfig model."""

    def test_prometheus_source(self):
        cfg = MetricConfig(source="prometheus", query="rate(errors_total[5m])")
        assert cfg.source == "prometheus"
        assert cfg.evaluation_interval_seconds == 60  # SECONDS_PER_MINUTE

    def test_all_valid_sources(self):
        for src in ("prometheus", "datadog", "custom", "database"):
            cfg = MetricConfig(source=src, query="some_query")
            assert cfg.source == src

    def test_invalid_source_raises(self):
        with pytest.raises(ValidationError):
            MetricConfig(source="grafana", query="q")

    def test_evaluation_interval_gt0(self):
        with pytest.raises(ValidationError):
            MetricConfig(source="prometheus", query="q", evaluation_interval_seconds=0)

    def test_custom_evaluation_interval(self):
        cfg = MetricConfig(
            source="datadog",
            query="avg:system.cpu.user{*}",
            evaluation_interval_seconds=120,
        )
        assert cfg.evaluation_interval_seconds == 120


class TestCompoundConditions:
    """Tests for CompoundCondition and CompoundConditions models."""

    def test_compound_condition_construction(self):
        cond = CompoundCondition(metric="error_rate", operator="gt", value=0.05)
        assert cond.metric == "error_rate"
        assert cond.operator == "gt"
        assert cond.value == 0.05

    def test_compound_conditions_and(self):
        cond1 = CompoundCondition(metric="error_rate", operator="gt", value=0.05)
        cond2 = CompoundCondition(metric="latency_p99", operator="gt", value=500.0)
        compound = CompoundConditions(operator="AND", conditions=[cond1, cond2])
        assert compound.operator == "AND"
        assert len(compound.conditions) == 2

    def test_compound_conditions_or(self):
        cond = CompoundCondition(metric="cpu_usage", operator="gt", value=0.9)
        compound = CompoundConditions(operator="OR", conditions=[cond])
        assert compound.operator == "OR"
        assert len(compound.conditions) == 1

    def test_invalid_operator_raises(self):
        """Only 'AND' and 'OR' are valid literals."""
        with pytest.raises(ValidationError):
            CompoundConditions(operator="NOT", conditions=[])

    def test_empty_conditions_list(self):
        compound = CompoundConditions(operator="AND", conditions=[])
        assert compound.conditions == []


class TestEventTrigger:
    """Tests for EventTrigger and EventTriggerInner."""

    def _make_inner(self, **kwargs) -> EventTriggerInner:
        defaults = {
            "name": "on-pr-created",
            "description": "Triggered on PR creation",
            "type": "EventTrigger",
            "source": EventSourceConfig(type="webhook"),
            "filter": EventFilter(event_type="pull_request.opened"),
            "workflow": "vcs_suggestion",
        }
        defaults.update(kwargs)
        return EventTriggerInner(**defaults)

    def test_full_construction(self):
        inner = self._make_inner()
        trigger = EventTrigger(trigger=inner)
        assert trigger.trigger.name == "on-pr-created"
        assert trigger.trigger.type == "EventTrigger"
        assert trigger.trigger.workflow == "vcs_suggestion"

    def test_type_must_be_event_trigger_literal(self):
        with pytest.raises(ValidationError):
            self._make_inner(type="CronTrigger")

    def test_workflow_inputs_defaults_empty(self):
        inner = self._make_inner()
        assert inner.workflow_inputs == {}

    def test_concurrency_uses_defaults(self):
        inner = self._make_inner()
        assert inner.concurrency.max_parallel_executions == 5

    def test_retry_uses_defaults(self):
        inner = self._make_inner()
        assert inner.retry.max_retries == 3

    def test_metadata_uses_defaults(self):
        inner = self._make_inner()
        assert inner.metadata.alert_on_failure is True

    def test_with_workflow_inputs(self):
        inner = self._make_inner(workflow_inputs={"branch": "main"})
        assert inner.workflow_inputs["branch"] == "main"


class TestCronTrigger:
    """Tests for CronTrigger and CronTriggerInner."""

    def _make_inner(self, **kwargs) -> CronTriggerInner:
        defaults = {
            "name": "daily-review",
            "description": "Run daily at midnight",
            "type": "CronTrigger",
            "schedule": "0 0 * * *",
            "workflow": "daily_review",
        }
        defaults.update(kwargs)
        return CronTriggerInner(**defaults)

    def test_full_construction(self):
        inner = self._make_inner()
        trigger = CronTrigger(trigger=inner)
        assert trigger.trigger.schedule == "0 0 * * *"
        assert trigger.trigger.type == "CronTrigger"

    def test_defaults(self):
        inner = self._make_inner()
        assert inner.timezone == "UTC"
        assert inner.skip_on_holiday is True
        assert inner.skip_if_recent_execution is True
        assert (
            inner.min_hours_between_runs == 168
        )  # SECONDS_PER_WEEK // SECONDS_PER_HOUR

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            self._make_inner(type="EventTrigger")

    def test_custom_timezone(self):
        inner = self._make_inner(timezone="America/New_York")
        assert inner.timezone == "America/New_York"

    def test_min_hours_between_runs_gt0(self):
        with pytest.raises(ValidationError):
            self._make_inner(min_hours_between_runs=0)

    def test_workflow_inputs_defaults_empty(self):
        inner = self._make_inner()
        assert inner.workflow_inputs == {}


class TestThresholdTrigger:
    """Tests for ThresholdTrigger and ThresholdTriggerInner."""

    def _make_metric(self) -> MetricConfig:
        return MetricConfig(source="prometheus", query="rate(errors_total[5m])")

    def _make_inner(self, **kwargs) -> ThresholdTriggerInner:
        defaults = {
            "name": "error-rate-alert",
            "description": "Alert on elevated error rate",
            "type": "ThresholdTrigger",
            "metric": self._make_metric(),
            "condition": "greater_than",
            "threshold": 0.05,
            "workflow": "incident_response",
        }
        defaults.update(kwargs)
        return ThresholdTriggerInner(**defaults)

    def test_full_construction(self):
        inner = self._make_inner()
        trigger = ThresholdTrigger(trigger=inner)
        assert trigger.trigger.threshold == 0.05
        assert trigger.trigger.type == "ThresholdTrigger"

    def test_valid_condition_greater_than(self):
        inner = self._make_inner(condition="greater_than")
        assert inner.condition == "greater_than"

    def test_valid_condition_less_than(self):
        inner = self._make_inner(condition="less_than")
        assert inner.condition == "less_than"

    def test_valid_condition_equals(self):
        inner = self._make_inner(condition="equals")
        assert inner.condition == "equals"

    def test_invalid_condition_raises(self):
        with pytest.raises(ValidationError):
            self._make_inner(condition="not_equal")

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            self._make_inner(type="CronTrigger")

    def test_duration_minutes_default(self):
        """duration_minutes defaults to MEDIUM_ITEM_LIMIT (10)."""
        inner = self._make_inner()
        assert inner.duration_minutes == 10

    def test_duration_minutes_gt0_enforced(self):
        with pytest.raises(ValidationError):
            self._make_inner(duration_minutes=0)

    def test_compound_conditions_none_by_default(self):
        inner = self._make_inner()
        assert inner.compound_conditions is None

    def test_with_compound_conditions_and(self):
        compound = CompoundConditions(
            operator="AND",
            conditions=[
                CompoundCondition(metric="error_rate", operator="gt", value=0.05),
                CompoundCondition(metric="traffic", operator="gt", value=100.0),
            ],
        )
        inner = self._make_inner(compound_conditions=compound)
        assert inner.compound_conditions is not None
        assert inner.compound_conditions.operator == "AND"
        assert len(inner.compound_conditions.conditions) == 2

    def test_with_compound_conditions_or(self):
        compound = CompoundConditions(
            operator="OR",
            conditions=[CompoundCondition(metric="cpu", operator="gt", value=0.9)],
        )
        inner = self._make_inner(compound_conditions=compound)
        assert inner.compound_conditions.operator == "OR"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
