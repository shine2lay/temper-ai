"""Real-time streaming display using Rich Live.

Supports multiple concurrent sources (parallel agents, tools, stages).
Each source gets its own panel, all rendered in a single Live display.

The display is event-type agnostic — it works exclusively with
``StreamEvent`` from ``stream_events``.  An auto-adapter in
``make_callback`` transparently converts legacy ``LLMStreamChunk`` objects.
"""
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from src.cli.stream_events import (
    LLM_DONE,
    LLM_TOKEN,
    PROGRESS,
    STATUS,
    TOOL_RESULT,
    TOOL_START,
    StreamEvent,
    from_llm_chunk,
)

# Maximum characters to display per source in the streaming window
_MAX_DISPLAY_CHARS = 1500

# Colors assigned to concurrent source panels (cycles if >len)
_SOURCE_COLORS = ["cyan", "green", "magenta", "yellow", "blue", "red"]


@dataclass
class _SourceStream:
    """Per-source streaming state."""

    name: str
    model: str = ""
    thinking_buffer: str = ""
    content_buffer: str = ""
    tool_line: str = ""
    status_line: str = ""
    done: bool = False
    color: str = "cyan"


class StreamDisplay:
    """Thread-safe multi-source streaming display using Rich Live.

    For parallel execution, call ``make_callback(source_name)`` to get a
    per-source callback.  For sequential/single-source use, ``on_chunk``
    still works (routes to a default "LLM" stream).
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._lock = threading.Lock()
        self._sources: Dict[str, _SourceStream] = {}
        self._color_idx = 0
        self._live: Optional[Live] = None
        self._started = False

    # ── public API ───────────────────────────────────────────────────

    def make_callback(self, source_name: str) -> Callable[[Any], None]:
        """Return a stream callback bound to *source_name*.

        The callback accepts either a ``StreamEvent`` or a legacy
        ``LLMStreamChunk``.  ``LLMStreamChunk`` objects are auto-adapted.
        """
        def _cb(event_or_chunk: Any) -> None:
            if isinstance(event_or_chunk, StreamEvent):
                self._on_event(source_name, event_or_chunk)
            else:
                # Legacy LLMStreamChunk — adapt on the fly
                self._on_event(source_name, from_llm_chunk(source_name, event_or_chunk))
        return _cb

    def on_chunk(self, chunk: Any) -> None:
        """Single-source callback (backward compat).

        Routes all chunks to a stream named after the model.
        """
        model = getattr(chunk, "model", None) or "LLM"
        if isinstance(chunk, StreamEvent):
            self._on_event(model, chunk)
        else:
            self._on_event(model, from_llm_chunk(model, chunk))

    # ── internals ────────────────────────────────────────────────────

    def _next_color(self) -> str:
        color = _SOURCE_COLORS[self._color_idx % len(_SOURCE_COLORS)]
        self._color_idx += 1
        return color

    def _ensure_live(self) -> None:
        """Start the Live display if not already running."""
        if self._live is None:
            self._live = Live(
                self._build_display(),
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.start()
            self._started = True

    def _stop(self) -> None:
        """End Live display."""
        if self._live is not None and self._started:
            try:
                self._live.stop()
            except Exception:  # noqa: BLE001 -- defensive cleanup
                pass
            self._started = False
            self._live = None

    def _on_event(self, source_name: str, event: StreamEvent) -> None:
        """Route a StreamEvent to the correct source stream."""
        if not self._started:
            self._ensure_live()

        with self._lock:
            if source_name not in self._sources:
                model = event.metadata.get("model", "") or ""
                self._sources[source_name] = _SourceStream(
                    name=source_name,
                    model=model,
                    color=self._next_color(),
                )
            stream = self._sources[source_name]
            self._apply_event(stream, event)

        if event.done:
            with self._lock:
                self._sources[source_name].done = True
                all_done = all(s.done for s in self._sources.values())
            if all_done:
                self._stop()
                return
            self._update_live()
            return

        self._update_live()

    @staticmethod
    def _apply_event(stream: _SourceStream, event: StreamEvent) -> None:
        """Mutate *stream* state based on *event* type."""
        etype = event.event_type

        if etype == LLM_TOKEN:
            chunk_type = event.metadata.get("chunk_type", "content")
            if chunk_type == "thinking":
                stream.thinking_buffer += event.content
            else:
                stream.content_buffer += event.content

        elif etype == LLM_DONE:
            # Final token text (often empty) goes to content
            if event.content:
                stream.content_buffer += event.content

        elif etype == TOOL_START:
            tool_name = event.metadata.get("tool_name", "tool")
            stream.tool_line = f"\u26a1 {tool_name} running..."

        elif etype == TOOL_RESULT:
            tool_name = event.metadata.get("tool_name", "tool")
            success = event.metadata.get("success", True)
            duration = event.metadata.get("duration_s")
            if success:
                dur_str = f" ({duration:.1f}s)" if duration is not None else ""
                stream.tool_line = f"\u2713 {tool_name}{dur_str}"
            else:
                error = event.metadata.get("error", "failed")
                stream.tool_line = f"\u2717 {tool_name}: {error}"

        elif etype == STATUS:
            stream.status_line = event.content

        elif etype == PROGRESS:
            stream.content_buffer += event.content

    def _update_live(self) -> None:
        if self._live is not None and self._started:
            try:
                self._live.update(self._build_display())
            except Exception:  # noqa: BLE001 -- display update must not crash agent
                pass

    # ── rendering ────────────────────────────────────────────────────

    def _build_source_panel(self, stream: _SourceStream) -> Panel:
        """Build a single source's panel."""
        output = Text()

        thinking = stream.thinking_buffer
        content = stream.content_buffer

        if thinking:
            display = thinking[-_MAX_DISPLAY_CHARS:]
            if len(thinking) > _MAX_DISPLAY_CHARS:
                display = "..." + display
            output.append(display, style="dim italic")
            if content:
                output.append("\n\n")

        if content:
            display = content[-_MAX_DISPLAY_CHARS:]
            if len(content) > _MAX_DISPLAY_CHARS:
                display = "..." + display
            output.append(display)

        if not thinking and not content:
            output.append("Waiting for tokens...", style="dim")

        # Tool line
        if stream.tool_line:
            output.append("\n")
            output.append(stream.tool_line, style="dim")

        # Status line
        if stream.status_line:
            output.append("\n")
            output.append(stream.status_line, style="dim")

        # Title: source name + model if available
        title_parts = [stream.name]
        if stream.model and stream.model != stream.name:
            title_parts.append(f"({stream.model})")
        title = " ".join(title_parts)

        return Panel(
            output,
            title=f"[{stream.color}]{title}[/{stream.color}] streaming",
            border_style=stream.color,
            padding=(0, 1),
        )

    def _build_display(self) -> Any:
        """Build a Group of panels for all active (non-done) sources."""
        with self._lock:
            active = [s for s in self._sources.values() if not s.done]

        if not active:
            return Panel(
                Text("Waiting for tokens...", style="dim"),
                title="[cyan]LLM[/cyan] streaming",
                border_style="cyan",
                padding=(0, 1),
            )

        panels = [self._build_source_panel(s) for s in active]

        if len(panels) == 1:
            return panels[0]
        return Group(*panels)
