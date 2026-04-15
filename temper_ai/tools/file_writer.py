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
            "description": {
                "type": "string",
                "description": "Brief one-line description of what this file contains/does. Will be embedded as metadata in the file header.",
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
        description = params.get("description", "")
        overwrite = params.get("overwrite", True)

        # Inject description as file header if provided
        if description:
            content = _inject_description(file_path, content, description)

        if not file_path:
            return ToolResult(success=False, result="", error="file_path is required")

        # Resolve relative paths against workspace_root
        workspace_root = self.config.get("workspace_root")
        if workspace_root and not file_path.startswith("/"):
            file_path = str(Path(workspace_root) / file_path)

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


def _inject_description(file_path: str, content: str, description: str) -> str:
    """Inject a description header into file content based on file type."""
    ext = Path(file_path).suffix.lower()
    desc = description.strip().replace("\n", " ")

    # Markdown: YAML frontmatter
    if ext in (".md", ".mdx"):
        if content.startswith("---"):
            # Already has frontmatter — inject description into it
            end = content.index("---", 3)
            frontmatter = content[3:end]
            if "description:" not in frontmatter:
                frontmatter = f"description: {desc}\n{frontmatter}"
            return f"---\n{frontmatter}---{content[end + 3:]}"
        return f"---\ndescription: {desc}\n---\n\n{content}"

    # TypeScript / JavaScript: JSDoc header
    if ext in (".ts", ".tsx", ".js", ".jsx"):
        if content.startswith("/**"):
            return content  # already has a doc comment, don't duplicate
        return f"/** @description {desc} */\n{content}"

    # Python: module docstring
    if ext == ".py":
        if content.startswith('"""') or content.startswith("'"):
            return content
        return f'"""{desc}"""\n{content}'

    # YAML: comment header
    if ext in (".yaml", ".yml"):
        return f"# @description {desc}\n{content}"

    # JSON: can't add comments, skip
    if ext == ".json":
        return content

    # Default: comment header
    return f"# @description {desc}\n{content}"


def _validate_path(file_path: str, allowed_root: str | None) -> Path:
    """Validate and resolve a file path. Raises ValueError on violations."""
    from temper_ai.tools._path_utils import validate_file_path
    return validate_file_path(file_path, allowed_root)
