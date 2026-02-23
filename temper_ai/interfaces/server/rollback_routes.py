"""Rollback API routes — query and execute manual rollbacks."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class RollbackExecuteRequest(BaseModel):
    """POST /api/rollbacks/{rollback_id}/execute request body."""

    operator: str
    reason: str
    dry_run: bool = False
    force: bool = False


# ── Router factory ────────────────────────────────────────────────────


def _handle_list_rollbacks(
    workflow_id: str | None,
    agent_id: str | None,
    limit: int,
) -> dict[str, Any]:
    """List available rollback snapshots with optional filtering."""
    from temper_ai.safety.rollback import RollbackManager
    from temper_ai.safety.rollback_api import RollbackAPI

    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)
        snapshots = api.list_snapshots(
            workflow_id=workflow_id, agent_id=agent_id, limit=limit
        )
        result = [
            {
                "id": s.id,
                "action": s.action,
                "context": s.context,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "file_count": len(s.file_snapshots),
            }
            for s in snapshots
        ]
        return {"rollbacks": result, "total": len(result)}
    except Exception as e:
        logger.exception("Failed to list rollback snapshots")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list rollback snapshots",
        ) from e


def _handle_get_rollback(rollback_id: str) -> dict[str, Any]:
    """Get detailed information about a specific rollback snapshot."""
    from temper_ai.safety.rollback import RollbackManager
    from temper_ai.safety.rollback_api import RollbackAPI

    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)
        details = api.get_snapshot_details(rollback_id)
    except Exception as e:
        logger.exception("Failed to retrieve rollback snapshot %s", rollback_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve rollback snapshot",
        ) from e

    if details is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Rollback snapshot not found: {rollback_id}",
        )
    return details


def _handle_execute_rollback(
    rollback_id: str, body: RollbackExecuteRequest
) -> dict[str, Any]:
    """Execute a manual rollback to a specific snapshot."""
    from temper_ai.safety.rollback import RollbackManager
    from temper_ai.safety.rollback_api import RollbackAPI

    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)
        result = api.execute_manual_rollback(
            snapshot_id=rollback_id,
            operator=body.operator,
            reason=body.reason,
            dry_run=body.dry_run,
            force=body.force,
        )
        return {
            "snapshot_id": result.snapshot_id,
            "success": result.success,
            "dry_run": body.dry_run,
            "files_restored": result.reverted_items,
            "metadata": result.metadata,
        }
    except ValueError as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to execute rollback %s", rollback_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rollback execution failed",
        ) from e


def create_rollback_router(auth_enabled: bool = False) -> APIRouter:
    """Create the rollbacks API router."""
    router = APIRouter(prefix="/api/rollbacks", tags=["rollbacks"])
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_rollbacks(
        workflow_id: str | None = Query(None, description="Filter by workflow ID"),
        agent_id: str | None = Query(None, description="Filter by agent ID"),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """List available rollback points."""
        return _handle_list_rollbacks(workflow_id, agent_id, limit)

    @router.get("/{rollback_id}", dependencies=read_deps)
    def get_rollback(rollback_id: str) -> dict[str, Any]:
        """Get details for a specific rollback point."""
        return _handle_get_rollback(rollback_id)

    @router.post("/{rollback_id}/execute", dependencies=write_deps)
    def execute_rollback(
        rollback_id: str, body: RollbackExecuteRequest = Body(...)
    ) -> dict[str, Any]:
        """Execute a rollback operation."""
        return _handle_execute_rollback(rollback_id, body)

    return router
