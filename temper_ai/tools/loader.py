"""Tool loader — load tool instances from agent config.

Handles both bare tool names ("Bash") and tool objects with config
({name: "FileWriter", config: {allowed_root: "/workspace"}}).
"""

import logging
from typing import Any

from temper_ai.tools.base import BaseTool

logger = logging.getLogger(__name__)


def load_tools(
    tool_specs: list[Any],
    tool_classes: dict[str, type[BaseTool]],
) -> dict[str, BaseTool]:
    """Load tool instances from a list of tool specifications.

    Args:
        tool_specs: List from agent YAML config. Each entry is either:
            - A string: "Bash" (bare tool name, no config)
            - A dict: {"name": "FileWriter", "config": {"allowed_root": "..."}}
        tool_classes: Registry mapping tool names to classes.

    Returns:
        Dict mapping tool name to instantiated tool.
    """
    tools: dict[str, BaseTool] = {}

    for spec in tool_specs:
        name, config = _resolve_spec(spec)

        tool_cls = tool_classes.get(name)
        if tool_cls is None:
            logger.warning("Unknown tool '%s' — skipping. Available: %s", name, sorted(tool_classes))
            continue

        try:
            tool = tool_cls(config=config)
            tools[name] = tool
        except Exception as e:
            logger.warning("Failed to instantiate tool '%s': %s", name, e)

    return tools


def _resolve_spec(spec: Any) -> tuple[str, dict[str, Any]]:
    """Parse a tool spec into (name, config_dict).

    Handles:
        "Bash"                          -> ("Bash", {})
        {"name": "Bash"}                -> ("Bash", {})
        {"name": "Bash", "config": {x}} -> ("Bash", {x})
    """
    if isinstance(spec, str):
        return spec, {}

    if isinstance(spec, dict):
        name = spec.get("name", "")
        config = spec.get("config", {})
        return name, config

    # If spec has .name attribute (Pydantic model, dataclass, etc.)
    if hasattr(spec, "name"):
        name = getattr(spec, "name", "")
        config = getattr(spec, "config", {}) or {}
        if isinstance(config, dict):
            return name, config
        # Config might be a Pydantic model — convert to dict
        if hasattr(config, "model_dump"):
            return name, config.model_dump()
        return name, {}

    logger.warning("Unrecognized tool spec format: %s", type(spec).__name__)
    return "", {}
