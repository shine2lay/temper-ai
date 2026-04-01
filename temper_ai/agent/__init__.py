"""Agent creation and type registry.

Usage:
    from temper_ai.agent import create_agent
    agent = create_agent(config)

To register a custom agent type:
    from temper_ai.agent import register_agent_type
    register_agent_type("api", APIAgent)
"""

from temper_ai.agent.base import AgentABC
from temper_ai.agent.llm_agent import LLMAgent
from temper_ai.agent.script_agent import ScriptAgent

AGENT_TYPES: dict[str, type[AgentABC]] = {
    "llm": LLMAgent,
    "script": ScriptAgent,
}


def create_agent(config: dict) -> AgentABC:
    """Create an agent from YAML config.

    Agent type determined by config["type"] (default: "llm").
    """
    agent_type = config.get("type", "llm")
    if agent_type not in AGENT_TYPES:
        raise ValueError(
            f"Unknown agent type: '{agent_type}'. "
            f"Available: {list(AGENT_TYPES.keys())}"
        )
    return AGENT_TYPES[agent_type](config)


def register_agent_type(name: str, agent_class: type[AgentABC]):
    """Register a custom agent type."""
    AGENT_TYPES[name] = agent_class


__all__ = [
    "AgentABC",
    "LLMAgent",
    "ScriptAgent",
    "AGENT_TYPES",
    "create_agent",
    "register_agent_type",
]
