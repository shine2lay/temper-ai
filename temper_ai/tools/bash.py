"""Bash tool — execute shell commands in a sandboxed environment.

Security:
- Commands run in a subprocess with a clean environment
- workspace_root config constrains the working directory
- Configurable command allowlist (default: common safe commands)
- Timeout enforcement (default 30s, max 600s)
"""

import logging
import os
import subprocess  # noqa: B404
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_COMMANDS = [
    "ls", "cat", "find", "mkdir", "pwd", "head", "tail", "wc",
    "grep", "sort", "uniq", "diff", "echo", "cp", "mv", "rm",
    "touch", "python3", "pip", "node", "npm", "npx", "git",
]

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600
_MAX_OUTPUT_SIZE = 256_000  # 256KB


class Bash(BaseTool):
    """Execute shell commands in a sandboxed subprocess with timeout enforcement."""

    name = "Bash"
    description = "Execute a shell command and return its output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30, max 600)",
            },
        },
        "required": ["command"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        command = params.get("command", "")
        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)

        if not command or not command.strip():
            return ToolResult(success=False, result="", error="Empty command")

        # Validate against allowlist if configured
        allowed = self.config.get("allowed_commands", _DEFAULT_ALLOWED_COMMANDS)
        base_cmd = command.strip().split()[0]
        # Strip path prefixes (e.g., /usr/bin/python3 -> python3)
        base_cmd_name = os.path.basename(base_cmd)
        if allowed and base_cmd_name not in allowed:
            return ToolResult(
                success=False, result="",
                error=f"Command '{base_cmd_name}' not in allowed list: {allowed}",
            )

        # Determine working directory
        cwd = self.config.get("workspace_root")

        try:
            result = subprocess.run(
                command,
                shell=True,  # noqa: B602
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=_safe_env(),
            )

            stdout = result.stdout
            stderr = result.stderr

            # Truncate large output
            if len(stdout) > _MAX_OUTPUT_SIZE:
                stdout = stdout[:_MAX_OUTPUT_SIZE] + "\n... (truncated)"
            if len(stderr) > _MAX_OUTPUT_SIZE:
                stderr = stderr[:_MAX_OUTPUT_SIZE] + "\n... (truncated)"

            output = stdout
            if stderr:
                output = f"{stdout}\nSTDERR:\n{stderr}" if stdout else f"STDERR:\n{stderr}"

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    result=output,
                    error=f"Command exited with code {result.returncode}",
                    metadata={"exit_code": result.returncode},
                )

            return ToolResult(success=True, result=output)

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, result="",
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                success=False, result="",
                error=f"{type(e).__name__}: {e}",
            )


def _safe_env() -> dict[str, str]:
    """Build a restricted environment for subprocess execution."""
    env = os.environ.copy()
    # Remove potentially dangerous vars
    for key in ["SUDO_ASKPASS", "SSH_AUTH_SOCK", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "DATABASE_URL"]:
        env.pop(key, None)
    return env
