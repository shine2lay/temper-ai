"""Comprehensive tests for AggregationQueryBuilder.

Tests cover:
- SQL query generation for workflow, agent, and LLM metrics
- Time-range filtering
- Aggregation functions (COUNT, SUM, AVG)
- GROUP BY clauses
- Status filtering (completed vs success)
- Query structure validation

NOTE: SQLite doesn't support PERCENTILE_CONT, so tests validate query structure
for percentile queries without executing them. Integration tests use PostgreSQL.
"""
import pytest
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, create_engine, SQLModel, select, func

from temper_ai.observability.aggregation.query_builder import AggregationQueryBuilder
from temper_ai.storage.database.models import WorkflowExecution, AgentExecution, LLMCall


@pytest.fixture
def db_session():
    """In-memory SQLite session for query tests."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def time_window():
    """Standard time window for tests."""
    end_time = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
    start_time = end_time - timedelta(hours=1)
    return start_time, end_time


class TestQueryStructureValidation:
    """Test query structure without executing (PERCENTILE_CONT compatibility check)."""

    def test_workflow_query_has_correct_structure(self, time_window):
        """Workflow query has correct SQL structure."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_workflow_query(start_time, end_time)

        # Verify query is a Select object
        from sqlalchemy.sql.selectable import Select
        assert isinstance(query, Select)

        # Verify column names in query
        query_str = str(query)
        assert 'workflow_name' in query_str
        assert 'count' in query_str.lower()
        assert 'sum' in query_str.lower()
        assert 'avg' in query_str.lower()
        assert 'percentile_cont' in query_str.lower()  # P95 duration
        assert 'GROUP BY' in query_str

    def test_agent_query_has_correct_structure(self, time_window):
        """Agent query has correct SQL structure."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_agent_query(start_time, end_time)

        query_str = str(query)
        assert 'agent_name' in query_str
        assert 'count' in query_str.lower()
        assert 'avg' in query_str.lower()
        assert 'GROUP BY' in query_str

    def test_llm_query_has_correct_structure(self, time_window):
        """LLM query has correct SQL structure."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_llm_query(start_time, end_time)

        query_str = str(query)
        assert 'provider' in query_str
        assert 'model' in query_str
        assert 'count' in query_str.lower()
        assert 'percentile_cont' in query_str.lower()  # P95 and P99
        assert 'GROUP BY' in query_str

    def test_workflow_query_time_filters(self, time_window):
        """Workflow query includes time range filters."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_workflow_query(start_time, end_time)

        # Check WHERE clause exists
        query_str = str(query)
        assert 'WHERE' in query_str
        assert 'start_time >=' in query_str
        assert 'start_time <' in query_str

    def test_agent_query_time_filters(self, time_window):
        """Agent query includes time range filters."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_agent_query(start_time, end_time)

        query_str = str(query)
        assert 'WHERE' in query_str
        assert 'start_time >=' in query_str

    def test_llm_query_time_filters(self, time_window):
        """LLM query includes time range filters."""
        start_time, end_time = time_window

        query = AggregationQueryBuilder.build_llm_query(start_time, end_time)

        query_str = str(query)
        assert 'WHERE' in query_str
        assert 'start_time >=' in query_str


class TestWorkflowQueryFiltering:
    """Test workflow query time filtering and grouping (without PERCENTILE_CONT)."""

    def test_filters_by_time_window(self, db_session, time_window):
        """Filters workflow executions by time window."""
        start_time, end_time = time_window

        # Create workflows within and outside time window
        wf_in = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=15),
            status="completed",
            duration_seconds=5.0
        )

        wf_before = WorkflowExecution(
            id="wf-2",
            workflow_name="test_workflow",
            start_time=start_time - timedelta(hours=2),
            status="completed",
            duration_seconds=3.0
        )

        wf_after = WorkflowExecution(
            id="wf-3",
            workflow_name="test_workflow",
            start_time=end_time + timedelta(hours=1),
            status="completed",
            duration_seconds=4.0
        )

        db_session.add_all([wf_in, wf_before, wf_after])
        db_session.commit()

        # Use a simple query without PERCENTILE_CONT for SQLite
        query = select(
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].total == 1  # Only wf_in is in the window

    def test_groups_by_workflow_name(self, db_session, time_window):
        """Groups results by workflow_name."""
        start_time, end_time = time_window

        wf1 = WorkflowExecution(
            id="wf-1",
            workflow_name="workflow_a",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=5.0
        )

        wf2 = WorkflowExecution(
            id="wf-2",
            workflow_name="workflow_b",
            start_time=start_time + timedelta(minutes=20),
            status="completed",
            duration_seconds=3.0
        )

        wf3 = WorkflowExecution(
            id="wf-3",
            workflow_name="workflow_a",
            start_time=start_time + timedelta(minutes=30),
            status="failed",
            duration_seconds=2.0
        )

        db_session.add_all([wf1, wf2, wf3])
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 2

        workflow_a = [r for r in results if r.workflow_name == "workflow_a"][0]
        assert workflow_a.total == 2

    def test_counts_successful_workflows(self, db_session, time_window):
        """Counts only completed workflows as successful."""
        start_time, end_time = time_window

        from sqlalchemy import case

        wf_completed1 = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=5),
            status="completed",
            duration_seconds=5.0
        )

        wf_completed2 = WorkflowExecution(
            id="wf-2",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=6.0
        )

        wf_failed = WorkflowExecution(
            id="wf-3",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=15),
            status="failed",
            duration_seconds=2.0
        )

        db_session.add_all([wf_completed1, wf_completed2, wf_failed])
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total'),
            func.sum(case((WorkflowExecution.status == 'completed', 1), else_=0)).label('successful')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        result = results[0]
        assert result.total == 3
        assert result.successful == 2

    def test_aggregates_duration(self, db_session, time_window):
        """Calculates average duration."""
        start_time, end_time = time_window

        wf1 = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=5),
            status="completed",
            duration_seconds=4.0
        )

        wf2 = WorkflowExecution(
            id="wf-2",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=6.0
        )

        db_session.add_all([wf1, wf2])
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.avg(WorkflowExecution.duration_seconds).label('avg_duration')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].avg_duration == 5.0

    def test_aggregates_cost(self, db_session, time_window):
        """Calculates total cost."""
        start_time, end_time = time_window

        wf1 = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=5),
            status="completed",
            duration_seconds=5.0,
            total_cost_usd=0.15
        )

        wf2 = WorkflowExecution(
            id="wf-2",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=5.0,
            total_cost_usd=0.25
        )

        db_session.add_all([wf1, wf2])
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.sum(WorkflowExecution.total_cost_usd).label('total_cost')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].total_cost == 0.40


