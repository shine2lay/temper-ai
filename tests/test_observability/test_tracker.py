"""
Tests for ExecutionTracker.
"""

import pytest

from temper_ai.storage.database import get_session, init_database
from temper_ai.storage.database.models import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)
from temper_ai.observability.tracker import ExecutionTracker
from temper_ai.shared.core.context import ExecutionContext


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    import temper_ai.storage.database as db_module
    from temper_ai.storage.database.manager import _db_lock
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def tracker(db):
    """Create fresh tracker for each test."""
    return ExecutionTracker()


class TestExecutionContext:
    """Tests for ExecutionContext dataclass."""

    def test_context_initialization(self):
        """Test context initialization."""
        ctx = ExecutionContext()
        assert ctx.workflow_id is None
        assert ctx.stage_id is None
        assert ctx.agent_id is None

    def test_context_with_values(self):
        """Test context with values."""
        ctx = ExecutionContext(
            workflow_id="wf-123",
            stage_id="st-456",
            agent_id="ag-789"
        )
        assert ctx.workflow_id == "wf-123"
        assert ctx.stage_id == "st-456"
        assert ctx.agent_id == "ag-789"


class TestWorkflowTracking:
    """Tests for workflow tracking."""

    def test_track_workflow_success(self, tracker):
        """Test successful workflow tracking."""
        config = {"workflow": {"name": "test", "version": "1.0"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            assert workflow_id is not None
            assert isinstance(workflow_id, str)

        # Verify database record
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf is not None
            assert wf.workflow_name == "test_workflow"
            assert wf.status == "completed"
            assert wf.duration_seconds is not None
            assert wf.duration_seconds > 0

    def test_track_workflow_with_metadata(self, tracker):
        """Test workflow tracking with metadata."""
        config = {"workflow": {}}

        with tracker.track_workflow(
            "test",
            config,
            trigger_type="manual",
            trigger_data={"user": "test_user"},
            optimization_target="speed",
            product_type="research",
            environment="test",
            tags=["test", "demo"]
        ) as workflow_id:
            pass

        # Verify metadata stored
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf.trigger_type == "manual"
            assert wf.trigger_data["user"] == "test_user"
            assert wf.optimization_target == "speed"
            assert wf.product_type == "research"
            assert wf.environment == "test"
            assert "test" in wf.tags
            assert "demo" in wf.tags

    def test_track_workflow_failure(self, tracker):
        """Test workflow tracking with failure."""
        config = {}

        with pytest.raises(ValueError):
            with tracker.track_workflow("test", config) as workflow_id:
                raise ValueError("Test error")

        # Verify error recorded
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(
                workflow_name="test"
            ).first()
            assert wf is not None
            assert wf.status == "failed"
            assert wf.error_message == "Test error"
            assert wf.error_stack_trace is not None

    def test_workflow_sets_context(self, tracker):
        """Test that workflow tracking sets context."""
        config = {}

        assert tracker.context.workflow_id is None

        with tracker.track_workflow("test", config) as workflow_id:
            assert tracker.context.workflow_id == workflow_id

        assert tracker.context.workflow_id is None


class TestStageTracking:
    """Tests for stage tracking."""

    def test_track_stage_success(self, tracker):
        """Test successful stage tracking."""
        config_wf = {}
        config_st = {"stage": {"name": "test_stage", "version": "1.0"}}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_stage", config_st, workflow_id) as stage_id:
                assert stage_id is not None

        # Verify database record
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st is not None
            assert st.stage_name == "test_stage"
            assert st.workflow_execution_id == workflow_id
            assert st.status == "completed"
            assert st.duration_seconds is not None

    def test_track_stage_with_input_data(self, tracker):
        """Test stage tracking with input data."""
        config_wf = {}
        config_st = {}
        input_data = {"topic": "AI research", "depth": "deep"}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage(
                "research",
                config_st,
                workflow_id,
                input_data=input_data
            ) as stage_id:
                pass

        # Verify input data stored
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st.input_data == input_data

    def test_track_stage_failure(self, tracker):
        """Test stage tracking with failure."""
        config_wf = {}
        config_st = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with pytest.raises(RuntimeError):
                with tracker.track_stage("test_stage", config_st, workflow_id) as stage_id:
                    raise RuntimeError("Stage failed")

        # Verify error recorded
        with get_session() as session:
            st = session.query(StageExecution).filter_by(
                stage_name="test_stage"
            ).first()
            assert st.status == "failed"
            assert st.error_message == "Stage failed"

    def test_set_stage_output(self, tracker):
        """Test setting stage output data."""
        config_wf = {}
        config_st = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_stage", config_st, workflow_id) as stage_id:
                output_data = {"insights": ["finding1", "finding2"]}
                tracker.set_stage_output(stage_id, output_data)

        # Verify output stored
        with get_session() as session:
            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st.output_data == output_data


class TestAgentTracking:
    """Tests for agent tracking."""

    def test_track_agent_success(self, tracker):
        """Test successful agent tracking."""
        config_wf = {}
        config_st = {}
        config_ag = {"agent": {"name": "researcher", "version": "1.0"}}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    assert agent_id is not None

        # Verify database record
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag is not None
            assert ag.agent_name == "researcher"
            assert ag.stage_execution_id == stage_id
            assert ag.status == "completed"
            assert ag.duration_seconds is not None

    def test_track_agent_with_input(self, tracker):
        """Test agent tracking with input data."""
        config_wf = {}
        config_st = {}
        config_ag = {}
        input_data = {"task": "analyze topic"}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent(
                    "researcher",
                    config_ag,
                    stage_id,
                    input_data=input_data
                ) as agent_id:
                    pass

        # Verify input stored
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.input_data == input_data

    def test_set_agent_output(self, tracker):
        """Test setting agent output data."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    output_data = {"result": "success"}
                    reasoning = "Based on analysis..."
                    tracker.set_agent_output(
                        agent_id,
                        output_data,
                        reasoning=reasoning,
                        confidence_score=0.85
                    )

        # Verify output stored
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.output_data == output_data
            assert ag.reasoning == reasoning
            assert ag.confidence_score == 0.85


class TestLLMTracking:
    """Tests for LLM call tracking."""

    def test_track_llm_call(self, tracker):
        """Test LLM call tracking."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    llm_call_id = tracker.track_llm_call(
                        agent_id,
                        provider="ollama",
                        model="llama3.2:3b",
                        prompt="Hello",
                        response="Hi there!",
                        prompt_tokens=10,
                        completion_tokens=5,
                        latency_ms=250,
                        estimated_cost_usd=0.001,
                        temperature=0.7,
                        max_tokens=2048
                    )

        # Verify LLM call recorded
        with get_session() as session:
            llm_call = session.query(LLMCall).filter_by(id=llm_call_id).first()
            assert llm_call is not None
            assert llm_call.agent_execution_id == agent_id
            assert llm_call.provider == "ollama"
            assert llm_call.model == "llama3.2:3b"
            assert llm_call.prompt == "Hello"
            assert llm_call.response == "Hi there!"
            assert llm_call.prompt_tokens == 10
            assert llm_call.completion_tokens == 5
            assert llm_call.total_tokens == 15
            assert llm_call.latency_ms == 250
            assert llm_call.estimated_cost_usd == 0.001

    def test_llm_call_updates_agent_metrics(self, tracker):
        """Test that LLM calls update agent metrics."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    # Make 2 LLM calls
                    tracker.track_llm_call(
                        agent_id, "ollama", "llama3.2:3b", "Hi", "Hello",
                        10, 5, 200, 0.001
                    )
                    tracker.track_llm_call(
                        agent_id, "ollama", "llama3.2:3b", "Bye", "Goodbye",
                        15, 8, 250, 0.002
                    )

        # Verify agent metrics updated
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.num_llm_calls == 2
            assert ag.total_tokens == 38  # (10+5) + (15+8)
            assert ag.prompt_tokens == 25  # 10 + 15
            assert ag.completion_tokens == 13  # 5 + 8
            assert ag.estimated_cost_usd == 0.003  # 0.001 + 0.002

    def test_reject_negative_prompt_tokens(self, tracker):
        """Test that negative prompt_tokens raises ValueError."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    with pytest.raises(ValueError, match="prompt_tokens must be non-negative"):
                        tracker.track_llm_call(
                            agent_id, "ollama", "llama3.2:3b", "Hello", "Hi",
                            -10, 5, 200, 0.001  # Negative prompt_tokens
                        )

    def test_reject_negative_completion_tokens(self, tracker):
        """Test that negative completion_tokens raises ValueError."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    with pytest.raises(ValueError, match="completion_tokens must be non-negative"):
                        tracker.track_llm_call(
                            agent_id, "ollama", "llama3.2:3b", "Hello", "Hi",
                            10, -5, 200, 0.001  # Negative completion_tokens
                        )

    def test_reject_negative_latency_ms(self, tracker):
        """Test that negative latency_ms raises ValueError."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    with pytest.raises(ValueError, match="latency_ms must be non-negative"):
                        tracker.track_llm_call(
                            agent_id, "ollama", "llama3.2:3b", "Hello", "Hi",
                            10, 5, -200, 0.001  # Negative latency_ms
                        )

    def test_reject_negative_estimated_cost(self, tracker):
        """Test that negative estimated_cost_usd raises ValueError."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    with pytest.raises(ValueError, match="estimated_cost_usd must be non-negative"):
                        tracker.track_llm_call(
                            agent_id, "ollama", "llama3.2:3b", "Hello", "Hi",
                            10, 5, 200, -0.001  # Negative cost
                        )

    def test_accept_zero_values(self, tracker):
        """Test that zero values are accepted (valid edge case)."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    # Should not raise - zeros are valid
                    llm_call_id = tracker.track_llm_call(
                        agent_id, "ollama", "llama3.2:3b", "Hello", "Hi",
                        0, 0, 0, 0.0  # All zeros (valid)
                    )
                    assert llm_call_id is not None


class TestToolTracking:
    """Tests for tool execution tracking."""

    def test_track_tool_call(self, tracker):
        """Test tool call tracking."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    tool_id = tracker.track_tool_call(
                        agent_id,
                        tool_name="calculator",
                        input_params={"operation": "add", "a": 1, "b": 2},
                        output_data={"result": 3},
                        duration_seconds=0.01,
                        status="success",
                        safety_checks=["input_validation"],
                        approval_required=False
                    )

        # Verify tool execution recorded
        with get_session() as session:
            tool_exec = session.query(ToolExecution).filter_by(id=tool_id).first()
            assert tool_exec is not None
            assert tool_exec.agent_execution_id == agent_id
            assert tool_exec.tool_name == "calculator"
            assert tool_exec.input_params["operation"] == "add"
            assert tool_exec.output_data["result"] == 3
            assert tool_exec.duration_seconds == 0.01
            assert tool_exec.status == "success"
            assert "input_validation" in tool_exec.safety_checks_applied

    def test_tool_call_updates_agent_metrics(self, tracker):
        """Test that tool calls update agent metrics."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("test_wf", config_wf) as workflow_id:
            with tracker.track_stage("test_st", config_st, workflow_id) as stage_id:
                with tracker.track_agent("researcher", config_ag, stage_id) as agent_id:
                    # Make 2 tool calls
                    tracker.track_tool_call(
                        agent_id, "calculator", {"op": "add"}, {"result": 3}, 0.01
                    )
                    tracker.track_tool_call(
                        agent_id, "search", {"query": "test"}, {"results": []}, 0.5
                    )

        # Verify agent metrics updated
        with get_session() as session:
            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag.num_tool_calls == 2


class TestNestedTracking:
    """Tests for nested execution tracking."""

    def test_full_nested_execution(self, tracker):
        """Test complete nested execution hierarchy."""
        config_wf = {"workflow": {"name": "full_test"}}
        config_st = {"stage": {"name": "test_stage"}}
        config_ag = {"agent": {"name": "test_agent"}}

        with tracker.track_workflow("full_test", config_wf) as workflow_id:
            with tracker.track_stage("stage1", config_st, workflow_id) as stage_id:
                with tracker.track_agent("agent1", config_ag, stage_id) as agent_id:
                    # Track LLM and tool calls
                    tracker.track_llm_call(
                        agent_id, "ollama", "llama3.2:3b",
                        "prompt", "response", 100, 50, 300, 0.005
                    )
                    tracker.track_tool_call(
                        agent_id, "tool1", {}, {}, 0.1
                    )

        # Verify full hierarchy in database
        with get_session() as session:
            wf = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert wf is not None
            assert wf.status == "completed"

            st = session.query(StageExecution).filter_by(id=stage_id).first()
            assert st is not None
            assert st.workflow_execution_id == workflow_id

            ag = session.query(AgentExecution).filter_by(id=agent_id).first()
            assert ag is not None
            assert ag.stage_execution_id == stage_id
            assert ag.num_llm_calls == 1
            assert ag.num_tool_calls == 1

            llm_calls = session.query(LLMCall).filter_by(agent_execution_id=agent_id).all()
            assert len(llm_calls) == 1

            tool_calls = session.query(ToolExecution).filter_by(agent_execution_id=agent_id).all()
            assert len(tool_calls) == 1

    def test_multiple_stages_in_workflow(self, tracker):
        """Test workflow with multiple stages."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("multi_stage", config_wf) as workflow_id:
            with tracker.track_stage("stage1", config_st, workflow_id) as stage1_id:
                with tracker.track_agent("agent1", config_ag, stage1_id):
                    pass

            with tracker.track_stage("stage2", config_st, workflow_id) as stage2_id:
                with tracker.track_agent("agent2", config_ag, stage2_id):
                    pass

        # Verify both stages recorded
        with get_session() as session:
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).all()
            assert len(stages) == 2
            assert {s.stage_name for s in stages} == {"stage1", "stage2"}

    def test_multiple_agents_in_stage(self, tracker):
        """Test stage with multiple agents."""
        config_wf = {}
        config_st = {}
        config_ag = {}

        with tracker.track_workflow("multi_agent", config_wf) as workflow_id:
            with tracker.track_stage("stage1", config_st, workflow_id) as stage_id:
                with tracker.track_agent("agent1", config_ag, stage_id):
                    pass

                with tracker.track_agent("agent2", config_ag, stage_id):
                    pass

        # Verify both agents recorded
        with get_session() as session:
            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).all()
            assert len(agents) == 2
            assert {a.agent_name for a in agents} == {"agent1", "agent2"}


class TestHighVolumePerformance:
    """Performance tests for high-volume event tracking."""

    @pytest.mark.slow
    def test_track_10k_workflows_throughput(self, tracker):
        """Test throughput of tracking 10,000 workflows."""
        import os
        import time

        import psutil

        # Measure initial memory
        process = psutil.Process(os.getpid())
        initial_memory_mb = process.memory_info().rss / 1024 / 1024

        # Track 10,000 workflows
        start_time = time.time()

        config = {"workflow": {"name": "perf_test"}}

        for i in range(10000):
            with tracker.track_workflow(f"workflow_{i}", config):
                pass  # Empty workflow

        elapsed_time = time.time() - start_time

        # Measure final memory
        final_memory_mb = process.memory_info().rss / 1024 / 1024
        memory_increase_mb = final_memory_mb - initial_memory_mb

        # Calculate throughput
        throughput = 10000 / elapsed_time

        # Verify acceptance criteria
        assert throughput > 1000, \
            f"Throughput {throughput:.0f} events/sec below requirement of 1000 events/sec"

        assert memory_increase_mb < 500, \
            f"Memory increase {memory_increase_mb:.1f}MB exceeds 500MB limit"

        # Verify all workflows were tracked
        with get_session() as session:
            count = session.query(WorkflowExecution).count()
            assert count == 10000, f"Expected 10000 workflows, got {count}"

        print("\nPerformance Results:")
        print(f"  Throughput: {throughput:.0f} events/sec")
        print(f"  Total time: {elapsed_time:.2f}s")
        print(f"  Memory increase: {memory_increase_mb:.1f}MB")

    @pytest.mark.slow
    def test_track_10k_stages_no_errors(self, tracker):
        """Test tracking 10,000 stages without errors."""
        config = {"workflow": {"name": "perf_test"}}

        # Create one workflow with many stages
        with tracker.track_workflow("bulk_stages_workflow", config) as workflow_id:
            stage_config = {}

            # Track 10,000 stages (reduced from workflows for performance)
            for i in range(10000):
                with tracker.track_stage(f"stage_{i}", stage_config, workflow_id):
                    pass  # Empty stage

        # Verify no errors and all stages tracked
        with get_session() as session:
            count = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).count()
            assert count == 10000, f"Expected 10000 stages, got {count}"

    @pytest.mark.slow
    def test_track_10k_agents_no_errors(self, tracker):
        """Test tracking 10,000 agents without errors."""
        config_wf = {"workflow": {"name": "perf_test"}}
        config_st = {}
        config_ag = {}

        # Create one workflow with one stage and many agents
        with tracker.track_workflow("bulk_agents_workflow", config_wf) as workflow_id:
            with tracker.track_stage("bulk_stage", config_st, workflow_id) as stage_id:
                # Track 10,000 agents
                for i in range(10000):
                    with tracker.track_agent(f"agent_{i}", config_ag, stage_id):
                        pass  # Empty agent

        # Verify all agents tracked
        with get_session() as session:
            count = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).count()
            assert count == 10000, f"Expected 10000 agents, got {count}"

    def test_concurrent_workflow_tracking(self, tracker):
        """Test concurrent workflow tracking performance.

        Note: SQLite in-memory databases require serialized writes.
        This test uses db_lock to serialize database commits while
        demonstrating concurrent tracking capability.
        """
        import threading
        import time

        errors = []
        workflow_ids = []
        lock = threading.Lock()
        db_lock = threading.Lock()  # Serialize SQLite writes

        def track_workflows(worker_id, num_workflows):
            """Track workflows in a thread."""
            try:
                config = {"workflow": {"name": f"worker_{worker_id}"}}

                for i in range(num_workflows):
                    # Serialize database operations for SQLite
                    with db_lock:
                        with tracker.track_workflow(f"wf_{worker_id}_{i}", config) as wf_id:
                            workflow_ids.append(wf_id)
            except Exception as e:
                with lock:
                    errors.append((worker_id, str(e)))

        # Launch 10 threads, each tracking 1000 workflows (10K total)
        start_time = time.time()
        threads = []

        for worker_id in range(10):
            thread = threading.Thread(target=track_workflows, args=(worker_id, 1000))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        elapsed_time = time.time() - start_time

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent tracking: {errors}"

        # Verify all workflows tracked
        assert len(workflow_ids) == 10000, f"Expected 10000 workflows, got {len(workflow_ids)}"

        # Calculate throughput
        throughput = 10000 / elapsed_time
        print(f"\nConcurrent tracking throughput: {throughput:.0f} events/sec")

        # Verify all in database
        with get_session() as session:
            count = session.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_name.like("wf_%")
            ).count()
            assert count == 10000

    def test_memory_usage_stable_under_load(self, tracker):
        """Test that memory usage stays stable under continuous load."""
        import gc
        import os

        import psutil

        process = psutil.Process(os.getpid())

        # Force garbage collection before starting
        gc.collect()

        # Measure baseline memory
        baseline_memory_mb = process.memory_info().rss / 1024 / 1024

        config = {"workflow": {"name": "memory_test"}}

        # Track 5000 workflows
        for i in range(5000):
            with tracker.track_workflow(f"mem_test_{i}", config):
                pass

            # Check memory every 1000 iterations
            if i % 1000 == 0:
                gc.collect()
                current_memory_mb = process.memory_info().rss / 1024 / 1024
                memory_increase = current_memory_mb - baseline_memory_mb

                # Memory increase should be reasonable (<500MB)
                assert memory_increase < 500, \
                    f"Memory increase {memory_increase:.1f}MB exceeds limit at iteration {i}"

        # Final memory check
        gc.collect()
        final_memory_mb = process.memory_info().rss / 1024 / 1024
        total_increase = final_memory_mb - baseline_memory_mb

        print("\nMemory stability test:")
        print(f"  Baseline: {baseline_memory_mb:.1f}MB")
        print(f"  Final: {final_memory_mb:.1f}MB")
        print(f"  Increase: {total_increase:.1f}MB")

        assert total_increase < 500, f"Total memory increase {total_increase:.1f}MB exceeds 500MB"
