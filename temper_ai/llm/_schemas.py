"""Tool schema building and caching for LLMService.

Builds text-based and native (function-calling) tool definitions,
with content-hash caching to avoid redundant rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from temper_ai.llm.tool_keys import ToolKeys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton tool instances for schema building (shared, read-only)
# ---------------------------------------------------------------------------
_schema_instances: dict[str, Any] = {}
_schema_instances_lock = __import__("threading").Lock()


def _get_schema_instance(name: str) -> Any | None:
    """Get or create a singleton tool instance for schema building.

    These are default-config instances used only for reading name/description/schema.
    """
    if name in _schema_instances:
        return _schema_instances[name]
    with _schema_instances_lock:
        if name in _schema_instances:
            return _schema_instances[name]
        from temper_ai.tools import TOOL_CLASSES

        cls = TOOL_CLASSES.get(name)
        if cls is None:
            return None
        try:
            instance = cls()
            _schema_instances[name] = instance
            return instance
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("Failed to create schema instance for %s: %s", name, e)
            return None


def get_tool_schemas(tool_names: list[str]) -> list[dict[str, Any]]:
    """Build LLM tool schemas from tool names (no per-agent registry needed).

    Uses singleton instances from TOOL_CLASSES to get name, description,
    and parameter schema. MCP tools are not included (they use a separate path).

    Returns:
        List of OpenAI function-calling format tool definitions.
    """
    schemas: list[dict[str, Any]] = []
    for name in tool_names:
        tool = _get_schema_instance(name)
        if tool is None:
            logger.warning("Tool '%s' not found in TOOL_CLASSES, skipping schema", name)
            continue
        schema = tool.get_parameters_schema()
        function_def: dict[str, Any] = {
            ToolKeys.NAME: tool.name,
            "description": tool.description,
            ToolKeys.PARAMETERS: schema,
        }
        result_schema = tool.get_result_schema()
        if result_schema:
            function_def["description"] = (
                f"{tool.description}\n\n"
                f"Result schema: {json.dumps(result_schema, indent=2)}"
            )
        schemas.append({"type": "function", "function": function_def})
    return schemas


def build_text_schemas(
    tools: list[Any] | None,
    cached_schemas: str | None,
    cached_hash: str | None,
) -> tuple[str | None, str | None]:
    """Build text-based tool schemas for LLMs without native tool support.

    Returns (schemas_text, content_hash). Reuses cached value when tool names
    hash matches cached_hash.
    """
    if not tools:
        return None, None

    tools_dict = {t.name: t for t in tools}
    if not tools_dict:
        return None, None

    tool_names_key = ",".join(sorted(tools_dict.keys()))
    current_hash = hashlib.sha256(tool_names_key.encode()).hexdigest()
    if cached_schemas is not None and cached_hash == current_hash:
        return cached_schemas, cached_hash

    tool_schemas = [
        {
            ToolKeys.NAME: tool.name,
            "description": tool.description,
            ToolKeys.PARAMETERS: tool.get_parameters_schema(),
        }
        for tool in tools_dict.values()
    ]
    tools_section = (
        "\n\n## Available Tools\n"
        "You can call tools by writing a tool_call block. "
        "To call a tool, use EXACTLY this format:\n"
        "<tool_call>\n"
        '{"name": "<tool_name>", "parameters": {<parameters>}}\n'
        "</tool_call>\n\n"
        "You may call multiple tools. Wait for tool results before continuing.\n\n"
        + json.dumps(tool_schemas, indent=2)
    )

    return tools_section, current_hash


def build_native_tool_defs(
    tools: list[Any] | None,
    cached_defs: list[dict[str, Any]] | None,
    cached_hash: str | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Build native tool definitions for providers with function calling.

    Native tool definitions are the default for all providers.  Text-based
    fallback is controlled by ``InferenceConfig.use_text_tool_schemas``.

    Returns (native_defs, new_hash). Reuses cached value when tool schemas
    hash matches cached_hash.
    """
    if not tools:
        return None, None

    tools_dict = {t.name: t for t in tools}
    if not tools_dict:
        return None, None

    schema_data = {
        name: tool.get_parameters_schema() for name, tool in sorted(tools_dict.items())
    }
    current_hash = hashlib.sha256(
        json.dumps(schema_data, sort_keys=True).encode()
    ).hexdigest()

    if cached_defs is not None and cached_hash == current_hash:
        return cached_defs, cached_hash

    native_tools: list[dict[str, Any]] = []
    for tool in tools_dict.values():
        schema = tool.get_parameters_schema()
        function_def: dict[str, Any] = {
            ToolKeys.NAME: tool.name,
            "description": tool.description,
            ToolKeys.PARAMETERS: schema,
        }
        result_schema = tool.get_result_schema()
        if result_schema:
            function_def["description"] = (
                f"{tool.description}\n\n"
                f"Result schema: {json.dumps(result_schema, indent=2)}"
            )
        native_tools.append(
            {
                "type": "function",
                "function": function_def,
            }
        )

    result = native_tools if native_tools else None
    return result, current_hash
