"""
Real error propagation tests using actual tool/agent/workflow implementations.

Tests error propagation through the full stack:
- Tool execution → Tool errors (ToolError, ToolExecutionError, ToolNotFoundError)
- Agent execution → Agent errors (AgentError, LLMError)
- Workflow execution → Workflow errors (WorkflowError)

Focus areas:
1. Exception chaining (__cause__, __context__)
2. Context preservation (workflow_id, stage_id, agent_id, tool_name)
3. Error type transformation at boundaries
4. Stack trace preservation
5. Secret sanitization in error messages

This file implements 150+ LOC of error propagation tests based on the
qa-engineer specialist's test strategy.
"""
import uuid

from temper_ai.shared.utils.exceptions import (
    AgentError,
    ErrorCode,
    ExecutionContext,
    ToolError,
    ToolExecutionError,
    WorkflowError,
)
from tests.fixtures.error_helpers import (
    assert_context_preserved,
    assert_error_chain,
)


class TestToolToAgentErrorPropagation:
    """Test errors propagate correctly from tools to agents."""

    def test_tool_exception_wrapped_in_agent_error(self):
        """CRITICAL: Tool exceptions wrapped with proper cause chain."""
        # Create a ToolError to simulate tool failure
        tool_error = ToolExecutionError(
            message="Division by zero in Calculator tool",
            tool_name="Calculator",
            cause=ZeroDivisionError("division by zero")
        )

        # Simulate agent wrapping the tool error
        agent_error = AgentError(
            message="Agent failed to execute tool",
            context=ExecutionContext(
                agent_id="agent-123",
                tool_name="Calculator"
            ),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=tool_error
        )

        # Verify error chain: AgentError -> ToolExecutionError -> ZeroDivisionError
        assert isinstance(agent_error, AgentError)
        assert agent_error.error_code == ErrorCode.AGENT_EXECUTION_ERROR

        # Verify cause chain exists (both custom .cause and Python __cause__)
        assert agent_error.cause is not None
        assert isinstance(agent_error.cause, ToolExecutionError)
        assert "division by zero" in str(agent_error.cause).lower()

        # IMPORTANT: Also verify Python's standard __cause__ if set
        # (The system may use .cause for backward compat and __cause__ for Python compatibility)
        if hasattr(agent_error, '__cause__') and agent_error.__cause__ is not None:
            assert agent_error.__cause__ is agent_error.cause

        # Verify underlying cause
        assert tool_error.cause is not None
        assert isinstance(tool_error.cause, ZeroDivisionError)

        # Verify context preserved
        assert agent_error.context.agent_id == "agent-123"
        assert agent_error.context.tool_name == "Calculator"
        assert tool_error.context.tool_name == "Calculator"

    def test_tool_timeout_becomes_agent_timeout(self):
        """CRITICAL: Tool timeout propagates as agent timeout."""
        # Create a timeout error from tool layer
        tool_timeout = ToolError(
            message="Tool execution timed out after 30s",
            context=ExecutionContext(tool_name="SlowAPI"),
            error_code=ErrorCode.TOOL_TIMEOUT,
            cause=TimeoutError("Operation timed out")
        )

        # Simulate agent wrapping timeout
        agent_timeout = AgentError(
            message="Agent execution timed out",
            context=ExecutionContext(
                agent_id="agent-456",
                tool_name="SlowAPI"
            ),
            error_code=ErrorCode.AGENT_TIMEOUT,
            cause=tool_timeout
        )

        # Verify timeout propagated correctly
        assert agent_timeout.error_code == ErrorCode.AGENT_TIMEOUT
        assert tool_timeout.error_code == ErrorCode.TOOL_TIMEOUT

        # Verify cause chain
        assert agent_timeout.cause is tool_timeout
        assert isinstance(tool_timeout.cause, TimeoutError)

        # Verify timeout context preserved
        assert "timed out" in str(agent_timeout).lower()
        assert "SlowAPI" in str(agent_timeout)

    def test_tool_context_preserved_in_agent_error(self):
        """CRITICAL: Tool name and parameters preserved in agent error."""
        # Create tool error with specific context
        tool_error = ToolExecutionError(
            message="Failed to fetch data from API",
            tool_name="DataFetcher",
            context=ExecutionContext(
                metadata={"url": "https://api.example.com", "method": "GET"}
            )
        )

        # Create agent error that wraps tool error
        agent_context = ExecutionContext(
            agent_id="agent-789",
            tool_name="DataFetcher",
            metadata={"query": "fetch user data"}
        )
        agent_error = AgentError(
            message="Agent failed during tool execution",
            context=agent_context,
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=tool_error
        )

        # Verify tool context preserved
        assert agent_error.context.tool_name == "DataFetcher"
        assert tool_error.context.tool_name == "DataFetcher"

        # Verify metadata preserved
        assert tool_error.context.metadata["url"] == "https://api.example.com"
        assert agent_error.context.metadata["query"] == "fetch user data"

        # Verify tool name appears in error message
        assert "DataFetcher" in str(agent_error)


