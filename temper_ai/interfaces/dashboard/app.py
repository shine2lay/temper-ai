"""FastAPI application factory for the dashboard and server."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 4
_API_PREFIX = "/api"

REACT_DIST_DIR = Path(__file__).parent / "react-dist"

# Header value for static assets — revalidate on every request
_NO_CACHE = "no-cache, must-revalidate"


class _NoCacheStaticMiddleware:
    """ASGI middleware: adds Cache-Control: no-cache to /app/ responses.

    Ensures browsers always revalidate static files with the server.
    Unchanged files get a fast 304; changed files get fresh content.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        is_static = path.startswith("/app/")
        if scope["type"] != "http" or not is_static:
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
        mode: "server" or "dev".
    """
    if mode == "server":
        cors_origins_env = os.environ.get("TEMPER_CORS_ORIGINS", "")
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        if cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_methods=["GET", "POST"],
                allow_headers=["Content-Type", "Authorization"],
            )
        # If TEMPER_CORS_ORIGINS is unset, no CORSMiddleware is added.
        # The browser's same-origin policy blocks cross-origin requests by default.
    else:
        # Dev mode: restrict to localhost only (blocks cross-origin from external sites)
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
            allow_methods=["*"],
            allow_headers=["*"],
        )


class _SecurityHeadersMiddleware:
    """ASGI middleware: adds security headers to all HTTP responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            """Inject security headers into HTTP response start messages."""
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Content-Type-Options", "nosniff")
                headers.append("X-Frame-Options", "DENY")
                headers.append("Referrer-Policy", "strict-origin-when-cross-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _register_routes(
    app: FastAPI,
    execution_service: Any,
    data_service: Any,
    config_root: str,
    mode: str,
    auth_enabled: bool = False,
) -> None:
    """Register API routes and WebSocket endpoints."""
    _register_core_routes(
        app, execution_service, data_service, config_root, auth_enabled=auth_enabled
    )
    _register_data_api_routes(app, data_service, auth_enabled=auth_enabled)
    _register_studio_routes(app, config_root, auth_enabled=auth_enabled)
    _register_management_routes(app, config_root, auth_enabled=auth_enabled)

    _register_dashboard_extras(app, data_service, config_root)

    _mount_react_app(app)


def _register_core_routes(
    app: FastAPI,
    execution_service: Any,
    data_service: Any,
    config_root: str,
    auth_enabled: bool = False,
) -> None:
    """Register server + WebSocket routes (all modes)."""
    from temper_ai.interfaces.dashboard.websocket import create_ws_endpoint
    from temper_ai.interfaces.server.routes import create_server_router

    app.include_router(
        create_server_router(
            execution_service, data_service, config_root, auth_enabled=auth_enabled
        ),
        prefix=_API_PREFIX,
    )

    ws_handler = create_ws_endpoint(data_service, auth_enabled=auth_enabled)
    app.add_api_websocket_route("/ws/{workflow_id}", ws_handler)


def _register_data_api_routes(
    app: FastAPI, data_service: Any, auth_enabled: bool = False
) -> None:
    """Register data query routes (workflows, stages, agents, llm/tool calls).

    Available in ALL modes so the React frontend can fetch data.
    """
    from temper_ai.interfaces.dashboard.routes import create_router

    app.include_router(
        create_router(data_service, auth_enabled=auth_enabled), prefix=_API_PREFIX
    )


def _register_studio_routes(
    app: FastAPI, config_root: str, auth_enabled: bool = False
) -> None:
    """Register Studio config CRUD routes (all modes)."""
    from temper_ai.interfaces.dashboard.studio_routes import create_studio_router
    from temper_ai.interfaces.dashboard.studio_service import StudioService

    studio_service = StudioService(config_root=config_root, use_db=auth_enabled)
    app.include_router(
        create_studio_router(studio_service, auth_enabled=auth_enabled),
        prefix="/api/studio",
    )


