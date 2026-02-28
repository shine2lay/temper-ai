"""Coverage tests for temper_ai/llm/_tool_execution.py.

Covers: _shutdown_tool_executor, parallel execution error path,
execute_single_tool type validations (non-string name, non-dict params).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from temper_ai.llm._tool_execution import (
    _get_tool_executor,
    _shutdown_tool_executor,
    execute_single_tool,
    execute_tools,
)
from temper_ai.shared.utils.exceptions import ToolExecutionError


class TestShutdownToolExecutor:
    def test_shutdown_when_none(self) -> None:
        """Shutdown should be a no-op when executor is None."""
        import temper_ai.llm._tool_execution as mod

        original = mod._tool_executor
        mod._tool_executor = None
        _shutdown_tool_executor()
        assert mod._tool_executor is None
        mod._tool_executor = original

    def test_shutdown_with_executor(self) -> None:
        """Shutdown should close the executor and set to None."""
        import temper_ai.llm._tool_execution as mod

        # Force creation
        _get_tool_executor()
        assert mod._tool_executor is not None
        _shutdown_tool_executor()
        assert mod._tool_executor is None


class TestExecuteSingleToolValidation:
    def test_non_string_name_raises(self) -> None:
        tool_call = {"name": 123, "parameters": {}}
        with pytest.raises(TypeError, match="must be a string"):
            execute_single_tool(tool_call, None, None, None)

    def test_non_dict_params_raises(self) -> None:
        tool_call = {"name": "test", "parameters": "not-a-dict"}
        with pytest.raises(TypeError, match="must be a dictionary"):
            execute_single_tool(tool_call, None, None, None)

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must contain 'name'"):
            execute_single_tool({"parameters": {}}, None, None, None)

    def test_not_dict_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a dictionary"):
            execute_single_tool("not-a-dict", None, None, None)  # type: ignore[arg-type]


class TestParallelExecutionErrors:
    def test_parallel_error_handling(self) -> None:
        """Test that parallel execution catches errors from futures."""

        def failing_execute(tc: Any, executor: Any, observer: Any, safety: Any) -> dict:
            raise ToolExecutionError("parallel fail", tool_name="test")

        tool_calls = [
            {"name": "tool1", "parameters": {}},
            {"name": "tool2", "parameters": {}},
        ]

        # Enable parallel (more than 1 tool call + parallel enabled)
        results = execute_tools(
            tool_calls,
            None,
            None,
            None,  # safety_config=None means parallel_tool_calls defaults to True
            failing_execute,
        )
        # Both should have error results
        assert len(results) == 2
        for r in results:
            assert r["success"] is False
            assert "Parallel execution error" in r["error"]

    def test_parallel_with_timeout_error(self) -> None:
        """Test parallel execution with TimeoutError."""

        def timeout_execute(tc: Any, executor: Any, observer: Any, safety: Any) -> dict:
            raise TimeoutError("timed out")

        tool_calls = [
            {"name": "tool1", "parameters": {}},
            {"name": "tool2", "parameters": {}},
        ]

        results = execute_tools(tool_calls, None, None, None, timeout_execute)
        assert all(not r["success"] for r in results)

    def test_parallel_with_runtime_error(self) -> None:
        """Test parallel execution with RuntimeError."""

        def runtime_execute(tc: Any, executor: Any, observer: Any, safety: Any) -> dict:
            raise RuntimeError("runtime fail")

        tool_calls = [
            {"name": "tool1", "parameters": {}},
            {"name": "tool2", "parameters": {}},
        ]

        results = execute_tools(tool_calls, None, None, None, runtime_execute)
        assert all(not r["success"] for r in results)


class TestExecuteToolsSerial:
    def test_serial_single_call(self) -> None:
        """Test serial execution with single tool call."""
        mock_execute = MagicMock(return_value={"name": "t", "success": True})
        tool_calls = [{"name": "t", "parameters": {}}]
        results = execute_tools(tool_calls, None, None, None, mock_execute)
        assert len(results) == 1
        assert results[0]["success"] is True

    def test_serial_when_parallel_disabled(self) -> None:
        """Test that parallel is disabled when safety config says so."""
        safety = MagicMock()
        safety.parallel_tool_calls = False

        mock_execute = MagicMock(return_value={"name": "t", "success": True})
        tool_calls = [
            {"name": "t1", "parameters": {}},
            {"name": "t2", "parameters": {}},
        ]
        results = execute_tools(tool_calls, None, None, safety, mock_execute)
        assert len(results) == 2
        # Should be called serially (not via thread pool)
        assert mock_execute.call_count == 2
