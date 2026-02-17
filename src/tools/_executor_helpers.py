"""Helper functions extracted from ToolExecutor to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from src.shared.constants.durations import (
    POLL_INTERVAL_FAST,
    SECONDS_PER_HOUR,
    TIMEOUT_VERY_SHORT,
)
from src.tools.base import BaseTool, ToolResult
from src.tools.constants import CONTEXT_KEY_AGENT_ID, ROLLBACK_TRIGGER_AUTO
from src.shared.utils.exceptions import RateLimitError

if TYPE_CHECKING:
    from src.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


def validate_workspace_path(file_path: str, workspace_root: Path) -> None:
    """Validate that a file path is within the workspace boundary.

    Args:
        file_path: The path to validate.
        workspace_root: The allowed workspace root directory.

    Raises:
        ValueError: If path escapes the workspace or contains dangerous patterns.
    """
    # Reject null bytes (path injection)
    if "\x00" in file_path:
        raise ValueError("Path contains null bytes")

    resolved = Path(file_path).resolve()
    workspace_resolved = workspace_root.resolve()

    # Check path stays within workspace (catches symlink escapes too)
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError:
        raise ValueError(
            f"Access denied: path '{file_path}' is outside workspace '{workspace_root}'"
        )


def _log_rollback_event(**kwargs: Any) -> None:
    """Lazy-import and call log_rollback_event (M-06)."""
    try:
        from src.observability.rollback_logger import log_rollback_event
        log_rollback_event(**kwargs)
    except ImportError:
        logger.debug("Observability not available; skipping rollback event logging")
    except (TypeError, ValueError, OSError) as e:
        logger.warning("Failed to log rollback event: %s", e)


# ---------------------------------------------------------------------------
# Concurrency and rate-limit helpers
# ---------------------------------------------------------------------------

def acquire_concurrent_slot(executor: ToolExecutor) -> bool:
    """Atomically check and acquire a concurrent execution slot."""
    with executor._concurrent_lock:
        if executor.max_concurrent is not None and executor._concurrent_count >= executor.max_concurrent:
            raise RateLimitError(
                f"Concurrent execution limit reached: {executor._concurrent_count}/{executor.max_concurrent}"
            )
        executor._concurrent_count += 1
        logger.debug(f"Concurrent executions: {executor._concurrent_count}")
    return True


def check_rate_limit(executor: ToolExecutor) -> None:
    """Check if rate limit is exceeded."""
    if executor.rate_limit is None:
        return

    with executor._rate_limit_lock:
        now = time.time()

        cutoff = now - executor.rate_window
        while executor._execution_times and executor._execution_times[0] < cutoff:
            executor._execution_times.popleft()

        if len(executor._execution_times) >= executor.rate_limit:
            raise RateLimitError(
                f"Rate limit exceeded: {len(executor._execution_times)}/{executor.rate_limit} "
                f"in {executor.rate_window}s window"
            )

        executor._execution_times.append(now)


def release_concurrent_slot(executor: ToolExecutor) -> None:
    """Release a concurrent execution slot."""
    with executor._concurrent_lock:
        executor._concurrent_count -= 1
        logger.debug(f"Concurrent executions: {executor._concurrent_count}")


def get_concurrent_execution_count(executor: ToolExecutor) -> int:
    """Get current number of concurrent executions."""
    with executor._concurrent_lock:
        return executor._concurrent_count


def get_rate_limit_usage(executor: ToolExecutor) -> Dict[str, Any]:
    """Get current rate limit usage."""
    if executor.rate_limit is None:
        return {
            "rate_limit": None,
            "current_usage": 0,
            "window_seconds": executor.rate_window
        }

    with executor._rate_limit_lock:
        now = time.time()
        cutoff = now - executor.rate_window

        while executor._execution_times and executor._execution_times[0] < cutoff:
            executor._execution_times.popleft()

        return {
            "rate_limit": executor.rate_limit,
            "current_usage": len(executor._execution_times),
            "window_seconds": executor.rate_window,
            "available": executor.rate_limit - len(executor._execution_times)
        }


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------

def execute_tool_internal(tool: BaseTool, params: Dict[str, Any]) -> ToolResult:
    """Internal method to execute tool."""
    try:
        return tool.execute(**params)
    except (RuntimeError, TypeError, ValueError, OSError, KeyError, AttributeError) as e:
        return ToolResult(
            success=False,
            result=None,
            error=f"Unhandled exception in tool: {str(e)}"
        )


def should_snapshot(executor: ToolExecutor, tool_name: str, params: Dict[str, Any]) -> bool:
    """Determine if snapshot should be created for this tool."""
    tool = executor.registry.get(tool_name)
    if not tool:
        return False

    metadata = tool.get_metadata()
    return metadata.modifies_state


# ---------------------------------------------------------------------------
# Approval workflow helpers
# ---------------------------------------------------------------------------

def wait_for_approval(
    executor: ToolExecutor,
    request_id: str,
    poll_interval: float = POLL_INTERVAL_FAST,
    max_wait: int = SECONDS_PER_HOUR,
) -> bool:
    """Wait for approval request to be approved/rejected."""
    future = executor._approval_executor.submit(
        poll_approval, executor, request_id, poll_interval, max_wait
    )
    try:
        return future.result(timeout=max_wait + TIMEOUT_VERY_SHORT)
    except (TimeoutError, RuntimeError, ValueError):
        return False


def poll_approval(
    executor: ToolExecutor,
    request_id: str,
    poll_interval: float,
    max_wait: int,
) -> bool:
    """Poll approval status on the dedicated approval thread pool."""
    event = threading.Event()
    deadline = time.monotonic() + max_wait

    while True:
        if executor.approval_workflow.is_approved(request_id):  # type: ignore[union-attr]
            return True
        if executor.approval_workflow.is_rejected(request_id):  # type: ignore[union-attr]
            return False

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False

        event.wait(timeout=min(poll_interval, remaining))


def handle_approval_rejection(executor: ToolExecutor, request: Any) -> None:
    """Callback for approval rejection - trigger rollback if snapshot exists."""
    snapshot_id = request.metadata.get("rollback_snapshot_id")
    if snapshot_id and executor.rollback_manager:
        try:
            rollback_result = executor.rollback_manager.execute_rollback(snapshot_id)
            logger.info(
                f"Auto-rollback on approval rejection: {rollback_result.status.value}"
            )

            _log_rollback_event(
                result=rollback_result,
                trigger="approval_rejection",
                operator=request.metadata.get("operator"),
                reason=f"Approval rejected: {request.decision_reason or 'No reason provided'}"
            )
        except (TypeError, ValueError, OSError, AttributeError) as e:
            logger.error(f"Auto-rollback on approval rejection failed: {e}")


# ---------------------------------------------------------------------------
# Rollback helpers
# ---------------------------------------------------------------------------

def handle_auto_rollback(executor: ToolExecutor, snapshot: Any, tool_name: str, result: ToolResult, context: Dict[str, Any]) -> None:
    """Handle auto-rollback on tool failure."""
    try:
        rollback_result = executor.rollback_manager.execute_rollback(snapshot.id)  # type: ignore[union-attr]
        logger.info(
            f"Auto-rollback for tool '{tool_name}': "
            f"status={rollback_result.status.value}, "
            f"reverted={len(rollback_result.reverted_items)}"
        )
        result.metadata["rollback_executed"] = True
        result.metadata["rollback_snapshot_id"] = snapshot.id
        result.metadata["rollback_status"] = rollback_result.status.value

        _log_rollback_event(
            result=rollback_result,
            trigger=ROLLBACK_TRIGGER_AUTO,
            operator=context.get(CONTEXT_KEY_AGENT_ID)
        )
    except (TypeError, ValueError, OSError, AttributeError) as e:
        logger.error(f"Auto-rollback failed: {e}")
        result.metadata["rollback_error"] = str(e)


def handle_timeout_rollback(executor: ToolExecutor, snapshot: Any, context: Dict[str, Any], reason: str = "Tool execution timeout") -> None:
    """Handle auto-rollback on timeout."""
    try:
        rollback_result = executor.rollback_manager.execute_rollback(snapshot.id)  # type: ignore[union-attr]
        logger.warning(f"Auto-rollback on timeout: {rollback_result.status.value}")

        _log_rollback_event(
            result=rollback_result,
            trigger="auto",
            operator=context.get("agent_id"),
            reason=reason
        )
    except (TypeError, ValueError, OSError, AttributeError) as e:
        logger.error(f"Auto-rollback on timeout failed: {e}")


def handle_exception_rollback(executor: ToolExecutor, snapshot: Any, tool_name: str, error: Exception, context: Dict[str, Any]) -> None:
    """Handle auto-rollback on exception."""
    try:
        rollback_result = executor.rollback_manager.execute_rollback(snapshot.id)  # type: ignore[union-attr]
        logger.error(
            f"Auto-rollback on exception for tool '{tool_name}': {error}",
            extra={"rollback_result": rollback_result.to_dict()}
        )

        _log_rollback_event(
            result=rollback_result,
            trigger="auto",
            operator=context.get("agent_id"),
            reason=f"Tool execution exception: {str(error)}"
        )
    except (TypeError, ValueError, OSError, AttributeError) as rollback_error:
        logger.error(f"Auto-rollback on exception failed: {rollback_error}")


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------

def execute_batch(
    executor: ToolExecutor,
    executions: list[tuple[str, Dict[str, Any]]],
    timeout: Optional[int] = None,
    overall_timeout: Optional[int] = None,
) -> list[ToolResult]:
    """Execute multiple tools in parallel."""
    results: list[Optional[ToolResult]] = [None] * len(executions)
    futures: Dict[Any, int] = {}

    for idx, (tool_name, params) in enumerate(executions):
        future = executor._executor.submit(executor.execute, tool_name, params, timeout)
        futures[future] = idx

    try:
        for future in concurrent.futures.as_completed(futures, timeout=overall_timeout):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except (RuntimeError, TypeError, ValueError, OSError, TimeoutError, KeyError, AttributeError) as e:
                results[idx] = ToolResult(
                    success=False,
                    result=None,
                    error=f"Execution failed: {str(e)}"
                )
    except concurrent.futures.TimeoutError:
        for future, idx in futures.items():
            if results[idx] is None:
                future.cancel()
                results[idx] = ToolResult(
                    success=False,
                    result=None,
                    error=f"Batch overall timeout ({overall_timeout}s) exceeded"
                )

    # All results should be non-None at this point
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Validation and info
# ---------------------------------------------------------------------------

def validate_tool_call(executor: ToolExecutor, tool_name: str, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate a tool call without executing it."""
    tool = executor.registry.get(tool_name)
    if not tool:
        return False, f"Tool not found: {tool_name}"

    try:
        validation = tool.validate_params(params)
        if not validation.valid:
            return False, f"Invalid parameters for tool '{tool_name}'"
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        return False, f"Parameter validation failed: {str(e)}"

    return True, None


