"""Tests for observability backend read API methods."""
from datetime import datetime, timezone

import pytest

from temper_ai.storage.database import init_database
from temper_ai.observability.constants import ObservabilityFields
from temper_ai.storage.database.models import (
    AgentExecution,
    CollaborationEvent,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)
from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    import temper_ai.storage.database.manager as db_module
    from temper_ai.storage.database.manager import _db_lock

    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def backend(db):
    """Create SQL backend with buffering disabled for synchronous writes."""
    return SQLObservabilityBackend(buffer=False)


@pytest.fixture
def populated_db(backend):
    """Create a fully populated workflow hierarchy for read tests."""
    now = datetime.now(timezone.utc)

    # Create workflow
    backend.track_workflow_start(
        workflow_id="wf-read-1",
        workflow_name="test_read_workflow",
        workflow_config={"workflow": {"name": "test", "version": "2.0"}},
        start_time=now,
        trigger_type="manual",
        environment="test",
        tags=["read-test"],
        extra_metadata={"test_key": "test_value"},
    )

    # Create stage
    backend.track_stage_start(
        stage_id="st-read-1",
        workflow_id="wf-read-1",
        stage_name="analysis_stage",
        stage_config={"stage": {"version": "1.0"}},
        start_time=now,
        input_data={"query": "test query"},
    )

    # Create agent
    backend.track_agent_start(
        agent_id="ag-read-1",
        stage_id="st-read-1",
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=now,
        input_data={"task": "research"},
    )

    # Create LLM call
    backend.track_llm_call(
        llm_call_id="llm-read-1",
        agent_id="ag-read-1",
        provider="ollama",
        model="qwen3",
        prompt="Analyze this topic",
        response="Here is my analysis...",
        prompt_tokens=50,
        completion_tokens=100,
        latency_ms=500,
        estimated_cost_usd=0.005,
        start_time=now,
        temperature=0.7,
        max_tokens=1024,
    )

    # Create tool call
    backend.track_tool_call(
        tool_execution_id="tool-read-1",
        agent_id="ag-read-1",
        tool_name="web_search",
        input_params={"query": "test search"},
        output_data={"results": ["result1", "result2"]},
        start_time=now,
        duration_seconds=1.5,
        status="success",
        safety_checks=["url_allowlist"],
        approval_required=False,
    )

    # Create collaboration event
    backend.track_collaboration_event(
        stage_id="st-read-1",
        event_type="vote",
        agents_involved=["ag-read-1"],
        event_data={"votes": {"ag-read-1": "approve"}},
        round_number=1,
        resolution_strategy="majority",
        outcome="approved",
        confidence_score=0.95,
    )

    # End agent, stage, workflow
    backend.track_agent_end(
        agent_id="ag-read-1",
        end_time=now,
        status="completed",
    )
    backend.set_agent_output(
        agent_id="ag-read-1",
        output_data={"analysis": "done"},
        reasoning="Completed analysis",
        confidence_score=0.9,
        total_tokens=150,
        prompt_tokens=50,
        completion_tokens=100,
        estimated_cost_usd=0.005,
        num_llm_calls=1,
        num_tool_calls=1,
    )
    backend.track_stage_end(
        stage_id="st-read-1",
        end_time=now,
        status="completed",
        num_agents_executed=1,
        num_agents_succeeded=1,
        num_agents_failed=0,
    )
    backend.set_stage_output(
        stage_id="st-read-1",
        output_data={"stage_result": "success"},
    )
    backend.track_workflow_end(
        workflow_id="wf-read-1",
        end_time=now,
        status="completed",
    )
    backend.update_workflow_metrics(
        workflow_id="wf-read-1",
        total_llm_calls=1,
        total_tool_calls=1,
        total_tokens=150,
        total_cost_usd=0.005,
    )

    return backend


