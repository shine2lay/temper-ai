"""Tests for temper_ai/llm/_tool_execution.py.

Tests cover:
- validate_tool_calls_input: type validation for list-of-dicts input
- check_safety_mode: safety mode enforcement (require_approval, dry_run, per-tool)
- build_tool_result: standardized result dictionary construction
- execute_single_tool: single tool execution with safety and observer integration
- execute_tools: serial/parallel execution dispatch
- execute_via_executor: routing through ToolExecutor with exception handling
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from temper_ai.llm._tool_execution import (
    build_tool_result,
    check_safety_mode,
    execute_single_tool,
    execute_tools,
    execute_via_executor,
    validate_tool_calls_input,
)
from temper_ai.llm.tool_keys import ToolKeys
from temper_ai.shared.utils.exceptions import ToolExecutionError, ToolNotFoundError


def _make_executor_result(
    success: bool, result: object = None, error: str | None = None
) -> MagicMock:
    """Create a mock tool executor result object."""
    mock_result = MagicMock()
    mock_result.success = success
    mock_result.result = result
    mock_result.error = error
    return mock_result


class TestValidateToolCallsInput:
    """Tests for validate_tool_calls_input."""

    def test_valid_list_of_dicts(self) -> None:
        """Valid list of dicts does not raise."""
        tool_calls = [
            {"name": "tool1", "parameters": {}},
            {"name": "tool2", "parameters": {"x": 1}},
        ]
        validate_tool_calls_input(tool_calls)  # Should not raise

    def test_empty_list_ok(self) -> None:
        """Empty list is valid and does not raise."""
        validate_tool_calls_input([])

    def test_non_list_raises_type_error(self) -> None:
        """Non-list input raises TypeError with descriptive message."""
        with pytest.raises(TypeError, match="tool_calls must be a list"):
            validate_tool_calls_input({"name": "tool1"})  # type: ignore[arg-type]

    def test_tuple_raises_type_error(self) -> None:
        """Tuple input raises TypeError even though it's sequence-like."""
        with pytest.raises(TypeError, match="tool_calls must be a list"):
            validate_tool_calls_input(("tool1", "tool2"))  # type: ignore[arg-type]

    def test_none_raises_type_error(self) -> None:
        """None input raises TypeError."""
        with pytest.raises(TypeError, match="tool_calls must be a list"):
            validate_tool_calls_input(None)  # type: ignore[arg-type]

    def test_non_dict_item_raises_type_error(self) -> None:
        """List with non-dict item raises TypeError mentioning index."""
        with pytest.raises(
            TypeError, match="tool_call at index 0 must be a dictionary"
        ):
            validate_tool_calls_input(["not_a_dict"])  # type: ignore[list-item]

    def test_mixed_items_raises_type_error_at_bad_index(self) -> None:
        """List with mixed valid/invalid items reports the bad index."""
        with pytest.raises(
            TypeError, match="tool_call at index 1 must be a dictionary"
        ):
            validate_tool_calls_input([{"name": "tool1"}, "invalid"])  # type: ignore[list-item]


