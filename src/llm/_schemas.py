"""Tool schema building and caching for LLMService.

Builds text-based and native (function-calling) tool definitions,
with caching by tool count/hash to avoid redundant rebuilds.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from src.llm.providers import AnthropicLLM, OllamaLLM, OpenAILLM
from src.tools.tool_keys import ToolKeys

logger = logging.getLogger(__name__)


def build_text_schemas(
    tools: Optional[List[Any]],
    cached_schemas: Optional[str],
    cached_version: int,
) -> tuple[Optional[str], int]:
    """Build text-based tool schemas for LLMs without native tool support.

    Returns (schemas_text, new_version). Reuses cached value when tool count
    matches cached_version.
    """
    if not tools:
        return None, 0

    tools_dict = {t.name: t for t in tools}
    if not tools_dict:
        return None, 0

    current_version = len(tools_dict)
    if cached_schemas is not None and cached_version == current_version:
        return cached_schemas, cached_version

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

    return tools_section, current_version


def build_native_tool_defs(
    llm: Any,
    tools: Optional[List[Any]],
    cached_defs: Optional[List[Dict[str, Any]]],
    cached_hash: Optional[str],
) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Build native tool definitions for providers with function calling.

    Returns (native_defs, new_hash). Reuses cached value when tool names
    hash matches cached_hash.
    """
    if not isinstance(llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
        return None, None

    if not tools:
        return None, None

    tools_dict = {t.name: t for t in tools}
    if not tools_dict:
        return None, None

    tool_names_key = ",".join(sorted(tools_dict.keys()))
    current_hash = hashlib.sha256(tool_names_key.encode()).hexdigest()

    if cached_defs is not None and cached_hash == current_hash:
        return cached_defs, cached_hash

    native_tools: List[Dict[str, Any]] = []
    for tool in tools_dict.values():
        schema = tool.get_parameters_schema()
        function_def: Dict[str, Any] = {
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
        native_tools.append({
            "type": "function",
            "function": function_def,
        })

    result = native_tools if native_tools else None
    return result, current_hash
