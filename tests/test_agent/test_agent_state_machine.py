"""Agent execution state machine tests.

These tests cover agent execution state transitions during workflow stages.

Note: The current agent implementation doesn't have explicit state machine
states. These tests establish the foundation for future state management:

- Agent initialization and configuration
- Execution tracking through stages
- Error handling and recovery
- Resource cleanup

Future enhancement: Add explicit agent states (idle, executing, tool_call,
waiting, completed, failed, retry) for better observability and control.
"""
from typing import Any, Dict, Optional
from unittest.mock import patch

from temper_ai.agent.base_agent import AgentResponse, BaseAgent, ExecutionContext
from temper_ai.storage.schemas.agent_config import AgentConfig


def create_mock_config(name: str = "test_agent", **kwargs) -> AgentConfig:
    """Create a mock agent config for testing."""
    config_dict = {
        "agent": {
            "name": name,
            "description": "Test agent",
            "version": "1.0",
            "inference": {
                "provider": "openai",
                "model": "gpt-4"
            },
            "prompt": {
                "template": "test template"
            },
            "tools": [],  # Required field
            "error_handling": {  # Required field
                "retry_strategy": "ExponentialBackoff",
                "max_retries": 3,
                "fallback": "GracefulDegradation",
                "escalate_to_human_after": 3
            }
        }
    }

    # Merge kwargs
    if kwargs:
        for key, value in kwargs.items():
            config_dict["agent"][key] = value

    return AgentConfig(**config_dict)


class MockAgent(BaseAgent):
    """Mock agent for testing."""

    def _run(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
        start_time: float = 0.0,
    ) -> AgentResponse:
        """Execute agent logic."""
        return AgentResponse(
            output="mock result",
            reasoning="mock reasoning",
            metadata={"input": input_data}
        )

    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities."""
        return {
            "name": self.name,
            "version": self.version,
            "tools": []
        }


def _make_mock_agent(config):
    """Create MockAgent with LLM creation patched out."""
    with patch("temper_ai.agent.base_agent.create_llm_from_config"):
        return MockAgent(config)


class TestAgentInitialization:
    """Test agent initialization state."""

    def test_agent_creation(self):
        """Test creating agent instance."""
        config = create_mock_config(name="test_agent")

        agent = _make_mock_agent(config)

        assert agent.config == config
        assert agent.name == "test_agent"
        assert agent.version == "1.0"

    def test_agent_with_tools(self):
        """Test agent initialization with tools."""
        config = create_mock_config(
            name="test_agent",
            tools=[{"name": "search"}, {"name": "calculator"}]
        )

        agent = _make_mock_agent(config)

        assert len(agent.config.agent.tools) == 2

    def test_agent_without_tools(self):
        """Test agent initialization without tools."""
        config = create_mock_config(name="test_agent")

        agent = _make_mock_agent(config)

        # Tools configuration might not exist or be empty
        assert agent.name == "test_agent"


class TestAgentExecutionFlow:
    """Test agent execution state flow."""

    def test_agent_execution_success(self):
        """Test successful agent execution."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        input_data = {"query": "test query"}
        result = agent.execute(input_data)

        assert isinstance(result, AgentResponse)
        assert result.output is not None
        assert result.metadata["input"] == input_data

    def test_agent_execution_with_context(self):
        """Test agent execution propagates context and input."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        input_data = {
            "query": "follow-up",
            "previous_output": "initial result"
        }

        context = ExecutionContext(
            workflow_id="wf-001",
            stage_id="stage1"
        )

        result = agent.execute(input_data, context)

        assert isinstance(result, AgentResponse)
        assert result.output == "mock result"
        assert result.metadata["input"] == input_data
        assert agent._execution_context is context
        assert agent._execution_context.workflow_id == "wf-001"

    def test_agent_multiple_executions(self):
        """Test agent can execute multiple times with independent results."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        result1 = agent.execute({"query": "first"})
        result2 = agent.execute({"query": "second"})
        result3 = agent.execute({"query": "third"})

        assert result1.metadata["input"] == {"query": "first"}
        assert result2.metadata["input"] == {"query": "second"}
        assert result3.metadata["input"] == {"query": "third"}
        assert result1.error is None
        assert result2.error is None
        assert result3.error is None


class TestAgentErrorHandling:
    """Test agent error handling and recovery."""

    def test_agent_handles_empty_input(self):
        """Test agent handles empty input."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        # Execute with empty input
        result = agent.execute({})

        # Should not crash
        assert isinstance(result, AgentResponse)
        assert result.output is not None


class TestAgentStateConsistency:
    """Test agent state consistency across operations."""

    def test_agent_config_preserved_during_execution(self):
        """Test agent config is preserved during execution."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        original_name = agent.name
        original_version = agent.version

        # Execute
        agent.execute({"query": "test"})

        # Config should be unchanged
        assert agent.name == original_name
        assert agent.version == original_version

    def test_agent_name_persistence(self):
        """Test agent name persists across executions."""
        config = create_mock_config(name="persistent_agent")
        agent = _make_mock_agent(config)

        assert agent.name == "persistent_agent"

        # Execute
        agent.execute({"query": "test"})

        # Name still the same
        assert agent.name == "persistent_agent"


