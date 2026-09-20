"""Tool executor — the gateway for all tool execution.

Handles:
- Tool lookup from registered instances
- Workspace path validation (the sandbox — see below for what it is and is not)
- Timeout enforcement via ThreadPoolExecutor
- Observability event recording at every decision point

What the sandbox is
-------------------
The path check on Read/Write/Edit/Grep/Glob is a guardrail against a node
*straying*: a reviewer writing its diff to /tmp because that is where diffs
go, a Glob judged from wherever the server was started. It is not a boundary
against a model that wants out. Bash has no path the executor can judge and is
governed only by its command allowlist, and a model refused a Write outside
the workspace has been seen `cp` the same file there through Bash seconds
later. The boundary that holds against intent is the container the run
executes in, plus that allowlist. Do not describe this sandbox as more than a
guardrail, and do not let a policy decision rest on it.

Most strays are a node wanting somewhere for a temporary file, so the run has
a scratch directory: a second root the sandbox allows, named in the refusal
the moment a node first needs it (see ToolExecutor.scratch_dir).

Future extensibility points:
- Safety policy validation (action_policies.yaml)
- Rollback snapshots (for modifies_state tools)
- Result caching (for read-only tools)
- Rate limiting
"""

import copy
import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Collection, Container
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from temper_ai.observability import EventType, record
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600
_DEFAULT_WORKERS = 4
# How long the wrapper waits past a timeout the tool enforces itself, so the tool's
# own, better-informed error (it can kill what it started) is the one reported.
_OWN_TIMEOUT_GRACE = 5


class _AllTools(Container[str]):
    """Every name is in it. See ALL_TOOLS."""

    def __contains__(self, item: object) -> bool:
        return True

    def __repr__(self) -> str:
        return "ALL_TOOLS"


ALL_TOOLS = _AllTools()
"""Declare this when the caller is temper itself rather than a model.

``execute()`` requires every caller to state which tools it may use. Model-driven
callers pass the agent's declared list; trusted internal callers (a ScriptAgent
running its own rendered script, a test exercising the executor) pass ALL_TOOLS —
explicit and greppable, and impossible to arrive at by forgetting.
"""

# Path parameter names to check for workspace sandboxing
_PATH_PARAMS = {"path", "file_path", "directory", "filename", "output_path"}


