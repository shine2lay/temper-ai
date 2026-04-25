"""RunnerContext — server-bound state the runner needs to execute a workflow.

Bundles together the heavyweight collaborators (graph loader, llm providers,
memory service, config store) that the runner module needs but doesn't own.

Today (phase 1): server constructs this from its AppState and passes it in.
Phase 2 (CLI): a `bootstrap_runner_context_from_env()` helper reconstructs
this from environment + DB so the CLI can run standalone.

This is intentionally NOT a frozen dataclass — the runner reads from it
once at construction and never mutates. Mutation happens at the AppState
level, on the server, before the runner is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.config import ConfigStore
    from temper_ai.memory import MemoryService
    from temper_ai.stage.loader import GraphLoader


@dataclass
class RunnerContext:
    """Heavyweight collaborators the runner module needs.

    All four are server-lifetime objects that are expensive to construct
    (memory backend, LLM provider clients, config registry). The server
    creates them once at startup and reuses across all runs.

    Phase 2's CLI mode rebuilds these from the environment in `bootstrap_*`
    helpers — slower at startup but standalone.
    """

    config_store: ConfigStore
    graph_loader: GraphLoader
    llm_providers: dict[str, Any]
    memory_service: MemoryService
