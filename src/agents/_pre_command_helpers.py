"""Pre-command execution helpers for agents with pre_commands.

Runs deterministic shell commands defined in agent YAML config before
the LLM prompt is sent.  Results are injected into ``input_data`` as
``command_results`` so the Jinja2 template (or auto-inject) can include them.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess  # noqa: S404 -- commands from trusted YAML config
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.agents.constants import PRE_COMMAND_MAX_OUTPUT_CHARS
from src.cli.stream_events import PROGRESS, TOOL_RESULT, TOOL_START, StreamEvent
from src.tools.field_names import ToolResultFields

if TYPE_CHECKING:
    from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Environment variable whitelist for subprocess execution
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "VIRTUAL_ENV", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
    "TERM", "SHELL", "TMPDIR", "TMP", "TEMP",
})

_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _detect_project_venv() -> Optional[str]:
    """Detect the project virtualenv from multiple sources.

    Checks (in order):
    1. VIRTUAL_ENV environment variable
    2. sys.prefix != sys.base_prefix (running inside a venv)
    3. ``venv/`` directory relative to the project root
    """
    # 1. Explicit env var
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and os.path.isdir(venv):
        return venv

    # 2. sys.prefix divergence (running inside a venv)
    import sys
    if sys.prefix != sys.base_prefix and os.path.isdir(sys.prefix):
        return sys.prefix

    # 3. Project-root venv/ directory (handles system-Python entry points)
    try:
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[2]  # src/agents/→ src/→ project
        candidate = project_root / "venv"
        if candidate.is_dir() and (candidate / "bin" / "python3").is_file():
            return str(candidate)
    except (IndexError, OSError):
        pass

    return None


def _build_safe_env() -> Dict[str, str]:
    """Build a restricted environment dict from the current process env.

    If a virtualenv is detected, ensures the venv's bin directory is
    prepended to PATH so ``python3`` resolves to the venv interpreter —
    even when the MAF entry-point uses a system Python shebang.
    """
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}

    venv = _detect_project_venv()
    if venv:
        venv_bin = os.path.join(venv, "bin")
        current_path = env.get("PATH", "")
        if venv_bin not in current_path.split(os.pathsep):
            env["PATH"] = venv_bin + os.pathsep + current_path
        env["VIRTUAL_ENV"] = venv

    return env


def _render_command(command: str, variables: Dict[str, Any]) -> str:
    """Substitute ``{{ var }}`` placeholders in a command string.

    Only replaces variables that exist in *variables*; unresolved
    placeholders are left as-is (they will likely cause a shell error
    which is the desired fail-loud behaviour).
    """
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)

    return _TEMPLATE_VAR_RE.sub(_replacer, command)


def _truncate(text: str, max_chars: int = PRE_COMMAND_MAX_OUTPUT_CHARS) -> str:
    """Truncate text to *max_chars*, appending a notice if trimmed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated at {max_chars} chars]"


def format_pre_command_results(
    results: List[Dict[str, Any]],
) -> str:
    """Format pre-command results as markdown for LLM consumption."""
    parts: list[str] = ["# Pre-Command Results\n"]
    for r in results:
        status = "PASS" if r[ToolResultFields.EXIT_CODE] == 0 else "FAIL"
        parts.append(f"## {r['name']} — {status} (exit {r[ToolResultFields.EXIT_CODE]})")
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


def execute_pre_commands(
    agent: BaseAgent,
    input_data: Dict[str, Any],
) -> Optional[str]:
    """Execute all ``pre_commands`` defined on the agent config.

    Returns a formatted markdown string of results, or ``None`` if
    the agent has no pre_commands configured.
    """
    pre_commands = getattr(agent.config.agent, "pre_commands", None)
    if not pre_commands:
        return None

    results: List[Dict[str, Any]] = []
    safe_env = _build_safe_env()

    for cmd_spec in pre_commands:
        name = cmd_spec.name
        raw_command = cmd_spec.command
        timeout = cmd_spec.timeout_seconds

        rendered = _render_command(raw_command, input_data)
        tool_label = f"pre_command:{name}"
        logger.info("[%s] pre_command '%s': %s", agent.name, name, rendered)

        # Emit TOOL_START for real-time CLI display
        _emit_stream_event(agent, StreamEvent(
            source=agent.name,
            event_type=TOOL_START,
            metadata={"tool_name": tool_label, "input_params": {ToolResultFields.COMMAND: rendered}},
        ))

        start = time.time()
        result: Dict[str, Any] = {
            "name": name,
            ToolResultFields.COMMAND: rendered,
            ToolResultFields.EXIT_CODE: -1,
            ToolResultFields.STDOUT: "",
            ToolResultFields.STDERR: "",
            ToolResultFields.ERROR: None,
            ToolResultFields.DURATION_SECONDS: 0.0,
        }

        try:
            proc = subprocess.run(  # noqa: S602 -- trusted YAML config
                rendered,
                shell=True,
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
            logger.warning("[%s] pre_command '%s' timed out after %ds", agent.name, name, timeout)
        except OSError as exc:
            result[ToolResultFields.EXIT_CODE] = -1
            result[ToolResultFields.ERROR] = str(exc)
            logger.warning("[%s] pre_command '%s' OS error: %s", agent.name, name, exc)

        result[ToolResultFields.DURATION_SECONDS] = round(time.time() - start, 2)
        results.append(result)

        # Emit stdout/stderr as PROGRESS for real-time streaming panel
        if result[ToolResultFields.STDOUT]:
            _emit_stream_event(agent, StreamEvent(
                source=agent.name, event_type=PROGRESS, content=result[ToolResultFields.STDOUT],
            ))
        if result[ToolResultFields.STDERR]:
            _emit_stream_event(agent, StreamEvent(
                source=agent.name, event_type=PROGRESS, content=f"[stderr] {result[ToolResultFields.STDERR]}",
            ))

        # Emit TOOL_RESULT with success/fail status and duration
        _emit_stream_event(agent, StreamEvent(
            source=agent.name,
            event_type=TOOL_RESULT,
            metadata={
                "tool_name": tool_label,
                "success": result[ToolResultFields.EXIT_CODE] == 0,
                "duration_s": result[ToolResultFields.DURATION_SECONDS],
                ToolResultFields.ERROR: result.get(ToolResultFields.ERROR) or (
                    result[ToolResultFields.STDERR][:200] if result[ToolResultFields.EXIT_CODE] != 0 else None
                ),
            },
        ))

        # Track via observability backend
        observer = getattr(agent, "_observer", None)
        if observer is not None:
            observer.track_tool_call(
                tool_name=tool_label,
                input_params={ToolResultFields.COMMAND: rendered},
                output_data={ToolResultFields.EXIT_CODE: result[ToolResultFields.EXIT_CODE], "stdout_len": len(result[ToolResultFields.STDOUT])},
                duration_seconds=result[ToolResultFields.DURATION_SECONDS],
                status="success" if result[ToolResultFields.EXIT_CODE] == 0 else "failed",
                error_message=result.get(ToolResultFields.ERROR),
            )

        status_label = "PASS" if result[ToolResultFields.EXIT_CODE] == 0 else "FAIL"
        logger.info(
            "[%s] pre_command '%s' %s (exit=%d, %.1fs)",
            agent.name, name, status_label, result[ToolResultFields.EXIT_CODE], result[ToolResultFields.DURATION_SECONDS],
        )

    return format_pre_command_results(results)