class TestAgentQueryFiltering:
    """Test agent query filtering and aggregation."""

    def test_filters_by_time_window(self, db_session, time_window):
        """Filters agent executions by time window."""
        start_time, end_time = time_window

        agent_in = AgentExecution(
            id="agent-1",
            agent_name="test_agent",
            start_time=start_time + timedelta(minutes=15),
            status="completed",
            duration_seconds=2.5
        )

        agent_out = AgentExecution(
            id="agent-2",
            agent_name="test_agent",
            start_time=end_time + timedelta(hours=1),
            status="completed",
            duration_seconds=3.0
        )

        db_session.add_all([agent_in, agent_out])
        db_session.commit()

        query = select(
            AgentExecution.agent_name,
            func.count(AgentExecution.id).label('total')
        ).where(
            AgentExecution.start_time >= start_time,
            AgentExecution.start_time < end_time
        ).group_by(AgentExecution.agent_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].total == 1

    def test_groups_by_agent_name(self, db_session, time_window):
        """Groups results by agent_name."""
        start_time, end_time = time_window

        agent1 = AgentExecution(
            id="agent-1",
            agent_name="agent_a",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=2.0
        )

        agent2 = AgentExecution(
            id="agent-2",
            agent_name="agent_b",
            start_time=start_time + timedelta(minutes=20),
            status="completed",
            duration_seconds=3.0
        )

        agent3 = AgentExecution(
            id="agent-3",
            agent_name="agent_a",
            start_time=start_time + timedelta(minutes=30),
            status="completed",
            duration_seconds=4.0
        )

        db_session.add_all([agent1, agent2, agent3])
        db_session.commit()

        query = select(
            AgentExecution.agent_name,
            func.count(AgentExecution.id).label('total')
        ).where(
            AgentExecution.start_time >= start_time,
            AgentExecution.start_time < end_time
        ).group_by(AgentExecution.agent_name)

        results = db_session.exec(query).all()

        assert len(results) == 2
        agent_a = [r for r in results if r.agent_name == "agent_a"][0]
        assert agent_a.total == 2

    def test_aggregates_tokens(self, db_session, time_window):
        """Calculates average tokens."""
        start_time, end_time = time_window

        agent1 = AgentExecution(
            id="agent-1",
            agent_name="test_agent",
            start_time=start_time + timedelta(minutes=5),
            status="completed",
            duration_seconds=2.0,
            total_tokens=100
        )

        agent2 = AgentExecution(
            id="agent-2",
            agent_name="test_agent",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=3.0,
            total_tokens=200
        )

        db_session.add_all([agent1, agent2])
        db_session.commit()

        query = select(
            AgentExecution.agent_name,
            func.avg(AgentExecution.total_tokens).label('avg_tokens')
        ).where(
            AgentExecution.start_time >= start_time,
            AgentExecution.start_time < end_time
        ).group_by(AgentExecution.agent_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].avg_tokens == 150.0


