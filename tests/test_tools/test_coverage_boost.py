"""
Targeted tests to boost coverage on files below 90%.

Focuses on uncovered paths in:
- _executor_helpers.py (71%)
- calculator.py (80%)
- executor.py (79%)
- file_writer.py (80%)
- http_client.py (79%)
- json_parser.py (87%)
- loader.py (88%)
- _registry_helpers.py (84%)
"""

from __future__ import annotations

import collections
import concurrent.futures
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

# ===========================================================================
# Shared helpers
# ===========================================================================


def _make_executor(max_concurrent=None, rate_limit=None, rate_window=60.0):
    """Build a mock ToolExecutor."""
    executor = MagicMock()
    executor.max_concurrent = max_concurrent
    executor._concurrent_count = 0
    executor._concurrent_lock = threading.Lock()
    executor.rate_limit = rate_limit
    executor.rate_window = rate_window
    executor._rate_limit_lock = threading.Lock()
    executor._execution_times = collections.deque()
    executor.rollback_manager = None
    executor.workspace_root = None
    executor.policy_engine = None
    executor.approval_workflow = None
    executor.enable_auto_rollback = False
    executor._tool_cache = None
    executor.workflow_rate_limiter = None
    return executor


class _SimpleTool(BaseTool):
    """Minimal concrete tool for testing."""

    def __init__(self, name="simple_tool", modifies_state=False, cacheable=None):
        self._name = name
        self._modifies_state = modifies_state
        self._cacheable = cacheable
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self._name,
            description="Test tool",
            modifies_state=self._modifies_state,
            cacheable=self._cacheable,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


# ===========================================================================
# _executor_helpers.py — targeted coverage
# ===========================================================================


class TestLogRollbackEvent:
    """Cover lines 57-66: _log_rollback_event."""

    def test_import_error_is_silently_logged(self):
        """Line 64: ImportError triggers debug log."""
        from temper_ai.tools._executor_helpers import _log_rollback_event

        with (
            patch("temper_ai.tools._executor_helpers.logger"),
            patch(
                "temper_ai.observability.rollback_logger.log_rollback_event",
                side_effect=ImportError("no module"),
                create=True,
            ),
        ):
            _log_rollback_event(result=MagicMock(), trigger="test")
            # Should not raise; ImportError path just debug-logs

    def test_value_error_triggers_warning(self):
        """Line 65-66: ValueError triggers warning log."""
        from temper_ai.tools._executor_helpers import _log_rollback_event

        with (
            patch("temper_ai.tools._executor_helpers.logger") as mock_logger,
            patch(
                "temper_ai.observability.rollback_logger.log_rollback_event",
                side_effect=ValueError("bad value"),
            ),
        ):
            _log_rollback_event(result=MagicMock(), trigger="test")
        mock_logger.warning.assert_called_once()

    def test_os_error_triggers_warning(self):
        """Line 65-66: OSError triggers warning log."""
        from temper_ai.tools._executor_helpers import _log_rollback_event

        with (
            patch("temper_ai.tools._executor_helpers.logger") as mock_logger,
            patch(
                "temper_ai.observability.rollback_logger.log_rollback_event",
                side_effect=OSError("disk error"),
            ),
        ):
            _log_rollback_event(result=MagicMock(), trigger="test")
        mock_logger.warning.assert_called_once()


class TestGetRateLimitUsageExpiredPruning:
    """Cover line 137: pruning inside get_rate_limit_usage."""

    def test_expired_entries_pruned_in_usage_report(self):
        from temper_ai.tools._executor_helpers import get_rate_limit_usage

        executor = _make_executor(rate_limit=10, rate_window=10.0)
        old = time.time() - 20  # outside the 10-second window
        executor._execution_times = collections.deque([old, old, old])
        usage = get_rate_limit_usage(executor)
        assert usage["current_usage"] == 0
        assert usage["available"] == 10


class TestHandleApprovalRejection:
    """Cover lines 225-242: handle_approval_rejection."""

    def test_no_snapshot_id_is_noop(self):
        from temper_ai.tools._executor_helpers import handle_approval_rejection

        executor = _make_executor()
        executor.rollback_manager = MagicMock()
        request = MagicMock()
        request.metadata = {}  # no rollback_snapshot_id
        handle_approval_rejection(executor, request)
        executor.rollback_manager.execute_rollback.assert_not_called()

    def test_rollback_executed_on_rejection(self):
        from temper_ai.tools._executor_helpers import handle_approval_rejection

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        request = MagicMock()
        request.metadata = {"rollback_snapshot_id": "snap-123", "operator": "agent1"}
        request.decision_reason = "Too risky"

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            handle_approval_rejection(executor, request)
        rollback_mgr.execute_rollback.assert_called_once_with("snap-123")

    def test_rollback_exception_is_logged(self):
        from temper_ai.tools._executor_helpers import handle_approval_rejection

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_mgr.execute_rollback.side_effect = AttributeError("no attr")
        executor.rollback_manager = rollback_mgr

        request = MagicMock()
        request.metadata = {"rollback_snapshot_id": "snap-999"}
        request.decision_reason = None

        # Should not raise
        handle_approval_rejection(executor, request)


class TestHandleAutoRollback:
    """Cover lines 250-276: handle_auto_rollback."""

    def test_successful_rollback_updates_result_metadata(self):
        from temper_ai.tools._executor_helpers import handle_auto_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_result.reverted_items = ["file1"]
        rollback_result.to_dict.return_value = {}
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-001"

        result = ToolResult(success=False, result=None, error="tool failed")
        result.metadata = {}

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            handle_auto_rollback(
                executor, snapshot, "my_tool", result, {"agent_id": "a1"}
            )

        assert result.metadata["rollback_executed"] is True
        assert result.metadata["rollback_snapshot_id"] == "snap-001"
        assert "rollback_status" in result.metadata

    def test_rollback_exception_records_error(self):
        from temper_ai.tools._executor_helpers import handle_auto_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_mgr.execute_rollback.side_effect = TypeError("bad type")
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-002"

        result = ToolResult(success=False, result=None, error="err")
        result.metadata = {}

        handle_auto_rollback(executor, snapshot, "my_tool", result, {})
        assert "rollback_error" in result.metadata


class TestHandleTimeoutRollback:
    """Cover lines 279-297: handle_timeout_rollback."""

    def test_successful_timeout_rollback(self):
        from temper_ai.tools._executor_helpers import handle_timeout_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-timeout"

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            handle_timeout_rollback(executor, snapshot, {"agent_id": "a1"})
        rollback_mgr.execute_rollback.assert_called_once_with("snap-timeout")

    def test_rollback_exception_on_timeout_is_logged(self):
        from temper_ai.tools._executor_helpers import handle_timeout_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_mgr.execute_rollback.side_effect = OSError("disk failure")
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-fail"

        # Should not raise
        handle_timeout_rollback(executor, snapshot, {}, reason="timeout after 30s")


class TestHandleExceptionRollback:
    """Cover lines 300-322: handle_exception_rollback."""

    def test_successful_exception_rollback(self):
        from temper_ai.tools._executor_helpers import handle_exception_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_result.to_dict.return_value = {}
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-exc"

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            handle_exception_rollback(
                executor, snapshot, "my_tool", RuntimeError("boom"), {"agent_id": "a"}
            )
        rollback_mgr.execute_rollback.assert_called_once_with("snap-exc")

    def test_rollback_exception_on_exception_is_logged(self):
        from temper_ai.tools._executor_helpers import handle_exception_rollback

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_mgr.execute_rollback.side_effect = ValueError("bad")
        executor.rollback_manager = rollback_mgr

        snapshot = MagicMock()
        snapshot.id = "snap-fail"

        # Should not raise
        handle_exception_rollback(
            executor, snapshot, "my_tool", RuntimeError("original"), {}
        )