class TestGetWorkflow:
    """Tests for get_workflow read method."""

    def test_get_workflow_returns_full_hierarchy(self, populated_db):
        """Verify get_workflow returns workflow with all nested children."""
        result = populated_db.get_workflow("wf-read-1")

        assert result is not None
        assert result["id"] == "wf-read-1"
        assert result["workflow_name"] == "test_read_workflow"
        assert result[ObservabilityFields.STATUS] == "completed"
        assert result["trigger_type"] == "manual"
        assert result["environment"] == "test"
        assert result[ObservabilityFields.TOTAL_TOKENS] == 150
        assert result[ObservabilityFields.TOTAL_COST_USD] == 0.005
        assert result[ObservabilityFields.TOTAL_LLM_CALLS] == 1
        assert result[ObservabilityFields.TOTAL_TOOL_CALLS] == 1
        assert result["tags"] == ["read-test"]
        assert result["extra_metadata"] == {"test_key": "test_value"}
        assert result[ObservabilityFields.START_TIME] is not None
        assert result[ObservabilityFields.END_TIME] is not None

        # Check stages
        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["id"] == "st-read-1"
        assert stage["stage_name"] == "analysis_stage"
        assert stage["status"] == "completed"
        assert stage[ObservabilityFields.OUTPUT_DATA] == {"stage_result": "success"}

        # Check agents
        assert len(stage["agents"]) == 1
        agent = stage["agents"][0]
        assert agent["id"] == "ag-read-1"
        assert agent[ObservabilityFields.AGENT_NAME] == "researcher"
        assert agent[ObservabilityFields.STATUS] == "completed"
        assert agent["reasoning"] == "Completed analysis"

        # Check LLM calls
        assert len(agent["llm_calls"]) == 1
        llm = agent["llm_calls"][0]
        assert llm["id"] == "llm-read-1"
        assert llm["provider"] == "ollama"
        assert llm["model"] == "qwen3"
        assert llm["prompt"] == "Analyze this topic"
        assert llm["response"] == "Here is my analysis..."
        assert llm["prompt_tokens"] == 50
        assert llm["completion_tokens"] == 100
        assert llm["latency_ms"] == 500

        # Check tool calls
        assert len(agent["tool_calls"]) == 1
        tool = agent["tool_calls"][0]
        assert tool["id"] == "tool-read-1"
        assert tool["tool_name"] == "web_search"
        assert tool["input_params"] == {"query": "test search"}
        assert tool["output_data"] == {"results": ["result1", "result2"]}
        assert tool["duration_seconds"] == 1.5

        # Check collaboration events
        assert len(stage["collaboration_events"]) == 1
        collab = stage["collaboration_events"][0]
        assert collab["event_type"] == "vote"
        assert collab["agents_involved"] == ["ag-read-1"]
        assert collab["round_number"] == 1
        assert collab["outcome"] == "approved"
        assert collab["confidence_score"] == 0.95

    def test_get_workflow_not_found(self, backend):
        """get_workflow returns None for non-existent workflow ID."""
        result = backend.get_workflow("nonexistent-id")
        assert result is None

    def test_get_workflow_datetime_iso_format(self, populated_db):
        """Verify datetime fields are returned as ISO format strings."""
        result = populated_db.get_workflow("wf-read-1")
        assert result is not None
        # Should be a string in ISO format, not a datetime object
        assert isinstance(result[ObservabilityFields.START_TIME], str)
        assert isinstance(result[ObservabilityFields.END_TIME], str)
        # Verify it can be parsed back
        datetime.fromisoformat(result[ObservabilityFields.START_TIME])
        datetime.fromisoformat(result[ObservabilityFields.END_TIME])


