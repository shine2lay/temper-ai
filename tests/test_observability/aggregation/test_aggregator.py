"""Comprehensive tests for AggregationOrchestrator.

Tests cover:
- Workflow, agent, and LLM metric aggregation
- Time-window filtering
- Transaction management (commit/rollback)
- Empty result handling
- Multi-workflow/agent aggregation
- Integration with MetricRecordCreator and QueryBuilder
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch

from src.observability.aggregation.aggregator import AggregationOrchestrator
from src.observability.aggregation.period import AggregationPeriod
from src.storage.database.models import WorkflowExecution, AgentExecution, LLMCall, SystemMetric


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = Mock()
    session.exec = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    return session


@pytest.fixture
def orchestrator(mock_session):
    """Create orchestrator with mock session."""
    return AggregationOrchestrator(mock_session)


@pytest.fixture
def time_window():
    """Standard time window for tests."""
    end_time = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
    start_time = end_time - timedelta(hours=1)
    return start_time, end_time


class TestAggregationOrchestratorInit:
    """Test orchestrator initialization."""

    def test_init_creates_metric_creator(self, mock_session):
        """Orchestrator initializes with MetricRecordCreator."""
        orchestrator = AggregationOrchestrator(mock_session)

        assert orchestrator.session is mock_session
        assert orchestrator._metric_creator is not None
        assert orchestrator._metric_creator.session is mock_session


class TestWorkflowMetricAggregation:
    """Test workflow metric aggregation."""

    def test_aggregate_workflow_metrics_basic(self, orchestrator, mock_session, time_window):
        """Aggregates workflow metrics successfully."""
        start_time, end_time = time_window

        # Mock query result
        mock_result = Mock()
        mock_result.workflow_name = "test_workflow"
        mock_result.total = 10
        mock_result.successful = 8
        mock_result.avg_duration = 5.5
        mock_result.total_cost = 0.25
        mock_result.p95_duration = 8.0

        mock_session.exec.return_value.all.return_value = [mock_result]

        # Mock metric creator
        with patch.object(orchestrator._metric_creator, 'create_workflow_metrics') as mock_create:
            mock_create.return_value = ['metric-abc123', 'metric-def456']

            result = orchestrator.aggregate_workflow_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 2
        assert result == ['metric-abc123', 'metric-def456']
        mock_session.commit.assert_called_once()
        mock_create.assert_called_once_with(mock_result, AggregationPeriod.HOUR, start_time)

    def test_aggregate_workflow_metrics_default_time_window(self, orchestrator, mock_session):
        """Uses default time window when not specified."""
        mock_session.exec.return_value.all.return_value = []

        with patch('src.observability.aggregation.aggregator.TimeWindowCalculator.get_default_time_window') as mock_window:
            mock_window.return_value = (
                datetime(2024, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
            )

            orchestrator.aggregate_workflow_metrics(period=AggregationPeriod.HOUR)

            mock_window.assert_called_once_with(AggregationPeriod.HOUR, None)

    def test_aggregate_workflow_metrics_empty_results(self, orchestrator, mock_session, time_window):
        """Handles empty query results."""
        start_time, end_time = time_window
        mock_session.exec.return_value.all.return_value = []

        result = orchestrator.aggregate_workflow_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        mock_session.commit.assert_called_once()

    def test_aggregate_workflow_metrics_multiple_workflows(self, orchestrator, mock_session, time_window):
        """Aggregates metrics for multiple workflows."""
        start_time, end_time = time_window

        # Mock multiple workflow results
        mock_result1 = Mock()
        mock_result1.workflow_name = "workflow_a"
        mock_result1.total = 5
        mock_result1.successful = 5
        mock_result1.avg_duration = 3.0
        mock_result1.total_cost = 0.10
        mock_result1.p95_duration = 4.5

        mock_result2 = Mock()
        mock_result2.workflow_name = "workflow_b"
        mock_result2.total = 8
        mock_result2.successful = 6
        mock_result2.avg_duration = 7.2
        mock_result2.total_cost = 0.35
        mock_result2.p95_duration = 10.0

        mock_session.exec.return_value.all.return_value = [mock_result1, mock_result2]

        with patch.object(orchestrator._metric_creator, 'create_workflow_metrics') as mock_create:
            mock_create.side_effect = [
                ['metric-1', 'metric-2'],
                ['metric-3', 'metric-4', 'metric-5']
            ]

            result = orchestrator.aggregate_workflow_metrics(
                period=AggregationPeriod.DAY,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 5
        assert mock_create.call_count == 2

    def test_aggregate_workflow_metrics_rollback_on_error(self, orchestrator, mock_session, time_window):
        """Rolls back transaction on error."""
        start_time, end_time = time_window
        mock_session.exec.side_effect = Exception("Database error")

        result = orchestrator.aggregate_workflow_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()


class TestAgentMetricAggregation:
    """Test agent metric aggregation."""

    def test_aggregate_agent_metrics_basic(self, orchestrator, mock_session, time_window):
        """Aggregates agent metrics successfully."""
        start_time, end_time = time_window

        # Mock query result
        mock_result = Mock()
        mock_result.agent_name = "test_agent"
        mock_result.total = 15
        mock_result.successful = 12
        mock_result.avg_duration = 2.5
        mock_result.total_cost = 0.15
        mock_result.avg_tokens = 150.0

        mock_session.exec.return_value.all.return_value = [mock_result]

        with patch.object(orchestrator._metric_creator, 'create_agent_metrics') as mock_create:
            mock_create.return_value = ['metric-agent1', 'metric-agent2']

            result = orchestrator.aggregate_agent_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 2
        mock_session.commit.assert_called_once()
        mock_create.assert_called_once_with(mock_result, AggregationPeriod.HOUR, start_time)

    def test_aggregate_agent_metrics_default_time_window(self, orchestrator, mock_session):
        """Uses default time window when not specified."""
        mock_session.exec.return_value.all.return_value = []

        with patch('src.observability.aggregation.aggregator.TimeWindowCalculator.get_default_time_window') as mock_window:
            mock_window.return_value = (
                datetime(2024, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
            )

            orchestrator.aggregate_agent_metrics(period=AggregationPeriod.HOUR)

            mock_window.assert_called_once_with(AggregationPeriod.HOUR, None)

    def test_aggregate_agent_metrics_multiple_agents(self, orchestrator, mock_session, time_window):
        """Aggregates metrics for multiple agents."""
        start_time, end_time = time_window

        mock_result1 = Mock()
        mock_result1.agent_name = "agent_a"
        mock_result1.total = 10
        mock_result1.successful = 9
        mock_result1.avg_duration = 1.5
        mock_result1.total_cost = 0.05
        mock_result1.avg_tokens = 100.0

        mock_result2 = Mock()
        mock_result2.agent_name = "agent_b"
        mock_result2.total = 20
        mock_result2.successful = 18
        mock_result2.avg_duration = 3.0
        mock_result2.total_cost = 0.20
        mock_result2.avg_tokens = 200.0

        mock_session.exec.return_value.all.return_value = [mock_result1, mock_result2]

        with patch.object(orchestrator._metric_creator, 'create_agent_metrics') as mock_create:
            mock_create.side_effect = [
                ['metric-a1', 'metric-a2'],
                ['metric-b1', 'metric-b2', 'metric-b3']
            ]

            result = orchestrator.aggregate_agent_metrics(
                period=AggregationPeriod.MINUTE,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 5

    def test_aggregate_agent_metrics_rollback_on_error(self, orchestrator, mock_session, time_window):
        """Rolls back transaction on error."""
        start_time, end_time = time_window
        mock_session.exec.side_effect = Exception("Query failed")

        result = orchestrator.aggregate_agent_metrics(
            period=AggregationPeriod.HOUR,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        mock_session.rollback.assert_called_once()


class TestLLMMetricAggregation:
    """Test LLM metric aggregation."""

    def test_aggregate_llm_metrics_basic(self, orchestrator, mock_session, time_window):
        """Aggregates LLM metrics successfully."""
        start_time, end_time = time_window

        # Mock query result
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-4"
        mock_result.total = 25
        mock_result.successful = 24
        mock_result.avg_latency = 500.0
        mock_result.p95_latency = 800.0
        mock_result.p99_latency = 950.0
        mock_result.total_cost = 0.50

        mock_session.exec.return_value.all.return_value = [mock_result]

        with patch.object(orchestrator._metric_creator, 'create_llm_metrics') as mock_create:
            mock_create.return_value = ['metric-llm1', 'metric-llm2', 'metric-llm3']

            result = orchestrator.aggregate_llm_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 3
        mock_session.commit.assert_called_once()
        mock_create.assert_called_once_with(mock_result, AggregationPeriod.HOUR, start_time)

    def test_aggregate_llm_metrics_multiple_providers(self, orchestrator, mock_session, time_window):
        """Aggregates metrics for multiple provider/model combinations."""
        start_time, end_time = time_window

        mock_result1 = Mock()
        mock_result1.provider = "openai"
        mock_result1.model = "gpt-4"
        mock_result1.total = 10
        mock_result1.successful = 10
        mock_result1.avg_latency = 400.0
        mock_result1.p95_latency = 600.0
        mock_result1.p99_latency = 700.0
        mock_result1.total_cost = 0.30

        mock_result2 = Mock()
        mock_result2.provider = "anthropic"
        mock_result2.model = "claude-3-opus"
        mock_result2.total = 15
        mock_result2.successful = 14
        mock_result2.avg_latency = 350.0
        mock_result2.p95_latency = 500.0
        mock_result2.p99_latency = 600.0
        mock_result2.total_cost = 0.45

        mock_session.exec.return_value.all.return_value = [mock_result1, mock_result2]

        with patch.object(orchestrator._metric_creator, 'create_llm_metrics') as mock_create:
            mock_create.side_effect = [
                ['metric-1', 'metric-2'],
                ['metric-3', 'metric-4']
            ]

            result = orchestrator.aggregate_llm_metrics(
                period=AggregationPeriod.DAY,
                start_time=start_time,
                end_time=end_time
            )

        assert len(result) == 4

    def test_aggregate_llm_metrics_rollback_on_error(self, orchestrator, mock_session, time_window):
        """Rolls back transaction on error."""
        start_time, end_time = time_window

        # Simulate error during metric creation
        mock_result = Mock()
        mock_result.provider = "openai"
        mock_result.model = "gpt-4"
        mock_session.exec.return_value.all.return_value = [mock_result]

        with patch.object(orchestrator._metric_creator, 'create_llm_metrics') as mock_create:
            mock_create.side_effect = Exception("Metric creation failed")

            result = orchestrator.aggregate_llm_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert result == []
        mock_session.rollback.assert_called_once()


class TestAggregateAllMetrics:
    """Test aggregate_all_metrics convenience method."""

    def test_aggregate_all_metrics_success(self, orchestrator, time_window):
        """Aggregates all metric types successfully."""
        start_time, end_time = time_window

        with patch.object(orchestrator, 'aggregate_workflow_metrics') as mock_workflow, \
             patch.object(orchestrator, 'aggregate_agent_metrics') as mock_agent, \
             patch.object(orchestrator, 'aggregate_llm_metrics') as mock_llm:

            mock_workflow.return_value = ['wf-1', 'wf-2']
            mock_agent.return_value = ['ag-1', 'ag-2', 'ag-3']
            mock_llm.return_value = ['llm-1']

            result = orchestrator.aggregate_all_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert result == {
            'workflow': ['wf-1', 'wf-2'],
            'agent': ['ag-1', 'ag-2', 'ag-3'],
            'llm': ['llm-1']
        }

        mock_workflow.assert_called_once_with(AggregationPeriod.HOUR, start_time, end_time)
        mock_agent.assert_called_once_with(AggregationPeriod.HOUR, start_time, end_time)
        mock_llm.assert_called_once_with(AggregationPeriod.HOUR, start_time, end_time)

    def test_aggregate_all_metrics_default_time_window(self, orchestrator):
        """Uses default time window when not specified."""
        with patch.object(orchestrator, 'aggregate_workflow_metrics') as mock_workflow, \
             patch.object(orchestrator, 'aggregate_agent_metrics') as mock_agent, \
             patch.object(orchestrator, 'aggregate_llm_metrics') as mock_llm:

            mock_workflow.return_value = []
            mock_agent.return_value = []
            mock_llm.return_value = []

            result = orchestrator.aggregate_all_metrics(period=AggregationPeriod.DAY)

        assert result == {'workflow': [], 'agent': [], 'llm': []}
        mock_workflow.assert_called_once_with(AggregationPeriod.DAY, None, None)

    def test_aggregate_all_metrics_partial_failures(self, orchestrator, time_window):
        """Handles partial failures gracefully."""
        start_time, end_time = time_window

        with patch.object(orchestrator, 'aggregate_workflow_metrics') as mock_workflow, \
             patch.object(orchestrator, 'aggregate_agent_metrics') as mock_agent, \
             patch.object(orchestrator, 'aggregate_llm_metrics') as mock_llm:

            # Workflow fails, others succeed
            mock_workflow.return_value = []  # Returns empty on error
            mock_agent.return_value = ['ag-1']
            mock_llm.return_value = ['llm-1', 'llm-2']

            result = orchestrator.aggregate_all_metrics(
                period=AggregationPeriod.HOUR,
                start_time=start_time,
                end_time=end_time
            )

        assert result == {
            'workflow': [],
            'agent': ['ag-1'],
            'llm': ['llm-1', 'llm-2']
        }


class TestPeriodVariations:
    """Test different aggregation periods."""

    def test_minute_period(self, orchestrator, mock_session):
        """Supports minute-level aggregation."""
        mock_session.exec.return_value.all.return_value = []

        end_time = datetime(2024, 1, 15, 14, 5, 0, tzinfo=timezone.utc)
        start_time = end_time - timedelta(minutes=1)

        result = orchestrator.aggregate_workflow_metrics(
            period=AggregationPeriod.MINUTE,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        mock_session.commit.assert_called_once()

    def test_day_period(self, orchestrator, mock_session):
        """Supports day-level aggregation."""
        mock_session.exec.return_value.all.return_value = []

        end_time = datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        start_time = end_time - timedelta(days=1)

        result = orchestrator.aggregate_agent_metrics(
            period=AggregationPeriod.DAY,
            start_time=start_time,
            end_time=end_time
        )

        assert result == []
        mock_session.commit.assert_called_once()
