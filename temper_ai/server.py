"""Temper AI — FastAPI server.

Entry point: uvicorn temper_ai.server:app --reload
Or: docker-compose up
"""

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from temper_ai.api.app_state import AppState
from temper_ai.api.docs import router as docs_router
from temper_ai.api.routes import init_app_state
from temper_ai.api.routes import router as api_router
from temper_ai.api.studio import router as studio_router
from temper_ai.config import ConfigStore
from temper_ai.database import init_database, reset_database
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.memory.base import MemoryStoreBase

# Import runner so its WorkflowRun SQLModel registers with metadata before
# init_database calls create_all_tables. Phase 0 of worker_protocol_v1.
from temper_ai.runner import WorkflowRun  # noqa: F401  (side-effect import)

# Configure logging so our module loggers output to stdout. Called at import
# time so loggers created by subsequent imports pick up the handler; kept
# below the imports (not above) so ruff E402 doesn't flag each import line.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def _init_llm_providers() -> dict:
    """Initialize LLM providers from environment.

    Server-level config — shared across all workflows.
    Agents reference providers by name (e.g., provider: "openai").
    """
    from temper_ai.llm.providers.base import BaseLLM

    providers: dict[str, BaseLLM] = {}

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        def _make_openai():
            from temper_ai.llm.providers.openai import OpenAILLM
            return OpenAILLM(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=openai_key,
            )
        _try_init_provider(providers, "openai", _make_openai, "OpenAI provider initialized")

    vllm_url = os.environ.get("VLLM_BASE_URL")
    if vllm_url:
        def _make_vllm():
            from temper_ai.llm.providers.vllm import VllmLLM
            return VllmLLM(model=os.environ.get("VLLM_MODEL", "default"), base_url=vllm_url)
        _try_init_provider(providers, "vllm", _make_vllm, f"vLLM provider initialized at {vllm_url}")

    ollama_url = os.environ.get("OLLAMA_BASE_URL")
    if ollama_url:
        def _make_ollama():
            from temper_ai.llm.providers.ollama import OllamaLLM
            return OllamaLLM(model=os.environ.get("OLLAMA_MODEL", "llama3.2"), base_url=ollama_url)
        _try_init_provider(providers, "ollama", _make_ollama, f"Ollama provider initialized at {ollama_url}")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        def _make_anthropic():
            from temper_ai.llm.providers.anthropic import AnthropicLLM
            return AnthropicLLM(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                api_key=anthropic_key,
            )
        _try_init_provider(providers, "anthropic", _make_anthropic, "Anthropic provider initialized")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        def _make_gemini():
            from temper_ai.llm.providers.gemini import GeminiLLM
            return GeminiLLM(
                model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                api_key=gemini_key,
            )
        _try_init_provider(providers, "gemini", _make_gemini, "Gemini provider initialized")

    # Local-only providers — registered via local/register_providers.py (see factory.py).
    # They self-register their classes; here we try to create instances for any
    # that appeared in the factory but weren't initialized above.
    from temper_ai.llm.providers.factory import _PROVIDER_MAP
    for name, cls in _PROVIDER_MAP.items():
        if name not in providers and hasattr(cls, 'create_from_env'):
            try:
                instance = cls.create_from_env()
                if instance:
                    providers[name] = instance
                    logger.info("Provider '%s' initialized (via local plugin)", name)
            except Exception:
                pass

    if not providers:
        logger.warning("No LLM providers configured. Set OPENAI_API_KEY, VLLM_BASE_URL, or OLLAMA_BASE_URL.")

    return providers


def _try_init_provider(providers: dict, name: str, factory, success_msg: str) -> None:
    """Try to initialize an LLM provider via factory(). Log success or warning on failure."""
    try:
        providers[name] = factory()
        logger.info(success_msg)
    except ImportError as exc:
        logger.warning("SDK not installed for provider '%s': %s", name, exc)
    except Exception as exc:
        logger.warning("Failed to init '%s' provider: %s", name, exc)


def _init_memory_service() -> MemoryService:
    """Initialize memory service.

    Uses InMemoryStore by default (non-persistent, for dev).
    Set TEMPER_MEMORY_BACKEND=mem0 for persistent memory (requires mem0ai).
    """
    backend = os.environ.get("TEMPER_MEMORY_BACKEND", "in_memory")

    store: MemoryStoreBase
    if backend == "mem0":
        try:
            from temper_ai.memory.mem0_store import Mem0Store
            store = Mem0Store()
            logger.info("Memory: mem0 backend initialized")
        except Exception as exc:
            logger.warning("Failed to init mem0, falling back to in-memory: %s", exc)
            store = InMemoryStore()
    else:
        store = InMemoryStore()
        logger.info("Memory: in-memory backend (non-persistent)")

    return MemoryService(store)


