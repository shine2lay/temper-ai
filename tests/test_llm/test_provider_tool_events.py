"""Tool calls a provider runs itself reach the event log.

Claude Code runs Bash, WebSearch and every MCP server it is given inside
its own process and hands temper a finished answer. A run that made five
browser calls over MCP reported "Tool Calls 0". A provider that can see its
own tool activity reports it through `on_tool_event`, and it is recorded in
the same shape as a tool temper ran — so nothing downstream has to know the
difference, and the labels say which it was.
"""

from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.provider_tools import classify_tool
from temper_ai.llm.service import LLMService
from temper_ai.observability import EventType, get_events

from .conftest import MockProvider


class ToolRunningProvider(MockProvider):
    """A provider that, like Claude Code, runs tools itself and says so."""

    PROVIDER_NAME = "claude"

    def __init__(self, reports, **kwargs):
        super().__init__([_answer()], **kwargs)
        self.reports = reports

    def complete(self, messages, **kwargs):
        on_tool_event = kwargs.get("on_tool_event")
        assert on_tool_event is not None, "the service must offer the callback"
        for report in self.reports:
            on_tool_event(report)
        return super().complete(messages, **kwargs)


def _answer():
    return LLMResponse(
        content="ANSWER: v24.21.0", model="haiku", provider="claude",
        prompt_tokens=10, completion_tokens=5, total_tokens=15,
        latency_ms=50, finish_reason="stop",
    )


def _ctx():
    return CallContext(execution_id="run-1", agent_event_id="agent-ev", agent_name="researcher", node_path="find")


def _tool_events(execution_id="run-1"):
    return [e for e in get_events(execution_id=execution_id, limit=100) if e["type"].startswith("tool.call.")]


def test_an_mcp_call_the_provider_ran_is_recorded_and_labelled():
    provider = ToolRunningProvider([
        {"phase": "started", "call_id": "toolu_1", "tool_name": "mcp__browser__browser_status", "input": {}},
        {"phase": "completed", "call_id": "toolu_1", "tool_name": "mcp__browser__browser_status",
         "output": '{"browserId": "chrome:abc"}', "is_error": False, "duration_ms": 120},
    ])
    LLMService(provider).run([{"role": "user", "content": "look"}], context=_ctx())

    events = _tool_events()
    assert [e["type"] for e in events] == [EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED]
    started, completed = events
    for e in (started, completed):
        assert e["data"]["transport"] == "mcp"
        assert e["data"]["server"] == "browser"
        assert e["data"]["tool_name"] == "browser_status"
        assert e["data"]["raw_tool_name"] == "mcp__browser__browser_status"
        assert e["data"]["executed_by"] == "claude"
        assert e["data"]["call_id"] == "toolu_1"
        assert e["data"]["agent_id"] == "agent-ev"
    assert completed["data"]["duration_ms"] == 120
    assert "chrome:abc" in completed["data"]["output"]


def test_it_hangs_under_the_llm_call_like_a_temper_run_tool_would():
    provider = ToolRunningProvider([
        {"phase": "started", "call_id": "t", "tool_name": "Bash", "input": {"command": "ls"}},
        {"phase": "completed", "call_id": "t", "tool_name": "Bash", "output": "a b c", "is_error": False},
    ])
    LLMService(provider).run([{"role": "user", "content": "list"}], context=_ctx())

    llm = [e for e in get_events(execution_id="run-1", limit=100) if e["type"] == EventType.LLM_CALL_STARTED]
    assert len(llm) == 1
    for e in _tool_events():
        assert e["parent_id"] == llm[0]["id"]
        assert e["data"]["transport"] == "builtin"
        assert e["data"]["server"] is None


def test_a_tool_that_errored_is_a_failed_call():
    provider = ToolRunningProvider([
        {"phase": "started", "call_id": "x", "tool_name": "mcp__browser__browser_close_tab", "input": {"tabId": 9}},
        {"phase": "completed", "call_id": "x", "tool_name": "mcp__browser__browser_close_tab",
         "output": "Closing an unowned user tab requires userRequested: true", "is_error": True},
    ])
    LLMService(provider).run([{"role": "user", "content": "close"}], context=_ctx())

    types = [e["type"] for e in _tool_events()]
    assert types == [EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_FAILED]
    failed = _tool_events()[1]
    assert "unowned user tab" in failed["data"]["error"]


def test_duration_is_measured_when_the_provider_does_not_report_it():
    provider = ToolRunningProvider([
        {"phase": "started", "call_id": "d", "tool_name": "WebSearch", "input": {"q": "x"}},
        {"phase": "completed", "call_id": "d", "tool_name": "WebSearch", "output": "…", "is_error": False},
    ])
    LLMService(provider).run([{"role": "user", "content": "search"}], context=_ctx())
    completed = _tool_events()[1]
    assert isinstance(completed["data"]["duration_ms"], int)
    assert completed["data"]["duration_ms"] >= 0


def test_a_huge_tool_result_is_clipped_in_the_log():
    provider = ToolRunningProvider([
        {"phase": "started", "call_id": "big", "tool_name": "mcp__browser__browser_extract", "input": {}},
        {"phase": "completed", "call_id": "big", "tool_name": "mcp__browser__browser_extract",
         "output": "x" * 50_000, "is_error": False},
    ])
    LLMService(provider).run([{"role": "user", "content": "read"}], context=_ctx())
    out = _tool_events()[1]["data"]["output"]
    assert len(out) < 10_000
    assert "more chars" in out


def test_bad_reports_never_break_the_call():
    """A provider's bookkeeping must not fail its answer."""
    provider = ToolRunningProvider([
        {"phase": "nonsense"},
        {"phase": "completed", "call_id": "never-started", "tool_name": "Bash", "output": "", "is_error": False},
    ])
    result = LLMService(provider).run([{"role": "user", "content": "go"}], context=_ctx())
    assert result.output == "ANSWER: v24.21.0"


def test_classification_by_name():
    assert classify_tool("mcp__browser__browser_status") == {"transport": "mcp", "server": "browser", "tool": "browser_status"}
    assert classify_tool("mcp__temper__get_run") == {"transport": "mcp", "server": "temper", "tool": "get_run"}
    assert classify_tool("Bash") == {"transport": "builtin", "server": None, "tool": "Bash"}
    assert classify_tool("WebSearch") == {"transport": "builtin", "server": None, "tool": "WebSearch"}
    # temper's own wrapper names MCP tools "<server>.<tool>"; only a configured server counts
    assert classify_tool("git.git_status", {"git"}) == {"transport": "mcp", "server": "git", "tool": "git_status"}
    assert classify_tool("git.git_status", set()) == {"transport": "builtin", "server": None, "tool": "git.git_status"}
    # a malformed mcp__ name is not silently promoted
    assert classify_tool("mcp__")["transport"] == "builtin"
