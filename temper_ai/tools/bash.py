"""
Bash tool for executing shell commands in a sandboxed environment.

Provides controlled command execution with:
- Allowlist enforcement (only permitted commands)
- Sandbox enforcement (working directory must be within workspace/)
- Configurable timeout (up to 600s)
- Shell metacharacter injection prevention
- stdout/stderr capture with exit code reporting
"""

import logging
import shlex
import subprocess  # noqa: F401 — kept for test mock patching compatibility
from pathlib import Path
from typing import Any

from temper_ai.tools._bash_helpers import (
    get_safe_env,
    run_command,
    validate_sandbox,
    validate_shell_mode_command,
    validate_strict_mode_command,
)
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.constants import (
    DEFAULT_BASH_TIMEOUT,
    MAX_BASH_TIMEOUT,
)

logger = logging.getLogger(__name__)


# Commands allowed by default
DEFAULT_ALLOWED_COMMANDS: set[str] = {
    "npm",
    "npx",
    "node",
    "hardhat",
    "ls",
    "cat",
    "find",
    "mkdir",
    "pwd",
}

# Shell metacharacters that indicate injection attempts
DANGEROUS_CHARS: set[str] = {
    ";",  # Command separator
    "|",  # Pipe
    "&",  # Background / AND
    "$",  # Variable expansion
    "`",  # Command substitution
    "\n",  # Newline injection
    "\r",  # Carriage return
    ">",  # Output redirection
    "<",  # Input redirection
    "(",  # Subshell open
    ")",  # Subshell close
}

# Maximum allowed timeout in seconds
MAX_TIMEOUT_SECONDS = MAX_BASH_TIMEOUT

# Shell operators that separate commands in a pipeline/chain.
# Ordered longest-first so "||" and "&&" are matched before "|".
_SHELL_OPERATORS = ("||", "&&", ";", "|")


def _split_shell_commands(command: str) -> list[str]:
    """Split a shell command string on unquoted shell operators.

    Uses shlex lexical analysis to correctly handle quoting so that
    operators inside quoted strings are not treated as separators.
    This replaces the previous regex-based splitting which could not
    distinguish quoted from unquoted operator characters (H-13).

    Args:
        command: Raw shell command string (may contain ;, |, &&, ||)

    Returns:
        List of individual sub-command strings.

    Raises:
        ValueError: If the command has unmatched quotes.
    """
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    # Treat shell operators as individual tokens by making them
    # non-whitespace-split characters. We need to reconstruct
    # sub-commands from tokens, splitting on operator tokens.
    #
    # Strategy: iterate character-by-character through the command,
    # tracking quoting state via shlex, and split on operators that
    # appear outside of quotes.
    sub_commands: list[str] = []
    current: list[str] = []
    i = 0
    in_single_quote = False
    in_double_quote = False
    escaped = False

    while i < len(command):
        ch = command[i]

        # Handle escape sequences
        if escaped:
            current.append(ch)
            escaped = False
            i += 1
            continue

        if ch == "\\" and not in_single_quote:
            current.append(ch)
            escaped = True
            i += 1
            continue

        # Handle quoting state
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(ch)
            i += 1
            continue

        # If inside quotes, everything is literal
        if in_single_quote or in_double_quote:
            current.append(ch)
            i += 1
            continue

        # Outside quotes: check for shell operators (longest match first)
        matched = False
        for op in _SHELL_OPERATORS:
            if command[i : i + len(op)] == op:
                # Found an unquoted operator -- split here
                sub_commands.append("".join(current))
                current = []
                i += len(op)
                matched = True
                break

        if not matched:
            current.append(ch)
            i += 1

    # Append the last sub-command
    sub_commands.append("".join(current))

    return sub_commands


