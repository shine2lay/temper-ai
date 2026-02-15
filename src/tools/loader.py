"""Tool loading, configuration, and template resolution utilities.

Used by BaseAgent to load tools from config and resolve Jinja2
template strings in tool configuration values.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def ensure_tools_discovered(registry: ToolRegistry) -> None:
    """Auto-discover tools if registry is empty."""
    if len(registry.list_tools()) == 0:
        discovered_count = registry.auto_discover()
        if discovered_count == 0:
            logger.warning(
                "No tools discovered via auto-discovery. "
                "Check that src/tools/ contains valid BaseTool subclasses."
            )


def resolve_tool_spec(tool_spec: Any) -> tuple[str, Dict[str, Any]]:
    """Resolve a tool spec into (name, config) tuple."""
    if isinstance(tool_spec, str):
        return tool_spec, {}
    tool_config = tool_spec.config if hasattr(tool_spec, 'config') else {}
    return tool_spec.name, tool_config


def apply_tool_config(tool_instance: Any, tool_name: str, tool_config: Dict[str, Any]) -> None:
    """Apply config dict to a tool instance."""
    if not tool_config:
        return
    logger.debug("Tool config provided for %s: %s", tool_name, tool_config)
    if hasattr(tool_instance, 'config'):
        if isinstance(tool_instance.config, dict):
            tool_instance.config.update(tool_config)
        else:
            tool_instance.config = tool_config


def resolve_tool_config_templates(
    registry: Any,
    input_data: Dict[str, Any],
    agent_name: str = "unknown",
) -> None:
    """Render Jinja2 template strings in tool config values using input_data."""
    if registry is None:
        return
    try:
        tools_dict = registry.get_all_tools()
    except (AttributeError, TypeError):
        return
    if not tools_dict:
        return

    for tool in tools_dict.values():
        if not hasattr(tool, "config") or not isinstance(tool.config, dict):
            continue
        changed = False
        for key, value in tool.config.items():
            if isinstance(value, str) and "{{" in value:
                rendered = _render_template_value(value, input_data)
                if rendered != value:
                    tool.config[key] = rendered
                    changed = True
        if changed:
            logger.debug(
                "[%s] Resolved tool config templates for %s: %s",
                agent_name,
                getattr(tool, "name", type(tool).__name__),
                {k: v for k, v in tool.config.items() if not k.startswith("_")},
            )


def _render_template_value(template: str, variables: Dict[str, Any]) -> str:
    """Render a single Jinja2 template string with the given variables."""
    result = template
    for match in re.finditer(r"\{\{\s*(\w+)\s*\}\}", template):
        var_name = match.group(1)
        if var_name in variables:
            result = result.replace(match.group(0), str(variables[var_name]))
    return result