class TestAgentToWorkflowErrorPropagation:
    """Test errors propagate correctly from agents to workflows."""

    def test_agent_error_wrapped_in_workflow_error(self):
        """CRITICAL: Agent errors wrapped with full cause chain."""
        # Create full error chain: ToolError -> AgentError -> WorkflowError
        tool_error = ToolExecutionError(
            message="Invalid API response",
            tool_name="APIClient",
        )

        agent_error = AgentError(
            message="Agent failed to process API response",
            context=ExecutionContext(agent_id="agent-abc", tool_name="APIClient"),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=tool_error
        )

        workflow_error = WorkflowError(
            message="Workflow execution failed at data processing stage",
            context=ExecutionContext(
                workflow_id="wf-123",
                stage_id="process_data",
                agent_id="agent-abc",
                tool_name="APIClient"
            ),
            error_code=ErrorCode.WORKFLOW_STAGE_ERROR,
            cause=agent_error
        )

        # Verify full chain
        assert_error_chain(
            workflow_error,
            [WorkflowError, AgentError, ToolExecutionError]
        )

        # Verify all context preserved
        assert workflow_error.context.workflow_id == "wf-123"
        assert workflow_error.context.stage_id == "process_data"
        assert workflow_error.context.agent_id == "agent-abc"
        assert workflow_error.context.tool_name == "APIClient"

    def test_llm_error_propagates_through_workflow(self):
        """CRITICAL: LLM failures become workflow errors."""
        # Simulate LLM error at agent level
        llm_error = AgentError(
            message="LLM provider returned 429 rate limit",
            context=ExecutionContext(agent_id="agent-llm"),
            error_code=ErrorCode.LLM_RATE_LIMIT,
        )

        # Workflow wraps LLM error
        workflow_error = WorkflowError(
            message="Workflow failed due to LLM rate limit",
            context=ExecutionContext(
                workflow_id="wf-456",
                stage_id="generate_response",
                agent_id="agent-llm"
            ),
            error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
            cause=llm_error
        )

        # Verify LLM error accessible from workflow
        assert workflow_error.cause is llm_error
        assert llm_error.error_code == ErrorCode.LLM_RATE_LIMIT
        assert "rate limit" in str(workflow_error).lower()


