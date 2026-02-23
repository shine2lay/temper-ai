"""REST API routes for the Workflow Studio config CRUD system."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.responses import PlainTextResponse
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from temper_ai.auth.api_key_auth import AuthContext, require_auth, require_role
from temper_ai.interfaces.dashboard.constants import API_CONFIG_ENDPOINT
from temper_ai.interfaces.dashboard.studio_service import (
    VALID_CONFIG_TYPES,
    StudioService,
)

logger = logging.getLogger(__name__)


def _validate_config_type_param(config_type: str) -> None:
    """Raise HTTP 400 if config_type is not a valid type.

    Args:
        config_type: The config type from the URL path.

    Raises:
        HTTPException: 400 if invalid.
    """
    if config_type not in VALID_CONFIG_TYPES:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid config type '{config_type}'. "
            f"Must be one of: {sorted(VALID_CONFIG_TYPES)}",
        )


def _handle_list_configs(
    studio_service: StudioService,
    config_type: str,
    ctx: AuthContext | None,
) -> dict[str, Any]:
    """List all configs, routing to DB when auth context is present."""
    _validate_config_type_param(config_type)
    try:
        if ctx is not None and studio_service.use_db:
            return studio_service.list_configs_db(config_type, ctx.tenant_id)
        return studio_service.list_configs(config_type)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _handle_get_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
    ctx: AuthContext | None,
) -> dict[str, Any]:
    """Get a config, routing to DB when auth context is present."""
    _validate_config_type_param(config_type)
    try:
        if ctx is not None and studio_service.use_db:
            return studio_service.get_config_db(config_type, name, ctx.tenant_id)
        return studio_service.get_config(config_type, name)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_get_config_raw(
    studio_service: StudioService,
    config_type: str,
    name: str,
) -> PlainTextResponse:
    """Get raw YAML text of a config file (file-system only)."""
    _validate_config_type_param(config_type)
    try:
        raw_yaml = studio_service.get_config_raw(config_type, name)
        return PlainTextResponse(content=raw_yaml, media_type="text/yaml")
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_create_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
    data: dict[str, Any],
    ctx: AuthContext | None,
) -> dict[str, Any]:
    """Create a config, routing to DB when auth context is present."""
    _validate_config_type_param(config_type)
    try:
        if ctx is not None and studio_service.use_db:
            return studio_service.create_config_db(
                config_type, name, data, ctx.tenant_id, ctx.user_id
            )
        return studio_service.create_config(config_type, name, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(exc)) from exc


def _handle_update_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
    data: dict[str, Any],
    ctx: AuthContext | None,
) -> dict[str, Any]:
    """Update a config, routing to DB when auth context is present."""
    _validate_config_type_param(config_type)
    try:
        if ctx is not None and studio_service.use_db:
            return studio_service.update_config_db(
                config_type, name, data, ctx.tenant_id, ctx.user_id
            )
        return studio_service.update_config(config_type, name, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_delete_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
    ctx: AuthContext | None,
) -> dict[str, Any]:
    """Delete a config, routing to DB when auth context is present."""
    _validate_config_type_param(config_type)
    try:
        if ctx is not None and studio_service.use_db:
            return studio_service.delete_config_db(config_type, name, ctx.tenant_id)
        return studio_service.delete_config(config_type, name)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_validate_config(
    studio_service: StudioService,
    config_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Validate config data without saving."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.validate_config(config_type, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _handle_get_schema(
    studio_service: StudioService, config_type: str
) -> dict[str, Any]:
    """Get JSON Schema for a config type."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.get_schema(config_type)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _register_studio_auth_endpoints(
    router: APIRouter,
    studio_service: StudioService,
    read_dep: Any,
    write_dep: Any,
    admin_dep: Any,
) -> None:
    """Register studio CRUD endpoints with auth dependencies."""

    @router.get("/configs/{config_type}", dependencies=[read_dep])
    def list_configs(
        config_type: str,
        ctx: AuthContext = read_dep,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """List all studio configurations."""
        return _handle_list_configs(studio_service, config_type, ctx)

    @router.get(API_CONFIG_ENDPOINT, dependencies=[read_dep])
    def get_config(
        config_type: str,
        name: str,
        ctx: AuthContext = read_dep,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Get a studio configuration by type and name."""
        return _handle_get_config(studio_service, config_type, name, ctx)

    @router.get("/configs/{config_type}/{name}/raw", dependencies=[read_dep])
    def get_config_raw(config_type: str, name: str) -> PlainTextResponse:
        """Get raw YAML content of a configuration."""
        return _handle_get_config_raw(studio_service, config_type, name)

    @router.post(
        API_CONFIG_ENDPOINT, status_code=HTTP_201_CREATED, dependencies=[write_dep]
    )
    def create_config(
        config_type: str,
        name: str,
        data: dict[str, Any] = Body(...),
        ctx: AuthContext = write_dep,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Create a new studio configuration."""
        return _handle_create_config(studio_service, config_type, name, data, ctx)

    @router.put(API_CONFIG_ENDPOINT, dependencies=[write_dep])
    def update_config(
        config_type: str,
        name: str,
        data: dict[str, Any] = Body(...),
        ctx: AuthContext = write_dep,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Update an existing studio configuration."""
        return _handle_update_config(studio_service, config_type, name, data, ctx)

    _register_studio_admin_endpoints(router, studio_service, write_dep, admin_dep)


def _register_studio_admin_endpoints(
    router: APIRouter,
    studio_service: StudioService,
    write_dep: Any,
    admin_dep: Any,
) -> None:
    """Register studio delete and validate endpoints with admin/write deps."""

    @router.delete(API_CONFIG_ENDPOINT, dependencies=[admin_dep])
    def delete_config(
        config_type: str,
        name: str,
        ctx: AuthContext = admin_dep,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Delete a studio configuration."""
        return _handle_delete_config(studio_service, config_type, name, ctx)

    @router.post("/validate/{config_type}", dependencies=[write_dep])
    def validate_config(
        config_type: str, data: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        """Validate a studio configuration."""
        return _handle_validate_config(studio_service, config_type, data)


def _register_studio_no_auth_endpoints(
    router: APIRouter,
    studio_service: StudioService,
) -> None:
    """Register studio CRUD endpoints without auth (dev mode)."""

    @router.get("/configs/{config_type}")
    def list_configs_no_auth(config_type: str) -> dict[str, Any]:  # noqa: duplicate
        """List studio configurations (no auth)."""
        return _handle_list_configs(studio_service, config_type, None)

    @router.get(API_CONFIG_ENDPOINT)
    def get_config_no_auth(
        config_type: str, name: str
    ) -> dict[str, Any]:  # noqa: duplicate
        """Get a configuration (no auth)."""
        return _handle_get_config(studio_service, config_type, name, None)

    @router.get("/configs/{config_type}/{name}/raw")
    def get_config_raw_no_auth(
        config_type: str, name: str
    ) -> PlainTextResponse:  # noqa: duplicate
        """Get raw YAML content (no auth)."""
        return _handle_get_config_raw(studio_service, config_type, name)

    @router.post(API_CONFIG_ENDPOINT, status_code=HTTP_201_CREATED)
    def create_config_no_auth(
        config_type: str,
        name: str,
        data: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:  # noqa: duplicate
        """Create a configuration (no auth)."""
        return _handle_create_config(studio_service, config_type, name, data, None)

    @router.put(API_CONFIG_ENDPOINT)
    def update_config_no_auth(
        config_type: str,
        name: str,
        data: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:  # noqa: duplicate
        """Update a configuration (no auth)."""
        return _handle_update_config(studio_service, config_type, name, data, None)

    @router.delete(API_CONFIG_ENDPOINT)
    def delete_config_no_auth(
        config_type: str, name: str
    ) -> dict[str, Any]:  # noqa: duplicate
        """Delete a configuration (no auth)."""
        return _handle_delete_config(studio_service, config_type, name, None)

    @router.post("/validate/{config_type}")
    def validate_config_no_auth(
        config_type: str,
        data: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:  # noqa: duplicate
        """Validate a configuration (no auth)."""
        return _handle_validate_config(studio_service, config_type, data)


def create_studio_router(
    studio_service: StudioService, auth_enabled: bool = False
) -> APIRouter:
    """Create APIRouter for Workflow Studio config CRUD endpoints.

    Args:
        studio_service: StudioService instance providing business logic.
        auth_enabled: When True, apply role-based auth to routes.

    Returns:
        Configured APIRouter with all studio endpoints.
    """
    router = APIRouter()

    if auth_enabled:
        _read_dep = Depends(require_auth)
        _write_dep = Depends(require_role("owner", "editor"))
        _admin_dep = Depends(require_role("owner"))
        _register_studio_auth_endpoints(
            router, studio_service, _read_dep, _write_dep, _admin_dep
        )
    else:
        _register_studio_no_auth_endpoints(router, studio_service)

    # Schema endpoint is always public — registered outside the if/else.
    @router.get("/schemas/{config_type}")
    def get_schema(config_type: str) -> dict[str, Any]:
        """Get JSON Schema for a config type (public, no auth required)."""
        return _handle_get_schema(studio_service, config_type)

    return router