def get_tool_info(executor: ToolExecutor, tool_name: str) -> Optional[Dict[str, Any]]:
    """Get information about a tool."""
    tool = executor.registry.get(tool_name)
    if not tool:
        return None

    metadata = tool.get_metadata()
    return {
        "name": metadata.name,
        "description": metadata.description,
        "version": metadata.version,
        "category": metadata.category,
        "parameters_schema": tool.get_parameters_schema(),
        "llm_schema": tool.to_llm_schema(),
    }


# ---------------------------------------------------------------------------
# Execute method helpers (extracted from ToolExecutor.execute)
# ---------------------------------------------------------------------------

_WORKSPACE_PATH_KEYS = ("path", "file_path", "directory", "filename", "output_path")


def validate_and_get_tool(
    executor: ToolExecutor,
    tool_name: str,
    params: Dict[str, Any],
) -> Tuple[Optional[BaseTool], Optional[ToolResult]]:
    """Validate workspace paths and tool params. Returns (tool, None) or (None, error)."""
    if executor.workspace_root is not None:
        for key in _WORKSPACE_PATH_KEYS:
            if key in params:
                try:
                    validate_workspace_path(str(params[key]), executor.workspace_root)
                except ValueError as e:
                    return None, ToolResult(success=False, result=None, error=str(e))

    tool = executor.registry.get(tool_name)
    if not tool:
        return None, ToolResult(success=False, result=None, error=f"Tool not found: {tool_name}")

    try:
        validation = tool.validate_params(params)
        if not validation.valid:
            return None, ToolResult(success=False, result=None, error=f"Invalid parameters for tool '{tool_name}'")
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        return None, ToolResult(success=False, result=None, error=f"Parameter validation failed: {str(e)}")

    return tool, None


