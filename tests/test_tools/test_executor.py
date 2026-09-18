"""Tests for ToolExecutor."""

import tempfile
import time
from typing import Any

from temper_ai.observability import EventType
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.executor import ToolExecutor


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

        result = executor.execute("Calculator", {"expression": "2 + 3"})
        assert result.success is True
        assert result.result == "5"

    def test_unknown_tool(self):
        executor = ToolExecutor()
        result = executor.execute("NonExistent", {})
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

        r1 = executor.execute("Calculator", {"expression": "10 * 5"})
        assert r1.result == "50"

        r2 = executor.execute("Bash", {"command": "echo hello"})
        assert r2.success is True
        assert "hello" in r2.result


class TestExecutorTimeout:
    def test_timeout_kills_slow_tool(self):
        executor = ToolExecutor(default_timeout=1)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute("slow", {"duration": 10})
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()

    def test_custom_timeout_per_call(self):
        executor = ToolExecutor(default_timeout=30)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute("slow", {"duration": 10}, timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()


class TestExecutorErrorHandling:
    def test_tool_exception_caught(self):
        executor = ToolExecutor()
        executor.register_tools({"failing": FailingTool()})

        result = executor.execute("failing", {})
        assert result.success is False
        assert "RuntimeError" in result.error
        assert "exploded" in result.error

    def test_context_manager(self):
        with ToolExecutor() as executor:
            from temper_ai.tools.calculator import Calculator
            executor.register_tools({"Calculator": Calculator()})
            result = executor.execute("Calculator", {"expression": "1 + 1"})
            assert result.result == "2"


class TestWorkspaceSandbox:
    def test_path_within_workspace(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        import os
        path = os.path.join(tmpdir, "safe.txt")
        result = executor.execute("FileWriter", {"file_path": path, "content": "ok"})
        assert result.success is True

    def test_path_escapes_workspace(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        result = executor.execute("FileWriter", {"file_path": "/tmp/escape.txt", "content": "bad"})
        assert result.success is False
        assert "escapes workspace" in result.error.lower()

    def test_null_byte_in_path(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.file_writer import FileWriter

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"FileWriter": FileWriter()})

        result = executor.execute("FileWriter", {"file_path": f"{tmpdir}/evil\x00.txt", "content": "x"})
        assert result.success is False
        # Null byte causes either our explicit check or an OS-level path error
        assert "null" in result.error.lower() or "invalid" in result.error.lower()

    def test_no_workspace_root_allows_all(self):
        """When workspace_root is not set, path validation is skipped."""
        from temper_ai.tools.calculator import Calculator
        executor = ToolExecutor()  # no workspace_root
        executor.register_tools({"Calculator": Calculator()})
        result = executor.execute("Calculator", {"expression": "1"})
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

        result = executor.execute("Calculator", {"expression": "1+1"})
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
            "Calculator", {"expression": "1+1"},
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
            "FileWriter", {"file_path": "/etc/passwd", "content": "x"},
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


class TestScopedToolExecutor:
    """A per-agent view: only the agent's declared tools resolve.

    The executor is per RUN and holds every node's tools together, so an agent
    shown only `github-ci.*` could otherwise execute `github-full.merge_pull_request`
    if that name reached the model — hallucinated, or planted in a tool result
    (GitHub issue bodies, PR descriptions and CI logs are untrusted input).
    """

    def _root(self):
        root = ToolExecutor()
        mine, theirs = EchoTool(), EchoTool()
        root.register_tools({"github-ci.get_job_logs": mine, "github-full.merge_pull_request": theirs})
        return root, mine, theirs

    def test_declared_tool_executes_through_the_root(self):
        root, mine, _ = self._root()
        view = root.scoped(["github-ci.get_job_logs"], agent_name="ci_diagnoser")
        result = view.execute("github-ci.get_job_logs", {"run_id": 1})
        assert result.success is True
        assert result.result == "echoed"
        assert mine.calls == [{"run_id": 1}]

    def test_undeclared_tool_is_refused_and_never_reaches_the_tool(self, monkeypatch):
        root, _, theirs = self._root()
        events: list[tuple] = []
        monkeypatch.setattr(
            "temper_ai.tools.executor.record",
            lambda et, **kw: events.append((et, kw)),
        )
        view = root.scoped(["github-ci.get_job_logs"], agent_name="ci_diagnoser")

        result = view.execute(
            "github-full.merge_pull_request", {"pullNumber": 1},
            context={"execution_id": "run-1", "parent_id": "evt-9"},
        )

        assert result.success is False
        assert "not available to agent 'ci_diagnoser'" in result.error
        assert "github-ci.get_job_logs" in result.error, "the model is told what it does have"
        assert theirs.calls == [], "the other agent's tool was never invoked"

        assert len(events) == 1
        event_type, kwargs = events[0]
        assert event_type is EventType.TOOL_BLOCKED
        assert kwargs["status"] == "blocked"
        assert kwargs["execution_id"] == "run-1"
        assert kwargs["parent_id"] == "evt-9"
        assert kwargs["data"] == {
            "tool_name": "github-full.merge_pull_request",
            "reason": "not_declared_by_agent",
            "agent_name": "ci_diagnoser",
            "declared": ["github-ci.get_job_logs"],
        }

    def test_get_tool_is_scoped_too(self):
        root, mine, _ = self._root()
        view = root.scoped(["github-ci.get_job_logs"])
        assert view.get_tool("github-ci.get_job_logs") is mine
        assert view.get_tool("github-full.merge_pull_request") is None
        assert root.get_tool("github-full.merge_pull_request") is not None, "root is unchanged"

    def test_empty_scope_allows_nothing(self):
        root, _, _ = self._root()
        view = root.scoped([], agent_name="no_tools")
        assert view.execute("github-ci.get_job_logs", {}).success is False
        assert "declared tools: none" in view.execute("github-ci.get_job_logs", {}).error

    def test_rescoping_widens_from_root_not_from_the_parent_view(self):
        """A Delegate child declares its own tools; it must not inherit the
        parent's narrower list."""
        root, _, theirs = self._root()
        parent = root.scoped(["github-ci.get_job_logs"], agent_name="parent")
        child = parent.scoped(["github-full.merge_pull_request"], agent_name="child")
        assert child.execute("github-full.merge_pull_request", {}).success is True
        assert theirs.calls == [{}]
        # and the child is still scoped — it did not inherit the parent's tool
        assert child.execute("github-ci.get_job_logs", {}).success is False

    def test_view_shares_run_state_and_never_shuts_down_the_pool(self):
        root, _, _ = self._root()
        view = root.scoped(["github-ci.get_job_logs"], agent_name="a")
        view.track_usage(cost_usd=0.25, tokens=100)
        assert root.run_cost_usd == 0.25 and root.run_tokens == 100
        assert view.run_cost_usd == 0.25, "passthrough reads the root's totals"
        assert view.workspace_root == root.workspace_root

        view.shutdown()  # a view does not own the pool
        assert root.execute("github-ci.get_job_logs", {}).success is True
        root.shutdown()