class TestValidateAndGetToolParamValidationException:
    """Cover lines 450-451: validate_and_get_tool param validation exception."""

    def test_attribute_error_in_validate_params_returns_error(self):
        from temper_ai.tools._executor_helpers import validate_and_get_tool

        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.side_effect = AttributeError("missing attr")
        executor._get_tool.return_value = tool

        result_tool, error = validate_and_get_tool(executor, "my_tool", {})
        assert result_tool is None
        assert error is not None
        assert error.success is False
        assert "validation failed" in error.error.lower()

    def test_key_error_in_validate_params_returns_error(self):
        from temper_ai.tools._executor_helpers import validate_and_get_tool

        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.side_effect = KeyError("missing_key")
        executor._get_tool.return_value = tool

        result_tool, error = validate_and_get_tool(executor, "my_tool", {})
        assert result_tool is None
        assert error.success is False


class TestValidatePolicy:
    """Cover lines 507-551: validate_policy."""

    def test_no_policy_engine_returns_none(self):
        from temper_ai.tools._executor_helpers import validate_policy

        executor = _make_executor()
        executor.policy_engine = None
        result = validate_policy(executor, "tool", {}, {})
        assert result is None

    def test_blocked_action_returns_error_result(self):
        from temper_ai.tools._executor_helpers import validate_policy

        executor = _make_executor()
        mock_engine = MagicMock()
        enforcement = MagicMock()
        enforcement.allowed = False
        violation = MagicMock()
        violation.message = "blocked by policy"
        violation.to_dict.return_value = {"msg": "blocked"}
        enforcement.violations = [violation]
        mock_engine.validate_action_sync.return_value = enforcement
        executor.policy_engine = mock_engine

        with patch(
            "temper_ai.tools._executor_helpers._build_policy_context"
        ) as mock_ctx:
            mock_ctx.return_value = MagicMock()
            result = validate_policy(executor, "tool", {}, {})

        assert result is not None
        assert result.success is False
        assert "blocked" in result.error.lower()

    def test_allowed_action_with_no_blocking_violations_returns_none(self):
        from temper_ai.tools._executor_helpers import validate_policy

        executor = _make_executor()
        mock_engine = MagicMock()
        enforcement = MagicMock()
        enforcement.allowed = True
        enforcement.has_blocking_violations.return_value = False
        mock_engine.validate_action_sync.return_value = enforcement
        executor.policy_engine = mock_engine
        executor.approval_workflow = None

        with patch(
            "temper_ai.tools._executor_helpers._build_policy_context"
        ) as mock_ctx:
            mock_ctx.return_value = MagicMock()
            result = validate_policy(executor, "tool", {}, {})

        assert result is None

    def test_policy_engine_exception_returns_error_result(self):
        from temper_ai.tools._executor_helpers import validate_policy

        executor = _make_executor()
        mock_engine = MagicMock()
        mock_engine.validate_action_sync.side_effect = RuntimeError("engine exploded")
        executor.policy_engine = mock_engine

        with patch(
            "temper_ai.tools._executor_helpers._build_policy_context"
        ) as mock_ctx:
            mock_ctx.return_value = MagicMock()
            result = validate_policy(executor, "tool", {}, {})

        assert result is not None
        assert result.success is False
        assert "policy validation failed" in result.error.lower()

    def test_import_error_in_policy_returns_error_result(self):
        from temper_ai.tools._executor_helpers import validate_policy

        executor = _make_executor()
        mock_engine = MagicMock()
        mock_engine.validate_action_sync.side_effect = ImportError("no module")
        executor.policy_engine = mock_engine

        with patch(
            "temper_ai.tools._executor_helpers._build_policy_context"
        ) as mock_ctx:
            mock_ctx.return_value = MagicMock()
            result = validate_policy(executor, "tool", {}, {})

        assert result is not None
        assert result.success is False


class TestCreateSnapshot:
    """Cover lines 554-584: create_snapshot."""

    def test_no_rollback_manager_returns_none(self):
        from temper_ai.tools._executor_helpers import create_snapshot

        executor = _make_executor()
        executor.rollback_manager = None
        result = create_snapshot(executor, "tool", {}, {})
        assert result is None

    def test_non_state_modifying_tool_returns_none(self):
        from temper_ai.tools._executor_helpers import create_snapshot

        executor = _make_executor()
        executor.rollback_manager = MagicMock()
        tool = MagicMock()
        metadata = MagicMock()
        metadata.modifies_state = False
        tool.get_metadata.return_value = metadata
        executor._get_tool.return_value = tool

        result = create_snapshot(executor, "tool", {}, {})
        assert result is None

    def test_snapshot_created_for_state_modifying_tool(self):
        from temper_ai.tools._executor_helpers import create_snapshot

        executor = _make_executor()
        rollback_mgr = MagicMock()
        snapshot = MagicMock()
        snapshot.id = "snap-new"
        rollback_mgr.create_snapshot.return_value = snapshot
        executor.rollback_manager = rollback_mgr

        tool = MagicMock()
        metadata = MagicMock()
        metadata.modifies_state = True
        tool.get_metadata.return_value = metadata
        executor._get_tool.return_value = tool

        with patch(
            "temper_ai.tools._executor_helpers.log_rollback_snapshot",
            side_effect=ImportError("no obs"),
            create=True,
        ):
            result = create_snapshot(executor, "tool", {}, {"workflow_id": "wf-1"})

        assert result is snapshot

    def test_snapshot_creation_exception_returns_none(self):
        from temper_ai.tools._executor_helpers import create_snapshot

        executor = _make_executor()
        rollback_mgr = MagicMock()
        rollback_mgr.create_snapshot.side_effect = OSError("disk full")
        executor.rollback_manager = rollback_mgr

        tool = MagicMock()
        metadata = MagicMock()
        metadata.modifies_state = True
        tool.get_metadata.return_value = metadata
        executor._get_tool.return_value = tool

        result = create_snapshot(executor, "tool", {}, {})
        assert result is None


