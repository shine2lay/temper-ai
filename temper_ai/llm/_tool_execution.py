"""Tool execution infrastructure for LLMService.

Handles single/parallel tool execution, safety mode checks,
thread pool management, and result building.
"""

from __future__ import annotations

import atexit
import concurrent.futures
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from temper_ai.llm.constants import ERROR_MSG_TOOL_PREFIX, FALLBACK_UNKNOWN_VALUE
from temper_ai.llm.tool_keys import ToolKeys
from temper_ai.shared.constants.limits import DEFAULT_POOL_SIZE as _POOL_SIZE_LIMIT
from temper_ai.shared.utils.exceptions import ToolExecutionError, ToolNotFoundError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared thread pool for parallel tool execution
# ---------------------------------------------------------------------------
_CPU_MULTIPLIER_FOR_POOL = 2
_MIN_POOL_SIZE_PER_CPU = 4
_DEFAULT_CPU_COUNT_FALLBACK = 4

_DEFAULT_POOL_SIZE = min(
    _POOL_SIZE_LIMIT,
    (os.cpu_count() or _DEFAULT_CPU_COUNT_FALLBACK) * _CPU_MULTIPLIER_FOR_POOL
    + _MIN_POOL_SIZE_PER_CPU,
)
_TOOL_POOL_SIZE = int(os.environ.get("AGENT_TOOL_WORKERS", str(_DEFAULT_POOL_SIZE)))
_tool_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()

# Minimum Python version supporting cancel_futures in ThreadPoolExecutor.shutdown()
_MIN_PYTHON_CANCEL_FUTURES = (3, 9)


