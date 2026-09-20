"""Tests for ToolExecutor."""

import tempfile
import threading
import time
from pathlib import Path
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
    # The tool only has to outlive its timeout; it used to sleep 10s against a
    # 1s timeout, and shutdown() then joined the abandoned thread — 20s of the
    # suite's wall clock spent waiting for sleeps nobody was measuring.
    OVERRUN = 1.3  # seconds; must exceed the 1s timeout floor (timeout is int)

    def test_timeout_stops_waiting_for_a_slow_tool(self):
        """Named for what it does: the WAIT ends. See the kill test below."""
        executor = ToolExecutor(default_timeout=1)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute(
            "slow", {"duration": self.OVERRUN}, allowed_tools=ALL_TOOLS
        )
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()

    def test_custom_timeout_per_call(self):
        """A per-call timeout overrides a longer default."""
        executor = ToolExecutor(default_timeout=30)
        executor.register_tools({"slow": SlowTool()})

        result = executor.execute(
            "slow", {"duration": self.OVERRUN}, allowed_tools=ALL_TOOLS, timeout=1
        )
        assert result.success is False
        assert "timed out" in result.error.lower()
        executor.shutdown()

    def test_a_timed_out_tool_is_not_actually_killed(self):
        """The timeout abandons the future; the thread runs to completion.

        Pinned because it is surprising and has teeth: a tool reported as
        "timed out" still holds a pool worker and its side effects still
        land afterwards. It is also why shutdown() blocks for as long as
        the runaway tool takes.
        """
        finished = threading.Event()

        class Runaway(BaseTool):
            name = "runaway"
            description = "Outlives its timeout, then completes anyway"
            parameters = {"type": "object", "properties": {}}

            def execute(self, **params: Any) -> ToolResult:
                time.sleep(TestExecutorTimeout.OVERRUN)
                finished.set()
                return ToolResult(success=True, result="side effect landed")

        executor = ToolExecutor(default_timeout=1)
        executor.register_tools({"runaway": Runaway()})

        result = executor.execute("runaway", {}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "timed out" in result.error.lower()
        assert not finished.is_set(), "tool should still be running at timeout"

        # It was never cancelled: it finishes on its own shortly after.
        assert finished.wait(timeout=5), "abandoned tool never completed"
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
        from temper_ai.tools.write import Write

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"Write": Write()})

        import os
        path = os.path.join(tmpdir, "safe.txt")
        result = executor.execute("Write", {"file_path": path, "content": "ok"}, allowed_tools=ALL_TOOLS)
        assert result.success is True

    def test_path_escapes_workspace(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.write import Write

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"Write": Write()})

        result = executor.execute(
            "Write", {"file_path": "/tmp/escape.txt", "content": "bad"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        assert "escapes workspace" in result.error.lower()

    def test_null_byte_in_path(self):
        tmpdir = tempfile.mkdtemp()
        from temper_ai.tools.write import Write

        executor = ToolExecutor(workspace_root=tmpdir)
        executor.register_tools({"Write": Write()})

        result = executor.execute(
            "Write", {"file_path": f"{tmpdir}/evil\x00.txt", "content": "x"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        # Null byte causes either our explicit check or an OS-level path error
        assert "null" in result.error.lower() or "invalid" in result.error.lower()

    def test_no_workspace_root_still_runs_tools_without_paths(self):
        """A tool with nothing to confine runs whether or not there is a workspace."""
        from temper_ai.tools.calculator import Calculator
        executor = ToolExecutor()  # no workspace_root
        executor.register_tools({"Calculator": Calculator()})
        result = executor.execute("Calculator", {"expression": "1"}, allowed_tools=ALL_TOOLS)
        assert result.success is True


class TestWorkspaceFailsClosed:
    """No workspace is not no sandbox.

    The run's workspace used to be the only one, and optional: with none set,
    path validation was skipped, so a run whose worktree is made by a node
    mid-run (the run itself starting with workspace_path=null) had its later
    agents reading and writing anywhere. Now a tool that takes a path does
    not run without a workspace, and a node can name its own — which must
    lie inside the run's when there is one.
    """

    def _tools(self):
        from temper_ai.tools.read import Read
        from temper_ai.tools.write import Write
        return {"Read": Read(), "Write": Write()}

    def test_path_tool_refused_without_any_workspace(self, tmp_path, monkeypatch):
        target = tmp_path / "anywhere.txt"
        ex = ToolExecutor()
        ex.register_tools(self._tools())
        events: list[tuple] = []
        monkeypatch.setattr(
            "temper_ai.tools.executor.record", lambda et, **kw: events.append((et, kw)),
        )
        result = ex.execute(
            "Write", {"path": str(target), "content": "x"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        assert "no workspace" in result.error
        assert "workspace_path" in result.error  # says how to fix it
        assert not target.exists()
        assert [(et, kw["data"]["reason"]) for et, kw in events] == [
            (EventType.TOOL_BLOCKED, "no_workspace"),
        ]

    def test_call_workspace_stands_in_for_the_runs(self, tmp_path):
        """A node's workspace_path confines its tools when the run has none."""
        ws = tmp_path / "worktree"
        ws.mkdir()
        ex = ToolExecutor()
        ex.register_tools(self._tools())
        ok = ex.execute(
            "Write", {"path": "notes.md", "content": "hi"}, allowed_tools=ALL_TOOLS, workspace=str(ws),
        )
        assert ok.success is True, ok.error
        assert (ws / "notes.md").read_text() == "hi"  # relative path resolved against the workspace
        out = ex.execute(
            "Write", {"path": str(tmp_path / "outside.txt"), "content": "no"},
            allowed_tools=ALL_TOOLS, workspace=str(ws),
        )
        assert out.success is False
        assert "escapes workspace" in out.error
        assert not (tmp_path / "outside.txt").exists()

    def test_relative_path_is_judged_from_the_workspace_not_the_cwd(self, tmp_path, monkeypatch):
        """'.' means the workspace. Judged from the server's cwd it would be an 'escape'."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("a")
        monkeypatch.chdir(tmp_path)  # somewhere else entirely
        ex = ToolExecutor(workspace_root=str(ws))
        ex.register_tools(self._tools())
        result = ex.execute("Read", {"path": "a.txt"}, allowed_tools=ALL_TOOLS)
        assert result.success is True, result.error
        assert "a" in result.result
        up = ex.execute("Read", {"path": "../secret.txt"}, allowed_tools=ALL_TOOLS)
        assert up.success is False and "escapes workspace" in up.error

    def test_call_workspace_must_lie_inside_the_runs(self, tmp_path):
        """workspace_path can come from another node's output; it cannot move the sandbox."""
        run_ws = tmp_path / "run"
        run_ws.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        ex = ToolExecutor(workspace_root=str(run_ws))
        ex.register_tools(self._tools())
        result = ex.execute(
            "Write", {"path": "x.txt", "content": "x"}, allowed_tools=ALL_TOOLS, workspace=str(elsewhere),
        )
        assert result.success is False
        assert "outside this run's workspace" in result.error
        assert not (elsewhere / "x.txt").exists()
        sub = run_ws / "worktrees" / "feat"
        sub.mkdir(parents=True)
        ok = ex.execute(
            "Write", {"path": "x.txt", "content": "x"}, allowed_tools=ALL_TOOLS, workspace=str(sub),
        )
        assert ok.success is True, ok.error
        assert (sub / "x.txt").exists()

    def test_bash_runs_in_the_call_workspace(self, tmp_path):
        from temper_ai.tools.bash import Bash
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        ex = ToolExecutor(workspace_root=str(tmp_path))
        ex.register_tools({"Bash": Bash()})
        ra = ex.execute("Bash", {"command": "pwd"}, allowed_tools=ALL_TOOLS, workspace=str(a))
        rb = ex.execute("Bash", {"command": "pwd"}, allowed_tools=ALL_TOOLS, workspace=str(b))
        root = ex.execute("Bash", {"command": "pwd"}, allowed_tools=ALL_TOOLS)
        assert ra.result.strip() == str(a.resolve())
        assert rb.result.strip() == str(b.resolve())
        assert root.result.strip() == str(tmp_path.resolve())
        # The registered instance was not moved: the per-call copy is what ran.
        assert ex.get_tool("Bash").config["workspace_root"] == str(tmp_path)

    def test_bash_without_any_workspace_still_runs(self):
        """Bash has no path to confine; the allowlist is its gate. The worktree
        node itself needs this: it runs before there is a workspace."""
        from temper_ai.tools.bash import Bash
        ex = ToolExecutor()
        ex.register_tools({"Bash": Bash()})
        assert ex.execute("Bash", {"command": "echo ok"}, allowed_tools=ALL_TOOLS).success is True

    def test_git_runs_in_the_workspace(self, tmp_path):
        """Registration does `Git()` with no workspace: it used to run in the server's cwd."""
        import subprocess

        from temper_ai.tools.git import Git
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        ex = ToolExecutor(workspace_root=str(tmp_path))
        ex.register_tools({"git": Git()})
        result = ex.execute(
            "git", {"command": "rev-parse --show-toplevel"}, allowed_tools=ALL_TOOLS, workspace=str(repo),
        )
        assert result.success is True, result.result
        assert result.result.strip() == str(repo.resolve())


class TestScratchDir:
    """A second root the sandbox allows, for the temporary files nodes want.

    The first stray the fail-closed sandbox refused in production was a
    reviewer writing a commit message to /tmp. Refused, the model moved the
    same file outside the workspace through Bash seven seconds later: a
    refusal alone teaches a model to route around the guardrail. So a run has
    a scratch directory, and the refusal names it.
    """

    def _tools(self):
        from temper_ai.tools.read import Read
        from temper_ai.tools.write import Write
        return {"Read": Read(), "Write": Write()}

    def _executor(self, root):
        ws = root / "ws"
        ws.mkdir()
        ex = ToolExecutor(workspace_root=str(ws))
        ex.register_tools(self._tools())
        return ex, ws

    def test_the_refusal_names_the_scratch_dir(self, tmp_path, monkeypatch):
        ex, _ = self._executor(tmp_path)
        events: list[tuple] = []
        monkeypatch.setattr(
            "temper_ai.tools.executor.record", lambda et, **kw: events.append((et, kw)),
        )
        stray = tmp_path / "commitmsg.txt"
        result = ex.execute("Write", {"path": str(stray), "content": "x"}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert "escapes workspace" in result.error
        assert not stray.exists()
        scratch = ex._scratch_dir  # made by the refusal itself, not by asking for it
        assert scratch is not None
        assert scratch in result.error  # the node is told where temporary files go
        assert Path(scratch).is_dir()  # and it exists by the time it is told
        [(et, data)] = [(et, kw["data"]) for et, kw in events]
        assert et is EventType.TOOL_BLOCKED
        assert data["reason"] == "workspace_violation"
        assert data["scratch_dir"] == scratch

    def test_files_in_scratch_are_allowed(self, tmp_path):
        ex, _ = self._executor(tmp_path)
        note = Path(ex.scratch_dir) / "notes" / "commitmsg.txt"
        w = ex.execute("Write", {"path": str(note), "content": "feat: x"}, allowed_tools=ALL_TOOLS)
        assert w.success is True, w.error
        assert note.read_text() == "feat: x"
        r = ex.execute("Read", {"path": str(note)}, allowed_tools=ALL_TOOLS)
        assert r.success is True, r.error
        assert "feat: x" in r.result

    def test_scratch_is_reachable_from_a_node_workspace(self, tmp_path):
        """A node confined to a worktree inside the run's workspace still has the run's scratch."""
        ex, ws = self._executor(tmp_path)
        worktree = ws / "worktrees" / "feat"
        worktree.mkdir(parents=True)
        note = Path(ex.scratch_dir) / "diff.txt"
        w = ex.execute(
            "Write", {"path": str(note), "content": "d"}, allowed_tools=ALL_TOOLS, workspace=str(worktree),
        )
        assert w.success is True, w.error
        assert note.read_text() == "d"

    def test_scratch_is_per_run(self, tmp_path):
        """Two executors are two runs; one cannot reach the other's scratch."""
        one, two = tmp_path / "one", tmp_path / "two"
        one.mkdir()
        two.mkdir()
        ex1, _ = self._executor(one)
        ex2, _ = self._executor(two)
        assert ex1.scratch_dir != ex2.scratch_dir
        into_other = Path(ex2.scratch_dir) / "x.txt"
        result = ex1.execute("Write", {"path": str(into_other), "content": "x"}, allowed_tools=ALL_TOOLS)
        assert result.success is False
        assert not into_other.exists()

    def test_not_made_until_a_path_strays(self, tmp_path):
        """A run that never strays never gets one — nothing to name, nothing to clean up."""
        ex, _ = self._executor(tmp_path)
        ok = ex.execute("Write", {"path": "in.txt", "content": "x"}, allowed_tools=ALL_TOOLS)
        assert ok.success is True, ok.error
        assert ex._scratch_dir is None
        ex.execute("Write", {"path": str(tmp_path / "out.txt"), "content": "x"}, allowed_tools=ALL_TOOLS)
        assert ex._scratch_dir is not None

    def test_shutdown_removes_it(self, tmp_path):
        ex, _ = self._executor(tmp_path)
        scratch = Path(ex.scratch_dir)
        (scratch / "left.txt").write_text("x")
        ex.shutdown()
        assert not scratch.exists()

    def test_a_symlink_out_of_scratch_is_still_outside(self, tmp_path):
        """Scratch is judged like the workspace: by where a path resolves to."""
        ex, _ = self._executor(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        link = Path(ex.scratch_dir) / "link"
        link.symlink_to(elsewhere)
        result = ex.execute(
            "Write", {"path": str(link / "x.txt"), "content": "x"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        assert not (elsewhere / "x.txt").exists()

    def test_no_workspace_means_no_scratch_either(self, tmp_path):
        """Scratch is a second root of an active sandbox, not a way to run with none."""
        ex = ToolExecutor()
        ex.register_tools(self._tools())
        result = ex.execute(
            "Write", {"path": str(tmp_path / "x.txt"), "content": "x"}, allowed_tools=ALL_TOOLS,
        )
        assert result.success is False
        assert "no workspace" in result.error
        assert ex._scratch_dir is None


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
        from temper_ai.tools.write import Write

        engine = PolicyEngine.from_config({
            "policies": [
                {"type": "budget", "max_cost_usd": 0.001},
                {"type": "file_access", "denied_paths": ["/etc"]},
            ],
        })
        executor = ToolExecutor(policy_engine=engine, workspace_root="/tmp")
        executor.register_tools({"Write": Write()})
        executor.run_cost_usd = 1.0  # Over budget

        # Skip budget, but file_access should still block /etc paths
        result = executor.execute(
            "Write", {"file_path": "/etc/passwd", "content": "x"}, allowed_tools=ALL_TOOLS,
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
        from temper_ai.tools.write import Write

        with tempfile.TemporaryDirectory() as workspace:
            ex = ToolExecutor(workspace_root=workspace)
            ex.register_tools({"Write": Write()})
            result = ex.execute(
                "Write", {"file_path": "/tmp/escape.txt", "content": "x"},
                allowed_tools=ALL_TOOLS,
            )
            assert result.success is False
            assert "escapes workspace root" in result.error

    def test_default_is_local(self):
        """Opting out is deliberate: a tool that says nothing gets the sandbox."""
        from temper_ai.tools.write import Write

        assert BaseTool.local_paths is True
        assert Write().local_paths is True


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


class SessionTool(BaseTool):
    """A tool whose state belongs to the caller (an MCP session does this)."""

    name = "session"
    description = "Holds something per caller"
    parameters = {"type": "object", "properties": {}}
    per_caller_state = True

    def __init__(self, config=None):
        super().__init__(config)
        self.seen: list[str] = []
        self.released: list[str] = []

    def execute(self, **params: Any) -> ToolResult:
        self.seen.append(self.caller)
        return ToolResult(success=True, result=self.caller)

    def release_caller(self, caller: str) -> None:
        self.released.append(caller)


class TestPerCallerState:
    """A tool with per-caller state runs as the caller's own instance.

    The executor is per run and its tools are shared by every node; nodes at the
    same level run concurrently. So "my session" has to mean the calling agent's,
    and it has to end when that agent does.
    """

    def _executor(self):
        tool = SessionTool()
        plain = EchoTool()
        ex = ToolExecutor()
        ex.register_tools({"session": tool, "Echo": plain})
        return ex, tool, plain

    def test_each_caller_gets_its_own_bound_instance(self):
        """Three nodes, one agent config: three callers, not one."""
        ex, tool, _ = self._executor()
        for node in ("report.walk_1", "report.walk_2"):
            result = ex.execute(
                "session", {}, allowed_tools=["session"],
                context={"execution_id": "run1", "node_path": node, "agent_name": "epd_walk"},
            )
            assert result.result == f"run1/{node}"
        assert tool.seen == ["run1/report.walk_1", "run1/report.walk_2"]
        assert tool.caller == "", "the registered instance is shared; binding must not mutate it"

    def test_caller_key_identifies_the_instance_not_the_config(self):
        from temper_ai.tools.executor import caller_key

        base = {"execution_id": "run1", "agent_name": "epd_walk"}
        keys = {caller_key({**base, "node_path": f"report.walk_{i}"}) for i in (1, 2, 3)}
        assert len(keys) == 3, "same agent in three nodes must not share one session"
        assert caller_key({**base, "node_path": "report.walk_1"}) != caller_key(
            {"execution_id": "run2", "node_path": "report.walk_1"}
        ), "two runs in one process are different callers"
        # No node path (a caller that does not report one): the agent name still
        # separates callers, and something is always returned to key by.
        assert caller_key(base) == "run1/epd_walk"
        assert caller_key({}) == "-/-"

    def test_release_reaches_only_per_caller_tools(self):
        ex, tool, plain = self._executor()
        ex.release_caller("run1/report.walk_1")
        assert tool.released == ["run1/report.walk_1"]
        assert not hasattr(plain, "released"), "a stateless tool is not asked to release"

    def test_release_ignores_an_empty_caller(self):
        """The shared session belongs to the run, not to any one caller."""
        ex, tool, _ = self._executor()
        ex.release_caller("")
        assert tool.released == []
