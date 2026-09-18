"""Read tool — read a file with bounded output.

temper had no file-reading tool: agents were told to shell out (`Bash("cat …")`),
which returns the whole file. One `cat` of a lock file, build log or minified
bundle is ~118k tokens — the entire 120k context window in a single tool result,
and with no prompt caching that cost is paid again on every following iteration.

Behaviour ported from pi's `read`, which solves this well:
- `offset`/`limit` for reading a slice
- a hard cap on lines AND bytes, whichever hits first
- a trailing line that tells the model exactly how to continue

That last part matters most for unattended agents: truncation the model can't
see is a trap, truncation that says "use offset=284 to continue" is a next step.
"""

import logging
from pathlib import Path
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_LINES = 2000
MAX_BYTES = 50_000


class Read(BaseTool):
    """Read a file's contents, truncated to a bounded window."""

    name = "Read"
    description = (
        "Read the contents of a text file. Output is capped at "
        f"{MAX_LINES} lines or {MAX_BYTES // 1000}KB (whichever comes first); when a file is "
        "longer the result ends with the offset to continue from. Use offset/limit "
        "to read a specific range instead of the whole file. Prefer this over "
        "running `cat` through Bash: that returns the entire file and can exhaust "
        "the context in one call."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File to read. Relative paths resolve against the workspace.",
            },
            "offset": {
                "type": "integer",
                "description": "1-indexed line to start from (default 1).",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum lines to return (default {MAX_LINES}).",
            },
        },
        "required": ["path"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path") or params.get("file_path", "")
        if not path:
            return ToolResult(success=False, result="", error="path is required")

        offset = max(int(params.get("offset") or 1), 1)
        limit = int(params.get("limit") or MAX_LINES)
        if limit < 1:
            return ToolResult(success=False, result="", error="limit must be at least 1")

        try:
            resolved = _resolve(path, self.config)
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))

        if not resolved.exists():
            return ToolResult(success=False, result="", error=f"File not found: {resolved}")
        if resolved.is_dir():
            return ToolResult(
                success=False, result="",
                error=f"{resolved} is a directory — use Glob or Grep to look inside it",
            )

        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")

        lines = text.splitlines()
        total = len(lines)
        if offset > total:
            return ToolResult(
                success=False, result="",
                error=f"offset {offset} is past the end of {resolved} ({total} lines)",
            )

        window = lines[offset - 1 : offset - 1 + min(limit, MAX_LINES)]

        # Byte cap: a file can be few-lined and enormous (minified JS, one-line JSON).
        out: list[str] = []
        size = 0
        byte_capped = False
        for line in window:
            encoded = len(line.encode("utf-8")) + 1
            if size + encoded > MAX_BYTES:
                byte_capped = True
                break
            out.append(line)
            size += encoded

        last = offset + len(out) - 1
        body = "\n".join(out)
        if last < total:
            reason = f" ({MAX_BYTES // 1000}.0KB limit)" if byte_capped else ""
            body += (
                f"\n\n[Showing lines {offset}-{last} of {total}{reason}. "
                f"Use offset={last + 1} to continue.]"
            )
        return ToolResult(
            success=True,
            result=body,
            metadata={"path": str(resolved), "lines": total, "shown": len(out), "truncated": last < total},
        )


def _resolve(path: str, config: dict[str, Any]) -> Path:
    """Workspace-relative by default; validated the same way the write tools are."""
    from temper_ai.tools._path_utils import validate_file_path

    workspace_root = config.get("workspace_root")
    if workspace_root and not path.startswith("/"):
        path = str(Path(workspace_root) / path)
    return validate_file_path(path, config.get("allowed_root"))
