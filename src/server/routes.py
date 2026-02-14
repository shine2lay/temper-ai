"""Server-mode API endpoints for MAF Server.

Provides endpoints for programmatic workflow execution, health checks,
and event retrieval — separate from the dashboard UI routes.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.status import (
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from src.server.health import check_health, check_readiness

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────

class RunRequest(BaseModel):
    """POST /api/runs request body."""

    workflow: str
    inputs: Dict[str, Any] = {}
    workspace: Optional[str] = None
    run_id: Optional[str] = None
    config: Dict[str, Any] = {}


class RunResponse(BaseModel):
    """POST /api/runs response body."""

    execution_id: str
    status: str = "pending"
    message: str = "Workflow execution started"


class ValidateRequest(BaseModel):
    """POST /api/validate request body."""

    workflow: str


# ── Router factory ────────────────────────────────────────────────────

def create_server_router(
    execution_service: Any,
    data_service: Any,
    config_root: str = "configs",
) -> APIRouter:
    """Create the server-mode API router.

    Args:
        execution_service: WorkflowExecutionService instance.
        data_service: DashboardDataService for querying recorded data.
        config_root: Config directory root path.
    """
    router = APIRouter()

    # ── Health ─────────────────────────────────────────────────────

    @router.get("/health")
    def health() -> Dict[str, Any]:
        """Liveness probe — always 200 if the process is up."""
        return check_health().model_dump()

    @router.get("/health/ready")
    def readiness(request: Request) -> Dict[str, Any]:
        """Readiness probe — 503 when draining."""
        gate = True
        if hasattr(request.app.state, "shutdown_manager"):
            gate = request.app.state.shutdown_manager.readiness_gate

        resp = check_readiness(
            execution_service=execution_service,
            readiness_gate=gate,
        )
        if resp.status != "ready":
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=resp.model_dump())
        return resp.model_dump()

    # ── Workflow runs ──────────────────────────────────────────────

    @router.post("/runs", response_model=RunResponse)
    async def create_run(body: RunRequest = Body(...)) -> RunResponse:
        """Start a workflow execution."""
        try:
            execution_id = await execution_service.execute_workflow_async(
                workflow_path=body.workflow,
                input_data=body.inputs,
                workspace=body.workspace,
                run_id=body.run_id,
            )
            return RunResponse(execution_id=execution_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except Exception as e:
            logger.exception("Run creation failed")
            raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error: workflow execution failed") from e

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> Dict[str, Any]:
        """Get execution status by ID."""
        try:
            result = await execution_service.get_execution_status(run_id)
        except Exception:
            logger.exception("Failed to retrieve run status for %s", run_id)
            raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve run status")
        if result is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Run not found")
        return result

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> Dict[str, Any]:
        """Cancel a running workflow execution."""
        cancelled = await execution_service.cancel_execution(run_id)
        if not cancelled:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="Run not found or already completed",
            )
        return {"status": "cancelled", "execution_id": run_id}

    @router.get("/runs/{run_id}/events")
    async def get_run_events(
        run_id: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        """Get events for a specific run."""
        # Look up the workflow_id from execution metadata
        meta = await execution_service.get_execution_status(run_id)
        if meta is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Run not found")

        workflow_id = meta.get("workflow_id")
        if not workflow_id:
            return {"events": [], "total": 0}

        try:
            from src.observability.backends.sql_backend import SQLObservabilityBackend

            backend = SQLObservabilityBackend(buffer=False)
            events = backend.get_run_events(
                workflow_id=workflow_id, limit=limit, offset=offset
            )
            return {"events": events, "total": len(events)}
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to query events: %s", e)
            return {"events": [], "total": 0}

    # ── Validation ────────────────────────────────────────────────

    @router.post("/validate")
    def validate_workflow(body: ValidateRequest = Body(...)) -> Dict[str, Any]:
        """Validate a workflow config without executing."""
        # Security: prevent path traversal
        config_root_resolved = Path(config_root).resolve()
        workflow_file = (config_root_resolved / body.workflow).resolve()
        try:
            workflow_file.relative_to(config_root_resolved)
        except ValueError:
            return {"valid": False, "errors": ["Invalid workflow path"], "warnings": []}
        if not workflow_file.exists():
            return {"valid": False, "errors": [f"File not found: {body.workflow}"], "warnings": []}

        try:
            with open(workflow_file) as f:
                wf_config = yaml.safe_load(f)
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "errors": [f"YAML parse error: {exc}"], "warnings": []}

        if not wf_config:
            return {"valid": False, "errors": ["Empty workflow file"], "warnings": []}

        errors: List[str] = []
        try:
            from src.compiler.schemas import WorkflowConfig as WfSchema
            WfSchema(**wf_config)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Schema error: {exc}")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": []}

    # ── Available workflows ───────────────────────────────────────

    @router.get("/workflows/available")
    def list_available_workflows() -> Dict[str, Any]:
        """List workflow config files from config_root."""
        workflows_dir = Path(config_root) / "workflows"
        if not workflows_dir.exists():
            return {"workflows": [], "total": 0}

        workflows: List[Dict[str, Any]] = []
        for path in sorted(workflows_dir.glob("*.yaml")):
            try:
                with open(path) as f:
                    config = yaml.safe_load(f)
                wf = config.get("workflow", {}) if config else {}
                workflows.append({
                    "path": f"workflows/{path.name}",
                    "name": wf.get("name", path.stem),
                    "description": wf.get("description", ""),
                    "version": wf.get("version", ""),
                    "tags": wf.get("tags", []),
                    "inputs": wf.get("inputs", {}),
                    "use_cases": wf.get("use_cases", []),
                })
            except Exception:  # noqa: BLE001
                continue

        return {"workflows": workflows, "total": len(workflows)}

    return router
