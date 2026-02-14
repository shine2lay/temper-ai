"""
Tool schema formatting for PromptEngine.

Provides formatting utilities for LLM function calling tool schemas.
"""
import json
from typing import Any, Dict, List

from src.constants.limits import MULTIPLIER_SMALL


class ToolSchemaFormatter:
    """Formats tool schemas for inclusion in prompts.

    Supports multiple format styles: JSON, list, and markdown table.
    """

    def format_tool_schemas(
        self,
        schemas: List[Dict[str, Any]],
        format_style: str = "json"
    ) -> str:
        """Format tool schemas for inclusion in prompts.

        Args:
            schemas: List of tool schema dictionaries
            format_style: How to format ("json", "list", "markdown")

        Returns:
            Formatted tool schemas string

        Raises:
            ValueError: If format_style is unknown
        """
        if not schemas:
            return "No tools available"

        if format_style == "json":
            return json.dumps(schemas, indent=MULTIPLIER_SMALL)

        if format_style == "list":
            lines = [f"- {s.get('name', 'Unknown')}: {s.get('description', 'No description')}" for s in schemas]
            return "\n".join(lines)

        if format_style == "markdown":
            lines = ["| Tool | Description |", "|------|-------------|"]
            lines.extend(f"| {s.get('name', 'Unknown')} | {s.get('description', 'No description')} |" for s in schemas)
            return "\n".join(lines)

        raise ValueError(f"Unknown format_style: {format_style}")
