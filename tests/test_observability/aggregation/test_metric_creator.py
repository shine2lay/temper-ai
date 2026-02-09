"""Comprehensive tests for MetricRecordCreator.

Tests cover:
- Workflow, agent, and LLM metric creation
- Conditional metric creation (value > 0)
- Success rate calculation
- Tag construction
- Metric naming and units
- Edge cases (zero values, null fields)
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.observability.aggregation.metric_creator import MetricRecordCreator
from src.observability.aggregation.period import AggregationPeriod


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = Mock()
    session.add = Mock()
    return session


@pytest.fixture
def creator(mock_session):
    """Create MetricRecordCreator with mock session."""
    return MetricRecordCreator(mock_session)


@pytest.fixture
def timestamp():
    """Standard timestamp for tests."""
    return datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


class TestMetricRecordCreatorInit:
    """Test creator initialization."""

    def test_init_stores_session(self, mock_session):
        """Creator stores session reference."""
        creator = MetricRecordCreator(mock_session)

        assert creator.session is mock_session


class TestWorkflowMetricCreation:
    """Test workflow metric creation."""

    def test_create_workflow_metrics_all_metrics(self, creator, mock_session, timestamp):
        """Creates all workflow metrics when values > 0."""
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 5.5
        mock_result.total_cost = 0.25
        mock_result.p95_duration = 8.0

        with patch('src.database.models.SystemMetric') as MockMetric:
            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 4 metrics: success_rate, avg_duration, total_cost, p95_duration
        assert len(metric_ids) == 4
        assert mock_session.add.call_count == 4
        assert all(mid.startswith('metric-') for mid in metric_ids)

    def test_create_workflow_metrics_success_rate_calculation(self, creator, mock_session, timestamp):
        """Calculates success rate correctly."""
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 10
        mock_result.successful = 7
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.p95_duration = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            mock_metric_instance = Mock()
            MockMetric.return_value = mock_metric_instance

            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create only success_rate metric
        assert len(metric_ids) == 1

        # Check success rate calculation (7/10 = 0.7)
        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_name'] == 'workflow_success_rate'
        assert call_kwargs['metric_value'] == 0.7
        assert call_kwargs['metric_unit'] == 'ratio'
        assert call_kwargs['workflow_name'] == 'test_workflow'
        assert call_kwargs['tags'] == {'total': 10, 'successful': 7}

    def test_create_workflow_metrics_zero_total_no_success_rate(self, creator, mock_session, timestamp):
        """Does not create success_rate metric when total is 0."""
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 0
        mock_result.successful = 0
        mock_result.avg_duration = 5.0
        mock_result.total_cost = 0
        mock_result.p95_duration = 0

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should only create avg_duration metric
        assert len(metric_ids) == 1

    def test_create_workflow_metrics_partial_values(self, creator, mock_session, timestamp):
        """Creates only metrics with values > 0."""
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 5
        mock_result.successful = 5
        mock_result.avg_duration = 3.2
        mock_result.total_cost = 0  # Zero - should not create
        mock_result.p95_duration = 0  # Zero - should not create

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 2 metrics: success_rate, avg_duration
        assert len(metric_ids) == 2

    def test_create_workflow_metrics_null_values(self, creator, mock_session, timestamp):
        """Handles null values from query results."""
        mock_result = Mock()
        mock_result.workflow_name = None
        mock_result.total = None
        mock_result.successful = None
        mock_result.avg_duration = None
        mock_result.total_cost = None
        mock_result.p95_duration = None

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create no metrics (all values are 0 after conversion)
        assert len(metric_ids) == 0

    def test_create_workflow_metrics_unknown_workflow_name(self, creator, mock_session, timestamp):
        """Uses 'unknown' for null workflow name."""
        mock_result = Mock()
        mock_result.workflow_name = None
        mock_result.total = 5
        mock_result.successful = 4
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.p95_duration = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['workflow_name'] == 'unknown'

    def test_create_workflow_metrics_different_periods(self, creator, mock_session, timestamp):
        """Creates metrics with different aggregation periods."""
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 5.0
        mock_result.total_cost = 0.5
        mock_result.p95_duration = 7.0

        for period in [AggregationPeriod.MINUTE, AggregationPeriod.HOUR, AggregationPeriod.DAY]:
            with patch('src.database.models.SystemMetric') as MockMetric:
                creator.create_workflow_metrics(mock_result, period, timestamp)

                call_kwargs = MockMetric.call_args[1]
                assert call_kwargs['aggregation_period'] == period.value


class TestAgentMetricCreation:
    """Test agent metric creation."""

    def test_create_agent_metrics_all_metrics(self, creator, mock_session, timestamp):
        """Creates all agent metrics when values > 0."""
        mock_result = Mock()
        mock_result.agent_name = "test_agent"
        mock_result.total = 15
        mock_result.successful = 12
        mock_result.avg_duration = 2.5
        mock_result.total_cost = 0.15
        mock_result.avg_tokens = 150.0

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 4 metrics: success_rate, avg_duration, total_cost, avg_tokens
        assert len(metric_ids) == 4

    def test_create_agent_metrics_success_rate_calculation(self, creator, mock_session, timestamp):
        """Calculates agent success rate correctly."""
        mock_result = Mock()
        mock_result.agent_name = "test_agent"
        mock_result.total = 20
        mock_result.successful = 18
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.avg_tokens = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_name'] == 'agent_success_rate'
        assert call_kwargs['metric_value'] == 0.9  # 18/20
        assert call_kwargs['metric_unit'] == 'ratio'
        assert call_kwargs['agent_name'] == 'test_agent'

    def test_create_agent_metrics_partial_values(self, creator, mock_session, timestamp):
        """Creates only metrics with values > 0."""
        mock_result = Mock()
        mock_result.agent_name = "test_agent"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 1.5
        mock_result.total_cost = 0  # Zero
        mock_result.avg_tokens = 0  # Zero

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 2 metrics: success_rate, avg_duration
        assert len(metric_ids) == 2

    def test_create_agent_metrics_null_agent_name(self, creator, mock_session, timestamp):
        """Uses 'unknown' for null agent name."""
        mock_result = Mock()
        mock_result.agent_name = None
        mock_result.total = 5
        mock_result.successful = 4
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.avg_tokens = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['agent_name'] == 'unknown'

    def test_create_agent_metrics_tags(self, creator, mock_session, timestamp):
        """Creates appropriate tags for agent metrics."""
        mock_result = Mock()
        mock_result.agent_name = "test_agent"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 2.0
        mock_result.total_cost = 0
        mock_result.avg_tokens = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Check tags for avg_duration metric (second call)
        call_kwargs_list = [call[1] for call in MockMetric.call_args_list]
        duration_metric = [c for c in call_kwargs_list if c['metric_name'] == 'agent_avg_duration'][0]
        assert duration_metric['tags'] == {'total': 10}


class TestLLMMetricCreation:
    """Test LLM metric creation."""

    def test_create_llm_metrics_all_metrics(self, creator, mock_session, timestamp):
        """Creates all LLM metrics when values > 0."""
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-4"
        mock_result.total = 25
        mock_result.successful = 24
        mock_result.avg_latency = 500.0
        mock_result.p95_latency = 800.0
        mock_result.p99_latency = 950.0
        mock_result.total_cost = 0.50

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 5 metrics: success_rate, avg_latency, p95_latency, p99_latency, total_cost
        assert len(metric_ids) == 5

    def test_create_llm_metrics_success_rate_calculation(self, creator, mock_session, timestamp):
        """Calculates LLM success rate correctly."""
        mock_result = Mock()
        mock_result.provider = "anthropic"
        mock_result.model = "claude-3-opus"
        mock_result.total = 30
        mock_result.successful = 29
        mock_result.avg_latency = 0
        mock_result.p95_latency = 0
        mock_result.p99_latency = 0
        mock_result.total_cost = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_name'] == 'llm_success_rate'
        assert abs(call_kwargs['metric_value'] - 0.9667) < 0.001  # 29/30
        assert call_kwargs['tags']['provider'] == 'anthropic'
        assert call_kwargs['tags']['model'] == 'claude-3-opus'

    def test_create_llm_metrics_latency_metrics(self, creator, mock_session, timestamp):
        """Creates latency metrics with correct units."""
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-4"
        mock_result.total = 10
        mock_result.successful = 10
        mock_result.avg_latency = 450.0
        mock_result.p95_latency = 700.0
        mock_result.p99_latency = 850.0
        mock_result.total_cost = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs_list = [call[1] for call in MockMetric.call_args_list]

        avg_latency = [c for c in call_kwargs_list if c['metric_name'] == 'llm_avg_latency'][0]
        assert avg_latency['metric_value'] == 450.0
        assert avg_latency['metric_unit'] == 'ms'

        p95_latency = [c for c in call_kwargs_list if c['metric_name'] == 'llm_p95_latency'][0]
        assert p95_latency['metric_value'] == 700.0
        assert p95_latency['metric_unit'] == 'ms'

        p99_latency = [c for c in call_kwargs_list if c['metric_name'] == 'llm_p99_latency'][0]
        assert p99_latency['metric_value'] == 850.0
        assert p99_latency['metric_unit'] == 'ms'

    def test_create_llm_metrics_partial_values(self, creator, mock_session, timestamp):
        """Creates only metrics with values > 0."""
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-3.5-turbo"
        mock_result.total = 15
        mock_result.successful = 14
        mock_result.avg_latency = 300.0
        mock_result.p95_latency = 0  # Zero
        mock_result.p99_latency = 0  # Zero
        mock_result.total_cost = 0  # Zero

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create 2 metrics: success_rate, avg_latency
        assert len(metric_ids) == 2

    def test_create_llm_metrics_unknown_provider_model(self, creator, mock_session, timestamp):
        """Uses 'unknown' for null provider/model."""
        mock_result = Mock()
        mock_result.provider = None
        mock_result.model = None
        mock_result.total = 5
        mock_result.successful = 5
        mock_result.avg_latency = 0
        mock_result.p95_latency = 0
        mock_result.p99_latency = 0
        mock_result.total_cost = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['tags']['provider'] == 'unknown'
        assert call_kwargs['tags']['model'] == 'unknown'


class TestCreateMetricHelper:
    """Test _create_metric helper method."""

    def test_create_metric_basic(self, creator, mock_session, timestamp):
        """Creates metric with basic parameters."""
        with patch('src.database.models.SystemMetric') as MockMetric:
            mock_metric = Mock()
            MockMetric.return_value = mock_metric

            metric_id = creator._create_metric(
                metric_name="test_metric",
                metric_value=42.5,
                metric_unit="ms",
                period=AggregationPeriod.HOUR,
                timestamp=timestamp
            )

        assert metric_id.startswith('metric-')
        assert len(metric_id) == 19  # "metric-" + 12 hex chars

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_name'] == 'test_metric'
        assert call_kwargs['metric_value'] == 42.5
        assert call_kwargs['metric_unit'] == 'ms'
        assert call_kwargs['timestamp'] == timestamp
        assert call_kwargs['aggregation_period'] == 'hour'
        assert call_kwargs['tags'] == {}

        mock_session.add.assert_called_once_with(mock_metric)

    def test_create_metric_with_dimensions(self, creator, mock_session, timestamp):
        """Creates metric with workflow/stage/agent dimensions."""
        with patch('src.database.models.SystemMetric') as MockMetric:
            creator._create_metric(
                metric_name="test_metric",
                metric_value=10.0,
                metric_unit="ratio",
                period=AggregationPeriod.DAY,
                timestamp=timestamp,
                workflow_name="test_wf",
                stage_name="stage_1",
                agent_name="agent_a"
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['workflow_name'] == 'test_wf'
        assert call_kwargs['stage_name'] == 'stage_1'
        assert call_kwargs['agent_name'] == 'agent_a'

    def test_create_metric_with_tags(self, creator, mock_session, timestamp):
        """Creates metric with custom tags."""
        tags = {'provider': 'openai', 'model': 'gpt-4', 'total': 100}

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator._create_metric(
                metric_name="test_metric",
                metric_value=0.95,
                metric_unit="ratio",
                period=AggregationPeriod.HOUR,
                timestamp=timestamp,
                tags=tags
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['tags'] == tags

    def test_create_metric_no_commit(self, creator, mock_session, timestamp):
        """Does not commit - caller must commit."""
        with patch('src.database.models.SystemMetric'):
            creator._create_metric(
                metric_name="test_metric",
                metric_value=1.0,
                metric_unit="seconds",
                period=AggregationPeriod.MINUTE,
                timestamp=timestamp
            )

        # Verify session.commit was NOT called
        mock_session.commit.assert_not_called()

    def test_create_metric_unique_ids(self, creator, mock_session, timestamp):
        """Generates unique IDs for each metric."""
        metric_ids = []

        with patch('src.database.models.SystemMetric'):
            for _ in range(10):
                metric_id = creator._create_metric(
                    metric_name="test_metric",
                    metric_value=1.0,
                    metric_unit="count",
                    period=AggregationPeriod.HOUR,
                    timestamp=timestamp
                )
                metric_ids.append(metric_id)

        # All IDs should be unique
        assert len(set(metric_ids)) == 10


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_perfect_success_rate(self, creator, mock_session, timestamp):
        """Handles 100% success rate correctly."""
        mock_result = Mock()
        mock_result.workflow_name = "perfect_workflow"
        mock_result.total = 50
        mock_result.successful = 50
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.p95_duration = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_value'] == 1.0

    def test_zero_success_rate(self, creator, mock_session, timestamp):
        """Handles 0% success rate correctly."""
        mock_result = Mock()
        mock_result.agent_name = "failing_agent"
        mock_result.total = 20
        mock_result.successful = 0
        mock_result.avg_duration = 0
        mock_result.total_cost = 0
        mock_result.avg_tokens = 0

        with patch('src.database.models.SystemMetric') as MockMetric:
            creator.create_agent_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        call_kwargs = MockMetric.call_args[1]
        assert call_kwargs['metric_value'] == 0.0

    def test_very_small_values(self, creator, mock_session, timestamp):
        """Handles very small metric values."""
        mock_result = Mock()
        mock_result.workflow_name = "micro_workflow"
        mock_result.total = 1000
        mock_result.successful = 999
        mock_result.avg_duration = 0.001  # 1ms
        mock_result.total_cost = 0.0001  # $0.0001
        mock_result.p95_duration = 0.002

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_workflow_metrics(
                mock_result,
                AggregationPeriod.HOUR,
                timestamp
            )

        # Should create all 4 metrics (all values > 0)
        assert len(metric_ids) == 4

    def test_large_values(self, creator, mock_session, timestamp):
        """Handles large metric values."""
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-4"
        mock_result.total = 1000000
        mock_result.successful = 999500
        mock_result.avg_latency = 5000.0
        mock_result.p95_latency = 10000.0
        mock_result.p99_latency = 15000.0
        mock_result.total_cost = 10000.0

        with patch('src.database.models.SystemMetric'):
            metric_ids = creator.create_llm_metrics(
                mock_result,
                AggregationPeriod.DAY,
                timestamp
            )

        # Should create all 5 metrics
        assert len(metric_ids) == 5