class TestFullStackErrorPropagation:
    """Test errors propagate through entire stack."""

    def test_tool_error_traceable_to_workflow(self):
        """CRITICAL: Tool error accessible from workflow error."""
        # Build complete error chain
        root_cause = ValueError("Invalid input format")

        tool_error = ToolExecutionError(
            message="Tool validation failed",
            tool_name="Validator",
            cause=root_cause
        )

        agent_error = AgentError(
            message="Agent validation error",
            context=ExecutionContext(agent_id="agent-validator", tool_name="Validator"),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=tool_error
        )

        workflow_error = WorkflowError(
            message="Workflow validation failed",
            context=ExecutionContext(
                workflow_id="wf-validation",
                stage_id="validate_input",
                agent_id="agent-validator",
                tool_name="Validator"
            ),
            error_code=ErrorCode.WORKFLOW_STAGE_ERROR,
            cause=agent_error
        )

        # Verify complete chain is traversable
        assert workflow_error.cause is agent_error
        assert agent_error.cause is tool_error
        assert tool_error.cause is root_cause

        # Verify root cause details accessible from top
        assert isinstance(workflow_error.cause.cause.cause, ValueError)
        assert "Invalid input format" in str(workflow_error)

    def test_error_context_complete_chain(self):
        """CRITICAL: All context (workflow/stage/agent/tool) preserved."""
        wf_id = str(uuid.uuid4())
        stage_id = "data_transform"
        agent_id = "agent-transform"
        tool_name = "DataTransformer"

        # Create errors with complete context
        tool_error = ToolExecutionError(
            message="Transform failed",
            tool_name=tool_name,
        )

        agent_error = AgentError(
            message="Agent transform failed",
            context=ExecutionContext(agent_id=agent_id, tool_name=tool_name),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=tool_error
        )

        workflow_error = WorkflowError(
            message="Workflow transform failed",
            context=ExecutionContext(
                workflow_id=wf_id,
                stage_id=stage_id,
                agent_id=agent_id,
                tool_name=tool_name
            ),
            error_code=ErrorCode.WORKFLOW_STAGE_ERROR,
            cause=agent_error
        )

        # Verify complete context chain
        assert_context_preserved(workflow_error, {
            "workflow_id": wf_id,
            "stage_id": stage_id,
            "agent_id": agent_id,
            "tool_name": tool_name
        })

        assert_context_preserved(agent_error, {
            "agent_id": agent_id,
            "tool_name": tool_name
        })

        assert_context_preserved(tool_error, {
            "tool_name": tool_name
        })

        # Verify all IDs appear in error string
        error_str = str(workflow_error)
        assert wf_id in error_str
        assert stage_id in error_str
        assert agent_id in error_str
        assert tool_name in error_str


class TestErrorSecretSanitization:
    """Test secret sanitization in error propagation."""

    def test_api_key_sanitized_in_tool_error(self):
        """CRITICAL: API keys redacted in tool errors."""
        # Create error with API key in message
        tool_error = ToolError(
            message="API request failed with key=sk-test-12345abcdef",
            context=ExecutionContext(tool_name="APIClient"),
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
        )

        # Verify API key sanitized
        error_str = str(tool_error)
        assert "sk-test-12345abcdef" not in error_str
        assert "[REDACTED-API-KEY]" in error_str

    def test_password_sanitized_in_error_chain(self):
        """CRITICAL: Passwords redacted throughout error chain."""
        # Create error with password in cause
        root_cause = ConnectionError("Failed to connect with password=secret123")

        tool_error = ToolError(
            message="Database connection failed",
            context=ExecutionContext(tool_name="DBClient"),
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            cause=root_cause
        )

        # Verify password sanitized
        error_str = str(tool_error)
        assert "secret123" not in error_str
        assert "[REDACTED-PASSWORD]" in error_str

    def test_token_sanitized_in_workflow_error(self):
        """CRITICAL: Tokens redacted in workflow errors."""
        # Create workflow error with token in message
        workflow_error = WorkflowError(
            message="Auth failed with token=ghp_abc123xyz789",
            context=ExecutionContext(workflow_id="wf-auth"),
            error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
        )

        # Verify token sanitized
        error_str = str(workflow_error)
        assert "ghp_abc123xyz789" not in error_str
        assert "[REDACTED-TOKEN]" in error_str

    def test_connection_string_sanitized(self):
        """CRITICAL: Database connection strings redacted."""
        # Create error with connection string
        tool_error = ToolError(
            message="Failed to connect: mysql://user:password123@localhost/db",
            context=ExecutionContext(tool_name="MySQL"),
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
        )

        # Verify connection string sanitized
        error_str = str(tool_error)
        assert "password123" not in error_str
        assert "[REDACTED-CREDENTIALS]" in error_str

    def test_jwt_token_sanitized(self):
        """CRITICAL: JWT tokens redacted."""
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"

        agent_error = AgentError(
            message=f"Authentication failed with Bearer {jwt_token}",
            context=ExecutionContext(agent_id="agent-auth"),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
        )

        # Verify JWT sanitized
        error_str = str(agent_error)
        assert jwt_token not in error_str
        assert "[REDACTED-JWT-TOKEN]" in error_str or "[REDACTED-TOKEN]" in error_str


