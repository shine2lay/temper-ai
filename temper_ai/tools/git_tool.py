"""
Git tool for running safe, read-friendly Git operations in a repository.

Security: Blocked destructive flags, path validation, no shell=True.
"""

import logging
import os
import subprocess
from typing import Any

from pydantic import BaseModel, Field

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.git_tool_constants import (
    GIT_ALLOWED_OPERATIONS,
    GIT_BLOCKED_FLAGS,
    GIT_DEFAULT_TIMEOUT,
    GIT_MAX_DIFF_SIZE,
)

logger = logging.getLogger(__name__)


def _validate_operation(operation: str) -> str | None:
    """Return error string if operation is not allowed, else None."""
    if operation not in GIT_ALLOWED_OPERATIONS:
        return f"Operation '{operation}' is not allowed. Allowed: {sorted(GIT_ALLOWED_OPERATIONS)}"
    return None


def _validate_args(args: list[str]) -> str | None:
    """Return error string if any arg contains a blocked flag, else None."""
    for arg in args:
        if arg in GIT_BLOCKED_FLAGS:
            return f"Argument '{arg}' is blocked for safety reasons"
    return None


def _validate_repo_path(repo_path: str) -> str | None:
    """Return error string if repo_path does not exist or is not a directory, else None."""
    if not os.path.exists(repo_path):
        return f"Repository path does not exist: '{repo_path}'"
    if not os.path.isdir(repo_path):
        return f"Repository path is not a directory: '{repo_path}'"
    return None


def _truncate_diff(output: str, operation: str) -> tuple[str, bool]:
    """Truncate output for diff operations. Returns (output, was_truncated)."""
    if operation in {"diff", "show", "log"} and len(output) > GIT_MAX_DIFF_SIZE:
        return output[:GIT_MAX_DIFF_SIZE], True
    return output, False


class GitToolParams(BaseModel):
    """Parameters for the Git tool."""

    operation: str = Field(
        description="Git operation (e.g., status, diff, log, commit, branch)",
    )
    repo_path: str = Field(
        default=".",
        description="Path to the git repository (default: current directory)",
    )
    args: list[str] | None = Field(
        default=None,
        description="Additional arguments to pass to the git command",
    )


class GitTool(BaseTool):
    """
    Git tool for running safe Git operations in a local repository.

    Security features:
    - Allowlist of permitted operations
    - Blocklist of destructive flags (--force, --hard, --delete, etc.)
    - Repository path existence check
    - No shell=True — subprocess with explicit arg list
    - Output truncated for large diffs/logs
    """

    params_model = GitToolParams

    def get_metadata(self) -> ToolMetadata:
        """Return Git tool metadata."""
        return ToolMetadata(
            name="Git",
            description=(
                "Runs Git operations (status, diff, log, commit, branch, etc.) "
                "in a local repository. Blocks destructive flags for safety."
            ),
            version="1.0",
            category="vcs",
            requires_network=True,
            requires_credentials=False,
            modifies_state=True,
        )

    def _run_git_subprocess(
        self, cmd: list[str], operation: str, repo_path: str
    ) -> ToolResult:
        """Run the git command and return a ToolResult."""
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=GIT_DEFAULT_TIMEOUT,
                shell=False,
            )
            stdout, truncated = _truncate_diff(proc.stdout, operation)
            stderr = proc.stderr.strip()
            success = proc.returncode == 0
            error_msg: str | None = (
                (stderr or f"git {operation} exited with code {proc.returncode}")
                if not success
                else None
            )
            return ToolResult(
                success=success,
                result={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": proc.returncode,
                },
                error=error_msg,
                metadata={
                    "operation": operation,
                    "repo_path": repo_path,
                    "output_truncated": truncated,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"git {operation} timed out after {GIT_DEFAULT_TIMEOUT} seconds",
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return ToolResult(success=False, error=f"Failed to run git: {exc}")

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute a git operation.

        Args:
            operation: Git subcommand to run
            repo_path: Path to the repository (default: ".")
            args: Extra arguments for the git command

        Returns:
            ToolResult with stdout output
        """
        operation = kwargs.get("operation", "")
        repo_path = str(kwargs.get("repo_path", "."))
        args: list[str] = list(kwargs.get("args") or [])

        op_error = _validate_operation(operation)
        if op_error:
            return ToolResult(success=False, error=op_error)

        args_error = _validate_args(args)
        if args_error:
            return ToolResult(success=False, error=args_error)

        path_error = _validate_repo_path(repo_path)
        if path_error:
            return ToolResult(success=False, error=path_error)

        return self._run_git_subprocess(
            ["git", "-C", repo_path, operation] + args, operation, repo_path
        )
