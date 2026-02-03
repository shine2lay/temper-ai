"""
Tests for observability hooks.
"""
import pytest

from src.observability.hooks import (
    get_tracker,
    set_tracker,
    reset_tracker,
    track_workflow,
    track_stage,
    track_agent,
    ExecutionHook
)
from src.observability.tracker import ExecutionTracker
from src.observability.database import init_database, get_session
from src.observability.models import WorkflowExecution, StageExecution, AgentExecution


@pytest.fixture(autouse=True)
def reset_global_tracker():
    """Reset global tracker before each test."""
    reset_tracker()
    yield
    reset_tracker()


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    from src.observability.database import _db_manager, _db_lock
    import src.observability.database as db_module
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


class TestGlobalTracker:
    """Tests for global tracker management."""

    def test_get_tracker_creates_instance(self):
        """Test that get_tracker creates a tracker instance."""
        tracker = get_tracker()
        assert tracker is not None
        assert isinstance(tracker, ExecutionTracker)

    def test_get_tracker_returns_same_instance(self):
        """Test that get_tracker returns same instance."""
        tracker1 = get_tracker()
        tracker2 = get_tracker()
        assert tracker1 is tracker2

    def test_set_tracker(self):
        """Test setting custom tracker."""
        custom_tracker = ExecutionTracker()
        set_tracker(custom_tracker)

        tracker = get_tracker()
        assert tracker is custom_tracker

    def test_reset_tracker(self):
        """Test resetting tracker."""
        tracker1 = get_tracker()
        reset_tracker()
        tracker2 = get_tracker()
        assert tracker1 is not tracker2


class TestWorkflowDecorator:
    """Tests for @track_workflow decorator."""

    def test_decorator_basic(self, db):
        """Test basic workflow decorator."""

        @track_workflow("test_workflow")
        def run_workflow(config):
            return "success"

        config = {"workflow": {"name": "test"}}
        result = run_workflow(config)

        assert result == "success"

        # Verify workflow tracked
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(
                workflow_name="test_workflow"
            ).first()
            assert wf is not None
            assert wf.status == "completed"

    def test_decorator_extracts_function_name(self, db):
        """Test decorator uses function name if no name provided."""

        @track_workflow()
        def my_custom_workflow(config):
            return "success"

        result = my_custom_workflow({})

        # Should use function name "my_custom_workflow"
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(
                workflow_name="my_custom_workflow"
            ).first()
            assert wf is not None

    def test_decorator_injects_workflow_id(self, db):
        """Test that decorator injects workflow_id if function accepts it."""

        @track_workflow("test")
        def run_workflow(config, workflow_id=None):
            assert workflow_id is not None
            return workflow_id

        workflow_id = run_workflow({})
        assert workflow_id is not None

        # Verify it's a valid workflow_id
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf is not None

    def test_decorator_handles_exceptions(self, db):
        """Test that decorator handles exceptions properly."""

        @track_workflow("failing_workflow")
        def run_workflow(config):
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            run_workflow({})

        # Verify workflow marked as failed
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(
                workflow_name="failing_workflow"
            ).first()
            assert wf.status == "failed"
            assert wf.error_message == "Test error"


class TestStageDecorator:
    """Tests for @track_stage decorator."""

    def test_decorator_basic(self, db):
        """Test basic stage decorator."""

        @track_workflow("test_wf")
        def run_workflow(config, workflow_id=None):
            @track_stage("test_stage")
            def run_stage(stage_config, workflow_id):
                return "success"

            return run_stage({}, workflow_id)

        result = run_workflow({})
        assert result == "success"

        # Verify stage tracked
        with get_session() as session:
            st = session.query(StageExecution).filter_by(
                stage_name="test_stage"
            ).first()
            assert st is not None
            assert st.status == "completed"

    def test_decorator_injects_stage_id(self, db):
        """Test that decorator injects stage_id if function accepts it."""

        @track_workflow("test_wf")
        def run_workflow(config, workflow_id=None):
            @track_stage("test_stage")
            def run_stage(stage_config, workflow_id, stage_id=None):
                assert stage_id is not None
                return stage_id

            return run_stage({}, workflow_id)

        stage_id = run_workflow({})
        assert stage_id is not None

        # Verify it's a valid stage_id
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st is not None


