"""Tests for the MCP tool layer.

The point of these tools is that an agent can drive temper without its
context being flooded, so the tests care most about what is *left out* of
each response and about failures being explained rather than silent.
"""

from unittest.mock import patch  # noqa: F401

import pytest

from temper_ai.mcp.tools import DEFAULT_MAX_CHARS, TemperTools, _clip, _node_summary

RUN = {
    "id": "run-1",
    "workflow_name": "demo",
    "status": "failed",
    "start_time": "2026-01-01T00:00:00",
    "end_time": "2026-01-01T00:01:00",
    "duration_seconds": 60.0,
    "total_tokens": 1234,
    "total_cost_usd": 0.05,
    "input_data": {"topic": "otters"},
    "workflow_output": {"answer": "..."},
    "error_message": None,
    "nodes": [
        {
            "name": "research",
            "type": "agent",
            "status": "completed",
            "duration_seconds": 12.0,
            "total_tokens": 1000,
            "cost_usd": 0.04,
            "agent": {
                "agent_name": "researcher",
                "status": "completed",
                "input_data": {"topic": "otters"},
                "output": "x" * 9000,
                "structured_output": {"found": True},
                "llm_calls": [
                    {
                        "id": "call-1",
                        "provider": "claude",
                        "model": "haiku",
                        "status": "completed",
                        "prompt": "p" * 9000,
                        "response": "r" * 50,
                        "total_tokens": 1000,
                        "estimated_cost_usd": 0.04,
                    }
                ],
                "tool_calls": [],
            },
            "agents": [],
        },
        {
            "name": "write",
            "type": "agent",
            "status": "failed",
            "error_message": "boom",
            "depends_on": ["research"],
            "agent": None,
            "agents": [],
            "child_nodes": [
                {
                    "name": "lane_0",
                    "type": "agent",
                    "status": "failed",
                    "agent": None,
                    "agents": [],
                }
            ],
        },
    ],
}


@pytest.fixture
def tools():
    return TemperTools()


def _with_run(run):
    return patch("temper_ai.api.data_service.get_workflow_execution", return_value=run)


class TestClip:
    def test_short_text_is_untouched(self):
        assert _clip("hello") == "hello"

    def test_long_text_says_how_much_was_dropped(self):
        out = _clip("x" * 5000, max_chars=100)
        assert out.startswith("x" * 100)
        assert "truncated 4900 more characters" in out

    def test_non_strings_pass_through(self):
        assert _clip({"a": 1}) == {"a": 1}
        assert _clip(None) is None


class TestGetRun:
    def test_summary_excludes_prompts_and_outputs(self, tools):
        with _with_run(RUN):
            result = tools.get_run("run-1")

        # The whole point: the expensive material must not be here.
        blob = str(result)
        assert "x" * 200 not in blob
        assert "p" * 200 not in blob
        assert result["status"] == "failed"
        assert result["total_tokens"] == 1234

    def test_names_the_failed_nodes(self, tools):
        with _with_run(RUN):
            result = tools.get_run("run-1")
        # Including one nested inside a container node.
        assert result["failed_nodes"] == ["write", "lane_0"]

    def test_unknown_run_is_an_explained_error(self, tools):
        with _with_run(None):
            result = tools.get_run("nope")
        assert "no run with id nope" in result["error"]


class TestNodeOutput:
    def test_returns_output_and_call_ids(self, tools):
        with _with_run(RUN):
            result = tools.get_node_output("run-1", "research")

        agent = result["agents"][0]
        assert agent["structured_output"] == {"found": True}
        assert agent["llm_call_ids"] == ["call-1"]
        assert "truncated" in agent["output"]  # 9000 chars, budget is 4000

    def test_respects_a_custom_budget(self, tools):
        with _with_run(RUN):
            result = tools.get_node_output("run-1", "research", max_chars=50)
        assert len(result["agents"][0]["output"]) < 200

    def test_unknown_node_lists_what_is_available(self, tools):
        with _with_run(RUN):
            result = tools.get_node_output("run-1", "typo")
        assert "typo" in result["error"]
        assert "research" in result["available"]
        assert "lane_0" in result["available"]  # nested nodes count


class TestLlmCall:
    def test_finds_a_call_and_truncates_the_prompt(self, tools):
        with _with_run(RUN):
            result = tools.get_llm_call("run-1", "call-1")
        assert result["model"] == "haiku"
        assert result["response"] == "r" * 50
        assert "truncated" in result["prompt"]

    def test_unknown_call_is_an_explained_error(self, tools):
        with _with_run(RUN):
            result = tools.get_llm_call("run-1", "missing")
        assert "missing" in result["error"]


class TestWait:
    def test_returns_as_soon_as_the_run_is_terminal(self, tools):
        with _with_run(RUN):
            result = tools.wait_for_run("run-1", timeout_seconds=5)
        assert result["timed_out"] is False
        assert result["status"] == "failed"

    def test_reports_a_timeout_without_failing(self, tools):
        running = {**RUN, "status": "running"}
        with _with_run(running):
            result = tools.wait_for_run("run-1", timeout_seconds=0.1)
        assert result["timed_out"] is True
        assert "call wait_for_run again" in result["hint"]

    def test_stops_early_on_an_unknown_run(self, tools):
        with _with_run(None):
            result = tools.wait_for_run("nope", timeout_seconds=30)
        assert "no run" in result["error"]


class TestNodeSummary:
    def test_keeps_shape_but_not_content(self):
        summary = _node_summary(RUN["nodes"][0])
        assert summary["agents"] == ["researcher"]
        assert summary["tokens"] == 1000
        assert "output" not in summary

    def test_nests_children(self):
        summary = _node_summary(RUN["nodes"][1])
        assert summary["children"][0]["name"] == "lane_0"
        assert summary["error"] == "boom"


class TestServerRegistration:
    def test_every_tool_is_registered_with_a_description(self):
        from temper_ai.mcp import build_server

        server = build_server()
        import anyio

        tools_list = anyio.run(server.list_tools)
        names = {t.name for t in tools_list}
        assert {
            "list_workflows",
            "run_workflow",
            "wait_for_run",
            "get_run",
            "get_node_output",
            "get_llm_call",
            "approve_gate",
        } <= names
        # The description is the only documentation the model gets.
        assert all(t.description for t in tools_list)

    def test_default_budget_is_modest(self):
        assert DEFAULT_MAX_CHARS <= 8000