class TestCheckSafetyMode:
    """Tests for check_safety_mode."""

    def test_none_safety_config_returns_none(self) -> None:
        """None safety_config passes through without blocking."""
        result = check_safety_mode(None, "some_tool", {})
        assert result is None

    def test_require_approval_mode_blocks_all_tools(self) -> None:
        """require_approval mode blocks any tool and returns error dict."""
        safety_config = MagicMock()
        safety_config.mode = "require_approval"
        safety_config.require_approval_for_tools = []

        result = check_safety_mode(safety_config, "dangerous_tool", {"param": "value"})

        assert result is not None
        assert result[ToolKeys.SUCCESS] is False
        assert "require_approval" in result[ToolKeys.ERROR]
        assert result[ToolKeys.NAME] == "dangerous_tool"
        assert result[ToolKeys.PARAMETERS] == {"param": "value"}

    def test_dry_run_mode_returns_simulated_result(self) -> None:
        """dry_run mode returns simulated result with [DRY RUN] marker."""
        safety_config = MagicMock()
        safety_config.mode = "dry_run"
        safety_config.require_approval_for_tools = []

        result = check_safety_mode(safety_config, "my_tool", {"x": 1})

        assert result is not None
        assert result[ToolKeys.SUCCESS] is True
        assert "[DRY RUN]" in result[ToolKeys.RESULT]
        assert result[ToolKeys.ERROR] is None
        assert result[ToolKeys.NAME] == "my_tool"

    def test_per_tool_approval_list_blocks_specific_tool(self) -> None:
        """Per-tool approval list blocks the named tool in normal execute mode."""
        safety_config = MagicMock()
        safety_config.mode = "execute"
        safety_config.require_approval_for_tools = ["restricted_tool"]

        result = check_safety_mode(safety_config, "restricted_tool", {})

        assert result is not None
        assert result["success"] is False
        assert "requires approval" in result["error"]

    def test_per_tool_approval_allows_unlisted_tools(self) -> None:
        """Per-tool approval list allows tools not on the list."""
        safety_config = MagicMock()
        safety_config.mode = "execute"
        safety_config.require_approval_for_tools = ["restricted_tool"]

        result = check_safety_mode(safety_config, "allowed_tool", {})

        assert result is None

    def test_normal_execute_mode_returns_none(self) -> None:
        """Normal execute mode returns None (permits execution)."""
        safety_config = MagicMock()
        safety_config.mode = "execute"
        safety_config.require_approval_for_tools = []

        result = check_safety_mode(safety_config, "any_tool", {})

        assert result is None

    def test_no_mode_attribute_defaults_to_execute(self) -> None:
        """Safety config without mode attribute defaults to execute (returns None)."""

        class MinimalConfig:
            pass

        safety_config = MinimalConfig()  # No mode or require_approval_for_tools attrs
        result = check_safety_mode(safety_config, "tool", {})
        assert result is None

    def test_require_approval_mode_takes_priority_over_dry_run(self) -> None:
        """require_approval check runs before dry_run check since ordering matters."""
        safety_config = MagicMock()
        safety_config.mode = "require_approval"
        safety_config.require_approval_for_tools = []

        result = check_safety_mode(safety_config, "tool", {})

        assert result is not None
        assert result[ToolKeys.SUCCESS] is False


class TestBuildToolResult:
    """Tests for build_tool_result."""

    def test_success_result(self) -> None:
        """Success result contains result data and clears error."""
        result = build_tool_result("my_tool", {"x": 1}, True, "output_data")

        assert result[ToolKeys.NAME] == "my_tool"
        assert result[ToolKeys.PARAMETERS] == {"x": 1}
        assert result[ToolKeys.SUCCESS] is True
        assert result[ToolKeys.RESULT] == "output_data"
        assert result[ToolKeys.ERROR] is None

    def test_error_result(self) -> None:
        """Error result contains error message and clears result data."""
        result = build_tool_result("my_tool", {}, False, None, "Something went wrong")

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.RESULT] is None
        assert result[ToolKeys.ERROR] == "Something went wrong"

    def test_defaults_for_result_and_error(self) -> None:
        """Default values for optional result and error parameters are None."""
        result = build_tool_result("tool", {}, True)

        assert result[ToolKeys.RESULT] is None
        assert result[ToolKeys.ERROR] is None
        assert result[ToolKeys.SUCCESS] is True

    def test_failed_result_clears_result_data(self) -> None:
        """Failed result sets result to None even if data is provided."""
        result = build_tool_result("tool", {}, False, "some_data", "error_msg")

        assert result[ToolKeys.RESULT] is None
        assert result[ToolKeys.ERROR] == "error_msg"

    def test_all_required_keys_present(self) -> None:
        """Result dict always contains all five required keys."""
        result = build_tool_result("tool", {}, True, "data")

        for key in (
            ToolKeys.NAME,
            ToolKeys.PARAMETERS,
            ToolKeys.SUCCESS,
            ToolKeys.RESULT,
            ToolKeys.ERROR,
        ):
            assert key in result


