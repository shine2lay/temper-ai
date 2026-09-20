"""Edit tool — exact-string replacement, several edits per call.

Replaces FileEdit. The one behaviour worth porting from pi is `edits[]`: N
disjoint replacements applied in a single call, all-or-nothing. temper's
previous tool took one replacement per call, so a three-line change across a
file cost three round-trips — and with no prompt caching on the anthropic
provider, each round-trip resends the entire transcript. This is the cheapest
token saving available in the tool layer.

All-or-nothing matters as much as the batching: a half-applied set of edits
leaves the file in a state neither the agent nor the next node expects, and
the agent cannot tell which half landed.

Uniqueness is kept from both tools: `old_text` must match exactly once, unless
`replace_all` is set. The error names the count so the model knows to add
surrounding context rather than guess.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_STRAY_CLOSING_BRACE = re.compile(r"\}\s*\}\s*\]\s*$")


class Edit(BaseTool):
    """Replace exact strings in a file; several replacements in one call."""

    name = "Edit"
    description = (
        "Edit a file by exact string replacement. Pass several disjoint edits in "
        "one call — they are applied together or not at all. Each old_text must "
        "appear exactly once (include surrounding lines to make it unique) unless "
        "replace_all is set. Use Write to create a file or replace it wholesale."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File to edit. Relative paths resolve against the workspace.",
            },
            "edits": {
                "type": "array",
                "description": "Replacements to apply together, in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {"type": "string", "description": "Exact text to find."},
                        "new_text": {"type": "string", "description": "Replacement text."},
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace every occurrence instead of requiring exactly one (default false).",
                        },
                    },
                    "required": ["old_text", "new_text"],
                },
            },
        },
        "required": ["path", "edits"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path") or params.get("file_path", "")
        if not path:
            return ToolResult(success=False, result="", error="path is required")

        edits = params.get("edits")
        if edits is None and params.get("old_text") is not None:
            # Single-edit form, as the previous FileEdit took it.
            edits = [{
                "old_text": params.get("old_text", ""),
                "new_text": params.get("new_text", ""),
                "replace_all": params.get("replace_all", False),
            }]
        if isinstance(edits, str):
            # claude-haiku-4-5 sends the array JSON-encoded in a string in most
            # calls (11 of 12 in one run, each refused, each a lost iteration).
            # The intent is unambiguous, so take it. When it does, the string
            # often ends `}}]` -- one stray brace before the `]` (3 of 3 string
            # calls in the next run). No array of flat {old_text, new_text}
            # objects can legitimately end that way, so drop the brace, but
            # only if the strict parse failed and the repaired text parses.
            try:
                edits = json.loads(edits)
            except ValueError:
                try:
                    edits = json.loads(_STRAY_CLOSING_BRACE.sub("}]", edits))
                except ValueError:
                    return ToolResult(
                        success=False, result="",
                        error="edits must be an array of {old_text, new_text} objects (got a string that is not JSON)",
                    )
        if not isinstance(edits, list) or not edits:
            return ToolResult(success=False, result="", error="edits must be a non-empty array")

        try:
            resolved = _resolve(path, self.config)
        except ValueError as e:
            return ToolResult(success=False, result="", error=str(e))
        if not resolved.exists():
            return ToolResult(success=False, result="", error=f"File not found: {resolved}")

        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")

        # Apply to a copy: any failure leaves the file untouched.
        updated = content
        applied = 0
        for i, edit in enumerate(edits, 1):
            if not isinstance(edit, dict):
                return ToolResult(success=False, result="", error=f"edits[{i}] must be an object")
            old = edit.get("old_text", "")
            new = edit.get("new_text", "")
            if not old:
                return ToolResult(success=False, result="", error=f"edits[{i}]: old_text is required")
            if old == new:
                return ToolResult(success=False, result="", error=f"edits[{i}]: old_text and new_text are identical")

            count = updated.count(old)
            if count == 0:
                return ToolResult(
                    success=False, result="",
                    error=(
                        f"edits[{i}]: text not found in {resolved}. Nothing was changed. "
                        "It must match exactly, including whitespace and indentation "
                        "(read the file first if unsure)."
                    ),
                )
            if count > 1 and not edit.get("replace_all"):
                return ToolResult(
                    success=False, result="",
                    error=(
                        f"edits[{i}]: found {count} occurrences in {resolved}. Nothing was changed. "
                        "Include surrounding lines to make old_text unique, or set replace_all=true."
                    ),
                )
            updated = updated.replace(old, new)
            applied += count if edit.get("replace_all") else 1

        try:
            resolved.write_text(updated, encoding="utf-8")
        except OSError as e:
            return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")

        return ToolResult(
            success=True,
            result=f"Applied {len(edits)} edit(s) ({applied} replacement(s)) to {resolved}",
            metadata={"path": str(resolved), "edits": len(edits), "replacements": applied},
        )


def _resolve(path: str, config: dict[str, Any]) -> Path:
    from temper_ai.tools._path_utils import validate_file_path

    workspace_root = config.get("workspace_root")
    if workspace_root and not path.startswith("/"):
        path = str(Path(workspace_root) / path)
    return validate_file_path(path, config.get("allowed_root"))
