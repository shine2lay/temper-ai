"""Grep tool — search file contents, bounded and structured.

Agents previously searched with `Bash("grep -rn …")`, whose output is unbounded:
a pattern that matches a vendored directory or a lock file returns tens of
thousands of lines into the context. This returns `path:line: text` (pi's shape
— compact and unambiguous for a model to act on), capped, with a tail saying how
many matches were left behind so the agent can narrow the pattern rather than
assume it saw everything.
"""

import logging
import re
from pathlib import Path
from typing import Any

from temper_ai.tools._ignore import Ignore
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000
MAX_LINE_CHARS = 300
_MAX_FILE_BYTES = 2_000_000  # skip blobs; a match inside a 50MB file helps nobody


class Grep(BaseTool):
    """Search file contents with a regular expression."""

    name = "Grep"
    description = (
        "Search file contents with a regular expression. Returns 'path:line: text' "
        f"for up to {DEFAULT_LIMIT} matches (raise with limit), then reports how many "
        "were omitted. Skips anything the repo's .gitignore excludes, plus .git, "
        "node_modules, __pycache__, virtualenvs and build output. Prefer this over "
        "running grep through Bash: that output is unbounded."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {
                "type": "string",
                "description": "File or directory to search. Relative paths resolve against the workspace. Default: the workspace.",
            },
            "glob": {
                "type": "string",
                "description": "Only search files matching this glob, e.g. '*.py' or '**/*.ts'.",
            },
            "ignore_case": {"type": "boolean", "description": "Case-insensitive match (default false)."},
            "literal": {
                "type": "boolean",
                "description": "Treat pattern as plain text rather than a regular expression (default false).",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum matches to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Also search files excluded by .gitignore (default false).",
            },
        },
        "required": ["pattern"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        pattern = params.get("pattern", "")
        if not pattern:
            return ToolResult(success=False, result="", error="pattern is required")
        try:
            regex = re.compile(
                re.escape(pattern) if params.get("literal") else pattern,
                re.IGNORECASE if params.get("ignore_case") else 0,
            )
        except re.error as e:
            return ToolResult(
                success=False, result="",
                error=f"Invalid regular expression: {e}. Set literal=true to search for it as plain text.",
            )

        try:
            root = _resolve(params.get("path") or ".", self.config)
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))
        if not root.exists():
            return ToolResult(success=False, result="", error=f"Path not found: {root}")

        limit = min(max(int(params.get("limit") or DEFAULT_LIMIT), 1), MAX_LIMIT)
        glob = params.get("glob")
        ignore = Ignore(root if root.is_dir() else root.parent, use_gitignore=not params.get("include_ignored"))
        files = [root] if root.is_file() else _walk(root, glob, ignore)

        hits: list[str] = []
        omitted = 0
        base = root if root.is_dir() else root.parent
        for f in files:
            try:
                if f.stat().st_size > _MAX_FILE_BYTES:
                    continue
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if not regex.search(line):
                            continue
                        if len(hits) >= limit:
                            omitted += 1
                            continue
                        rel = f.relative_to(base) if f != base else f.name
                        text = line.rstrip("\n")
                        if len(text) > MAX_LINE_CHARS:
                            text = text[:MAX_LINE_CHARS] + " …"
                        hits.append(f"{rel}:{n}: {text}")
            except OSError:
                continue

        if not hits:
            return ToolResult(success=True, result=f"No matches for {pattern!r} in {root}", metadata={"matches": 0})
        body = "\n".join(hits)
        if omitted:
            body += (
                f"\n\n[{limit} of {limit + omitted} matches shown. Narrow the pattern, "
                f"set a glob, or raise limit (max {MAX_LIMIT}).]"
            )
        return ToolResult(success=True, result=body, metadata={"matches": len(hits), "omitted": omitted})


def _walk(root: Path, glob: str | None, ignore: Ignore) -> list[Path]:
    matcher = root.glob(glob) if glob else root.rglob("*")
    return sorted(p for p in matcher if p.is_file() and not ignore.skips(p))


def _resolve(path: str, config: dict[str, Any]) -> Path:
    from temper_ai.tools._path_utils import validate_file_path

    workspace_root = config.get("workspace_root")
    if path == "." and workspace_root:
        path = workspace_root
    elif workspace_root and not path.startswith("/"):
        path = str(Path(workspace_root) / path)
    return validate_file_path(path, config.get("allowed_root"))