class TestListWorkflows:
    """Tests for list_workflows read method."""

    def test_list_workflows_returns_summaries(self, populated_db):
        """list_workflows returns workflow summaries without children."""
        result = populated_db.list_workflows()
        assert len(result) == 1
        wf = result[0]
        assert wf["id"] == "wf-read-1"
        assert wf["workflow_name"] == "test_read_workflow"
        # Summary only: stages list should be empty (not loaded)
        assert wf["stages"] == []

    def test_list_workflows_pagination(self, backend):
        """Test limit and offset pagination."""
        now = datetime.now(timezone.utc)
        # Create 5 workflows
        for i in range(5):
            backend.track_workflow_start(
                workflow_id=f"wf-page-{i}",
                workflow_name=f"workflow_{i}",
                workflow_config={"workflow": {"name": f"wf_{i}"}},
                start_time=now,
            )

        # Get first 2
        result = backend.list_workflows(limit=2, offset=0)
        assert len(result) == 2

        # Get next 2
        result2 = backend.list_workflows(limit=2, offset=2)
        assert len(result2) == 2

        # Get last 1
        result3 = backend.list_workflows(limit=2, offset=4)
        assert len(result3) == 1

        # All IDs should be different
        all_ids = [w["id"] for w in result + result2 + result3]
        assert len(set(all_ids)) == 5

    def test_list_workflows_status_filter(self, backend):
        """Test filtering by status."""
        now = datetime.now(timezone.utc)
        # Create completed workflow
        backend.track_workflow_start(
            workflow_id="wf-filter-1",
            workflow_name="completed_workflow",
            workflow_config={"workflow": {}},
            start_time=now,
        )
        backend.track_workflow_end(
            workflow_id="wf-filter-1",
            end_time=now,
            status="completed",
        )
        # Create running workflow
        backend.track_workflow_start(
            workflow_id="wf-filter-2",
            workflow_name="running_workflow",
            workflow_config={"workflow": {}},
            start_time=now,
        )

        # Filter completed only
        completed = backend.list_workflows(status="completed")
        assert len(completed) == 1
        assert completed[0]["id"] == "wf-filter-1"

        # Filter running only
        running = backend.list_workflows(status="running")
        assert len(running) == 1
        assert running[0]["id"] == "wf-filter-2"

        # No filter returns all
        all_wfs = backend.list_workflows()
        assert len(all_wfs) == 2

    def test_list_workflows_empty(self, backend):
        """list_workflows returns empty list when no workflows exist."""
        result = backend.list_workflows()
        assert result == []


class TestGetStage:
    """Tests for get_stage read method."""

    def test_get_stage_with_agents(self, populated_db):
        """Verify stage includes agents and collaboration events."""
        result = populated_db.get_stage("st-read-1")
        assert result is not None
        assert result["id"] == "st-read-1"
        assert result["stage_name"] == "analysis_stage"
        assert result[ObservabilityFields.STATUS] == "completed"
        assert result[ObservabilityFields.INPUT_DATA] == {"query": "test query"}
        assert result[ObservabilityFields.OUTPUT_DATA] == {"stage_result": "success"}
        assert result["num_agents_executed"] == 1
        assert result["num_agents_succeeded"] == 1

        # Agents loaded
        assert len(result["agents"]) == 1
        assert result["agents"][0]["id"] == "ag-read-1"

        # Collaboration events loaded
        assert len(result["collaboration_events"]) == 1
        assert result["collaboration_events"][0]["event_type"] == "vote"

    def test_get_stage_not_found(self, backend):
        """get_stage returns None for non-existent stage ID."""
        result = backend.get_stage("nonexistent-id")
        assert result is None


class TestGetAgent:
    """Tests for get_agent read method."""

    def test_get_agent_with_calls(self, populated_db):
        """Verify agent includes LLM and tool calls."""
        result = populated_db.get_agent("ag-read-1")
        assert result is not None
        assert result["id"] == "ag-read-1"
        assert result[ObservabilityFields.AGENT_NAME] == "researcher"
        assert result[ObservabilityFields.STATUS] == "completed"
        assert result["reasoning"] == "Completed analysis"
        assert result["confidence_score"] == 0.9
        assert result[ObservabilityFields.TOTAL_TOKENS] == 150

        # LLM calls loaded
        assert len(result["llm_calls"]) == 1
        assert result["llm_calls"][0]["id"] == "llm-read-1"

        # Tool calls loaded
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "tool-read-1"

    def test_get_agent_not_found(self, backend):
        """get_agent returns None for non-existent agent ID."""
        result = backend.get_agent("nonexistent-id")
        assert result is None


