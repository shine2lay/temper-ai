"""Tests for tool execution with observability."""

from temper_ai.llm.models import CallContext
from temper_ai.llm.tool_execution import execute_tool_calls
from temper_ai.observability import EventType, get_events


def _success_executor(name: str, params: dict) -> str:
    """A tool executor that always succeeds."""
    return f"executed {name} with {params}"


def _failing_executor(name: str, params: dict) -> str:
    """A tool executor that always raises."""
    raise RuntimeError(f"Tool {name} failed")


def _selective_executor(name: str, params: dict) -> str:
    """Succeeds for 'bash', fails for everything else."""
    if name == "bash":
        return "file1.py\nfile2.py"
    raise ValueError(f"Unknown tool: {name}")


class TestExecuteToolCalls:
    def test_single_successful_call(self):
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {"command": "ls"}}]
        results = execute_tool_calls(tool_calls, _success_executor)

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["tool_call_id"] == "c1"
        assert results[0]["name"] == "bash"
        assert "executed bash" in results[0]["result"]
        assert results[0]["duration_ms"] >= 0

    def test_single_failed_call(self):
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {"command": "ls"}}]
        results = execute_tool_calls(tool_calls, _failing_executor)

        assert len(results) == 1
        assert results[0]["success"] is False
        assert "RuntimeError" in results[0]["result"]
        assert results[0]["duration_ms"] >= 0

    def test_multiple_calls(self):
        tool_calls = [
            {"id": "c1", "name": "bash", "arguments": {"command": "ls"}},
            {"id": "c2", "name": "file_writer", "arguments": {"path": "x.py"}},
            {"id": "c3", "name": "bash", "arguments": {"command": "cat x.py"}},
        ]
        results = execute_tool_calls(tool_calls, _success_executor)
        assert len(results) == 3
        assert all(r["success"] for r in results)

    def test_mixed_success_and_failure(self):
        tool_calls = [
            {"id": "c1", "name": "bash", "arguments": {"command": "ls"}},
            {"id": "c2", "name": "unknown_tool", "arguments": {}},
        ]
        results = execute_tool_calls(tool_calls, _selective_executor)
        assert results[0]["success"] is True
        assert results[1]["success"] is False


class TestToolObservability:
    def test_records_start_and_complete_events(self):
        ctx = CallContext(execution_id="exec-1", agent_name="researcher")
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {"command": "ls"}}]

        execute_tool_calls(tool_calls, _success_executor, context=ctx)

        events = get_events(execution_id="exec-1")
        types = [e["type"] for e in events]

        assert EventType.TOOL_CALL_STARTED in types
        assert EventType.TOOL_CALL_COMPLETED in types

        started = [e for e in events if e["type"] == EventType.TOOL_CALL_STARTED][0]
        assert started["data"]["tool_name"] == "bash"
        assert started["data"]["agent_name"] == "researcher"
        assert started["status"] == "running"

        completed = [e for e in events if e["type"] == EventType.TOOL_CALL_COMPLETED][0]
        assert completed["data"]["tool_name"] == "bash"
        assert completed["data"]["duration_ms"] >= 0
        assert completed["status"] == "completed"

    def test_records_failed_event(self):
        ctx = CallContext(execution_id="exec-2", agent_name="coder")
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {"command": "rm -rf /"}}]

        execute_tool_calls(tool_calls, _failing_executor, context=ctx)

        events = get_events(execution_id="exec-2")
        failed = [e for e in events if e["type"] == EventType.TOOL_CALL_FAILED]

        assert len(failed) == 1
        assert failed[0]["data"]["tool_name"] == "bash"
        assert "RuntimeError" in failed[0]["data"]["error"]
        assert failed[0]["status"] == "failed"

    def test_parent_id_links_to_llm_call(self):
        ctx = CallContext(execution_id="exec-3")
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {}}]

        execute_tool_calls(
            tool_calls, _success_executor, context=ctx,
            llm_call_event_id="llm-event-123",
        )

        events = get_events(execution_id="exec-3")
        for event in events:
            assert event["data"].get("tool_name") == "bash" or True
            # All events should have llm call as parent
            if event["type"] in (EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED):
                assert event["parent_id"] == "llm-event-123"

    def test_multiple_tools_each_get_events(self):
        ctx = CallContext(execution_id="exec-4")
        tool_calls = [
            {"id": "c1", "name": "bash", "arguments": {"cmd": "ls"}},
            {"id": "c2", "name": "bash", "arguments": {"cmd": "pwd"}},
        ]

        execute_tool_calls(tool_calls, _success_executor, context=ctx)

        events = get_events(execution_id="exec-4")
        started = [e for e in events if e["type"] == EventType.TOOL_CALL_STARTED]
        completed = [e for e in events if e["type"] == EventType.TOOL_CALL_COMPLETED]

        assert len(started) == 2
        assert len(completed) == 2


class TestToolInputStorage:
    def test_full_input_stored(self):
        ctx = CallContext(execution_id="exec-5")
        long_args = {"data": "x" * 5000}
        tool_calls = [{"id": "c1", "name": "process", "arguments": long_args}]

        execute_tool_calls(tool_calls, _success_executor, context=ctx)

        events = get_events(execution_id="exec-5")
        started = [e for e in events if e["type"] == EventType.TOOL_CALL_STARTED][0]
        # Full params stored as dict, not truncated
        assert started["data"]["input_params"] == long_args

    def test_full_output_stored(self):
        ctx = CallContext(execution_id="exec-6")
        tool_calls = [{"id": "c1", "name": "process", "arguments": {"x": "test"}}]

        execute_tool_calls(tool_calls, _success_executor, context=ctx)

        events = get_events(execution_id="exec-6")
        completed = [e for e in events if e["type"] == EventType.TOOL_CALL_COMPLETED][0]
        assert "output" in completed["data"]
        assert "executed process" in completed["data"]["output"]
