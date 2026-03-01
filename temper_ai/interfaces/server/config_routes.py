"""Config CRUD, import/export, fork, and template endpoints.

Allows authenticated users to create, read, update, delete, import, export,
and fork YAML/JSON configs (workflows, stages, agents, tools) stored in the
database. Prefix: /api/configs.
"""

import copy
import logging
from pathlib import Path
from typing import Any

import yaml
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


class ConfigCreateRequest(BaseModel):
    """POST /api/configs/{type} request body."""

    name: str
    description: str = ""
    config_data: dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    """PUT /api/configs/{type}/{name} request body."""

    description: str | None = None
    config_data: dict[str, Any] | None = None


class ForkRequest(BaseModel):
    """POST /api/configs/{type}/{name}/fork request body."""

    new_name: str
    overrides: dict[str, Any] = {}


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


def _validate_config_data(config_type: str, config_data: dict[str, Any]) -> None:
    """Validate config_data against Pydantic schema. Raises HTTP 422 on failure."""
    from temper_ai.workflow._config_loader_helpers import validate_config

    try:
        validate_config(config_type, config_data)
    except Exception as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Validation failed: {exc}",
        ) from exc


def _handle_create_config(
    config_type: str, body: ConfigCreateRequest, ctx: AuthContext
) -> dict[str, Any]:
    """Create a new config in the database."""
    config_type = _validate_and_normalize_config_type(config_type)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Config name must not be empty."
        )

    _validate_config_data(config_type, body.config_data)

    sync_service = _get_sync_service()
    existing = sync_service.get_config(
        tenant_id=ctx.tenant_id, config_type=config_type, name=name
    )
    if existing:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Config '{name}' already exists for type '{config_type}'.",
        )

    result = sync_service.create_config(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        config_type=config_type,
        name=name,
        description=body.description,
        config_data=body.config_data,
    )
    return {"id": result["id"], "name": name, "version": result.get("version", 1)}


def _handle_get_config(config_type: str, name: str, ctx: AuthContext) -> dict[str, Any]:
    """Get a single config by type and name."""
    config_type = _validate_and_normalize_config_type(config_type)
    sync_service = _get_sync_service()
    config = sync_service.get_config(
        tenant_id=ctx.tenant_id, config_type=config_type, name=name
    )
    if config is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Config '{name}' of type '{config_type}' not found.",
        )
    return config


def _handle_update_config(
    config_type: str, name: str, body: ConfigUpdateRequest, ctx: AuthContext
) -> dict[str, Any]:
    """Update an existing config."""
    config_type = _validate_and_normalize_config_type(config_type)

    if body.config_data is not None:
        _validate_config_data(config_type, body.config_data)

    sync_service = _get_sync_service()
    try:
        result = sync_service.update_config(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            config_type=config_type,
            name=name,
            description=body.description,
            config_data=body.config_data,
        )
    except KeyError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result


def _handle_delete_config(
    config_type: str, name: str, ctx: AuthContext
) -> dict[str, str]:
    """Delete a config."""
    config_type = _validate_and_normalize_config_type(config_type)
    sync_service = _get_sync_service()
    try:
        sync_service.delete_config(
            tenant_id=ctx.tenant_id, config_type=config_type, name=name
        )
    except KeyError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "deleted"}


_TYPE_DIR_MAP = {
    "workflow": "workflows",
    "stage": "stages",
    "agent": "agents",
    "tool": "tools",
}


def _load_filesystem_template(
    config_type: str, name: str, config_root: str = "configs"
) -> dict[str, Any] | None:
    """Load a filesystem template by name. Returns parsed dict or None."""
    dir_name = _TYPE_DIR_MAP.get(config_type, config_type + "s")
    template_dir = Path(config_root) / dir_name

    for ext in (".yaml", ".yml"):
        candidate = template_dir / f"{name}{ext}"
        if candidate.exists():
            with open(candidate) as fh:
                return yaml.safe_load(fh)
    return None


