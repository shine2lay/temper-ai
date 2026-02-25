"""Checkpoint API endpoints for workflow state persistence and resume.

Provides endpoints for listing, retrieving, and resuming from checkpoints.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class CheckpointResumeRequest(BaseModel):
    """POST /api/checkpoints/{checkpoint_id}/resume request body."""

    workflow_id: str
    config: dict[str, Any] = {}


# ── Router factory ────────────────────────────────────────────────────


def _handle_list_checkpoints(workflow_id: str) -> dict[str, Any]:
    """List all checkpoints for a workflow."""
    from temper_ai.workflow.checkpoint_manager import CheckpointManager

    manager = CheckpointManager()
    try:
        checkpoints = manager.list_checkpoints(workflow_id)
        return {
            "checkpoints": checkpoints,
            "total": len(checkpoints),
            "workflow_id": workflow_id,
        }
    except Exception as e:
        logger.exception("Failed to list checkpoints for workflow %s", workflow_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list checkpoints",
        ) from e


def _handle_get_checkpoint(checkpoint_id: str, workflow_id: str) -> dict[str, Any]:
    """Get a single checkpoint by ID."""
    from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError
    from temper_ai.workflow.checkpoint_manager import CheckpointManager

    manager = CheckpointManager()
    try:
        domain_state = manager.load_checkpoint(workflow_id, checkpoint_id)
        return {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "current_stage": domain_state.current_stage,
            "stage_outputs": domain_state.stage_outputs,
        }
    except CheckpointNotFoundError:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Checkpoint '{checkpoint_id}' not found for workflow '{workflow_id}'",
        ) from None
    except Exception as e:
        logger.exception("Failed to load checkpoint %s", checkpoint_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load checkpoint",
        ) from e


def _handle_resume_checkpoint(
    checkpoint_id: str, body: CheckpointResumeRequest
) -> dict[str, Any]:
    """Resume a workflow from a specific checkpoint."""
    from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError
    from temper_ai.workflow.checkpoint_manager import CheckpointManager

    manager = CheckpointManager()
    try:
        domain_state = manager.load_checkpoint(body.workflow_id, checkpoint_id)
    except CheckpointNotFoundError:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Checkpoint '{checkpoint_id}' not found for workflow '{body.workflow_id}'",
        ) from None
    except Exception as e:
        logger.exception("Failed to load checkpoint %s for resume", checkpoint_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load checkpoint for resume",
        ) from e

    return {
        "status": "resumed",
        "checkpoint_id": checkpoint_id,
        "workflow_id": body.workflow_id,
        "resume_stage": domain_state.current_stage,
    }


def create_checkpoint_router(auth_enabled: bool = False) -> APIRouter:
    """Create the checkpoints API router."""
    router = APIRouter(prefix="/api/checkpoints")
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_checkpoints(
        workflow_id: str = Query(..., description="Workflow execution ID")
    ) -> dict[str, Any]:
        """List checkpoints for a workflow execution."""
        return _handle_list_checkpoints(workflow_id)

    @router.get("/{checkpoint_id}", dependencies=read_deps)
    def get_checkpoint(
        checkpoint_id: str,
        workflow_id: str = Query(..., description="Workflow execution ID"),
    ) -> dict[str, Any]:
        """Get a specific checkpoint by ID."""
        return _handle_get_checkpoint(checkpoint_id, workflow_id)

    @router.post("/{checkpoint_id}/resume", dependencies=write_deps)
    async def resume_from_checkpoint(
        checkpoint_id: str, body: CheckpointResumeRequest = Body(...)
    ) -> dict[str, Any]:
        """Resume a workflow from a checkpoint."""
        return _handle_resume_checkpoint(checkpoint_id, body)

    return router