class ToolExecutor:
    """Executes tools with per-caller scope, timeout enforcement and workspace sandboxing.

    One executor per RUN: it holds every node's tools registered together, so
    every call must say which tools ITS caller may run (see execute()). Records
    observability events for every execution, including blocks, timeouts, and
    errors. Events use parent_id/execution_id from the context dict if provided.

    Usage:
        executor = ToolExecutor(workspace_root="/home/user/project")
        executor.register_tools({"Bash": bash_instance, "Write": fw_instance})

        # agent-driven: scoped to what that agent declared
        result = executor.execute("Bash", {"command": "ls"}, allowed_tools=["Bash"])

        # temper itself, not a model
        result = executor.execute("Bash", {"command": "ls"}, allowed_tools=ALL_TOOLS)
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        default_timeout: int = _DEFAULT_TIMEOUT,
        max_workers: int = _DEFAULT_WORKERS,
        policy_engine: Any | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout
        self.policy_engine = policy_engine  # SafetyPolicyEngine (optional)
        self._tools: dict[str, BaseTool] = {}
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._scratch_dir: str | None = None  # made on first need, see scratch_dir
        self._scratch_lock = threading.Lock()
        # Running cost/token totals for budget policy enforcement
        self.run_cost_usd: float = 0.0
        self.run_tokens: int = 0

    @property
    def scratch_dir(self) -> str:
        """This run's scratch directory — the one place outside the workspace its tools may use.

        Made the first time a path strays outside the workspace, and named in
        that refusal: nearly every stray is a node wanting somewhere for a
        temporary file, and a node told only "no" has been seen put the file
        there through Bash instead. A run that never strays never gets one.
        Per executor, so per run: nodes of one run share it, runs do not.
        Removed by shutdown() — it is scratch; what a node wants kept belongs
        in the workspace.
        """
        with self._scratch_lock:
            if self._scratch_dir is None:
                self._scratch_dir = self._make_scratch_dir()
            return self._scratch_dir

    def _make_scratch_dir(self) -> str:
        return tempfile.mkdtemp(prefix="temper-scratch-")

    def track_usage(self, cost_usd: float = 0.0, tokens: int = 0) -> None:
        """Update running cost/token totals for budget policy enforcement."""
        self.run_cost_usd += cost_usd
        self.run_tokens += tokens

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a registered tool by name. Returns None if not found."""
        return self._tools.get(name)

    def tool_names(self) -> list[str]:
        """Names of every registered tool — what an agent can actually be given."""
        return sorted(self._tools)

    def release_caller(self, caller: str) -> None:
        """Free what the run's tools hold for one finished caller.

        Called at the end of a node (stage/agent_node.py). The executor lives for
        the whole run, so anything a tool opened per caller — an MCP session, its
        browser — would otherwise stay open until the run ended, one per node.
        """
        if not caller:
            return
        for tool in list(self._tools.values()):
            if getattr(tool, "per_caller_state", False):
                tool.release_caller(caller)

    def register_tools(self, tools: dict[str, BaseTool]) -> None:
        """Register tool instances for this executor."""
        # The run-level workspace is the default every call resolves relative
        # paths against; a call that names its own workspace gets a copy of the
        # tool configured for that one instead (see _tool_for).
        if self.workspace_root:
            for tool in tools.values():
                if hasattr(tool, 'config') and isinstance(tool.config, dict):
                    tool.config["workspace_root"] = self.workspace_root
        self._tools.update(tools)

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        allowed_tools: Container[str],
        workspace: str | None = None,
        timeout: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a tool by name, if the caller declared it.

        Args:
            tool_name: Registered tool name.
            params: Parameters to pass to the tool.
            workspace: The directory THIS caller works in — a node's
                ``workspace_path`` input, typically a worktree another node
                made earlier in the run. Defaults to the run's workspace_root.
                Path parameters must stay inside it (or inside the run's
                scratch directory, see scratch_dir), relative ones resolve
                against it, and Bash/git run in it. It must itself lie inside
                the run's workspace when the run has one: the value can come
                from another node's output, and a node must not be able to
                move the sandbox. A tool that takes a path (Read, Write, Edit,
                Grep, Glob) does not run with no workspace at all — "no
                sandbox configured" used to mean "no sandbox", which is how a
                run whose worktree was made mid-run got its reviewer writing
                to /tmp. Bash has no path to judge; it stays governed by its
                command allowlist either way.
            allowed_tools: What THIS caller may run — an agent's declared tool
                list, or ALL_TOOLS for trusted internal callers. Required and
                keyword-only: the executor is per RUN and holds every node's
                tools registered together, so without a per-call scope any name
                reaching any caller would run. An agent's YAML ``tools:``
                decides what its model is *shown*; this decides what it may
                *execute*, and the two must agree — a model only ever emits a
                name, and a name can be planted in a tool result (a PR
                description saying "call github-full.merge_pull_request"
                reaching an agent that was only shown ``github-ci.*``). A
                required parameter rather than a scoped wrapper or a context
                key: a caller cannot get a weaker guarantee by holding a
                different object or by omitting a key — there is one entry
                point and it does not run without an answer.
            timeout: Execution timeout in seconds. Uses default if not specified.
            context: Optional observability context with parent_id, execution_id,
                and agent_name (named in the refusal when a tool is not declared).

        Returns:
            ToolResult with success/failure, result, and optional error.
        """
        ctx = context or {}
        parent_id = ctx.get("parent_id")
        execution_id = ctx.get("execution_id")

        if tool_name not in allowed_tools:
            # Checked before the registry lookup on purpose: "you may not" must
            # not also reveal whether the tool exists elsewhere in this run.
            declared = sorted(allowed_tools) if isinstance(allowed_tools, Collection) else []
            caller = str(ctx.get("agent_name") or "")
            who = f"agent '{caller}'" if caller else "this caller"
            record(
                EventType.TOOL_BLOCKED,
                parent_id=parent_id,
                execution_id=execution_id,
                status="blocked",
                data={
                    "tool_name": tool_name,
                    "reason": "not_declared_by_caller",
                    "agent_name": caller,
                    "declared": declared,
                },
            )
            logger.warning("Tool '%s' refused: not declared by %s", tool_name, who)
            return ToolResult(
                success=False,
                result="",
                error=(
                    f"Tool '{tool_name}' is not available to {who} "
                    f"(declared tools: {', '.join(declared) or 'none'})"
                ),
            )

        tool = self._tools.get(tool_name)
        if tool is None:
            error = f"Unknown tool: '{tool_name}'. Available: {sorted(self._tools)}"
            record(EventType.TOOL_UNKNOWN, parent_id=parent_id, execution_id=execution_id,
                   status="failed", data={"tool_name": tool_name, "available": sorted(self._tools)})
            return ToolResult(success=False, result="", error=error)

        policy_block = self._evaluate_safety_policies(tool_name, params, ctx, parent_id, execution_id)
        if policy_block is not None:
            return policy_block

        # Only for tools whose paths are local (see BaseTool.local_paths): an MCP
        # tool's `path` names a file in a repo or on another machine, and resolving
        # it against this process's workspace would reject every legitimate call.
        if tool.local_paths:
            effective, block = self._resolve_workspace(tool, tool_name, workspace, parent_id, execution_id)
            if block is not None:
                return block
            if effective:
                workspace_block = self._validate_workspace_paths(
                    tool_name, params, effective, parent_id, execution_id,
                )
                if workspace_block is not None:
                    return workspace_block
                tool = _tool_for(tool, effective)

        # A tool whose state belongs to the caller (an MCP session's browser and
        # cookies) runs as that caller's own instance, so the resources it opens
        # are keyed by who opened them and can be freed when they finish.
        if getattr(tool, "per_caller_state", False):
            tool = _tool_for_caller(tool, caller_key(ctx))

        # Tools that manage their own execution (e.g., Delegate runs sub-agents)
        # skip the timeout wrapper — they handle timeouts internally.
        if getattr(tool, 'manages_own_timeout', False):
            return self._execute_direct(tool, tool_name, params, parent_id, execution_id)

        # A call that names its own timeout gets that long. Bash offers `timeout`
        # ("default 30, max 600") and enforces it on the subprocess; the wait here
        # used to be a flat 30s regardless, so a `uv run pytest` asked to run for
        # 600s came back "timed out after 30s" every time, while the suite kept
        # running in a pool worker. Three of those and two `sleep`s filled the
        # run's four workers, and the implementer's `echo hi` timed out behind
        # them; its `git commit` was still queued when the node gave up.
        own = _own_timeout(tool, params)
        asked = timeout or own or self.default_timeout
        effective_timeout = min(asked, _MAX_TIMEOUT) + (_OWN_TIMEOUT_GRACE if own else 0)
        return self._execute_with_timeout(tool, tool_name, params, effective_timeout, parent_id, execution_id)

    def _evaluate_safety_policies(
        self,
        tool_name: str,
        params: dict[str, Any],
        ctx: dict[str, Any],
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult | None:
        """Check safety policies. Returns a blocking ToolResult if denied, else None.

        Respects ``skip_policies`` from the execution context — policy types
        listed there are temporarily disabled for this evaluation.
        """
        if not self.policy_engine:
            return None

        from temper_ai.safety.base import ActionType

        skip = set(ctx.get("skip_policies") or [])

        policy_ctx = {**ctx, "run_cost_usd": self.run_cost_usd, "run_tokens": self.run_tokens}
        decision = self.policy_engine.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": tool_name, "tool_params": params},
            policy_ctx,
            skip_types=skip,
        )
        if decision.action != "deny":
            return None

        record(
            EventType.SAFETY_POLICY_TRIGGERED,
            parent_id=parent_id,
            execution_id=execution_id,
            status="blocked",
            data={
                "tool_name": tool_name,
                "policy_name": decision.policy_name,
                "reason": decision.reason,
                "action": "deny",
            },
        )
        return ToolResult(
            success=False, result="",
            error=f"Blocked by safety policy '{decision.policy_name}': {decision.reason}",
        )

    def _resolve_workspace(
        self,
        tool: BaseTool,
        tool_name: str,
        workspace: str | None,
        parent_id: str | None,
        execution_id: str | None,
    ) -> tuple[str | None, ToolResult | None]:
        """The workspace this call runs in, or a blocking ToolResult.

        The caller's workspace narrows the run's; it cannot leave it. With
        neither, a tool that takes a path does not run (see execute()).
        """
        if workspace and self.workspace_root and not _inside(workspace, self.workspace_root):
            error = (
                f"Workspace '{workspace}' is outside this run's workspace '{self.workspace_root}'"
            )
            self._record_blocked(tool_name, "workspace_violation", error, parent_id, execution_id)
            return None, ToolResult(success=False, result="", error=error)

        effective = workspace or self.workspace_root
        if effective is None and _takes_path(tool):
            error = (
                f"Tool '{tool_name}' takes a path and this run has no workspace to confine it to. "
                "Start the run with a workspace (--workspace / workspace_path), or give this node a "
                "workspace_path input."
            )
            self._record_blocked(tool_name, "no_workspace", error, parent_id, execution_id)
            return None, ToolResult(success=False, result="", error=error)
        return effective, None

    def _validate_workspace_paths(
        self,
        tool_name: str,
        params: dict[str, Any],
        workspace_root: str,
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult | None:
        """Check that path params stay within the workspace (or the run's scratch dir).

        Returns a blocking ToolResult or None.
        """
        path_error = _validate_workspace_paths(params, workspace_root, lambda: self.scratch_dir)
        if not path_error:
            return None
        self._record_blocked(tool_name, "workspace_violation", path_error, parent_id, execution_id,
                             workspace_root=workspace_root, scratch_dir=self._scratch_dir)
        return ToolResult(success=False, result="", error=path_error)

    def _record_blocked(
        self,
        tool_name: str,
        reason: str,
        error: str,
        parent_id: str | None,
        execution_id: str | None,
        **data: Any,
    ) -> None:
        record(
            EventType.TOOL_BLOCKED,
            parent_id=parent_id,
            execution_id=execution_id,
            status="blocked",
            data={"tool_name": tool_name, "reason": reason, "error": error, **data},
        )

    def _execute_direct(
        self,
        tool: BaseTool,
        tool_name: str,
        params: dict[str, Any],
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult:
        """Run tool.execute() directly without timeout wrapper."""
        try:
            result = tool.execute(**params)
            if not isinstance(result, ToolResult):
                result = ToolResult(success=True, result=str(result) if result is not None else "")
            return result
        except Exception as exc:
            return ToolResult(success=False, result="", error=f"{type(exc).__name__}: {exc}")

    def _execute_with_timeout(
        self,
        tool: BaseTool,
        tool_name: str,
        params: dict[str, Any],
        timeout: int,
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult:
        """Run tool.execute() in a thread pool with timeout and observability."""
        start = time.monotonic()

        try:
            future = self._thread_pool.submit(tool.execute, **params)
            result = future.result(timeout=timeout)
            duration_ms = int((time.monotonic() - start) * 1000)

            # Ensure we got a ToolResult back
            if not isinstance(result, ToolResult):
                result = ToolResult(
                    success=True,
                    result=str(result) if result is not None else "",
                )

            # Normal success/failure is recorded by the LLM layer (tool_execution.py)
            # which owns TOOL_CALL_STARTED/COMPLETED/FAILED for the standard flow.
            # The executor only records events the LLM layer can't see:
            # TOOL_BLOCKED, TOOL_TIMEOUT, TOOL_UNKNOWN (handled elsewhere in this class).
            return result

        except FutureTimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            # A call still queued behind busy workers is withdrawn: the caller is
            # about to be told it did not happen, so it must not happen later.
            # One already running cannot be stopped from here; it holds its
            # worker until it ends, which for a tool that enforces its own
            # timeout is now, and for one that does not is whenever it does.
            never_started = future.cancel()
            error = f"Tool '{tool_name}' timed out after {timeout}s"
            if never_started:
                error += " without starting: the run's tool workers were all busy. Wait for them; do not retry yet."
            record(
                EventType.TOOL_TIMEOUT,
                parent_id=parent_id,
                execution_id=execution_id,
                status="failed",
                data={
                    "tool_name": tool_name,
                    "timeout_s": timeout,
                    "duration_ms": duration_ms,
                    "never_started": never_started,
                },
            )
            return ToolResult(success=False, result="", error=error)

        except Exception as e:
            # Generic exceptions are also caught by the LLM layer.
            # No duplicate event needed here.
            return ToolResult(
                success=False, result="",
                error=f"{type(e).__name__}: {e}",
            )

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool and remove the run's scratch directory, if it made one."""
        self._thread_pool.shutdown(wait=wait)
        with self._scratch_lock:
            scratch, self._scratch_dir = self._scratch_dir, None
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)

    def __enter__(self) -> "ToolExecutor":
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()