def _handle_list_templates(config_type: str, config_root: str) -> dict[str, Any]:
    """List pre-deployed filesystem configs available for forking."""
    config_type = _validate_and_normalize_config_type(config_type)
    dir_name = _TYPE_DIR_MAP.get(config_type, config_type + "s")
    template_dir = Path(config_root) / dir_name

    templates: list[dict[str, Any]] = []
    if template_dir.exists():
        for f in sorted(template_dir.glob("*.y*ml")):
            try:
                with open(f) as fh:
                    data = yaml.safe_load(fh)
                inner = data.get(config_type, data) if isinstance(data, dict) else {}
                templates.append(
                    {
                        "name": f.stem,
                        "description": (
                            inner.get("description", "")
                            if isinstance(inner, dict)
                            else ""
                        ),
                        "filename": f.name,
                    }
                )
            except Exception:  # noqa: BLE001
                continue

    return {"templates": templates, "total": len(templates)}


def _handle_fork_config(
    config_type: str,
    name: str,
    body: ForkRequest,
    ctx: AuthContext,
    config_root: str = "configs",
) -> dict[str, Any]:
    """Fork an existing config (DB or filesystem template) into a new tenant-owned copy."""
    config_type = _validate_and_normalize_config_type(config_type)

    sync_service = _get_sync_service()
    source = sync_service.get_config(
        tenant_id=ctx.tenant_id, config_type=config_type, name=name
    )
    if source is not None:
        source_data = source.get("config_data", {})
    else:
        source_data = _load_filesystem_template(config_type, name, config_root)
        if source_data is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Config '{name}' not found in DB or templates.",
            )

    forked_data = copy.deepcopy(source_data)
    forked_data.update(body.overrides)

    _validate_config_data(config_type, forked_data)

    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Fork name must not be empty."
        )

    result = sync_service.create_config(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        config_type=config_type,
        name=new_name,
        config_data=forked_data,
    )
    return {"id": result["id"], "name": new_name, "forked_from": name}


# ── Router factory ────────────────────────────────────────────────────


def create_config_router(config_root: str = "configs") -> APIRouter:
    """Create the /api/configs router."""
    router = APIRouter(prefix="/api/configs", tags=["configs"])

    # ── Import/Export (existing) ──────────────────────────────────

    @router.post("/import")
    def import_config(
        body: ImportConfigRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Import a YAML configuration file."""
        return _handle_import_config(body, ctx)

    # ── Templates (must be before /{config_type} to avoid shadowing) ──

    @router.get("/templates/{config_type}")
    def list_templates(config_type: str) -> dict[str, Any]:
        """List pre-deployed filesystem configs available for forking."""
        return _handle_list_templates(config_type, config_root)

    # ── CRUD endpoints ────────────────────────────────────────────

    @router.post("/{config_type}")
    def create_config(
        config_type: str,
        body: ConfigCreateRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Create a new config."""
        return _handle_create_config(config_type, body, ctx)

    @router.get("/{config_type}/{name}/export")
    def export_config(
        config_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(*VIEWER_ROLES)),
    ) -> PlainTextResponse:
        """Export a configuration as YAML."""
        return _handle_export_config(config_type, name, ctx)

    @router.post("/{config_type}/{name}/fork")
    def fork_config(
        config_type: str,
        name: str,
        body: ForkRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Fork an existing config into a new tenant-owned copy."""
        return _handle_fork_config(config_type, name, body, ctx, config_root)

    @router.get("/{config_type}/{name}")
    def get_config(
        config_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(*VIEWER_ROLES)),
    ) -> dict[str, Any]:
        """Get a single config by type and name."""
        return _handle_get_config(config_type, name, ctx)

    @router.put("/{config_type}/{name}")
    def update_config(
        config_type: str,
        name: str,
        body: ConfigUpdateRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Update an existing config."""
        return _handle_update_config(config_type, name, body, ctx)

    @router.delete("/{config_type}/{name}")
    def delete_config(
        config_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(ROLE_OWNER)),
    ) -> dict[str, str]:
        """Delete a config."""
        return _handle_delete_config(config_type, name, ctx)

    @router.get("/{config_type}")
    def list_configs(
        config_type: str, ctx: AuthContext = Depends(require_role(*VIEWER_ROLES))
    ) -> dict[str, Any]:
        """List available configurations by type."""
        return _handle_list_configs(config_type, ctx)

    return router
