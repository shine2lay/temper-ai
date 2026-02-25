"""Pre-command execution helpers for agents with pre_commands.

Runs deterministic shell commands defined in agent YAML config before
the LLM prompt is sent.  Results are injected into ``input_data`` as
``command_results`` so the Jinja2 template (or auto-inject) can include them.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess  # noqa: S404 -- commands from trusted YAML config
import time
from typing import TYPE_CHECKING, Any

from temper_ai.agent.utils.constants import (
    ENV_VAR_PATH,
    ENV_VAR_VIRTUAL_ENV,
    PRE_COMMAND_MAX_OUTPUT_CHARS,
)
from temper_ai.shared.core.stream_events import (
    PROGRESS,
    TOOL_RESULT,
    TOOL_START,
    StreamEvent,
)
from temper_ai.tools.field_names import ToolResultFields

if TYPE_CHECKING:
    from temper_ai.agent.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Environment variable whitelist for subprocess execution
_SAFE_ENV_KEYS = frozenset(
    {
        ENV_VAR_PATH,
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        ENV_VAR_VIRTUAL_ENV,
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "TERM",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
    }
)

_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# Max characters of stderr to include in error message metadata
MAX_STDERR_ERROR_CHARS = 200

# Depth from this file to project root: _pre_command_helpers.py → utils/ → agent/ → temper_ai/ → project
_PROJECT_ROOT_DEPTH = 3


def _detect_project_venv() -> str | None:
    """Detect the project virtualenv from multiple sources.

    Checks (in order):
    1. VIRTUAL_ENV environment variable
    2. sys.prefix != sys.base_prefix (running inside a venv)
    3. ``venv/`` directory relative to the project root
    """
    # 1. Explicit env var
    venv = os.environ.get(ENV_VAR_VIRTUAL_ENV)
    if venv and os.path.isdir(venv):
        return venv

    # 2. sys.prefix divergence (running inside a venv)
    import sys

    if sys.prefix != sys.base_prefix and os.path.isdir(sys.prefix):
        return sys.prefix

    # 3. Project-root venv/ directory (handles system-Python entry points)
    try:
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[_PROJECT_ROOT_DEPTH]
        candidate = project_root / "venv"
        if candidate.is_dir() and (candidate / "bin" / "python3").is_file():
            return str(candidate)
    except (IndexError, OSError):
        pass

    return None


def _build_safe_env() -> dict[str, str]:
    """Build a restricted environment dict from the current process env.

    If a virtualenv is detected, ensures the venv's bin directory is
    prepended to PATH so ``python3`` resolves to the venv interpreter —
    even when the MAF entry-point uses a system Python shebang.
    """
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}

    venv = _detect_project_venv()
    if venv:
        venv_bin = os.path.join(venv, "bin")
        current_path = env.get(ENV_VAR_PATH, "")
        if venv_bin not in current_path.split(os.pathsep):
            env[ENV_VAR_PATH] = venv_bin + os.pathsep + current_path
        env[ENV_VAR_VIRTUAL_ENV] = venv

    return env


def _render_command(command: str, variables: dict[str, Any]) -> str:
    """Substitute ``{{ var }}`` placeholders in a command string.

    Only replaces variables that exist in *variables*; unresolved
    placeholders are left as-is (they will likely cause a shell error
    which is the desired fail-loud behaviour).

    Security: Values are shell-escaped using shlex.quote() to prevent
    command injection via malicious variable values.
    """

    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables:
            # Shell-escape the value to prevent command injection
            return shlex.quote(str(variables[key]))
        return match.group(0)

    return _TEMPLATE_VAR_RE.sub(_replacer, command)


def _truncate(text: str, max_chars: int = PRE_COMMAND_MAX_OUTPUT_CHARS) -> str:
    """Truncate text to *max_chars*, appending a notice if trimmed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated at {max_chars} chars]"


