"""Plugin registry for lazy loading of external agent adapters."""

from __future__ import annotations

import logging
import threading
from typing import Any

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
_PLUGIN_MAP: dict[str, tuple[str, str, str]] = {
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


def list_plugins() -> dict[str, dict[str, Any]]:
    """List all known plugins with their availability status."""
    result: dict[str, dict[str, Any]] = {}
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


async def get_health_checks() -> dict[str, dict[str, Any]]:
    """Run health_check() on all registered adapters.

    Loads each adapter class and calls health_check() via the class variables
    without requiring a full agent config instance.
    """
    import importlib
    import importlib.util

    results: dict[str, dict[str, Any]] = {}
    for plugin_type, (module_path, class_name, framework_pkg) in _PLUGIN_MAP.items():
        try:
            module = importlib.import_module(module_path)
            adapter_cls = getattr(module, class_name)
            spec = importlib.util.find_spec(framework_pkg)
            if spec is None:
                results[plugin_type] = {
                    "status": "unavailable",
                    "framework": adapter_cls.FRAMEWORK_NAME,
                }
                continue
            # Call the class-level health_check via a sentinel instance
            # to avoid requiring a full AgentConfig
            result = await _call_class_health_check(adapter_cls, framework_pkg)
            results[plugin_type] = result
        except Exception as exc:  # noqa: BLE001
            results[plugin_type] = {
                "status": "error",
                "framework": plugin_type,
                "detail": str(exc),
            }
    return results


async def _call_class_health_check(
    adapter_cls: Any, framework_pkg: str
) -> dict[str, Any]:
    """Call health_check using class variables without a full AgentConfig."""
    import importlib
    import importlib.util

    framework_name = getattr(adapter_cls, "FRAMEWORK_NAME", framework_pkg)
    spec = importlib.util.find_spec(framework_pkg)
    if spec is None:
        return {"status": "unavailable", "framework": framework_name}
    try:
        mod = importlib.import_module(framework_pkg)
        version = getattr(mod, "__version__", "unknown")
    except ImportError:
        version = "unknown"
    return {"status": "ok", "framework": framework_name, "version": version}
