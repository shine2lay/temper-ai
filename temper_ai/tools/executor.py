"""Tool executor — the gateway for all tool execution.

Handles:
- Tool lookup from registered instances
- Workspace path validation (security)
- Timeout enforcement via ThreadPoolExecutor
- Observability event recording at every decision point

Future extensibility points:
- Safety policy validation (action_policies.yaml)
- Rollback snapshots (for modifies_state tools)
- Result caching (for read-only tools)
- Rate limiting
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from temper_ai.observability import EventType, record
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600
_DEFAULT_WORKERS = 4

# Path parameter names to check for workspace sandboxing
_PATH_PARAMS = {"path", "file_path", "directory", "filename", "output_path"}


class ToolExecutor:
    """Executes tools with timeout enforcement and workspace sandboxing.

    Records observability events for every execution, including blocks,
    timeouts, and errors. Events use parent_id/execution_id from the
    context dict if provided.

    Usage:
        executor = ToolExecutor(workspace_root="/home/user/project")
        executor.register_tools({"Bash": bash_instance, "FileWriter": fw_instance})
        result = executor.execute("Bash", {"command": "ls"})
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
        # Running cost/token totals for budget policy enforcement
        self.run_cost_usd: float = 0.0
        self.run_tokens: int = 0

    def track_usage(self, cost_usd: float = 0.0, tokens: int = 0) -> None:
        """Update running cost/token totals for budget policy enforcement."""
        self.run_cost_usd += cost_usd
        self.run_tokens += tokens

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a registered tool by name. Returns None if not found."""
        return self._tools.get(name)

    def register_tools(self, tools: dict[str, BaseTool]) -> None:
        """Register tool instances for this executor."""
        self._tools.update(tools)

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        timeout: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a tool by name.

        Args:
            tool_name: Registered tool name.
            params: Parameters to pass to the tool.
            timeout: Execution timeout in seconds. Uses default if not specified.
            context: Optional observability context with parent_id, execution_id, etc.

        Returns:
            ToolResult with success/failure, result, and optional error.
        """
        ctx = context or {}
        parent_id = ctx.get("parent_id")
        execution_id = ctx.get("execution_id")

        tool = self._tools.get(tool_name)
        if tool is None:
            error = f"Unknown tool: '{tool_name}'. Available: {sorted(self._tools)}"
            record(EventType.TOOL_UNKNOWN, parent_id=parent_id, execution_id=execution_id,
                   status="failed", data={"tool_name": tool_name, "available": sorted(self._tools)})
            return ToolResult(success=False, result="", error=error)

        policy_block = self._evaluate_safety_policies(tool_name, params, ctx, parent_id, execution_id)
        if policy_block is not None:
            return policy_block

        workspace_block = self._validate_workspace_paths(tool_name, params, parent_id, execution_id)
        if workspace_block is not None:
            return workspace_block

        # Tools that manage their own execution (e.g., Delegate runs sub-agents)
        # skip the timeout wrapper — they handle timeouts internally.
        if getattr(tool, 'manages_own_timeout', False):
            return self._execute_direct(tool, tool_name, params, parent_id, execution_id)

        effective_timeout = min(timeout or self.default_timeout, _MAX_TIMEOUT)
        return self._execute_with_timeout(tool, tool_name, params, effective_timeout, parent_id, execution_id)

    def _evaluate_safety_policies(
        self,
        tool_name: str,
        params: dict[str, Any],
        ctx: dict[str, Any],
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult | None:
        """Check safety policies. Returns a blocking ToolResult if denied, else None."""
        if not self.policy_engine:
            return None

        from temper_ai.safety.base import ActionType
        policy_ctx = {**ctx, "run_cost_usd": self.run_cost_usd, "run_tokens": self.run_tokens}
        decision = self.policy_engine.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": tool_name, "tool_params": params},
            policy_ctx,
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

    def _validate_workspace_paths(
        self,
        tool_name: str,
        params: dict[str, Any],
        parent_id: str | None,
        execution_id: str | None,
    ) -> ToolResult | None:
        """Check that path params stay within the workspace. Returns blocking ToolResult or None."""
        if not self.workspace_root:
            return None

        path_error = _validate_workspace_paths(params, self.workspace_root)
        if not path_error:
            return None

        record(
            EventType.TOOL_BLOCKED,
            parent_id=parent_id,
            execution_id=execution_id,
            status="blocked",
            data={
                "tool_name": tool_name,
                "reason": "workspace_violation",
                "error": path_error,
                "workspace_root": self.workspace_root,
            },
        )
        return ToolResult(success=False, result="", error=path_error)

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
            error = f"Tool '{tool_name}' timed out after {timeout}s"
            record(
                EventType.TOOL_TIMEOUT,
                parent_id=parent_id,
                execution_id=execution_id,
                status="failed",
                data={
                    "tool_name": tool_name,
                    "timeout_s": timeout,
                    "duration_ms": duration_ms,
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
        """Shut down the thread pool."""
        self._thread_pool.shutdown(wait=wait)

    def __enter__(self) -> "ToolExecutor":
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()


def _validate_workspace_paths(params: dict[str, Any], workspace_root: str) -> str | None:
    """Check that path parameters don't escape the workspace. Returns error string or None."""
    root = Path(workspace_root).resolve()

    for key in _PATH_PARAMS:
        value = params.get(key)
        if not value or not isinstance(value, str):
            continue

        try:
            resolved = Path(value).resolve()
        except (OSError, ValueError):
            return f"Invalid path in '{key}': {value}"

        if "\x00" in value:
            return f"Path in '{key}' contains null byte"

        if not (resolved == root or str(resolved).startswith(str(root) + "/")):
            return f"Path '{value}' escapes workspace root '{workspace_root}'"

    return None
