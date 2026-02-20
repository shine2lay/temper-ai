"""
Tool executor with safety checks and error handling.

Provides robust thread pool management with guaranteed cleanup
using weakref.finalize() to prevent thread leaks.
"""
from __future__ import annotations

import threading
import weakref
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Union

from temper_ai.shared.constants.limits import MIN_WORKERS
from temper_ai.tools._executor_config import ToolExecutorConfig
from temper_ai.tools._executor_helpers import (
    acquire_concurrent_slot,
    check_rate_limit,
    create_snapshot,
    execute_with_timeout,
    handle_approval_rejection,
    handle_exception_rollback,
    release_concurrent_slot,
    validate_and_get_tool,
    validate_policy,
)
from temper_ai.tools._executor_helpers import (
    execute_batch as _execute_batch,
)
from temper_ai.tools._executor_helpers import (
    get_concurrent_execution_count as _get_concurrent_count,
)
from temper_ai.tools._executor_helpers import (
    get_rate_limit_usage as _get_rate_limit_usage,
)
from temper_ai.tools._executor_helpers import (
    get_tool_info as _get_tool_info,
)
from temper_ai.tools._executor_helpers import (
    validate_tool_call as _validate_tool_call,
)
from temper_ai.tools.base import ToolResult
from temper_ai.tools.registry import ToolRegistry
from temper_ai.shared.utils.exceptions import RateLimitError
from temper_ai.shared.utils.logging import get_logger

# Module logger
logger = get_logger(__name__)

# Note: RateLimitError now imported from temper_ai.shared.utils.exceptions
# (unified base class for all rate limit exceptions)


def _build_tool_cache(cfg: "ToolExecutorConfig") -> Any:
    """Create ToolResultCache from config, or None if caching is disabled."""
    if not cfg.enable_tool_cache:
        return None
    from temper_ai.tools.tool_cache import ToolResultCache
    from temper_ai.tools.tool_cache_constants import (
        DEFAULT_CACHE_MAX_SIZE,
        DEFAULT_CACHE_TTL_SECONDS,
    )
    return ToolResultCache(
        max_size=cfg.tool_cache_max_size or DEFAULT_CACHE_MAX_SIZE,
        ttl_seconds=cfg.tool_cache_ttl or DEFAULT_CACHE_TTL_SECONDS,
    )