class Bash(BaseTool):
    """
    Sandboxed bash command execution tool.

    Executes commands via subprocess with:
    - Allowlist: only commands in the allowed set can run
    - Sandbox: working directory must be within workspace/ under project root
    - Timeout: configurable up to 600 seconds
    - Injection prevention: shell metacharacters are rejected
    - No shell=True: commands are split and executed directly

    Shell mode (shell_mode=True):
    - Allows shell metacharacters (>, ;, |, etc.) for file operations
    - Uses shell=True so redirections and pipes work
    - Still enforces workspace sandbox — CWD must be within workspace_root
    - Intended for LLM agents that need to write files via shell commands

    Safety:
    - modifies_state=True enables safety system snapshots
    - Commands run with shell=False by default to prevent injection
    - Working directory is validated before execution
    """

    DEFAULT_TIMEOUT = DEFAULT_BASH_TIMEOUT  # 2 minutes default

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize Bash tool.

        Args:
            config: Optional configuration dict with keys:
                - allowed_commands: Set of allowed command names (overrides default)
                - workspace_root: Base directory for sandbox (default: project workspace/)
                - default_timeout: Default timeout in seconds
                - shell_mode: If True, allow shell metacharacters and use shell=True.
                    Still enforces workspace sandbox. (default: False)
        """
        # Pre-initialize fields that get_metadata() needs before super().__init__
        # (BaseTool.__init__ calls get_metadata() which references self.shell_mode)
        cfg = config or {}
        self.shell_mode = bool(cfg.get("shell_mode", False))

        super().__init__(config)

        # Configure allowlist
        allowed = self.config.get("allowed_commands")
        if allowed is not None:
            self.allowed_commands: set[str] = set(allowed)
        else:
            self.allowed_commands = DEFAULT_ALLOWED_COMMANDS.copy()

        # Configure workspace root for sandbox
        workspace_root = self.config.get("workspace_root")
        if workspace_root:
            self.workspace_root = Path(workspace_root).resolve()
        else:
            # Default: workspace/ under project root (cwd)
            self.workspace_root = Path.cwd() / "workspace"

        # Default timeout
        self.default_timeout = min(
            self.config.get("default_timeout", self.DEFAULT_TIMEOUT),
            MAX_TIMEOUT_SECONDS,
        )

    def get_metadata(self) -> ToolMetadata:
        """Return Bash tool metadata."""
        if self.shell_mode:
            desc = (
                "Executes shell commands in a sandboxed workspace directory. "
                "Shell mode enabled: redirections (>), pipes (|), and multi-line "
                "commands are allowed. Working directory must be within workspace/. "
                "You can use cat, echo, node, npm, npx, or any command to create "
                "and modify files within the workspace."
            )
        else:
            desc = (
                "Executes shell commands in a sandboxed workspace directory. "
                "Only allowed commands can be run. No chaining with && or ;. "
                "Use the working_directory parameter instead of cd."
            )
        return ToolMetadata(
            name="Bash",
            description=desc,
            version="1.0",
            category="system",
            requires_network=True,  # npm install needs network
            requires_credentials=False,
            modifies_state=True,
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for Bash parameters."""
        if self.shell_mode:
            cmd_desc = (
                "Shell command to execute. Shell mode is enabled: you can use "
                "redirections (>), pipes (|), semicolons (;), and multi-line "
                "commands. Use 'cat > file <<EOF' or 'echo content > file' to "
                "write files. All operations are sandboxed to the workspace."
            )
        else:
            cmd_desc = (
                "A single shell command to execute. Must start with an allowed "
                "command. No shell metacharacters (;|&$`><) allowed. "
                "Do NOT chain commands with && or ;. "
                "Use the working_directory parameter instead of 'cd'."
            )
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": cmd_desc,
                },
                "working_directory": {
                    "type": "string",
                    "description": (
                        "Working directory for command execution. "
                        "Use this instead of 'cd <dir> && <command>'. "
                        "Must be within the workspace/ directory."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Timeout in seconds (max {MAX_BASH_TIMEOUT}). Default: {DEFAULT_BASH_TIMEOUT}."
                    ),
                    "default": DEFAULT_BASH_TIMEOUT,
                },
            },
            "required": ["command"],
        }

    def _sync_config_from_agent(self) -> None:
        """Sync workspace_root and allowed_commands from config (may be updated by agent)."""
        # Sync workspace_root
        cfg_root = self.config.get("workspace_root")
        if cfg_root:
            resolved = Path(cfg_root).resolve()
            if resolved != self.workspace_root:
                logger.warning(
                    "Bash workspace_root changed: %s -> %s",
                    self.workspace_root,
                    resolved,
                )
                self.workspace_root = resolved

        # Sync allowed_commands
        cfg_cmds = self.config.get("allowed_commands")
        if cfg_cmds is not None:
            new_cmds = set(cfg_cmds)
            if new_cmds != self.allowed_commands:
                logger.warning(
                    "Bash allowed_commands changed: %s -> %s",
                    sorted(self.allowed_commands),
                    sorted(new_cmds),
                )
                self.allowed_commands = new_cmds

    def _validate_command_input(
        self, command: Any
    ) -> tuple[str | None, ToolResult | None]:
        """Validate command input. Returns (command, None) or (None, error_result)."""
        if not command or not isinstance(command, str):
            return None, ToolResult(
                success=False,
                error="command must be a non-empty string",
            )

        command_stripped = command.strip()
        if not command_stripped:
            return None, ToolResult(
                success=False,
                error="command must be a non-empty string",
            )

        return command_stripped, None

    def _validate_command_mode(
        self, command: str
    ) -> tuple[list[str] | None, ToolResult | None]:
        """Validate command for shell or strict mode. Returns (parts, None) or (None, error_result)."""
        if self.shell_mode:
            error_result = validate_shell_mode_command(
                command,
                self.allowed_commands,
                self.workspace_root,
            )
            if error_result is not None:
                return None, error_result
            return None, None  # None parts signals shell=True

        parts, error_result = validate_strict_mode_command(
            command,
            self.allowed_commands,
            DANGEROUS_CHARS,
        )
        return parts, error_result

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a shell command in the sandboxed workspace.

        Args:
            command: Shell command string to execute
            working_directory: Optional working directory (must be in workspace/)
            timeout: Optional timeout in seconds (max 600)

        Returns:
            ToolResult with stdout in result, stderr/exit_code in metadata
        """
        command = kwargs.get("command")
        working_directory = kwargs.get("working_directory")
        timeout = kwargs.get("timeout", self.default_timeout)

        # Sync config from agent
        self._sync_config_from_agent()

        # Validate command input
        command, error_result = self._validate_command_input(command)
        if error_result is not None:
            return error_result
        if command is None:
            return ToolResult(success=False, error="Command is required")

        # Validate command mode (shell or strict)
        parts, error_result = self._validate_command_mode(command)
        if error_result is not None:
            return error_result

        # Validate timeout
        if not isinstance(timeout, (int, float)):
            timeout = self.default_timeout
        timeout = min(max(1, int(timeout)), MAX_TIMEOUT_SECONDS)

        # Validate working directory (sandbox)
        resolved_cwd, error_result = validate_sandbox(
            self.workspace_root,
            working_directory,
            parts,
        )
        if error_result is not None:
            return error_result

        # Execute command
        if resolved_cwd is None:
            raise ValueError("resolved_cwd should not be None after validate_sandbox")
        return run_command(
            command,
            parts,
            resolved_cwd,
            timeout,
            self.shell_mode,
            get_safe_env(self.SAFE_ENV_VARS),
        )

    # Environment variables safe to pass to subprocesses
    SAFE_ENV_VARS = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        # Node.js specific
        "NODE_PATH",
        "NODE_ENV",
        "NVM_DIR",
        "NVM_BIN",
        "NPM_CONFIG_PREFIX",
        "NPM_CONFIG_CACHE",
    }

    def _get_safe_env(self) -> dict[str, str]:
        """Build a safe environment for subprocess execution."""
        return get_safe_env(self.SAFE_ENV_VARS)
