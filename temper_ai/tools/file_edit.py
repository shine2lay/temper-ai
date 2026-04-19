"""FileEdit tool — exact string replacement in files.

Modeled after Claude Code's Edit tool: find an exact substring
in a file and replace it. The old_string must be unique in the
file (or use replace_all for bulk renames).

This is much more token-efficient than FileWriter for small changes —
the model only sends the changed fragment, not the entire file.
"""

import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class FileEdit(BaseTool):
    """Replace exact text in a file without rewriting the entire file."""

    name = "FileEdit"
    description = (
        "Replace exact text in an existing file. Provide the exact text to find "
        "(old_text) and what to replace it with (new_text). The old_text must match "
        "exactly once in the file, including whitespace and indentation. "
        "Include a few surrounding lines in old_text to make it unique. "
        "Use replace_all=true to replace all occurrences (e.g., renaming a variable)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to edit",
            },
            "old_text": {
                "type": "string",
                "description": "The exact text to find (must be unique in the file)",
            },
            "new_text": {
                "type": "string",
                "description": "The replacement text",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of requiring uniqueness (default: false)",
            },
        },
        "required": ["file_path", "old_text", "new_text"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("file_path", "")
        old_text = params.get("old_text", "")
        new_text = params.get("new_text", "")
        replace_all = params.get("replace_all", False)

        if not file_path:
            return ToolResult(success=False, result="", error="file_path is required")
        if not old_text:
            return ToolResult(success=False, result="", error="old_text is required")
        if old_text == new_text:
            return ToolResult(success=False, result="", error="old_text and new_text are identical")

        from temper_ai.tools._path_utils import validate_file_path
        try:
            path = validate_file_path(file_path, self.config.get("allowed_root"))
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))
        if not path.exists():
            return ToolResult(success=False, result="", error=f"File not found: {file_path}")

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, result="", error=f"Cannot read file: {e}")

        count = content.count(old_text)

        if count == 0:
            return ToolResult(
                success=False, result="",
                error=f"No match found for the specified text in {path.name}",
            )

        if count > 1 and not replace_all:
            return ToolResult(
                success=False, result="",
                error=f"Found {count} matches in {path.name}. Include more surrounding context to make old_text unique, or set replace_all=true.",
            )

        if replace_all:
            new_content = content.replace(old_text, new_text)
            replaced = count
        else:
            new_content = content.replace(old_text, new_text, 1)
            replaced = 1

        try:
            path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, result="", error=f"Cannot write file: {e}")

        return ToolResult(
            success=True,
            result=f"Replaced {replaced} occurrence(s) in {path.name}",
        )