class TestExecuteSingleTool:
    """Tests for execute_single_tool."""

    def test_success_with_observer_tracking(self) -> None:
        """Successful execution tracks via observer with correct status."""
        tool_executor = MagicMock()
        observer = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(True, "output")

        tool_call = {ToolKeys.NAME: "my_tool", ToolKeys.PARAMETERS: {"x": 1}}
        result = execute_single_tool(tool_call, tool_executor, observer, None)

        assert result[ToolKeys.SUCCESS] is True
        assert result[ToolKeys.RESULT] == "output"
        observer.track_tool_call.assert_called_once()
        call_kwargs = observer.track_tool_call.call_args[1]
        assert call_kwargs["tool_name"] == "my_tool"
        assert call_kwargs["status"] == "success"

    def test_failure_with_error_result(self) -> None:
        """Failed executor result returns error dict and observer tracks failure."""
        tool_executor = MagicMock()
        observer = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(
            False, error="execution failed"
        )

        tool_call = {ToolKeys.NAME: "my_tool", ToolKeys.PARAMETERS: {}}
        result = execute_single_tool(tool_call, tool_executor, observer, None)

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.ERROR] == "execution failed"
        observer.track_tool_call.assert_called_once()
        call_kwargs = observer.track_tool_call.call_args[1]
        assert call_kwargs["status"] == "failed"

    def test_no_executor_returns_error_with_security_message(self) -> None:
        """Missing tool_executor returns error result — no silent fallback."""
        tool_call = {ToolKeys.NAME: "my_tool", ToolKeys.PARAMETERS: {}}
        result = execute_single_tool(tool_call, None, None, None)

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.ERROR] is not None
        assert "my_tool" in result[ToolKeys.ERROR]

    def test_safety_blocks_execution_in_require_approval_mode(self) -> None:
        """Safety config in require_approval mode blocks before execution."""
        safety_config = MagicMock()
        safety_config.mode = "require_approval"
        safety_config.require_approval_for_tools = []

        tool_call = {ToolKeys.NAME: "blocked_tool", ToolKeys.PARAMETERS: {}}
        result = execute_single_tool(tool_call, MagicMock(), None, safety_config)

        assert result[ToolKeys.SUCCESS] is False
        assert "require_approval" in result[ToolKeys.ERROR]

    def test_non_dict_tool_call_raises_type_error(self) -> None:
        """Non-dict tool_call raises TypeError before execution."""
        with pytest.raises(TypeError, match="tool_call must be a dictionary"):
            execute_single_tool("not_a_dict", None, None, None)  # type: ignore[arg-type]

    def test_missing_name_field_raises_value_error(self) -> None:
        """tool_call without 'name' field raises ValueError."""
        with pytest.raises(ValueError, match="name"):
            execute_single_tool({"parameters": {}}, None, None, None)

    def test_no_observer_does_not_raise(self) -> None:
        """Execution with observer=None completes without error."""
        tool_executor = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(True, "ok")

        tool_call = {ToolKeys.NAME: "tool", ToolKeys.PARAMETERS: {}}
        result = execute_single_tool(tool_call, tool_executor, None, None)

        assert result[ToolKeys.SUCCESS] is True


class TestExecuteTools:
    """Tests for execute_tools."""

    def test_empty_list_returns_empty(self) -> None:
        """Empty tool_calls list returns empty list without calling execute_single."""
        execute_single = MagicMock()
        result = execute_tools([], None, None, None, execute_single)

        assert result == []
        execute_single.assert_not_called()

    def test_serial_execution_for_single_tool_call(self) -> None:
        """Single tool call uses serial execution path."""
        expected = {
            ToolKeys.NAME: "tool1",
            ToolKeys.SUCCESS: True,
            ToolKeys.RESULT: "out",
            ToolKeys.PARAMETERS: {},
            ToolKeys.ERROR: None,
        }
        execute_single = MagicMock(return_value=expected)
        tool_calls = [{ToolKeys.NAME: "tool1", ToolKeys.PARAMETERS: {}}]

        results = execute_tools(tool_calls, None, None, None, execute_single)

        assert len(results) == 1
        assert results[0] == expected
        execute_single.assert_called_once()

    def test_parallel_execution_for_multiple_tool_calls(self) -> None:
        """Multiple tool calls execute in parallel via thread pool."""

        def fake_execute(tc, tool_executor, observer, safety_config):  # type: ignore[no-untyped-def]
            return {
                ToolKeys.NAME: tc[ToolKeys.NAME],
                ToolKeys.SUCCESS: True,
                ToolKeys.RESULT: "ok",
                ToolKeys.PARAMETERS: {},
                ToolKeys.ERROR: None,
            }

        tool_calls = [
            {ToolKeys.NAME: "tool1", ToolKeys.PARAMETERS: {}},
            {ToolKeys.NAME: "tool2", ToolKeys.PARAMETERS: {}},
        ]
        results = execute_tools(tool_calls, None, None, None, fake_execute)

        assert len(results) == 2
        names = {r[ToolKeys.NAME] for r in results}
        assert names == {"tool1", "tool2"}

    def test_non_list_raises_type_error(self) -> None:
        """Non-list tool_calls raises TypeError via validate_tool_calls_input."""
        with pytest.raises(TypeError, match="tool_calls must be a list"):
            execute_tools("not_a_list", None, None, None, MagicMock())  # type: ignore[arg-type]

    def test_parallel_preserves_all_results(self) -> None:
        """All results are returned when running multiple tools in parallel."""

        def fake_execute(tc, tool_executor, observer, safety_config):  # type: ignore[no-untyped-def]
            return {
                ToolKeys.NAME: tc[ToolKeys.NAME],
                ToolKeys.SUCCESS: True,
                ToolKeys.RESULT: f"result_{tc[ToolKeys.NAME]}",
                ToolKeys.PARAMETERS: {},
                ToolKeys.ERROR: None,
            }

        tool_calls = [
            {ToolKeys.NAME: f"tool{i}", ToolKeys.PARAMETERS: {}} for i in range(3)
        ]
        results = execute_tools(tool_calls, None, None, None, fake_execute)

        assert len(results) == 3


