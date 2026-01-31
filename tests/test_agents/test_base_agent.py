"""Tests for base agent interface."""
import pytest
from src.agents.base_agent import BaseAgent, AgentResponse, ExecutionContext
from src.compiler.schemas import AgentConfig


def test_agent_response_creation():
    """Test AgentResponse dataclass creation."""
    response = AgentResponse(
        output="Hello world",
        reasoning="This is my thought process",
        tool_calls=[{"name": "calculator", "result": 42}],
        tokens=100,
        estimated_cost_usd=0.002,
        latency_seconds=1.5,
    )

    assert response.output == "Hello world"
    assert response.reasoning == "This is my thought process"
    assert len(response.tool_calls) == 1
    assert response.tokens == 100
    assert response.estimated_cost_usd == 0.002
    assert response.latency_seconds == 1.5
    assert response.error is None


def test_agent_response_with_error():
    """Test AgentResponse with error."""
    response = AgentResponse(
        output="",
        error="LLM call failed",
        latency_seconds=0.5,
    )

    assert response.output == ""
    assert response.error == "LLM call failed"
    assert response.tokens == 0


def test_execution_context_creation():
    """Test ExecutionContext dataclass creation."""
    context = ExecutionContext(
        workflow_id="wf-001",
        stage_id="stage-001",
        agent_id="agent-001",
        session_id="session-123",
        metadata={"user": "test"}
    )

    assert context.workflow_id == "wf-001"
    assert context.stage_id == "stage-001"
    assert context.agent_id == "agent-001"
    assert context.session_id == "session-123"
    assert context.metadata["user"] == "test"


def test_execution_context_defaults():
    """Test ExecutionContext with default values."""
    context = ExecutionContext()

    assert context.workflow_id is None
    assert context.stage_id is None
    assert context.agent_id is None
    assert context.session_id is None
    assert context.user_id is None
    assert context.metadata == {}


def test_base_agent_is_abstract():
    """Test that BaseAgent cannot be instantiated directly."""
    # This should fail since BaseAgent is abstract
    with pytest.raises(TypeError):
        BaseAgent(None)  # type: ignore


class MockAgent(BaseAgent):
    """Mock agent for testing interface contract."""

    def execute(self, input_data, context=None):
        return AgentResponse(
            output="mock output",
            reasoning="mock reasoning",
        )

    def get_capabilities(self):
        return {
            "name": self.name,
            "type": "mock",
            "tools": []
        }


def test_base_agent_subclass_requires_execute():
    """Test that subclasses must implement execute()."""

    class IncompleteAgent(BaseAgent):
        """Agent missing execute implementation."""
        def get_capabilities(self):
            return {}

    # Should fail to instantiate without execute()
    with pytest.raises(TypeError):
        IncompleteAgent(None)  # type: ignore


def test_base_agent_subclass_requires_get_capabilities():
    """Test that subclasses must implement get_capabilities()."""

    class IncompleteAgent(BaseAgent):
        """Agent missing get_capabilities implementation."""
        def execute(self, input_data, context=None):
            return AgentResponse(output="test")

    # Should fail to instantiate without get_capabilities()
    with pytest.raises(TypeError):
        IncompleteAgent(None)  # type: ignore


def test_mock_agent_initialization(minimal_agent_config):
    """Test MockAgent initialization."""
    agent = MockAgent(minimal_agent_config)

    assert agent.config == minimal_agent_config
    assert agent.name == minimal_agent_config.agent.name
    assert agent.description == minimal_agent_config.agent.description
    assert agent.version == minimal_agent_config.agent.version


def test_mock_agent_execute(minimal_agent_config):
    """Test MockAgent execute method."""
    agent = MockAgent(minimal_agent_config)

    response = agent.execute({"query": "test"})

    assert isinstance(response, AgentResponse)
    assert response.output == "mock output"
    assert response.reasoning == "mock reasoning"


def test_mock_agent_execute_with_context(minimal_agent_config):
    """Test MockAgent execute with context."""
    agent = MockAgent(minimal_agent_config)
    context = ExecutionContext(workflow_id="wf-001")

    response = agent.execute({"query": "test"}, context=context)

    assert isinstance(response, AgentResponse)
    assert response.output == "mock output"


def test_mock_agent_get_capabilities(minimal_agent_config):
    """Test MockAgent get_capabilities method."""
    agent = MockAgent(minimal_agent_config)

    capabilities = agent.get_capabilities()

    assert isinstance(capabilities, dict)
    assert capabilities["name"] == minimal_agent_config.agent.name
    assert capabilities["type"] == "mock"
    assert "tools" in capabilities