class ToolExecutor:
    """
    Executes tools with safety checks and error handling.

    Features:
    - Parameter validation
    - Timeout handling
    - Error handling and reporting
    - Structured result format
    """

    def __init__(
        self,
        registry: ToolRegistry,
        config: Optional[Union[ToolExecutorConfig, Dict[str, Any]]] = None,
        **kwargs: Any,
    ):
        """
        Initialize tool executor.

        Args:
            registry: ToolRegistry instance (required)
            config: Optional ToolExecutorConfig or dict with config params
            **kwargs: Individual config params (for backward compatibility)

        Supported config params:
            default_timeout: Default timeout in seconds
            max_workers: Max concurrent tool executions
            max_concurrent: Max total concurrent executions allowed
            rate_limit: Max executions per rate_window
            rate_window: Time window for rate limiting in seconds
            rollback_manager: RollbackManager for snapshot/rollback
            policy_engine: ActionPolicyEngine for policy validation
            approval_workflow: ApprovalWorkflow for approval requests
            enable_auto_rollback: Enable automatic rollback on failure
            workspace_root: Optional workspace root directory path
        """
        # Parse config
        if config is None:
            cfg = ToolExecutorConfig(**kwargs)
        elif isinstance(config, dict):
            cfg = ToolExecutorConfig(**config)
        else:
            cfg = config

        # Set attributes from config
        self.registry = registry
        self.default_timeout = cfg.default_timeout
        self.max_concurrent = cfg.max_concurrent
        self.rate_limit = cfg.rate_limit
        self.rate_window = cfg.rate_window
        self.workspace_root = cfg.workspace_path

        # Safety components (optional)
        self.rollback_manager = cfg.rollback_manager
        self.policy_engine = cfg.policy_engine
        self.approval_workflow = cfg.approval_workflow
        self.enable_auto_rollback = cfg.enable_auto_rollback

        # Thread pools
        self._executor = ThreadPoolExecutor(
            max_workers=cfg.max_workers,
            thread_name_prefix="tool-exec",
        )
        self._approval_executor = ThreadPoolExecutor(
            max_workers=MIN_WORKERS,
            thread_name_prefix="tool-approval",
        )
        self._shutdown = False

        # Concurrent execution tracking
        self._concurrent_count = 0
        self._concurrent_lock = threading.Lock()

        # Rate limiting tracking
        self._execution_times: deque[float] = deque()
        self._rate_limit_lock = threading.Lock()

        # R0.3 & R0.9
        self._tool_cache = _build_tool_cache(cfg)
        self.workflow_rate_limiter: Any = None

        # Register cleanup using weakref.finalize()
        self._finalizer = weakref.finalize(
            self,
            self._cleanup_executor,
            self._executor,
            self._approval_executor,
        )

        # Register approval rejection callback if both workflows provided
        if self.approval_workflow and self.rollback_manager:
            self.approval_workflow.on_rejected(lambda req: handle_approval_rejection(self, req))

        logger.debug(f"ToolExecutor initialized with {cfg.max_workers} workers, "
                    f"max_concurrent={cfg.max_concurrent}, rate_limit={cfg.rate_limit}/{cfg.rate_window}s, "
                    f"rollback={'enabled' if cfg.rollback_manager else 'disabled'}")

    def get_concurrent_execution_count(self) -> int:
        """Return current concurrent execution count."""
        return _get_concurrent_count(self)

    def get_rate_limit_usage(self) -> Dict[str, Any]:
        """Return current rate limit usage stats."""
        return _get_rate_limit_usage(self)

    def _resolve_defaults(
        self,
        params: Optional[Dict[str, Any]],
        timeout: Optional[int],
        context: Optional[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
        """Resolve None parameters to their defaults."""
        return (
            params if params is not None else {},
            timeout if timeout is not None else self.default_timeout,
            context if context is not None else {},
        )

    def _handle_execution_error(
        self,
        error: Exception,
        snapshot: Any,
        tool_name: str,
        context: Dict[str, Any],
    ) -> ToolResult:
        """Handle exception during tool execution with optional rollback."""
        if snapshot and self.enable_auto_rollback and self.rollback_manager:
            handle_exception_rollback(
                self, snapshot, tool_name, error, context
            )
        logger.error(f"Tool execution failed: {error}", exc_info=True)
        return ToolResult(
            success=False,
            result=None,
            error="Tool execution failed due to an internal error",
        )

    def execute(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute tool with parameters."""
        params, timeout, context = self._resolve_defaults(
            params, timeout, context
        )

        try:
            check_rate_limit(self)
        except RateLimitError as e:
            return ToolResult(success=False, result=None, error=str(e))

        tool, error = validate_and_get_tool(self, tool_name, params)
        if error is not None:
            return error
        if tool is None:
            return ToolResult(
                success=False, error=f"Tool '{tool_name}' not found"
            )

        policy_error = validate_policy(self, tool_name, params, context)
        if policy_error is not None:
            return policy_error

        snapshot = create_snapshot(self, tool_name, params, context)

        try:
            return execute_with_timeout(
                self, tool, params, timeout, snapshot, tool_name, context
            )
        except (RuntimeError, OSError, MemoryError) as e:
            return self._handle_execution_error(
                e, snapshot, tool_name, context
            )

    def execute_batch(self, executions: list[tuple[str, Dict[str, Any]]], timeout: Optional[int] = None, overall_timeout: Optional[int] = None) -> list[ToolResult]:
        """Execute multiple tools in parallel."""
        return _execute_batch(self, executions, timeout, overall_timeout)

    def validate_tool_call(self, tool_name: str, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate a tool call before execution."""
        return _validate_tool_call(self, tool_name, params)

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata about a registered tool."""
        return _get_tool_info(self, tool_name)

    @staticmethod
    def _cleanup_executor(executor: ThreadPoolExecutor, approval_executor: Optional[ThreadPoolExecutor] = None) -> None:
        """Static cleanup method for thread pools."""
        for pool_name, pool in [("tool-exec", executor), ("tool-approval", approval_executor)]:
            if pool is None:
                continue
            try:
                pool.shutdown(wait=True, cancel_futures=True)
                logger.debug("ThreadPoolExecutor (%s) cleaned up successfully", pool_name)
            except (RuntimeError, OSError) as e:
                logger.error("Error during thread pool cleanup (%s): %s", pool_name, e)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shutdown the executor and cleanup resources."""
        if self._shutdown:
            logger.debug("Executor already shut down, ignoring duplicate shutdown call")
            return
        try:
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self._approval_executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self._shutdown = True
            logger.debug("ToolExecutor shutdown completed")
        except (RuntimeError, OSError) as e:
            logger.error(f"Error during executor shutdown: {e}")
            raise

    def __enter__(self) -> "ToolExecutor":
        logger.debug("Entering ToolExecutor context")
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        logger.debug("Exiting ToolExecutor context")
        self.shutdown(wait=True)

    def __del__(self) -> None:
        try:
            if not self._shutdown and hasattr(self, '_executor'):
                logger.warning(
                    "ToolExecutor garbage collected without explicit shutdown. "
                    "Use context manager or call shutdown() explicitly."
                )
                self.shutdown(wait=False, cancel_futures=True)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.error(f"Error in ToolExecutor.__del__: {e}")

    def is_shutdown(self) -> bool:
        """Return whether the executor has been shut down."""
        return self._shutdown

    def __repr__(self) -> str:
        status = "shutdown" if self._shutdown else "active"
        return f"ToolExecutor(registry={self.registry}, timeout={self.default_timeout}s, status={status})"


# --------------------------------------------------------------------------
# Methods attached outside the class body to keep method_count under the
# god-class threshold while preserving backward compatibility.
# --------------------------------------------------------------------------

def _acquire_concurrent_slot_method(self: ToolExecutor) -> bool:
    """Acquire a concurrent slot."""
    return acquire_concurrent_slot(self)

def _release_concurrent_slot_method(self: ToolExecutor) -> None:
    """Release a concurrent slot."""
    release_concurrent_slot(self)

def _check_rate_limit_method(self: ToolExecutor) -> None:
    """Check rate limit."""
    check_rate_limit(self)

ToolExecutor._acquire_concurrent_slot = _acquire_concurrent_slot_method  # type: ignore[attr-defined]
ToolExecutor._release_concurrent_slot = _release_concurrent_slot_method  # type: ignore[attr-defined]
ToolExecutor._check_rate_limit = _check_rate_limit_method  # type: ignore[attr-defined]
