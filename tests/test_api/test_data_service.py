"""Tests for api/data_service.py — event hierarchy reconstruction."""

from unittest.mock import patch

from temper_ai.api.data_service import (
    _build_agent_execution,
    _build_node_execution,
    _find_children,
    _find_event_by_type,
    _get_end_time,
    _resolve_status,
    get_workflow_execution,
    list_workflow_executions,
)


def _evt(id, type, parent_id=None, execution_id="run-1", status="running", data=None, timestamp="2026-01-01T00:00:00"):
    """Helper to build event dicts."""
    return {
        "id": id,
        "type": type,
        "parent_id": parent_id,
        "execution_id": execution_id,
        "status": status,
        "data": data or {},
        "timestamp": timestamp,
    }


class TestHelpers:
    def test_find_event_by_type(self):
        events = [
            _evt("1", "agent.started"),
            _evt("2", "workflow.started"),
        ]
        assert _find_event_by_type(events, "workflow.")["id"] == "2"

    def test_find_event_by_type_not_found(self):
        assert _find_event_by_type([_evt("1", "agent.started")], "workflow.") is None

    def test_find_children(self):
        events = [
            _evt("wf", "workflow.started"),
            _evt("s1", "stage.started", parent_id="wf"),
            _evt("s2", "stage.started", parent_id="wf"),
            _evt("s1c", "stage.completed", parent_id="wf"),  # should be excluded (completed)
            _evt("a1", "agent.started", parent_id="s1"),  # wrong parent
        ]
        children = _find_children(events, "wf", "stage.")
        assert len(children) == 2
        assert {c["id"] for c in children} == {"s1", "s2"}

    def test_resolve_status(self):
        assert _resolve_status({"status": "completed"}) == "completed"
        assert _resolve_status({}) == "pending"

    def test_get_end_time(self):
        events = [
            _evt("wf", "workflow.started", timestamp="T1"),
            _evt("wfc", "workflow.completed", parent_id="wf", timestamp="T2"),
        ]
        assert _get_end_time(events, "wf", "workflow.") == "T2"

    def test_get_end_time_not_found(self):
        events = [_evt("wf", "workflow.started")]
        assert _get_end_time(events, "wf", "workflow.") is None


class TestBuildAgentExecution:
    def test_basic_agent(self):
        agent_started = _evt("a1", "agent.started", parent_id="s1", data={
            "agent_name": "planner",
            "input_data": {"task": "plan"},
            "agent_config": {"type": "llm", "model": "gpt-4o"},
        })
        agent_completed = _evt("a1c", "agent.completed", parent_id="a1", status="completed", data={
            "agent_name": "planner",
            "output": "Here is the plan",
            "tokens": 150,
            "cost_usd": 0.01,
        })
        all_events = [agent_started, agent_completed]

        result = _build_agent_execution(agent_started, all_events)

        assert result["agent_name"] == "planner"
        assert result["status"] == "completed"
        assert result["output"] == "Here is the plan"
        assert result["total_tokens"] == 150
        assert result["estimated_cost_usd"] == 0.01
        assert result["input_data"] == {"task": "plan"}
        assert result["agent_config_snapshot"]["agent"]["model"] == "gpt-4o"

    def test_agent_with_llm_and_tool_calls(self):
        agent = _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder"})
        llm1 = _evt("l1", "llm.call.started", parent_id="a1", data={"iteration": 1})
        llm1c = _evt("l1c", "llm.call.completed", parent_id="a1", data={
            "iteration": 1, "total_tokens": 100,
        })
        tool1 = _evt("t1", "tool.call.started", parent_id="a1", data={"tool_name": "Bash"})
        all_events = [agent, llm1, llm1c, tool1]

        result = _build_agent_execution(agent, all_events)

        assert result["total_llm_calls"] == 1
        assert result["total_tool_calls"] == 1

    def test_agent_no_config_snapshot(self):
        agent = _evt("a1", "agent.started", data={})
        result = _build_agent_execution(agent, [agent])
        assert result["agent_config_snapshot"] is None


