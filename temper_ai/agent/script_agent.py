"""Script agent — executes a Jinja-rendered bash script.

No LLM calls. Renders a script template with input_data,
executes via tool_executor (Bash tool), returns stdout as output.
"""

from __future__ import annotations

import json
import logging
import time

from jinja2 import BaseLoader, Environment

from temper_ai.agent.base import AgentABC
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import AgentResult, ExecutionContext, Status

logger = logging.getLogger(__name__)


class ScriptAgent(AgentABC):
    """Agent that executes a Jinja-rendered bash script."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.env = Environment(loader=BaseLoader())  # noqa: B701

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        """Execute the script agent pipeline.

        1. Render Jinja template from config["script_template"] with input_data
        2. Execute via context.tool_executor (Bash tool with workspace + timeout)
        3. Return AgentResult with stdout as output
        """
        start = time.monotonic()
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = self._record_script_started(_record, input_data, context)

        try:
            template = self.env.from_string(self.config["script_template"])
            script = template.render(**input_data)

            timeout = self.config.get("timeout_seconds", 30)
            tool_result = context.tool_executor.execute(
                "Bash",
                {"command": script, "_skip_allowlist": True},
                timeout=timeout,
                context={
                    "parent_id": agent_event_id,
                    "execution_id": context.run_id,
                },
            )

            duration = round(time.monotonic() - start, 3)
            status = Status.COMPLETED if tool_result.success else Status.FAILED
            output = str(tool_result.result) if tool_result.result else ""
            self._record_script_completed(tool_result, output, duration, agent_event_id, context, status)

            # Extract structured output from script's JSON output (if any)
            structured = _extract_json(output)

            return AgentResult(
                status=status,
                output=output,
                structured_output=structured,
                error=tool_result.error,
                duration_seconds=duration,
            )

        except Exception as e:  # noqa: broad-except
            duration = round(time.monotonic() - start, 3)
            _record(
                EventType.AGENT_FAILED,
                parent_id=agent_event_id,
                execution_id=context.run_id,
                status="failed",
                data={
                    "agent_name": self.name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_seconds": duration,
                },
            )
            return AgentResult(
                status=Status.FAILED,
                output="",
                error=str(e),
                duration_seconds=duration,
            )

    def _record_script_started(self, _record, input_data: dict, context: ExecutionContext) -> str:
        """Emit AGENT_STARTED event and return the event id."""
        return _record(
            EventType.AGENT_STARTED,
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status="running",
            data={
                "agent_name": self.name,
                "node_path": context.node_path,
                "type": "script",
                "input_data": input_data,
                "agent_config": {
                    "agent": {
                        "type": "script",
                        "name": self.name,
                        "script_template": self.config.get("script_template", "")[:2000],
                        "timeout_seconds": self.config.get("timeout_seconds", 30),
                    }
                },
            },
        )

    def _record_script_completed(self, tool_result, output: str, duration: float,
                                 agent_event_id: str, context: ExecutionContext, status) -> None:
        """Emit AGENT_COMPLETED or AGENT_FAILED event after script execution."""
        _record = context.event_recorder.record if context.event_recorder else _default_record
        structured = _extract_json(output)
        _record(
            EventType.AGENT_COMPLETED if tool_result.success else EventType.AGENT_FAILED,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status=status.value,
            data={
                "agent_name": self.name,
                "output": output[:20000] if output else "",  # Script output is the primary artifact — allow more
                "output_length": len(output),
                "structured_output": structured,
                "has_structured_output": structured is not None,
                "duration_seconds": duration,
                "error": tool_result.error,
            },
        )

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        if not self.config.get("script_template"):
            errors.append("ScriptAgent requires 'script_template' in config")
        return errors


def _extract_json(text: str) -> dict | None:
    """Extract JSON from the last line of script output."""
    if not text:
        return None
    # Try last line first (scripts typically output JSON as the final line)
    for line in reversed(text.strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None
