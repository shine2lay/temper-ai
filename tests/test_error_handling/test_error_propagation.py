"""
Error propagation tests for agent → stage → workflow chain.

Tests error propagation, context preservation, partial failures, cascading control,
and metadata sanitization to prevent secret leakage.
"""
from typing import Any, Dict, List, Optional

import pytest


class AgentError(Exception):
    """Base agent error."""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}


class ToolNotFoundError(AgentError):
    """Tool not found error."""
    pass


class StageExecutionError(Exception):
    """Stage execution error."""
    def __init__(self, message: str, agent_errors: Optional[List[Exception]] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.agent_errors = agent_errors or []
        self.context = context or {}


class WorkflowExecutionError(Exception):
    """Workflow execution error."""
    def __init__(self, message: str, stage_errors: Optional[List[Exception]] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.stage_errors = stage_errors or []
        self.context = context or {}


class MockAgent:
    """Mock agent for testing error propagation."""

    def __init__(self, name: str, should_fail: bool = False, error_type: type = AgentError):
        self.name = name
        self.should_fail = should_fail
        self.error_type = error_type

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent."""
        if self.should_fail:
            raise self.error_type(
                f"Agent {self.name} failed",
                context={"agent": self.name, "operation": "execute"}
            )

        return {"agent": self.name, "result": f"Success from {self.name}"}


class MockStage:
    """Mock stage for testing error propagation."""

    def __init__(self, name: str, agents: List[MockAgent], fail_on_error: bool = True):
        self.name = name
        self.agents = agents
        self.fail_on_error = fail_on_error

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute stage with agents."""
        results = []
        errors = []

        for agent in self.agents:
            try:
                result = await agent.execute(context)
                results.append(result)
            except Exception as e:
                errors.append(e)
                if self.fail_on_error:
                    raise StageExecutionError(
                        f"Stage {self.name} failed due to agent error",
                        agent_errors=[e],
                        context={"stage": self.name, "failed_agents": 1}
                    )

        if errors and not self.fail_on_error:
            # Partial failure mode - return both successes and failures
            return {
                "stage": self.name,
                "results": results,
                "errors": errors,
                "partial_failure": True
            }

        return {"stage": self.name, "results": results}


class MockWorkflow:
    """Mock workflow for testing error propagation."""

    def __init__(self, name: str, stages: List[MockStage]):
        self.name = name
        self.stages = stages

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow with stages."""
        stage_results = []
        stage_errors = []

        for stage in self.stages:
            try:
                result = await stage.execute(context)
                stage_results.append(result)
            except Exception as e:
                stage_errors.append(e)
                raise WorkflowExecutionError(
                    f"Workflow {self.name} failed at stage {stage.name}",
                    stage_errors=[e],
                    context={"workflow": self.name, "failed_stage": stage.name}
                )

        return {"workflow": self.name, "stages": stage_results}


class TestErrorPropagationChain:
    """Test error propagation through agent → stage → workflow."""

    @pytest.mark.asyncio
    async def test_agent_to_stage_error_propagation(self):
        """Test agent error propagates to stage with context."""
        # Create failing agent
        agent = MockAgent("failing_agent", should_fail=True, error_type=ToolNotFoundError)
        stage = MockStage("test_stage", [agent])

        # Execute stage (should fail)
        with pytest.raises(StageExecutionError) as exc_info:
            await stage.execute({})

        error = exc_info.value

        # Verify stage error contains agent error
        assert len(error.agent_errors) == 1
        assert isinstance(error.agent_errors[0], ToolNotFoundError)
        assert "failing_agent" in str(error.agent_errors[0])

        # Verify context preserved
        assert error.context["stage"] == "test_stage"
        assert error.context["failed_agents"] == 1

    @pytest.mark.asyncio
    async def test_stage_to_workflow_error_propagation(self):
        """Test stage error propagates to workflow with full chain."""
        # Create failing agent → stage → workflow
        agent = MockAgent("failing_agent", should_fail=True)
        stage = MockStage("failing_stage", [agent])
        workflow = MockWorkflow("test_workflow", [stage])

        # Execute workflow (should fail)
        with pytest.raises(WorkflowExecutionError) as exc_info:
            await workflow.execute({})

        error = exc_info.value

        # Verify workflow error contains stage error
        assert len(error.stage_errors) == 1
        assert isinstance(error.stage_errors[0], StageExecutionError)

        # Verify context chain
        assert error.context["workflow"] == "test_workflow"
        assert error.context["failed_stage"] == "failing_stage"

        # Verify agent error in chain
        stage_error = error.stage_errors[0]
        assert len(stage_error.agent_errors) == 1
        assert isinstance(stage_error.agent_errors[0], AgentError)

    @pytest.mark.asyncio
    async def test_full_error_chain_integrity(self):
        """Test complete error chain from agent through workflow."""
        # Create error chain: agent error → stage error → workflow error
        agent = MockAgent("agent1", should_fail=True, error_type=ToolNotFoundError)
        stage = MockStage("stage1", [agent])
        workflow = MockWorkflow("workflow1", [stage])

        with pytest.raises(WorkflowExecutionError) as exc_info:
            await workflow.execute({})

        # Verify complete chain
        workflow_error = exc_info.value
        assert isinstance(workflow_error, WorkflowExecutionError)
        assert workflow_error.context["workflow"] == "workflow1"

        stage_error = workflow_error.stage_errors[0]
        assert isinstance(stage_error, StageExecutionError)
        assert stage_error.context["stage"] == "stage1"

        agent_error = stage_error.agent_errors[0]
        assert isinstance(agent_error, ToolNotFoundError)
        assert "agent1" in str(agent_error)

    @pytest.mark.asyncio
    async def test_successful_stages_continue_after_error(self):
        """Test that previous successful stages don't affect error propagation."""
        # Create workflow: success stage → failing stage
        success_agent = MockAgent("success_agent", should_fail=False)
        fail_agent = MockAgent("fail_agent", should_fail=True)

        success_stage = MockStage("success_stage", [success_agent])
        fail_stage = MockStage("fail_stage", [fail_agent])

        workflow = MockWorkflow("test_workflow", [success_stage, fail_stage])

        with pytest.raises(WorkflowExecutionError) as exc_info:
            await workflow.execute({})

        error = exc_info.value

        # Workflow should fail at second stage
        assert error.context["failed_stage"] == "fail_stage"

        # But first stage completed successfully (no error from it)
        assert len(error.stage_errors) == 1


class TestPartialFailureHandling:
    """Test handling of partial failures (some agents succeed, some fail)."""

    @pytest.mark.asyncio
    async def test_partial_agent_failures_captured(self):
        """Test workflow captures both successes and failures in parallel stage."""
        # Create stage with 5 agents: 3 succeed, 2 fail
        agents = [
            MockAgent("agent1", should_fail=False),
            MockAgent("agent2", should_fail=True),
            MockAgent("agent3", should_fail=False),
            MockAgent("agent4", should_fail=True),
            MockAgent("agent5", should_fail=False),
        ]

        # Stage configured to NOT fail on agent error
        stage = MockStage("parallel_stage", agents, fail_on_error=False)

        result = await stage.execute({})

        # Verify partial failure captured
        assert result["partial_failure"] is True
        assert len(result["results"]) == 3  # 3 successes
        assert len(result["errors"]) == 2  # 2 failures

        # Verify successful results
        success_names = [r["agent"] for r in result["results"]]
        assert "agent1" in success_names
        assert "agent3" in success_names
        assert "agent5" in success_names

        # Verify failed agents captured
        assert len(result["errors"]) == 2
        assert all(isinstance(e, AgentError) for e in result["errors"])

    @pytest.mark.asyncio
    async def test_all_failures_in_parallel_stage(self):
        """Test stage handles all agents failing."""
        agents = [
            MockAgent("agent1", should_fail=True),
            MockAgent("agent2", should_fail=True),
            MockAgent("agent3", should_fail=True),
        ]

        stage = MockStage("all_fail_stage", agents, fail_on_error=False)
        result = await stage.execute({})

        # All failed
        assert result["partial_failure"] is True
        assert len(result["results"]) == 0
        assert len(result["errors"]) == 3

    @pytest.mark.asyncio
    async def test_all_successes_in_parallel_stage(self):
        """Test stage handles all agents succeeding."""
        agents = [
            MockAgent("agent1", should_fail=False),
            MockAgent("agent2", should_fail=False),
            MockAgent("agent3", should_fail=False),
        ]

        stage = MockStage("all_success_stage", agents, fail_on_error=False)
        result = await stage.execute({})

        # All succeeded
        assert "partial_failure" not in result or not result["partial_failure"]
        assert len(result["results"]) == 3
        assert len(result.get("errors", [])) == 0


class TestErrorContextPreservation:
    """Test that error context is preserved at each level."""

    @pytest.mark.asyncio
    async def test_agent_context_preserved(self):
        """Test agent error context is preserved."""
        agent = MockAgent("context_agent", should_fail=True)

        with pytest.raises(AgentError) as exc_info:
            await agent.execute({"request_id": "req-123"})

        error = exc_info.value

        # Agent should preserve its context
        assert error.context["agent"] == "context_agent"
        assert error.context["operation"] == "execute"

    @pytest.mark.asyncio
    async def test_stage_context_added(self):
        """Test stage adds its own context to error."""
        agent = MockAgent("agent1", should_fail=True)
        stage = MockStage("context_stage", [agent])

        with pytest.raises(StageExecutionError) as exc_info:
            await stage.execute({"request_id": "req-456"})

        error = exc_info.value

        # Stage should add its context
        assert error.context["stage"] == "context_stage"

        # Original agent error should be preserved
        agent_error = error.agent_errors[0]
        assert agent_error.context["agent"] == "agent1"

    @pytest.mark.asyncio
    async def test_workflow_context_complete_chain(self):
        """Test workflow preserves complete context chain."""
        agent = MockAgent("agent1", should_fail=True)
        stage = MockStage("stage1", [agent])
        workflow = MockWorkflow("workflow1", [stage])

        with pytest.raises(WorkflowExecutionError) as exc_info:
            await workflow.execute({"request_id": "req-789", "user": "test_user"})

        error = exc_info.value

        # Workflow context
        assert error.context["workflow"] == "workflow1"
        assert error.context["failed_stage"] == "stage1"

        # Stage context preserved
        stage_error = error.stage_errors[0]
        assert stage_error.context["stage"] == "stage1"

        # Agent context preserved
        agent_error = stage_error.agent_errors[0]
        assert agent_error.context["agent"] == "agent1"


class TestErrorCascadingControl:
    """Test that error cascading stops when appropriate."""

    @pytest.mark.asyncio
    async def test_error_stops_at_stage_level(self):
        """Test error can be caught and handled at stage level."""
        # Agent fails, but stage handles it
        agent = MockAgent("fail_agent", should_fail=True)
        stage = MockStage("handling_stage", [agent], fail_on_error=False)

        # Should not raise
        result = await stage.execute({})

        # Error captured but not propagated
        assert result["partial_failure"] is True
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_workflow_continues_after_recoverable_error(self):
        """Test workflow can continue after stage with partial failures."""
        # Stage 1: partial failure (2 of 3 succeed)
        stage1_agents = [
            MockAgent("a1", should_fail=False),
            MockAgent("a2", should_fail=True),
            MockAgent("a3", should_fail=False),
        ]
        stage1 = MockStage("stage1", stage1_agents, fail_on_error=False)

        # Stage 2: all succeed
        stage2_agents = [MockAgent("a4", should_fail=False)]
        stage2 = MockStage("stage2", stage2_agents, fail_on_error=False)

        workflow = MockWorkflow("resilient_workflow", [stage1, stage2])

        # Should complete successfully despite stage1 partial failure
        result = await workflow.execute({})

        assert len(result["stages"]) == 2

        # Stage 1 had partial failure
        assert result["stages"][0]["partial_failure"] is True

        # Stage 2 succeeded
        assert len(result["stages"][1]["results"]) == 1


class TestErrorMetadataSanitization:
    """Test that secrets are not leaked in error messages."""

    def test_api_key_sanitized_in_error(self):
        """Test API keys are sanitized from error messages."""
        api_key = "sk-1234567890abcdef"

        def sanitize_error_message(message: str) -> str:
            """Sanitize sensitive data from error messages."""
            import re

            # Sanitize API keys (sk-*, api-*, etc.)
            message = re.sub(r'(sk|api|key)-[a-zA-Z0-9]+', '[REDACTED-API-KEY]', message)

            # Sanitize tokens (Bearer, etc.)
            message = re.sub(r'Bearer [a-zA-Z0-9._-]+', 'Bearer [REDACTED-TOKEN]', message)

            # Sanitize passwords
            message = re.sub(r'password["\']?\s*[:=]\s*["\']?[^\s"\']+', 'password=[REDACTED]', message, flags=re.IGNORECASE)

            return message

        # Error message with API key
        error_message = f"Authentication failed with API key: {api_key}"

        # Sanitize
        sanitized = sanitize_error_message(error_message)

        # API key should be redacted
        assert api_key not in sanitized
        assert "[REDACTED-API-KEY]" in sanitized

    def test_password_sanitized_in_error(self):
        """Test passwords are sanitized from error messages."""
        password = "super_secret_password_123"

        def sanitize_error_message(message: str) -> str:
            import re
            return re.sub(r'password["\']?\s*[:=]\s*["\']?[^\s"\']+', 'password=[REDACTED]', message, flags=re.IGNORECASE)

        error_message = f"Database connection failed: password={password}"

        sanitized = sanitize_error_message(error_message)

        # Password should be redacted
        assert password not in sanitized
        assert "[REDACTED]" in sanitized

    def test_bearer_token_sanitized_in_error(self):
        """Test bearer tokens are sanitized from error messages."""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"

        def sanitize_error_message(message: str) -> str:
            import re
            return re.sub(r'Bearer [a-zA-Z0-9._-]+', 'Bearer [REDACTED-TOKEN]', message)

        error_message = f"API request failed: Authorization: Bearer {token}"

        sanitized = sanitize_error_message(error_message)

        # Token should be redacted
        assert token not in sanitized
        assert "[REDACTED-TOKEN]" in sanitized

    def test_multiple_secrets_sanitized(self):
        """Test multiple secrets in same error are all sanitized."""
        api_key = "sk-test-key-123"
        password = "my_password"
        token = "jwt_token_xyz"

        def sanitize_error_message(message: str) -> str:
            import re
            message = re.sub(r'(sk|api|key)-[a-zA-Z0-9-]+', '[REDACTED-API-KEY]', message)
            message = re.sub(r'password["\']?\s*[:=]\s*["\']?[^\s"\']+', 'password=[REDACTED]', message, flags=re.IGNORECASE)
            message = re.sub(r'Bearer [a-zA-Z0-9._-]+', 'Bearer [REDACTED-TOKEN]', message)
            return message

        error_message = f"Auth failed: api_key={api_key}, password={password}, Bearer {token}"

        sanitized = sanitize_error_message(error_message)

        # All secrets should be redacted
        assert api_key not in sanitized
        assert password not in sanitized
        assert token not in sanitized
        assert sanitized.count("[REDACTED") == 3


class TestErrorMessageQuality:
    """Test that error messages are helpful and actionable."""

    @pytest.mark.asyncio
    async def test_error_message_includes_context(self):
        """Test error messages include relevant context."""
        agent = MockAgent("data_processor", should_fail=True)

        with pytest.raises(AgentError) as exc_info:
            await agent.execute({})

        error = exc_info.value

        # Error message should include agent name
        assert "data_processor" in str(error)

        # Context should be present
        assert "agent" in error.context
        assert error.context["agent"] == "data_processor"

    @pytest.mark.asyncio
    async def test_nested_error_messages_are_clear(self):
        """Test nested errors have clear messages at each level."""
        agent = MockAgent("failing_agent", should_fail=True, error_type=ToolNotFoundError)
        stage = MockStage("processing_stage", [agent])
        workflow = MockWorkflow("data_pipeline", [stage])

        with pytest.raises(WorkflowExecutionError) as exc_info:
            await workflow.execute({})

        error = exc_info.value

        # Workflow level message
        workflow_msg = str(error)
        assert "data_pipeline" in workflow_msg
        assert "processing_stage" in workflow_msg

        # Stage level message
        stage_error = error.stage_errors[0]
        stage_msg = str(stage_error)
        assert "processing_stage" in stage_msg

        # Agent level message
        agent_error = stage_error.agent_errors[0]
        agent_msg = str(agent_error)
        assert "failing_agent" in agent_msg

    @pytest.mark.asyncio
    async def test_error_type_distinguishable(self):
        """Test different error types are distinguishable."""
        # Different error types
        tool_error_agent = MockAgent("agent1", should_fail=True, error_type=ToolNotFoundError)
        generic_error_agent = MockAgent("agent2", should_fail=True, error_type=AgentError)

        # Both raise errors
        with pytest.raises(ToolNotFoundError):
            await tool_error_agent.execute({})

        with pytest.raises(AgentError):
            await generic_error_agent.execute({})

        # Types should be distinct
        assert ToolNotFoundError != AgentError
        assert issubclass(ToolNotFoundError, AgentError)


class TestErrorSanitizationIntegration:
    """Test that error sanitization is integrated into all error classes.

    SECURITY CRITICAL: These tests verify that sensitive data (API keys, passwords,
    tokens) are automatically redacted from all error messages, preventing secret
    leakage in logs, monitoring systems, and error tracking services.
    """

    def test_api_key_redacted_in_agent_error(self):
        """Test API keys are redacted in AgentError messages."""
        from src.utils.exceptions import AgentError, ErrorCode, ExecutionContext

        api_key = "sk-test-1234567890abcdef"

        # Create error with API key in message
        error = AgentError(
            message=f"API key {api_key} failed authentication",
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            context=ExecutionContext(agent_id="test-agent")
        )

        error_str = str(error)

        # API key should be redacted
        assert api_key not in error_str, "API key leaked in error message!"
        assert "[REDACTED-API-KEY]" in error_str

    def test_aws_key_redacted_in_llm_error(self):
        """Test AWS keys are redacted in LLMError messages."""
        from src.utils.exceptions import ErrorCode, LLMError

        aws_key = "AKIAIOSFODNN7EXAMPLE"

        error = LLMError(
            message=f"AWS access key {aws_key} unauthorized",
            error_code=ErrorCode.LLM_AUTHENTICATION_ERROR,
            provider="openai"
        )

        error_str = str(error)

        # AWS key should be redacted
        assert aws_key not in error_str
        assert "[REDACTED-AWS-KEY]" in error_str

    def test_password_redacted_in_config_error(self):
        """Test passwords are redacted in ConfigurationError messages."""
        from src.utils.exceptions import ConfigurationError, ErrorCode

        password = "SuperSecret123!"

        error = ConfigurationError(
            message=f"Database connection failed: password={password}",
            error_code=ErrorCode.CONFIG_INVALID
        )

        error_str = str(error)

        # Password should be redacted
        assert password not in error_str
        assert "[REDACTED-PASSWORD]" in error_str

    def test_bearer_token_redacted_in_tool_error(self):
        """Test Bearer tokens are redacted in ToolError messages."""
        from src.utils.exceptions import ErrorCode, ToolError

        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"

        error = ToolError(
            message=f"API request failed: Authorization: Bearer {token}",
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            tool_name="api_caller"
        )

        error_str = str(error)

        # Token should be redacted
        assert token not in error_str
        assert "[REDACTED-TOKEN]" in error_str or "[REDACTED-JWT-TOKEN]" in error_str

    def test_jwt_token_redacted_in_workflow_error(self):
        """Test JWT tokens are redacted in WorkflowError messages."""
        from src.utils.exceptions import ErrorCode, WorkflowError

        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

        error = WorkflowError(
            message=f"Auth failed with token {jwt}",
            error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR
        )

        error_str = str(error)

        # JWT should be redacted
        assert jwt not in error_str
        assert "[REDACTED-JWT-TOKEN]" in error_str

    def test_connection_string_redacted_in_safety_error(self):
        """Test database connection strings are redacted in SafetyError."""
        from src.utils.exceptions import ErrorCode, SafetyError

        conn_str = "postgresql://admin:secret123@localhost:5432/mydb"

        error = SafetyError(
            message=f"Invalid connection: {conn_str}",
            error_code=ErrorCode.SAFETY_VIOLATION
        )

        error_str = str(error)

        # Password in connection string should be redacted
        assert "secret123" not in error_str
        assert "[REDACTED-CREDENTIALS]" in error_str

    def test_multiple_secrets_redacted_in_validation_error(self):
        """Test multiple secrets in same error are all redacted."""
        from src.utils.exceptions import ErrorCode, ValidationError

        api_key = "sk-prod-key-xyz"
        password = "MyP@ssw0rd!"
        token = "eyJhbGciOiJIUzI1NiJ9.test"

        error = ValidationError(
            message=f"Auth failed: api_key={api_key}, password={password}, token={token}",
            error_code=ErrorCode.VALIDATION_ERROR
        )

        error_str = str(error)

        # All secrets should be redacted
        assert api_key not in error_str
        assert password not in error_str
        assert token not in error_str
        assert error_str.count("[REDACTED") >= 3

    def test_secrets_redacted_in_repr(self):
        """Test secrets are redacted in error repr()."""
        from src.utils.exceptions import ErrorCode, LLMError

        api_key = "sk-test-secret-key"

        error = LLMError(
            message=f"API call with key {api_key} failed",
            error_code=ErrorCode.LLM_AUTHENTICATION_ERROR
        )

        repr_str = repr(error)

        # API key should be redacted in repr
        assert api_key not in repr_str
        assert "[REDACTED-API-KEY]" in repr_str

    def test_secrets_redacted_in_to_dict(self):
        """Test secrets are redacted in error.to_dict()."""
        from src.utils.exceptions import AgentError, ErrorCode

        password = "admin123"

        error = AgentError(
            message=f"Login failed with password: {password}",
            error_code=ErrorCode.AGENT_EXECUTION_ERROR
        )

        error_dict = error.to_dict()

        # Password should be redacted in dict representation
        assert password not in error_dict["message"]
        assert "[REDACTED-PASSWORD]" in error_dict["message"]

    def test_secrets_redacted_in_cause(self):
        """Test secrets are redacted when error wraps another exception."""
        from src.utils.exceptions import ErrorCode, ToolError

        api_key = "api-key-1234567890"

        # Create a cause exception with secret
        try:
            raise ValueError(f"Invalid API key: {api_key}")
        except ValueError as e:
            error = ToolError(
                message="Tool execution failed",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                cause=e
            )

        error_str = str(error)

        # API key should be redacted in cause message
        assert api_key not in error_str
        assert "[REDACTED-API-KEY]" in error_str

    def test_secrets_redacted_in_traceback(self):
        """Test secrets are redacted in error traceback."""

        from src.utils.exceptions import ErrorCode, WorkflowError

        password = "p@ssw0rd!"

        # Create error with cause to trigger traceback
        # Use password=value format so it matches the regex pattern
        try:
            try:
                raise RuntimeError(f"Database connection failed: password={password}")
            except RuntimeError as e:
                # Create error while exception is active (so traceback.format_exc() works)
                error = WorkflowError(
                    message="Workflow failed",
                    error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
                    cause=e
                )
                error_dict = error.to_dict()
        except Exception:
            pass

        # Password should be redacted in traceback
        if error_dict.get("traceback"):
            assert password not in error_dict["traceback"], \
                f"Password leaked in traceback: {error_dict['traceback']}"
            assert "[REDACTED-PASSWORD]" in error_dict["traceback"]

    def test_api_key_formats_all_redacted(self):
        """Test various API key formats are all redacted."""
        from src.utils.exceptions import ErrorCode, LLMError

        test_keys = [
            ("sk-test-key", "sk- prefix"),
            ("api-prod-key-xyz", "api- prefix"),
            ("key-admin-12345", "key- prefix"),
            ("api_key=sk-secret-123", "assignment format"),
            ("apiKey: api-key-456", "camelCase format"),
        ]

        for key, description in test_keys:
            error = LLMError(
                message=f"Auth failed: {key}",
                error_code=ErrorCode.LLM_AUTHENTICATION_ERROR
            )

            error_str = str(error)

            # Extract the actual secret from the key string
            if "=" in key or ":" in key:
                # For assignment formats, check that value is redacted
                assert "[REDACTED" in error_str, f"Failed to redact {description}: {key}"
            else:
                # For plain keys, check that key is redacted
                assert key not in error_str, f"Failed to redact {description}: {key}"
                assert "[REDACTED-API-KEY]" in error_str

    def test_password_formats_all_redacted(self):
        """Test various password formats are all redacted."""
        from src.utils.exceptions import ConfigurationError, ErrorCode

        test_passwords = [
            ("password=secret", "equals format"),
            ("password: secret", "colon format"),
            ("pwd=admin123", "abbreviated format"),
            ("Password='p@ss'", "quoted format"),
        ]

        for pwd_str, description in test_passwords:
            error = ConfigurationError(
                message=f"Config error: {pwd_str}",
                error_code=ErrorCode.CONFIG_INVALID
            )

            error_str = str(error)

            # Password value should be redacted
            assert "[REDACTED" in error_str, f"Failed to redact {description}: {pwd_str}"

    def test_sanitization_performance(self):
        """Test that error sanitization has minimal performance overhead."""
        import time

        from src.utils.exceptions import AgentError, ErrorCode

        # Test with message containing secrets
        message_with_secrets = (
            "Error: api_key=sk-test-123, password=secret, "
            "token=eyJhbGciOiJIUzI1NiJ9.test, aws_key=AKIAIOSFODNN7EXAMPLE"
        )

        # Measure time for 1000 error creations
        start = time.time()
        for i in range(1000):
            error = AgentError(
                message=message_with_secrets,
                error_code=ErrorCode.AGENT_EXECUTION_ERROR
            )
            _ = str(error)
        elapsed = time.time() - start

        # Average time per error should be < 1ms
        avg_time_ms = (elapsed / 1000) * 1000
        assert avg_time_ms < 1.0, f"Sanitization too slow: {avg_time_ms:.2f}ms per error"

    def test_no_false_positives(self):
        """Test that sanitization doesn't redact non-secret data."""
        from src.utils.exceptions import ErrorCode, ToolError

        # Message with words that contain trigger patterns but aren't secrets
        message = (
            "Tool execution at stage skipped due to apiVersion mismatch. "
            "Password field was empty. Key parameter missing."
        )

        error = ToolError(
            message=message,
            error_code=ErrorCode.TOOL_EXECUTION_ERROR
        )

        error_str = str(error)

        # These normal words should NOT be redacted
        assert "skipped" in error_str
        assert "apiVersion" in error_str
        assert "Password field" in error_str  # "Password" as word, not assignment
        assert "Key parameter" in error_str  # "Key" as word, not key-value

    def test_edge_case_empty_message(self):
        """Test sanitization handles empty messages gracefully."""
        from src.utils.exceptions import BaseError, ErrorCode

        error = BaseError(
            message="",
            error_code=ErrorCode.UNKNOWN_ERROR
        )

        error_str = str(error)

        # Should not crash, should produce valid string
        assert isinstance(error_str, str)
        assert "[UNKNOWN_ERROR]" in error_str

    def test_edge_case_none_message(self):
        """Test sanitization handles None in cause gracefully."""
        from src.utils.exceptions import AgentError, ErrorCode

        error = AgentError(
            message="Test error",
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            cause=None
        )

        error_str = str(error)

        # Should not crash
        assert isinstance(error_str, str)
        assert "Test error" in error_str