class TestAgentDecorator:
    """Tests for @track_agent decorator."""

    def test_decorator_basic(self, db):
        """Test basic agent decorator."""

        @track_workflow("test_wf")
        def run_workflow(config, workflow_id=None):
            @track_stage("test_stage")
            def run_stage(stage_config, workflow_id, stage_id=None):
                @track_agent("test_agent")
                def run_agent(agent_config, stage_id):
                    return "success"

                return run_agent({}, stage_id)

            return run_stage({}, workflow_id)

        result = run_workflow({})
        assert result == "success"

        # Verify agent tracked
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(
                agent_name="test_agent"
            ).first()
            assert ag is not None
            assert ag.status == "completed"

    def test_decorator_injects_agent_id(self, db):
        """Test that decorator injects agent_id if function accepts it."""

        @track_workflow("test_wf")
        def run_workflow(config, workflow_id=None):
            @track_stage("test_stage")
            def run_stage(stage_config, workflow_id, stage_id=None):
                @track_agent("test_agent")
                def run_agent(agent_config, stage_id, agent_id=None):
                    assert agent_id is not None
                    return agent_id

                return run_agent({}, stage_id)

            return run_stage({}, workflow_id)

        agent_id = run_workflow({})
        assert agent_id is not None

        # Verify it's a valid agent_id
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag is not None


class TestExecutionHook:
    """Tests for ExecutionHook class."""

    def test_hook_workflow_lifecycle(self, db):
        """Test workflow lifecycle with ExecutionHook."""
        hook = ExecutionHook()

        # Start workflow
        workflow_id = hook.start_workflow("test_workflow", {})
        assert workflow_id is not None

        # Verify running
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf.status == "running"

        # End workflow
        hook.end_workflow(workflow_id)

        # Verify completed
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf.status == "completed"

    def test_hook_workflow_with_error(self, db):
        """Test workflow lifecycle with error."""
        hook = ExecutionHook()

        workflow_id = hook.start_workflow("test_workflow", {})
        hook.end_workflow(workflow_id, error=ValueError("Test error"))

        # Verify failed
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf.status == "failed"
            assert wf.error_message == "Test error"

    def test_hook_stage_lifecycle(self, db):
        """Test stage lifecycle with ExecutionHook."""
        hook = ExecutionHook()

        workflow_id = hook.start_workflow("test_wf", {})
        stage_id = hook.start_stage("test_stage", {}, workflow_id)
        assert stage_id is not None

        # Verify running
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st.status == "running"

        hook.end_stage(stage_id)

        # Verify completed
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st.status == "completed"

        hook.end_workflow(workflow_id)

    def test_hook_agent_lifecycle(self, db):
        """Test agent lifecycle with ExecutionHook."""
        hook = ExecutionHook()

        workflow_id = hook.start_workflow("test_wf", {})
        stage_id = hook.start_stage("test_stage", {}, workflow_id)
        agent_id = hook.start_agent("test_agent", {}, stage_id)
        assert agent_id is not None

        # Verify running
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.status == "running"

        hook.end_agent(agent_id)

        # Verify completed
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.status == "completed"

        hook.end_stage(stage_id)
        hook.end_workflow(workflow_id)

    def test_hook_llm_call(self, db):
        """Test logging LLM call with ExecutionHook."""
        hook = ExecutionHook()

        workflow_id = hook.start_workflow("test_wf", {})
        stage_id = hook.start_stage("test_stage", {}, workflow_id)
        agent_id = hook.start_agent("test_agent", {}, stage_id)

        llm_call_id = hook.log_llm_call(
            agent_id,
            "ollama",
            "llama3.2:3b",
            "Hello",
            "Hi there!",
            10,
            5,
            250,
            0.001
        )

        assert llm_call_id is not None

        # Verify LLM call recorded
        with get_session() as session:
            from src.observability.models import LLMCall
            llm_call = session.query(LLMCall).filter_by(id=llm_call_id).first()
            assert llm_call is not None
            assert llm_call.agent_execution_id == agent_id
            assert llm_call.provider == "ollama"

        hook.end_agent(agent_id)
        hook.end_stage(stage_id)
        hook.end_workflow(workflow_id)

    def test_hook_tool_call(self, db):
        """Test logging tool call with ExecutionHook."""
        hook = ExecutionHook()

        workflow_id = hook.start_workflow("test_wf", {})
        stage_id = hook.start_stage("test_stage", {}, workflow_id)
        agent_id = hook.start_agent("test_agent", {}, stage_id)

        tool_id = hook.log_tool_call(
            agent_id,
            "calculator",
            {"operation": "add"},
            {"result": 3},
            0.01
        )

        assert tool_id is not None

        # Verify tool call recorded
        with get_session() as session:
            from src.observability.models import ToolExecution
            tool_exec = session.query(ToolExecution).filter_by(id=tool_id).first()
            assert tool_exec is not None
            assert tool_exec.agent_execution_id == agent_id
            assert tool_exec.tool_name == "calculator"

        hook.end_agent(agent_id)
        hook.end_stage(stage_id)
        hook.end_workflow(workflow_id)

    def test_hook_full_execution(self, db):
        """Test complete execution with all levels."""
        hook = ExecutionHook()

        # Start workflow
        workflow_id = hook.start_workflow("full_test", {})

        # Start stage
        stage_id = hook.start_stage("stage1", {}, workflow_id)

        # Start agent
        agent_id = hook.start_agent("agent1", {}, stage_id)

        # Log LLM and tool calls
        hook.log_llm_call(
            agent_id, "ollama", "llama3.2:3b",
            "prompt", "response", 100, 50, 300, 0.005
        )
        hook.log_tool_call(
            agent_id, "tool1", {}, {}, 0.1
        )

        # End agent
        hook.end_agent(agent_id)

        # End stage
        hook.end_stage(stage_id)

        # End workflow
        hook.end_workflow(workflow_id)

        # Verify full hierarchy
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf.status == "completed"

            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st.status == "completed"

            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.status == "completed"
            assert ag.num_llm_calls == 1
            assert ag.num_tool_calls == 1


