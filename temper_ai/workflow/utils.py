"""Shared utility functions for the compiler module.

This module provides common helper functions used across multiple compiler components
to reduce code duplication and improve maintainability.
"""

from typing import Any


def extract_agent_name(agent_ref: Any) -> str:
    """Extract agent name from various agent reference formats.

    Handles different ways agents can be referenced:
    - String: "analyzer"
    - Dict: {"name": "analyzer"} or {"agent_name": "analyzer"}
    - Pydantic model: agent.name or agent.agent_name

    Args:
        agent_ref: Agent reference (dict, str, or Pydantic model)

    Returns:
        Agent name as string

    Examples:
        >>> extract_agent_name("analyzer")
        'analyzer'
        >>> extract_agent_name({"name": "analyzer"})
        'analyzer'
        >>> extract_agent_name({"agent_name": "analyzer"})
        'analyzer'

    Note:
        This is a shared utility to avoid code duplication across:
        - node_builder.py
        - executors/sequential.py
        - executors/parallel.py
    """
    if isinstance(agent_ref, str):
        return agent_ref
    elif isinstance(agent_ref, dict):
        return agent_ref.get("name") or agent_ref.get("agent_name") or str(agent_ref)
    else:
        # Pydantic model or object with attributes
        return (
            getattr(agent_ref, "name", None)
            or getattr(agent_ref, "agent_name", None)
            or str(agent_ref)
        )