class TestGetLLMCall:
    """Tests for get_llm_call read method."""

    def test_get_llm_call(self, populated_db):
        """Verify full prompt/response returned."""
        result = populated_db.get_llm_call("llm-read-1")
        assert result is not None
        assert result["id"] == "llm-read-1"
        assert result["provider"] == "ollama"
        assert result["model"] == "qwen3"
        assert result["prompt"] == "Analyze this topic"
        assert result["response"] == "Here is my analysis..."
        assert result["prompt_tokens"] == 50
        assert result["completion_tokens"] == 100
        assert result[ObservabilityFields.TOTAL_TOKENS] == 150
        assert result["latency_ms"] == 500
        assert result["estimated_cost_usd"] == 0.005
        assert result["temperature"] == 0.7
        assert result["max_tokens"] == 1024
        assert result[ObservabilityFields.STATUS] == "success"
        assert isinstance(result[ObservabilityFields.START_TIME], str)

    def test_get_llm_call_not_found(self, backend):
        """get_llm_call returns None for non-existent ID."""
        result = backend.get_llm_call("nonexistent-id")
        assert result is None


class TestGetToolCall:
    """Tests for get_tool_call read method."""

    def test_get_tool_call(self, populated_db):
        """Verify full params/output returned."""
        result = populated_db.get_tool_call("tool-read-1")
        assert result is not None
        assert result["id"] == "tool-read-1"
        assert result["tool_name"] == "web_search"
        assert result["input_params"] == {"query": "test search"}
        assert result[ObservabilityFields.OUTPUT_DATA] == {"results": ["result1", "result2"]}
        assert result[ObservabilityFields.DURATION_SECONDS] == 1.5
        assert result[ObservabilityFields.STATUS] == "success"
        assert result["safety_checks_applied"] == ["url_allowlist"]
        assert result["approval_required"] is False
        assert isinstance(result[ObservabilityFields.START_TIME], str)

    def test_get_tool_call_not_found(self, backend):
        """get_tool_call returns None for non-existent ID."""
        result = backend.get_tool_call("nonexistent-id")
        assert result is None


class TestNoOpBackendReadStubs:
    """Verify NoOp backend read stubs return expected defaults."""

    def test_noop_read_stubs(self):
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        assert backend.get_workflow("any-id") is None
        assert backend.list_workflows() == []
        assert backend.get_stage("any-id") is None
        assert backend.get_agent("any-id") is None
        assert backend.get_llm_call("any-id") is None
        assert backend.get_tool_call("any-id") is None


class TestPrometheusBackendReadStubs:
    """Verify Prometheus backend read stubs return expected defaults."""

    def test_prometheus_read_stubs(self):
        from temper_ai.observability.backends.prometheus_backend import PrometheusObservabilityBackend

        backend = PrometheusObservabilityBackend()
        assert backend.get_workflow("any-id") is None
        assert backend.list_workflows() == []
        assert backend.get_stage("any-id") is None
        assert backend.get_agent("any-id") is None
        assert backend.get_llm_call("any-id") is None
        assert backend.get_tool_call("any-id") is None


class TestS3BackendReadStubs:
    """Verify S3 backend read stubs return expected defaults."""

    def test_s3_read_stubs(self):
        from temper_ai.observability.backends.s3_backend import S3ObservabilityBackend

        backend = S3ObservabilityBackend()
        assert backend.get_workflow("any-id") is None
        assert backend.list_workflows() == []
        assert backend.get_stage("any-id") is None
        assert backend.get_agent("any-id") is None
        assert backend.get_llm_call("any-id") is None
        assert backend.get_tool_call("any-id") is None