def _load_default_configs(config_store: ConfigStore):
    """Load demo workflow configs from configs/ directory on startup."""
    configs_dir = Path(os.environ.get("TEMPER_CONFIG_DIR", Path(__file__).parent.parent / "configs"))
    if not configs_dir.exists():
        logger.info("No configs/ directory found, skipping default config loading")
        return

    from temper_ai.config.importer import import_yaml

    loaded = 0
    for yaml_file in sorted(configs_dir.rglob("*.yaml")):
        # Skip non-config YAMLs (MCP servers, tool definitions)
        if "mcp_servers" in yaml_file.parts or "tools" in yaml_file.parts:
            continue
        try:
            import_yaml(str(yaml_file), config_store)
            loaded += 1
        except Exception as exc:
            logger.debug("Skipped config %s: %s", yaml_file, exc)

    if loaded:
        logger.info("Loaded %d configs from %s", loaded, configs_dir)


def _recover_orphaned_runs():
    """Mark any executions left in 'running' status as 'interrupted'.

    These are orphaned from a previous server crash. They can be resumed
    via the checkpoint system.
    """
    try:
        from temper_ai.observability.event_types import EventType
        from temper_ai.observability.recorder import get_events, update_event

        running_events = get_events(
            event_type=EventType("workflow.started"),
            status="running",
            limit=100,
        )
        if not running_events:
            return

        for event in running_events:
            execution_id = event.get("execution_id", "")
            update_event(
                event["id"],
                status="interrupted",
                data={"interrupted_reason": "Server restarted — resume via POST /api/runs/{id}/resume"},
            )
            logger.info("Marked orphaned execution %s as interrupted", execution_id)

        logger.info("Recovered %d orphaned run(s)", len(running_events))
    except Exception as exc:
        logger.warning("Orphaned run recovery failed (non-fatal): %s", exc)


# -- Lifespan --
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize infrastructure on startup, clean up on shutdown."""
    # Database
    db_url = os.environ.get("TEMPER_DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./data/temper.db"))
    init_database(db_url)
    logger.info("Database connected: %s", db_url.split("@")[-1] if "@" in db_url else db_url)

    # LLM providers
    providers = _init_llm_providers()

    # Memory
    memory = _init_memory_service()

    # Shared config store
    from temper_ai.stage.loader import GraphLoader
    config_store = ConfigStore()
    graph_loader = GraphLoader(config_store)

    # Initialize shared app state
    state = AppState(
        config_store=config_store,
        graph_loader=graph_loader,
        llm_providers=providers,
        memory_service=memory,
    )
    init_app_state(state)

    # Load default configs
    _load_default_configs(config_store)

    # MCP servers (load configs only — connections are lazy)
    try:
        from temper_ai.tools.mcp_client import mcp_manager
        await mcp_manager.start()
        configured = mcp_manager.get_configured_servers()
        if configured:
            logger.info("MCP: %d servers configured (lazy connect): %s",
                        len(configured), ", ".join(configured))
    except Exception as e:
        logger.warning("MCP setup failed (non-fatal): %s", e)

    # Mark orphaned runs as interrupted (from previous crashes)
    _recover_orphaned_runs()

    logger.info("Temper AI server ready")
    yield

    # Shutdown
    try:
        from temper_ai.tools.mcp_client import mcp_manager
        await mcp_manager.stop()
    except Exception:
        logger.debug("MCP shutdown failed (non-fatal)", exc_info=True)
    reset_database()
    logger.info("Server shutdown")


app = FastAPI(
    title="Temper AI",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# -- CORS --
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Security headers --
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers (X-Content-Type-Options, X-Frame-Options, etc.) to all responses."""
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# -- Include routers --
app.include_router(api_router)
app.include_router(studio_router)
app.include_router(docs_router)


# -- Health check --
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "healthy",
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
    }


# -- Serve frontend (SPA with client-side routing) --
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from starlette.responses import FileResponse

    # Serve static assets (JS, CSS, images)
    app.mount("/app/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")

    # SPA catch-all: serve index.html for any /app/* route
    @app.get("/app/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all frontend routes (SPA client-side routing)."""
        # Check if it's a real static file first
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise serve index.html (React Router handles the route)
        return FileResponse(str(_frontend_dist / "index.html"))

    @app.get("/app")
    async def serve_spa_root():
        return FileResponse(str(_frontend_dist / "index.html"))

    logger.info("Serving frontend from %s", _frontend_dist)
