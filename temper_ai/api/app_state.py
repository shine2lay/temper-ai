"""Shared application state — initialized once in server lifespan, accessed by all routers.

Replaces module-level singletons and global statements with FastAPI's app.state.
Usage in route handlers: request.app.state.app_state.<field>
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from temper_ai.config import ConfigStore
from temper_ai.memory import MemoryService
from temper_ai.stage.loader import GraphLoader


@dataclass
class AppState:
    """All shared server state in one place."""

    config_store: ConfigStore
    graph_loader: GraphLoader
    llm_providers: dict[str, Any]
    memory_service: MemoryService

    # Per-execution state (mutated at runtime)
    running: dict[str, threading.Event] = field(default_factory=dict)
    gates: dict[str, threading.Event] = field(default_factory=dict)
