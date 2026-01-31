"""Tests for observability database models."""
import pytest
from datetime import datetime
from sqlmodel import Session, select

from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
    AgentMeritScore,
    DecisionOutcome,
    SystemMetric,
)
from src.observability.database import DatabaseManager


@pytest.fixture
def db_manager():
    """Create a test database manager."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()
    yield manager
    manager.drop_all_tables()


@pytest.fixture
def session(db_manager):
    """Create a test session."""
    with db_manager.session() as s:
        yield s


def test_workflow_execution_creation(session: Session):
    """Test creating a workflow execution."""
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_version="1.0.0",
        workflow_config_snapshot={"param1": "value1"},
        status="running",
        optimization_target="cost",
        environment="development",
    )
    session.add(workflow)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
    assert result is not None
    assert result.workflow_name == "test_workflow"
    assert result.workflow_version == "1.0.0"
    assert result.status == "running"
    assert result.workflow_config_snapshot == {"param1": "value1"}
    assert result.optimization_target == "cost"


def test_stage_execution_creation(session: Session):
    """Test creating a stage execution."""
    # Create parent workflow first
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.commit()

    # Create stage
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_version="1.0.0",
        stage_config_snapshot={"agent_count": 3},
        status="running",
        input_data={"query": "test query"},
    )
    session.add(stage)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(StageExecution).where(StageExecution.id == "stage-001")).first()
    assert result is not None
    assert result.stage_name == "research_stage"
    assert result.workflow_execution_id == "wf-001"
    assert result.stage_config_snapshot == {"agent_count": 3}
    assert result.input_data == {"query": "test query"}


def test_agent_execution_creation(session: Session):
    """Test creating an agent execution."""
    # Create parent workflow and stage
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.commit()

    # Create agent
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_version="1.0.0",
        agent_config_snapshot={"temperature": 0.7},
        status="running",
        input_data={"task": "research topic"},
        total_tokens=1000,
        prompt_tokens=800,
        completion_tokens=200,
        estimated_cost_usd=0.05,
    )
    session.add(agent)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(AgentExecution).where(AgentExecution.id == "agent-001")).first()
    assert result is not None
    assert result.agent_name == "researcher_agent"
    assert result.stage_execution_id == "stage-001"
    assert result.total_tokens == 1000
    assert result.estimated_cost_usd == 0.05


def test_llm_call_creation(session: Session):
    """Test creating an LLM call."""
    # Create parent hierarchy
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.add(agent)
    session.commit()

    # Create LLM call
    llm_call = LLMCall(
        id="llm-001",
        agent_execution_id="agent-001",
        provider="openai",
        model="gpt-4",
        prompt="Test prompt",
        response="Test response",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        estimated_cost_usd=0.001,
        status="success",
        temperature=0.7,
        latency_ms=500,
    )
    session.add(llm_call)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(LLMCall).where(LLMCall.id == "llm-001")).first()
    assert result is not None
    assert result.provider == "openai"
    assert result.model == "gpt-4"
    assert result.total_tokens == 30
    assert result.status == "success"


def test_tool_execution_creation(session: Session):
    """Test creating a tool execution."""
    # Create parent hierarchy
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.add(agent)
    session.commit()

    # Create tool execution
    tool = ToolExecution(
        id="tool-001",
        agent_execution_id="agent-001",
        tool_name="web_scraper",
        tool_version="1.0.0",
        input_params={"url": "https://example.com"},
        output_data={"content": "scraped data"},
        status="success",
        duration_seconds=2.5,
        safety_checks_applied=["url_validation"],
    )
    session.add(tool)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(ToolExecution).where(ToolExecution.id == "tool-001")).first()
    assert result is not None
    assert result.tool_name == "web_scraper"
    assert result.status == "success"
    assert result.duration_seconds == 2.5
    assert result.input_params == {"url": "https://example.com"}


def test_collaboration_event_creation(session: Session):
    """Test creating a collaboration event."""
    # Create parent hierarchy
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.commit()

    # Create collaboration event
    event = CollaborationEvent(
        id="event-001",
        stage_execution_id="stage-001",
        event_type="vote",
        agents_involved=["agent-001", "agent-002", "agent-003"],
        event_data={"votes": {"option_a": 2, "option_b": 1}},
        resolution_strategy="majority",
        outcome="option_a",
        confidence_score=0.67,
    )
    session.add(event)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(CollaborationEvent).where(CollaborationEvent.id == "event-001")).first()
    assert result is not None
    assert result.event_type == "vote"
    assert result.outcome == "option_a"
    assert result.confidence_score == 0.67
    assert len(result.agents_involved) == 3


def test_agent_merit_score_creation(session: Session):
    """Test creating an agent merit score."""
    merit = AgentMeritScore(
        id="merit-001",
        agent_name="researcher_agent",
        domain="market_research",
        total_decisions=100,
        successful_decisions=85,
        failed_decisions=10,
        overridden_decisions=5,
        success_rate=0.85,
        average_confidence=0.82,
        expertise_score=0.84,
        last_30_days_success_rate=0.87,
        last_90_days_success_rate=0.85,
    )
    session.add(merit)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(AgentMeritScore).where(AgentMeritScore.id == "merit-001")).first()
    assert result is not None
    assert result.agent_name == "researcher_agent"
    assert result.domain == "market_research"
    assert result.success_rate == 0.85
    assert result.total_decisions == 100


def test_decision_outcome_creation(session: Session):
    """Test creating a decision outcome."""
    # Create parent hierarchy
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.add(agent)
    session.commit()

    # Create decision outcome
    outcome = DecisionOutcome(
        id="outcome-001",
        agent_execution_id="agent-001",
        workflow_execution_id="wf-001",
        decision_type="synthesis",
        decision_data={"chosen_option": "option_a", "rationale": "best fit"},
        validation_method="user_feedback",
        outcome="success",
        impact_metrics={"accuracy": 0.95, "user_satisfaction": 4.5},
        should_repeat=True,
        tags=["high_quality", "validated"],
    )
    session.add(outcome)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(DecisionOutcome).where(DecisionOutcome.id == "outcome-001")).first()
    assert result is not None
    assert result.decision_type == "synthesis"
    assert result.outcome == "success"
    assert result.should_repeat is True
    assert len(result.tags) == 2


def test_system_metric_creation(session: Session):
    """Test creating a system metric."""
    metric = SystemMetric(
        id="metric-001",
        metric_name="avg_workflow_duration",
        metric_value=125.5,
        metric_unit="seconds",
        workflow_name="test_workflow",
        environment="production",
        aggregation_period="hour",
        tags={"region": "us-east-1"},
    )
    session.add(metric)
    session.commit()

    # Retrieve and verify
    result = session.exec(select(SystemMetric).where(SystemMetric.id == "metric-001")).first()
    assert result is not None
    assert result.metric_name == "avg_workflow_duration"
    assert result.metric_value == 125.5
    assert result.metric_unit == "seconds"
    assert result.tags["region"] == "us-east-1"


def test_relationships(session: Session):
    """Test relationships between models."""
    # Create hierarchy
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="running",
    )
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="running",
    )
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_config_snapshot={},
        status="running",
    )
    session.add(workflow)
    session.add(stage)
    session.add(agent)
    session.commit()

    # Test relationships
    wf = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
    assert len(wf.stages) == 1
    assert wf.stages[0].stage_name == "research_stage"

    st = session.exec(select(StageExecution).where(StageExecution.id == "stage-001")).first()
    assert st.workflow.workflow_name == "test_workflow"
    assert len(st.agents) == 1
    assert st.agents[0].agent_name == "researcher_agent"

    ag = session.exec(select(AgentExecution).where(AgentExecution.id == "agent-001")).first()
    assert ag.stage.stage_name == "research_stage"


def test_json_field_serialization(session: Session):
    """Test that JSON fields serialize/deserialize correctly."""
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "bool": True,
        },
        tags=["tag1", "tag2"],
        extra_metadata={"custom_field": "custom_value"},
        status="running",
    )
    session.add(workflow)
    session.commit()

    # Retrieve and verify JSON fields
    result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
    assert result.workflow_config_snapshot["nested"]["key"] == "value"
    assert result.workflow_config_snapshot["list"] == [1, 2, 3]
    assert result.workflow_config_snapshot["bool"] is True
    assert result.tags == ["tag1", "tag2"]
    assert result.extra_metadata["custom_field"] == "custom_value"