def _register_management_routes(
    app: FastAPI, config_root: str, auth_enabled: bool = False
) -> None:
    """Register management API routes (checkpoints, events, memory, etc.).

    Uses lazy importlib to keep import fan-out minimal. Each route module
    follows the ``create_*_router(auth_enabled)`` factory convention.
    """
    import importlib

    management_routes: list[tuple[str, str, str]] = [
        (
            "temper_ai.interfaces.server.checkpoint_routes",
            "create_checkpoint_router",
            "Checkpoint",
        ),
        ("temper_ai.interfaces.server.event_routes", "create_event_router", "Event"),
        ("temper_ai.interfaces.server.memory_routes", "create_memory_router", "Memory"),
        (
            "temper_ai.interfaces.server.optimization_routes",
            "create_optimization_router",
            "Optimization",
        ),
        ("temper_ai.interfaces.server.plugin_routes", "create_plugin_router", "Plugin"),
        (
            "temper_ai.interfaces.server.rollback_routes",
            "create_rollback_router",
            "Rollback",
        ),
        (
            "temper_ai.interfaces.server.template_routes",
            "create_template_router",
            "Template",
        ),
        (
            "temper_ai.interfaces.server.visualize_routes",
            "create_visualize_router",
            "Visualize",
        ),
        (
            "temper_ai.interfaces.server.scaffold_routes",
            "create_scaffold_router",
            "Scaffold",
        ),
        ("temper_ai.interfaces.server.chat_routes", "create_chat_router", "Chat"),
    ]
    for module_path, factory_name, label in management_routes:
        try:
            mod = importlib.import_module(module_path)
            factory = getattr(mod, factory_name)
            app.include_router(factory(auth_enabled=auth_enabled))
        except Exception:  # noqa: BLE001
            logger.warning("%s routes not available", label)


def _register_dashboard_extras(
    app: FastAPI,
    data_service: Any,
    config_root: str,
) -> None:
    """Register dashboard-only routes (learning, goals, portfolio)."""
    _register_optional_routes(app, config_root)


