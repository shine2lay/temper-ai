"""Glob tool — find files by name pattern, bounded.

The counterpart to Grep (contents) and Read (one file): "what files are here?"
without `Bash("find …")`, whose output is unbounded and whose flags models get
wrong. Results are newest-first, because when an agent asks what exists it is
almost always looking for what it or a previous node just produced.

Named Glob rather than pi's `find`: the input is a glob pattern, and a tool
called `find` invites find(1) syntax (`-name`, `-type f`, `-exec`) — especially
next to a Bash tool that has the real find(1). It is also what Claude Code calls
it, so a prompt works unchanged under either provider.
"""

import logging
from pathlib import Path
from typing import Any

from temper_ai.tools._ignore import Ignore
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


class Glob(BaseTool):
    """List files matching a glob pattern."""

    name = "Glob"
    description = (
        "Find files by name pattern, e.g. '**/*.py' or 'src/**/test_*.ts'. Returns "
        f"up to {DEFAULT_LIMIT} paths (raise with limit), newest first. Skips anything "
        "the repo's .gitignore excludes, plus .git, node_modules, __pycache__, "
        "virtualenvs and build output. Use Grep to search file contents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."},
            "path": {
                "type": "string",
                "description": "Directory to search in. Relative paths resolve against the workspace. Default: the workspace.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum paths to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Also return files excluded by .gitignore (default false).",
            },
        },
        "required": ["pattern"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        pattern = params.get("pattern", "")
        if not pattern:
            return ToolResult(success=False, result="", error="pattern is required")
        if pattern.startswith("/"):
            return ToolResult(
                success=False, result="",
                error="pattern must be relative; pass a directory in 'path' instead",
            )

        try:
            root = _resolve(params.get("path") or ".", self.config)
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))
        if not root.is_dir():
            return ToolResult(success=False, result="", error=f"Not a directory: {root}")

        limit = min(max(int(params.get("limit") or DEFAULT_LIMIT), 1), MAX_LIMIT)
        ignore = Ignore(root, use_gitignore=not params.get("include_ignored"))

        found: list[tuple[float, Path]] = []
        try:
            for p in root.glob(pattern):
                if not p.is_file() or ignore.skips(p):
                    continue
                try:
                    found.append((p.stat().st_mtime, p))
                except OSError:
                    continue
        except (ValueError, OSError) as e:
            return ToolResult(success=False, result="", error=f"Invalid pattern {pattern!r}: {e}")

        if not found:
            return ToolResult(success=True, result=f"No files match {pattern!r} under {root}", metadata={"count": 0})

        found.sort(key=lambda t: t[0], reverse=True)
        shown = found[:limit]
        body = "\n".join(str(p.relative_to(root)) for _, p in shown)
        if len(found) > limit:
            body += (
                f"\n\n[{limit} of {len(found)} matches shown, newest first. "
                f"Narrow the pattern or raise limit (max {MAX_LIMIT}).]"
            )
        return ToolResult(success=True, result=body, metadata={"count": len(found), "shown": len(shown)})


def _resolve(path: str, config: dict[str, Any]) -> Path:
    from temper_ai.tools._path_utils import validate_file_path

    workspace_root = config.get("workspace_root")
    if path == "." and workspace_root:
        path = workspace_root
    elif workspace_root and not path.startswith("/"):
        path = str(Path(workspace_root) / path)
    return validate_file_path(path, config.get("allowed_root"))
