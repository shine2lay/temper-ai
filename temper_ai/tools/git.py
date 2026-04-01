"""Git tool — workspace-scoped git operations.

Provides a structured interface for common git commands.
All operations are scoped to the workspace directory.
"""

import logging
import subprocess
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_SIZE = 128_000

# Git subcommands that are safe to execute
_ALLOWED_SUBCOMMANDS = {
    "status", "diff", "log", "show", "blame",
    "add", "commit", "checkout", "branch",
    "pull", "push", "fetch", "merge", "rebase",
    "stash", "tag", "remote", "rev-parse",
    "ls-files", "ls-tree",
}

# Subcommands that should never be used
_BLOCKED_SUBCOMMANDS = {
    "filter-branch", "reflog", "fsck", "gc",
}


class Git(BaseTool):
    """Execute git commands within the workspace."""

    name = "git"
    description = "Run git commands in the workspace (status, diff, add, commit, push, etc.)"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Git subcommand and arguments (e.g., 'status', 'diff --staged', 'add .')",
            },
        },
        "required": ["command"],
    }
    modifies_state = True

    def __init__(self, workspace: str | None = None, timeout: int = _DEFAULT_TIMEOUT):
        self.workspace = workspace
        self.timeout = timeout

    def execute(self, command: str, **kwargs: Any) -> ToolResult:
        """Execute a git command.

        Args:
            command: Git subcommand and args (e.g., "status", "diff --staged")
        """
        parts = command.strip().split()
        if not parts:
            return ToolResult(success=False, result="", error="Empty git command")

        subcommand = parts[0]

        # Block dangerous subcommands
        if subcommand in _BLOCKED_SUBCOMMANDS:
            return ToolResult(
                success=False, result="",
                error=f"Git subcommand '{subcommand}' is not allowed",
            )

        # Block --force on push
        if subcommand == "push" and ("--force" in parts or "-f" in parts):
            return ToolResult(
                success=False, result="",
                error="Force push is not allowed",
            )

        full_command = ["git"] + parts

        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.workspace,
            )

            output = result.stdout
            if result.stderr:
                output += f"\n{result.stderr}" if output else result.stderr

            # Truncate large output
            if len(output) > _MAX_OUTPUT_SIZE:
                output = output[:_MAX_OUTPUT_SIZE] + f"\n... [truncated, {len(output)} chars total]"

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    result=output,
                    error=f"git {subcommand} failed with exit code {result.returncode}",
                )

            return ToolResult(success=True, result=output)

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, result="",
                error=f"git {subcommand} timed out after {self.timeout}s",
            )
        except FileNotFoundError:
            return ToolResult(
                success=False, result="",
                error="git is not installed or not in PATH",
            )
        except Exception as e:
            return ToolResult(
                success=False, result="",
                error=f"git {subcommand} error: {e}",
            )