def test_base_agent_validate_config(minimal_agent_config):
    """Test base agent config validation."""
    agent = MockAgent(minimal_agent_config)

    # Should pass validation
    assert agent.validate_config() is True


def test_base_agent_validate_config_missing_name():
    """Test validation fails with missing name."""
    from src.compiler.schemas import (
        AgentConfigInner,
        PromptConfig,
        InferenceConfig,
        ErrorHandlingConfig,
    )

    config = AgentConfig(
        agent=AgentConfigInner(
            name="",  # Empty name
            description="Test",
            prompt=PromptConfig(inline="test"),
            inference=InferenceConfig(provider="ollama", model="llama2"),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )

    agent = MockAgent(config)

    with pytest.raises(ValueError, match="Agent name is required"):
        agent.validate_config()


class TestContextPropagation:
    """Tests for ExecutionContext propagation through agent calls (P1)."""

    def test_context_passed_to_child_agent(self, minimal_agent_config):
        """Test that context is passed from parent to child agent."""

        class ChildAgent(MockAgent):
            """Agent that captures the context it receives."""
            received_context = None

            def execute(self, input_data, context=None):
                ChildAgent.received_context = context
                return AgentResponse(output="child response")

        class ParentAgent(MockAgent):
            """Agent that calls child agent."""
            def __init__(self, config):
                super().__init__(config)
                self.child = ChildAgent(config)

            def execute(self, input_data, context=None):
                # Call child agent with context
                child_response = self.child.execute({"nested": True}, context=context)
                return AgentResponse(output=f"parent wraps: {child_response.output}")

        # Create parent with context
        parent = ParentAgent(minimal_agent_config)
        parent_context = ExecutionContext(
            workflow_id="wf-parent",
            stage_id="stage-1",
            agent_id="agent-parent"
        )

        # Execute parent (which calls child)
        response = parent.execute({"test": True}, context=parent_context)

        # Verify child received the context
        assert ChildAgent.received_context is not None
        assert ChildAgent.received_context.workflow_id == "wf-parent"
        assert ChildAgent.received_context.stage_id == "stage-1"
        assert ChildAgent.received_context.agent_id == "agent-parent"

    def test_context_preserved_across_multiple_calls(self, minimal_agent_config):
        """Test context is preserved across multiple agent calls."""

        class ContextCapturingAgent(MockAgent):
            """Agent that captures all contexts it receives."""
            captured_contexts = []

            def execute(self, input_data, context=None):
                ContextCapturingAgent.captured_contexts.append(context)
                return AgentResponse(output=f"call {len(self.captured_contexts)}")

        agent = ContextCapturingAgent(minimal_agent_config)
        context = ExecutionContext(
            workflow_id="wf-123",
            stage_id="stage-456",
            session_id="session-789"
        )

        # Make multiple calls with same context
        agent.execute({"call": 1}, context=context)
        agent.execute({"call": 2}, context=context)
        agent.execute({"call": 3}, context=context)

        # All calls should have received the same context
        assert len(ContextCapturingAgent.captured_contexts) == 3
        for ctx in ContextCapturingAgent.captured_contexts:
            assert ctx.workflow_id == "wf-123"
            assert ctx.stage_id == "stage-456"
            assert ctx.session_id == "session-789"

    def test_context_includes_workflow_stage_ids(self, minimal_agent_config):
        """Test that context includes workflow_id and stage_id."""
        agent = MockAgent(minimal_agent_config)
        context = ExecutionContext(
            workflow_id="wf-production",
            stage_id="stage-processing"
        )

        # Execute with context
        response = agent.execute({"test": True}, context=context)

        # Verify context fields are set
        assert context.workflow_id == "wf-production"
        assert context.stage_id == "stage-processing"

    def test_context_with_parent_id_tracking(self, minimal_agent_config):
        """Test context can track parent agent relationships."""

        class TrackedAgent(MockAgent):
            """Agent that adds itself to context metadata."""
            def execute(self, input_data, context=None):
                if context and context.metadata:
                    # Track parent in metadata
                    parent_id = context.metadata.get("parent_agent_id")
                    context.metadata["current_agent_id"] = self.name
                    if parent_id:
                        context.metadata["parent_chain"] = context.metadata.get("parent_chain", []) + [parent_id]
                return AgentResponse(output="tracked")

        agent1 = TrackedAgent(minimal_agent_config)
        agent1.name = "agent-1"

        # Create context with parent tracking
        context = ExecutionContext(
            workflow_id="wf-001",
            metadata={"parent_agent_id": "agent-0"}
        )

        # Execute
        response = agent1.execute({"test": True}, context=context)

        # Verify parent was tracked
        assert context.metadata["current_agent_id"] == "agent-1"
        assert "agent-0" in context.metadata.get("parent_chain", [])

    def test_nested_agent_execution_depth_tracking(self, minimal_agent_config):
        """Test tracking execution depth in nested agent calls."""

        class DepthTrackingAgent(MockAgent):
            """Agent that tracks execution depth."""
            max_depth = 3

            def execute(self, input_data, context=None):
                if context is None:
                    context = ExecutionContext(metadata={})

                depth = context.metadata.get("depth", 0)
                context.metadata["depth"] = depth + 1

                # Call child if not at max depth
                if depth < self.max_depth:
                    child_response = self.execute(input_data, context=context)
                    return AgentResponse(output=f"depth {depth}: {child_response.output}")
                else:
                    return AgentResponse(output=f"max depth {depth}")

        agent = DepthTrackingAgent(minimal_agent_config)
        context = ExecutionContext(metadata={"depth": 0})

        # Execute with nesting
        response = agent.execute({"nested": True}, context=context)

        # Verify depth was tracked
        assert context.metadata["depth"] == 4  # 0→1→2→3→4

    def test_context_accessible_during_execution(self, minimal_agent_config):
        """Test that context is accessible during agent execution."""

        class ContextAwareAgent(MockAgent):
            """Agent that uses context during execution."""
            def execute(self, input_data, context=None):
                # Use context to modify behavior
                if context and context.workflow_id:
                    output = f"Processing in workflow: {context.workflow_id}"
                else:
                    output = "No workflow context"

                return AgentResponse(output=output)

        agent = ContextAwareAgent(minimal_agent_config)

        # Execute with context
        context = ExecutionContext(workflow_id="wf-production-123")
        response_with_context = agent.execute({"test": True}, context=context)
        assert "wf-production-123" in response_with_context.output

        # Execute without context
        response_without_context = agent.execute({"test": True}, context=None)
        assert response_without_context.output == "No workflow context"

    def test_context_metadata_extensibility(self, minimal_agent_config):
        """Test that context metadata can be extended with custom fields."""
        agent = MockAgent(minimal_agent_config)

        # Create context with custom metadata
        context = ExecutionContext(
            workflow_id="wf-001",
            metadata={
                "user_id": "user-123",
                "tenant_id": "tenant-456",
                "request_id": "req-789",
                "custom_field": "custom_value"
            }
        )

        # Execute
        response = agent.execute({"test": True}, context=context)

        # Verify custom metadata is preserved
        assert context.metadata["user_id"] == "user-123"
        assert context.metadata["tenant_id"] == "tenant-456"
        assert context.metadata["request_id"] == "req-789"
        assert context.metadata["custom_field"] == "custom_value"

    def test_context_session_id_tracking(self, minimal_agent_config):
        """Test that session_id is properly tracked in context."""

        class SessionAwareAgent(MockAgent):
            """Agent that tracks session information."""
            def execute(self, input_data, context=None):
                session_id = context.session_id if context else None
                return AgentResponse(
                    output=f"session: {session_id}",
                    metadata={"session_id": session_id}
                )

        agent = SessionAwareAgent(minimal_agent_config)
        context = ExecutionContext(
            workflow_id="wf-001",
            session_id="session-xyz"
        )

        response = agent.execute({"test": True}, context=context)

        # Verify session was tracked
        assert "session-xyz" in response.output
        assert response.metadata["session_id"] == "session-xyz"

    def test_context_user_id_propagation(self, minimal_agent_config):
        """Test that user_id propagates through context."""
        agent = MockAgent(minimal_agent_config)

        context = ExecutionContext(
            workflow_id="wf-001",
            user_id="user-alice"
        )

        # Execute
        response = agent.execute({"test": True}, context=context)

        # Verify user_id is in context
        assert context.user_id == "user-alice"

    def test_context_none_is_valid(self, minimal_agent_config):
        """Test that agents can handle None context gracefully."""
        agent = MockAgent(minimal_agent_config)

        # Execute without context (None)
        response = agent.execute({"test": True}, context=None)

        # Should succeed
        assert isinstance(response, AgentResponse)
        assert response.output == "mock output"
