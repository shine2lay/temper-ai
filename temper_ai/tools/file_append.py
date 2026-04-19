"""FileAppend tool — append text to a file without rewriting it."""

from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult


class FileAppend(BaseTool):
    """Append text to the end of an existing file."""

    name = "FileAppend"
    description = (
        "Append text to the end of a file. The file must already exist. "
        "Use this instead of FileWriter when you want to add a new section "
        "to an existing file without rewriting it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to append to",
            },
            "content": {
                "type": "string",
                "description": "Text to append at the end of the file",
            },
        },
        "required": ["file_path", "content"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("file_path", "")
        content = params.get("content", "")

        if not file_path:
            return ToolResult(success=False, result="", error="file_path is required")
        if not content:
            return ToolResult(success=False, result="", error="content is required")

        from temper_ai.tools._path_utils import validate_file_path
        try:
            path = validate_file_path(file_path, self.config.get("allowed_root"))
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))
        if not path.exists():
            return ToolResult(success=False, result="", error=f"File not found: {file_path}")

        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, result=f"Appended to {path.name}")
        except Exception as e:
            return ToolResult(success=False, result="", error=f"Cannot append: {e}")
