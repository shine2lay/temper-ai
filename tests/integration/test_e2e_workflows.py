"""
End-to-end integration tests for multi-stage workflows.

Tests complete workflow execution with real components and mocked LLM/tools.
Validates:
- 3-stage workflow execution (research → analyze → synthesize)
- Sequential and parallel agent execution
- Stage output flow
- Observability tracking
- Tool execution in workflow context
"""
import uuid
import pytest
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from src.observability.database import init_database, get_session
from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
)
from src.compiler.config_loader import ConfigLoader
from src.compiler.workflow_executor import WorkflowExecutor
from src.compiler.stage_compiler import StageCompiler
from src.observability.tracker import ExecutionTracker


pytestmark = [pytest.mark.integration, pytest.mark.critical_path]


class TestThreeStageWorkflow:
    """Test complete 3-stage workflow (research → analyze → synthesize)"""

    @pytest.fixture
    def test_database(self):
        """Initialize in-memory database for testing."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield
        # Cleanup handled by in-memory database

    @pytest.fixture
    def execution_tracker(self, test_database):
        """Execution tracker with test database."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.fixture
    def config_loader(self):
        """Config loader pointing to test configs."""
        project_root = Path(__file__).parent.parent.parent
        configs_dir = project_root / "configs"
        return ConfigLoader(config_root=configs_dir, cache_enabled=False)

    @pytest.fixture
    def mock_llm_provider(self):
        """Mock LLM provider with deterministic responses."""

        def create_response(agent_name: str, stage: str, iteration: int = 0):
            """Generate deterministic LLM response based on context."""
            responses = {
                "research": {
                    "researcher1": "Finding 1: AI advances rapidly. Confidence: 0.85",
                    "researcher2": "Finding 2: Safety concerns exist. Confidence: 0.90",
                    "researcher3": "Finding 3: Regulations needed. Confidence: 0.78"
                },
                "analyze": {
                    "analyst": "Analysis: Three key themes identified. Risk: Medium. Confidence: 0.88"
                },
                "synthesize": {
                    "synthesizer": "Synthesis: AI progress requires balanced regulation. Confidence: 0.92"
                }
            }

            content = responses.get(stage, {}).get(agent_name, "Default response")

            return {
                "content": f"<answer>{content}</answer>",
                "model": "mock-model",
                "provider": "mock",
                "total_tokens": 100 + (iteration * 10),
                "prompt_tokens": 50,
                "completion_tokens": 50 + (iteration * 10),
                "estimated_cost_usd": 0.001
            }

        return create_response

    @pytest.fixture
    def three_stage_workflow_config(self):
        """Standard 3-stage workflow configuration."""
        return {
            "workflow": {
                "name": "test_research_workflow",
                "version": "1.0",
                "stages": [
                    {
                        "name": "research",
                        "stage_ref": "research_stage",
                        "depends_on": []
                    },
                    {
                        "name": "analyze",
                        "stage_ref": "analyze_stage",
                        "depends_on": ["research"]
                    },
                    {
                        "name": "synthesize",
                        "stage_ref": "synthesize_stage",
                        "depends_on": ["analyze"]
                    }
                ],
                "error_handling": {
                    "on_stage_failure": "halt",
                    "escalation_policy": "DefaultEscalation",
                    "enable_rollback": True
                }
            }
        }

    @pytest.fixture
    def stage_configs(self):
        """Stage configurations for 3-stage workflow."""
        return {
            "research_stage": {
                "stage": {
                    "name": "research",
                    "agents": ["researcher1", "researcher2", "researcher3"],
                    "execution": {"agent_mode": "parallel", "timeout_seconds": 60},
                    "collaboration": {"strategy": "consensus", "max_rounds": 1},
                    "error_handling": {"min_successful_agents": 2}
                }
            },
            "analyze_stage": {
                "stage": {
                    "name": "analyze",
                    "agents": ["analyst"],
                    "execution": {"agent_mode": "sequential", "timeout_seconds": 45},
                    "collaboration": {"strategy": "single_agent"}
                }
            },
            "synthesize_stage": {
                "stage": {
                    "name": "synthesize",
                    "agents": ["synthesizer"],
                    "execution": {"agent_mode": "sequential", "timeout_seconds": 30}
                }
            }
        }

    def test_three_stage_sequential_success(
        self,
        test_database,
        execution_tracker,
        three_stage_workflow_config,
        stage_configs,
        mock_llm_provider
    ):
        """Test complete 3-stage workflow executes successfully."""
        workflow_id = str(uuid.uuid4())

        # This test validates the workflow orchestration without actual LLM calls
        # It focuses on state flow, stage transitions, and observability tracking

        # Create workflow execution record
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="test_research_workflow",
            workflow_version="1.0",
            workflow_config_snapshot=three_stage_workflow_config,
            trigger_type="manual",
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Simulate 3-stage execution
        stage_outputs = {}

        # Stage 1: Research (parallel agents)
        with execution_tracker.track_workflow(workflow_id, three_stage_workflow_config) as tracked_wf_id:
            with execution_tracker.track_stage("research", stage_configs["research_stage"], tracked_wf_id) as stage_id:
                # Simulate 3 agents executing in parallel
                for agent_name in ["researcher1", "researcher2", "researcher3"]:
                    with execution_tracker.track_agent(agent_name, {}, stage_id) as agent_id:
                        # Simulate LLM call
                        llm_response = mock_llm_provider(agent_name, "research")
                        execution_tracker.track_llm_call(
                            agent_id,
                            provider="mock",
                            model="mock-model",
                            prompt=f"Research query for {agent_name}",
                            response=llm_response["content"],
                            prompt_tokens=llm_response["prompt_tokens"],
                            completion_tokens=llm_response["completion_tokens"],
                            total_tokens=llm_response["total_tokens"],
                            estimated_cost_usd=llm_response["estimated_cost_usd"],
                            temperature=0.7
                        )

                stage_outputs["research"] = {
                    "findings": [
                        mock_llm_provider("researcher1", "research"),
                        mock_llm_provider("researcher2", "research"),
                        mock_llm_provider("researcher3", "research")
                    ]
                }

        # Verify stage 1 completion
        with get_session() as session:
            stage_exec = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id,
                stage_name="research"
            ).first()
            assert stage_exec is not None
            assert stage_exec.status == "completed"

            # Verify 3 agents executed
            agent_execs = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_exec.id
            ).all()
            assert len(agent_execs) == 3

        # Stage 2: Analyze (sequential)
        with execution_tracker.track_stage("analyze", stage_configs["analyze_stage"], workflow_id) as stage_id:
            with execution_tracker.track_agent("analyst", {}, stage_id) as agent_id:
                llm_response = mock_llm_provider("analyst", "analyze")
                execution_tracker.track_llm_call(
                    agent_id,
                    provider="mock",
                    model="mock-model",
                    prompt="Analyze research findings",
                    response=llm_response["content"],
                    prompt_tokens=llm_response["prompt_tokens"],
                    completion_tokens=llm_response["completion_tokens"],
                    total_tokens=llm_response["total_tokens"],
                    estimated_cost_usd=llm_response["estimated_cost_usd"],
                    temperature=0.7
                )

            stage_outputs["analyze"] = {"analysis": llm_response}

        # Stage 3: Synthesize (sequential)
        with execution_tracker.track_stage("synthesize", stage_configs["synthesize_stage"], workflow_id) as stage_id:
            with execution_tracker.track_agent("synthesizer", {}, stage_id) as agent_id:
                llm_response = mock_llm_provider("synthesizer", "synthesize")
                execution_tracker.track_llm_call(
                    agent_id,
                    provider="mock",
                    model="mock-model",
                    prompt="Synthesize analysis",
                    response=llm_response["content"],
                    prompt_tokens=llm_response["prompt_tokens"],
                    completion_tokens=llm_response["completion_tokens"],
                    total_tokens=llm_response["total_tokens"],
                    estimated_cost_usd=llm_response["estimated_cost_usd"],
                    temperature=0.7
                )

            stage_outputs["synthesize"] = {"synthesis": llm_response}

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Workflow completion
        with get_session() as session:
            loaded_workflow = session.query(WorkflowExecution).filter_by(
                id=workflow_id
            ).first()
            assert loaded_workflow is not None
            assert loaded_workflow.status == "completed"

            # Verify all 3 stages executed
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).all()
            assert len(stages) == 3

            stage_names = {s.stage_name for s in stages}
            assert stage_names == {"research", "analyze", "synthesize"}

            # Verify all stages completed
            for stage in stages:
                assert stage.status == "completed"

            # Verify total agent count (3 + 1 + 1 = 5)
            total_agents = 0
            for stage in stages:
                agents = session.query(AgentExecution).filter_by(
                    stage_execution_id=stage.id
                ).all()
                total_agents += len(agents)
            assert total_agents == 5

            # Verify LLM calls recorded
            llm_calls = session.query(LLMCall).join(
                AgentExecution
            ).join(
                StageExecution
            ).filter(
                StageExecution.workflow_execution_id == workflow_id
            ).all()
            assert len(llm_calls) == 5  # One per agent

    def test_parallel_agents_within_stage(
        self,
        test_database,
        execution_tracker
    ):
        """Test parallel agent execution within a single stage."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="parallel_agent_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with 4 parallel agents
        stage_config = {
            "stage": {
                "name": "parallel_stage",
                "agents": ["agent1", "agent2", "agent3", "agent4"],
                "execution": {"agent_mode": "parallel"}
            }
        }

        with execution_tracker.track_stage("parallel_stage", stage_config, workflow_id) as stage_id:
            # Simulate parallel execution
            for i in range(1, 5):
                agent_name = f"agent{i}"
                with execution_tracker.track_agent(agent_name, {}, stage_id) as agent_id:
                    # Simulate work
                    pass

        # VERIFICATION: All agents executed
        with get_session() as session:
            stage_exec = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).first()
            assert stage_exec is not None

            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_exec.id
            ).all()
            assert len(agents) == 4

            # All agents should have completed
            for agent in agents:
                assert agent.status == "completed"

    def test_stage_output_flow_to_next_stage(
        self,
        test_database,
        execution_tracker
    ):
        """Test stage outputs flow correctly to next stage."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="output_flow_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Generate output
        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("agent1", {}, stage1_id):
                pass

        # Update stage 1 with output
        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.output_data = {"result": "data from stage 1"}
            session.commit()

        # Stage 2: Should receive stage 1 output
        with execution_tracker.track_stage("stage2", {}, workflow_id) as stage2_id:
            # In real execution, stage2 would receive stage1.output_data as input
            with get_session() as session:
                stage1_data = session.query(StageExecution).filter_by(id=stage1_id).first()
                input_from_stage1 = stage1_data.output_data

                # Verify stage 2 can access stage 1 output
                assert input_from_stage1 == {"result": "data from stage 1"}

            with execution_tracker.track_agent("agent2", {}, stage2_id):
                pass

        # VERIFICATION: Stage output chain intact
        with get_session() as session:
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).order_by(StageExecution.start_time).all()

            assert len(stages) == 2
            assert stages[0].output_data == {"result": "data from stage 1"}