class TestBuildNodeExecution:
    def test_agent_node(self):
        stage = _evt("s1", "stage.started", parent_id="wf", data={"name": "planner"})
        agent = _evt("a1", "agent.started", parent_id="s1", data={
            "agent_name": "planner", "tokens": 100,
        })
        agent_c = _evt("a1c", "agent.completed", parent_id="a1", status="completed", data={
            "tokens": 100, "cost_usd": 0.01,
        })
        all_events = [stage, agent, agent_c]

        result = _build_node_execution(stage, all_events)

        assert result["name"] == "planner"
        assert result["type"] == "agent"
        assert result["agent"] is not None  # single agent → goes to "agent" field
        assert result["agents"] is None

    def test_stage_with_multiple_agents(self):
        stage = _evt("s1", "stage.started", parent_id="wf", data={"name": "code"})
        a1 = _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder_a"})
        a2 = _evt("a2", "agent.started", parent_id="s1", data={"agent_name": "coder_b"})
        all_events = [stage, a1, a2]

        result = _build_node_execution(stage, all_events)

        assert result["agents"] is not None
        assert len(result["agents"]) == 2


class TestGetWorkflowExecution:
    @patch("temper_ai.api.data_service.get_events")
    def test_full_workflow(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf", "workflow.started", execution_id="run-1", data={"name": "test_wf"}),
            _evt("s1", "stage.started", parent_id="wf", execution_id="run-1", data={"name": "plan"}),
            _evt("a1", "agent.started", parent_id="s1", execution_id="run-1", data={
                "agent_name": "planner", "tokens": 50,
            }),
            _evt("a1c", "agent.completed", parent_id="a1", execution_id="run-1", status="completed", data={
                "tokens": 50, "cost_usd": 0.005,
            }),
        ]

        result = get_workflow_execution("run-1")

        assert result is not None
        assert result["id"] == "run-1"
        assert result["workflow_name"] == "test_wf"
        assert len(result["nodes"]) == 1

    @patch("temper_ai.api.data_service.get_events")
    def test_no_events_returns_none(self, mock_get_events):
        mock_get_events.return_value = []
        assert get_workflow_execution("nonexistent") is None

    @patch("temper_ai.api.data_service.get_events")
    def test_no_workflow_event_returns_none(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("a1", "agent.started"),  # no workflow event
        ]
        assert get_workflow_execution("run-1") is None


class TestListWorkflowExecutions:
    @patch("temper_ai.api.data_service.get_events")
    def test_list_runs(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf1", "workflow.started", execution_id="run-1", status="completed",
                 data={"name": "wf1", "cost_usd": 0.1}, timestamp="2026-01-01T00:00:01"),
            _evt("wf2", "workflow.started", execution_id="run-2", status="running",
                 data={"name": "wf2"}, timestamp="2026-01-01T00:00:02"),
        ]

        result = list_workflow_executions()

        assert result["total"] == 2
        assert len(result["runs"]) == 2
        # Most recent first
        assert result["runs"][0]["id"] == "run-2"

    @patch("temper_ai.api.data_service.get_events")
    def test_filter_by_status(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf1", "workflow.started", execution_id="run-1", status="completed",
                 data={"name": "wf1"}, timestamp="T1"),
            _evt("wf2", "workflow.started", execution_id="run-2", status="running",
                 data={"name": "wf2"}, timestamp="T2"),
        ]

        result = list_workflow_executions(status="completed")

        assert result["total"] == 1
        assert result["runs"][0]["status"] == "completed"

    @patch("temper_ai.api.data_service.get_events")
    def test_pagination(self, mock_get_events):
        mock_get_events.return_value = [
            _evt(f"wf{i}", "workflow.started", execution_id=f"run-{i}", status="completed",
                 data={"name": f"wf{i}"}, timestamp=f"2026-01-01T00:00:{i:02d}")
            for i in range(10)
        ]

        result = list_workflow_executions(limit=3, offset=2)

        assert result["total"] == 10
        assert len(result["runs"]) == 3

    @patch("temper_ai.api.data_service.get_events")
    def test_empty(self, mock_get_events):
        mock_get_events.return_value = []
        result = list_workflow_executions()
        assert result == {"runs": [], "total": 0}
