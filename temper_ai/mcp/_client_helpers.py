"""Helper functions for MCP client — event loop bridging and annotation mapping."""
import asyncio
import threading
from typing import Any, Dict, Optional, Tuple

from temper_ai.mcp.constants import MCP_EVENT_LOOP_THREAD_NAME


def create_event_loop_thread() -> Tuple[asyncio.AbstractEventLoop, threading.Thread]:
    """Create a daemon thread running a dedicated asyncio event loop.

    Used to bridge synchronous BaseTool.execute() calls into async MCP SDK calls.

    Returns:
        (loop, thread) — the thread is already running; call stop_event_loop() when done.
    """
    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(
        target=_run_loop,
        name=MCP_EVENT_LOOP_THREAD_NAME,
        daemon=True,
    )
    thread.start()
    return loop, thread


def stop_event_loop(
    loop: asyncio.AbstractEventLoop,
    thread: threading.Thread,
    join_timeout: float = 5.0,  # noqa  # scanner: skip-magic
) -> None:
    """Gracefully shut down the background event loop and join the thread.

    Args:
        loop: The asyncio event loop to stop.
        thread: The daemon thread running the loop.
        join_timeout: Seconds to wait for the thread to finish.
    """
    if not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=join_timeout)


def map_annotations_to_metadata(annotations: Optional[Any]) -> Dict[str, Any]:
    """Map MCP tool annotations to ToolMetadata field values.

    Annotation semantics:
    - ``readOnlyHint=True``  → ``modifies_state=False``
    - ``destructiveHint=True`` → ``modifies_state=True``  (already the default)
    - ``openWorldHint=True``  → ``requires_network=True``

    Args:
        annotations: MCP ToolAnnotations object (or None).

    Returns:
        Dict of ToolMetadata keyword arguments inferred from annotations.
    """
    result: Dict[str, Any] = {}

    if annotations is None:
        return result

    read_only = getattr(annotations, "readOnlyHint", None)
    destructive = getattr(annotations, "destructiveHint", None)
    open_world = getattr(annotations, "openWorldHint", None)

    if read_only is True:
        result["modifies_state"] = False
    elif destructive is True:
        result["modifies_state"] = True

    if open_world is True:
        result["requires_network"] = True

    return result
