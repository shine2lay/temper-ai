"""Config import/export endpoints for multi-tenant config storage.

Allows authenticated users to upload, download, and list YAML configs
(workflows, stages, agents) stored in the database. Prefix: /api/configs.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.responses import PlainTextResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
)

from temper_ai.auth.api_key_auth import AuthContext, require_role
from temper_ai.storage.database.models_tenancy import VALID_CONFIG_TYPES

logger = logging.getLogger(__name__)

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_OWNER = "owner"

EDITOR_ROLES = (ROLE_EDITOR, ROLE_OWNER)
VIEWER_ROLES = (ROLE_VIEWER, ROLE_EDITOR, ROLE_OWNER)


def _invalid_config_type_detail(config_type: str, valid: frozenset[str]) -> str:
    """Build detail string for invalid config_type errors."""
    return f"Invalid config_type '{config_type}'. Must be one of: {sorted(valid)}"


# ── Request models ────────────────────────────────────────────────────


class ImportConfigRequest(BaseModel):
    """POST /api/configs/import request body."""

    config_type: str
    name: str
    yaml_content: str


# ── Service dependency ────────────────────────────────────────────────


def _get_sync_service() -> Any:
    """Lazily instantiate ConfigSyncService to avoid circular imports."""
    from temper_ai.auth.config_sync import ConfigSyncService  # noqa: PLC0415

    return ConfigSyncService()


# ── Helpers ───────────────────────────────────────────────────────────


def _validate_and_normalize_config_type(config_type: str) -> str:
    """Validate and normalize config_type, raising HTTP 400 if invalid."""
    config_type = config_type.strip().lower()
    if config_type not in VALID_CONFIG_TYPES:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=_invalid_config_type_detail(config_type, VALID_CONFIG_TYPES),
        )
    return config_type


def _handle_import_config(
    body: ImportConfigRequest, ctx: AuthContext
) -> dict[str, Any]:
    """Upload YAML content, parse it, and store in the database."""
    config_type = _validate_and_normalize_config_type(body.config_type)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Config name must not be empty."
        )

    sync_service = _get_sync_service()
    try:
        result = sync_service.import_config(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            config_type=config_type,
            name=name,
            yaml_content=body.yaml_content,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return {
        "name": result.get("name", name),
        "config_type": config_type,
        "version": result.get("version", 1),
    }


def _handle_export_config(
    config_type: str, name: str, ctx: AuthContext
) -> PlainTextResponse:
    """Read a config from the database and return it as YAML text."""
    config_type = _validate_and_normalize_config_type(config_type)
    sync_service = _get_sync_service()
    try:
        yaml_content = sync_service.export_config(
            tenant_id=ctx.tenant_id, config_type=config_type, name=name
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Config '{name}' of type '{config_type}' not found.",
        ) from exc
    return PlainTextResponse(content=yaml_content, media_type="text/yaml")


def _handle_list_configs(config_type: str, ctx: AuthContext) -> dict[str, Any]:
    """List all configs of a given type for the authenticated tenant."""
    config_type = _validate_and_normalize_config_type(config_type)
    sync_service = _get_sync_service()
    configs: list[dict[str, Any]] = sync_service.list_configs(
        tenant_id=ctx.tenant_id, config_type=config_type
    )
    return {"configs": configs, "total": len(configs)}


# ── Router factory ────────────────────────────────────────────────────


def create_config_router() -> APIRouter:
    """Create the /api/configs router."""
    router = APIRouter(prefix="/api/configs", tags=["configs"])

    @router.post("/import")
    def import_config(
        body: ImportConfigRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Import a YAML configuration file."""
        return _handle_import_config(body, ctx)

    @router.get("/{config_type}/{name}/export")
    def export_config(
        config_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(*VIEWER_ROLES)),
    ) -> PlainTextResponse:
        """Export a configuration as YAML."""
        return _handle_export_config(config_type, name, ctx)

    @router.get("/{config_type}")
    def list_configs(
        config_type: str, ctx: AuthContext = Depends(require_role(*VIEWER_ROLES))
    ) -> dict[str, Any]:
        """List available configurations by type."""
        return _handle_list_configs(config_type, ctx)

    return router
