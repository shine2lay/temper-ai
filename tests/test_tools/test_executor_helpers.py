"""Tests for temper_ai/tools/_executor_helpers.py."""

from __future__ import annotations

import collections
import concurrent.futures
import threading
import time
from unittest.mock import MagicMock

import pytest

from temper_ai.shared.utils.exceptions import RateLimitError
from temper_ai.tools._executor_helpers import (
    _is_tool_cacheable,
    acquire_concurrent_slot,
    check_rate_limit,
    execute_batch,
    execute_tool_internal,
    get_concurrent_execution_count,
    get_rate_limit_usage,
    release_concurrent_slot,
    should_snapshot,
    validate_and_get_tool,
    validate_tool_call,
    validate_workspace_path,
)
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(max_concurrent=None, rate_limit=None, rate_window=60.0):
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
    return executor


class _MockTool(BaseTool):
    """Minimal concrete tool for testing."""

    def __init__(self, name="mock_tool", modifies_state=True, cacheable=None):
        self._name = name
        self._modifies_state = modifies_state
        self._cacheable = cacheable

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self._name,
            description="A mock tool for testing",
            modifies_state=self._modifies_state,
            cacheable=self._cacheable,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


# ---------------------------------------------------------------------------
# TestValidateWorkspacePath
# ---------------------------------------------------------------------------


class TestValidateWorkspacePath:
    def test_valid_path_within_workspace(self, tmp_path):
        target = tmp_path / "subdir" / "file.txt"
        # Should not raise
        validate_workspace_path(str(target), tmp_path)

    def test_null_bytes_raise_value_error(self, tmp_path):
        with pytest.raises(ValueError, match="null bytes"):
            validate_workspace_path("/tmp/file\x00.txt", tmp_path)

    def test_path_outside_workspace_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError, match="outside workspace"):
            validate_workspace_path("/etc/passwd", tmp_path)

    def test_path_traversal_blocked(self, tmp_path):
        traversal = str(tmp_path / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="outside workspace"):
            validate_workspace_path(traversal, tmp_path)


# ---------------------------------------------------------------------------
# TestAcquireConcurrentSlot
# ---------------------------------------------------------------------------


class TestAcquireConcurrentSlot:
    def test_acquires_slot_and_increments_count(self):
        executor = _make_executor()
        result = acquire_concurrent_slot(executor)
        assert result is True
        assert executor._concurrent_count == 1

    def test_raises_rate_limit_error_at_limit(self):
        executor = _make_executor(max_concurrent=2)
        executor._concurrent_count = 2
        with pytest.raises(RateLimitError):
            acquire_concurrent_slot(executor)

    def test_no_limit_allows_increment_past_arbitrary_count(self):
        executor = _make_executor(max_concurrent=None)
        executor._concurrent_count = 99
        acquire_concurrent_slot(executor)
        assert executor._concurrent_count == 100


# ---------------------------------------------------------------------------
# TestCheckRateLimit
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    def test_no_rate_limit_is_noop(self):
        executor = _make_executor(rate_limit=None)
        check_rate_limit(executor)  # must not raise
        assert len(executor._execution_times) == 0

    def test_within_limit_passes_and_records_time(self):
        executor = _make_executor(rate_limit=5, rate_window=60.0)
        # Add 2 recent entries
        now = time.time()
        executor._execution_times = collections.deque([now - 5, now - 10])
        before_len = len(executor._execution_times)
        check_rate_limit(executor)  # must not raise
        assert len(executor._execution_times) == before_len + 1

    def test_exceeded_limit_raises_rate_limit_error(self):
        executor = _make_executor(rate_limit=3, rate_window=60.0)
        now = time.time()
        executor._execution_times = collections.deque([now - 1, now - 2, now - 3])
        with pytest.raises(RateLimitError):
            check_rate_limit(executor)

    def test_expired_entries_pruned_before_check(self):
        executor = _make_executor(rate_limit=3, rate_window=10.0)
        old = time.time() - 20  # outside the 10-second window
        executor._execution_times = collections.deque([old, old, old])
        # After pruning, count is 0 < 3 — should not raise
        check_rate_limit(executor)
        # Only the newly appended timestamp should remain
        assert len(executor._execution_times) == 1