class _SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA fallback: serves index.html for unknown paths.

    Enables React Router client-side routing by returning index.html
    for any path that doesn't match a real static file.
    """

    async def get_response(self, path: str, scope: Any) -> Any:
        """Return static file response, falling back to index.html for SPA routing."""
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException:
            # SPA fallback — serve index.html for client-side routing
            return await super().get_response("index.html", scope)


def _mount_react_app(app: FastAPI) -> None:
    """Mount the React SPA at /app if the build exists."""
    if REACT_DIST_DIR.exists():
        app.mount(
            "/app",
            _SPAStaticFiles(directory=str(REACT_DIST_DIR), html=True),
            name="react-app",
        )
        app.add_middleware(_NoCacheStaticMiddleware)

    @app.get("/")
    async def root() -> RedirectResponse:
        """Redirect root to React app."""
        return RedirectResponse(url="/app")


def _seed_filesystem_configs(config_root: str, tenant_id: str) -> None:
    """Seed filesystem YAML configs into the database for a given tenant.

    Scans configs/{type}/*.yaml and imports any that don't already exist in
    the DB. Runs once at startup so the Library page shows all configs.
    """
    from temper_ai.auth.config_sync import ConfigSyncService

    sync = ConfigSyncService()
    _type_dir_map = {
        "workflow": "workflows",
        "stage": "stages",
        "agent": "agents",
        "tool": "tools",
    }
    root = Path(config_root)
    seeded = 0

    for config_type, dir_name in _type_dir_map.items():
        config_dir = root / dir_name
        if not config_dir.exists():
            continue
        for f in config_dir.glob("*.yaml"):
            name = f.stem
            # Skip if already in DB
            existing = sync.get_config(
                tenant_id=tenant_id, config_type=config_type, name=name
            )
            if existing is not None:
                continue
            try:
                yaml_content = f.read_text(encoding="utf-8")
                sync.import_config(
                    tenant_id=tenant_id,
                    config_type=config_type,
                    name=name,
                    yaml_content=yaml_content,
                    user_id=None,
                )
                seeded += 1
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Skipped seeding %s/%s (validation error)", config_type, name
                )

    if seeded:
        logger.info(
            "Seeded %d filesystem configs into DB for tenant '%s'", seeded, tenant_id
        )


def _register_noauth_config_routes(app: FastAPI, config_root: str) -> None:
    """Register noauth /api/configs and /api/profiles routes for dev mode.

    The frontend Library page fetches from /api/configs/{type} and
    /api/profiles/{type}. In auth mode these are provided by config_routes
    and profile_routes (DB-backed). In dev mode those are skipped, so we
    register DB-backed proxies using the default tenant.
    """
    from starlette.requests import Request

    from temper_ai.auth.config_sync import ConfigSyncService
    from temper_ai.interfaces.server.lifecycle import DEFAULT_TENANT_ID

    sync = ConfigSyncService()

    # Seed filesystem configs into DB so the Library has data
    try:
        _seed_filesystem_configs(config_root, DEFAULT_TENANT_ID)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to seed filesystem configs into DB", exc_info=True)

    @app.get("/api/configs/templates/{config_type}")
    def noauth_list_templates(config_type: str) -> dict:
        """List filesystem templates for a config type (noauth)."""
        from temper_ai.interfaces.server.config_routes import (
            _handle_list_templates,
        )

        return _handle_list_templates(config_type, config_root)

    @app.get("/api/configs/{config_type}/{name}/fork")
    def noauth_fork_placeholder(config_type: str, name: str) -> dict:
        """Placeholder for fork — not available in noauth mode."""
        from fastapi import HTTPException

        raise HTTPException(status_code=501, detail="Fork requires authentication")

    @app.get("/api/configs/{config_type}/{name}")
    def noauth_get_config(config_type: str, name: str) -> dict:
        """Get a single config by type and name (noauth, DB-backed)."""
        config = sync.get_config(
            tenant_id=DEFAULT_TENANT_ID, config_type=config_type, name=name
        )
        if config is None:
            from fastapi import HTTPException
            from starlette.status import HTTP_404_NOT_FOUND

            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Config '{name}' of type '{config_type}' not found.",
            )
        return config

    @app.get("/api/configs/{config_type}")
    def noauth_list_configs(config_type: str) -> dict:
        """List configs by type (noauth, DB-backed with default tenant)."""
        try:
            configs = sync.list_configs(
                tenant_id=DEFAULT_TENANT_ID, config_type=config_type
            )
            return {"configs": configs, "total": len(configs)}
        except ValueError:
            return {"configs": [], "total": 0}

    @app.post("/api/configs/{config_type}")
    async def noauth_create_config(config_type: str, request: Request) -> dict:
        """Create a new config (noauth, DB-backed)."""
        from fastapi import HTTPException

        body = await request.json()
        name = body.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="'name' is required")
        config_data = body.get("config_data", {})
        description = body.get("description", "")
        try:
            result = sync.create_config(
                tenant_id=DEFAULT_TENANT_ID,
                config_type=config_type,
                name=name,
                config_data=config_data,
                description=description,
                user_id=None,
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/configs/{config_type}/{name}")
    async def noauth_update_config(
        config_type: str, name: str, request: Request
    ) -> dict:
        """Update an existing config (noauth, DB-backed)."""
        from fastapi import HTTPException

        body = await request.json()
        try:
            result = sync.update_config(
                tenant_id=DEFAULT_TENANT_ID,
                config_type=config_type,
                name=name,
                config_data=body.get("config_data"),
                description=body.get("description"),
                user_id=None,
            )
            if result is None:
                from starlette.status import HTTP_404_NOT_FOUND

                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND,
                    detail=f"Config '{name}' of type '{config_type}' not found.",
                )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/configs/{config_type}/{name}")
    def noauth_delete_config(config_type: str, name: str) -> dict:
        """Delete a config (noauth, DB-backed)."""
        from fastapi import HTTPException

        try:
            sync.delete_config(
                tenant_id=DEFAULT_TENANT_ID,
                config_type=config_type,
                name=name,
            )
            return {"status": "deleted", "name": name}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/profiles/{profile_type}")
    def noauth_list_profiles(profile_type: str) -> dict:
        """List profiles (noauth, DB-backed with default tenant)."""
        try:
            from temper_ai.interfaces.server.profile_routes import (
                _get_profile_model,
                _validate_profile_type,
            )
            from temper_ai.storage.database.manager import get_session

            profile_type_norm = _validate_profile_type(profile_type)
            model_cls = _get_profile_model(profile_type_norm)
            with get_session() as session:
                records = (
                    session.query(model_cls)
                    .filter_by(tenant_id=DEFAULT_TENANT_ID)
                    .all()
                )
                profiles = [
                    {
                        "name": r.name,
                        "description": getattr(r, "description", ""),
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for r in records
                ]
            return {"profiles": profiles, "total": len(profiles)}
        except Exception:  # noqa: BLE001
            return {"profiles": [], "total": 0}


def _register_auth_routes(app: FastAPI) -> None:
    """Register auth and config management routes (server mode only)."""
    try:
        from temper_ai.interfaces.server.auth_routes import create_auth_router

        app.include_router(create_auth_router())
    except ImportError:
        logger.warning("Auth routes not available")

    try:
        from temper_ai.interfaces.server.config_routes import create_config_router

        app.include_router(create_config_router())
    except ImportError:
        logger.warning("Config routes not available")


def _register_optional_routes(app: FastAPI, config_root: str) -> None:
    """Register optional dashboard routes (learning, autonomy, goals, portfolio).

    Uses importlib for cross-domain optional integrations to keep
    the interfaces module fan-out within architectural limits.
    """
    import importlib

    try:
        from temper_ai.safety.autonomy.dashboard_routes import create_autonomy_router
        from temper_ai.safety.autonomy.dashboard_service import AutonomyDataService
        from temper_ai.safety.autonomy.store import AutonomyStore

        _autonomy_store = AutonomyStore()
        _autonomy_svc = AutonomyDataService(_autonomy_store)
        app.include_router(create_autonomy_router(_autonomy_svc), prefix=_API_PREFIX)
    except Exception:  # noqa: BLE001
        logger.warning("Autonomy routes not available")

    optional_routes = [
        ("temper_ai.learning", "Learning"),
        ("temper_ai.goals", "Goal"),
        ("temper_ai.portfolio", "Portfolio"),
    ]
    for domain, label in optional_routes:
        try:
            mod_routes = importlib.import_module(f"{domain}.dashboard_routes")
            _register_domain_routes(app, domain, mod_routes)
        except Exception:  # noqa: BLE001
            logger.warning("%s routes not available", label)

    try:
        from temper_ai.experimentation.dashboard_routes import (
            create_experimentation_router,
        )
        from temper_ai.experimentation.dashboard_service import ExperimentDataService

        exp_svc = ExperimentDataService()
        app.include_router(create_experimentation_router(exp_svc), prefix=_API_PREFIX)
    except Exception:  # noqa: BLE001
        logger.warning("Experimentation routes not available")

    try:
        from temper_ai.interfaces.server.agent_routes import router as agent_router

        app.include_router(agent_router)
    except Exception:  # noqa: BLE001
        logger.warning("Agent registry routes not available")


_SUBMOD_STORE = "store"
_SUBMOD_SVC = "dashboard_service"

_DOMAIN_REGISTRY = {
    "temper_ai.learning": (
        "LearningStore",
        "LearningDataService",
        "create_learning_router",
    ),
    "temper_ai.goals": ("GoalStore", "GoalDataService", "create_goals_router"),
    "temper_ai.portfolio": ("PortfolioStore", None, "create_portfolio_router"),
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
    """Initialize server-mode components (shutdown manager, background jobs).

    Returns:
        Tuple of (shutdown_mgr, mining_job, analysis_job) — each may be None.
    """
    shutdown_mgr = None
    mining_job = None
    analysis_job = None

    if mode not in ("server", "dev"):
        return shutdown_mgr, mining_job, analysis_job

    from temper_ai.interfaces.server.lifecycle import GracefulShutdownManager

    shutdown_mgr = GracefulShutdownManager()

    try:
        from temper_ai.learning.background import BackgroundMiningJob
        from temper_ai.learning.convergence import ConvergenceDetector
        from temper_ai.learning.orchestrator import MiningOrchestrator
        from temper_ai.learning.store import LearningStore

        _ls = LearningStore()
        mining_job = BackgroundMiningJob(
            orchestrator=MiningOrchestrator(store=_ls),
            convergence=ConvergenceDetector(_ls),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Background mining job not available")

    try:
        from temper_ai.goals.analysis_orchestrator import AnalysisOrchestrator
        from temper_ai.goals.background import BackgroundAnalysisJob
        from temper_ai.goals.store import GoalStore

        goal_store = GoalStore()
        analysis_job = BackgroundAnalysisJob(
            orchestrator=AnalysisOrchestrator(store=goal_store),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Background analysis job not available")

    return shutdown_mgr, mining_job, analysis_job


def _configure_app_middleware_and_routes(  # noqa: long
    app: FastAPI,
    execution_service: Any,
    backend: Any,
    event_bus: Any,
    config_root: str,
    mode: str,
) -> None:
    """Apply middleware, CORS, and register all routes on the app."""
    from temper_ai.interfaces.dashboard.data_service import DashboardDataService

    _configure_cors(app, mode)
    app.add_middleware(_SecurityHeadersMiddleware)
    auth_enabled = mode == "server"

    data_service = DashboardDataService(backend=backend, event_bus=event_bus)
    _register_routes(
        app,
        execution_service,
        data_service,
        config_root,
        mode,
        auth_enabled=auth_enabled,
    )

    # Unauthenticated endpoint: exposes TEMPER_DASHBOARD_TOKEN so the
    # frontend can auto-authenticate without a manual login step.
    @app.get(f"{_API_PREFIX}/runtime-config")
    async def runtime_config() -> dict:
        """Return runtime configuration for frontend auto-authentication."""
        token = os.environ.get("TEMPER_DASHBOARD_TOKEN")
        return {"dashboard_token": token}

    if auth_enabled:
        _register_auth_routes(app)
    else:
        try:
            _register_noauth_config_routes(app, config_root)
        except Exception:  # noqa: BLE001
            logger.warning("Noauth config routes not available (DB may not be set up)")


def create_app(  # noqa: long
    backend: Any = None,
    event_bus: Any = None,
    mode: str = "dev",
    config_root: str = "configs",
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        backend: ObservabilityBackend instance for reading workflow data.
        event_bus: ObservabilityEventBus instance for real-time events.
        mode: "dev" (default) or "server" (headless HTTP API with auth).
        config_root: Config directory root path.
        max_workers: Max concurrent workflow executions.

    Returns:
        Configured FastAPI application.
    """
    from temper_ai.workflow.execution_service import (
        WorkflowExecutionService,
    )

    title = "Temper AI Server" if mode == "server" else "Temper AI (Dev)"
    shutdown_mgr, _mining_job, _analysis_job = _init_server_components(mode)

    execution_service = WorkflowExecutionService(
        backend=backend,
        event_bus=event_bus,
        config_root=config_root,
        max_workers=max_workers,
    )

    # Two-phase init: inject execution_service into event bus for cross-workflow triggers
    if event_bus is not None and hasattr(event_bus, "set_execution_service"):
        event_bus.set_execution_service(execution_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup / shutdown lifecycle for the app."""
        if shutdown_mgr is not None:
            shutdown_mgr.register_signals()
        if _mining_job is not None:
            await _mining_job.start()
        if _analysis_job is not None:
            await _analysis_job.start()
        yield
        if _analysis_job is not None:
            await _analysis_job.stop()
        if _mining_job is not None:
            await _mining_job.stop()
        if shutdown_mgr is not None:
            await shutdown_mgr.drain(execution_service)
        execution_service.shutdown()

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    app.state.execution_service = execution_service
    if shutdown_mgr is not None:
        app.state.shutdown_manager = shutdown_mgr

    _configure_app_middleware_and_routes(
        app, execution_service, backend, event_bus, config_root, mode
    )
    return app
