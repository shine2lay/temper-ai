"""FastAPI application factory for the dashboard."""
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(backend: Any = None, event_bus: Any = None) -> FastAPI:
    """Create and configure the dashboard FastAPI application.

    Args:
        backend: ObservabilityBackend instance for reading workflow data.
        event_bus: ObservabilityEventBus instance for real-time events.

    Returns:
        Configured FastAPI application.
    """
    from src.dashboard.data_service import DashboardDataService
    from src.dashboard.routes import create_router
    from src.dashboard.websocket import create_ws_endpoint

    app = FastAPI(title="MAF Dashboard", version="0.1.0")

    # CORS for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Data service
    data_service = DashboardDataService(backend=backend, event_bus=event_bus)

    # REST API routes
    app.include_router(create_router(data_service), prefix="/api")

    # WebSocket endpoint
    ws_handler = create_ws_endpoint(data_service)
    app.add_api_websocket_route("/ws/{workflow_id}", ws_handler)

    # Static files (create dir if needed for dev)
    if STATIC_DIR.exists():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="dashboard",
        )

    # Root redirect
    @app.get("/")
    async def root() -> RedirectResponse:
        """Redirect root to dashboard UI."""
        return RedirectResponse(url="/dashboard/list.html")

    return app
