"""
Bash tool for executing shell commands in a sandboxed environment.

Provides controlled command execution with:
- Allowlist enforcement (only permitted commands)
- Sandbox enforcement (working directory must be within workspace/)
- Configurable timeout (up to 600s)
- Shell metacharacter injection prevention
- stdout/stderr capture with exit code reporting
"""
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Set

from src.tools.base import BaseTool, ToolMetadata, ToolResult


# Commands allowed by default
DEFAULT_ALLOWED_COMMANDS: Set[str] = {
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
DANGEROUS_CHARS: Set[str] = {
    ";",   # Command separator
    "|",   # Pipe
    "&",   # Background / AND
    "$",   # Variable expansion
    "`",   # Command substitution
    "\n",  # Newline injection
    "\r",  # Carriage return
    ">",   # Output redirection
    "<",   # Input redirection
    "(",   # Subshell open
    ")",   # Subshell close
}

# Maximum allowed timeout in seconds
MAX_TIMEOUT_SECONDS = 600


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

    DEFAULT_TIMEOUT = 120  # 2 minutes default

    def __init__(self, config: Optional[Dict[str, Any]] = None):
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
            self.allowed_commands: Set[str] = set(allowed)
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
                "Only allowed commands (npm, npx, node, hardhat, ls, cat, find, "
                "mkdir, pwd) can be run. Working directory must be within workspace/."
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

    def get_parameters_schema(self) -> Dict[str, Any]:
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
                "Shell command to execute. Must start with an allowed "
                "command (npm, npx, node, hardhat, ls, cat, find, mkdir, pwd). "
                "No shell metacharacters (;|&$`><) allowed."
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
                        "Must be within the workspace/ directory."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Timeout in seconds (max 600). Default: 120."
                    ),
                    "default": 120,
                },
            },
            "required": ["command"],
        }

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

        # --- Validate command ---
        if not command or not isinstance(command, str):
            return ToolResult(
                success=False,
                error="command must be a non-empty string",
            )

        command = command.strip()
        if not command:
            return ToolResult(
                success=False,
                error="command must be a non-empty string",
            )

        # --- Shell mode vs strict mode ---
        if self.shell_mode:
            # Shell mode: allow metacharacters, use shell=True later.
            # SECURITY: Validate ALL commands in a pipeline/chain against the
            # allowlist. Shell operators (;, |, &&, ||) can chain arbitrary
            # commands, so every sub-command must be validated.
            import re as _re
            import shlex as _shlex

            # Split on shell operators to get individual commands
            sub_commands = _re.split(r'\s*(?:;|\|\||&&|\|)\s*', command)

            # Also reject command substitution ($(...) and backticks)
            if '`' in command or '$(' in command:
                return ToolResult(
                    success=False,
                    error=(
                        "Command substitution ($() and backticks) is not allowed. "
                        f"Allowed commands: {sorted(self.allowed_commands)}"
                    ),
                )

            for sub_cmd in sub_commands:
                sub_cmd = sub_cmd.strip()
                if not sub_cmd:
                    continue
                try:
                    shell_parts = _shlex.split(sub_cmd)
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
                            f"Allowed commands: {sorted(self.allowed_commands)}"
                        ),
                    )
                if cmd_name not in self.allowed_commands:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Command '{cmd_name}' is not in the allowed list. "
                            f"Allowed commands: {sorted(self.allowed_commands)}"
                        ),
                    )
            parts = None  # Signal to use shell=True with the raw command string
        else:
            # Strict mode: block metacharacters and enforce allowlist

            # Check for shell metacharacters (injection prevention)
            for char in DANGEROUS_CHARS:
                if char in command:
                    return ToolResult(
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
                return ToolResult(
                    success=False,
                    error=f"Invalid command syntax: {e}",
                )

            if not parts:
                return ToolResult(
                    success=False,
                    error="Command is empty after parsing",
                )

            # Check allowlist - require bare command names (no paths)
            cmd_name = parts[0]
            if "/" in cmd_name or "\\" in cmd_name:
                return ToolResult(
                    success=False,
                    error=(
                        f"Command must be a bare name, not a path: '{cmd_name}'. "
                        f"Allowed commands: {sorted(self.allowed_commands)}"
                    ),
                )
            if cmd_name not in self.allowed_commands:
                return ToolResult(
                    success=False,
                    error=(
                        f"Command '{cmd_name}' is not in the allowed list. "
                        f"Allowed commands: {sorted(self.allowed_commands)}"
                    ),
                )

        # --- Validate timeout ---
        if not isinstance(timeout, (int, float)):
            timeout = self.default_timeout
        timeout = min(max(1, int(timeout)), MAX_TIMEOUT_SECONDS)

        # --- Validate working directory (sandbox) ---
        if working_directory:
            cwd = Path(working_directory).resolve()
        else:
            cwd = self.workspace_root

        # Ensure workspace root exists
        if not self.workspace_root.exists():
            try:
                self.workspace_root.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ToolResult(
                    success=False,
                    error=f"Cannot create workspace directory: {e}",
                )

        # Sandbox check: resolved CWD must be within resolved workspace root
        resolved_workspace = self.workspace_root.resolve()
        resolved_cwd = cwd.resolve() if cwd != self.workspace_root else resolved_workspace
        try:
            resolved_cwd.relative_to(resolved_workspace)
        except ValueError:
            return ToolResult(
                success=False,
                error=(
                    f"Working directory '{cwd}' resolves outside the sandbox. "
                    f"Must be within '{self.workspace_root}'."
                ),
            )

        # Check command arguments for path traversal (strict mode only)
        if parts is not None:
            for arg in parts[1:]:
                if arg.startswith("-"):
                    continue  # Skip flags
                arg_path = (resolved_cwd / arg).resolve() if not Path(arg).is_absolute() else Path(arg).resolve()
                try:
                    arg_path.relative_to(resolved_workspace)
                except ValueError:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Path argument '{arg}' resolves outside the sandbox. "
                            f"All paths must stay within '{self.workspace_root}'."
                        ),
                    )

        # Create working directory if it doesn't exist
        if not resolved_cwd.exists():
            try:
                resolved_cwd.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ToolResult(
                    success=False,
                    error=f"Cannot create working directory: {e}",
                )

        # --- Execute command ---
        try:
            use_shell = self.shell_mode
            cmd_arg = command if use_shell else parts
            result = subprocess.run(
                cmd_arg,
                cwd=str(resolved_cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=use_shell,
                env=self._get_safe_env(),
            )

            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.returncode

            # Truncate very long output
            max_output = 50000
            if len(stdout) > max_output:
                stdout = stdout[:max_output] + "\n... [output truncated]"
            if len(stderr) > max_output:
                stderr = stderr[:max_output] + "\n... [output truncated]"

            success = exit_code == 0

            return ToolResult(
                success=success,
                result=stdout if success else f"Command failed (exit {exit_code}):\n{stderr}\n{stdout}",
                error=stderr if not success and stderr else None,
                metadata={
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "command": command,
                    "working_directory": str(cwd),
                    "timeout": timeout,
                },
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
                metadata={
                    "command": command,
                    "working_directory": str(cwd),
                    "timeout": timeout,
                },
            )

        except FileNotFoundError:
            cmd_display = command.split()[0] if use_shell else parts[0]
            return ToolResult(
                success=False,
                error=f"Command not found: {cmd_display}",
                metadata={"command": command},
            )

        except PermissionError:
            cmd_display = command.split()[0] if use_shell else parts[0]
            return ToolResult(
                success=False,
                error=f"Permission denied executing: {cmd_display}",
                metadata={"command": command},
            )

        except OSError as e:
            return ToolResult(
                success=False,
                error=f"OS error executing command: {e}",
                metadata={"command": command},
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

    def _get_safe_env(self) -> Dict[str, str]:
        """Build a safe environment for subprocess execution.

        Only passes through a curated allowlist of environment variables.
        Secrets (API keys, credentials, etc.) are NOT passed to subprocesses.

        Returns:
            Environment dict for subprocess with only safe variables
        """
        env = {}
        for key in self.SAFE_ENV_VARS:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        return env
