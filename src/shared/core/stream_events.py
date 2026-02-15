"""Generic stream event types for multi-source real-time display.

Producers (agents, executors, tool runners) emit ``StreamEvent`` instances.
``StreamDisplay`` consumes them.  An adapter converts legacy ``LLMStreamChunk``
objects at the callback boundary so existing code keeps working.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# ── Event type constants ──────────────────────────────────────────────
LLM_TOKEN = "llm_token"  # noqa: S105  # Event type identifier, not credential
LLM_DONE = "llm_done"          # done=True, metadata has token counts
TOOL_START = "tool_start"      # metadata["tool_name"], metadata["input_params"]
TOOL_RESULT = "tool_result"    # metadata["tool_name"], metadata["success"], metadata["duration_s"]
STATUS = "status"              # content=status message (overwrites, not appends)
PROGRESS = "progress"          # content=progress message (appends)


@dataclass
class StreamEvent:
    """Universal event currency for the streaming display system.

    Parameters
    ----------
    source : str
        Who emitted this event (agent name, stage name, ``"system"``).
    event_type : str
        What happened — one of the module-level constants.
    content : str
        Display text (token text, status message, etc.).
    done : bool
        Signals end of this source's stream.
    metadata : dict
        Type-specific extras (model, tool_name, duration, etc.).
    """

    source: str
    event_type: str
    content: str = ""
    done: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── LLMStreamChunk adapter ───────────────────────────────────────────

def from_llm_chunk(source: str, chunk: Any) -> StreamEvent:
    """Convert an ``LLMStreamChunk`` into a ``StreamEvent``.

    Parameters
    ----------
    source : str
        Logical name for the stream (agent name, model name, etc.).
    chunk : LLMStreamChunk
        The legacy chunk object.

    Returns
    -------
    StreamEvent
    """
    if chunk.done:
        return StreamEvent(
            source=source,
            event_type=LLM_DONE,
            content=chunk.content,
            done=True,
            metadata={
                "model": chunk.model,
                "chunk_type": getattr(chunk, "chunk_type", "content"),
                "prompt_tokens": chunk.prompt_tokens,
                "completion_tokens": chunk.completion_tokens,
                "finish_reason": getattr(chunk, "finish_reason", None),
            },
        )

    return StreamEvent(
        source=source,
        event_type=LLM_TOKEN,
        content=chunk.content,
        done=False,
        metadata={
            "model": chunk.model,
            "chunk_type": getattr(chunk, "chunk_type", "content"),
        },
    )