class TestExecuteWithTimeout:
    """Cover lines 628-683: execute_with_timeout."""

    def _make_pool_executor(self, workers=4):
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        return pool

    def test_cache_hit_returns_cached_result(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        cached_result = ToolResult(success=True, result="cached")
        executor._tool_cache = MagicMock()
        executor._tool_cache.get.return_value = cached_result

        tool = _SimpleTool(modifies_state=False, cacheable=True)
        pool = self._make_pool_executor()
        executor._executor = pool

        result = execute_with_timeout(executor, tool, {}, 30, None, "simple_tool", {})
        pool.shutdown(wait=False)

        assert result is cached_result

    def test_successful_execution_stores_execution_time(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        executor._tool_cache = None

        tool = _SimpleTool()
        pool = self._make_pool_executor()
        executor._executor = pool

        result = execute_with_timeout(executor, tool, {}, 30, None, "simple_tool", {})
        pool.shutdown(wait=True)

        assert result.success is True
        assert "execution_time_seconds" in result.metadata

    def test_timeout_returns_timeout_error(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        executor._tool_cache = None

        stop_event = threading.Event()

        class SlowTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="slow_tool_to", description="slow")

            def execute(self, **kwargs) -> ToolResult:
                stop_event.wait(timeout=5)
                return ToolResult(success=True, result="slow")

        tool = SlowTool()
        pool = self._make_pool_executor()
        executor._executor = pool

        result = execute_with_timeout(executor, tool, {}, 1, None, "slow_tool_to", {})
        stop_event.set()  # Release the sleeping thread
        pool.shutdown(wait=False)

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_timeout_with_snapshot_triggers_timeout_rollback(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        executor._tool_cache = None
        executor.enable_auto_rollback = True
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        stop_event = threading.Event()

        class SlowTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="slow_tool_ts", description="slow")

            def execute(self, **kwargs) -> ToolResult:
                stop_event.wait(timeout=5)
                return ToolResult(success=True, result="slow")

        tool = SlowTool()
        snapshot = MagicMock()
        snapshot.id = "snap-timeout"

        pool = self._make_pool_executor()
        executor._executor = pool

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            result = execute_with_timeout(
                executor, tool, {}, 1, snapshot, "slow_tool_ts", {}
            )
        stop_event.set()  # Release the sleeping thread
        pool.shutdown(wait=False)

        assert result.success is False
        rollback_mgr.execute_rollback.assert_called_once_with("snap-timeout")

    def test_failed_result_with_snapshot_triggers_auto_rollback(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        executor._tool_cache = None
        executor.enable_auto_rollback = True
        rollback_mgr = MagicMock()
        rollback_result = MagicMock()
        rollback_result.status.value = "completed"
        rollback_result.reverted_items = []
        rollback_mgr.execute_rollback.return_value = rollback_result
        executor.rollback_manager = rollback_mgr

        class FailTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="fail_tool_ar", description="fails")

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=False, error="always fails", result=None)

        tool = FailTool()
        snapshot = MagicMock()
        snapshot.id = "snap-fail"

        pool = self._make_pool_executor()
        executor._executor = pool

        with patch("temper_ai.tools._executor_helpers._log_rollback_event"):
            result = execute_with_timeout(
                executor, tool, {}, 30, snapshot, "fail_tool_ar", {}
            )
        pool.shutdown(wait=True)

        assert result.success is False
        rollback_mgr.execute_rollback.assert_called_once_with("snap-fail")

    def test_rate_limit_error_from_concurrent_slot_returns_error(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor(max_concurrent=1)
        executor._concurrent_count = 1  # already at max
        executor._tool_cache = None

        tool = _SimpleTool()
        pool = self._make_pool_executor()
        executor._executor = pool

        result = execute_with_timeout(executor, tool, {}, 30, None, "simple_tool", {})
        pool.shutdown(wait=False)

        assert result.success is False
        assert "limit" in result.error.lower()

    def test_workflow_rate_limiter_called(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        executor._tool_cache = None
        mock_limiter = MagicMock()
        executor.workflow_rate_limiter = mock_limiter

        tool = _SimpleTool()
        pool = self._make_pool_executor()
        executor._executor = pool

        execute_with_timeout(executor, tool, {}, 30, None, "simple_tool", {})
        pool.shutdown(wait=True)

        mock_limiter.acquire.assert_called_once()

    def test_successful_result_stored_in_cache(self):
        from temper_ai.tools._executor_helpers import execute_with_timeout

        executor = _make_executor()
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache miss
        executor._tool_cache = mock_cache

        tool = _SimpleTool(modifies_state=False, cacheable=True)
        pool = self._make_pool_executor()
        executor._executor = pool

        result = execute_with_timeout(executor, tool, {}, 30, None, "simple_tool", {})
        pool.shutdown(wait=True)

        assert result.success is True
        mock_cache.put.assert_called_once()


class TestCheckApprovalRequired:
    """Cover lines 481-504: _check_approval_required."""

    def test_no_blocking_violations_returns_none(self):
        from temper_ai.tools._executor_helpers import _check_approval_required

        executor = _make_executor()
        enforcement = MagicMock()
        enforcement.has_blocking_violations.return_value = False

        result = _check_approval_required(executor, enforcement, {}, {})
        assert result is None

    def test_no_approval_workflow_returns_none(self):
        from temper_ai.tools._executor_helpers import _check_approval_required

        executor = _make_executor()
        executor.approval_workflow = None
        enforcement = MagicMock()
        enforcement.has_blocking_violations.return_value = True

        result = _check_approval_required(executor, enforcement, {}, {})
        assert result is None

    def test_approval_denied_returns_error_result(self):
        from temper_ai.tools._executor_helpers import _check_approval_required

        executor = _make_executor()
        mock_workflow = MagicMock()
        approval_request = MagicMock()
        approval_request.id = "req-001"
        mock_workflow.request_approval.return_value = approval_request
        executor.approval_workflow = mock_workflow

        enforcement = MagicMock()
        enforcement.has_blocking_violations.return_value = True
        enforcement.violations = []
        enforcement.metadata = {}

        with patch(
            "temper_ai.tools._executor_helpers.wait_for_approval", return_value=False
        ):
            result = _check_approval_required(executor, enforcement, {}, {})

        assert result is not None
        assert result.success is False
        assert "approval" in result.error.lower()

    def test_approval_granted_returns_none(self):
        from temper_ai.tools._executor_helpers import _check_approval_required

        executor = _make_executor()
        mock_workflow = MagicMock()
        approval_request = MagicMock()
        approval_request.id = "req-002"
        mock_workflow.request_approval.return_value = approval_request
        executor.approval_workflow = mock_workflow

        enforcement = MagicMock()
        enforcement.has_blocking_violations.return_value = True
        enforcement.violations = []
        enforcement.metadata = {}

        with patch(
            "temper_ai.tools._executor_helpers.wait_for_approval", return_value=True
        ):
            result = _check_approval_required(executor, enforcement, {}, {})

        assert result is None


class TestWaitForApproval:
    """Cover lines 186-199: wait_for_approval."""

    def test_returns_true_when_approved(self):
        from temper_ai.tools._executor_helpers import wait_for_approval

        executor = _make_executor()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor._approval_executor = pool

        mock_workflow = MagicMock()
        mock_workflow.is_approved.return_value = True
        mock_workflow.is_rejected.return_value = False
        executor.approval_workflow = mock_workflow

        result = wait_for_approval(executor, "req-001", poll_interval=0.01, max_wait=5)
        pool.shutdown(wait=True)
        assert result is True

    def test_returns_false_when_rejected(self):
        from temper_ai.tools._executor_helpers import wait_for_approval

        executor = _make_executor()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor._approval_executor = pool

        mock_workflow = MagicMock()
        mock_workflow.is_approved.return_value = False
        mock_workflow.is_rejected.return_value = True
        executor.approval_workflow = mock_workflow

        result = wait_for_approval(executor, "req-002", poll_interval=0.01, max_wait=5)
        pool.shutdown(wait=True)
        assert result is False

    def test_returns_false_on_deadline_exceeded(self):
        from temper_ai.tools._executor_helpers import wait_for_approval

        executor = _make_executor()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor._approval_executor = pool

        mock_workflow = MagicMock()
        mock_workflow.is_approved.return_value = False
        mock_workflow.is_rejected.return_value = False
        executor.approval_workflow = mock_workflow

        result = wait_for_approval(executor, "req-003", poll_interval=0.01, max_wait=1)
        pool.shutdown(wait=True)
        # Either False from timeout or False from deadline
        assert result is False


# ===========================================================================
# calculator.py — targeted coverage
# ===========================================================================


class TestCalculatorOverflowAndEdgeCases:
    """Cover lines 149-153, 165, 173, 185, 205, 215-217, 223, 231, 237, 246-251, 287."""

    def test_overflow_error_caught(self):
        """Line 149-150: OverflowError returned as error."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # exp of a very large number causes overflow
        result = calc.execute(expression="exp(1000000)")
        assert result.success is False
        assert (
            "math error" in result.error.lower() or "overflow" in result.error.lower()
        )

    def test_type_error_caught(self):
        """Lines 152-153: TypeError/AttributeError returned as error."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # Calling min with no args raises TypeError
        result = calc.execute(expression="min()")
        assert result.success is False

    def test_unsupported_binop_operator(self):
        """Line 165: Unsupported binary operator."""
        import ast

        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # BitAnd is not in SAFE_OPERATORS
        node = ast.BinOp(
            left=ast.Constant(value=5),
            op=ast.BitAnd(),
            right=ast.Constant(value=3),
        )
        with pytest.raises(ValueError, match="Unsupported operator"):
            calc._eval_binop(node, depth=0)

    def test_exponent_too_large(self):
        """Line 173: Exponent exceeds MAX_EXPONENT."""
        from temper_ai.tools.calculator import MAX_EXPONENT, Calculator

        calc = Calculator()
        big_exp = MAX_EXPONENT + 1
        result = calc.execute(expression=f"2 ** {big_exp}")
        assert result.success is False
        assert "exponent" in result.error.lower()

    def test_unsupported_unary_operator(self):
        """Line 185: Unsupported unary operator."""
        import ast

        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        node = ast.UnaryOp(op=ast.Invert(), operand=ast.Constant(value=5))
        with pytest.raises(ValueError, match="Unsupported unary operator"):
            calc._eval_unaryop(node, depth=0)

    def test_eval_call_keyword_args_rejected(self):
        """Line 205: Keyword arguments not supported."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # round(3.5, ndigits=0) uses keyword arg
        result = calc.execute(expression="round(3.5, ndigits=0)")
        assert result.success is False

    def test_eval_call_constant_with_args_rejected(self):
        """Lines 215-217: Constant called as function with args."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # pi is a constant, calling it as pi(2) should fail
        result = calc.execute(expression="pi(2)")
        assert result.success is False
        assert "constant" in result.error.lower()

    def test_eval_name_unknown_name_rejected(self):
        """Line 223: Unknown name in expression."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        result = calc.execute(expression="foo")
        assert result.success is False
        assert "unsupported name" in result.error.lower()

    def test_eval_name_callable_is_function_error(self):
        """Line 231: Name is a function, not a constant."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # 'sqrt' is a function; referencing without () should fail
        result = calc.execute(expression="sqrt")
        assert result.success is False
        assert "function" in result.error.lower()

    def test_list_oversized_rejected(self):
        """Lines 237: List exceeds MAX_COLLECTION_SIZE."""
        from temper_ai.tools.calculator import Calculator
        from temper_ai.tools.constants import MAX_COLLECTION_SIZE as _mc

        calc = Calculator()
        # Build a list expression too large
        big_list = "[" + ",".join(["1"] * (_mc + 1)) + "]"
        result = calc.execute(expression=f"sum({big_list})")
        assert result.success is False
        assert "size" in result.error.lower() or "maximum" in result.error.lower()

    def test_tuple_oversized_rejected(self):
        """Lines 246-251: Tuple exceeds MAX_COLLECTION_SIZE."""
        from temper_ai.tools.calculator import Calculator
        from temper_ai.tools.constants import MAX_COLLECTION_SIZE as _mc

        calc = Calculator()
        big_tuple = "(" + ",".join(["1"] * (_mc + 1)) + ")"
        result = calc.execute(expression=big_tuple)
        assert result.success is False
        assert "size" in result.error.lower() or "maximum" in result.error.lower()

    def test_unsupported_ast_node_type(self):
        """Line 287-289: Unsupported AST node type."""
        import ast

        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        node = ast.Dict(keys=[], values=[])  # Dict is not in the whitelist
        with pytest.raises(ValueError, match="Unsupported AST node type"):
            calc._safe_eval(node, depth=0)

    def test_uadd_operator(self):
        """Cover UAdd (unary +) operator path."""
        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        result = calc.execute(expression="+5")
        assert result.success is True
        assert result.result == 5

    def test_eval_constant_non_numeric_raises(self):
        """Cover _eval_constant with non-numeric constant."""
        import ast

        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        node = ast.Constant(value="hello")
        with pytest.raises(ValueError, match="Unsupported constant type"):
            calc._eval_constant(node)

    def test_eval_call_non_name_func_raises(self):
        """Cover _eval_call when func is not ast.Name."""
        import ast

        from temper_ai.tools.calculator import Calculator

        calc = Calculator()
        # Create a call with attribute access as function (not a Name node)
        node = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="math", ctx=ast.Load()),
                attr="sqrt",
                ctx=ast.Load(),
            ),
            args=[ast.Constant(value=4)],
            keywords=[],
        )
        with pytest.raises(ValueError, match="simple function names"):
            calc._eval_call(node, depth=0)

    def test_nesting_depth_exceeded(self):
        """Cover depth limit in _safe_eval."""
        from temper_ai.tools.calculator import MAX_NESTING_DEPTH, Calculator

        calc = Calculator()
        # Build deeply nested expression
        expr = "1"
        for _ in range(MAX_NESTING_DEPTH + 5):
            expr = f"abs({expr})"
        result = calc.execute(expression=expr)
        assert result.success is False
        assert "nesting depth" in result.error.lower()


