"""Plugin API endpoints for external framework adapter management.

Provides endpoints for listing plugins, importing them, and checking health.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class ImportPluginRequest(BaseModel):
    """POST /api/plugins/import request body."""

    framework: str  # crewai | langgraph | openai_agents | autogen


# ── Router factory ────────────────────────────────────────────────────


def _handle_import_plugin(body: ImportPluginRequest) -> dict[str, Any]:
    """Import and register a plugin adapter by framework name."""
    from temper_ai.plugins.registry import ensure_plugin_registered, is_plugin_type

    if not is_plugin_type(body.framework):
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Unknown plugin framework: '{body.framework}'. Available: crewai, langgraph, openai_agents, autogen",
        )
    try:
        success = ensure_plugin_registered(body.framework)
        if not success:
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to import plugin '{body.framework}'. Install with: pip install 'temper-ai[{body.framework}]'",
            )
        return {"framework": body.framework, "status": "registered"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to import plugin %s", body.framework)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plugin import failed: {e}",
        ) from e


async def _handle_plugin_health(framework: str) -> dict[str, Any]:
    """Check health of a specific plugin framework."""
    from temper_ai.plugins.registry import get_health_checks, is_plugin_type

    if not is_plugin_type(framework):
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Unknown plugin framework: '{framework}'",
        )
    try:
        all_health = await get_health_checks()
        result = all_health.get(framework)
        if result is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"No health data for framework '{framework}'",
            )
        return {"framework": framework, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Health check failed for plugin %s", framework)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {e}",
        ) from e


def create_plugin_router(auth_enabled: bool = False) -> APIRouter:
    """Create the plugins API router."""
    router = APIRouter(prefix="/api/plugins")
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_plugins() -> dict[str, Any]:
        """List all registered plugins."""
        from temper_ai.plugins.registry import list_plugins as _list_plugins

        plugins = _list_plugins()
        return {"plugins": plugins, "total": len(plugins)}

    @router.post("/import", dependencies=write_deps)
    def import_plugin(body: ImportPluginRequest = Body(...)) -> dict[str, Any]:
        """Import and register a plugin framework."""
        return _handle_import_plugin(body)

    @router.get("/{framework}/health", dependencies=read_deps)
    async def plugin_health(framework: str) -> dict[str, Any]:
        """Check health of a plugin framework."""
        return await _handle_plugin_health(framework)

    return router