# ---------------------------------------------------------------------------
# TestReleaseConcurrentSlot
# ---------------------------------------------------------------------------


class TestReleaseConcurrentSlot:
    def test_decrements_count(self):
        executor = _make_executor()
        executor._concurrent_count = 3
        release_concurrent_slot(executor)
        assert executor._concurrent_count == 2


# ---------------------------------------------------------------------------
# TestGetConcurrentExecutionCount
# ---------------------------------------------------------------------------


class TestGetConcurrentExecutionCount:
    def test_returns_current_count(self):
        executor = _make_executor()
        executor._concurrent_count = 7
        assert get_concurrent_execution_count(executor) == 7

    def test_returns_zero_initially(self):
        executor = _make_executor()
        assert get_concurrent_execution_count(executor) == 0


# ---------------------------------------------------------------------------
# TestGetRateLimitUsage
# ---------------------------------------------------------------------------


class TestGetRateLimitUsage:
    def test_no_rate_limit_returns_dict_with_none(self):
        executor = _make_executor(rate_limit=None, rate_window=60.0)
        usage = get_rate_limit_usage(executor)
        assert usage["rate_limit"] is None
        assert usage["current_usage"] == 0
        assert usage["window_seconds"] == 60.0

    def test_with_rate_limit_returns_usage_dict(self):
        executor = _make_executor(rate_limit=10, rate_window=60.0)
        now = time.time()
        executor._execution_times = collections.deque([now - 5, now - 10])
        usage = get_rate_limit_usage(executor)
        assert usage["rate_limit"] == 10
        assert "current_usage" in usage
        assert "available" in usage
        assert usage["window_seconds"] == 60.0
        assert usage["available"] == 10 - usage["current_usage"]


# ---------------------------------------------------------------------------
# TestExecuteToolInternal
# ---------------------------------------------------------------------------


class TestExecuteToolInternal:
    def test_success_result_returned(self):
        tool = MagicMock()
        tool.execute.return_value = ToolResult(success=True, result="hello")
        result = execute_tool_internal(tool, {"key": "value"})
        assert result.success is True
        assert result.result == "hello"

    def test_catches_runtime_error(self):
        tool = MagicMock()
        tool.execute.side_effect = RuntimeError("boom")
        result = execute_tool_internal(tool, {})
        assert result.success is False
        assert "boom" in result.error

    def test_catches_type_error(self):
        tool = MagicMock()
        tool.execute.side_effect = TypeError("bad type")
        result = execute_tool_internal(tool, {})
        assert result.success is False
        assert "bad type" in result.error

    def test_catches_value_error(self):
        tool = MagicMock()
        tool.execute.side_effect = ValueError("bad value")
        result = execute_tool_internal(tool, {})
        assert result.success is False
        assert "bad value" in result.error

    def test_catches_os_error(self):
        tool = MagicMock()
        tool.execute.side_effect = OSError("file error")
        result = execute_tool_internal(tool, {})
        assert result.success is False
        assert "file error" in result.error


# ---------------------------------------------------------------------------
# TestShouldSnapshot
# ---------------------------------------------------------------------------


class TestShouldSnapshot:
    def test_modifies_state_true_returns_true(self):
        executor = _make_executor()
        tool = _MockTool(modifies_state=True)
        executor.registry.get.return_value = tool
        assert should_snapshot(executor, "mock_tool", {}) is True

    def test_modifies_state_false_returns_false(self):
        executor = _make_executor()
        tool = _MockTool(modifies_state=False)
        executor.registry.get.return_value = tool
        assert should_snapshot(executor, "mock_tool", {}) is False

    def test_unknown_tool_returns_false(self):
        executor = _make_executor()
        executor.registry.get.return_value = None
        assert should_snapshot(executor, "nonexistent", {}) is False


# ---------------------------------------------------------------------------
# TestValidateToolCall
# ---------------------------------------------------------------------------


