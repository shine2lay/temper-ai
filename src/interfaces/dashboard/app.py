"""FastAPI application factory for the dashboard and server."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 4
_API_PREFIX = "/api"

STATIC_DIR = Path(__file__).parent / "static"

# Header value for static assets — revalidate on every request
_NO_CACHE = "no-cache, must-revalidate"


class _NoCacheStaticMiddleware:
    """ASGI middleware: adds Cache-Control: no-cache to /dashboard/ responses.

    Ensures browsers always revalidate static files with the server.
    Unchanged files get a fast 304; changed files get fresh content.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/dashboard/"):
            await self.app(scope, receive, send)
            return

        async def send_no_cache(message: Any) -> None:
            """Inject Cache-Control: no-cache header into HTTP responses.

            Ensures browsers always revalidate static files, allowing fast 304
            responses for unchanged assets and fresh content for changes.

            Args:
                message: ASGI message dict containing response headers and type.
            """
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("Cache-Control", _NO_CACHE)
            await send(message)

        await self.app(scope, receive, send_no_cache)


def _configure_cors(app: FastAPI, mode: str) -> None:
    """Configure CORS middleware based on mode.

    Args:
        app: FastAPI application instance.
        mode: "server" or "dashboard".
    """
    if mode == "server":
        cors_origins_env = os.environ.get("MAF_CORS_ORIGINS", "")
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        if cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_methods=["GET", "POST"],
                allow_headers=["Content-Type"],
            )
    else:
        # Dashboard mode: permissive for local development
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )


def _register_routes(
    app: FastAPI,
    execution_service: Any,
    data_service: Any,
    config_root: str,
    mode: str,
) -> None:
    """Register API routes and WebSocket endpoints."""
    _register_core_routes(app, execution_service, data_service, config_root)

    if mode != "server":
        _register_dashboard_routes(app, data_service, config_root)


def _register_core_routes(
    app: FastAPI,
    execution_service: Any,
    data_service: Any,
    config_root: str,
) -> None:
    """Register server + WebSocket routes (all modes)."""
    from src.interfaces.dashboard.websocket import create_ws_endpoint
    from src.interfaces.server.routes import create_server_router

    app.include_router(
        create_server_router(execution_service, data_service, config_root),
        prefix=_API_PREFIX,
    )

    ws_handler = create_ws_endpoint(data_service)
    app.add_api_websocket_route("/ws/{workflow_id}", ws_handler)


def _register_dashboard_routes(
    app: FastAPI, data_service: Any, config_root: str,
) -> None:
    """Register dashboard-only routes (studio, learning, goals, portfolio)."""
    from src.interfaces.dashboard.routes import create_router

    app.include_router(create_router(data_service), prefix=_API_PREFIX)

    # Studio config CRUD routes
    from src.interfaces.dashboard.studio_routes import create_studio_router
    from src.interfaces.dashboard.studio_service import StudioService

    studio_service = StudioService(config_root=config_root)
    app.include_router(create_studio_router(studio_service), prefix="/api/studio")

    _register_optional_routes(app, config_root)

    # Static files with no-cache middleware
    if STATIC_DIR.exists():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="dashboard",
        )
        app.add_middleware(_NoCacheStaticMiddleware)

    # Root redirect
    @app.get("/")
    async def root() -> RedirectResponse:
        """Redirect root to dashboard UI."""
        return RedirectResponse(url="/dashboard/list.html")


def _register_optional_routes(app: FastAPI, config_root: str) -> None:
    """Register optional dashboard routes (learning, autonomy, goals, portfolio).

    Uses importlib for cross-domain optional integrations to keep
    the interfaces module fan-out within architectural limits.
    """
    import importlib

    try:
        from src.safety.autonomy.dashboard_routes import create_autonomy_router
        from src.safety.autonomy.dashboard_service import AutonomyDataService
        from src.safety.autonomy.store import AutonomyStore

        _autonomy_store = AutonomyStore()
        _autonomy_svc = AutonomyDataService(_autonomy_store)
        app.include_router(create_autonomy_router(_autonomy_svc), prefix=_API_PREFIX)
    except Exception:  # noqa: BLE001
        logger.warning("Autonomy routes not available")

    _OPTIONAL_ROUTES = [
        ("src.learning", "Learning"),
        ("src.goals", "Goal"),
        ("src.portfolio", "Portfolio"),
    ]
    for domain, label in _OPTIONAL_ROUTES:
        try:
            mod_routes = importlib.import_module(f"{domain}.dashboard_routes")
            _register_domain_routes(app, domain, mod_routes)
        except Exception:  # noqa: BLE001
            logger.warning("%s routes not available", label)


