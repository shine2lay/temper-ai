"""Real-time LLM streaming display using Rich Live.

Provides a thread-safe display that shows LLM tokens as they arrive,
with separate rendering for thinking and content tokens.
"""
import threading
from typing import Any, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


# Maximum characters to display in the streaming window
_MAX_DISPLAY_CHARS = 2000


class StreamDisplay:
    """Thread-safe streaming display using Rich Live.

    The on_chunk callback runs in the LLM thread while Rich renders
    in the main thread, so all buffer access is guarded by a lock.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._lock = threading.Lock()
        self._thinking_buffer = ""
        self._content_buffer = ""
        self._agent_name: Optional[str] = None
        self._live: Optional[Live] = None
        self._started = False

    def _start(self, agent_name: str) -> None:
        """Begin Live display with agent name header."""
        with self._lock:
            self._agent_name = agent_name
            self._thinking_buffer = ""
            self._content_buffer = ""
        if self._live is None:
            self._live = Live(
                self._build_panel(),
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

    def on_chunk(self, chunk: Any) -> None:
        """Append chunk to appropriate buffer and update display.

        This is the callback passed as stream_callback to the workflow state.
        """
        # Auto-start on first chunk
        if not self._started:
            model = getattr(chunk, 'model', None) or ''
            self._start(model)

        with self._lock:
            if chunk.chunk_type == "thinking":
                self._thinking_buffer += chunk.content
            else:
                self._content_buffer += chunk.content

        if chunk.done:
            self._stop()
            return

        if self._live is not None and self._started:
            try:
                self._live.update(self._build_panel())
            except Exception:  # noqa: BLE001 -- display update must not crash agent
                pass

    def _build_panel(self) -> Panel:
        """Build Rich Panel showing thinking and content buffers."""
        with self._lock:
            thinking = self._thinking_buffer
            content = self._content_buffer
            agent = self._agent_name or "LLM"

        output = Text()

        if thinking:
            # Show last N chars of thinking in dim italic
            display_thinking = thinking[-_MAX_DISPLAY_CHARS:]
            if len(thinking) > _MAX_DISPLAY_CHARS:
                display_thinking = "..." + display_thinking
            output.append(display_thinking, style="dim italic")
            if content:
                output.append("\n\n")

        if content:
            # Show last N chars of content
            display_content = content[-_MAX_DISPLAY_CHARS:]
            if len(content) > _MAX_DISPLAY_CHARS:
                display_content = "..." + display_content
            output.append(display_content)

        if not thinking and not content:
            output.append("Waiting for tokens...", style="dim")

        return Panel(
            output,
            title=f"[cyan]{agent}[/cyan] streaming",
            border_style="cyan",
            padding=(0, 1),
        )
