"""Agent factory for creating agents from configuration.

The AgentFactory enables configuration-driven agent creation by mapping
the 'type' field in agent config to concrete agent implementations.

This supports the "radical modularity" vision by allowing multiple agent types
(standard, debate, human, custom) to be used interchangeably.
"""
import threading
from typing import Dict, Type

from src.agents.base_agent import BaseAgent
from src.agents.standard_agent import StandardAgent
from src.compiler.schemas import AgentConfig


class AgentFactory:
    """Factory for creating agents from configuration.

    Maps agent type strings to implementation classes and provides a unified
    create() method for instantiation.

    Supported types:
    - "standard": StandardAgent with LLM + tool execution loop
    - More types can be added in M3+ (debate, human, custom, etc.)
    """

    _lock = threading.Lock()

    # Map of agent type strings to implementation classes
    _agent_types: Dict[str, Type[BaseAgent]] = {
        "standard": StandardAgent,
        # Future types:
        # "debate": DebateAgent,
        # "human": HumanAgent,
        # "custom": CustomAgent,
    }

    @classmethod
    def create(cls, config: AgentConfig) -> BaseAgent:
        """Create agent from configuration.

        Args:
            config: Agent configuration schema

        Returns:
            Initialized agent instance of the appropriate type

        Raises:
            ValueError: If agent type is unknown or config is invalid

        Example:
            >>> config = AgentConfig(...)
            >>> agent = AgentFactory.create(config)
            >>> response = agent.execute({"query": "..."})
        """
        # Get agent type from config (defaults to "standard")
        agent_type = getattr(config.agent, "type", "standard")

        with cls._lock:
            if agent_type not in cls._agent_types:
                raise ValueError(
                    f"Unknown agent type: '{agent_type}'. "
                    f"Supported types: {list(cls._agent_types.keys())}"
                )
            agent_class = cls._agent_types[agent_type]

        return agent_class(config)

    @classmethod
    def register_type(cls, type_name: str, agent_class: Type[BaseAgent]) -> None:
        """Register a custom agent type.

        Allows plugins and extensions to register new agent types at runtime.

        Args:
            type_name: Name for the agent type (used in config)
            agent_class: Agent class that inherits from BaseAgent

        Raises:
            ValueError: If type_name already registered or agent_class invalid

        Example:
            >>> class MyCustomAgent(BaseAgent):
            ...     pass
            >>> AgentFactory.register_type("my_custom", MyCustomAgent)
        """
        if not issubclass(agent_class, BaseAgent):
            raise ValueError(
                f"Agent class must inherit from BaseAgent, got {agent_class.__name__}"
            )

        with cls._lock:
            if type_name in cls._agent_types:
                raise ValueError(f"Agent type '{type_name}' is already registered")
            cls._agent_types[type_name] = agent_class

    @classmethod
    def list_types(cls) -> Dict[str, Type[BaseAgent]]:
        """List all registered agent types.

        Returns:
            Dict mapping type names to agent classes
        """
        with cls._lock:
            return cls._agent_types.copy()

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset agent types to defaults for testing."""
        with cls._lock:
            cls._agent_types = {
                "standard": StandardAgent,
            }
