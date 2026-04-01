"""CLI event printer — Rich-based terminal output for workflow execution.

Implements the EventNotifier interface so it can be plugged into EventRecorder
as a drop-in replacement for WebSocketManager.

Three verbosity levels:
    0 (default): one line per agent — progress tracking
    1 (-v):      inputs/outputs truncated — context engineering visibility
    2 (-vv):     full dump — debugging
"""

import time

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

console = Console(stderr=True)

# Status symbols
_SYMBOLS = {
    "completed": "[green]✓[/green]",
    "failed": "[red]✗[/red]",
    "running": "[yellow]…[/yellow]",
    "skipped": "[dim]–[/dim]",
}

_MAX_TRUNCATE = 200


class CLIPrinter:
    """Prints workflow events to terminal using Rich.

    Implements the same interface as WebSocketManager so it can be
    passed to EventRecorder as a notifier.
    """

    def __init__(self, verbosity: int = 0):
        self.verbosity = verbosity
        self._current_stage: str | None = None
        self._stage_strategy: dict[str, str] = {}  # stage_name -> strategy
        self._agent_start_times: dict[str, float] = {}  # agent_event_id -> start time
        self._run_start: float = time.monotonic()
        self._total_tokens: int = 0
        self._total_cost: float = 0.0

    def print_header(self, workflow_name: str, provider: str = "", model: str = "", budget: str = ""):
        """Print the workflow header panel."""
        subtitle_parts = []
        if provider and model:
            subtitle_parts.append(f"{provider}/{model}")
        if budget:
            subtitle_parts.append(f"budget: {budget}")
        subtitle = " | ".join(subtitle_parts)

        console.print(Panel(
            subtitle or workflow_name,
            title=f"[bold]{workflow_name}[/bold]",
            border_style="cyan",
            padding=(0, 1),
        ))

    def print_footer(self):
        """Print the run summary footer."""
        duration = round(time.monotonic() - self._run_start, 1)
        console.print(Rule(style="dim"))
        console.print(
            f"Completed in {duration}s | "
            f"{self._total_tokens:,} tokens | "
            f"${self._total_cost:.2f}",
        )

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        """Handle an event from the recorder."""
        if event_type == "stage.started":
            self._on_stage_started(data)
        elif event_type == "agent.started":
            self._on_agent_started(data)
        elif event_type == "agent.completed":
            self._on_agent_completed(data)
        elif event_type == "agent.failed":
            self._on_agent_failed(data)
        elif event_type == "workflow.completed":
            self._on_workflow_completed(data)
        elif event_type == "workflow.failed":
            self._on_workflow_failed(data)
        # Other events (llm.call.*, tool.call.*) ignored in default/verbose mode

    def notify_stream_chunk(
        self,
        execution_id: str,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
    ) -> None:
        """Stream chunks are ignored in CLI mode — we show results after completion."""
        pass

    def cleanup(self, execution_id: str) -> None:
        """No cleanup needed for CLI."""
        pass

    # -- Event handlers --

    def _on_stage_started(self, data: dict) -> None:
        name = data.get("name", "")
        strategy = data.get("strategy", "")
        if strategy:
            self._stage_strategy[name] = strategy

        label = f" {name}"
        if strategy:
            label += f" ({strategy})"

        console.print()
        console.print(Rule(label, style="#d4b702"))

    def _on_agent_started(self, data: dict) -> None:
        event_id = data.get("event_id", "")
        self._agent_start_times[event_id] = time.monotonic()

        if self.verbosity >= 1:
            agent_name = data.get("agent_name", "")
            input_data = data.get("input_data", {})
            console.print(f"  [bold magenta]{agent_name}[/bold magenta]")
            if input_data:
                self._print_data("input", input_data)

    def _on_agent_completed(self, data: dict) -> None:
        agent_name = data.get("agent_name", "")
        tokens = data.get("tokens", 0)
        cost = data.get("cost_usd", 0.0)
        duration = data.get("duration_seconds", 0.0)
        output = data.get("output", "")

        self._total_tokens += tokens
        self._total_cost += cost

        symbol = _SYMBOLS["completed"]
        line = f"  {symbol} [bold magenta]{agent_name}[/bold magenta] {duration}s | {tokens:,} tokens"
        if cost > 0:
            line += f" | ${cost:.3f}"
        console.print(line)

        if self.verbosity >= 1 and output:
            self._print_data("output", output)

    def _on_agent_failed(self, data: dict) -> None:
        agent_name = data.get("agent_name", "")
        error = data.get("error", "unknown error")
        duration = data.get("duration_seconds", 0.0)

        symbol = _SYMBOLS["failed"]
        console.print(f"  {symbol} [bold magenta]{agent_name}[/bold magenta] {duration}s | [red]{error}[/red]")

    def _on_workflow_completed(self, data: dict) -> None:
        self.print_footer()

    def _on_workflow_failed(self, data: dict) -> None:
        error = data.get("error", "")
        console.print()
        console.print(Rule(style="red"))
        duration = round(time.monotonic() - self._run_start, 1)
        console.print(f"[red]Failed[/red] in {duration}s: {error}")

    # -- Helpers --

    def _print_data(self, label: str, value) -> None:
        """Print input/output data at the current verbosity level."""
        if isinstance(value, dict):
            text = _format_dict(value, self.verbosity)
        elif isinstance(value, str):
            text = _truncate(value, self.verbosity)
        else:
            text = str(value)

        for line in text.split("\n"):
            console.print(f"    [dim]{label}:[/dim] {line}")


def _truncate(text: str, verbosity: int) -> str:
    """Truncate text based on verbosity level."""
    if verbosity >= 2:
        return text
    if len(text) > _MAX_TRUNCATE:
        return text[:_MAX_TRUNCATE] + f"... [{len(text)} chars]"
    # Collapse multiline to single line
    if "\n" in text:
        first_line = text.split("\n")[0]
        line_count = text.count("\n") + 1
        return first_line[:_MAX_TRUNCATE] + f"... [{line_count} lines]"
    return text


def _format_dict(d: dict, verbosity: int) -> str:
    """Format a dict for display."""
    if verbosity >= 2:
        import json
        return json.dumps(d, indent=2, default=str)

    # Compact: key=value pairs on one line
    parts = []
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 80:
            v = v[:80] + "..."
        parts.append(f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}")
    text = ", ".join(parts)
    if len(text) > _MAX_TRUNCATE:
        return text[:_MAX_TRUNCATE] + "..."
    return text
