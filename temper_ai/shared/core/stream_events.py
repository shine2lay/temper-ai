"""Generic stream event types for multi-source real-time display.

Producers (agents, executors, tool runners) emit ``StreamEvent`` instances.
``StreamDisplay`` consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Event type constants ──────────────────────────────────────────────
TOOL_START = "tool_start"  # metadata["tool_name"], metadata["input_params"]
TOOL_RESULT = (
    "tool_result"  # metadata["tool_name"], metadata["success"], metadata["duration_s"]
)
PROGRESS = "progress"  # content=progress message (appends)


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
    metadata: dict[str, Any] = field(default_factory=dict)