# ===========================================================================
# executor.py — targeted coverage
# ===========================================================================


class TestToolExecutorBuildToolCache:
    """Cover lines 53-62: _build_tool_cache."""

    def test_cache_disabled_returns_none(self):
        from temper_ai.tools._executor_config import ToolExecutorConfig
        from temper_ai.tools.executor import _build_tool_cache

        cfg = ToolExecutorConfig(enable_tool_cache=False)
        result = _build_tool_cache(cfg)
        assert result is None

    def test_cache_enabled_returns_cache_instance(self):
        from temper_ai.tools._executor_config import ToolExecutorConfig
        from temper_ai.tools.executor import _build_tool_cache

        cfg = ToolExecutorConfig(
            enable_tool_cache=True,
            tool_cache_max_size=50,
            tool_cache_ttl=300,
        )
        result = _build_tool_cache(cfg)
        assert result is not None

    def test_cache_enabled_with_defaults(self):
        from temper_ai.tools._executor_config import ToolExecutorConfig
        from temper_ai.tools.executor import _build_tool_cache

        cfg = ToolExecutorConfig(enable_tool_cache=True)
        result = _build_tool_cache(cfg)
        assert result is not None


class TestToolExecutorInit:
    """Cover lines 102-107: config parameter handling."""

    def test_init_with_dict_config(self):
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry, config={"default_timeout": 60})
        assert executor.default_timeout == 60
        executor.shutdown(wait=False)

    def test_init_with_executor_config_object(self):
        from temper_ai.tools._executor_config import ToolExecutorConfig
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        cfg = ToolExecutorConfig(default_timeout=45)
        executor = ToolExecutor(registry, config=cfg)
        assert executor.default_timeout == 45
        executor.shutdown(wait=False)

    def test_init_with_approval_workflow_and_rollback_registers_callback(self):
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        mock_workflow = MagicMock()
        mock_rollback = MagicMock()

        executor = ToolExecutor(
            registry,
            approval_workflow=mock_workflow,
            rollback_manager=mock_rollback,
        )
        mock_workflow.on_rejected.assert_called_once()
        executor.shutdown(wait=False)


