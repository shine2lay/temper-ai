"""M9 persistent agent context helpers.

Free functions called by StandardAgent to inject persistent agent context
into prompts. Follows the same pattern as _r0_pipeline_helpers.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DESK_MODE = "desk"
PROJECT_MODE = "project"
MAX_GOAL_CONTEXT_CHARS = 1000
MAX_CROSS_POLLINATION_CHARS = 2000
EXECUTION_MODE_SECTION = "\n\n## Execution Mode\n"
GOALS_SECTION = "\n\n## Active Goals\n"
CROSS_POLLINATION_SECTION = "\n\n## Insights from Other Agents\n"


def detect_execution_mode(context: Dict[str, Any]) -> str:
    """Detect whether agent is running in 'desk' (standalone) or 'project' (workflow) mode.

    Returns 'project' if workflow_id is present in context, else 'desk'.
    """
    if context.get("workflow_id"):
        return PROJECT_MODE
    return DESK_MODE


def inject_execution_mode_context(template: str, mode: str) -> str:
    """Append execution mode section to prompt template."""
    if mode == PROJECT_MODE:
        return template + EXECUTION_MODE_SECTION + (
            "You are executing as part of a workflow pipeline. "
            "Focus on your assigned stage objectives."
        )
    return template + EXECUTION_MODE_SECTION + (
        "You are in direct conversation mode. "
        "Draw on your persistent memory and past experiences."
    )


def inject_project_goal_context(
    template: str,
    agent_id: str,
    goal_service: Any,
    max_chars: int = MAX_GOAL_CONTEXT_CHARS,
) -> str:
    """Append active goals section to prompt template."""
    try:
        context_str = goal_service.format_goals_context(agent_id, max_chars=max_chars)
        if context_str:
            return template + GOALS_SECTION + context_str
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError):
        logger.debug("Failed to inject goal context", exc_info=True)
    return template


def inject_cross_pollination_context(
    template: str,
    config: Any,
    memory_service: Any,
    query: str,
    max_chars: int = MAX_CROSS_POLLINATION_CHARS,
) -> str:
    """Append cross-pollination insights from subscribed agents."""
    if not config or not getattr(config, "enabled", False):
        return template

    subscribe_to = getattr(config, "subscribe_to", [])
    if not subscribe_to:
        return template

    try:
        from temper_ai.memory.cross_pollination import (
            format_cross_pollination_context,
            retrieve_subscribed_knowledge,
        )

        results = retrieve_subscribed_knowledge(
            subscribe_to=subscribe_to,
            query=query,
            memory_service=memory_service,
            retrieval_k=getattr(config, "retrieval_k", 5),
            relevance_threshold=getattr(config, "relevance_threshold", 0.7),
        )
        formatted = format_cross_pollination_context(results, max_chars=max_chars)
        if formatted:
            return template + CROSS_POLLINATION_SECTION + formatted
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError):
        logger.debug("Failed to inject cross-pollination context", exc_info=True)
    return template


def sync_workflow_learnings_to_agent(
    agent_id: str,
    agent_name: str,
    workflow_name: str,
    memory_service: Any,
) -> Dict[str, Any]:
    """Sync workflow learnings to a persistent agent's memory namespace.

    Called by the autonomy orchestrator post-workflow for each persistent agent.
    Returns dict with sync stats.
    """
    try:
        from temper_ai.memory.cross_pollination import publish_knowledge

        content = f"Completed workflow '{workflow_name}' execution."
        entry_id = publish_knowledge(
            agent_name=agent_name,
            content=content,
            memory_service=memory_service,
            metadata={"workflow_name": workflow_name, "agent_id": agent_id},
        )
        return {"synced": True, "entry_id": entry_id}
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError) as exc:
        logger.warning("Failed to sync learnings for agent %s: %s", agent_name, exc)
        return {"synced": False, "error": str(exc)}