class TestAgentToolCalls:
    """Test agent tool calling patterns.

    Future enhancement: Add explicit tool_call state to track
    when agent is waiting for tool results.
    """

    def test_agent_with_tool_config(self):
        """Test agent configured with tools."""
        config = create_mock_config(
            name="tool_agent",
            tools=[
                {"name": "search", "description": "Search the web"},
                {"name": "calculator", "description": "Calculate"}
            ]
        )

        agent = _make_mock_agent(config)

        assert agent.name == "tool_agent"

    def test_agent_tool_execution_simulation(self):
        """Test agent with tool config completes and preserves input."""
        config = create_mock_config(
            name="tool_agent",
            tools=[{"name": "search"}]
        )

        agent = _make_mock_agent(config)

        input_data = {
            "query": "search for Python",
            "use_tools": True
        }

        result = agent.execute(input_data)

        assert isinstance(result, AgentResponse)
        assert result.error is None
        assert result.metadata["input"] == input_data
        assert len(agent.config.agent.tools) == 1


class TestAgentResourceManagement:
    """Test agent resource management."""

    def test_agent_accessible_after_execution(self):
        """Test agent remains functional after execution."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        result1 = agent.execute({"query": "test"})
        assert result1.error is None

        # Agent should still be usable for subsequent calls
        result2 = agent.execute({"query": "another"})
        assert result2.error is None
        assert result2.metadata["input"] == {"query": "another"}
        assert agent.name == "test_agent"

    def test_agent_config_validation(self):
        """Test agent validates configuration."""
        valid_config = create_mock_config(name="valid_agent")

        # Should not raise
        agent = _make_mock_agent(valid_config)
        assert agent.name == "valid_agent"
        assert agent.validate_config() is True


class TestAgentEdgeCases:
    """Test edge cases in agent state management."""

    def test_agent_with_complex_input(self):
        """Test agent with complex nested input."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        complex_input = {
            "query": "test",
            "context": {
                "previous": ["item1", "item2"],
                "metadata": {"key": "value"}
            },
            "options": {
                "temperature": 0.7,
                "max_tokens": 1000
            }
        }

        result = agent.execute(complex_input)

        assert isinstance(result, AgentResponse)
        assert result.output is not None

    def test_agent_execution_order(self):
        """Test multiple agents can execute in sequence."""
        agent1 = _make_mock_agent(create_mock_config(name="agent1"))
        agent2 = _make_mock_agent(create_mock_config(name="agent2"))

        result1 = agent1.execute({"query": "first"})
        # Pass result1 to agent2
        result2 = agent2.execute({"query": "second", "previous": result1.output})

        assert isinstance(result1, AgentResponse)
        assert isinstance(result2, AgentResponse)

    def test_agent_large_input(self):
        """Test agent handles large input without error."""
        config = create_mock_config(name="test_agent")
        agent = _make_mock_agent(config)

        large_input = {
            "query": "process data",
            "data": ["item" * 100 for _ in range(1000)]
        }

        result = agent.execute(large_input)

        assert isinstance(result, AgentResponse)
        assert result.error is None
        assert result.metadata["input"] == large_input
        assert len(result.metadata["input"]["data"]) == 1000


class TestAgentConcurrentExecution:
    """Test agent behavior under concurrent execution scenarios.

    Future enhancement: Add state locking or concurrent execution guards.
    """

    def test_multiple_agents_independent(self):
        """Test multiple agent instances are independent."""
        agent1 = _make_mock_agent(create_mock_config(name="agent1"))
        agent2 = _make_mock_agent(create_mock_config(name="agent2"))

        result1 = agent1.execute({"query": "query1"})
        result2 = agent2.execute({"query": "query2"})

        # Agents should be independent
        assert agent1.name == "agent1"
        assert agent2.name == "agent2"
        assert isinstance(result1, AgentResponse)
        assert isinstance(result2, AgentResponse)

    def test_same_agent_sequential_execution(self):
        """Test same agent instance can execute sequentially."""
        agent = _make_mock_agent(create_mock_config(name="sequential_agent"))

        results = []
        for i in range(5):
            result = agent.execute({"query": f"query_{i}"})
            results.append(result)

        # All executions should succeed
        assert len(results) == 5
        assert all(isinstance(r, AgentResponse) for r in results)
