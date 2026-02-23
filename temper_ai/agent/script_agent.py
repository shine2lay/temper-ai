"""Script agent — runs a bash script directly, zero LLM calls.

Renders a Jinja2 script template from agent config, executes via subprocess,
parses ``::output key=value`` lines into structured metadata.
"""

from __future__ import annotations

import logging
import re
import subprocess  # noqa: S404 -- scripts from trusted YAML config
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.storage.schemas import AgentConfig

from temper_ai.agent.base_agent import BaseAgent, ExecutionContext
from temper_ai.agent.models.response import AgentResponse
from temper_ai.agent.utils._pre_command_helpers import (
    _build_safe_env,
    _emit_stream_event,
    _render_command,
)
from temper_ai.shared.core.stream_events import (
    PROGRESS,
    TOOL_RESULT,
    TOOL_START,
    StreamEvent,
)
from temper_ai.tools.field_names import ToolResultFields

logger = logging.getLogger(__name__)

# Script agent constants
DEFAULT_SCRIPT_TIMEOUT = 120
MAX_STDERR_CHARS = 200

# Regex for ``::output key=value`` directives
_OUTPUT_LINE_RE = re.compile(r"^::output\s+(\w+)=(.*)$")


def _parse_script_outputs(stdout: str) -> tuple[str, dict[str, str]]:
    """Parse ``::output key=value`` directives from stdout.

    Returns (remaining_output, outputs_dict).
    Lines matching ``::output key=value`` are extracted into the dict;
    all other lines are preserved in remaining_output.
    """
    outputs: dict[str, str] = {}
    remaining: list[str] = []
    for line in stdout.splitlines():
        match = _OUTPUT_LINE_RE.match(line)
        if match:
            outputs[match.group(1)] = match.group(2).strip()
        else:
            remaining.append(line)
    return "\n".join(remaining), outputs


def _execute_script(
    rendered_script: str,
    timeout: int,
    safe_env: dict[str, str],
) -> tuple[int, str, str, str | None]:
    """Execute rendered script via subprocess.

    Returns (exit_code, stdout, stderr, error_message).
    """
    try:
        # shell=True required for multi-line bash scripts;
        # mitigated by: restricted env, timeout, shlex.quote on template vars
        proc = subprocess.run(  # noqa: S602
            rendered_script,
            shell=True,  # nosec B602
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_env,
        )
        return proc.returncode, proc.stdout, proc.stderr, None
    except subprocess.TimeoutExpired:
        return -1, "", "", f"Script timed out after {timeout}s"
    except OSError as exc:
        return -1, "", "", str(exc)


def _build_error_message(
    exit_code: int,
    stderr: str,
    exec_error: str | None,
) -> str | None:
    """Build error message from script execution results."""
    if exit_code == 0:
        return None
    if exec_error:
        return exec_error
    if stderr:
        return stderr[:MAX_STDERR_CHARS]
    return f"Script exited with code {exit_code}"


