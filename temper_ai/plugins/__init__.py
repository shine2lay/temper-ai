"""Universal agent ingestion plugin system for Temper AI.

Provides adapters for external agent frameworks (CrewAI, LangGraph,
OpenAI Agents SDK, AutoGen) that run inside Temper AI workflows.

Install framework extras:
    pip install 'temper-ai[crewai]'
    pip install 'temper-ai[openai_agents]'
    pip install 'temper-ai[autogen]'
"""

from temper_ai.plugins._schemas import PluginConfig  # noqa: F401
from temper_ai.plugins.constants import (  # noqa: F401
    ALL_PLUGIN_TYPES,
    PLUGIN_TYPE_AUTOGEN,
    PLUGIN_TYPE_CREWAI,
    PLUGIN_TYPE_LANGGRAPH,
    PLUGIN_TYPE_OPENAI_AGENTS,
)


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import plugin classes on first access."""
    if name == "ExternalAgentPlugin":
        from temper_ai.plugins.base import ExternalAgentPlugin

        return ExternalAgentPlugin
    if name == "ensure_plugin_registered":
        from temper_ai.plugins.registry import ensure_plugin_registered

        return ensure_plugin_registered
    if name == "list_plugins":
        from temper_ai.plugins.registry import list_plugins

        return list_plugins
    raise AttributeError(f"module 'temper_ai.plugins' has no attribute {name!r}")
