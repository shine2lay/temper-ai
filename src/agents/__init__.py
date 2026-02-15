"""Agent execution infrastructure.

Provides the agent base class, standard agent implementation,
agent factory, and prompt engine.

LLM providers are available via ``src.llm.providers``.

Imports are lazy to avoid circular dependency:
  src.llm.providers.base -> src.agents.utils.constants
  -> src.agents.__init__ -> src.agents.base_agent
  -> src.llm.providers.factory -> src.llm.providers.base (circular)
"""
from typing import Any

_LAZY_IMPORTS = {
    "AgentFactory": "src.agents.utils.agent_factory",
    "AgentResponse": "src.agents.models.response",
    "ToolCallRecord": "src.agents.models.response",
    "BaseAgent": "src.agents.base_agent",
    "ExecutionContext": "src.agents.base_agent",
    "StandardAgent": "src.agents.standard_agent",
    "PromptEngine": "src.prompts.engine",
    "PromptRenderError": "src.prompts.engine",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is not None:
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Agent classes
    "BaseAgent",
    "AgentResponse",
    "ExecutionContext",
    "StandardAgent",
    "AgentFactory",

    # Prompt engine
    "PromptEngine",
    "PromptRenderError",
]