def _validate_workspace_paths(
    params: dict[str, Any],
    workspace_root: str,
    scratch: Callable[[], str],
) -> str | None:
    """Check that path parameters don't escape the workspace. Returns error string or None.

    A relative path is judged from the workspace, which is where the tool will
    resolve it — not from this process's cwd, which is wherever the server
    was started. ``scratch()`` names the run's scratch directory, the one
    other place a path may be; it is called only for a path that is not in
    the workspace, which is what makes the directory (see
    ToolExecutor.scratch_dir), and the refusal tells the node about it.
    """
    for key in _PATH_PARAMS:
        value = params.get(key)
        if not value or not isinstance(value, str):
            continue

        if "\x00" in value:
            return f"Path in '{key}' contains null byte"

        try:
            if _inside(value, workspace_root):
                continue
            scratch_dir = scratch()
            if _inside(value, scratch_dir):
                continue
            return (
                f"Path '{value}' escapes workspace root '{workspace_root}'. "
                f"Temporary files belong in this run's scratch directory '{scratch_dir}'; "
                "everything else belongs in the workspace."
            )
        except (OSError, ValueError):
            return f"Invalid path in '{key}': {value}"

    return None


def _inside(path: str, root: str) -> bool:
    """Whether ``path`` (relative ones taken from ``root``) resolves to ``root`` or under it."""
    base = Path(root).resolve()
    p = Path(path)
    resolved = (p if p.is_absolute() else base / p).resolve()
    return resolved == base or str(resolved).startswith(str(base) + "/")


