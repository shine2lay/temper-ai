"""Agent factory for creating agents from configuration.

The AgentFactory enables configuration-driven agent creation by mapping
the 'type' field in agent config to concrete agent implementations.

This supports the "radical modularity" vision by allowing multiple agent types
(standard, debate, human, custom) to be used interchangeably.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from temper_ai.agent.base_agent import BaseAgent
from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.agent.standard_agent import StandardAgent
from temper_ai.agent.static_checker_agent import StaticCheckerAgent
from temper_ai.agent.utils.constants import (
    AGENT_TYPE_SCRIPT,
    AGENT_TYPE_STANDARD,
    AGENT_TYPE_STATIC_CHECKER,
)

if TYPE_CHECKING:
    from temper_ai.storage.schemas import AgentConfig


class AgentFactory:
    """Factory for creating agents from configuration.

    Maps agent type strings to implementation classes and provides a unified
    create() method for instantiation.

    Built-in types:
    - "standard": StandardAgent with LLM + tool execution loop
    - "script": ScriptAgent for zero-LLM bash script execution
    - "static_checker": StaticCheckerAgent for command-based checks

    Custom types can be registered via register_type().
    """

    _lock = threading.Lock()

    # Map of agent type strings to implementation classes
    _agent_types: dict[str, type[BaseAgent]] = {
        AGENT_TYPE_STANDARD: StandardAgent,
        AGENT_TYPE_SCRIPT: ScriptAgent,
        AGENT_TYPE_STATIC_CHECKER: StaticCheckerAgent,
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
        agent_type = getattr(config.agent, "type", AGENT_TYPE_STANDARD)

        with cls._lock:
            if agent_type not in cls._agent_types:
                # Try plugin registry before raising
                from temper_ai.plugins.registry import ensure_plugin_registered

                if not ensure_plugin_registered(agent_type):
                    raise ValueError(
                        f"Unknown agent type: '{agent_type}'. "
                        f"Supported types: {list(cls._agent_types.keys())}"
                    )
            agent_class = cls._agent_types[agent_type]

        return agent_class(config)

    @classmethod
    def register_type(cls, type_name: str, agent_class: type[BaseAgent]) -> None:
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
    def list_types(cls) -> dict[str, type[BaseAgent]]:
        """List all registered agent types.

        Returns:
            Dict mapping type names to agent classes
        """
        with cls._lock:
            return cls._agent_types.copy()

    @staticmethod
    def get_interface(
        agent_name: str,
        config_loader: Any,
    ) -> dict[str, Any]:
        """Extract agent I/O interface from config without instantiation.

        Loads the agent config and extracts input/output declarations.
        No LLM connection, tool registry, or infrastructure needed.

        Useful for compile-time validation and future orchestrator discovery.

        Args:
            agent_name: Agent name or config path.
            config_loader: ConfigLoader with ``load_agent()`` method.

        Returns:
            Dict with keys: name, description, inputs, outputs.
        """
        from temper_ai.storage.schemas.agent_config import AgentIODeclaration

        config_dict = config_loader.load_agent(agent_name)
        agent_inner = config_dict.get("agent", config_dict)

        raw_inputs = agent_inner.get("inputs") or {}
        raw_outputs = agent_inner.get("outputs") or {}

        inputs: dict[str, AgentIODeclaration] = {}
        for name, decl in raw_inputs.items():
            if isinstance(decl, dict):
                inputs[name] = AgentIODeclaration(**decl)
            elif isinstance(decl, AgentIODeclaration):
                inputs[name] = decl

        outputs: dict[str, AgentIODeclaration] = {}
        for name, decl in raw_outputs.items():
            if isinstance(decl, dict):
                outputs[name] = AgentIODeclaration(**decl)
            elif isinstance(decl, AgentIODeclaration):
                outputs[name] = decl

        return {
            "name": agent_inner.get("name", agent_name),
            "description": agent_inner.get("description", ""),
            "inputs": inputs,
            "outputs": outputs,
        }

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset agent types to defaults for testing."""
        with cls._lock:
            cls._agent_types = {
                AGENT_TYPE_STANDARD: StandardAgent,
                AGENT_TYPE_SCRIPT: ScriptAgent,
                AGENT_TYPE_STATIC_CHECKER: StaticCheckerAgent,
            }
