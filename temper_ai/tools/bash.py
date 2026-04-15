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
    # File operations
    "ls", "cat", "find", "mkdir", "pwd", "head", "tail", "wc",
    "grep", "sort", "uniq", "diff", "echo", "cp", "mv", "rm",
    "touch", "chmod", "tee",
    # Shell built-ins (used in scripts)
    "set", "export", "source", "cd", "test", "[", "true", "false",
    "read", "printf", "local", "return", "exit",
    # Text processing
    "sed", "awk", "tr", "cut", "xargs",
    # Path utilities
    "basename", "dirname", "realpath", "readlink", "which",
    # Shell built-ins / safe utilities
    "cd", "test", "true", "false", "sleep", "date", "whoami", "env",
    # Dev tools
    "python3", "pip", "node", "npm", "npx", "git", "curl",
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

        # Check commands against the allowlist
        # Script agents pass _skip_allowlist=True since their scripts are author-defined, not LLM-generated
        skip_allowlist = params.get("_skip_allowlist", False)
        allowed = self.config.get("allowed_commands", _DEFAULT_ALLOWED_COMMANDS)
        if allowed and not skip_allowlist:
            for line in command.strip().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Handle chained commands: &&, ||, ;, |
                for segment in line.replace("&&", ";").replace("||", ";").replace("|", ";").split(";"):
                    segment = segment.strip()
                    if not segment:
                        continue
                    first_word = segment.split()[0]
                    # Skip variable assignments (VAR=value, VAR="value")
                    if "=" in first_word and not first_word.startswith("="):
                        continue
                    # Skip shell syntax tokens
                    if first_word in ("then", "else", "fi", "do", "done", "esac", "}", "{", ")", "(", ";;"):
                        continue
                    base_cmd_name = os.path.basename(first_word)
                    if base_cmd_name not in allowed:
                        return ToolResult(
                            success=False, result="",
                            error=f"Command '{base_cmd_name}' not in allowed list: {allowed}",
                        )

        cwd = self.config.get("workspace_root") or self.config.get("cwd")
        return _run_subprocess(command, timeout, cwd)


def _run_subprocess(command: str, timeout: int, cwd: str | None) -> "ToolResult":
    """Execute a shell command in a subprocess and return a ToolResult."""
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

        stdout = result.stdout[:_MAX_OUTPUT_SIZE] + "\n... (truncated)" if len(result.stdout) > _MAX_OUTPUT_SIZE else result.stdout
        stderr = result.stderr[:_MAX_OUTPUT_SIZE] + "\n... (truncated)" if len(result.stderr) > _MAX_OUTPUT_SIZE else result.stderr

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
        return ToolResult(success=False, result="", error=f"Command timed out after {timeout}s")
    except Exception as e:
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")


def _safe_env() -> dict[str, str]:
    """Build a restricted environment for subprocess execution.

    Strips secrets, API keys, and tokens to prevent LLM agents from
    exfiltrating credentials via commands like `env | grep KEY`.
    """
    env = os.environ.copy()
    # Remove keys matching sensitive patterns
    sensitive_suffixes = ("_API_KEY", "_SECRET", "_SECRET_KEY", "_TOKEN", "_PASSWORD")
    sensitive_exact = {
        "SUDO_ASKPASS", "SSH_AUTH_SOCK", "DATABASE_URL", "TEMPER_DATABASE_URL",
        "TEMPER_DASHBOARD_TOKEN", "CLAUDE_CONFIG_DIR",
    }
    to_remove = set()
    for key in env:
        if key in sensitive_exact:
            to_remove.add(key)
        elif any(key.endswith(s) for s in sensitive_suffixes):
            to_remove.add(key)
    for key in to_remove:
        env.pop(key, None)
    return env