class TestValidateToolCall:
    def test_valid_tool_and_params_passes(self):
        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.return_value = MagicMock(valid=True)
        executor.registry.get.return_value = tool
        valid, error = validate_tool_call(executor, "my_tool", {})
        assert valid is True
        assert error is None

    def test_unknown_tool_fails(self):
        executor = _make_executor()
        executor.registry.get.return_value = None
        valid, error = validate_tool_call(executor, "nonexistent", {})
        assert valid is False
        assert "not found" in error

    def test_invalid_params_fails(self):
        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.return_value = MagicMock(valid=False)
        executor.registry.get.return_value = tool
        valid, error = validate_tool_call(executor, "my_tool", {"bad": "param"})
        assert valid is False
        assert error is not None

    def test_validation_exception_returns_false(self):
        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.side_effect = TypeError("unexpected type")
        executor.registry.get.return_value = tool
        valid, error = validate_tool_call(executor, "my_tool", {})
        assert valid is False
        assert "validation failed" in error.lower()


# ---------------------------------------------------------------------------
# TestIsToolCacheable
# ---------------------------------------------------------------------------


class TestIsToolCacheable:
    def test_cacheable_true_explicit(self):
        tool = _MockTool(modifies_state=True, cacheable=True)
        assert _is_tool_cacheable(tool) is True

    def test_cacheable_false_explicit(self):
        tool = _MockTool(modifies_state=False, cacheable=False)
        assert _is_tool_cacheable(tool) is False

    def test_cacheable_none_read_only_tool(self):
        # cacheable=None, modifies_state=False → should be cacheable
        tool = _MockTool(modifies_state=False, cacheable=None)
        assert _is_tool_cacheable(tool) is True

    def test_cacheable_none_stateful_tool(self):
        # cacheable=None, modifies_state=True → should NOT be cacheable
        tool = _MockTool(modifies_state=True, cacheable=None)
        assert _is_tool_cacheable(tool) is False


# ---------------------------------------------------------------------------
# TestExecuteBatch
# ---------------------------------------------------------------------------


class TestExecuteBatch:
    def test_parallel_execution_returns_all_results(self):
        executor = _make_executor()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        executor._executor = pool

        success_result = ToolResult(success=True, result="done")

        def fake_execute(tool_name, params, timeout):
            return success_result

        executor.execute = fake_execute
        executions = [("tool_a", {}), ("tool_b", {})]
        results = execute_batch(executor, executions)
        pool.shutdown(wait=True)

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_overall_timeout_fills_pending_results(self):
        executor = _make_executor()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        executor._executor = pool

        def slow_execute(tool_name, params, timeout):
            time.sleep(10)
            return ToolResult(success=True, result="done")

        executor.execute = slow_execute
        executions = [("slow_tool", {})]
        results = execute_batch(executor, executions, overall_timeout=0.05)
        pool.shutdown(wait=False)

        assert len(results) == 1
        assert results[0].success is False
        assert "timeout" in results[0].error.lower()


# ---------------------------------------------------------------------------
# TestValidateAndGetTool
# ---------------------------------------------------------------------------


class TestValidateAndGetTool:
    def test_valid_tool_and_params_returns_tool(self):
        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.return_value = MagicMock(valid=True)
        executor.registry.get.return_value = tool

        result_tool, error = validate_and_get_tool(executor, "my_tool", {})
        assert result_tool is tool
        assert error is None

    def test_workspace_path_validation_blocks_escape(self, tmp_path):
        executor = _make_executor()
        executor.workspace_root = tmp_path
        outside_params = {"path": "/etc/passwd"}
        tool_mock = MagicMock()
        tool_mock.validate_params.return_value = MagicMock(valid=True)
        executor.registry.get.return_value = tool_mock

        result_tool, error_result = validate_and_get_tool(
            executor, "my_tool", outside_params
        )
        assert result_tool is None
        assert error_result is not None
        assert error_result.success is False

    def test_unknown_tool_returns_error_result(self):
        executor = _make_executor()
        executor.registry.get.return_value = None

        result_tool, error_result = validate_and_get_tool(executor, "nonexistent", {})
        assert result_tool is None
        assert error_result.success is False
        assert "not found" in error_result.error

    def test_invalid_params_returns_error_result(self):
        executor = _make_executor()
        tool = MagicMock()
        tool.validate_params.return_value = MagicMock(valid=False)
        executor.registry.get.return_value = tool

        result_tool, error_result = validate_and_get_tool(executor, "my_tool", {})
        assert result_tool is None
        assert error_result.success is False
