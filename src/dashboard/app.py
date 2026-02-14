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
    from src.dashboard.data_service import DashboardDataService
    from src.dashboard.execution_service import WorkflowExecutionService
    from src.dashboard.routes import create_router
    from src.dashboard.websocket import create_ws_endpoint

    title = "MAF Server" if mode == "server" else "MAF Dashboard"

    # Build lifespan for server mode (graceful shutdown)
    shutdown_mgr = None
    if mode == "server":
        from src.server.lifecycle import GracefulShutdownManager

        shutdown_mgr = GracefulShutdownManager()

    # Execution service
    execution_service = WorkflowExecutionService(
        backend=backend,
        event_bus=event_bus,
        config_root=config_root,
        max_workers=max_workers,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup / shutdown lifecycle for the app."""
        if shutdown_mgr is not None:
            shutdown_mgr.register_signals()
        yield
        # Drain active workflows in server mode
        if shutdown_mgr is not None:
            await shutdown_mgr.drain(execution_service)
        execution_service.shutdown()

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)

    # Store on app.state for endpoint access
    app.state.execution_service = execution_service
    if shutdown_mgr is not None:
        app.state.shutdown_manager = shutdown_mgr

    # CORS configuration
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

    # Data service
    data_service = DashboardDataService(backend=backend, event_bus=event_bus)

    # Server router is always included first so literal routes like
    # /api/workflows/available match before parametric /api/workflows/{id}.
    from src.server.routes import create_server_router

    app.include_router(
        create_server_router(execution_service, data_service, config_root),
        prefix="/api",
    )

    # WebSocket endpoint for event streaming (both modes)
    ws_handler = create_ws_endpoint(data_service)
    app.add_api_websocket_route("/ws/{workflow_id}", ws_handler)

    if mode != "server":
        # Dashboard mode: data query routes + studio + static files
        app.include_router(create_router(data_service), prefix="/api")

        # Studio config CRUD routes
        from src.dashboard.studio_routes import create_studio_router
        from src.dashboard.studio_service import StudioService

        studio_service = StudioService(config_root=config_root)
        app.include_router(create_studio_router(studio_service), prefix="/api/studio")

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

    return app
