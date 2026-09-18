"""Tests for ToolExecutor."""

import tempfile
import time
from typing import Any

import pytest

from temper_ai.observability import EventType
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.executor import ALL_TOOLS, ToolExecutor


class SlowTool(BaseTool):
    name = "slow"
    description = "Sleeps for a bit"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **params: Any) -> ToolResult:
        time.sleep(params.get("duration", 5))
        return ToolResult(success=True, result="done")


class FailingTool(BaseTool):
    name = "failing"
    description = "Always raises"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **params: Any) -> ToolResult:
        raise RuntimeError("Tool exploded")


class TestExecutorBasics:
    def test_execute_registered_tool(self):
        from temper_ai.tools.calculator import Calculator
        executor = ToolExecutor()
        executor.register_tools({"Calculator": Calculator()})

        result = executor.execute("Calculator", {"expression": "2 + 3"}, allowed_tools=ALL_TOOLS)
        assert result.success is True
        assert result.result == "5"

    def test_unknown_tool(self):
        executor = ToolExecutor()
        result = executor.execute("NonExistent", {}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_multiple_tools(self):
        from temper_ai.tools.bash import Bash
        from temper_ai.tools.calculator import Calculator

        executor = ToolExecutor()
        executor.register_tools({
            "Calculator": Calculator(),
            "Bash": Bash(),
        })

        r1 = executor.execute("Calculator", {"expression": "10 * 5"}, allowed_tools=ALL_TOOLS)
        assert r1.result == "50"

        r2 = executor.execute("Bash", {"command": "echo hello"}, allowed_tools=ALL_TOOLS)
        assert r2.success is True
        assert "hello" in r2.result


class TestExecutorTimeout:
    def test_timeout_kills_slow_tool(self):
        executor = ToolExecutor(default_timeout=1)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute("slow", {"duration": 10}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()

    def test_custom_timeout_per_call(self):
        executor = ToolExecutor(default_timeout=30)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute("slow", {"duration": 10}, allowed_tools=ALL_TOOLS, timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()


class TestExecutorErrorHandling:
    def test_tool_exception_caught(self):
        executor = ToolExecutor()
        executor.register_tools({"failing": FailingTool()})

        result = executor.execute("failing", {}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "RuntimeError" in result.error
        assert "exploded" in result.error

    def test_context_manager(self):
        with ToolExecutor() as executor:
            from temper_ai.tools.calculator import Calculator
            executor.register_tools({"Calculator": Calculator()})
            result = executor.execute("Calculator", {"expression": "1 + 1"}, allowed_tools=ALL_TOOLS)
            assert result.result == "2"


class TestWorkspaceSandbox:
    def test_path_within_workspace(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        import os
        path = os.path.join(tmpdir, "safe.txt")
        result = executor.execute("FileWriter", {"file_path": path, "content": "ok"}, allowed_tools=ALL_TOOLS)
        assert result.success is True

    def test_path_escapes_workspace(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        result = executor.execute(
            "FileWriter", {"file_path": "/tmp/escape.txt", "content": "bad"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        assert "escapes workspace" in result.error.lower()

    def test_null_byte_in_path(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        result = executor.execute(
            "FileWriter", {"file_path": f"{tmpdir}/evil\x00.txt", "content": "x"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        # Null byte causes either our explicit check or an OS-level path error
        assert "null" in result.error.lower() or "invalid" in result.error.lower()

    def test_no_workspace_root_allows_all(self):
        """When workspace_root is not set, path validation is skipped."""
        from temper_ai.tools.calculator import Calculator
        executor = ToolExecutor()  # no workspace_root
        executor.register_tools({"Calculator": Calculator()})
        result = executor.execute("Calculator", {"expression": "1"}, allowed_tools=ALL_TOOLS)
        assert result.success is True


class TestSkipPolicies:
    """Test that skip_policies in execution context bypasses matching policies."""

    def _make_budget_engine(self):
        """Create a policy engine with a budget policy that always denies."""
        from temper_ai.safety.engine import PolicyEngine
        return PolicyEngine.from_config({
            "policies": [{"type": "budget", "max_cost_usd": 0.001}],
        })

    def test_budget_blocks_without_skip(self):
        """Budget policy should block when cost exceeds limit."""
        from temper_ai.tools.calculator import Calculator
        engine = self._make_budget_engine()
        executor = ToolExecutor(policy_engine=engine)
        executor.register_tools({"Calculator": Calculator()})
        executor.run_cost_usd = 1.0  # Over the 0.001 limit

        result = executor.execute("Calculator", {"expression": "1+1"}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "budget" in result.error.lower() or "policy" in result.error.lower()

    def test_skip_policies_bypasses_budget(self):
        """With skip_policies=['budget'], budget policy should be skipped."""
        from temper_ai.tools.calculator import Calculator
        engine = self._make_budget_engine()
        executor = ToolExecutor(policy_engine=engine)
        executor.register_tools({"Calculator": Calculator()})
        executor.run_cost_usd = 1.0  # Over the limit

        result = executor.execute(
            "Calculator", {"expression": "1+1"}, allowed_tools=ALL_TOOLS,
            context={"skip_policies": ["budget"]},
        )
        assert result.success is True
        assert result.result == "2"

    def test_skip_policies_only_skips_matching(self):
        """Skipping 'budget' should not skip other policies like file_access."""
        from temper_ai.safety.engine import PolicyEngine
        from temper_ai.tools.file_writer import FileWriter

        engine = PolicyEngine.from_config({
            "policies": [
                {"type": "budget", "max_cost_usd": 0.001},
                {"type": "file_access", "denied_paths": ["/etc"]},
            ],
        })
        executor = ToolExecutor(policy_engine=engine, workspace_root="/tmp")
        executor.register_tools({"FileWriter": FileWriter()})
        executor.run_cost_usd = 1.0  # Over budget

        # Skip budget, but file_access should still block /etc paths
        result = executor.execute(
            "FileWriter", {"file_path": "/etc/passwd", "content": "x"}, allowed_tools=ALL_TOOLS,
            context={"skip_policies": ["budget"]},
        )
        assert result.success is False


class EchoTool(BaseTool):
    name = "echo"
    description = "Returns what it was given"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, config=None):
        super().__init__(config)
        self.calls: list[dict] = []

    def execute(self, **params: Any) -> ToolResult:
        self.calls.append(params)
        return ToolResult(success=True, result="echoed")


class RemotePathTool(BaseTool):
    """A tool whose 'path' names a file somewhere else (an MCP tool does this)."""
    name = "remote"
    description = "Reads a path on another machine"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(success=True, result=f"remote:{params.get('path')}")


class TestWorkspaceSandboxScope:
    """The workspace sandbox judges LOCAL paths only.

    path/file_path/... are resolved against this process's cwd and compared to
    workspace_root. For a tool that opens files here that is the point. For a
    tool that forwards its arguments to another process it is simply wrong:
    every GitHub `get_file_contents(path="README.md")` was refused with
    "escapes workspace root" before local_paths existed.
    """

    def test_remote_path_tool_is_not_sandboxed(self):
        with tempfile.TemporaryDirectory() as workspace:
            ex = ToolExecutor(workspace_root=workspace)
            ex.register_tools({"remote": RemotePathTool()})
            for path in ("README.md", "src/main.py", "/etc/passwd"):
                result = ex.execute("remote", {"path": path}, allowed_tools=ALL_TOOLS)
                assert result.success is True, f"{path} should reach the tool"
                assert result.result == f"remote:{path}"

    def test_local_path_tool_is_still_sandboxed(self):
        from temper_ai.tools.file_writer import FileWriter

        with tempfile.TemporaryDirectory() as workspace:
            ex = ToolExecutor(workspace_root=workspace)
            ex.register_tools({"FileWriter": FileWriter()})
            result = ex.execute(
                "FileWriter", {"file_path": "/tmp/escape.txt", "content": "x"},
                allowed_tools=ALL_TOOLS,
            )
            assert result.success is False
            assert "escapes workspace root" in result.error

    def test_default_is_local(self):
        """Opting out is deliberate: a tool that says nothing gets the sandbox."""
        from temper_ai.tools.file_writer import FileWriter

        assert BaseTool.local_paths is True
        assert FileWriter().local_paths is True


class TestToolDeclarationGate:
    """execute() runs a tool only if the CALLER declared it.

    One executor per run holds every node's tools registered together, so
    without a per-call scope any name reaching any caller would run: an agent
    shown only `github-ci.*` could execute `github-full.merge_pull_request` —
    hallucinated, or planted in a tool result (GitHub issue bodies, PR
    descriptions and CI logs are third-party text).

    ``allowed_tools`` is required and keyword-only, so this is a property of the
    interface rather than of which object the caller happens to hold.
    """

    def _executor(self):
        ex = ToolExecutor()
        mine, theirs = EchoTool(), EchoTool()
        ex.register_tools({"github-ci.get_job_logs": mine, "github-full.merge_pull_request": theirs})
        return ex, mine, theirs

    def test_execute_cannot_be_called_without_declaring(self):
        """The interpreter enforces it — not a convention a caller may skip."""
        ex, _, _ = self._executor()
        with pytest.raises(TypeError, match="allowed_tools"):
            ex.execute("github-ci.get_job_logs", {})  # type: ignore[call-arg]

    def test_declared_tool_runs(self):
        ex, mine, _ = self._executor()
        result = ex.execute(
            "github-ci.get_job_logs", {"run_id": 1},
            allowed_tools=["github-ci.get_job_logs"],
        )
        assert result.success is True
        assert result.result == "echoed"
        assert mine.calls == [{"run_id": 1}]

    def test_undeclared_tool_is_refused_and_never_reaches_the_tool(self, monkeypatch):
        ex, _, theirs = self._executor()
        events: list[tuple] = []
        monkeypatch.setattr(
            "temper_ai.tools.executor.record",
            lambda et, **kw: events.append((et, kw)),
        )

        result = ex.execute(
            "github-full.merge_pull_request", {"pullNumber": 1},
            allowed_tools=["github-ci.get_job_logs"],
            context={"execution_id": "run-1", "parent_id": "evt-9", "agent_name": "ci_diagnoser"},
        )

        assert result.success is False
        assert "not available to agent 'ci_diagnoser'" in result.error
        assert "github-ci.get_job_logs" in result.error, "the caller is told what it does have"
        assert theirs.calls == [], "the other agent's tool was never invoked"

        assert len(events) == 1
        event_type, kwargs = events[0]
        assert event_type is EventType.TOOL_BLOCKED
        assert kwargs["status"] == "blocked"
        assert kwargs["execution_id"] == "run-1"
        assert kwargs["parent_id"] == "evt-9"
        assert kwargs["data"] == {
            "tool_name": "github-full.merge_pull_request",
            "reason": "not_declared_by_caller",
            "agent_name": "ci_diagnoser",
            "declared": ["github-ci.get_job_logs"],
        }

    def test_refusal_does_not_reveal_whether_the_tool_exists(self):
        """Undeclared registered tool and undeclared unknown tool look the same."""
        ex, _, _ = self._executor()
        registered = ex.execute("github-full.merge_pull_request", {}, allowed_tools=["x"])
        unknown = ex.execute("no_such_tool_at_all", {}, allowed_tools=["x"])
        assert registered.error.replace("github-full.merge_pull_request", "T") == unknown.error.replace(
            "no_such_tool_at_all", "T"
        )
        # declared-but-unregistered still reports Unknown tool, as before
        assert "Unknown tool" in ex.execute("ghost", {}, allowed_tools=["ghost"]).error

    def test_empty_declaration_allows_nothing(self):
        ex, _, _ = self._executor()
        result = ex.execute("github-ci.get_job_logs", {}, allowed_tools=[])
        assert result.success is False
        assert "declared tools: none" in result.error
        assert "this caller" in result.error, "no agent_name in context → generic wording"

    def test_all_tools_is_an_explicit_opt_out(self):
        """Trusted internal callers (ScriptAgent, these tests) say so out loud."""
        ex, mine, theirs = self._executor()
        assert ex.execute("github-ci.get_job_logs", {}, allowed_tools=ALL_TOOLS).success is True
        assert ex.execute("github-full.merge_pull_request", {}, allowed_tools=ALL_TOOLS).success is True
        assert mine.calls == [{}] and theirs.calls == [{}]
        assert "anything" in ALL_TOOLS and repr(ALL_TOOLS) == "ALL_TOOLS"

    def test_gate_runs_before_safety_policies_and_sandbox(self):
        """An undeclared tool is refused without consulting policies at all."""
        from temper_ai.safety.engine import PolicyEngine

        engine = PolicyEngine.from_config({"policies": [{"type": "budget", "max_cost_usd": 0.001}]})
        ex = ToolExecutor(policy_engine=engine)
        ex.register_tools({"Echo": EchoTool()})
        ex.run_cost_usd = 1.0  # would trip the budget policy
        result = ex.execute("Echo", {}, allowed_tools=[])
        assert "is not available" in result.error, "refused by the gate, not the budget policy"
