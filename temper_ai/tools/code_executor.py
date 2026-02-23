"""
Code executor tool for running Python code snippets in a sandboxed subprocess.

Security: No shell=True, blocked import scanning, restricted env vars.
Only Python is supported.
"""

import logging
import re
import subprocess
import sys
from typing import Any

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.code_executor_constants import (
    CODE_EXEC_BLOCKED_MODULES,
    CODE_EXEC_DEFAULT_TIMEOUT,
    CODE_EXEC_LANGUAGE,
    CODE_EXEC_MAX_OUTPUT,
)

logger = logging.getLogger(__name__)

# Patterns for detecting blocked module imports in code
_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.MULTILINE,
)


def _find_blocked_import(code: str) -> str | None:
    """
    Scan code for blocked module imports.

    Returns the first blocked module name found, or None if safe.
    """
    for match in _IMPORT_RE.finditer(code):
        module_name = match.group(1)
        if module_name in CODE_EXEC_BLOCKED_MODULES:
            return module_name
    return None


def _truncate(text: str) -> tuple[str, bool]:
    """Truncate text to CODE_EXEC_MAX_OUTPUT. Returns (text, was_truncated)."""
    if len(text) > CODE_EXEC_MAX_OUTPUT:
        return text[:CODE_EXEC_MAX_OUTPUT], True
    return text, False


class CodeExecutorTool(BaseTool):
    """
    Code executor tool that runs Python snippets in an isolated subprocess.

    Security features:
    - Blocked import scanning (os, sys, subprocess, socket, etc.)
    - No shell=True — subprocess.run with explicit arg list
    - Output truncated to CODE_EXEC_MAX_OUTPUT (64 KB)
    - Configurable timeout
    """

    def get_metadata(self) -> ToolMetadata:
        """Return code executor tool metadata."""
        return ToolMetadata(
            name="CodeExecutor",
            description=(
                "Executes Python code snippets in a sandboxed subprocess. "
                "Blocks dangerous imports (os, sys, subprocess, socket, etc.). "
                "Only Python is supported."
            ),
            version="1.0",
            category="execution",
            requires_network=False,
            requires_credentials=False,
            modifies_state=True,
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for code executor parameters."""
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "timeout": {
                    "type": "integer",
                    "description": f"Execution timeout in seconds (default: {CODE_EXEC_DEFAULT_TIMEOUT})",
                    "default": CODE_EXEC_DEFAULT_TIMEOUT,
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (only 'python' supported)",
                    "default": CODE_EXEC_LANGUAGE,
                },
            },
            "required": ["code"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute Python code in a subprocess.

        Args:
            code: Python source code to run
            timeout: Execution timeout in seconds (default: CODE_EXEC_DEFAULT_TIMEOUT)
            language: Must be 'python' (default)

        Returns:
            ToolResult with stdout/stderr output
        """
        code = kwargs.get("code", "")
        timeout = kwargs.get("timeout", CODE_EXEC_DEFAULT_TIMEOUT)
        language = kwargs.get("language", CODE_EXEC_LANGUAGE)

        if not code or not isinstance(code, str):
            return ToolResult(success=False, error="code must be a non-empty string")

        if language != CODE_EXEC_LANGUAGE:
            return ToolResult(
                success=False,
                error=f"Unsupported language '{language}'. Only 'python' is supported.",
            )

        blocked_module = _find_blocked_import(code)
        if blocked_module:
            return ToolResult(
                success=False,
                error=f"Blocked import detected: '{blocked_module}' is not allowed for security reasons",
            )

        env = {"PYTHONDONTWRITEBYTECODE": "1"}

        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=int(timeout),
                env=env,
                shell=False,
            )

            stdout, stdout_truncated = _truncate(proc.stdout)
            stderr, stderr_truncated = _truncate(proc.stderr)

            success = proc.returncode == 0
            error_msg: str | None = None
            if not success:
                error_msg = stderr or f"Process exited with code {proc.returncode}"

            return ToolResult(
                success=success,
                result={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": proc.returncode,
                },
                error=error_msg,
                metadata={
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, error=f"Execution timed out after {timeout} seconds"
            )
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, error=f"Execution error: {exc}")