def _own_timeout(tool: BaseTool, params: dict[str, Any]) -> int | None:
    """The timeout this call carries, when the tool's schema offers one.

    A tool that puts `timeout` in its parameters is telling the model it will
    run that long and stop itself after; the wrapper's wait has to be at least
    that, or the schema is a lie. Absent, unset or nonsense means the wrapper's
    default applies, as for any tool with no notion of its own.
    """
    props = (getattr(tool, "parameters", None) or {}).get("properties") or {}
    raw = params.get("timeout") if "timeout" in props else None
    if raw is None:
        return None
    try:
        asked = int(raw)
    except (TypeError, ValueError):
        return None
    return asked if asked > 0 else None


def _takes_path(tool: BaseTool) -> bool:
    """Whether the tool declares a parameter the sandbox judges (see _PATH_PARAMS)."""
    props = (getattr(tool, "parameters", None) or {}).get("properties") or {}
    return any(key in props for key in _PATH_PARAMS)


def caller_key(ctx: dict[str, Any]) -> str:
    """Who is calling: one agent instance, not one agent config.

    ``run/node.path`` — the node path, because that is what identifies an
    instance. Three nodes can run the same agent config at the same level (three
    walkers, all ``epd_walk``), and keyed by agent name they would share the one
    browser this is here to stop them sharing. The run id keeps two runs in one
    process apart.
    """
    run = str(ctx.get("execution_id") or "-")
    who = str(ctx.get("node_path") or ctx.get("agent_name") or "-")
    return f"{run}/{who}"


def _tool_for_caller(tool: BaseTool, caller: str) -> BaseTool:
    """The tool as bound to ``caller``: itself if already bound, else a shallow copy.

    A copy per call for the same reason as _tool_for: the registered instance is
    shared by every node in the run, and two nodes run at the same time.
    """
    if getattr(tool, "caller", "") == caller:
        return tool
    clone = copy.copy(tool)
    clone.caller = caller
    return clone


def _tool_for(tool: BaseTool, workspace: str) -> BaseTool:
    """The tool as configured for ``workspace``: itself if that is already its
    workspace_root, else a shallow copy whose config says so.

    A copy per call rather than an assignment on the registered instance: the
    executor is per run and its tools are shared by every node, and two nodes
    in different worktrees can run at the same time.
    """
    config = getattr(tool, "config", None)
    if not isinstance(config, dict) or config.get("workspace_root") == workspace:
        return tool
    clone = copy.copy(tool)
    clone.config = {**config, "workspace_root": workspace}
    return clone
