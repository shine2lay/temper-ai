"""Agent execution infrastructure.

Provides the agent base class, standard agent implementation,
agent factory, and prompt engine.

LLM providers are available via ``temper_ai.llm.providers``.

Imports are lazy to avoid circular dependency:
  temper_ai.llm.providers.base -> temper_ai.agent.utils.constants
  -> temper_ai.agent.__init__ -> temper_ai.agent.base_agent
  -> temper_ai.llm.providers.factory -> temper_ai.llm.providers.base (circular)
"""

from typing import Any

_LAZY_IMPORTS = {
    "AgentFactory": "temper_ai.agent.utils.agent_factory",
    "AgentResponse": "temper_ai.agent.models.response",
    "ToolCallRecord": "temper_ai.agent.models.response",
    "BaseAgent": "temper_ai.agent.base_agent",
    "ExecutionContext": "temper_ai.agent.base_agent",
    "StandardAgent": "temper_ai.agent.standard_agent",
    "PromptEngine": "temper_ai.llm.prompts.engine",
    "PromptRenderError": "temper_ai.llm.prompts.engine",
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