class TestToolExecutorExecute:
    """Cover lines 154, 180, 200-205, 237, 243-250, 256-258, 281-282, 286, 311."""

    def _make_registry_with_tool(self, tool):
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(tool)
        return registry

    def _make_named_tool(self, tool_name: str):
        """Create a named concrete tool for real registry use."""

        class NamedTool(BaseTool):
            _tool_name = tool_name

            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(
                    name=self._tool_name, description=f"{self._tool_name} tool"
                )

            def get_parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, result="ok")

        return NamedTool()

    def test_execute_with_none_params_defaults_to_empty_dict(self):
        from temper_ai.tools.executor import ToolExecutor

        tool = self._make_named_tool("exec_none_params")
        registry = self._make_registry_with_tool(tool)
        executor = ToolExecutor(registry)

        result = executor.execute("exec_none_params", params=None)
        assert result.success is True
        executor.shutdown(wait=False)

    def test_execute_with_none_timeout_uses_default(self):
        from temper_ai.tools.executor import ToolExecutor

        tool = self._make_named_tool("exec_none_timeout")
        registry = self._make_registry_with_tool(tool)
        executor = ToolExecutor(registry, default_timeout=30)

        result = executor.execute("exec_none_timeout", params={}, timeout=None)
        assert result.success is True
        executor.shutdown(wait=False)

    def test_execute_unknown_tool_returns_error(self):
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.execute("nonexistent_tool", {})
        assert result.success is False
        assert "not found" in result.error.lower()
        executor.shutdown(wait=False)

    def test_execute_rate_limit_exceeded_returns_error(self):
        from temper_ai.tools.executor import ToolExecutor

        tool = self._make_named_tool("exec_rate_limit")
        registry = self._make_registry_with_tool(tool)
        executor = ToolExecutor(registry, rate_limit=1, rate_window=60.0)

        # Pre-fill execution times to exceed rate limit
        now = time.time()
        executor._execution_times.append(now - 1)

        result = executor.execute("exec_rate_limit", {})
        assert result.success is False
        assert "rate limit" in result.error.lower()
        executor.shutdown(wait=False)

    def test_execute_exception_from_execute_with_timeout_handled(self):
        from temper_ai.tools.executor import ToolExecutor

        class ExceptionTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="exception_tool", description="raises")

            def get_parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs) -> ToolResult:
                raise RuntimeError("unexpected crash")

        tool = ExceptionTool()
        registry = self._make_registry_with_tool(tool)
        executor = ToolExecutor(registry)

        result = executor.execute("exception_tool", {})
        # RuntimeError is caught by execute_tool_internal
        assert result.success is False
        executor.shutdown(wait=False)

    def test_context_manager_usage(self):
        from temper_ai.tools.executor import ToolExecutor

        tool = self._make_named_tool("ctx_tool")
        registry = self._make_registry_with_tool(tool)

        with ToolExecutor(registry) as executor:
            result = executor.execute("ctx_tool", {})
            assert result.success is True

    def test_shutdown_idempotent(self):
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        executor.shutdown(wait=False)
        # Second shutdown should be a no-op
        executor.shutdown(wait=False)

    def test_repr_shows_status(self):
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        repr_str = repr(executor)
        assert "active" in repr_str
        executor.shutdown(wait=False)
        repr_str2 = repr(executor)
        assert "shutdown" in repr_str2

    def test_execute_with_workspace_blocks_escape(self, tmp_path):
        from temper_ai.tools.executor import ToolExecutor

        class PathTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="path_tool_ws", description="path tool")

            def get_parameters_schema(self) -> dict:
                return {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                }

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, result="ok")

        tool = PathTool()
        registry = self._make_registry_with_tool(tool)
        executor = ToolExecutor(registry, workspace_root=str(tmp_path))

        result = executor.execute("path_tool_ws", {"path": "/etc/passwd"})
        assert result.success is False
        executor.shutdown(wait=False)


# ===========================================================================
# file_writer.py — targeted coverage
# ===========================================================================


