"""Plugin registry for lazy loading of external agent adapters."""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Tuple

from temper_ai.plugins.constants import (
    ALL_PLUGIN_TYPES,
    PLUGIN_TYPE_AUTOGEN,
    PLUGIN_TYPE_CREWAI,
    PLUGIN_TYPE_LANGGRAPH,
    PLUGIN_TYPE_OPENAI_AGENTS,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Maps plugin type → (module_path, class_name, framework_package)
_PLUGIN_MAP: Dict[str, Tuple[str, str, str]] = {
    PLUGIN_TYPE_CREWAI: (
        "temper_ai.plugins.adapters.crewai_adapter",
        "CrewAIAgent",
        "crewai",
    ),
    PLUGIN_TYPE_LANGGRAPH: (
        "temper_ai.plugins.adapters.langgraph_adapter",
        "LangGraphAgent",
        "langgraph",
    ),
    PLUGIN_TYPE_OPENAI_AGENTS: (
        "temper_ai.plugins.adapters.openai_agents_adapter",
        "OpenAIAgentsAgent",
        "agents",
    ),
    PLUGIN_TYPE_AUTOGEN: (
        "temper_ai.plugins.adapters.autogen_adapter",
        "AutoGenAgent",
        "autogen_agentchat",
    ),
}


def is_plugin_type(agent_type: str) -> bool:
    """Check if an agent type is a known plugin type."""
    return agent_type in ALL_PLUGIN_TYPES


def ensure_plugin_registered(agent_type: str) -> bool:
    """Lazily import and register a plugin adapter with AgentFactory.

    Returns True if successfully registered, False otherwise.
    Thread-safe via module-level lock.
    """
    if agent_type not in _PLUGIN_MAP:
        return False

    with _lock:
        # Lazy import to avoid circular dependency
        from temper_ai.agent.utils.agent_factory import AgentFactory

        # Already registered (race condition check)
        if agent_type in AgentFactory.list_types():
            return True

        module_path, class_name, _pkg = _PLUGIN_MAP[agent_type]
        try:
            import importlib
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
            AgentFactory.register_type(agent_type, agent_class)
            logger.info("Registered plugin adapter: %s", agent_type)
            return True
        except ImportError:
            logger.warning(
                "Plugin '%s' requires package not installed. "
                "Install with: pip install 'temper-ai[%s]'",
                agent_type,
                agent_type,
            )
            return False
        except (AttributeError, ValueError) as exc:
            logger.warning("Failed to register plugin '%s': %s", agent_type, exc)
            return False


def list_plugins() -> Dict[str, Dict[str, Any]]:
    """List all known plugins with their availability status."""
    result: Dict[str, Dict[str, Any]] = {}
    for plugin_type, (module_path, class_name, framework_pkg) in _PLUGIN_MAP.items():
        available = _check_framework_available(framework_pkg)
        result[plugin_type] = {
            "module": module_path,
            "class": class_name,
            "available": available,
            "install_hint": f"pip install 'temper-ai[{plugin_type}]'",
        }
    return result


def _check_framework_available(framework_package: str) -> bool:
    """Check if a framework's top-level package can be imported."""
    try:
        import importlib
        importlib.import_module(framework_package)
        return True
    except ImportError:
        return False