def _get_tool_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or lazily create the shared thread pool for tool execution."""
    global _tool_executor
    if _tool_executor is None:
        with _executor_lock:
            if _tool_executor is None:
                _tool_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_TOOL_POOL_SIZE,
                    thread_name_prefix="llm-tool",
                )
    return _tool_executor


def _shutdown_tool_executor() -> None:
    """Shutdown the tool executor pool gracefully."""
    global _tool_executor
    if _tool_executor is not None:
        if sys.version_info >= _MIN_PYTHON_CANCEL_FUTURES:
            _tool_executor.shutdown(wait=True, cancel_futures=True)
        else:
            _tool_executor.shutdown(wait=True)
        _tool_executor = None


atexit.register(_shutdown_tool_executor)


# ---------------------------------------------------------------------------
# Validation and helpers
# ---------------------------------------------------------------------------


def validate_tool_calls_input(tool_calls: list[dict[str, Any]]) -> None:
    """Validate that tool_calls is a list of dicts."""
    if not isinstance(tool_calls, list):
        raise TypeError(f"tool_calls must be a list, got {type(tool_calls).__name__}")
    for i, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            raise TypeError(
                f"tool_call at index {i} must be a dictionary, got {type(tool_call).__name__}"
            )


def check_safety_mode(
    safety_config: Any,
    tool_name: str,
    tool_params: dict[str, Any],
) -> dict[str, Any] | None:
    """Check if safety mode blocks execution. Returns error dict or None."""
    if safety_config is None:
        return None

    mode = getattr(safety_config, "mode", "execute")
    require_approval_for_tools = getattr(
        safety_config, "require_approval_for_tools", []
    )

    if mode == "require_approval":
        return {
            ToolKeys.NAME: tool_name,
            ToolKeys.PARAMETERS: tool_params,
            ToolKeys.RESULT: None,
            ToolKeys.ERROR: f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' blocked: safety mode is 'require_approval'",
            ToolKeys.SUCCESS: False,
        }

    if tool_name in require_approval_for_tools:
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' requires approval before execution",
            "success": False,
        }

    if mode == "dry_run":
        return {
            ToolKeys.NAME: tool_name,
            ToolKeys.PARAMETERS: tool_params,
            ToolKeys.RESULT: f"[DRY RUN] {ERROR_MSG_TOOL_PREFIX}{tool_name}' would be executed with parameters: {tool_params}",
            ToolKeys.ERROR: None,
            ToolKeys.SUCCESS: True,
        }

    return None


def build_tool_result(
    tool_name: str,
    tool_params: dict[str, Any],
    success: bool,
    result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build standardized tool result dictionary."""
    return {
        ToolKeys.NAME: tool_name,
        ToolKeys.PARAMETERS: tool_params,
        ToolKeys.RESULT: result if success else None,
        ToolKeys.ERROR: error if not success else None,
        ToolKeys.SUCCESS: success,
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_tools(
    tool_calls: list[dict[str, Any]],
    tool_executor: Any,
    observer: Any,
    safety_config: Any,
    execute_single: Callable,
) -> list[dict[str, Any]]:
    """Execute a list of tool calls (serial or parallel)."""
    validate_tool_calls_input(tool_calls)

    parallel_enabled = (
        getattr(safety_config, "parallel_tool_calls", True) if safety_config else True
    )
    use_parallel = len(tool_calls) > 1 and parallel_enabled

    if not use_parallel:
        return [
            execute_single(tc, tool_executor, observer, safety_config)
            for tc in tool_calls
        ]

    return _execute_parallel(
        tool_calls, tool_executor, observer, safety_config, execute_single
    )


def _execute_parallel(
    tool_calls: list[dict[str, Any]],
    tool_executor: Any,
    observer: Any,
    safety_config: Any,
    execute_single: Callable,
) -> list[dict[str, Any]]:
    """Execute tool calls in parallel using thread pool."""
    tool_results: list[Any] = [None] * len(tool_calls)

    future_to_index = {
        _get_tool_executor().submit(
            execute_single,
            tc,
            tool_executor,
            observer,
            safety_config,
        ): i
        for i, tc in enumerate(tool_calls)
    }

    for future in concurrent.futures.as_completed(future_to_index):
        index = future_to_index[future]
        try:
            tool_results[index] = future.result()
        except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
            logger.error("Tool execution failed in parallel mode: %s", e)
            tool_results[index] = {
                ToolKeys.NAME: tool_calls[index].get(
                    ToolKeys.NAME, FALLBACK_UNKNOWN_VALUE
                ),
                ToolKeys.PARAMETERS: tool_calls[index].get(ToolKeys.PARAMETERS, {}),
                ToolKeys.SUCCESS: False,
                ToolKeys.RESULT: None,
                ToolKeys.ERROR: f"Parallel execution error: {str(e)}",
            }

    return tool_results


def execute_single_tool(
    tool_call: dict[str, Any],
    tool_executor: Any,
    observer: Any,
    safety_config: Any,
) -> dict[str, Any]:
    """Execute a single tool call."""
    if not isinstance(tool_call, dict):
        raise TypeError(
            f"tool_call must be a dictionary, got {type(tool_call).__name__}"
        )
    if ToolKeys.NAME not in tool_call:
        raise ValueError("tool_call must contain 'name' field")

    tool_name = tool_call.get(ToolKeys.NAME)
    tool_params = tool_call.get(ToolKeys.PARAMETERS, tool_call.get("arguments", {}))

    if not isinstance(tool_name, str):
        raise TypeError(
            f"tool_call 'name' must be a string, got {type(tool_name).__name__}"
        )
    if isinstance(tool_params, str):
        # LLM sometimes returns arguments as a JSON string instead of a dict
        try:
            parsed = json.loads(tool_params)
            if isinstance(parsed, dict):
                tool_params = parsed
            else:
                tool_params = {}
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Malformed tool_params string for %s: %s",
                tool_name,
                tool_params[:200],
            )
            tool_params = {}
    if not isinstance(tool_params, dict):
        raise TypeError(
            f"tool_call 'parameters' must be a dictionary, got {type(tool_params).__name__}"
        )

    # Safety mode pre-checks
    safety_block = check_safety_mode(safety_config, tool_name, tool_params)
    if safety_block is not None:
        return safety_block

    # Route through ToolExecutor (safety-integrated execution)
    if tool_executor is not None:
        return execute_via_executor(tool_name, tool_params, tool_executor, observer)

    # SECURITY: No silent fallback
    logger.critical(
        "SECURITY: No tool_executor provided. "
        "%s%s' execution blocked to prevent safety bypass.",
        ERROR_MSG_TOOL_PREFIX,
        tool_name,
    )
    return build_tool_result(
        tool_name,
        tool_params,
        False,
        None,
        f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' execution blocked: no tool_executor configured. "
        f"The safety stack is required for tool execution.",
    )


def execute_via_executor(
    tool_name: str,
    tool_params: dict[str, Any],
    tool_executor: Any,
    observer: Any,
) -> dict[str, Any]:
    """Execute tool through the safety-integrated ToolExecutor."""
    tool_start_time = time.time()
    try:
        result = tool_executor.execute(tool_name, tool_params)
        duration_seconds = time.time() - tool_start_time
        if result.success:
            logger.info("Tool '%s' succeeded (%.1fs)", tool_name, duration_seconds)
        else:
            logger.warning(
                "Tool '%s' failed (%.1fs): %s",
                tool_name,
                duration_seconds,
                result.error,
            )
        if observer is not None:
            observer.track_tool_call(
                tool_name=tool_name,
                input_params=tool_params,
                output_data={"result": result.result} if result.success else {},
                duration_seconds=duration_seconds,
                status="success" if result.success else "failed",
                error_message=result.error if not result.success else None,
            )
        return build_tool_result(
            tool_name, tool_params, result.success, result.result, result.error
        )
    except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
        duration_seconds = time.time() - tool_start_time
        error_msg = f"Tool execution error: {str(e)}"
        if observer is not None:
            observer.track_tool_call(
                tool_name=tool_name,
                input_params=tool_params,
                output_data={},
                duration_seconds=duration_seconds,
                status="failed",
                error_message=error_msg,
            )
        return build_tool_result(tool_name, tool_params, False, None, error_msg)