class TestCustomTracker:
    """Tests for using custom tracker."""

    def test_hook_with_custom_tracker(self, db):
        """Test ExecutionHook with custom tracker."""
        custom_tracker = ExecutionTracker()
        hook = ExecutionHook(tracker=custom_tracker)

        workflow_id = hook.start_workflow("test", {})
        hook.end_workflow(workflow_id)

        # Verify workflow tracked
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf is not None

    def test_decorator_with_custom_global_tracker(self, db):
        """Test decorator with custom global tracker."""
        custom_tracker = ExecutionTracker()
        set_tracker(custom_tracker)

        @track_workflow("test")
        def run_workflow(config):
            return "success"

        run_workflow({})

        # Verify workflow tracked
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(
                workflow_name="test"
            ).first()
            assert wf is not None


class TestParameterInspection:
    """Verify decorators only inject into actual parameters, not local variables.

    The decorators use inspect.signature() to determine if a function
    accepts the injected parameter. Local variables with the same name
    should NOT be overwritten.
    """

    def test_workflow_injects_when_parameter(self, db):
        """workflow_id is injected when it's a function parameter."""
        received = {}

        @track_workflow("test")
        def run(config, workflow_id=None):
            received["workflow_id"] = workflow_id

        run({})
        assert received["workflow_id"] is not None

    def test_workflow_skips_when_local_variable(self, db):
        """workflow_id local variable is NOT overwritten by injection."""
        received = {}

        @track_workflow("test")
        def run(config):
            workflow_id = "my_local_value"  # noqa: F841
            received["workflow_id"] = workflow_id

        run({})
        assert received["workflow_id"] == "my_local_value"

    def test_workflow_no_parameter_no_error(self, db):
        """No workflow_id parameter or local — no error, no injection."""
        @track_workflow("test")
        def run(config):
            return "ok"

        assert run({}) == "ok"

    def test_stage_injects_when_parameter(self, db):
        """stage_id is injected when it's a function parameter."""
        received = {}
        tracker = get_tracker()

        # Create a real workflow so FK constraint is satisfied
        with tracker.track_workflow("parent_wf", {}) as wf_id:
            @track_stage("test")
            def run(config, workflow_id=None, stage_id=None):
                received["stage_id"] = stage_id

            run({}, workflow_id=wf_id)

        assert received["stage_id"] is not None

    def test_stage_skips_when_local_variable(self, db):
        """stage_id local variable is NOT overwritten by injection."""
        received = {}
        tracker = get_tracker()

        with tracker.track_workflow("parent_wf", {}) as wf_id:
            @track_stage("test")
            def run(config, workflow_id=None):
                stage_id = "my_local_stage"  # noqa: F841
                received["stage_id"] = stage_id

            run({}, workflow_id=wf_id)

        assert received["stage_id"] == "my_local_stage"

    def test_agent_injects_when_parameter(self, db):
        """agent_id is injected when it's a function parameter."""
        received = {}
        tracker = get_tracker()

        with tracker.track_workflow("parent_wf", {}) as wf_id:
            with tracker.track_stage("parent_st", {}, wf_id) as st_id:
                @track_agent("test")
                def run(config, stage_id=None, agent_id=None):
                    received["agent_id"] = agent_id

                run({}, stage_id=st_id)

        assert received["agent_id"] is not None

    def test_agent_skips_when_local_variable(self, db):
        """agent_id local variable is NOT overwritten by injection."""
        received = {}
        tracker = get_tracker()

        with tracker.track_workflow("parent_wf", {}) as wf_id:
            with tracker.track_stage("parent_st", {}, wf_id) as st_id:
                @track_agent("test")
                def run(config, stage_id=None):
                    agent_id = "my_local_agent"  # noqa: F841
                    received["agent_id"] = agent_id

                run({}, stage_id=st_id)

        assert received["agent_id"] == "my_local_agent"

    def test_workflow_no_injection_for_kwargs_only(self, db):
        """Function with only **kwargs does not get workflow_id injected.

        inspect.signature() correctly identifies **kwargs as VAR_KEYWORD,
        not as a named 'workflow_id' parameter.
        """
        received = {}

        @track_workflow("test")
        def run(config, **kwargs):
            received["kwargs"] = kwargs

        run({})
        # **kwargs parameter does not match 'workflow_id' in signature
        assert "workflow_id" not in received["kwargs"]