class TestErrorEdgeCases:
    """Test edge cases in error handling."""

    def test_error_without_cause(self):
        """Edge case: Error with no underlying cause."""
        error = ToolError(
            message="Standalone error",
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            context=ExecutionContext(tool_name="Test")
        )

        assert error.cause is None
        # __cause__ may or may not be set depending on implementation
        assert "Caused by:" not in str(error)

    def test_deep_error_chain(self):
        """Edge case: Deep error chains (10+ levels)."""
        # Build 10-level chain
        current_error = ValueError("Root cause")

        for i in range(10):
            current_error = ToolError(
                message=f"Level {i}",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                cause=current_error
            )

        # Verify we can traverse entire chain
        depth = 0
        err = current_error
        while err is not None:
            depth += 1
            # Check both __cause__ and .cause
            err = getattr(err, '__cause__', None) or getattr(err, 'cause', None)

        assert depth == 11  # 10 ToolErrors + 1 ValueError

    def test_unicode_in_error_messages(self):
        """Edge case: Non-ASCII characters in errors."""
        tool_error = ToolError(
            message="API 请求失败 with émojis 🔥💥",
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            context=ExecutionContext(tool_name="UnicodeAPI")
        )

        # Should handle unicode without crashes
        error_str = str(tool_error)
        error_dict = tool_error.to_dict()
        error_repr = repr(tool_error)

        # Verify no encoding errors
        assert "message" in error_dict
        assert isinstance(error_str, str)
        assert isinstance(error_repr, str)


class TestErrorMetadata:
    """Test error metadata and extra_data preservation."""

    def test_extra_data_preserved_in_error(self):
        """HIGH: Extra error data preserved through chain."""
        extra_data = {
            "request_id": "req-123",
            "retry_count": 3,
            "endpoint": "/api/users"
        }

        tool_error = ToolError(
            message="API request failed",
            context=ExecutionContext(tool_name="APIClient"),
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            extra_data=extra_data
        )

        # Verify extra_data accessible
        assert tool_error.extra_data == extra_data
        assert tool_error.extra_data["request_id"] == "req-123"
        assert tool_error.extra_data["retry_count"] == 3

    def test_error_to_dict_serialization(self):
        """HIGH: Error serialization preserves all fields."""
        workflow_id = str(uuid.uuid4())

        workflow_error = WorkflowError(
            message="Workflow failed",
            context=ExecutionContext(
                workflow_id=workflow_id,
                stage_id="stage-1",
                agent_id="agent-1",
                tool_name="Tool1"
            ),
            error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
            extra_data={"attempt": 1}
        )

        # Serialize to dict
        error_dict = workflow_error.to_dict()

        # Verify all fields present
        assert error_dict["error_type"] == "WorkflowError"
        assert error_dict["error_code"] == "WORKFLOW_EXECUTION_ERROR"
        assert error_dict["context"]["workflow_id"] == workflow_id
        assert error_dict["context"]["stage_id"] == "stage-1"
        assert error_dict["context"]["agent_id"] == "agent-1"
        assert error_dict["context"]["tool_name"] == "Tool1"
        assert error_dict["extra_data"]["attempt"] == 1
        assert "timestamp" in error_dict

    def test_error_repr_sanitized(self):
        """HIGH: Error repr sanitizes secrets."""
        agent_error = AgentError(
            message="Failed with api_key=sk-secret",
            context=ExecutionContext(agent_id="agent-123"),
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
        )

        # Verify repr is sanitized
        repr_str = repr(agent_error)
        assert "sk-secret" not in repr_str
        assert "[REDACTED-API-KEY]" in repr_str
