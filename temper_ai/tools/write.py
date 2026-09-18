"""Write tool — create or overwrite a file, or append to one.

Replaces FileWriter and FileAppend. Appending was never a separate capability,
only a mode, and two tools for one job cost a slot in every agent's tool list
and an occasional wrong choice.

Dropped from FileWriter on purpose: the `description` parameter, which injected
a comment/frontmatter header into the content. A write tool that silently edits
what you asked it to write is a surprise, and agents that want a header can put
one in `content`.
"""

import logging
from pathlib import Path
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_CONTENT_SIZE = 10_485_760  # 10MB


class Write(BaseTool):
    """Write content to a file, creating parent directories as needed."""

    name = "Write"
    description = (
        "Write content to a file, creating parent directories as needed. Overwrites "
        "by default; set append=true to add to the end instead. To change part of an "
        "existing file use Edit, which does not require rewriting the whole file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File to write. Relative paths resolve against the workspace.",
            },
            "content": {"type": "string", "description": "Content to write."},
            "append": {
                "type": "boolean",
                "description": "Append to the file instead of replacing it (default false).",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Allow replacing an existing file (default true). Ignored when append=true.",
            },
        },
        "required": ["path", "content"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path") or params.get("file_path", "")
        content = params.get("content")
        if content is None:
            content = params.get("contents", "")
        append = bool(params.get("append", False))
        overwrite = params.get("overwrite", True)

        if not path:
            return ToolResult(success=False, result="", error="path is required")
        if len(content) > MAX_CONTENT_SIZE:
            return ToolResult(
                success=False, result="",
                error=f"Content too large: {len(content)} bytes (max {MAX_CONTENT_SIZE})",
            )

        try:
            resolved = _resolve(path, self.config)
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))

        if resolved.exists() and not append and not overwrite:
            return ToolResult(
                success=False, result="",
                error=f"File already exists: {resolved} (set overwrite=true to replace)",
            )

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with resolved.open("a" if append else "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as e:
            return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")

        written = len(content.encode("utf-8"))
        verb = "Appended to" if append else "Wrote"
        return ToolResult(
            success=True,
            result=f"{verb} {resolved} ({written} bytes)",
            metadata={"path": str(resolved), "bytes_written": written, "append": append},
        )


def _resolve(path: str, config: dict[str, Any]) -> Path:
    from temper_ai.tools._path_utils import validate_file_path

    workspace_root = config.get("workspace_root")
    if workspace_root and not path.startswith("/"):
        path = str(Path(workspace_root) / path)
    return validate_file_path(path, config.get("allowed_root"))
