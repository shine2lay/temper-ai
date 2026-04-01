"""Studio API routes — config CRUD for the workflow designer.

GET    /api/studio/configs/{type}           — list configs
GET    /api/studio/configs/{type}/{name}    — get config
POST   /api/studio/configs/{type}/{name}    — create config
PUT    /api/studio/configs/{type}/{name}    — update config
DELETE /api/studio/configs/{type}/{name}    — delete config
POST   /api/studio/validate/{type}          — validate config

config_type: "workflow" | "stage" | "agent"
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from temper_ai.config import ConfigStore
from temper_ai.config.helpers import ConfigNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio")

_config_store = ConfigStore()


class ConfigBody(BaseModel):
    """Request body for saving/updating a config."""

    config: dict
    schema_version: str = "1.0"


@router.get("/configs/{config_type}")
def list_configs(config_type: str):
    """List all configs of a type."""
    try:
        configs = _config_store.list(config_type=config_type)
        return {"configs": configs, "total": len(configs)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/configs/{config_type}/{name}")
def get_config(config_type: str, name: str):
    """Get a single config by type and name."""
    try:
        return _config_store.get(name, config_type)
    except ConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/configs/{config_type}/{name}", status_code=201)
def create_config(config_type: str, name: str, body: ConfigBody):
    """Create a new config."""
    try:
        config_id = _config_store.put(
            name=name,
            config_type=config_type,
            config=body.config,
            schema_version=body.schema_version,
        )
        return {"id": config_id, "type": config_type, "name": name}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/configs/{config_type}/{name}")
def update_config(config_type: str, name: str, body: ConfigBody):
    """Update an existing config."""
    try:
        config_id = _config_store.put(
            name=name,
            config_type=config_type,
            config=body.config,
            schema_version=body.schema_version,
        )
        return {"id": config_id, "type": config_type, "name": name}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/configs/{config_type}/{name}")
def delete_config(config_type: str, name: str):
    """Delete a config."""
    try:
        deleted = _config_store.delete(name, config_type)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"{config_type} '{name}' not found")
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate/{config_type}")
def validate_config(config_type: str, body: ConfigBody):
    """Validate a config without saving it.

    For workflows: validates the graph structure (circular deps, missing refs, etc.)
    For agents: validates required fields
    """
    errors = []
    warnings = []

    if config_type == "workflow":
        from temper_ai.stage.loader import GraphLoader
        loader = GraphLoader(_config_store)
        try:
            # Temporarily store config for validation
            _config_store.put("__validate_temp", config_type, body.config)
            loader.load_workflow("__validate_temp")
        except Exception as exc:
            errors.append(str(exc))
        finally:
            _config_store.delete("__validate_temp", config_type)

    elif config_type == "agent":
        config = body.config
        if not config.get("name"):
            errors.append("Agent config must have 'name'")
        if not config.get("system_prompt") and not config.get("task_template"):
            warnings.append("Agent has no system_prompt or task_template")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


@router.get("/registry")
def get_registry():
    """Return all registered types for dynamic dropdowns in the Studio UI.

    Each registry is pulled from the actual runtime registries, so custom
    types registered via plugins or startup hooks appear automatically.
    """
    from temper_ai.stage.topology import _GENERATORS
    from temper_ai.agent import AGENT_TYPES
    from temper_ai.llm.providers.factory import _PROVIDER_MAP
    from temper_ai.tools import TOOL_CLASSES
    from temper_ai.safety.engine import POLICY_REGISTRY

    return {
        "strategies": sorted(_GENERATORS.keys()),
        "agent_types": sorted(AGENT_TYPES.keys()),
        "providers": sorted(_PROVIDER_MAP.keys()),
        "tools": sorted(TOOL_CLASSES.keys()),
        "safety_policies": sorted(POLICY_REGISTRY.keys()),
        "condition_operators": [
            "equals", "not_equals", "contains", "in", "exists", "not_exists",
        ],
    }
