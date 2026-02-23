"""Shared agent loading, execution, and response extraction logic.

Consolidates duplicated code from _sequential_helpers.py and
_parallel_helpers.py into a single module, reducing ~100 lines of
duplicate code across the two helper files.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Module-level cache for persistent agents — survives across workflow runs.
_persistent_agent_cache: dict[str, Any] = {}
_persistent_cache_lock = threading.Lock()


def resolve_agent_factory(agent_factory_cls: Any) -> Any:
    """Resolve agent factory class, importing default if None.

    Args:
        agent_factory_cls: Factory class or None for default

    Returns:
        Resolved agent factory class
    """
    if agent_factory_cls is not None:
        return agent_factory_cls
    from temper_ai.agent.utils.agent_factory import AgentFactory as _AgentFactory

    return _AgentFactory


def load_or_cache_agent(
    agent_name: str,
    config_loader: Any,
    agent_cache: dict[str, Any],
    agent_factory: Any,
) -> tuple:
    """Load agent config, create or retrieve cached agent instance.

    Persistent agents (persistent=True) are cached at module level for
    cross-workflow reuse. Non-persistent agents use the per-execution cache.

    Args:
        agent_name: Name of the agent to load
        config_loader: ConfigLoader for loading agent configs
        agent_cache: Dict mapping agent names to cached instances
        agent_factory: Factory class for creating agents

    Returns:
        Tuple of (agent, agent_config, agent_config_dict)
    """
    from temper_ai.storage.schemas.agent_config import AgentConfig

    agent_config_dict = config_loader.load_agent(agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    is_persistent = getattr(agent_config.agent, "persistent", False)

    if is_persistent:
        with _persistent_cache_lock:
            if agent_name in _persistent_agent_cache:
                return (
                    _persistent_agent_cache[agent_name],
                    agent_config,
                    agent_config_dict,
                )
            agent = agent_factory.create(agent_config)
            _persistent_agent_cache[agent_name] = agent
        return agent, agent_config, agent_config_dict

    if agent_name in agent_cache:
        agent = agent_cache[agent_name]
    else:
        agent = agent_factory.create(agent_config)
        agent_cache[agent_name] = agent
    return agent, agent_config, agent_config_dict


def config_to_tracking_dict(
    agent_config: Any,
    agent_config_dict: dict[str, Any],
) -> dict[str, Any]:
    """Convert agent config to a dict suitable for tracking.

    Handles Pydantic model_dump(), legacy dict(), and plain dict fallback.

    Args:
        agent_config: Agent config (Pydantic model or dict)
        agent_config_dict: Fallback raw dict

    Returns:
        Dict representation of the config
    """
    if hasattr(agent_config, "model_dump"):
        result: dict[str, Any] = agent_config.model_dump()
        return result
    if hasattr(agent_config, "dict"):
        result2: dict[str, Any] = agent_config.dict()
        return result2
    return dict(agent_config_dict)


def extract_response_data(response: Any) -> dict[str, Any]:
    """Extract common data fields from an agent response.

    Args:
        response: Agent execution response

    Returns:
        Dict with output, reasoning, confidence, tokens, cost_usd, tool_calls
    """
    return {
        "output": response.output,
        "reasoning": response.reasoning,
        "confidence": response.confidence,
        "tokens": response.tokens,
        "cost_usd": response.estimated_cost_usd,
        "tool_calls": response.tool_calls if response.tool_calls else [],
    }


def extract_response_metrics(response: Any, duration: float) -> dict[str, Any]:
    """Extract common metrics from an agent response.

    Args:
        response: Agent execution response
        duration: Execution duration in seconds

    Returns:
        Dict with tokens, cost_usd, duration_seconds, tool_calls
    """
    return {
        "tokens": response.tokens or 0,
        "cost_usd": response.estimated_cost_usd or 0.0,
        "duration_seconds": duration,
        "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
    }
