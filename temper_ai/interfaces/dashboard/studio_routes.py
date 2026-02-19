"""REST API routes for the Workflow Studio config CRUD system."""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException
from starlette.responses import PlainTextResponse
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from temper_ai.interfaces.dashboard.constants import API_CONFIG_ENDPOINT
from temper_ai.interfaces.dashboard.studio_service import VALID_CONFIG_TYPES, StudioService

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


def _handle_list_configs(studio_service: StudioService, config_type: str) -> Dict[str, Any]:
    """List all configs of the given type."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.list_configs(config_type)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _handle_get_config(studio_service: StudioService, config_type: str, name: str) -> Dict[str, Any]:
    """Get a config as parsed JSON."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.get_config(config_type, name)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_get_config_raw(studio_service: StudioService, config_type: str, name: str) -> PlainTextResponse:
    """Get raw YAML text of a config file."""
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
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new config file."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.create_config(config_type, name, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(exc)) from exc


def _handle_update_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Update an existing config file."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.update_config(config_type, name, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_delete_config(
    studio_service: StudioService,
    config_type: str,
    name: str,
) -> Dict[str, Any]:
    """Delete a config file."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.delete_config(config_type, name)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _handle_validate_config(
    studio_service: StudioService,
    config_type: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate config data without saving."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.validate_config(config_type, data)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _handle_get_schema(studio_service: StudioService, config_type: str) -> Dict[str, Any]:
    """Get JSON Schema for a config type."""
    _validate_config_type_param(config_type)
    try:
        return studio_service.get_schema(config_type)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def create_studio_router(studio_service: StudioService) -> APIRouter:
    """Create APIRouter for Workflow Studio config CRUD endpoints.

    Args:
        studio_service: StudioService instance providing business logic.

    Returns:
        Configured APIRouter with all studio endpoints.
    """
    router = APIRouter()

    @router.get("/configs/{config_type}")
    def list_configs(config_type: str) -> Dict[str, Any]:
        """List all configs of the given type."""
        return _handle_list_configs(studio_service, config_type)

    @router.get(API_CONFIG_ENDPOINT)
    def get_config(config_type: str, name: str) -> Dict[str, Any]:
        """Get a config as parsed JSON."""
        return _handle_get_config(studio_service, config_type, name)

    @router.get("/configs/{config_type}/{name}/raw")
    def get_config_raw(config_type: str, name: str) -> PlainTextResponse:
        """Get raw YAML text of a config file."""
        return _handle_get_config_raw(studio_service, config_type, name)

    @router.post(API_CONFIG_ENDPOINT, status_code=HTTP_201_CREATED)
    def create_config(
        config_type: str,
        name: str,
        data: Dict[str, Any] = Body(...),
    ) -> Dict[str, Any]:
        """Create a new config file."""
        return _handle_create_config(studio_service, config_type, name, data)

    @router.put(API_CONFIG_ENDPOINT)
    def update_config(
        config_type: str,
        name: str,
        data: Dict[str, Any] = Body(...),
    ) -> Dict[str, Any]:
        """Update an existing config file."""
        return _handle_update_config(studio_service, config_type, name, data)

    @router.delete(API_CONFIG_ENDPOINT)
    def delete_config(config_type: str, name: str) -> Dict[str, Any]:
        """Delete a config file."""
        return _handle_delete_config(studio_service, config_type, name)

    @router.post("/validate/{config_type}")
    def validate_config(
        config_type: str,
        data: Dict[str, Any] = Body(...),
    ) -> Dict[str, Any]:
        """Validate config data without saving."""
        return _handle_validate_config(studio_service, config_type, data)

    @router.get("/schemas/{config_type}")
    def get_schema(config_type: str) -> Dict[str, Any]:
        """Get JSON Schema for a config type."""
        return _handle_get_schema(studio_service, config_type)

    return router
