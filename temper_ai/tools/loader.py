"""Tool loading, configuration, and template resolution utilities.

Used by BaseAgent to load tools from config and resolve Jinja2
template strings in tool configuration values.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from temper_ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def ensure_tools_discovered(registry: ToolRegistry) -> None:
    """No-op.  Tools are now lazily loaded from TOOL_CLASSES.

    Kept for backward compatibility — callers can safely call this
    but it does nothing since ``ToolRegistry.get()`` handles lazy
    instantiation from the static tool map.
    """


def resolve_tool_spec(tool_spec: Any) -> tuple[str, dict[str, Any]]:
    """Resolve a tool spec into (name, config) tuple."""
    if isinstance(tool_spec, str):
        return tool_spec, {}
    tool_config = tool_spec.config if hasattr(tool_spec, "config") else {}
    return tool_spec.name, tool_config


def apply_tool_config(
    tool_instance: Any, tool_name: str, tool_config: dict[str, Any]
) -> None:
    """Apply config dict to a tool instance.

    Creates a new dict instead of mutating in-place to prevent
    cross-agent contamination when tool instances are shared.
    """
    if not tool_config:
        return
    logger.debug("Tool config provided for %s: %s", tool_name, tool_config)
    if hasattr(tool_instance, "config"):
        if isinstance(tool_instance.config, dict):
            tool_instance.config = {**tool_instance.config, **tool_config}
        else:
            tool_instance.config = dict(tool_config)

    # Validate merged config against config_model (if defined)
    if hasattr(tool_instance, "validate_config"):
        result = tool_instance.validate_config()
        if not result.valid:
            logger.warning(
                "Config validation failed for %s: %s",
                tool_name,
                result.error_message,
            )


def _restore_saved_templates(config: dict[str, Any]) -> None:
    """Restore original template strings from the ``_templates`` backup.

    This allows cached agents to re-resolve templates when input_data
    changes between loop iterations.
    """
    saved = config.get("_templates")
    if isinstance(saved, dict):
        for key, orig in saved.items():
            config[key] = orig


def _collect_and_render_templates(
    config: dict[str, Any], input_data: dict[str, Any]
) -> dict[str, str]:
    """Scan config for Jinja2 template strings, render them in-place.

    Returns a mapping of key -> original template for every key whose
    value was actually changed, so callers can store a backup.
    """
    new_templates: dict[str, str] = {}
    for key, value in list(config.items()):
        if key.startswith("_"):
            continue
        if not isinstance(value, str) or "{{" not in value:
            continue
        rendered = _render_template_value(value, input_data)
        if rendered != value:
            new_templates[key] = value
            config[key] = rendered
    return new_templates


def _resolve_single_tool_templates(
    tool: Any,
    input_data: dict[str, Any],
    agent_name: str,
) -> None:
    """Render Jinja2 template strings in a single tool's config.

    Preserves original template strings in ``_templates`` so that
    cached agents can re-resolve templates on subsequent executions
    (e.g. when input_data changes between loop iterations).
    """
    if not hasattr(tool, "config") or not isinstance(tool.config, dict):
        return

    _restore_saved_templates(tool.config)
    new_templates = _collect_and_render_templates(tool.config, input_data)

    if new_templates:
        tool.config["_templates"] = new_templates
        logger.debug(
            "[%s] Resolved tool config templates for %s: %s",
            agent_name,
            getattr(tool, "name", type(tool).__name__),
            {k: v for k, v in tool.config.items() if not k.startswith("_")},
        )

    # Re-validate config after template resolution
    if hasattr(tool, "validate_config"):
        result = tool.validate_config()
        if not result.valid:
            logger.warning(
                "[%s] Config validation failed for %s after template resolution: %s",
                agent_name,
                getattr(tool, "name", type(tool).__name__),
                result.error_message,
            )


def resolve_tool_config_templates(
    registry: Any,
    input_data: dict[str, Any],
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
        _resolve_single_tool_templates(tool, input_data, agent_name)


def _render_template_value(template: str, variables: dict[str, Any]) -> str:
    """Render a single Jinja2 template string with the given variables."""
    result = template
    for match in re.finditer(r"\{\{\s*(\w+)\s*\}\}", template):
        var_name = match.group(1)
        if var_name in variables:
            result = result.replace(match.group(0), str(variables[var_name]))
    return result
