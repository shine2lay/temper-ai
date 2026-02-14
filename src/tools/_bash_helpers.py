"""Helper functions extracted from Bash tool to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.tools.base import ToolResult
from src.tools.constants import MAX_BASH_OUTPUT_LENGTH
from src.tools.field_names import ToolResultFields

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shell mode validation
# ---------------------------------------------------------------------------

def _check_shell_metacharacters(command: str, allowed_commands: Set[str]) -> Optional[ToolResult]:
    """Check for dangerous shell metacharacters. Returns error or None."""
    import re as _re

    # SECURITY: Reject command substitution
    if '`' in command or '$(' in command:
        return ToolResult(
            success=False,
            error=(
                "Command substitution ($() and backticks) is not allowed. "
                f"Allowed commands: {sorted(allowed_commands)}"
            ),
        )

    # SECURITY: Block heredoc syntax
    if '<<' in command:
        return ToolResult(
            success=False,
            error=(
                "Heredoc syntax (<<) is not allowed in shell mode. "
                "Use echo or printf with redirection instead."
            ),
        )

    # SECURITY: Block brace expansion
    if '{' in command or '}' in command:
        return ToolResult(
            success=False,
            error=(
                "Brace expansion ({, }) is not allowed in shell mode. "
                "List files explicitly instead."
            ),
        )

    # H-20: Block glob patterns
    if '*' in command or '?' in command or '[' in command:
        return ToolResult(
            success=False,
            error=(
                "Glob patterns (*, ?, []) are not allowed in shell mode. "
                "List files explicitly instead."
            ),
        )

    # SECURITY: Block process substitution
    if '<(' in command or '>(' in command:
        return ToolResult(
            success=False,
            error=(
                "Process substitution (<() and >()) is not allowed. "
                f"Allowed commands: {sorted(allowed_commands)}"
            ),
        )

    # SECURITY: Block stderr redirection
    if _re.search(r'(?:^|[^<>])(?:2>|&>)', command):
        return ToolResult(
            success=False,
            error=(
                "Stderr redirection (2>, &>) is not allowed in shell mode. "
                "Use stdout redirection only."
            ),
        )

    return None


def _validate_command_allowlist(
    sub_commands: List[str],
    allowed_commands: Set[str],
) -> Optional[ToolResult]:
    """Validate each sub-command against allowlist. Returns error or None."""
    for sub_cmd in sub_commands:
        sub_cmd = sub_cmd.strip()
        if not sub_cmd:
            continue
        try:
            shell_parts = shlex.split(sub_cmd)
        except ValueError:
            return ToolResult(
                success=False,
                error=(
                    f"Could not parse command: '{sub_cmd}'. "
                    "Ensure commands are properly quoted."
                ),
            )
        if not shell_parts:
            continue
        cmd_name = shell_parts[0]
        if '/' in cmd_name:
            return ToolResult(
                success=False,
                error=(
                    f"Command must be a bare name, not a path: '{cmd_name}'. "
                    f"Allowed commands: {sorted(allowed_commands)}"
                ),
            )
        if cmd_name not in allowed_commands:
            return ToolResult(
                success=False,
                error=(
                    f"Command '{cmd_name}' is not in the allowed list. "
                    f"Allowed commands: {sorted(allowed_commands)}"
                ),
            )
    return None


def _validate_path_arguments(
    sub_commands: List[str],
    workspace_root: Path,
) -> Optional[ToolResult]:
    """Validate path arguments against sandbox. Returns error or None."""
    for sub_cmd in sub_commands:
        sub_cmd = sub_cmd.strip()
        if not sub_cmd:
            continue
        try:
            shell_parts = shlex.split(sub_cmd)
        except ValueError:
            continue  # Already validated in allowlist check
        for arg in shell_parts[1:]:
            if arg.startswith("-"):
                continue
            if arg in (">", ">>", "<"):
                continue
            arg_path = (
                Path(arg).resolve() if Path(arg).is_absolute()
                else (workspace_root / arg).resolve()
            )
            try:
                arg_path.relative_to(workspace_root.resolve())
            except ValueError:
                return ToolResult(
                    success=False,
                    error=(
                        f"Path argument '{arg}' resolves outside the sandbox. "
                        f"All paths must stay within '{workspace_root}'."
                    ),
                )
    return None


def validate_shell_mode_command(
    command: str,
    allowed_commands: Set[str],
    workspace_root: Path,
) -> Optional[ToolResult]:
    """Validate command in shell mode. Returns ToolResult on error, None if valid.

    Also returns None and sets parts=None in the caller to signal shell=True.
    """
    from src.tools.bash import _split_shell_commands

    # Check for dangerous shell metacharacters
    error_result = _check_shell_metacharacters(command, allowed_commands)
    if error_result is not None:
        return error_result

    # Split and validate each sub-command
    sub_commands = _split_shell_commands(command)

    # Validate against allowlist
    error_result = _validate_command_allowlist(sub_commands, allowed_commands)
    if error_result is not None:
        return error_result

    # Validate path arguments against sandbox
    error_result = _validate_path_arguments(sub_commands, workspace_root)
    if error_result is not None:
        return error_result

    return None  # Valid


# ---------------------------------------------------------------------------
# Strict mode validation
# ---------------------------------------------------------------------------

def validate_strict_mode_command(
    command: str,
    allowed_commands: Set[str],
    dangerous_chars: Set[str],
) -> tuple[Optional[List[str]], Optional[ToolResult]]:
    """Validate command in strict mode.

    Returns (parts, None) on success, (None, ToolResult) on error.
    """
    # Check for shell metacharacters
    for char in dangerous_chars:
        if char in command:
            return None, ToolResult(
                success=False,
                error=(
                    f"Command contains forbidden character '{repr(char)}'. "
                    "Shell metacharacters are not allowed for security."
                ),
            )

    # Parse command into parts
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return None, ToolResult(
            success=False,
            error=f"Invalid command syntax: {e}",
        )

    if not parts:
        return None, ToolResult(
            success=False,
            error="Command is empty after parsing",
        )

    # Check allowlist
    cmd_name = parts[0]
    if "/" in cmd_name or "\\" in cmd_name:
        return None, ToolResult(
            success=False,
            error=(
                f"Command must be a bare name, not a path: '{cmd_name}'. "
                f"Allowed commands: {sorted(allowed_commands)}"
            ),
        )
    if cmd_name not in allowed_commands:
        return None, ToolResult(
            success=False,
            error=(
                f"Command '{cmd_name}' is not in the allowed list. "
                f"Allowed commands: {sorted(allowed_commands)}"
            ),
        )

    return parts, None


# ---------------------------------------------------------------------------
# Sandbox validation
# ---------------------------------------------------------------------------

def _ensure_workspace_exists(workspace_root: Path) -> Optional[ToolResult]:
    """Ensure workspace root exists. Returns error or None."""
    if not workspace_root.exists():
        try:
            workspace_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(
                success=False,
                error=f"Cannot create workspace directory: {e}",
            )
    return None


def _check_path_in_sandbox(
    path: Path,
    workspace_root: Path,
    path_description: str,
) -> Optional[ToolResult]:
    """Check if path is within sandbox. Returns error or None."""
    try:
        path.relative_to(workspace_root.resolve())
    except ValueError:
        return ToolResult(
            success=False,
            error=(
                f"{path_description} '{path}' resolves outside the sandbox. "
                f"Must be within '{workspace_root}'."
            ),
        )
    return None


def _validate_command_arguments(
    parts: List[str],
    resolved_cwd: Path,
    resolved_workspace: Path,
    workspace_root: Path,
) -> Optional[ToolResult]:
    """Validate command arguments for path traversal. Returns error or None."""
    for arg in parts[1:]:
        if arg.startswith("-"):
            continue
        arg_path = (resolved_cwd / arg).resolve() if not Path(arg).is_absolute() else Path(arg).resolve()
        error_result = _check_path_in_sandbox(
            arg_path, resolved_workspace, "Path argument"
        )
        if error_result is not None:
            return error_result
    return None


def validate_sandbox(
    workspace_root: Path,
    working_directory: Optional[str],
    parts: Optional[List[str]],
) -> tuple[Optional[Path], Optional[ToolResult]]:
    """Validate working directory and path arguments against sandbox.

    Returns (resolved_cwd, None) on success, (None, ToolResult) on error.
    """
    cwd = Path(working_directory).resolve() if working_directory else workspace_root

    # Ensure workspace root exists
    error_result = _ensure_workspace_exists(workspace_root)
    if error_result is not None:
        return None, error_result

    # Resolve paths
    resolved_workspace = workspace_root.resolve()
    resolved_cwd = cwd.resolve() if cwd != workspace_root else resolved_workspace

    # Check working directory is in sandbox
    error_result = _check_path_in_sandbox(resolved_cwd, resolved_workspace, "Working directory")
    if error_result is not None:
        return None, error_result

    # Check command arguments for path traversal (strict mode only)
    if parts is not None:
        error_result = _validate_command_arguments(parts, resolved_cwd, resolved_workspace, workspace_root)
        if error_result is not None:
            return None, error_result

    # Create working directory if it doesn't exist
    if not resolved_cwd.exists():
        try:
            resolved_cwd.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return None, ToolResult(
                success=False,
                error=f"Cannot create working directory: {e}",
            )

    return resolved_cwd, None


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

def _truncate_output(output: str) -> str:
    """Truncate output if it exceeds max length."""
    if len(output) > MAX_BASH_OUTPUT_LENGTH:
        return output[:MAX_BASH_OUTPUT_LENGTH] + "\n... [output truncated]"
    return output


def _build_success_result(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    resolved_cwd: Path,
    timeout: int,
) -> ToolResult:
    """Build ToolResult for successful command execution."""
    success = exit_code == 0
    return ToolResult(
        success=success,
        result=stdout if success else f"Command failed (exit {exit_code}):\n{stderr}\n{stdout}",
        error=stderr if not success and stderr else None,
        metadata={
            ToolResultFields.EXIT_CODE: exit_code,
            ToolResultFields.STDOUT: stdout,
            ToolResultFields.STDERR: stderr,
            ToolResultFields.COMMAND: command,
            "working_directory": str(resolved_cwd),
            ToolResultFields.TIMEOUT: timeout,
        },
    )


def run_command(
    command: str,
    parts: Optional[List[str]],
    resolved_cwd: Path,
    timeout: int,
    shell_mode: bool,
    safe_env: Dict[str, str],
) -> ToolResult:
    """Execute a validated command via subprocess."""
    try:
        use_shell = shell_mode
        cmd_arg: str | List[str] = command if use_shell else (parts or [])
        result = subprocess.run(  # noqa: S603 — bash tool requires subprocess  # nosec B602
            cmd_arg,
            cwd=str(resolved_cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=use_shell,  # noqa: S602  # nosec B602
            env=safe_env,
        )

        # Truncate output if needed
        stdout = _truncate_output(result.stdout or "")
        stderr = _truncate_output(result.stderr or "")

        return _build_success_result(
            stdout, stderr, result.returncode, command, resolved_cwd, timeout
        )

    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error=f"Command timed out after {timeout} seconds",
            metadata={
                ToolResultFields.COMMAND: command,
                "working_directory": str(resolved_cwd),
                ToolResultFields.TIMEOUT: timeout,
            },
        )

    except FileNotFoundError:
        cmd_display = command.split()[0] if use_shell else (parts[0] if parts else "unknown")
        return ToolResult(
            success=False,
            error=f"Command not found: {cmd_display}",
            metadata={ToolResultFields.COMMAND: command},
        )

    except PermissionError:
        cmd_display = command.split()[0] if use_shell else (parts[0] if parts else "unknown")
        return ToolResult(
            success=False,
            error=f"Permission denied executing: {cmd_display}",
            metadata={ToolResultFields.COMMAND: command},
        )

    except OSError as e:
        logger.error(f"OS error executing command: {e}", exc_info=True)
        return ToolResult(
            success=False,
            error="OS error executing command",
            metadata={ToolResultFields.COMMAND: command},
        )


def get_safe_env(safe_env_vars: Set[str]) -> Dict[str, str]:
    """Build a safe environment for subprocess execution."""
    env = {}
    for key in safe_env_vars:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env
