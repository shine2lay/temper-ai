"""
Tool executor with safety checks and error handling.

Provides robust thread pool management with guaranteed cleanup
using weakref.finalize() to prevent thread leaks.
"""
import time
import weakref
import threading
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from collections import deque, defaultdict

from src.tools.base import BaseTool, ToolResult
from src.tools.registry import ToolRegistry
from src.utils.logging import get_logger
from src.safety.rollback import RollbackManager
from src.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from src.safety.approval import ApprovalWorkflow
from src.observability.rollback_logger import log_rollback_event

# Module logger
logger = get_logger(__name__)


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""
    pass


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


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
        default_timeout: int = 30,
        max_workers: int = 4,
        max_concurrent: Optional[int] = None,
        rate_limit: Optional[int] = None,
        rate_window: float = 1.0,
        rollback_manager: Optional[RollbackManager] = None,
        policy_engine: Optional[ActionPolicyEngine] = None,
        approval_workflow: Optional[ApprovalWorkflow] = None,
        enable_auto_rollback: bool = True
    ):
        """
        Initialize tool executor.

        Creates a thread pool and registers cleanup handlers to ensure
        threads are properly shut down even if the executor is not explicitly
        closed.

        Args:
            registry: ToolRegistry instance
            default_timeout: Default timeout in seconds (default: 30)
            max_workers: Max concurrent tool executions (default: 4)
            max_concurrent: Max total concurrent executions allowed (default: None/unlimited)
            rate_limit: Max executions per rate_window (default: None/unlimited)
            rate_window: Time window for rate limiting in seconds (default: 1.0)
            rollback_manager: RollbackManager for snapshot/rollback (optional)
            policy_engine: ActionPolicyEngine for policy validation (optional)
            approval_workflow: ApprovalWorkflow for approval requests (optional)
            enable_auto_rollback: Enable automatic rollback on failure (default: True)
        """
        self.registry = registry
        self.default_timeout = default_timeout
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit
        self.rate_window = rate_window

        # Safety components (optional)
        self.rollback_manager = rollback_manager
        self.policy_engine = policy_engine
        self.approval_workflow = approval_workflow
        self.enable_auto_rollback = enable_auto_rollback

        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._shutdown = False  # Track shutdown state

        # Concurrent execution tracking
        self._concurrent_count = 0
        self._concurrent_lock = threading.Lock()

        # Rate limiting tracking
        self._execution_times: deque[float] = deque()  # Timestamps of recent executions
        self._rate_limit_lock = threading.Lock()

        # Register cleanup using weakref.finalize() for guaranteed cleanup
        # This ensures the thread pool is shut down even if __del__ is not called
        self._finalizer = weakref.finalize(
            self,
            self._cleanup_executor,
            self._executor
        )

        # Register approval rejection callback if both workflows provided
        if self.approval_workflow and self.rollback_manager:
            self.approval_workflow.on_rejected(self._handle_approval_rejection)

        logger.debug(f"ToolExecutor initialized with {max_workers} workers, "
                    f"max_concurrent={max_concurrent}, rate_limit={rate_limit}/{rate_window}s, "
                    f"rollback={'enabled' if rollback_manager else 'disabled'}")

    def _acquire_concurrent_slot(self) -> bool:
        """Atomically check and acquire a concurrent execution slot.

        Combines the former _check_concurrent_limit and _increment_concurrent
        into a single atomic operation to prevent TOCTOU race conditions.

        Always increments the concurrent count for observability tracking.
        Only enforces the limit when max_concurrent is configured.

        Returns:
            True if slot was acquired

        Raises:
            RateLimitError: If concurrent limit exceeded
        """
        with self._concurrent_lock:
            if self.max_concurrent is not None and self._concurrent_count >= self.max_concurrent:
                raise RateLimitError(
                    f"Concurrent execution limit reached: {self._concurrent_count}/{self.max_concurrent}"
                )
            self._concurrent_count += 1
            logger.debug(f"Concurrent executions: {self._concurrent_count}")
        return True

    def _check_rate_limit(self) -> None:
        """Check if rate limit is exceeded.

        Raises:
            RateLimitError: If rate limit exceeded
        """
        if self.rate_limit is None:
            return

        with self._rate_limit_lock:
            now = time.time()

            # Remove old timestamps outside the window
            cutoff = now - self.rate_window
            while self._execution_times and self._execution_times[0] < cutoff:
                self._execution_times.popleft()

            # Check if limit exceeded
            if len(self._execution_times) >= self.rate_limit:
                raise RateLimitError(
                    f"Rate limit exceeded: {len(self._execution_times)}/{self.rate_limit} "
                    f"in {self.rate_window}s window"
                )

            # Add current execution timestamp
            self._execution_times.append(now)

    def _release_concurrent_slot(self) -> None:
        """Release a concurrent execution slot.

        Counterpart to _acquire_concurrent_slot().
        """
        with self._concurrent_lock:
            self._concurrent_count -= 1
            logger.debug(f"Concurrent executions: {self._concurrent_count}")

    def get_concurrent_execution_count(self) -> int:
        """Get current number of concurrent executions.

        Returns:
            Number of currently executing tools
        """
        with self._concurrent_lock:
            return self._concurrent_count

    def get_rate_limit_usage(self) -> Dict[str, Any]:
        """Get current rate limit usage.

        Returns:
            Dict with rate limit statistics
        """
        if self.rate_limit is None:
            return {
                "rate_limit": None,
                "current_usage": 0,
                "window_seconds": self.rate_window
            }

        with self._rate_limit_lock:
            now = time.time()
            cutoff = now - self.rate_window

            # Clean old timestamps
            while self._execution_times and self._execution_times[0] < cutoff:
                self._execution_times.popleft()

            return {
                "rate_limit": self.rate_limit,
                "current_usage": len(self._execution_times),
                "window_seconds": self.rate_window,
                "available": self.rate_limit - len(self._execution_times)
            }

    def execute(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        """
        Execute tool with parameters.

        Args:
            tool_name: Name of tool to execute
            params: Tool parameters (default: {})
            timeout: Execution timeout in seconds (default: self.default_timeout)
            context: Execution context for safety checks (optional)

        Returns:
            ToolResult with success status, result data, and optional error
        """
        if params is None:
            params = {}

        if timeout is None:
            timeout = self.default_timeout

        if context is None:
            context = {}

        snapshot = None
        approval_request = None

        # Check rate limit before execution
        try:
            self._check_rate_limit()
        except RateLimitError as e:
            return ToolResult(
                success=False,
                result=None,
                error=str(e)
            )

        # Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                result=None,
                error=f"Tool not found: {tool_name}"
            )

        # Validate parameters
        try:
            validation = tool.validate_params(params)
            if not validation.valid:
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"Invalid parameters for tool '{tool_name}'"
                )
        except Exception as e:
            return ToolResult(
                success=False,
                result=None,
                error=f"Parameter validation failed: {str(e)}"
            )

        # Policy validation (if engine provided)
        try:
            if self.policy_engine:
                enforcement = self.policy_engine.validate_action(
                    action={"tool": tool_name, "params": params},
                    context=PolicyExecutionContext(
                        agent_id=context.get("agent_id", "unknown"),
                        workflow_id=context.get("workflow_id", "unknown"),
                        stage_id=context.get("stage_id", "unknown"),
                        action_type="tool_execution",
                        action_data={"tool_name": tool_name, "params": params}
                    )
                )

                # Block on policy violations
                if not enforcement.allowed:  # type: ignore
                    return ToolResult(
                        success=False,
                        result=None,
                        error=f"Action blocked by policy: {enforcement.violations[0].message}",  # type: ignore
                        metadata={"violations": [v.to_dict() for v in enforcement.violations]}  # type: ignore
                    )

                # Request approval for HIGH/CRITICAL violations
                if enforcement.has_blocking_violations() and self.approval_workflow:  # type: ignore
                    approval_request = self.approval_workflow.request_approval(
                        action={"tool": tool_name, "params": params},
                        reason=f"HIGH/CRITICAL policy violations detected",
                        context=context,
                        violations=enforcement.violations,  # type: ignore
                        metadata={"enforcement_result": enforcement.metadata}  # type: ignore
                    )

                    # Wait for approval (blocking, with timeout)
                    if not self._wait_for_approval(approval_request.id):
                        return ToolResult(
                            success=False,
                            result=None,
                            error="Action requires approval but was not approved",
                            metadata={"approval_request_id": approval_request.id}
                        )
        except Exception as e:
            logger.error(f"Policy validation error (fail-closed): {e}")
            return ToolResult(
                success=False,
                result=None,
                error=f"Policy validation failed: {e}",
                metadata={"policy_error": str(e)}
            )

        # Create snapshot (if rollback enabled and state-modifying tool)
        try:
            if self.rollback_manager and self._should_snapshot(tool_name, params):
                snapshot = self.rollback_manager.create_snapshot(
                    action={"tool": tool_name, "params": params},
                    context=context,
                    strategy_name="file"
                )
                logger.debug(f"Created snapshot {snapshot.id} for tool {tool_name}")
        except Exception as e:
            logger.warning(f"Failed to create snapshot: {e}")
            # Continue execution even if snapshot fails

        # Execute with timeout
        try:
            # Atomically check limit and acquire slot (prevents TOCTOU race)
            try:
                self._acquire_concurrent_slot()
            except RateLimitError as e:
                return ToolResult(
                    success=False,
                    result=None,
                    error=str(e)
                )

            try:
                start_time = time.time()
                future = self._executor.submit(self._execute_tool, tool, params)

                try:
                    result = future.result(timeout=timeout)
                    execution_time = time.time() - start_time

                    # Add execution time to metadata
                    if result.metadata is None:
                        result.metadata = {}  # type: ignore[unreachable]
                    result.metadata["execution_time_seconds"] = execution_time

                    # Auto-rollback on failure (if enabled)
                    if not result.success and snapshot and self.enable_auto_rollback:
                        try:
                            rollback_result = self.rollback_manager.execute_rollback(snapshot.id)  # type: ignore[union-attr]
                            logger.warning(
                                f"Auto-rollback executed for failed tool '{tool_name}': "
                                f"status={rollback_result.status.value}, "
                                f"reverted={len(rollback_result.reverted_items)}"
                            )
                            result.metadata["rollback_executed"] = True
                            result.metadata["rollback_snapshot_id"] = snapshot.id
                            result.metadata["rollback_status"] = rollback_result.status.value

                            # Log rollback event to database
                            try:
                                log_rollback_event(
                                    result=rollback_result,
                                    trigger="auto",
                                    operator=context.get("agent_id")
                                )
                            except Exception as log_error:
                                logger.warning(f"Failed to log rollback event: {log_error}")
                        except Exception as e:
                            logger.error(f"Auto-rollback failed: {e}")
                            result.metadata["rollback_error"] = str(e)

                    return result

                except FuturesTimeoutError:
                    future.cancel()

                    # Auto-rollback on timeout
                    if snapshot and self.enable_auto_rollback and self.rollback_manager:
                        try:
                            rollback_result = self.rollback_manager.execute_rollback(snapshot.id)
                            logger.warning(f"Auto-rollback on timeout: {rollback_result.status.value}")

                            # Log rollback event
                            try:
                                log_rollback_event(
                                    result=rollback_result,
                                    trigger="auto",
                                    operator=context.get("agent_id"),
                                    reason="Tool execution timeout"
                                )
                            except Exception as log_error:
                                logger.warning(f"Failed to log rollback event: {log_error}")
                        except Exception as e:
                            logger.error(f"Auto-rollback on timeout failed: {e}")

                    return ToolResult(
                        success=False,
                        result=None,
                        error=f"Tool execution timed out after {timeout} seconds"
                    )

            finally:
                # Always decrement concurrent count
                self._release_concurrent_slot()

        except Exception as e:
            # Auto-rollback on exception
            if snapshot and self.enable_auto_rollback and self.rollback_manager:
                try:
                    rollback_result = self.rollback_manager.execute_rollback(snapshot.id)
                    logger.error(
                        f"Auto-rollback on exception for tool '{tool_name}': {e}",
                        extra={"rollback_result": rollback_result.to_dict()}
                    )

                    # Log rollback event
                    try:
                        log_rollback_event(
                            result=rollback_result,
                            trigger="auto",
                            operator=context.get("agent_id"),
                            reason=f"Tool execution exception: {str(e)}"
                        )
                    except Exception as log_error:
                        logger.warning(f"Failed to log rollback event: {log_error}")
                except Exception as rollback_error:
                    logger.error(f"Auto-rollback on exception failed: {rollback_error}")

            return ToolResult(
                success=False,
                result=None,
                error=f"Tool execution failed: {str(e)}"
            )

    def _execute_tool(self, tool: BaseTool, params: Dict[str, Any]) -> ToolResult:
        """
        Internal method to execute tool.

        Args:
            tool: Tool instance
            params: Tool parameters

        Returns:
            ToolResult
        """
        try:
            return tool.execute(**params)
        except Exception as e:
            # Catch any unhandled exceptions from tool.execute()
            return ToolResult(
                success=False,
                result=None,
                error=f"Unhandled exception in tool: {str(e)}"
            )

    def _should_snapshot(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """Determine if snapshot should be created for this tool.

        Skip snapshots for:
        - Read-only tools (tools with modifies_state=False)
        - Tools with no side effects

        Args:
            tool_name: Name of tool
            params: Tool parameters

        Returns:
            True if snapshot should be created
        """
        # Get tool metadata to check if it modifies state
        tool = self.registry.get(tool_name)
        if not tool:
            # If tool not found, don't create snapshot (execution will fail anyway)
            return False

        metadata = tool.get_metadata()
        return metadata.modifies_state

    def _wait_for_approval(
        self,
        request_id: str,
        poll_interval: float = 1.0,
        max_wait: int = 3600
    ) -> bool:
        """Wait for approval request to be approved/rejected.

        Args:
            request_id: Approval request ID
            poll_interval: Time between status checks (seconds)
            max_wait: Maximum wait time (seconds)

        Returns:
            True if approved, False if rejected/expired/timeout
        """
        start_time = time.time()
        while time.time() - start_time < max_wait:
            if self.approval_workflow.is_approved(request_id):  # type: ignore[union-attr]
                return True
            if self.approval_workflow.is_rejected(request_id):  # type: ignore[union-attr]
                return False
            time.sleep(poll_interval)
        return False

    def _handle_approval_rejection(self, request: Any) -> None:
        """Callback for approval rejection - trigger rollback if snapshot exists.

        Args:
            request: ApprovalRequest that was rejected
        """
        snapshot_id = request.metadata.get("rollback_snapshot_id")
        if snapshot_id and self.rollback_manager:
            try:
                rollback_result = self.rollback_manager.execute_rollback(snapshot_id)
                logger.info(
                    f"Auto-rollback on approval rejection: {rollback_result.status.value}"
                )

                # Log rollback event
                try:
                    log_rollback_event(
                        result=rollback_result,
                        trigger="approval_rejection",
                        operator=request.metadata.get("operator"),
                        reason=f"Approval rejected: {request.decision_reason or 'No reason provided'}"
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log rollback event: {log_error}")
            except Exception as e:
                logger.error(f"Auto-rollback on approval rejection failed: {e}")

    def execute_batch(
        self,
        executions: list[tuple[str, Dict[str, Any]]],
        timeout: Optional[int] = None
    ) -> list[ToolResult]:
        """
        Execute multiple tools in parallel.

        Args:
            executions: List of (tool_name, params) tuples
            timeout: Timeout for each execution

        Returns:
            List of ToolResults in same order as executions
        """
        results = []
        futures = []

        for tool_name, params in executions:
            future = self._executor.submit(self.execute, tool_name, params, timeout)
            futures.append(future)

        # Collect results in order
        for future in futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append(
                    ToolResult(
                        success=False,
                        result=None,
                        error=f"Batch execution failed: {str(e)}"
                    )
                )

        return results

    def validate_tool_call(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate a tool call without executing it.

        Args:
            tool_name: Name of tool
            params: Tool parameters

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if tool exists
        tool = self.registry.get(tool_name)
        if not tool:
            return False, f"Tool not found: {tool_name}"

        # Validate parameters
        try:
            validation = tool.validate_params(params)
            if not validation.valid:
                return False, f"Invalid parameters for tool '{tool_name}'"
        except Exception as e:
            return False, f"Parameter validation failed: {str(e)}"

        return True, None

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a tool.

        Args:
            tool_name: Name of tool

        Returns:
            Dict with tool info or None if not found
        """
        tool = self.registry.get(tool_name)
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

    @staticmethod
    def _cleanup_executor(executor: ThreadPoolExecutor) -> None:
        """
        Static cleanup method for thread pool.

        This is called by weakref.finalize() and must not reference
        the ToolExecutor instance (to avoid circular references).

        Args:
            executor: ThreadPoolExecutor to shut down
        """
        try:
            executor.shutdown(wait=True, cancel_futures=True)
            logger.debug("ThreadPoolExecutor cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during thread pool cleanup: {e}")

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        Shutdown the executor and cleanup resources.

        Args:
            wait: If True, wait for pending executions to complete
            cancel_futures: If True, cancel pending futures before shutdown
        """
        if self._shutdown:
            logger.debug("Executor already shut down, ignoring duplicate shutdown call")
            return

        try:
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self._shutdown = True
            logger.debug("ToolExecutor shutdown completed")
        except Exception as e:
            logger.error(f"Error during executor shutdown: {e}")
            raise

    def __enter__(self) -> "ToolExecutor":
        """Context manager entry."""
        logger.debug("Entering ToolExecutor context")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        logger.debug("Exiting ToolExecutor context")
        self.shutdown(wait=True)

    def __del__(self) -> None:
        """
        Destructor - attempts cleanup on garbage collection.

        Note: __del__ may not always be called (e.g., in circular references),
        which is why we also use weakref.finalize() for guaranteed cleanup.
        """
        try:
            if not self._shutdown and hasattr(self, '_executor'):
                logger.warning(
                    "ToolExecutor garbage collected without explicit shutdown. "
                    "Use context manager or call shutdown() explicitly."
                )
                self.shutdown(wait=False, cancel_futures=True)
        except Exception as e:
            # Exceptions in __del__ are ignored but logged
            logger.error(f"Error in ToolExecutor.__del__: {e}")

    def is_shutdown(self) -> bool:
        """
        Check if executor has been shut down.

        Returns:
            True if executor is shut down, False otherwise
        """
        return self._shutdown

    def __repr__(self) -> str:
        status = "shutdown" if self._shutdown else "active"
        return f"ToolExecutor(registry={self.registry}, timeout={self.default_timeout}s, status={status})"
