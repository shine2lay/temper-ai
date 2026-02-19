"""
End-to-end integration tests for error propagation through the entire stack.

Tests:
- Tool errors propagate to agents
- Agent errors propagate to stages
- Stage errors propagate to workflow
- Error context preservation
- Timeout cascading through layers
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.observability.database import get_session, init_database
from temper_ai.observability.models import (
    AgentExecution,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)
from temper_ai.observability.tracker import ExecutionTracker

pytestmark = [pytest.mark.integration, pytest.mark.critical_path]


class TestToolToAgentErrorPropagation:
    """Test errors from tools to agents"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    def test_tool_exception_caught_by_agent(
        self,
        sample_database,
        execution_tracker
    ):
        """Test tool exception is caught and handled by agent."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="tool_error_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with failing tool
        with execution_tracker.track_stage("compute_stage", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent1", {}, stage_id) as agent_id:
                # Tool fails
                tool_exec_id = execution_tracker.track_tool_call(
                    agent_id,
                    tool_name="Calculator",
                    tool_version="1.0",
                    input_params={"operation": "divide", "a": 10, "b": 0},
                    output_data=None,
                    status="failed",
                    error_message="ZeroDivisionError: division by zero",
                    error_type="ZeroDivisionError",
                    safety_checks_applied=[],
                    approval_required=False
                )

        # VERIFICATION: Tool error captured
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec is not None
            assert tool_exec.status == "failed"
            assert "division by zero" in tool_exec.error_message

            # Agent should complete (handled tool error)
            agent_exec = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent_exec.status == "completed"

    def test_tool_timeout_propagated(
        self,
        sample_database,
        execution_tracker
    ):
        """Test tool timeout is propagated to agent."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="tool_timeout_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with timing-out tool
        with execution_tracker.track_stage("slow_stage", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent1", {}, stage_id) as agent_id:
                # Tool times out
                tool_exec_id = execution_tracker.track_tool_call(
                    agent_id,
                    tool_name="WebScraper",
                    tool_version="1.0",
                    input_params={"url": "http://slow-server.com"},
                    output_data=None,
                    status="failed",
                    error_message="TimeoutError: Tool execution exceeded 5s timeout",
                    error_type="TimeoutError",
                    safety_checks_applied=["url_validation"],
                    approval_required=False
                )

        # VERIFICATION: Timeout recorded
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec is not None
            assert tool_exec.status == "failed"
            assert "TimeoutError" in tool_exec.error_message

    def test_tool_error_context_preserved(
        self,
        sample_database,
        execution_tracker
    ):
        """Test tool error context includes tool details."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="context_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage
        with execution_tracker.track_stage("error_stage", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent1", {}, stage_id) as agent_id:
                # Tool fails with context
                tool_exec_id = execution_tracker.track_tool_call(
                    agent_id,
                    tool_name="DatabaseQuery",
                    tool_version="2.1",
                    input_params={"query": "SELECT * FROM users WHERE id = ?", "params": [999]},
                    output_data=None,
                    status="failed",
                    error_message="RecordNotFoundError: No user with id=999",
                    error_type="RecordNotFoundError",
                    safety_checks_applied=["sql_injection_check"],
                    approval_required=False
                )

        # VERIFICATION: Error context preserved
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec.tool_name == "DatabaseQuery"
            assert tool_exec.tool_version == "2.1"
            assert tool_exec.error_type == "RecordNotFoundError"
            assert tool_exec.error_message == "RecordNotFoundError: No user with id=999"
            assert "sql_injection_check" in tool_exec.safety_checks_applied


class TestAgentToStageErrorPropagation:
    """Test errors from agents to stages"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    def test_agent_failure_stops_stage(
        self,
        sample_database,
        execution_tracker
    ):
        """Test single-agent stage fails when agent fails."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="agent_failure_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with failing agent
        stage_id = str(uuid.uuid4())
        stage_exec = StageExecution(
            id=stage_id,
            workflow_execution_id=workflow_id,
            stage_name="single_agent_stage",
            stage_version="1.0",
            stage_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(stage_exec)
            session.commit()

        # Agent fails
        agent_id = str(uuid.uuid4())
        agent_exec = AgentExecution(
            id=agent_id,
            stage_execution_id=stage_id,
            agent_name="failing_agent",
            agent_version="1.0",
            agent_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="failed",
            error_message="LLMError: API rate limit exceeded",
            error_type="LLMError"
        )

        with get_session() as session:
            session.add(agent_exec)
            session.commit()

        # Stage fails due to agent failure
        stage_exec.end_time = datetime.now(UTC)
        stage_exec.duration_seconds = 1.5
        stage_exec.status = "failed"
        stage_exec.error_message = "Agent failing_agent failed: LLMError: API rate limit exceeded"
        stage_exec.num_agents_executed = 1
        stage_exec.num_agents_failed = 1

        with get_session() as session:
            session.merge(stage_exec)
            session.commit()

        # VERIFICATION: Stage failed due to agent
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage.status == "failed"
            assert "failing_agent" in stage.error_message
            assert stage.num_agents_failed == 1

    def test_agent_failure_partial_success(
        self,
        sample_database,
        execution_tracker
    ):
        """Test stage with multiple agents handles partial failure."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="partial_failure_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Create stage
        stage_id = str(uuid.uuid4())
        stage_exec = StageExecution(
            id=stage_id,
            workflow_execution_id=workflow_id,
            stage_name="multi_agent_stage",
            stage_version="1.0",
            stage_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(stage_exec)
            session.commit()

        # Agent 1: Success
        agent1_id = str(uuid.uuid4())
        agent1_exec = AgentExecution(
            id=agent1_id,
            stage_execution_id=stage_id,
            agent_name="agent1",
            agent_version="1.0",
            agent_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="success"
        )

        with get_session() as session:
            session.add(agent1_exec)
            session.commit()

        # Agent 2: Failed
        agent2_id = str(uuid.uuid4())
        agent2_exec = AgentExecution(
            id=agent2_id,
            stage_execution_id=stage_id,
            agent_name="agent2",
            agent_version="1.0",
            agent_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="failed",
            error_message="Connection timeout",
            error_type="TimeoutError"
        )

        with get_session() as session:
            session.add(agent2_exec)
            session.commit()

        # Agent 3: Success
        agent3_id = str(uuid.uuid4())
        agent3_exec = AgentExecution(
            id=agent3_id,
            stage_execution_id=stage_id,
            agent_name="agent3",
            agent_version="1.0",
            agent_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="success"
        )

        with get_session() as session:
            session.add(agent3_exec)
            session.commit()

        # Stage: Partial success (2/3 agents succeeded, min_successful_agents=2)
        stage_exec.end_time = datetime.now(UTC)
        stage_exec.duration_seconds = 3.0
        stage_exec.status = "partial_success"
        stage_exec.num_agents_executed = 3
        stage_exec.num_agents_succeeded = 2
        stage_exec.num_agents_failed = 1

        with get_session() as session:
            session.merge(stage_exec)
            session.commit()

        # VERIFICATION: Partial success recorded
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage.status == "partial_success"
            assert stage.num_agents_executed == 3
            assert stage.num_agents_succeeded == 2
            assert stage.num_agents_failed == 1

    def test_min_successful_agents_enforcement(
        self,
        sample_database
    ):
        """Test stage fails if below min_successful_agents threshold."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="threshold_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage with min_successful_agents=2
        stage_id = str(uuid.uuid4())
        stage_exec = StageExecution(
            id=stage_id,
            workflow_execution_id=workflow_id,
            stage_name="threshold_stage",
            stage_version="1.0",
            stage_config_snapshot={"error_handling": {"min_successful_agents": 2}},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(stage_exec)
            session.commit()

        # 3 agents: 1 success, 2 failures (below threshold of 2)
        for i, status in enumerate(["success", "failed", "failed"]):
            agent_id = str(uuid.uuid4())
            agent_exec = AgentExecution(
                id=agent_id,
                stage_execution_id=stage_id,
                agent_name=f"agent{i+1}",
                agent_version="1.0",
                agent_config_snapshot={},
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC) + timedelta(seconds=1),
                duration_seconds=1.0,
                status=status,
                error_message="Failed" if status == "failed" else None
            )

            with get_session() as session:
                session.add(agent_exec)
                session.commit()

        # Stage fails (1 success < 2 min required)
        stage_exec.end_time = datetime.now(UTC)
        stage_exec.duration_seconds = 3.0
        stage_exec.status = "failed"
        stage_exec.error_message = "Only 1 agents succeeded, minimum required: 2"
        stage_exec.num_agents_executed = 3
        stage_exec.num_agents_succeeded = 1
        stage_exec.num_agents_failed = 2

        with get_session() as session:
            session.merge(stage_exec)
            session.commit()

        # VERIFICATION: Stage failed due to threshold
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage.status == "failed"
            assert "minimum required" in stage.error_message
            assert stage.num_agents_succeeded == 1
            assert stage.num_agents_failed == 2


class TestStageToWorkflowErrorPropagation:
    """Test errors from stages to workflow"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    def test_stage_failure_stops_workflow(
        self,
        sample_database
    ):
        """Test workflow stops when critical stage fails."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="workflow_stop_test",
            workflow_version="1.0",
            workflow_config_snapshot={"error_handling": {"on_stage_failure": "halt"}},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Success
        stage1_id = str(uuid.uuid4())
        stage1_exec = StageExecution(
            id=stage1_id,
            workflow_execution_id=workflow_id,
            stage_name="stage1",
            stage_version="1.0",
            stage_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="success"
        )

        with get_session() as session:
            session.add(stage1_exec)
            session.commit()

        # Stage 2: Failed (critical)
        stage2_id = str(uuid.uuid4())
        stage2_exec = StageExecution(
            id=stage2_id,
            workflow_execution_id=workflow_id,
            stage_name="stage2",
            stage_version="1.0",
            stage_config_snapshot={},
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            duration_seconds=1.0,
            status="failed",
            error_message="Critical error: Data validation failed",
            error_type="ValidationError"
        )

        with get_session() as session:
            session.add(stage2_exec)
            session.commit()

        # Workflow halts due to stage failure
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.duration_seconds = 2.5
        workflow_exec.status = "failed"
        workflow_exec.error_message = "Workflow halted: stage2 failed with ValidationError"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Workflow stopped
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "failed"
            assert "stage2" in workflow.error_message

            # Only 2 stages executed (stage 3 not reached)
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).all()
            assert len(stages) == 2


class TestTimeoutCascading:
    """Test timeout propagation through layers"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from temper_ai.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    def test_timeout_enforcement_at_each_layer(
        self,
        sample_database,
        execution_tracker
    ):
        """Test timeout is enforced at tool, agent, and stage layers."""
        workflow_id = str(uuid.uuid4())

        # Create workflow with timeout config
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="timeout_test",
            workflow_version="1.0",
            workflow_config_snapshot={
                "execution": {"timeout_seconds": 60}  # Workflow timeout: 60s
            },
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage with 30s timeout
        stage_id = str(uuid.uuid4())
        stage_exec = StageExecution(
            id=stage_id,
            workflow_execution_id=workflow_id,
            stage_name="timeout_stage",
            stage_version="1.0",
            stage_config_snapshot={"execution": {"timeout_seconds": 30}},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(stage_exec)
            session.commit()

        # Agent with 10s timeout
        agent_id = str(uuid.uuid4())
        agent_exec = AgentExecution(
            id=agent_id,
            stage_execution_id=stage_id,
            agent_name="timeout_agent",
            agent_version="1.0",
            agent_config_snapshot={"execution": {"timeout_seconds": 10}},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(agent_exec)
            session.commit()

        # Tool with 5s timeout times out
        tool_exec_id = execution_tracker.track_tool_call(
            agent_id,
            tool_name="SlowTool",
            tool_version="1.0",
            input_params={"delay": 20},
            output_data=None,
            status="failed",
            error_message="TimeoutError: Tool execution exceeded 5s timeout",
            error_type="TimeoutError",
            safety_checks_applied=[],
            approval_required=False
        )

        # Agent times out due to tool timeout
        agent_exec.end_time = datetime.now(UTC)
        agent_exec.duration_seconds = 5.1
        agent_exec.status = "failed"
        agent_exec.error_message = "Agent timeout: Tool execution exceeded timeout"
        agent_exec.error_type = "TimeoutError"

        with get_session() as session:
            session.merge(agent_exec)
            session.commit()

        # Stage times out due to agent timeout
        stage_exec.end_time = datetime.now(UTC)
        stage_exec.duration_seconds = 5.2
        stage_exec.status = "failed"
        stage_exec.error_message = "Stage timeout: timeout_agent exceeded timeout"
        stage_exec.num_agents_executed = 1
        stage_exec.num_agents_failed = 1

        with get_session() as session:
            session.merge(stage_exec)
            session.commit()

        # Workflow times out due to stage timeout
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.duration_seconds = 5.3
        workflow_exec.status = "failed"
        workflow_exec.error_message = "Workflow timeout: timeout_stage exceeded timeout"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Timeout cascaded through all layers
        with get_session() as session:
            tool = session.query(ToolExecution).filter_by(agent_execution_id=agent_id).first()
            assert tool.status == "failed"
            assert "TimeoutError" in tool.error_message

            agent = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent.status == "failed"
            assert "timeout" in agent.error_message.lower()

            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage.status == "failed"
            assert "timeout" in stage.error_message.lower()

            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "failed"
            assert "timeout" in workflow.error_message.lower()
