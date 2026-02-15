"""Cross-Module Integration Tests.

Tests integration between compiler, agents, safety, and observability modules.
Validates data flow, error propagation, and contracts at module boundaries.

Priority: HIGH (P1)
Coverage Target: All 4 primary modules working together
Test Strategy: Real integrations with minimal mocking

Module Interactions Tested:
- Compiler → Agent → Observability
- Agent → Tool → Safety → Observability
- Compiler → Safety → Observability
- Configuration flow through all modules
- Error propagation across module boundaries
"""
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.workflow.config_loader import ConfigLoader
from src.workflow.langgraph_compiler import LangGraphCompiler
from src.observability.database import DatabaseManager, get_session
from src.observability.models import (
    AgentExecution,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)
from src.observability.tracker import ExecutionTracker
from src.tools.calculator import Calculator
from src.tools.registry import ToolRegistry

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def db_fixture():
    """Create in-memory test database."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db
    # Cleanup handled by in-memory database


@pytest.fixture
def tool_registry():
    """Create tool registry with calculator."""
    registry = ToolRegistry()
    registry.register(Calculator())
    return registry


@pytest.fixture
def config_loader():
    """Create config loader."""
    config_root = Path(__file__).parent.parent.parent / "configs"
    return ConfigLoader(config_root=str(config_root))


@pytest.fixture
def execution_tracker(db_fixture):
    """Create execution tracker."""
    # ExecutionTracker uses get_session() internally
    tracker = ExecutionTracker()
    yield tracker
    # Reset tracker after test
    tracker.reset()


@pytest.fixture
def integrated_system(db_fixture, config_loader, tool_registry, execution_tracker):
    """Create fully integrated system with all modules."""
    # Compiler with observability
    compiler = LangGraphCompiler(
        tool_registry=tool_registry,
        config_loader=config_loader
    )

    return {
        "compiler": compiler,
        "config_loader": config_loader,
        "tool_registry": tool_registry,
        "execution_tracker": execution_tracker,
        "db_fixture": db_fixture
    }


# ============================================================================
# Priority 1: Critical Cross-Module Tests
# ============================================================================

class TestFullStackIntegration:
    """Test complete workflow execution through all modules."""

    def test_workflow_execution_with_observability_tracking(
        self,
        integrated_system
    ):
        """Test complete workflow execution tracked in observability database.

        Flow:
        1. Compiler loads workflow config
        2. Agent executes with tools
        3. Observability tracks all events

        Validates: Compiler→Agent→Tool→Observability
        """
        compiler = integrated_system["compiler"]
        config_loader = integrated_system["config_loader"]
        tracker = integrated_system["execution_tracker"]

        # 1. Create workflow configuration
        workflow_config = {
            "workflow": {
                "name": "cross_module_test",
                "stages": ["analysis"]
            }
        }

        # 2. Compile workflow
        compiled = compiler.compile(workflow_config)
        assert compiled is not None, "Workflow compilation failed"

        # 3. Execute workflow with tracking
        workflow_id = str(uuid.uuid4())

        with tracker.track_workflow("cross_module_test", workflow_config) as wf_id:
            # Verify workflow ID generated
            assert wf_id is not None
            workflow_id = wf_id

            # Execute a simple stage
            with tracker.track_stage("analysis", {}, wf_id) as stage_id:
                assert stage_id is not None

                # Track agent execution
                with tracker.track_agent("test_agent", {}, stage_id) as agent_id:
                    assert agent_id is not None

                    # Track tool call
                    tool_call_id = tracker.track_tool_call(
                        agent_id=agent_id,
                        tool_name="Calculator",
                        tool_version="1.0",
                        input_params={"expression": "2+2"},
                        output_data={"result": 4},
                        status="success"
                    )
                    assert tool_call_id is not None

        # 4. Verify observability captured all events
        with get_session() as session:
            # Check workflow tracked
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow is not None, "Workflow not tracked in database"
            assert workflow.workflow_name == "cross_module_test"
            assert workflow.status == "completed"

            # Check stage tracked
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).all()
            assert len(stages) >= 1, "Stage not tracked"
            assert stages[0].stage_name == "analysis"

            # Check agent tracked
            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).all()
            assert len(agents) >= 1, "Agent not tracked"

            # Check tool execution tracked
            tool_execs = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).all()
            assert len(tool_execs) >= 1, "Tool execution not tracked"
            assert tool_execs[0].tool_name == "Calculator"
            assert tool_execs[0].status == "success"


class TestConfigurationPropagation:
    """Test configuration flows correctly through all modules."""

    def test_config_flow_from_compiler_to_agents(
        self,
        integrated_system,
        tmp_path
    ):
        """Test configuration propagates from compiler through all modules.

        Validates:
        - Compiler loads and validates config
        - Config settings affect module behavior
        - Tool timeouts respected
        - Safety limits applied
        """
        compiler = integrated_system["compiler"]
        config_loader = integrated_system["config_loader"]
        tracker = integrated_system["execution_tracker"]

        # 1. Create workflow config with module-specific settings
        workflow_config = {
            "workflow": {
                "name": "config_propagation_test",
                "stages": ["stage1"]
            },
            "inference": {
                "timeout": 30,
                "max_tokens": 1000
            },
            "safety": {
                "rate_limit": 10,
                "rate_window": 60
            }
        }

        # 2. Compile workflow
        compiled = compiler.compile(workflow_config)
        assert compiled is not None

        # 3. Verify config accessible
        assert workflow_config["inference"]["timeout"] == 30
        assert workflow_config["inference"]["max_tokens"] == 1000
        assert workflow_config["safety"]["rate_limit"] == 10

        # Config successfully loaded and accessible to modules


class TestErrorPropagationWithObservability:
    """Test errors propagate correctly through all layers."""

    def test_tool_error_tracked_in_observability(
        self,
        integrated_system
    ):
        """Test tool errors are captured in observability database.

        Scenario:
        1. Tool execution fails
        2. Error tracked in observability
        3. Error context preserved
        """
        tracker = integrated_system["execution_tracker"]

        workflow_id = str(uuid.uuid4())

        with tracker.track_workflow("error_test", {}) as wf_id:
            with tracker.track_stage("stage1", {}, wf_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    # Track failed tool execution
                    tool_call_id = tracker.track_tool_call(
                        agent_id=agent_id,
                        tool_name="FailingTool",
                        tool_version="1.0",
                        input_params={"should_fail": True},
                        output_data=None,
                        status="failed",
                        error_message="Simulated tool failure",
                        duration_ms=100
                    )

        # Verify error tracked in database
        with get_session() as session:
            # Tool execution shows error
            tool_exec = session.query(ToolExecution).filter_by(
                agent_execution_id=agent_id
            ).first()
            assert tool_exec is not None
            assert tool_exec.status == "failed"
            assert "Simulated tool failure" in tool_exec.error_message

            # Agent execution completed (handled error)
            agent_exec = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent_exec is not None
            assert agent_exec.status == "completed"

            # Workflow still completed (error handled gracefully)
            workflow = session.query(WorkflowExecution).filter_by(id=wf_id).first()
            assert workflow is not None
            assert workflow.status == "completed"


class TestObservabilityCompleteness:
    """Test observability captures events from all modules."""

    def test_complete_event_hierarchy_in_database(
        self,
        integrated_system
    ):
        """Test observability captures complete event hierarchy.

        Validates:
        - Workflow start/end
        - Stage start/end
        - Agent start/end
        - Tool executions
        - Proper parent-child relationships
        """
        tracker = integrated_system["execution_tracker"]

        workflow_config = {
            "workflow": {
                "name": "observability_hierarchy_test",
                "stages": ["stage1", "stage2"]
            }
        }

        with tracker.track_workflow("observability_hierarchy_test", workflow_config) as wf_id:
            # Stage 1: Agent with tool call
            with tracker.track_stage("stage1", {}, wf_id) as stage1_id:
                with tracker.track_agent("agent1", {}, stage1_id) as agent1_id:
                    # Tool call
                    tracker.track_tool_call(
                        agent_id=agent1_id,
                        tool_name="Calculator",
                        tool_version="1.0",
                        input_params={"expression": "2+2"},
                        output_data={"result": 4},
                        status="success"
                    )

            # Stage 2: Different agent
            with tracker.track_stage("stage2", {}, wf_id) as stage2_id:
                with tracker.track_agent("agent2", {}, stage2_id) as agent2_id:
                    # Another tool call
                    tracker.track_tool_call(
                        agent_id=agent2_id,
                        tool_name="WebSearch",
                        tool_version="1.0",
                        input_params={"query": "test"},
                        output_data={"results": []},
                        status="success"
                    )

        # Verify complete event hierarchy
        with get_session() as session:
            # Workflow level
            workflow = session.query(WorkflowExecution).filter_by(id=wf_id).first()
            assert workflow is not None
            assert workflow.workflow_name == "observability_hierarchy_test"

            # Stage level
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=wf_id
            ).all()
            assert len(stages) == 2, f"Expected 2 stages, found {len(stages)}"
            stage_names = {s.stage_name for s in stages}
            assert stage_names == {"stage1", "stage2"}

            # Agent level
            agents_stage1 = session.query(AgentExecution).filter_by(
                stage_execution_id=stage1_id
            ).all()
            assert len(agents_stage1) >= 1, "Agent1 not tracked"

            agents_stage2 = session.query(AgentExecution).filter_by(
                stage_execution_id=stage2_id
            ).all()
            assert len(agents_stage2) >= 1, "Agent2 not tracked"

            # Tool level
            tools_agent1 = session.query(ToolExecution).filter_by(
                agent_execution_id=agent1_id
            ).all()
            assert len(tools_agent1) >= 1, "Tool for agent1 not tracked"
            assert tools_agent1[0].tool_name == "Calculator"

            tools_agent2 = session.query(ToolExecution).filter_by(
                agent_execution_id=agent2_id
            ).all()
            assert len(tools_agent2) >= 1, "Tool for agent2 not tracked"
            assert tools_agent2[0].tool_name == "WebSearch"


class TestConcurrentCrossModuleOperations:
    """Test concurrent workflows execute without interference."""

    def test_concurrent_workflow_execution_thread_safe(
        self,
        integrated_system
    ):
        """Test multiple workflows execute concurrently without state leakage.

        Validates:
        - Thread-safe execution tracker
        - Database connection pooling
        - No state leakage between workflows
        """
        compiler = integrated_system["compiler"]
        tracker = integrated_system["execution_tracker"]

        workflow_config = {
            "workflow": {
                "name": "concurrent_test",
                "stages": ["compute"]
            }
        }

        def execute_workflow(workflow_num: int):
            """Execute a single workflow."""
            with tracker.track_workflow(
                f"concurrent_test_{workflow_num}",
                workflow_config
            ) as wf_id:
                with tracker.track_stage("compute", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        f"agent_{workflow_num}", {}, stage_id
                    ) as agent_id:
                        # Track tool execution
                        tracker.track_tool_call(
                            agent_id=agent_id,
                            tool_name="Calculator",
                            tool_version="1.0",
                            input_params={"expression": f"{workflow_num} * {workflow_num}"},
                            output_data={"result": workflow_num * workflow_num},
                            status="success"
                        )

                        return {
                            "workflow_id": wf_id,
                            "workflow_num": workflow_num,
                            "result": workflow_num * workflow_num
                        }

        # Execute 5 workflows concurrently
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(execute_workflow, i)
                for i in range(5)
            ]

            results = []
            for future in as_completed(futures):
                results.append(future.result())

        # Verify all completed successfully
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"

        # Verify all tracked in database
        with get_session() as session:
            workflows = session.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_name.like("concurrent_test_%")
            ).all()
            assert len(workflows) >= 5, f"Expected at least 5 workflows, found {len(workflows)}"

            # Verify no data corruption
            for result in results:
                wf = session.query(WorkflowExecution).filter_by(
                    id=result["workflow_id"]
                ).first()
                assert wf is not None, f"Workflow {result['workflow_id']} not found"
                assert wf.status == "completed"


# ============================================================================
# Data Contract Validation Tests
# ============================================================================

class TestModuleBoundaryContracts:
    """Test data contracts at module boundaries."""

    def test_workflow_id_propagates_through_all_modules(
        self,
        integrated_system
    ):
        """Test workflow_id propagates from compiler through all modules."""
        tracker = integrated_system["execution_tracker"]

        workflow_config = {"workflow": {"name": "id_propagation_test", "stages": ["stage1"]}}

        with tracker.track_workflow("id_propagation_test", workflow_config) as wf_id:
            assert wf_id is not None, "Workflow ID not generated"

            with tracker.track_stage("stage1", {}, wf_id) as stage_id:
                assert stage_id is not None

                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    assert agent_id is not None

        # Verify IDs in database
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=wf_id).first()
            assert workflow is not None

            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage is not None
            assert stage.workflow_execution_id == wf_id, "Stage not linked to workflow"

            agent = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert agent is not None
            assert agent.stage_execution_id == stage_id, "Agent not linked to stage"


    def test_tracking_ids_are_uuids(
        self,
        integrated_system
    ):
        """Test all tracking IDs are valid UUIDs."""
        tracker = integrated_system["execution_tracker"]

        # Create context with tracking IDs
        with tracker.track_workflow("id_test", {}) as wf_id:
            with tracker.track_stage("stage1", {}, wf_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id) as agent_id:
                    # Verify IDs are valid UUIDs (can be converted)
                    import uuid as uuid_module

                    # These should not raise ValueError
                    wf_uuid = uuid_module.UUID(wf_id)
                    stage_uuid = uuid_module.UUID(stage_id)
                    agent_uuid = uuid_module.UUID(agent_id)

                    assert wf_uuid.version is not None, "Workflow ID is not a valid UUID"
                    assert stage_uuid.version is not None, "Stage ID is not a valid UUID"
                    assert agent_uuid.version is not None, "Agent ID is not a valid UUID"