class TestExecuteViaExecutor:
    """Tests for execute_via_executor."""

    def test_routes_through_tool_executor(self) -> None:
        """Successful execution routes through tool_executor.execute."""
        tool_executor = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(True, "output_value")

        result = execute_via_executor("my_tool", {"param": "val"}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is True
        assert result[ToolKeys.RESULT] == "output_value"
        tool_executor.execute.assert_called_once_with("my_tool", {"param": "val"})

    def test_tool_not_found_error_caught_and_returned(self) -> None:
        """ToolNotFoundError is caught and returned as error result dict."""
        tool_executor = MagicMock()
        tool_executor.execute.side_effect = ToolNotFoundError(
            "tool not found", tool_name="missing_tool"
        )

        result = execute_via_executor("missing_tool", {}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.ERROR] is not None
        assert "tool not found" in result[ToolKeys.ERROR]

    def test_tool_execution_error_caught(self) -> None:
        """ToolExecutionError is caught and returned as error result dict."""
        tool_executor = MagicMock()
        tool_executor.execute.side_effect = ToolExecutionError(
            "execution failed", tool_name="my_tool"
        )

        result = execute_via_executor("my_tool", {}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.ERROR] is not None

    def test_timeout_error_caught(self) -> None:
        """TimeoutError is caught and returned as error result dict."""
        tool_executor = MagicMock()
        tool_executor.execute.side_effect = TimeoutError("timed out")

        result = execute_via_executor("slow_tool", {}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is False
        assert result[ToolKeys.ERROR] is not None

    def test_observer_called_on_success(self) -> None:
        """Observer.track_tool_call is called when execution succeeds."""
        tool_executor = MagicMock()
        observer = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(True, "result")

        execute_via_executor("my_tool", {"x": 1}, tool_executor, observer)

        observer.track_tool_call.assert_called_once()
        call_kwargs = observer.track_tool_call.call_args[1]
        assert call_kwargs["status"] == "success"

    def test_observer_called_on_exception(self) -> None:
        """Observer.track_tool_call is called with failed status when exception raised."""
        tool_executor = MagicMock()
        observer = MagicMock()
        tool_executor.execute.side_effect = ToolExecutionError(
            "boom", tool_name="my_tool"
        )

        execute_via_executor("my_tool", {}, tool_executor, observer)

        observer.track_tool_call.assert_called_once()
        call_kwargs = observer.track_tool_call.call_args[1]
        assert call_kwargs["status"] == "failed"

    def test_none_observer_does_not_raise(self) -> None:
        """observer=None does not cause errors during execution."""
        tool_executor = MagicMock()
        tool_executor.execute.return_value = _make_executor_result(True, "ok")

        result = execute_via_executor("my_tool", {}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is True

    def test_runtime_error_caught(self) -> None:
        """RuntimeError is caught and returned as error result dict."""
        tool_executor = MagicMock()
        tool_executor.execute.side_effect = RuntimeError("unexpected runtime error")

        result = execute_via_executor("my_tool", {}, tool_executor, None)

        assert result[ToolKeys.SUCCESS] is False
        assert "unexpected runtime error" in result[ToolKeys.ERROR]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
