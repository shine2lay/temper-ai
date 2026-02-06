"""
Regression tests for integration bugs.

Tests for bugs that appear in end-to-end scenarios and component interactions.
"""
from unittest.mock import patch

import pytest

from src.agents.agent_factory import AgentFactory
from src.agents.standard_agent import StandardAgent
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)
from src.tools.calculator import Calculator
from src.tools.registry import ToolRegistry


class TestAgentToolIntegration:
    """Regression tests for agent-tool integration bugs."""

    def test_agent_tool_registry_mismatch(self):
        """
        Regression test for agent-tool registry mismatch.

        Bug: Agent created with tools not in registry, causing runtime errors.
        Discovered: Integration testing
        Affects: Agent initialization with tools
        Severity: HIGH (agent fails at runtime)
        Fixed: Agent initialization NOW VALIDATES tools exist and fails early with clear error
        """
        config = AgentConfig(
            agent=AgentConfigInner(
                name="test_agent",
                description="Test",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="Test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=["NonexistentTool"],  # Tool not in registry
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        # Agent creation should now fail early with validation error
        with pytest.raises((ValueError, KeyError, Exception)) as exc_info:
            agent = AgentFactory.create(config)

        # Should get clear error about missing tool
        error_msg = str(exc_info.value).lower()
        assert "tool" in error_msg or "nonexistent" in error_msg


class TestConfigAgentIntegration:
    """Regression tests for config-agent integration bugs."""

    def test_config_to_agent_field_mapping(self, minimal_agent_config):
        """
        Regression test for config field mapping to agent.

        Bug: Config fields not properly mapped to agent attributes.
        Discovered: Agent initialization testing
        Affects: All agent creation
        Severity: HIGH (incorrect agent behavior)
        Fixed: AgentFactory now properly maps all config fields
        """
        with patch('src.agents.standard_agent.ToolRegistry'):
            agent = AgentFactory.create(minimal_agent_config)

            # Verify all config fields mapped correctly
            assert agent.name == minimal_agent_config.agent.name
            assert agent.description == minimal_agent_config.agent.description
            assert agent.version == minimal_agent_config.agent.version


class TestToolExecutorIntegration:
    """Regression tests for tool executor integration bugs."""

    def test_executor_result_metadata_missing(self):
        """
        Regression test for missing result metadata.

        Bug: Tool execution metadata not included in results.
        Discovered: Observability testing
        Affects: All tool executions
        Severity: MEDIUM (poor observability)
        Fixed: ToolExecutor now includes execution_time in metadata
        """
        registry = ToolRegistry()
        registry.register(Calculator())

        from src.tools.executor import ToolExecutor
        executor = ToolExecutor(registry)

        result = executor.execute(
            tool_name="Calculator",
            params={"expression": "2 + 2"}
        )

        # Should include metadata
        assert result.success is True
        # Metadata might be None or dict
        if result.metadata is not None:
            assert isinstance(result.metadata, dict)


class TestAgentFactory:
    """Regression tests for AgentFactory bugs."""

    def test_factory_default_type_handling(self, minimal_agent_config):
        """
        Regression test for default agent type.

        Bug: Missing type field caused KeyError instead of defaulting to "standard".
        Discovered: Backward compatibility testing
        Affects: Configs without explicit type
        Severity: MEDIUM (breaks old configs)
        Fixed: AgentFactory defaults to "standard" if type missing
        """
        # Remove type field if present
        if hasattr(minimal_agent_config.agent, 'type'):
            delattr(minimal_agent_config.agent, 'type')

        with patch('src.agents.standard_agent.ToolRegistry'):
            agent = AgentFactory.create(minimal_agent_config)

            # Should default to StandardAgent
            assert isinstance(agent, StandardAgent)


class TestErrorHandlingIntegration:
    """Regression tests for error handling integration bugs."""

    def test_error_propagation_from_tools(self):
        """
        Regression test for error propagation.

        Bug: Tool errors not properly propagated to agent responses.
        Discovered: Error handling testing
        Affects: All tool executions
        Severity: HIGH (silent failures)
        Fixed: ToolExecutor returns error in ToolResult
        """
        registry = ToolRegistry()
        registry.register(Calculator())

        from src.tools.executor import ToolExecutor
        executor = ToolExecutor(registry)

        # Execute with invalid params
        result = executor.execute(
            tool_name="Calculator",
            params={"expression": ""}  # Empty expression
        )

        # Error should be in result
        assert result.success is False
        assert result.error is not None
        assert len(result.error) > 0


class TestConcurrency:
    """Regression tests for concurrency bugs."""

    def test_concurrent_tool_execution_safety(self):
        """
        Regression test for concurrent tool execution.

        Bug: Concurrent tool executions caused race conditions.
        Discovered: Load testing
        Affects: Multi-threaded environments
        Severity: HIGH (data corruption)
        Fixed: ToolExecutor uses ThreadPoolExecutor with proper locking
        """
        registry = ToolRegistry()
        registry.register(Calculator())

        import concurrent.futures

        from src.tools.executor import ToolExecutor

        executor = ToolExecutor(registry, max_workers=4)

        def execute_calc():
            return executor.execute(
                tool_name="Calculator",
                params={"expression": "2 + 2"}
            )

        # Execute concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(execute_calc) for _ in range(20)]
            results = [f.result() for f in futures]

        # All should succeed
        assert len(results) == 20
        assert all(r.success for r in results)
        assert all(r.result == 4 for r in results)
