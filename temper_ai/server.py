"""Temper AI — FastAPI server.

Entry point: uvicorn temper_ai.server:app --reload
Or: docker-compose up
"""

import datetime as _dt
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
from temper_ai.api.auth import TokenAuthMiddleware, configured_token
from temper_ai.api.docs import router as docs_router
from temper_ai.api.routes import init_app_state
from temper_ai.api.routes import router as api_router
from temper_ai.api.studio import router as studio_router
from temper_ai.config import ConfigStore
from temper_ai.database import init_database, reset_database
from temper_ai.mcp import build_server as _build_mcp_server
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

    Defaults to the `sql` backend, which persists memories in the database
    temper already uses. The previous default, `in_memory`, is a dict owned by
    one process: with the server/worker split every run executes in its own
    process, so an agent with memory enabled recalled nothing from the run
    before while looking correctly configured.

    `TEMPER_MEMORY_BACKEND` selects `sql` (default), `mem0` (semantic recall,
    requires mem0ai) or `in_memory` (tests and throwaway runs).
    """
    backend = os.environ.get("TEMPER_MEMORY_BACKEND", "sql")

    store: MemoryStoreBase
    if backend == "mem0":
        try:
            from temper_ai.memory.mem0_store import Mem0Store
            store = Mem0Store()
            logger.info("Memory: mem0 backend initialized")
        except Exception as exc:
            logger.warning("Failed to init mem0, falling back to SQL memory: %s", exc)
            store = _sql_or_in_memory()
    elif backend == "in_memory":
        store = InMemoryStore()
        logger.warning(
            "Memory: in-memory backend selected — memories are lost when this "
            "process exits, and workflows executed by a worker process keep "
            "their own copy. Use TEMPER_MEMORY_BACKEND=sql to persist."
        )
    else:
        store = _sql_or_in_memory()

    return MemoryService(store)


def _sql_or_in_memory() -> MemoryStoreBase:
    """SQL-backed memory, falling back to the dict store if the DB is absent."""
    try:
        from temper_ai.memory import SqlMemoryStore
        store = SqlMemoryStore()
        # Touch the table so a misconfigured database fails here, loudly,
        # rather than on the first agent that tries to remember something.
        store.recall("__healthcheck__", "__startup__", limit=1)
        logger.info("Memory: SQL backend (persistent)")
        return store
    except Exception as exc:
        logger.warning(
            "Memory: SQL backend unavailable (%s) — falling back to a "
            "non-persistent in-memory store", exc,
        )
        return InMemoryStore()


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


# -- MCP server (built once; mounted below, session started in the lifespan) --
_mcp_server = _build_mcp_server()


# Captured before any run of ours can start, so reconciliation can tell a
# previous process's runs from this one's.
_PROCESS_START = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)


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

    # Runs that were in flight when this process last stopped cannot report
    # their own death — their status lives on an event nobody will update.
    from temper_ai.observability.reconcile import reconcile_interrupted_runs
    reconcile_interrupted_runs(started_before=_PROCESS_START)

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

    # Reaper — only when subprocess execution is enabled. In-process runs
    # don't need it because they share the server process's lifecycle.
    reaper = None
    if os.environ.get("TEMPER_EXECUTION_MODE", "inprocess").lower() == "subprocess":
        from temper_ai.spawner import get_spawner
        from temper_ai.spawner.reaper import Reaper
        try:
            reaper = Reaper(get_spawner())
            reaper.start()
        except Exception as e:
            logger.warning("Reaper failed to start (cancel/orphan detection disabled): %s", e)

    if configured_token():
        logger.info("Authentication: enabled (bearer token required)")
    else:
        logger.warning(
            "Authentication: disabled — the API, the MCP endpoint and the "
            "dashboard are open to anyone who can reach this server. Set "
            "TEMPER_API_TOKEN to require a token."
        )

    logger.info("Temper AI server ready")

    # The /mcp endpoint needs its session manager running for the life of
    # the server; mounting a Starlette sub-app does not start it for us.
    async with _mcp_server.session_manager.run():
        yield

    # Shutdown
    if reaper is not None:
        reaper.stop()
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
def frame_ancestors() -> str:
    """Origins allowed to embed this server in a frame (default: none).

    Embedding is denied outright unless TEMPER_FRAME_ANCESTORS names the
    origins that may frame the dashboard, e.g. a private pi-web-ui instance
    showing runs next to its chats:

        TEMPER_FRAME_ANCESTORS=https://pi.wai2shine.com
        TEMPER_FRAME_ANCESTORS=https://pi.wai2shine.com https://spark.tailbb5055.ts.net:8787

    Space- or comma-separated. Only complete origins belong here (scheme +
    host [+ port]); this is an allow-list against clickjacking, so wildcards
    such as "*" are rejected rather than quietly trusted.
    """
    raw = os.environ.get("TEMPER_FRAME_ANCESTORS", "")
    origins = [part for part in raw.replace(",", " ").split() if part]
    return " ".join(o for o in origins if o != "*" and "://" in o)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers (X-Content-Type-Options, X-Frame-Options, etc.) to all responses."""
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Framing: X-Frame-Options cannot express an allow-list, so a configured
        # allow-list switches to CSP frame-ancestors (and must NOT also send
        # XFO DENY — browsers honouring XFO would block the allowed origin).
        # Unconfigured stays exactly as before: deny, with both headers set.
        allowed = frame_ancestors()
        if allowed:
            response.headers["Content-Security-Policy"] = f"frame-ancestors 'self' {allowed}"
        else:
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# -- Include routers --
app.include_router(api_router)
app.include_router(studio_router)
app.include_router(docs_router)

# -- MCP --
# Agents drive temper through the same functions the REST API uses.
#
# Mounted under /mcp (never at "/", which would shadow every route
# registered after it, including the dashboard). We mount the session
# manager's ASGI handler rather than FastMCP's own Starlette app, so that
# both /mcp and /mcp/ are served directly: the wrapper app answers only at
# its root and sends /mcp to /mcp/ as a 307, which not every MCP client
# follows. The session manager itself is started by the lifespan above.
_mcp_server.streamable_http_app()  # forces session-manager construction


async def _mcp_asgi(scope, receive, send):
    await _mcp_server.session_manager.handle_request(scope, receive, send)


class MCPPathMiddleware:
    """Serve the MCP endpoint at /mcp as well as /mcp/.

    A Mount only matches paths *under* its prefix, so a request to exactly
    /mcp would otherwise be answered with a 307 to /mcp/ — and MCP clients
    configured with the obvious URL do not all follow redirects on POST.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


app.mount("/mcp", _mcp_asgi)
app.add_middleware(MCPPathMiddleware)

# Added last, so it wraps everything else: /api, /mcp and /ws alike. Does
# nothing unless TEMPER_API_TOKEN is set.
app.add_middleware(TokenAuthMiddleware)


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