class ScriptAgent(BaseAgent):
    """Agent that executes a bash script — zero LLM calls.

    The script is Jinja2-rendered from stage inputs (variables shell-escaped
    via ``shlex.quote``), executed via ``subprocess.run``, and ``::output``
    directives in stdout are parsed into structured metadata.

    Config requirements:
    - ``type: script``
    - ``script: |`` — the bash script body (Jinja2 template)
    - ``timeout_seconds:`` — optional (default 120)
    """

    def __init__(self, config: AgentConfig) -> None:
        # Skip BaseAgent.__init__ — no LLM or PromptEngine needed
        self.config = config
        self.name = config.agent.name
        self.description = config.agent.description
        self.version = config.agent.version

        # Infrastructure attrs — set by _setup() at execution time
        self.tool_executor: Any = None
        self.tracker: Any = None
        self._observer: Any = None
        self._stream_callback: Any = None
        self._execution_context: Any = None

    def validate_config(self) -> bool:
        """Validate script agent configuration.

        Intentionally does not call super().validate_config() — script agents
        have no inference or prompt config, so BaseAgent's checks do not apply.
        """
        if not self.config.agent.name:
            raise ValueError("Agent name is required")
        if not self.config.agent.script:
            raise ValueError(f"ScriptAgent '{self.name}' requires a 'script' field")
        return True

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def _run(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
        start_time: float,
    ) -> AgentResponse:
        """Render script, execute via subprocess, parse outputs."""
        script = self.config.agent.script
        if not script:
            raise ValueError(f"ScriptAgent '{self.name}' has no script configured")

        rendered = _render_command(script, input_data)
        timeout = self.config.agent.timeout_seconds or DEFAULT_SCRIPT_TIMEOUT

        exit_code, stdout, stderr, exec_error = self._execute_and_emit(
            rendered,
            timeout,
            start_time,
        )

        remaining_output, outputs = _parse_script_outputs(stdout)
        error = _build_error_message(exit_code, stderr, exec_error)

        return AgentResponse(
            output=remaining_output,
            reasoning=None,
            tool_calls=[],
            metadata={"outputs": outputs, "exit_code": exit_code},
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=time.time() - start_time,
            error=error,
        )

    def _execute_and_emit(
        self,
        rendered: str,
        timeout: int,
        start_time: float,
    ) -> tuple[int, str, str, str | None]:
        """Execute script and emit stream events."""
        tool_label = f"script:{self.name}"

        _emit_stream_event(
            self,
            StreamEvent(
                source=self.name,
                event_type=TOOL_START,
                metadata={"tool_name": tool_label},
            ),
        )

        safe_env = _build_safe_env()
        exit_code, stdout, stderr, exec_error = _execute_script(
            rendered,
            timeout,
            safe_env,
        )

        self._emit_result_events(
            tool_label,
            stdout,
            stderr,
            exit_code,
            exec_error,
            start_time,
        )

        return exit_code, stdout, stderr, exec_error

    def _emit_result_events(
        self,
        tool_label: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        exec_error: str | None,
        start_time: float,
    ) -> None:
        """Emit PROGRESS and TOOL_RESULT stream events."""
        if stdout:
            _emit_stream_event(
                self,
                StreamEvent(
                    source=self.name,
                    event_type=PROGRESS,
                    content=stdout,
                ),
            )
        if stderr:
            _emit_stream_event(
                self,
                StreamEvent(
                    source=self.name,
                    event_type=PROGRESS,
                    content=f"[stderr] {stderr}",
                ),
            )

        duration = round(time.time() - start_time, 2)
        _emit_stream_event(
            self,
            StreamEvent(
                source=self.name,
                event_type=TOOL_RESULT,
                metadata={
                    "tool_name": tool_label,
                    "success": exit_code == 0,
                    "duration_s": duration,
                    ToolResultFields.ERROR: exec_error,
                },
            ),
        )

        self._track_observability(
            tool_label,
            exit_code,
            stdout,
            duration,
            exec_error,
        )

    def _track_observability(
        self,
        tool_label: str,
        exit_code: int,
        stdout: str,
        duration: float,
        error: str | None,
    ) -> None:
        """Track script execution via observability backend."""
        observer = getattr(self, "_observer", None)
        if observer is not None:
            observer.track_tool_call(
                tool_name=tool_label,
                input_params={"type": "script"},
                output_data={
                    ToolResultFields.EXIT_CODE: exit_code,
                    "stdout_len": len(stdout),
                },
                duration_seconds=duration,
                status="success" if exit_code == 0 else "failed",
                error_message=error,
            )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _on_error(
        self,
        error: Exception,
        start_time: float,
    ) -> AgentResponse | None:
        """Handle errors that escape _run().

        Note: OSError and TimeoutError from subprocess execution are caught
        inside _execute_script() and do NOT propagate here. This handler
        covers errors raised directly in _run() — e.g., a ValueError from
        a missing script config field, or a RuntimeError from _render_command.
        OSError/TimeoutError are listed defensively for future callers.
        """
        if isinstance(error, (ValueError, TimeoutError, RuntimeError, OSError)):
            return self._build_error_response(error, start_time)
        return None

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> dict[str, Any]:
        """Get agent capabilities."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": "script",
            "tools": [],
            "supports_streaming": False,
            "supports_multimodal": False,
        }