def format_pre_command_results(
    results: list[dict[str, Any]],
) -> str:
    """Format pre-command results as markdown for LLM consumption."""
    parts: list[str] = ["# Pre-Command Results\n"]
    for r in results:
        status = "PASS" if r[ToolResultFields.EXIT_CODE] == 0 else "FAIL"
        parts.append(
            f"## {r['name']} — {status} (exit {r[ToolResultFields.EXIT_CODE]})"
        )
        if r[ToolResultFields.STDOUT]:
            parts.append(f"```\n{r[ToolResultFields.STDOUT]}\n```")
        if r[ToolResultFields.STDERR]:
            parts.append(f"**stderr:**\n```\n{r[ToolResultFields.STDERR]}\n```")
        if r.get(ToolResultFields.ERROR):
            parts.append(f"**error:** {r[ToolResultFields.ERROR]}")
        parts.append("")
    return "\n".join(parts)


def _emit_stream_event(agent: BaseAgent, event: StreamEvent) -> None:
    """Emit a StreamEvent via the agent's stream callback, if present."""
    stream_cb = getattr(agent, "_stream_callback", None)
    if stream_cb is not None:
        stream_cb(event)


def _execute_single_pre_command(
    rendered_command: str,
    timeout: int,
    safe_env: dict[str, str],
) -> dict[str, Any]:
    """Execute a single pre-command and return result dict.

    Args:
        rendered_command: The fully rendered command string
        timeout: Timeout in seconds
        safe_env: Safe environment variables

    Returns:
        Dict with exit_code, stdout, stderr, error, and duration_seconds
    """
    start = time.time()
    result: dict[str, Any] = {
        ToolResultFields.EXIT_CODE: -1,
        ToolResultFields.STDOUT: "",
        ToolResultFields.STDERR: "",
        ToolResultFields.ERROR: None,
        ToolResultFields.DURATION_SECONDS: 0.0,
    }

    try:
        # shell=True required for compound commands (pipelines, conditionals);
        # mitigated by: restricted env (_build_safe_env), timeout enforcement,
        # shlex.quote on template variables (_render_command)
        proc = subprocess.run(  # noqa: S602
            rendered_command,
            shell=True,  # nosec B602
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_env,
        )
        result[ToolResultFields.EXIT_CODE] = proc.returncode
        result[ToolResultFields.STDOUT] = _truncate(proc.stdout)
        result[ToolResultFields.STDERR] = _truncate(proc.stderr)
    except subprocess.TimeoutExpired:
        result[ToolResultFields.EXIT_CODE] = -1
        result[ToolResultFields.ERROR] = f"Timed out after {timeout}s"
    except OSError as exc:
        result[ToolResultFields.EXIT_CODE] = -1
        result[ToolResultFields.ERROR] = str(exc)

    result[ToolResultFields.DURATION_SECONDS] = round(time.time() - start, 2)
    return result


def _emit_pre_command_events(
    agent: BaseAgent,
    tool_label: str,
    result: dict[str, Any],
) -> None:
    """Emit StreamEvents for pre-command execution (PROGRESS, TOOL_RESULT).

    TOOL_START is emitted by the caller before execution, not here.

    Args:
        agent: The agent instance
        tool_label: Label for the tool (e.g., "pre_command:setup")
        result: Result dict from _execute_single_pre_command
    """
    # TOOL_START was emitted before execution, so we skip it here

    # Emit stdout/stderr as PROGRESS
    if result[ToolResultFields.STDOUT]:
        _emit_stream_event(
            agent,
            StreamEvent(
                source=agent.name,
                event_type=PROGRESS,
                content=result[ToolResultFields.STDOUT],
            ),
        )
    if result[ToolResultFields.STDERR]:
        _emit_stream_event(
            agent,
            StreamEvent(
                source=agent.name,
                event_type=PROGRESS,
                content=f"[stderr] {result[ToolResultFields.STDERR]}",
            ),
        )

    # Emit TOOL_RESULT with success/fail status
    _emit_stream_event(
        agent,
        StreamEvent(
            source=agent.name,
            event_type=TOOL_RESULT,
            metadata={
                "tool_name": tool_label,
                "success": result[ToolResultFields.EXIT_CODE] == 0,
                "duration_s": result[ToolResultFields.DURATION_SECONDS],
                ToolResultFields.ERROR: result.get(ToolResultFields.ERROR)
                or (
                    result[ToolResultFields.STDERR][:MAX_STDERR_ERROR_CHARS]
                    if result[ToolResultFields.EXIT_CODE] != 0
                    else None
                ),
            },
        ),
    )


