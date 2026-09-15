"""Tests for the MCP tool layer.

The point of these tools is that an agent can drive temper without its
context being flooded, so the tests care most about what is *left out* of
each response and about failures being explained rather than silent.
"""

from unittest.mock import patch  # noqa: F401

import anyio  # noqa: E402
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

    def test_small_structures_keep_their_shape(self):
        assert _clip({"a": 1}) == {"a": 1}
        assert _clip(None) is None
        assert _clip([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]

    def test_structures_are_bounded_too(self):
        """A chat prompt is a list of message dicts, so bounding only str
        left the largest field in the payload unbounded."""
        prompt = [{"role": "system", "content": "x" * 9000},
                  {"role": "user", "content": "y" * 9000}]
        out = _clip(prompt, max_chars=500)
        assert len(str(out)) < 1500
        assert "truncated" in str(out)

    def test_a_chat_prompt_stays_readable_as_messages(self):
        # Every role visible, each message opening with real text, rather
        # than the whole prompt flattened into one truncated blob.
        prompt = [
            {"role": "system", "content": "s" * 5000},
            {"role": "user", "content": "u" * 5000},
        ]
        out = _clip(prompt, max_chars=2000)
        assert isinstance(out, list)
        assert [m["role"] for m in out] == ["system", "user"]
        assert out[0]["content"].startswith("s" * 256)
        assert "truncated" in out[0]["content"]

    def test_falls_back_to_text_when_there_are_too_many_pieces(self):
        huge = [{"role": "user", "content": "x" * 400} for _ in range(200)]
        out = _clip(huge, max_chars=1000)
        assert isinstance(out, str)
        assert "truncated" in out


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
            result = anyio.run(tools.wait_for_run, "run-1", 5)
        assert result["timed_out"] is False
        assert result["status"] == "failed"

    def test_reports_a_timeout_without_failing(self, tools):
        running = {**RUN, "status": "running"}
        with _with_run(running):
            result = anyio.run(tools.wait_for_run, "run-1", 0.1)
        assert result["timed_out"] is True
        assert "call wait_for_run again" in result["hint"]

    def test_stops_early_on_an_unknown_run(self, tools):
        with _with_run(None):
            result = anyio.run(tools.wait_for_run, "nope", 30)
        assert "no run" in result["error"]

    def test_waiting_does_not_block_the_event_loop(self, tools):
        """The bug this replaced: FastMCP calls sync tools directly on the
        event loop, so sleeping inside one froze the whole server — the
        dashboard and the API stopped answering while an agent waited."""
        running = {**RUN, "status": "running"}
        progressed = 0
        progressed_when_wait_returned = -1

        async def scenario():
            nonlocal progressed, progressed_when_wait_returned

            async def other_work():
                nonlocal progressed
                while True:
                    await anyio.sleep(0.05)
                    progressed += 1

            async with anyio.create_task_group() as tg:
                tg.start_soon(other_work)
                with _with_run(running):
                    await tools.wait_for_run("run-1", timeout_seconds=0.4)
                # Sampled here, not after the task group drains, or a
                # blocking implementation would look fine in hindsight.
                progressed_when_wait_returned = progressed
                tg.cancel_scope.cancel()

        anyio.run(scenario)
        assert progressed_when_wait_returned >= 3


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


class TestAllowedHosts:
    """The SDK rejects unknown Host headers; serving under a real hostname
    means naming it, and forgetting to is a 421 that looks like a network
    fault rather than a configuration one."""

    def test_localhost_works_without_configuration(self, monkeypatch):
        from temper_ai.mcp.server import _security_settings

        monkeypatch.delenv("TEMPER_MCP_ALLOWED_HOSTS", raising=False)
        settings = _security_settings()
        assert "localhost:8420" in settings.allowed_hosts
        assert "127.0.0.1:8420" in settings.allowed_hosts

    def test_configured_hosts_are_added_with_both_schemes(self, monkeypatch):
        from temper_ai.mcp.server import _security_settings

        monkeypatch.setenv("TEMPER_MCP_ALLOWED_HOSTS", "temper.example.com, host.ts.net")
        settings = _security_settings()
        assert "temper.example.com" in settings.allowed_hosts
        assert "host.ts.net" in settings.allowed_hosts  # whitespace trimmed
        assert "https://temper.example.com" in settings.allowed_origins
        # Local access keeps working once a gateway name is added.
        assert "localhost" in settings.allowed_hosts

    def test_empty_configuration_adds_nothing(self, monkeypatch):
        from temper_ai.mcp.server import _security_settings

        monkeypatch.setenv("TEMPER_MCP_ALLOWED_HOSTS", "  ,  ")
        settings = _security_settings()
        assert settings.allowed_hosts == [
            "localhost",
            "localhost:8420",
            "127.0.0.1",
            "127.0.0.1:8420",
        ]