def validate_policy(
    executor: ToolExecutor,
    tool_name: str,
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Optional[ToolResult]:
    """Run policy validation. Returns ToolResult on error/block, None if allowed."""
    if not executor.policy_engine:
        return None

    try:
        from src.safety.action_policy_engine import PolicyExecutionContext
        metadata = {}
        if context.get("autonomy_config") is not None:
            metadata["autonomy_config"] = context["autonomy_config"]
        if context.get("autonomy_level") is not None:
            metadata["autonomy_level"] = context["autonomy_level"]
        enforcement = executor.policy_engine.validate_action_sync(
            action={"tool": tool_name, "params": params},
            context=PolicyExecutionContext(
                agent_id=context.get("agent_id", "unknown"),
                workflow_id=context.get("workflow_id", "unknown"),
                stage_id=context.get("stage_id", "unknown"),
                action_type="tool_execution",
                action_data={"tool_name": tool_name, "params": params},
                metadata=metadata,
            )
        )

        if not enforcement.allowed:
            return ToolResult(
                success=False, result=None,
                error=f"Action blocked by policy: {enforcement.violations[0].message}",
                metadata={"violations": [v.to_dict() for v in enforcement.violations]}
            )

        if enforcement.has_blocking_violations() and executor.approval_workflow:
            approval_request = executor.approval_workflow.request_approval(
                action={"tool": tool_name, "params": params},
                reason="HIGH/CRITICAL policy violations detected",
                context=context,
                violations=enforcement.violations,
                metadata={"enforcement_result": enforcement.metadata}
            )
            if not wait_for_approval(executor, approval_request.id):
                return ToolResult(
                    success=False, result=None,
                    error="Action requires approval but was not approved",
                    metadata={"approval_request_id": approval_request.id}
                )
    except (TypeError, ValueError, KeyError, AttributeError, ImportError, RuntimeError) as e:
        logger.error(f"Policy validation error (fail-closed): {e}")
        return ToolResult(
            success=False, result=None,
            error=f"Policy validation failed: {e}",
            metadata={"policy_error": str(e)}
        )

    return None


def create_snapshot(
    executor: ToolExecutor,
    tool_name: str,
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Any:
    """Create a rollback snapshot if applicable. Returns snapshot or None."""
    if not executor.rollback_manager or not should_snapshot(executor, tool_name, params):
        return None

    try:
        snapshot = executor.rollback_manager.create_snapshot(
            action={"tool": tool_name, "params": params},
            context=context, strategy_name="file"
        )
        logger.debug(f"Created snapshot {snapshot.id} for tool {tool_name}")
        try:
            from src.observability.rollback_logger import log_rollback_snapshot
            log_rollback_snapshot(snapshot, workflow_execution_id=context.get("workflow_id"))
        except Exception as e:
            logger.warning(f"Failed to persist rollback snapshot to DB: {e}")
        return snapshot
    except (TypeError, ValueError, OSError, AttributeError) as e:
        logger.warning(f"Failed to create snapshot: {e}")
        return None


def execute_with_timeout(
    executor: ToolExecutor,
    tool: BaseTool,
    params: Dict[str, Any],
    timeout: int,
    snapshot: Any,
    tool_name: str,
    context: Dict[str, Any],
) -> ToolResult:
    """Execute tool in thread pool with timeout and rollback handling."""
    try:
        acquire_concurrent_slot(executor)
    except RateLimitError as e:
        return ToolResult(success=False, result=None, error=str(e))

    try:
        start_time = time.time()
        future = executor._executor.submit(execute_tool_internal, tool, params)

        try:
            result = future.result(timeout=timeout)
            execution_time = time.time() - start_time

            if result.metadata is None:
                result.metadata = {}  # type: ignore[unreachable]
            result.metadata["execution_time_seconds"] = execution_time

            if not result.success and snapshot and executor.enable_auto_rollback:
                handle_auto_rollback(executor, snapshot, tool_name, result, context)

            return result

        except concurrent.futures.TimeoutError:
            future.cancel()
            if snapshot and executor.enable_auto_rollback and executor.rollback_manager:
                handle_timeout_rollback(executor, snapshot, context)
            return ToolResult(
                success=False, result=None,
                error=f"Tool execution timed out after {timeout} seconds"
            )

    finally:
        release_concurrent_slot(executor)
