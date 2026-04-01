"""FileWriter tool — write content to files with path safety.

Security:
- Path traversal protection (no .., no symlink escape)
- Forbidden paths (/etc, /sys, /proc, etc.)
- Configurable allowed_root constraint
- Content size limit (10MB)
- Overwrite protection (opt-in)
"""

import logging
from pathlib import Path
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_MAX_CONTENT_SIZE = 10_485_760  # 10MB

_FORBIDDEN_PREFIXES = (
    "/etc", "/sys", "/proc", "/dev", "/boot", "/sbin",
    "/usr/sbin", "/var/run", "/var/lock",
)


class FileWriter(BaseTool):
    """Write content to files with path traversal protection and size limits."""

    name = "FileWriter"
    description = "Write content to a file. Creates parent directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Whether to overwrite if file exists (default true)",
            },
        },
        "required": ["file_path", "content"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        # Normalize LLM parameter aliases
        file_path = params.get("file_path") or params.get("path", "")
        content = params.get("content") or params.get("contents", "")
        overwrite = params.get("overwrite", True)

        if not file_path:
            return ToolResult(success=False, result="", error="file_path is required")

        # Content size check
        if len(content) > _MAX_CONTENT_SIZE:
            return ToolResult(
                success=False, result="",
                error=f"Content too large: {len(content)} bytes (max {_MAX_CONTENT_SIZE})",
            )

        # Resolve and validate path
        try:
            resolved = _validate_path(file_path, self.config.get("allowed_root"))
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))

        # Overwrite check
        if resolved.exists() and not overwrite:
            return ToolResult(
                success=False, result="",
                error=f"File already exists: {resolved} (set overwrite=true to replace)",
            )

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                result=str(resolved),
                metadata={"bytes_written": len(content.encode("utf-8"))},
            )
        except Exception as e:
            return ToolResult(
                success=False, result="",
                error=f"{type(e).__name__}: {e}",
            )


def _validate_path(file_path: str, allowed_root: str | None) -> Path:
    """Validate and resolve a file path. Raises ValueError on violations."""
    # Null byte check
    if "\x00" in file_path:
        raise ValueError("Path contains null byte")

    resolved = Path(file_path).resolve()

    # Forbidden system paths
    resolved_str = str(resolved)
    for prefix in _FORBIDDEN_PREFIXES:
        if resolved_str.startswith(prefix):
            raise ValueError(f"Writing to {prefix} is forbidden")

    # Allowed root constraint
    if allowed_root:
        root = Path(allowed_root).resolve()
        if not resolved_str.startswith(str(root)):
            raise ValueError(
                f"Path '{resolved}' is outside allowed root '{root}'"
            )

    return resolved