_SUBMOD_STORE = "store"
_SUBMOD_SVC = "dashboard_service"

_DOMAIN_REGISTRY = {
    "src.learning": ("LearningStore", "LearningDataService", "create_learning_router"),
    "src.goals": ("GoalStore", "GoalDataService", "create_goals_router"),
    "src.portfolio": ("PortfolioStore", None, "create_portfolio_router"),
}


def _register_domain_routes(app: FastAPI, domain: str, mod_routes: Any) -> None:
    """Register routes for a dynamically loaded domain module."""
    import importlib

    entry = _DOMAIN_REGISTRY.get(domain)
    if entry is None:
        return
    store_cls, svc_cls, router_fn = entry

    mod_store = importlib.import_module(f"{domain}.{_SUBMOD_STORE}")
    store = getattr(mod_store, store_cls)()
    router_factory = getattr(mod_routes, router_fn)

    if svc_cls is not None:
        mod_svc = importlib.import_module(f"{domain}.{_SUBMOD_SVC}")
        svc = getattr(mod_svc, svc_cls)(store)
        app.include_router(router_factory(svc), prefix=_API_PREFIX)
    else:
        app.include_router(router_factory(store), prefix=_API_PREFIX)


def _init_server_components(mode: str) -> tuple:
    """Initialize server-mode components (shutdown manager, run store, mining job).

    Returns:
        Tuple of (shutdown_mgr, run_store, mining_job) — each may be None.
    """
    shutdown_mgr = None
    run_store = None
    mining_job = None

    if mode != "server":
        return shutdown_mgr, run_store, mining_job

    from src.interfaces.server.lifecycle import GracefulShutdownManager

    shutdown_mgr = GracefulShutdownManager()

    try:
        from src.interfaces.server.run_store import RunStore

        run_store = RunStore()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to initialize RunStore, runs will not persist")

    try:
        from src.learning.background import BackgroundMiningJob
        from src.learning.convergence import ConvergenceDetector
        from src.learning.orchestrator import MiningOrchestrator
        from src.learning.store import LearningStore

        _ls = LearningStore()
        mining_job = BackgroundMiningJob(
            orchestrator=MiningOrchestrator(store=_ls),
            convergence=ConvergenceDetector(_ls),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Background mining job not available")

    return shutdown_mgr, run_store, mining_job


def create_app(
    backend: Any = None,
    event_bus: Any = None,
    mode: str = "dashboard",
    config_root: str = "configs",
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        backend: ObservabilityBackend instance for reading workflow data.
        event_bus: ObservabilityEventBus instance for real-time events.
        mode: "dashboard" (default) or "server" (headless HTTP API).
        config_root: Config directory root path.
        max_workers: Max concurrent workflow executions.

    Returns:
        Configured FastAPI application.
    """
    from src.interfaces.dashboard.data_service import DashboardDataService
    from src.interfaces.dashboard.execution_service import WorkflowExecutionService

    title = "MAF Server" if mode == "server" else "MAF Dashboard"
    shutdown_mgr, run_store, _mining_job = _init_server_components(mode)

    execution_service = WorkflowExecutionService(
        backend=backend, event_bus=event_bus, config_root=config_root,
        max_workers=max_workers, run_store=run_store,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup / shutdown lifecycle for the app."""
        if shutdown_mgr is not None:
            shutdown_mgr.register_signals()
        if _mining_job is not None:
            await _mining_job.start()
        yield
        if _mining_job is not None:
            await _mining_job.stop()
        if shutdown_mgr is not None:
            await shutdown_mgr.drain(execution_service)
        execution_service.shutdown()

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    app.state.execution_service = execution_service
    if shutdown_mgr is not None:
        app.state.shutdown_manager = shutdown_mgr

    _configure_cors(app, mode)
    if mode == "server":
        from src.interfaces.server.auth import APIKeyMiddleware

        app.add_middleware(APIKeyMiddleware)

    data_service = DashboardDataService(backend=backend, event_bus=event_bus)
    _register_routes(app, execution_service, data_service, config_root, mode)

    return app