class TestFileWriterSyncConfig:
    """Cover lines 147-159: _sync_config."""

    def test_sync_config_updates_validator_on_root_change(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        new_root = str(tmp_path / "subdir")
        (tmp_path / "subdir").mkdir()

        # Directly change config
        writer.config["allowed_root"] = new_root
        writer._sync_config()

        assert writer._configured_root == new_root

    def test_sync_config_noop_when_root_unchanged(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        original_validator = writer.path_validator
        writer._sync_config()
        # Validator should not be replaced when root is unchanged
        assert writer.path_validator is original_validator


class TestFileWriterPrepareDirectory:
    """Cover lines 210-219: _prepare_directory."""

    def test_create_dirs_false_missing_parent_returns_error(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        path = tmp_path / "nonexistent" / "file.txt"

        error = writer._prepare_directory(path, create_dirs=False)
        assert error is not None
        assert error.success is False
        assert "parent directory does not exist" in error.error.lower()

    def test_create_dirs_true_creates_parent(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        path = tmp_path / "new_dir" / "file.txt"

        error = writer._prepare_directory(path, create_dirs=True)
        assert error is None
        assert path.parent.exists()


class TestFileWriterDoWrite:
    """Cover lines 221-266: _do_write error paths."""

    def test_permission_error_returned_as_error_result(self, tmp_path):
        from unittest.mock import patch as upatch

        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "test.txt"

        with upatch("builtins.open", side_effect=PermissionError("denied")):
            result = writer._do_write(str(file_path), "content", False, True)

        assert result.success is False
        assert "permission denied" in result.error.lower()

    def test_os_error_returned_as_error_result(self, tmp_path):
        from unittest.mock import patch as upatch

        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "test.txt"

        with upatch("builtins.open", side_effect=OSError("disk error")):
            result = writer._do_write(str(file_path), "content", False, True)

        assert result.success is False
        assert "os error" in result.error.lower()

    def test_overwritten_flag_true_when_file_existed(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "existing.txt"
        file_path.write_text("old content")

        result = writer._do_write(str(file_path), "new content", True, True)
        assert result.success is True
        assert result.metadata["overwritten"] is True

    def test_overwritten_flag_false_for_new_file(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "new.txt"

        result = writer._do_write(str(file_path), "content", False, True)
        assert result.success is True
        assert result.metadata["overwritten"] is False


class TestFileWriterRelativePathResolution:
    """Cover lines 293-300: relative path resolution with configured_root."""

    def test_relative_path_resolved_against_root(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        result = writer.execute(file_path="relative.txt", content="test")
        assert result.success is True
        assert (tmp_path / "relative.txt").exists()

    def test_absolute_path_not_modified_by_root(self, tmp_path):
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        abs_path = str(tmp_path / "absolute.txt")
        result = writer.execute(file_path=abs_path, content="test")
        assert result.success is True

    def test_no_root_non_absolute_path_resolved_internally(self, tmp_path):
        """When no allowed_root configured, relative paths go through path validation."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        # Relative path resolved against allowed_root
        result = writer.execute(file_path="relative_test.txt", content="data")
        assert result.success is True
        assert (tmp_path / "relative_test.txt").exists()


# ===========================================================================
# http_client.py — targeted coverage
# ===========================================================================


class TestValidateUrl:
    """Cover lines 44-45, 48, 60-64 in http_client.py."""

    def test_empty_url_returns_error(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url("")
        assert error is not None
        assert "non-empty" in error.lower()

    def test_non_string_url_returns_error(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url(None)  # type: ignore[arg-type]
        assert error is not None

    def test_ftp_url_returns_error(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url("ftp://example.com/file")
        assert error is not None
        assert "http" in error.lower()

    def test_url_missing_hostname_returns_error(self):
        from temper_ai.tools.http_client import _validate_url

        # Constructed URL that parses but has no hostname
        error = _validate_url("http:///path")
        assert error is not None
        assert "hostname" in error.lower()

    def test_blocked_ipv6_loopback(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url("http://[::1]/api")
        assert error is not None
        assert "blocked" in error.lower()

    def test_blocked_cloud_metadata(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url("http://169.254.169.254/metadata")
        assert error is not None
        assert "blocked" in error.lower()

    def test_valid_https_url_returns_none(self):
        from temper_ai.tools.http_client import _validate_url

        error = _validate_url("https://example.com/api")
        assert error is None


class TestValidateHeaders:
    """Cover lines 56-64 in http_client.py."""

    def test_none_headers_returns_none(self):
        from temper_ai.tools.http_client import _validate_headers

        assert _validate_headers(None) is None

    def test_non_dict_headers_returns_error(self):
        from temper_ai.tools.http_client import _validate_headers

        error = _validate_headers(["X-Header: value"])
        assert error is not None
        assert "json object" in error.lower()

    def test_too_many_headers_returns_error(self):
        from temper_ai.tools.http_client import _validate_headers
        from temper_ai.tools.http_client_constants import HTTP_MAX_HEADER_COUNT

        big_headers = {f"X-Header-{i}": "val" for i in range(HTTP_MAX_HEADER_COUNT + 1)}
        error = _validate_headers(big_headers)
        assert error is not None
        assert "too many" in error.lower()

    def test_valid_headers_returns_none(self):
        from temper_ai.tools.http_client import _validate_headers

        assert _validate_headers({"Authorization": "Bearer token"}) is None


class TestHTTPClientToolExecute:
    """Cover lines 146, 182-185 in http_client.py."""

    def _mock_client_context(self, status=200, body="ok", headers=None):
        """Helper to set up a mock httpx.Client context manager."""
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.text = body
        mock_response.headers = headers or {}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        return mock_client

    def test_truncated_large_response(self):
        """Line 164-165: Response larger than HTTP_MAX_RESPONSE_SIZE is truncated."""
        from temper_ai.tools.http_client import HTTPClientTool
        from temper_ai.tools.http_client_constants import HTTP_MAX_RESPONSE_SIZE

        tool = HTTPClientTool()
        large_body = "x" * (HTTP_MAX_RESPONSE_SIZE + 100)
        mock_client = self._mock_client_context(body=large_body)

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(url="https://example.com/large")

        assert result.success is True
        assert result.result["truncated"] is True
        assert len(result.result["body"]) == HTTP_MAX_RESPONSE_SIZE

    def test_http_error_returns_failed_result(self):
        """Lines 182-183: httpx.HTTPError returns failed result."""
        import httpx

        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.HTTPError("connection refused")

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(url="https://example.com/api")

        assert result.success is False
        assert "http error" in result.error.lower()

    def test_value_error_returns_failed_result(self):
        """Lines 184-185: ValueError returns failed result."""
        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = ValueError("bad request")

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(url="https://example.com/api")

        assert result.success is False
        assert "invalid request" in result.error.lower()

    def test_execute_with_invalid_headers_returns_error(self):
        """Line 146: headers_error path in execute."""
        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        result = tool.execute(url="https://example.com", headers="not-a-dict")
        assert result.success is False
        assert "json object" in result.error.lower()

    def test_head_method(self):
        """Cover HEAD method path."""
        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        mock_client = self._mock_client_context(status=200, body="")

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(url="https://example.com", method="HEAD")

        assert result.success is True

    def test_delete_method(self):
        """Cover DELETE method path."""
        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        mock_client = self._mock_client_context(status=204, body="")

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(url="https://example.com/resource", method="DELETE")

        assert result.success is True

    def test_patch_method(self):
        """Cover PATCH method path."""
        from temper_ai.tools.http_client import HTTPClientTool

        tool = HTTPClientTool()
        mock_client = self._mock_client_context(status=200, body='{"updated": true}')

        with patch(
            "temper_ai.tools.http_client.httpx.Client", return_value=mock_client
        ):
            result = tool.execute(
                url="https://example.com/resource",
                method="PATCH",
                body={"name": "new name"},
            )

        assert result.success is True


# ===========================================================================
# json_parser.py — targeted coverage
# ===========================================================================


class TestJsonParserCoverage:
    """Cover lines 44-45, 50, 57-58, 144, 176, 197 in json_parser.py."""

    def test_empty_data_returns_error(self):
        """Line 144: empty data string."""
        from temper_ai.tools.json_parser import JSONParserTool

        tool = JSONParserTool()
        result = tool.execute(data="", operation="parse")
        assert result.success is False
        assert "non-empty" in result.error.lower()

    def test_non_string_data_returns_error(self):
        """Line 143-144: non-string data."""
        from temper_ai.tools.json_parser import JSONParserTool

        tool = JSONParserTool()
        result = tool.execute(data=None, operation="parse")  # type: ignore[arg-type]
        assert result.success is False

    def test_extract_with_array_index_out_of_range(self):
        """Line 50: array index out of range."""

        from temper_ai.tools.json_parser import _extract_by_path

        parsed = {"items": [1, 2, 3]}
        value, error = _extract_by_path(parsed, "items.5")
        assert value is None
        assert "out of range" in error.lower()

    def test_extract_when_index_used_on_non_list(self):
        """Lines 44-45: array index on non-list."""
        from temper_ai.tools.json_parser import _extract_by_path

        parsed = {"name": "Alice"}
        value, error = _extract_by_path(parsed, "name.0")
        assert value is None
        assert "not a list" in error.lower()

    def test_extract_when_key_used_on_non_dict(self):
        """Lines 57-58: key access on non-dict."""
        from temper_ai.tools.json_parser import _extract_by_path

        parsed = {"items": [1, 2, 3]}
        value, error = _extract_by_path(parsed, "items.foo")
        assert value is None
        assert "not a dict" in error.lower()

    def test_format_with_invalid_json_returns_error(self):
        """Line 197: format operation with invalid JSON."""
        from temper_ai.tools.json_parser import JSONParserTool

        tool = JSONParserTool()
        result = tool.execute(data="not valid {json", operation="format")
        assert result.success is False
        assert "invalid json" in result.error.lower()

    def test_extract_with_invalid_json_returns_error(self):
        """Line 176: extract operation with invalid JSON."""
        from temper_ai.tools.json_parser import JSONParserTool

        tool = JSONParserTool()
        result = tool.execute(data="bad json", operation="extract", path="x")
        assert result.success is False
        assert "invalid json" in result.error.lower()

    def test_validate_with_schema_valid_required_keys(self):
        """Cover schema validation with all required keys present."""
        from temper_ai.tools.json_parser import JSONParserTool

        tool = JSONParserTool()
        import json

        data = json.dumps({"name": "Alice", "age": 30})
        result = tool.execute(
            data=data,
            operation="validate",
            schema={"required": ["name", "age"]},
        )
        assert result.success is True
        assert result.result["valid"] is True

    def test_validate_with_non_dict_schema_ignored(self):
        """Cover schema validation when schema is not a dict."""
        from temper_ai.tools.json_parser import _validate_json

        is_valid, error = _validate_json('{"x": 1}', schema=None)
        assert is_valid is True
        assert error is None

    def test_parse_json_error_returned(self):
        """Cover _parse_json returning error."""
        from temper_ai.tools.json_parser import _parse_json

        parsed, error = _parse_json("invalid {")
        assert parsed is None
        assert error is not None
        assert "invalid json" in error.lower()


# ===========================================================================
# loader.py — targeted coverage
# ===========================================================================


class TestLoaderCoverage:
    """Cover lines 23, 126-128, 146-147 in loader.py."""

    def test_ensure_tools_discovered_is_noop(self):
        """ensure_tools_discovered is now a no-op (lazy loading)."""
        from temper_ai.tools.loader import ensure_tools_discovered

        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = []

        ensure_tools_discovered(mock_registry)

        # Should not call auto_discover — function is a no-op
        mock_registry.auto_discover.assert_not_called()

    def test_resolve_single_tool_calls_validate_config_after_template_resolution(self):
        """Lines 125-133: validate_config called after template resolution."""
        from temper_ai.tools.loader import _resolve_single_tool_templates

        tool = MagicMock()
        tool.config = {"url": "https://{{host}}/api"}

        validation_result = SimpleNamespace(valid=False, error_message="Bad config")
        tool.validate_config.return_value = validation_result

        with patch("temper_ai.tools.loader.logger") as mock_logger:
            _resolve_single_tool_templates(tool, {"host": "example.com"}, "test-agent")

        # Should have logged warning about validation failure
        mock_logger.warning.assert_called()

    def test_resolve_single_tool_valid_config_no_warning(self):
        """Lines 124-133: No warning when config is valid after resolution."""
        from temper_ai.tools.loader import _resolve_single_tool_templates

        tool = MagicMock()
        tool.config = {"url": "https://{{host}}/api"}

        validation_result = SimpleNamespace(valid=True, error_message="")
        tool.validate_config.return_value = validation_result

        with patch("temper_ai.tools.loader.logger") as mock_logger:
            _resolve_single_tool_templates(tool, {"host": "example.com"}, "test-agent")

        # No warning for valid config
        for call in mock_logger.warning.call_args_list:
            assert "validation" not in str(call).lower()

    def test_resolve_tool_config_templates_attribute_error_is_handled(self):
        """Lines 146-147: AttributeError from get_all_tools is silently handled."""
        from temper_ai.tools.loader import resolve_tool_config_templates

        mock_registry = MagicMock()
        mock_registry.get_all_tools.side_effect = AttributeError("no attr")

        # Should not raise
        resolve_tool_config_templates(mock_registry, {}, "agent")

    def test_resolve_tool_config_templates_type_error_is_handled(self):
        """Lines 146-147: TypeError from get_all_tools is silently handled."""
        from temper_ai.tools.loader import resolve_tool_config_templates

        mock_registry = MagicMock()
        mock_registry.get_all_tools.side_effect = TypeError("bad type")

        # Should not raise
        resolve_tool_config_templates(mock_registry, {}, "agent")

    def test_apply_tool_config_tool_without_config_attr(self):
        """Cover apply_tool_config when tool has no config attribute."""
        from temper_ai.tools.loader import apply_tool_config

        class NoConfigTool:
            pass

        tool = NoConfigTool()
        # Should not raise even when no config attribute
        apply_tool_config(tool, "tool_name", {"key": "value"})


# ===========================================================================
# executor.py — additional targeted coverage
# ===========================================================================


class TestToolExecutorAdditionalCoverage:
    """Cover remaining uncovered lines in executor.py."""

    def test_execute_policy_error_returned(self):
        """Line 185-186: policy_error returned from execute."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        class SimpleReg(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="pol_tool", description="policy tool")

            def get_parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True)

        registry = ToolRegistry()
        registry.register(SimpleReg())

        mock_engine = MagicMock()
        enforcement = MagicMock()
        enforcement.allowed = False
        violation = MagicMock()
        violation.message = "blocked"
        violation.to_dict.return_value = {}
        enforcement.violations = [violation]
        mock_engine.validate_action_sync.return_value = enforcement

        with patch(
            "temper_ai.tools._executor_helpers._build_policy_context"
        ) as mock_ctx:
            mock_ctx.return_value = MagicMock()
            executor = ToolExecutor(registry, policy_engine=mock_engine)
            result = executor.execute("pol_tool", {})

        assert result.success is False
        assert "blocked" in result.error.lower()
        executor.shutdown(wait=False)

    def test_cleanup_executor_with_none_approval_executor(self):
        """Line 237: pool is None in _cleanup_executor."""
        from temper_ai.tools.executor import ToolExecutor

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        # Call with approval_executor=None — covers the `if pool is None: continue` branch
        ToolExecutor._cleanup_executor(pool, approval_executor=None)

    def test_shutdown_raises_on_os_error(self):
        """Lines 256-258: OSError during shutdown re-raised."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        with patch.object(
            executor._executor, "shutdown", side_effect=OSError("io error")
        ):
            with pytest.raises(OSError, match="io error"):
                executor.shutdown(wait=True)

    def test_del_exception_handled(self):
        """Lines 281-282: Exception in __del__ is caught."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        with patch.object(executor, "shutdown", side_effect=RuntimeError("del error")):
            # Manually call __del__ to test exception handling
            executor.__del__()
            # Should not raise

    def test_attached_methods_work(self):
        """Line 311: _check_rate_limit bound method."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        executor = ToolExecutor(registry, rate_limit=10, rate_window=60.0)

        # Call the monkey-patched methods
        executor._acquire_concurrent_slot()
        executor._release_concurrent_slot()
        executor._check_rate_limit()
        count = executor.get_concurrent_execution_count()
        assert count == 0
        usage = executor.get_rate_limit_usage()
        assert "rate_limit" in usage
        executor.shutdown(wait=False)


# ===========================================================================
# file_writer.py — additional targeted coverage
# ===========================================================================


class TestFileWriterAdditionalCoverage:
    """Cover remaining uncovered lines in file_writer.py."""

    def test_normalize_params_canonical_key_wins(self):
        """Line 114: canonical key wins over previously-mapped alias."""
        from temper_ai.tools.file_writer import FileWriter

        # Both file_path (canonical) and path (alias) present
        # file_path should win since it's processed and set first or alias processed first
        params = {"path": "/alias/path", "file_path": "/canonical/path", "content": "x"}
        result = FileWriter._normalize_params(params)
        # The canonical key should be the final value
        assert result["file_path"] == "/canonical/path"

    def test_validate_path_directory_returns_error(self, tmp_path):
        """Line 197: path.is_dir() returns error."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        dir_path = tmp_path / "subdir"
        dir_path.mkdir()

        path, error = writer._validate_path(str(dir_path), False, True)
        assert path is None
        assert error is not None
        assert "directory" in error.error.lower()

    def test_do_write_prepare_directory_error(self, tmp_path):
        """Line 243: _prepare_directory returns error."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        # Path in non-existent parent with create_dirs=False
        file_path = str(tmp_path / "nonexistent_parent" / "file.txt")

        result = writer._do_write(file_path, "content", False, False)
        assert result.success is False
        assert "parent directory does not exist" in result.error.lower()

    def test_do_write_unicode_error(self, tmp_path):
        """Lines 265-266: UnicodeError caught in _do_write."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "unicode_test.txt"

        with patch("builtins.open") as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.write.side_effect = UnicodeError("encoding error")
            mock_open.return_value = mock_file

            result = writer._do_write(str(file_path), "content", False, True)

        assert result.success is False
        assert "unexpected error" in result.error.lower()

    def test_execute_with_canonical_alias_both_present(self, tmp_path):
        """Line 300: execute reaches _do_write with both file_path and content valid."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        file_path = tmp_path / "test_execute.txt"

        # Use aliases to trigger normalization code path
        result = writer.execute(path=str(file_path), text="test content")
        assert result.success is True
        assert file_path.read_text() == "test content"

    def test_sync_config_changes_root_to_none(self, tmp_path):
        """Line 158: PathSafetyValidator recreated with None root."""
        from temper_ai.tools.file_writer import FileWriter

        writer = FileWriter(config={"allowed_root": str(tmp_path)})
        assert writer._configured_root is not None

        # Change root to None
        writer.config["allowed_root"] = None
        writer._sync_config()
        assert writer._configured_root is None


# ===========================================================================
# _registry_helpers.py — targeted coverage
# ===========================================================================


class TestRegistryHelpersCoverage:
    """Cover gaps in _registry_helpers.py."""

    def test_validate_tool_interface_with_non_class_raises_type_error(self):
        """Lines 58-60: issubclass(not_a_class) raises TypeError."""
        from temper_ai.tools._registry_helpers import validate_tool_interface

        # Passing a string as tool_class causes TypeError in issubclass
        valid, errors = validate_tool_interface("not_a_class")  # type: ignore[arg-type]
        assert valid is False
        assert any("invalid tool class" in e.lower() for e in errors)

    def test_lazy_get_from_static_registry(self):
        """TOOL_CLASSES-backed lazy get creates instances on demand."""
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        assert registry.list_tools() == []
        tool = registry.get("Calculator")
        assert tool is not None
        assert tool.name == "Calculator"

    def test_has_checks_static_registry(self):
        """has() checks TOOL_CLASSES without instantiation."""
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        assert registry.has("Bash")
        assert not registry.has("NonExistentTool")

    def test_list_available_returns_all_known(self):
        """list_available() returns TOOL_CLASSES + registered."""
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        available = registry.list_available()
        assert "Bash" in available
        assert "Calculator" in available
        assert len(available) >= 8

    def test_auto_discover_deprecated_returns_count(self):
        """auto_discover() is deprecated and returns TOOL_CLASSES count."""
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            count = registry.auto_discover()
        from temper_ai.tools import TOOL_CLASSES

        assert count == len(TOOL_CLASSES)

    def test_get_registration_report_with_no_tools(self):
        """Lines 360-361: Report when no tools registered."""
        from temper_ai.tools._registry_helpers import get_registration_report
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        report = get_registration_report(registry)
        assert "no tools registered" in report.lower()

    def _make_concrete_tool(self, tool_name: str):
        """Return a concrete BaseTool with the given name."""

        class ConcreteTool(BaseTool):
            _n = tool_name

            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name=self._n, description=f"{self._n} tool")

            def get_parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True)

        return ConcreteTool()

    def test_get_registration_report_with_tools(self):
        """Lines 458-461: Report when tools are registered."""
        from temper_ai.tools._registry_helpers import get_registration_report
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_concrete_tool("report_tool"))

        report = get_registration_report(registry)
        assert "report_tool" in report.lower()

    def test_list_available_tools_returns_dict(self):
        """Cover list_available_tools."""
        from temper_ai.tools._registry_helpers import list_available_tools
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_concrete_tool("list_tool"))

        tools = list_available_tools(registry)
        assert "list_tool" in tools
        assert "description" in tools["list_tool"]

    def test_get_tool_metadata_known_tool(self):
        """Cover get_tool_metadata for known tool."""
        from temper_ai.tools._registry_helpers import get_tool_metadata
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_concrete_tool("meta_tool"))

        metadata = get_tool_metadata(registry, "meta_tool")
        assert metadata["name"] == "meta_tool"

    def test_get_tool_metadata_unknown_tool_raises(self):
        """Cover get_tool_metadata for unknown tool."""
        from temper_ai.shared.utils.exceptions import ToolRegistryError
        from temper_ai.tools._registry_helpers import get_tool_metadata
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(ToolRegistryError, match="not found"):
            get_tool_metadata(registry, "nonexistent")

    def test_get_latest_version_with_unparseable_version(self):
        """Lines 502-503: Unparseable version strings."""
        from temper_ai.tools._registry_helpers import get_latest_version

        # When versions are not parseable, fallback to (0,0,0) comparison
        result = get_latest_version(["abc", "def", "1.0"])
        assert result == "1.0"

    def test_tool_registry_validation_mixin(self):
        """Cover ToolRegistryValidationMixin methods."""
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()

        class ConcreteTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name="concrete", description="test")

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True)

        valid, errors = registry._validate_tool_interface(ConcreteTool)
        assert valid is True

        suggestion = registry._get_error_suggestion("requires init arguments")
        assert suggestion is not None

    def test_load_from_config_missing_name_raises(self):
        """Lines 370-373: Missing 'name' field raises ToolRegistryError."""
        from temper_ai.shared.utils.exceptions import ToolRegistryError
        from temper_ai.tools._registry_helpers import load_from_config
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        mock_loader = MagicMock()
        mock_loader.load_tool.return_value = {"tool": {"implementation": "some.Class"}}

        with pytest.raises(ToolRegistryError, match="missing 'name'"):
            load_from_config(registry, "unnamed_tool", mock_loader)

    def test_load_from_config_loader_error_raises(self):
        """Lines 358-363: Config load failure raises ToolRegistryError."""
        from temper_ai.shared.utils.exceptions import ToolRegistryError
        from temper_ai.tools._registry_helpers import load_from_config
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        mock_loader = MagicMock()
        mock_loader.load_tool.side_effect = FileNotFoundError("config not found")

        with pytest.raises(
            ToolRegistryError, match="Failed to load tool configuration"
        ):
            load_from_config(registry, "bad_config", mock_loader)

    def test_load_all_from_configs_lists_error_returns_zero(self):
        """Lines 402-405: list_configs error returns 0."""
        from temper_ai.tools._registry_helpers import load_all_from_configs
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        mock_loader = MagicMock()
        mock_loader.list_configs.side_effect = OSError("cannot list")

        result = load_all_from_configs(registry, mock_loader)
        assert result == 0

    def test_load_all_from_configs_skips_failures(self):
        """Cover load_all_from_configs skipping individual failures."""
        from temper_ai.shared.utils.exceptions import ToolRegistryError
        from temper_ai.tools._registry_helpers import load_all_from_configs
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        mock_loader = MagicMock()
        mock_loader.list_configs.return_value = ["tool1", "tool2"]
        mock_loader.load_tool.side_effect = ToolRegistryError("bad tool")

        result = load_all_from_configs(registry, mock_loader)
        assert result == 0