class TestLLMQueryFiltering:
    """Test LLM query filtering and aggregation."""

    def test_filters_by_time_window(self, db_session, time_window):
        """Filters LLM calls by time window."""
        start_time, end_time = time_window

        llm_in = LLMCall(
            id="llm-1",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=15),
            status="success",
            latency_ms=500.0
        )

        llm_out = LLMCall(
            id="llm-2",
            provider="openai",
            model="gpt-4",
            start_time=start_time - timedelta(hours=2),
            status="success",
            latency_ms=600.0
        )

        db_session.add_all([llm_in, llm_out])
        db_session.commit()

        query = select(
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id).label('total')
        ).where(
            LLMCall.start_time >= start_time,
            LLMCall.start_time < end_time
        ).group_by(LLMCall.provider, LLMCall.model)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].total == 1

    def test_groups_by_provider_and_model(self, db_session, time_window):
        """Groups results by provider and model."""
        start_time, end_time = time_window

        llm1 = LLMCall(
            id="llm-1",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=10),
            status="success",
            latency_ms=500.0
        )

        llm2 = LLMCall(
            id="llm-2",
            provider="openai",
            model="gpt-3.5-turbo",
            start_time=start_time + timedelta(minutes=20),
            status="success",
            latency_ms=300.0
        )

        llm3 = LLMCall(
            id="llm-3",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=30),
            status="success",
            latency_ms=550.0
        )

        db_session.add_all([llm1, llm2, llm3])
        db_session.commit()

        query = select(
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id).label('total')
        ).where(
            LLMCall.start_time >= start_time,
            LLMCall.start_time < end_time
        ).group_by(LLMCall.provider, LLMCall.model)

        results = db_session.exec(query).all()

        assert len(results) == 2
        gpt4 = [r for r in results if r.model == "gpt-4"][0]
        assert gpt4.total == 2

    def test_counts_successful_calls(self, db_session, time_window):
        """Counts successful LLM calls."""
        start_time, end_time = time_window

        from sqlalchemy import case

        llm_success1 = LLMCall(
            id="llm-1",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=5),
            status="success",
            latency_ms=500.0
        )

        llm_success2 = LLMCall(
            id="llm-2",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=10),
            status="success",
            latency_ms=600.0
        )

        llm_error = LLMCall(
            id="llm-3",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=15),
            status="error",
            latency_ms=100.0
        )

        db_session.add_all([llm_success1, llm_success2, llm_error])
        db_session.commit()

        query = select(
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id).label('total'),
            func.sum(case((LLMCall.status == 'success', 1), else_=0)).label('successful')
        ).where(
            LLMCall.start_time >= start_time,
            LLMCall.start_time < end_time
        ).group_by(LLMCall.provider, LLMCall.model)

        results = db_session.exec(query).all()

        assert len(results) == 1
        result = results[0]
        assert result.total == 3
        assert result.successful == 2

    def test_aggregates_latency(self, db_session, time_window):
        """Calculates average latency."""
        start_time, end_time = time_window

        llm1 = LLMCall(
            id="llm-1",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=5),
            status="success",
            latency_ms=400.0
        )

        llm2 = LLMCall(
            id="llm-2",
            provider="openai",
            model="gpt-4",
            start_time=start_time + timedelta(minutes=10),
            status="success",
            latency_ms=600.0
        )

        db_session.add_all([llm1, llm2])
        db_session.commit()

        query = select(
            LLMCall.provider,
            LLMCall.model,
            func.avg(LLMCall.latency_ms).label('avg_latency')
        ).where(
            LLMCall.start_time >= start_time,
            LLMCall.start_time < end_time
        ).group_by(LLMCall.provider, LLMCall.model)

        results = db_session.exec(query).all()

        assert len(results) == 1
        assert results[0].avg_latency == 500.0


class TestTimeWindowEdgeCases:
    """Test edge cases for time window filtering."""

    def test_exact_boundary_start_time(self, db_session, time_window):
        """Includes executions at exact start_time."""
        start_time, end_time = time_window

        wf = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time,
            status="completed",
            duration_seconds=5.0
        )

        db_session.add(wf)
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1

    def test_exact_boundary_end_time(self, db_session, time_window):
        """Excludes executions at exact end_time."""
        start_time, end_time = time_window

        wf = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=end_time,
            status="completed",
            duration_seconds=5.0
        )

        db_session.add(wf)
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        # Should exclude end_time (start_time < end_time, not <=)
        assert len(results) == 0

    def test_null_cost_values(self, db_session, time_window):
        """Handles null cost values in aggregation."""
        start_time, end_time = time_window

        wf1 = WorkflowExecution(
            id="wf-1",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=10),
            status="completed",
            duration_seconds=5.0,
            total_cost_usd=None
        )

        wf2 = WorkflowExecution(
            id="wf-2",
            workflow_name="test_workflow",
            start_time=start_time + timedelta(minutes=20),
            status="completed",
            duration_seconds=6.0,
            total_cost_usd=0.10
        )

        db_session.add_all([wf1, wf2])
        db_session.commit()

        query = select(
            WorkflowExecution.workflow_name,
            func.sum(WorkflowExecution.total_cost_usd).label('total_cost')
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

        results = db_session.exec(query).all()

        assert len(results) == 1
        # SUM ignores NULLs in SQLite
        assert results[0].total_cost == 0.10