def _track_pre_command_observability(
    agent: BaseAgent,
    tool_label: str,
    rendered_command: str,
    result: dict[str, Any],
) -> None:
    """Track pre-command execution via observability backend.

    Args:
        agent: The agent instance
        tool_label: Label for the tool
        rendered_command: The rendered command string
        result: Result dict from _execute_single_pre_command
    """
    observer = getattr(agent, "_observer", None)
    if observer is not None:
        observer.track_tool_call(
            tool_name=tool_label,
            input_params={ToolResultFields.COMMAND: rendered_command},
            output_data={
                ToolResultFields.EXIT_CODE: result[ToolResultFields.EXIT_CODE],
                "stdout_len": len(result[ToolResultFields.STDOUT]),
            },
            duration_seconds=result[ToolResultFields.DURATION_SECONDS],
            status="success" if result[ToolResultFields.EXIT_CODE] == 0 else "failed",
            error_message=result.get(ToolResultFields.ERROR),
        )


def _log_pre_command_status(  # noqa: long
    agent: BaseAgent,
    name: str,
    result: dict[str, Any],
) -> None:
    """Log the final status of a pre_command execution."""
    exit_code = result[ToolResultFields.EXIT_CODE]
    status_label = "PASS" if exit_code == 0 else "FAIL"
    if result.get(ToolResultFields.ERROR):
        logger.warning(
            "[%s] pre_command '%s' error: %s",
            agent.name,
            name,
            result[ToolResultFields.ERROR],
        )
    elif exit_code != 0:
        logger.warning(
            "[%s] pre_command '%s' %s (exit=%d, %.1fs)",
            agent.name,
            name,
            status_label,
            exit_code,
            result[ToolResultFields.DURATION_SECONDS],
        )
    else:
        logger.info(
            "[%s] pre_command '%s' %s (exit=%d, %.1fs)",
            agent.name,
            name,
            status_label,
            exit_code,
            result[ToolResultFields.DURATION_SECONDS],
        )


def execute_pre_commands(
    agent: BaseAgent,
    input_data: dict[str, Any],
) -> str | None:
    """Execute all ``pre_commands`` defined on the agent config.

    Returns a formatted markdown string of results, or ``None`` if
    the agent has no pre_commands configured.
    """
    pre_commands = getattr(agent.config.agent, "pre_commands", None)
    if not pre_commands:
        return None

    results: list[dict[str, Any]] = []
    safe_env = _build_safe_env()

    for cmd_spec in pre_commands:
        name = cmd_spec.name
        rendered = _render_command(cmd_spec.command, input_data)
        tool_label = f"pre_command:{name}"

        logger.info("[%s] pre_command '%s': %s", agent.name, name, rendered)

        # Emit TOOL_START for real-time CLI display
        _emit_stream_event(
            agent,
            StreamEvent(
                source=agent.name,
                event_type=TOOL_START,
                metadata={
                    "tool_name": tool_label,
                    "input_params": {ToolResultFields.COMMAND: rendered},
                },
            ),
        )

        # Execute command
        result = _execute_single_pre_command(
            rendered, cmd_spec.timeout_seconds, safe_env
        )
        result["name"] = name
        result[ToolResultFields.COMMAND] = rendered
        results.append(result)

        # Emit events and track observability
        _emit_pre_command_events(agent, tool_label, result)
        _track_pre_command_observability(agent, tool_label, rendered, result)
        _log_pre_command_status(agent, name, result)

    return format_pre_command_results(results)