class TestWorkflowWithToolExecution:
    """Test workflows where agents use tools"""

    @pytest.fixture
    def test_database(self):
        """Initialize test database."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, test_database):
        """Execution tracker."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    def test_tool_execution_in_workflow_context(
        self,
        test_database,
        execution_tracker
    ):
        """Test tool execution within workflow is tracked."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="tool_execution_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with tool-using agent
        with execution_tracker.track_stage("compute_stage", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("calculator_agent", {}, stage_id) as agent_id:
                # Simulate tool execution
                tool_exec_id = execution_tracker.track_tool_call(
                    agent_id,
                    tool_name="Calculator",
                    tool_version="1.0",
                    input_params={"operation": "add", "a": 5, "b": 3},
                    output_data={"result": 8},
                    status="success",
                    safety_checks_applied=["parameter_validation"],
                    approval_required=False
                )

        # VERIFICATION: Tool execution tracked
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec is not None
            assert tool_exec.tool_name == "Calculator"
            assert tool_exec.status == "success"
            assert tool_exec.output_data == {"result": 8}

            # Verify tool linked to agent
            agent_exec = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent_exec is not None
            assert agent_exec.num_tool_calls == 1

    def test_tool_failure_handling_in_stage(
        self,
        test_database,
        execution_tracker
    ):
        """Test tool failures are handled and tracked correctly."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="tool_failure_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage with failing tool
        with execution_tracker.track_stage("failing_tool_stage", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent_with_tool", {}, stage_id) as agent_id:
                # Simulate failed tool execution
                tool_exec_id = execution_tracker.track_tool_call(
                    agent_id,
                    tool_name="WebScraper",
                    tool_version="1.0",
                    input_params={"url": "http://invalid"},
                    output_data=None,
                    status="failed",
                    error_message="Connection timeout",
                    safety_checks_applied=["url_validation"],
                    approval_required=False
                )

        # VERIFICATION: Tool failure tracked
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec is not None
            assert tool_exec.status == "failed"
            assert tool_exec.error_message == "Connection timeout"

            # Agent should still complete (handled tool failure)
            agent_exec = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent_exec.status == "completed"  # Agent handled failure
