"""Bootstrap a RunnerContext from environment variables + config dir.

The server builds RunnerContext at startup from its own AppState. The
standalone runner (this CLI in phase 2; subprocess in phase 3) doesn't
have an AppState, so it has to rebuild the same collaborators by reading
the environment the server reads — DB URL, LLM provider keys, memory
backend, config dir.

This module is deliberately a thin wrapper that delegates to server.py's
existing init helpers (`_init_llm_providers`, `_init_memory_service`,
`_load_default_configs`). Sharing one source-of-truth means the worker
process picks up the same providers / memory backend / config directory
as the server without per-mode drift.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from temper_ai.config import ConfigStore
from temper_ai.runner.context import RunnerContext
from temper_ai.stage.loader import GraphLoader

logger = logging.getLogger(__name__)


def bootstrap_runner_context_from_env(
    *,
    config_dir: str | Path | None = None,
) -> RunnerContext:
    """Reconstruct a RunnerContext suitable for execute_workflow().

    Args:
        config_dir: where to load workflow YAMLs from. None means use
            $TEMPER_CONFIG_DIR or fall back to `<repo>/configs`. The
            server uses identical resolution in `_load_default_configs`.

    Returns:
        RunnerContext ready to pass to execute_workflow().

    Side effects:
        - Initializes the database via $TEMPER_DATABASE_URL (or DATABASE_URL,
          or the local sqlite default). Idempotent — safe to call after
          the DB is already up.
        - Builds LLM provider clients from env (OPENAI_API_KEY etc.). Empty
          if no provider keys set; execute_workflow will fail at first agent
          call. That's the right surface for a misconfigured worker.
        - Loads workflow YAML configs from config_dir into a fresh
          ConfigStore so graph_loader.load_workflow() can resolve them.
    """
    # Database — reuse server's resolution. init_database is idempotent so
    # the spawner can call this even when the server already opened the DB.
    from temper_ai.database import init_database
    db_url = os.environ.get(
        "TEMPER_DATABASE_URL",
        os.environ.get("DATABASE_URL", "sqlite:///./data/temper.db"),
    )
    init_database(db_url)
    logger.info(
        "Worker DB connected: %s",
        db_url.split("@")[-1] if "@" in db_url else db_url,
    )

    # LLM providers + memory — borrow server's initializers so the worker
    # picks up the exact same env-driven setup the server uses (no drift).
    from temper_ai.server import _init_llm_providers, _init_memory_service
    llm_providers = _init_llm_providers()
    memory_service = _init_memory_service()

    # Config store + graph loader — fresh per worker. The server has its
    # own; loading the same YAMLs here means the worker can resolve any
    # workflow name the server can. Cheap (file reads + dataclass parsing).
    config_store = ConfigStore()
    graph_loader = GraphLoader(config_store)
    _load_configs_into_store(config_store, config_dir)

    return RunnerContext(
        config_store=config_store,
        graph_loader=graph_loader,
        llm_providers=llm_providers,
        memory_service=memory_service,
    )


def _load_configs_into_store(
    store: ConfigStore, config_dir: str | Path | None,
) -> int:
    """Walk config_dir for *.yaml workflow configs and import each.

    Returns the count loaded. Skips MCP-server / tool YAMLs the same way
    the server does. Errors are logged at debug — a single bad YAML
    shouldn't take down the worker if other workflows are loadable.
    """
    if config_dir is None:
        config_dir = os.environ.get("TEMPER_CONFIG_DIR")
    if config_dir is None:
        # Fall back to repo-root configs/ (server.py uses the same path)
        config_dir = Path(__file__).resolve().parents[2] / "configs"
    config_dir = Path(config_dir)

    if not config_dir.is_dir():
        logger.warning("Config dir does not exist: %s", config_dir)
        return 0

    from temper_ai.config.importer import import_yaml

    loaded = 0
    for yaml_file in sorted(config_dir.rglob("*.yaml")):
        if "mcp_servers" in yaml_file.parts or "tools" in yaml_file.parts:
            continue
        try:
            import_yaml(str(yaml_file), store)
            loaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipped config %s: %s", yaml_file, exc)

    logger.info("Loaded %d workflow configs from %s", loaded, config_dir)
    return loaded
