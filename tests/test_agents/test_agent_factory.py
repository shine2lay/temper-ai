"""Tests for AgentFactory."""
import threading

import pytest

from src.agents.utils.agent_factory import AgentFactory
from src.agents.base_agent import AgentResponse, BaseAgent
from src.agents.standard_agent import StandardAgent
from src.compiler.schemas import AgentConfig


def test_agent_factory_create_standard_agent(minimal_agent_config):
    """Test factory creates StandardAgent for 'standard' type."""
    agent = AgentFactory.create(minimal_agent_config)

    assert isinstance(agent, StandardAgent)
    assert isinstance(agent, BaseAgent)
    assert agent.name == "test_agent"


def test_agent_factory_create_default_type(minimal_agent_config):
    """Test factory defaults to standard type if not specified."""
    # Remove type field (tests backward compatibility)
    if hasattr(minimal_agent_config.agent, 'type'):
        delattr(minimal_agent_config.agent, 'type')

    agent = AgentFactory.create(minimal_agent_config)

    assert isinstance(agent, StandardAgent)


def test_agent_factory_unknown_type():
    """Test factory raises error for unknown agent type."""
    from src.compiler.schemas import (
        AgentConfigInner,
        ErrorHandlingConfig,
        InferenceConfig,
        PromptConfig,
    )

    config = AgentConfig(
        agent=AgentConfigInner(
            name="test",
            description="Test",
            version="1.0",
            type="unknown_type",  # Invalid type
            prompt=PromptConfig(inline="test"),
            inference=InferenceConfig(provider="ollama", model="llama2"),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )

    with pytest.raises(ValueError, match="Unknown agent type: 'unknown_type'"):
        AgentFactory.create(config)


def test_agent_factory_list_types():
    """Test factory lists all registered types."""
    types = AgentFactory.list_types()

    assert isinstance(types, dict)
    assert "standard" in types
    assert types["standard"] == StandardAgent


def test_agent_factory_register_custom_type(minimal_agent_config):
    """Test registering custom agent type."""

    class CustomAgent(BaseAgent):
        """Custom test agent."""

        def _run(self, input_data, context=None, start_time=0.0):
            return AgentResponse(output="custom response")

        def get_capabilities(self):
            return {"type": "custom"}

    # Register custom type
    AgentFactory.register_type("custom", CustomAgent)

    # Verify it's registered
    types = AgentFactory.list_types()
    assert "custom" in types
    assert types["custom"] == CustomAgent

    # Create agent with custom type
    minimal_agent_config.agent.type = "custom"
    agent = AgentFactory.create(minimal_agent_config)

    assert isinstance(agent, CustomAgent)
    assert agent.get_capabilities()["type"] == "custom"


def test_agent_factory_register_duplicate_type():
    """Test registering duplicate type raises error."""

    class AnotherStandardAgent(BaseAgent):
        """Another standard agent."""

        def _run(self, input_data, context=None, start_time=0.0):
            return AgentResponse(output="test")

        def get_capabilities(self):
            return {}

    # Try to register a type that already exists
    with pytest.raises(ValueError, match="already registered"):
        AgentFactory.register_type("standard", AnotherStandardAgent)


def test_agent_factory_register_invalid_class():
    """Test registering non-BaseAgent class raises error."""

    class NotAnAgent:
        """Not an agent class."""
        pass

    with pytest.raises(ValueError, match="must inherit from BaseAgent"):
        AgentFactory.register_type("invalid", NotAnAgent)  # type: ignore


def test_agent_factory_creates_working_agent(minimal_agent_config):
    """Test factory-created agent can execute."""
    from unittest.mock import patch

    with patch('src.agents.base_agent.ToolRegistry'):
        agent = AgentFactory.create(minimal_agent_config)

        # Agent should have all required methods
        assert hasattr(agent, 'execute')
        assert hasattr(agent, 'get_capabilities')
        assert hasattr(agent, 'validate_config')

        # Capabilities should be valid
        capabilities = agent.get_capabilities()
        assert "type" in capabilities
        assert capabilities["type"] == "standard"


class TestAgentFactoryThreadSafety:
    """Thread safety tests for AgentFactory (P1)."""

    def test_concurrent_agent_creation(self, minimal_agent_config):
        """Test that 100+ agents can be created concurrently without errors."""
        import concurrent.futures
        from unittest.mock import patch

        def create_agent(agent_id):
            """Create an agent with unique name."""
            # Create a copy of config with unique name
            config_copy = minimal_agent_config
            config_copy.agent.name = f"agent_{agent_id}"
            return AgentFactory.create(config_copy)

        # Mock ToolRegistry to avoid actual tool initialization
        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # Create 100 agents concurrently
                futures = [
                    executor.submit(create_agent, i)
                    for i in range(100)
                ]

                # Collect results
                results = [f.result() for f in futures]

        # All should be valid StandardAgent instances
        assert len(results) == 100
        assert all(isinstance(agent, StandardAgent) for agent in results)
        assert all(isinstance(agent, BaseAgent) for agent in results)

        # All should have unique names
        names = [agent.name for agent in results]
        assert len(set(names)) == 100, "All agents should have unique names"

    def test_concurrent_agent_creation_200_agents(self, minimal_agent_config):
        """Stress test with 200 concurrent agent creations."""
        import concurrent.futures
        from unittest.mock import patch

        def create_agent():
            return AgentFactory.create(minimal_agent_config)

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(create_agent) for _ in range(200)]
                results = [f.result() for f in futures]

        assert len(results) == 200
        assert all(isinstance(agent, StandardAgent) for agent in results)

    def test_concurrent_registration_and_creation(self, minimal_agent_config):
        """Test concurrent type registration and agent creation."""
        import concurrent.futures
        import threading
        from unittest.mock import patch

        # Create multiple custom agent types
        custom_agents = []
        for i in range(5):
            class CustomAgent(BaseAgent):
                type_id = i  # Store type id as class variable

                def _run(self, input_data, context=None, start_time=0.0):
                    return AgentResponse(output=f"custom_{self.type_id}")

                def get_capabilities(self):
                    return {"type": f"custom_{self.type_id}"}

            custom_agents.append((f"custom_{i}", CustomAgent))

        registration_errors = []
        creation_results = []
        lock = threading.Lock()

        def register_type(type_name, agent_class):
            """Register a custom agent type."""
            try:
                AgentFactory.register_type(type_name, agent_class)
            except ValueError as e:
                # Expected if type already registered
                with lock:
                    registration_errors.append(str(e))

        def create_standard_agent():
            """Create standard agents during registration."""
            try:
                agent = AgentFactory.create(minimal_agent_config)
                with lock:
                    creation_results.append(agent)
            except Exception as e:
                with lock:
                    creation_results.append(e)

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = []

                # Submit registration tasks
                for type_name, agent_class in custom_agents:
                    futures.append(executor.submit(register_type, type_name, agent_class))

                # Simultaneously create standard agents
                for _ in range(20):
                    futures.append(executor.submit(create_standard_agent))

                # Wait for all to complete
                concurrent.futures.wait(futures)

        # All standard agents should have been created successfully
        successful_creations = [r for r in creation_results if isinstance(r, BaseAgent)]
        assert len(successful_creations) == 20

        # All custom types should be registered (some might have duplicate errors)
        types = AgentFactory.list_types()
        for type_name, _ in custom_agents:
            assert type_name in types

    def test_concurrent_creation_no_race_conditions(self, minimal_agent_config):
        """Test that concurrent creation doesn't cause race conditions in initialization."""
        import concurrent.futures
        import time
        from unittest.mock import patch

        created_agents = []
        creation_times = []
        lock = threading.Lock()

        def create_and_track_agent(agent_id):
            """Create agent and track creation time."""
            start = time.time()
            agent = AgentFactory.create(minimal_agent_config)
            elapsed = time.time() - start

            with lock:
                created_agents.append(agent)
                creation_times.append(elapsed)

            return agent

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(create_and_track_agent, i)
                    for i in range(100)
                ]

                # Wait for all
                results = [f.result() for f in futures]

        # All should succeed
        assert len(results) == 100
        assert len(created_agents) == 100
        assert all(isinstance(agent, StandardAgent) for agent in results)

        # Verify timing is reasonable (no extreme outliers indicating deadlocks)
        avg_time = sum(creation_times) / len(creation_times)
        max_time = max(creation_times)

        # Max time shouldn't be more than 100x average (allows for thread scheduling variance)
        # This catches deadlocks but not normal concurrency variance
        assert max_time < avg_time * 100, f"Potential deadlock detected (max: {max_time}s, avg: {avg_time}s)"

        # Also check no agent took more than 1 second (absolute timeout)
        assert max_time < 1.0, f"Agent creation took too long: {max_time}s"

    def test_concurrent_list_types_while_creating(self, minimal_agent_config):
        """Test listing types while agents are being created concurrently."""
        import concurrent.futures
        from unittest.mock import patch

        list_results = []
        creation_results = []
        lock = threading.Lock()

        def list_types():
            """List agent types."""
            types = AgentFactory.list_types()
            with lock:
                list_results.append(types)

        def create_agent():
            """Create an agent."""
            agent = AgentFactory.create(minimal_agent_config)
            with lock:
                creation_results.append(agent)

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = []

                # Mix of list_types and create operations
                for i in range(50):
                    if i % 2 == 0:
                        futures.append(executor.submit(list_types))
                    else:
                        futures.append(executor.submit(create_agent))

                # Wait for all
                concurrent.futures.wait(futures)

        # All list operations should have succeeded
        assert len(list_results) == 25
        assert all(isinstance(types, dict) for types in list_results)
        assert all("standard" in types for types in list_results)

        # All creation operations should have succeeded
        assert len(creation_results) == 25
        assert all(isinstance(agent, BaseAgent) for agent in creation_results)

    def test_concurrent_creation_with_different_configs(self):
        """Test concurrent creation with varying configurations."""
        import concurrent.futures
        from unittest.mock import patch

        from src.compiler.schemas import (
            AgentConfig,
            AgentConfigInner,
            ErrorHandlingConfig,
            InferenceConfig,
            PromptConfig,
        )

        def create_agent_with_config(agent_id):
            """Create agent with unique configuration."""
            config = AgentConfig(
                agent=AgentConfigInner(
                    name=f"agent_{agent_id}",
                    description=f"Test agent {agent_id}",
                    version="1.0",
                    type="standard",
                    prompt=PromptConfig(inline=f"Test prompt {agent_id}"),
                    inference=InferenceConfig(provider="ollama", model="llama2"),
                    tools=[],
                    error_handling=ErrorHandlingConfig(
                        retry_strategy="ExponentialBackoff",
                        fallback="GracefulDegradation",
                    ),
                )
            )
            return AgentFactory.create(config)

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = [
                    executor.submit(create_agent_with_config, i)
                    for i in range(150)
                ]

                results = [f.result() for f in futures]

        # All should succeed
        assert len(results) == 150
        assert all(isinstance(agent, StandardAgent) for agent in results)

        # All should have correct unique names
        names = [agent.name for agent in results]
        assert len(set(names)) == 150

    def test_no_race_condition_in_registry(self, minimal_agent_config):
        """Test that the agent type registry doesn't have race conditions."""
        import concurrent.futures
        import threading
        from unittest.mock import patch

        errors = []
        lock = threading.Lock()

        def create_agents_batch():
            """Create a batch of agents."""
            try:
                for _ in range(10):
                    agent = AgentFactory.create(minimal_agent_config)
                    assert isinstance(agent, StandardAgent)
            except Exception as e:
                with lock:
                    errors.append(e)

        with patch('src.agents.base_agent.ToolRegistry'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # 10 threads, each creating 10 agents = 100 total
                futures = [executor.submit(create_agents_batch) for _ in range(10)]

                # Wait for all
                concurrent.futures.wait(futures)

        # No errors should have occurred
        assert len(errors) == 0, f"Race conditions detected: {errors}"

    def test_concurrent_creation_memory_safety(self, minimal_agent_config):
        """Test that concurrent creation doesn't cause memory issues."""
        import concurrent.futures
        import gc
        from unittest.mock import patch

        def create_and_discard_agent():
            """Create agent and let it be garbage collected."""
            agent = AgentFactory.create(minimal_agent_config)
            # Don't hold reference, let GC clean up
            return agent.name

        with patch('src.agents.base_agent.ToolRegistry'):
            # Create many agents to test memory safety
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(create_and_discard_agent)
                    for _ in range(200)
                ]

                results = [f.result() for f in futures]

        # All should complete
        assert len(results) == 200

        # Force garbage collection
        gc.collect()

        # If we got here without memory errors, test passes
