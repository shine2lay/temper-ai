"""Profile CRUD endpoints for reusable configuration profiles.

Provides create, list, get, update, delete for all 6 profile types
(llm, safety, error_handling, observability, memory, budget).
Prefix: /api/profiles.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from temper_ai.auth.api_key_auth import AuthContext, require_role
from temper_ai.storage.database.models_tenancy import VALID_PROFILE_TYPES

logger = logging.getLogger(__name__)

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_OWNER = "owner"

EDITOR_ROLES = (ROLE_EDITOR, ROLE_OWNER)
VIEWER_ROLES = (ROLE_VIEWER, ROLE_EDITOR, ROLE_OWNER)


# ── Request models ────────────────────────────────────────────────────


class ProfileCreateRequest(BaseModel):
    """POST /api/profiles/{type} request body."""

    name: str
    description: str = ""
    config_data: dict[str, Any]


class ProfileUpdateRequest(BaseModel):
    """PUT /api/profiles/{type}/{name} request body."""

    description: str | None = None
    config_data: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────


def _validate_profile_type(profile_type: str) -> str:
    """Validate and normalize profile_type, raising HTTP 400 if invalid."""
    normalized = profile_type.strip().lower().replace("-", "_")
    if normalized not in VALID_PROFILE_TYPES:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid profile type '{profile_type}'. "
                f"Must be one of: {sorted(VALID_PROFILE_TYPES)}"
            ),
        )
    return normalized


def _get_profile_model(profile_type: str) -> type:
    """Get the DB model class for a profile type."""
    from temper_ai.storage.database.models_tenancy import PROFILE_DB_MAP

    return PROFILE_DB_MAP[profile_type]


# ── Handlers ──────────────────────────────────────────────────────────


def _handle_create_profile(
    profile_type: str, body: ProfileCreateRequest, ctx: AuthContext
) -> dict[str, Any]:
    """Create a new profile."""
    profile_type = _validate_profile_type(profile_type)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Profile name must not be empty."
        )

    model_cls = _get_profile_model(profile_type)

    from temper_ai.storage.database.manager import get_session

    with get_session() as session:
        existing = (
            session.query(model_cls)
            .filter_by(tenant_id=ctx.tenant_id, name=name)
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"Profile '{name}' already exists for type '{profile_type}'.",
            )

        record_id = str(uuid.uuid4())
        record = model_cls(
            id=record_id,
            tenant_id=ctx.tenant_id,
            name=name,
            description=body.description,
            config_data=body.config_data,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(record)

    return {"id": record_id, "name": name, "profile_type": profile_type}


def _handle_list_profiles(profile_type: str, ctx: AuthContext) -> dict[str, Any]:
    """List all profiles of a given type for the tenant."""
    profile_type = _validate_profile_type(profile_type)
    model_cls = _get_profile_model(profile_type)

    from temper_ai.storage.database.manager import get_session

    with get_session() as session:
        records = session.query(model_cls).filter_by(tenant_id=ctx.tenant_id).all()
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


def _handle_get_profile(
    profile_type: str, name: str, ctx: AuthContext
) -> dict[str, Any]:
    """Get a single profile by type and name."""
    profile_type = _validate_profile_type(profile_type)
    model_cls = _get_profile_model(profile_type)

    from temper_ai.storage.database.manager import get_session

    with get_session() as session:
        record = (
            session.query(model_cls)
            .filter_by(tenant_id=ctx.tenant_id, name=name)
            .first()
        )
        if record is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Profile '{name}' of type '{profile_type}' not found.",
            )
        return {
            "id": record.id,
            "name": record.name,
            "description": getattr(record, "description", ""),
            "config_data": record.config_data,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }


def _handle_update_profile(
    profile_type: str,
    name: str,
    body: ProfileUpdateRequest,
    ctx: AuthContext,
) -> dict[str, Any]:
    """Update an existing profile."""
    profile_type = _validate_profile_type(profile_type)
    model_cls = _get_profile_model(profile_type)

    from temper_ai.storage.database.datetime_utils import utcnow
    from temper_ai.storage.database.manager import get_session

    with get_session() as session:
        record = (
            session.query(model_cls)
            .filter_by(tenant_id=ctx.tenant_id, name=name)
            .first()
        )
        if record is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Profile '{name}' of type '{profile_type}' not found.",
            )

        if body.config_data is not None:
            record.config_data = body.config_data
        if body.description is not None:
            record.description = body.description
        record.updated_by = ctx.user_id
        record.updated_at = utcnow()

    return {"id": record.id, "name": record.name, "profile_type": profile_type}


def _handle_delete_profile(
    profile_type: str, name: str, ctx: AuthContext
) -> dict[str, str]:
    """Delete a profile."""
    profile_type = _validate_profile_type(profile_type)
    model_cls = _get_profile_model(profile_type)

    from temper_ai.storage.database.manager import get_session

    with get_session() as session:
        record = (
            session.query(model_cls)
            .filter_by(tenant_id=ctx.tenant_id, name=name)
            .first()
        )
        if record is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Profile '{name}' of type '{profile_type}' not found.",
            )
        session.delete(record)

    return {"status": "deleted"}


# ── Router factory ────────────────────────────────────────────────────


def create_profile_router() -> APIRouter:
    """Create the /api/profiles router."""
    router = APIRouter(prefix="/api/profiles", tags=["profiles"])

    @router.post("/{profile_type}")
    def create_profile(
        profile_type: str,
        body: ProfileCreateRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Create a new profile."""
        return _handle_create_profile(profile_type, body, ctx)

    @router.get("/{profile_type}")
    def list_profiles(
        profile_type: str,
        ctx: AuthContext = Depends(require_role(*VIEWER_ROLES)),
    ) -> dict[str, Any]:
        """List profiles by type."""
        return _handle_list_profiles(profile_type, ctx)

    @router.get("/{profile_type}/{name}")
    def get_profile(
        profile_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(*VIEWER_ROLES)),
    ) -> dict[str, Any]:
        """Get a single profile."""
        return _handle_get_profile(profile_type, name, ctx)

    @router.put("/{profile_type}/{name}")
    def update_profile(
        profile_type: str,
        name: str,
        body: ProfileUpdateRequest,
        ctx: AuthContext = Depends(require_role(*EDITOR_ROLES)),
    ) -> dict[str, Any]:
        """Update a profile."""
        return _handle_update_profile(profile_type, name, body, ctx)

    @router.delete("/{profile_type}/{name}")
    def delete_profile(
        profile_type: str,
        name: str,
        ctx: AuthContext = Depends(require_role(ROLE_OWNER)),
    ) -> dict[str, str]:
        """Delete a profile."""
        return _handle_delete_profile(profile_type, name, ctx)

    return router
