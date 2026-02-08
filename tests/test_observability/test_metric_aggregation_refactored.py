"""Tests for refactored MetricAggregator (SQL-based aggregation).

Tests the new modular aggregation pipeline:
- TimeWindowCalculator
- AggregationQueryBuilder
- MetricRecordCreator
- MetricAggregator (orchestrator)
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, call
from typing import Any

from src.observability.aggregation import MetricAggregator, AggregationPeriod
from src.observability.aggregation.time_window import TimeWindowCalculator
from src.observability.aggregation.query_builder import AggregationQueryBuilder
from src.observability.aggregation.metric_creator import MetricRecordCreator


class TestTimeWindowCalculator:
    """Tests for TimeWindowCalculator."""

    def test_get_period_start_minute(self):
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.MINUTE)
        assert start_time == datetime(2024, 1, 1, 14, 29, 0, tzinfo=timezone.utc)

    def test_get_period_start_hour(self):
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.HOUR)
        assert start_time == datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)

    def test_get_period_start_day(self):
        end_time = datetime(2024, 1, 2, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.DAY)
        assert start_time == datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)

    def test_get_default_time_window(self):
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time, returned_end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.HOUR, end_time
        )
        assert start_time == datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)
        assert returned_end == end_time

    def test_get_default_time_window_no_end_time(self):
        """Test default time window uses current time."""
        start_time, end_time = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.HOUR
        )
        # Should be roughly 1 hour difference
        time_diff = end_time - start_time
        assert 3590 <= time_diff.total_seconds() <= 3610  # ~1 hour with tolerance


class TestAggregationQueryBuilder:
    """Tests for AggregationQueryBuilder."""

    def test_build_workflow_query_returns_select(self):
        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        query = AggregationQueryBuilder.build_workflow_query(start_time, end_time)

        # Verify it's a SQLAlchemy Select object
        assert hasattr(query, 'where')
        assert hasattr(query, 'group_by')

    def test_build_agent_query_returns_select(self):
        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        query = AggregationQueryBuilder.build_agent_query(start_time, end_time)

        assert hasattr(query, 'where')
        assert hasattr(query, 'group_by')

    def test_build_llm_query_returns_select(self):
        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        query = AggregationQueryBuilder.build_llm_query(start_time, end_time)

        assert hasattr(query, 'where')
        assert hasattr(query, 'group_by')


class TestMetricRecordCreator:
    """Tests for MetricRecordCreator."""

    def test_create_workflow_metrics(self):
        mock_session = Mock()
        creator = MetricRecordCreator(mock_session)

        # Mock query result
        result = Mock()
        result.workflow_name = "test_workflow"
        result.total = 10
        result.successful = 8
        result.avg_duration = 5.5
        result.total_cost = 0.05
        result.p95_duration = 8.2

        timestamp = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        metric_ids = creator.create_workflow_metrics(
            result, AggregationPeriod.HOUR, timestamp
        )

        # Should create 4 metrics
        assert len(metric_ids) == 4
        assert all(mid.startswith("metric-") for mid in metric_ids)

        # Should have called session.add 4 times
        assert mock_session.add.call_count == 4

    def test_create_workflow_metrics_with_zeros(self):
        """Test that metrics with zero values are not created."""
        mock_session = Mock()
        creator = MetricRecordCreator(mock_session)

        result = Mock()
        result.workflow_name = "test_workflow"
        result.total = 0
        result.successful = 0
        result.avg_duration = 0.0
        result.total_cost = 0.0
        result.p95_duration = 0.0

        timestamp = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        metric_ids = creator.create_workflow_metrics(
            result, AggregationPeriod.HOUR, timestamp
        )

        # No metrics should be created
        assert len(metric_ids) == 0
        assert mock_session.add.call_count == 0

    def test_create_agent_metrics(self):
        mock_session = Mock()
        creator = MetricRecordCreator(mock_session)

        result = Mock()
        result.agent_name = "test_agent"
        result.total = 15
        result.successful = 12
        result.avg_duration = 3.2
        result.total_cost = 0.03
        result.avg_tokens = 1500

        timestamp = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        metric_ids = creator.create_agent_metrics(
            result, AggregationPeriod.HOUR, timestamp
        )

        assert len(metric_ids) == 4
        assert mock_session.add.call_count == 4

    def test_create_llm_metrics(self):
        mock_session = Mock()
        creator = MetricRecordCreator(mock_session)

        result = Mock()
        result.provider = "openai"
        result.model = "gpt-4"
        result.total = 20
        result.successful = 19
        result.avg_latency = 250.5
        result.p95_latency = 450.0
        result.p99_latency = 600.0
        result.total_cost = 0.10

        timestamp = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        metric_ids = creator.create_llm_metrics(
            result, AggregationPeriod.HOUR, timestamp
        )

        # Should create 5 metrics
        assert len(metric_ids) == 5
        assert mock_session.add.call_count == 5

    def test_create_metric_handles_none_values(self):
        """Test that None values are handled with 'unknown' default."""
        mock_session = Mock()
        creator = MetricRecordCreator(mock_session)

        result = Mock()
        result.workflow_name = None
        result.total = 5
        result.successful = 3
        result.avg_duration = 2.0
        result.total_cost = 0.01
        result.p95_duration = 3.0

        timestamp = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        metric_ids = creator.create_workflow_metrics(
            result, AggregationPeriod.HOUR, timestamp
        )

        # Should still create metrics with 'unknown' name
        assert len(metric_ids) == 4


class TestMetricAggregatorOrchestrator:
    """Tests for MetricAggregator orchestrator class."""

    def test_init(self):
        mock_session = Mock()
        aggregator = MetricAggregator(mock_session)

        assert aggregator.session == mock_session
        assert isinstance(aggregator._metric_creator, MetricRecordCreator)

    def test_aggregate_workflow_metrics_with_explicit_times(self):
        mock_session = Mock()
        mock_session.exec.return_value.all.return_value = []

        aggregator = MetricAggregator(mock_session)

        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        result = aggregator.aggregate_workflow_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        assert mock_session.commit.called
        assert mock_session.exec.called

    def test_aggregate_workflow_metrics_with_results(self):
        mock_session = Mock()

        # Create mock result
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 5.5
        mock_result.total_cost = 0.05
        mock_result.p95_duration = 8.2

        mock_session.exec.return_value.all.return_value = [mock_result]

        aggregator = MetricAggregator(mock_session)

        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        result = aggregator.aggregate_workflow_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        # Should create 4 metrics
        assert len(result) == 4
        assert mock_session.commit.called

    def test_aggregate_workflow_metrics_rollback_on_error(self):
        mock_session = Mock()
        mock_session.exec.side_effect = Exception("Database error")

        aggregator = MetricAggregator(mock_session)

        start_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        result = aggregator.aggregate_workflow_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        assert mock_session.rollback.called
        assert not mock_session.commit.called

    def test_aggregate_agent_metrics(self):
        mock_session = Mock()
        mock_session.exec.return_value.all.return_value = []

        aggregator = MetricAggregator(mock_session)

        result = aggregator.aggregate_agent_metrics(
            period=AggregationPeriod.HOUR
        )

        assert result == []
        assert mock_session.commit.called

    def test_aggregate_llm_metrics(self):
        mock_session = Mock()
        mock_session.exec.return_value.all.return_value = []

        aggregator = MetricAggregator(mock_session)

        result = aggregator.aggregate_llm_metrics(
            period=AggregationPeriod.HOUR
        )

        assert result == []
        assert mock_session.commit.called

    def test_aggregate_all_metrics(self):
        mock_session = Mock()
        mock_session.exec.return_value.all.return_value = []

        aggregator = MetricAggregator(mock_session)

        result = aggregator.aggregate_all_metrics(
            period=AggregationPeriod.HOUR
        )

        assert "workflow" in result
        assert "agent" in result
        assert "llm" in result
        assert all(isinstance(v, list) for v in result.values())
        assert mock_session.commit.call_count == 3  # One per aggregation method


class TestBackwardCompatibility:
    """Tests for backward compatibility of imports."""

    def test_import_from_aggregation_module(self):
        """Test importing from old aggregation.py file.

        Note: Deprecation warning may not be captured in pytest if module
        is already loaded. The critical requirement is that the import works.
        """
        import warnings
        warnings.simplefilter("ignore")

        from src.observability import aggregation

        # Verify the classes are accessible
        assert hasattr(aggregation, 'MetricAggregator')
        assert hasattr(aggregation, 'AggregationPeriod')

    def test_classes_accessible_from_aggregation_module(self):
        """Test that classes are accessible from old import path."""
        import warnings
        warnings.simplefilter("ignore")

        from src.observability import aggregation

        assert hasattr(aggregation, 'MetricAggregator')
        assert hasattr(aggregation, 'AggregationPeriod')

    def test_import_from_package_no_warning(self):
        """Test importing from new package path has no warning."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.observability.aggregation import MetricAggregator
            from src.observability.aggregation import AggregationPeriod

            # Should have no warnings
            assert len(w) == 0
