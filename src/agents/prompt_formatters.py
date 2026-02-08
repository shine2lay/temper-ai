"""
Tool schema formatting for PromptEngine.

Provides formatting utilities for LLM function calling tool schemas.
"""
import json
from typing import Any, Dict, List


class ToolSchemaFormatter:
    """Formats tool schemas for inclusion in prompts.

    Supports multiple format styles: JSON, list, and markdown table.
    """

    def format_tool_schemas(
        self,
        schemas: List[Dict[str, Any]],
        format_style: str = "json"
    ) -> str:
        """
        Format tool schemas for inclusion in prompts.

        Args:
            schemas: List of tool schema dictionaries
            format_style: How to format ("json", "list", "markdown")

        Returns:
            Formatted tool schemas string

        Raises:
            ValueError: If format_style is unknown

        Examples:
            >>> formatter = ToolSchemaFormatter()
            >>> tools = [{"name": "calc", "description": "Calculator"}]
            >>> formatter.format_tool_schemas(tools, "list")
            '- calc: Calculator'
        """
        if not schemas:
            return "No tools available"

        if format_style == "json":
            # Pretty JSON format
            return json.dumps(schemas, indent=2)

        elif format_style == "list":
            # Simple list format: "- name: description"
            lines = []
            for schema in schemas:
                name = schema.get("name", "Unknown")
                desc = schema.get("description", "No description")
                lines.append(f"- {name}: {desc}")
            return "\n".join(lines)

        elif format_style == "markdown":
            # Markdown table format
            lines = ["| Tool | Description |", "|------|-------------|"]
            for schema in schemas:
                name = schema.get("name", "Unknown")
                desc = schema.get("description", "No description")
                lines.append(f"| {name} | {desc} |")
            return "\n".join(lines)

        else:
            raise ValueError(f"Unknown format_style: {format_style}")
