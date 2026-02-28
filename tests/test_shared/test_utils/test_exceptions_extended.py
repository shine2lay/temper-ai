"""Extended tests for temper_ai/shared/utils/exceptions.py.

Targets uncovered lines:
- Line 216: context.agent_id in _build_message
- Line 446: ToolError with tool_name and existing context
- Lines 536-542: MaxIterationsError attributes
- Lines 594-595: WorkflowStageError.stage_name attribute
"""

from temper_ai.shared.utils.exceptions import (
    AgentError,
    BaseError,
    ErrorCode,
    MaxIterationsError,
    SecurityError,
    ToolError,
    WorkflowError,
    WorkflowStageError,
)


class TestBaseErrorBuildMessage:
    """Tests for BaseError._build_message covering context fields."""

    def test_agent_id_in_message(self):
        """agent_id in context appears in the built message (line 215-216)."""
        from temper_ai.shared.core.context import ExecutionContext

        ctx = ExecutionContext(agent_id="agent-42")
        error = BaseError("test error", context=ctx)
        assert "agent-42" in str(error) or "agent_id" in str(error)

    def test_all_context_fields_in_message(self):
        """All context fields appear in message when set."""
        from temper_ai.shared.core.context import ExecutionContext

        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="stage-2",
            agent_id="agent-3",
            tool_name="my_tool",
        )
        error = BaseError("context test", context=ctx)
        msg = str(error)
        assert "wf-1" in msg
        assert "stage-2" in msg
        assert "agent-3" in msg
        assert "my_tool" in msg

    def test_message_with_no_context_fields(self):
        """Empty context doesn't add context section to message."""
        error = BaseError("plain error")
        msg = str(error)
        assert "plain error" in msg

    def test_message_with_cause(self):
        """Cause is included in the message."""
        cause = ValueError("root cause")
        error = BaseError("wrapped", cause=cause)
        msg = str(error)
        assert "Caused by" in msg or "ValueError" in msg


class TestToolErrorWithContext:
    """Tests for ToolError covering tool_name + context branch (line 446)."""

    def test_tool_error_with_tool_name_and_context(self):
        """ToolError with both tool_name and context uses the context (line 445-446)."""
        from temper_ai.shared.core.context import ExecutionContext

        ctx = ExecutionContext(workflow_id="wf-99")
        error = ToolError(
            "tool failed",
            tool_name="my_tool",
            context=ctx,
        )
        assert error.context.tool_name == "my_tool"
        assert error.context.workflow_id == "wf-99"

    def test_tool_error_with_tool_name_no_context(self):
        """ToolError with tool_name but no context creates a new ExecutionContext (lines 447-450)."""
        error = ToolError("tool error", tool_name="my_tool")
        assert error.context.tool_name == "my_tool"

    def test_tool_error_without_tool_name(self):
        """ToolError without tool_name doesn't set tool_name on context."""
        error = ToolError("tool error")
        # context.tool_name may be None or unset
        assert error.context is not None


class TestMaxIterationsError:
    """Tests for MaxIterationsError (lines 536-546)."""

    def test_basic_creation(self):
        """MaxIterationsError stores iterations count (line 536)."""
        error = MaxIterationsError(iterations=10)
        assert error.iterations == 10

    def test_default_attributes(self):
        """MaxIterationsError has sensible defaults (lines 537-541)."""
        error = MaxIterationsError(iterations=5)
        assert error.tool_calls == []
        assert error.tokens == 0
        assert error.cost == 0.0
        assert error.last_output == ""
        assert error.last_reasoning is None

    def test_custom_attributes(self):
        """MaxIterationsError stores all provided attributes (lines 536-542)."""
        tool_calls = [{"name": "search"}, {"name": "read"}]
        error = MaxIterationsError(
            iterations=7,
            tool_calls=tool_calls,
            tokens=1500,
            cost=0.05,
            last_output="partial result",
            last_reasoning="stopped because limit",
        )
        assert error.iterations == 7
        assert error.tool_calls == tool_calls
        assert error.tokens == 1500
        assert error.cost == 0.05
        assert error.last_output == "partial result"
        assert error.last_reasoning == "stopped because limit"

    def test_message_contains_iteration_count(self):
        """Message includes the iteration count."""
        error = MaxIterationsError(iterations=42)
        assert "42" in str(error)

    def test_is_agent_error(self):
        """MaxIterationsError is a subtype of AgentError."""
        error = MaxIterationsError(iterations=3)
        assert isinstance(error, AgentError)

    def test_error_code_is_max_iterations(self):
        """MaxIterationsError uses AGENT_MAX_ITERATIONS error code."""
        error = MaxIterationsError(iterations=5)
        assert error.error_code == ErrorCode.AGENT_MAX_ITERATIONS


class TestWorkflowStageError:
    """Tests for WorkflowStageError (lines 594-601)."""

    def test_stage_name_stored(self):
        """stage_name attribute is stored (line 594)."""
        error = WorkflowStageError(
            message="stage failed",
            stage_name="preprocessing",
        )
        assert error.stage_name == "preprocessing"

    def test_is_workflow_error(self):
        """WorkflowStageError is a subtype of WorkflowError."""
        error = WorkflowStageError("fail", stage_name="step1")
        assert isinstance(error, WorkflowError)

    def test_stage_name_in_subclass(self):
        """stage_name is accessible after construction."""
        error = WorkflowStageError(
            "message", stage_name="my-stage", cause=ValueError("x")
        )
        assert error.stage_name == "my-stage"


class TestSecurityError:
    """Tests for SecurityError (line 607-619)."""

    def test_security_error_is_framework_exception(self):
        """SecurityError inherits from FrameworkException."""
        from temper_ai.shared.utils.exceptions import FrameworkException

        error = SecurityError("access denied")
        assert isinstance(error, FrameworkException)

    def test_security_error_message(self):
        """SecurityError stores and returns message."""
        error = SecurityError("unauthorized access attempt")
        assert "unauthorized" in str(error)
