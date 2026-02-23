"""Server-mode API endpoints for MAF Server.

Provides endpoints for programmatic workflow execution, health checks,
and event retrieval — separate from the dashboard UI routes.
"""

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from temper_ai.auth.api_key_auth import AuthContext, require_auth, require_role
from temper_ai.interfaces.server.health import check_health, check_readiness

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class RunRequest(BaseModel):
    """POST /api/runs request body."""

    workflow: str
    inputs: dict[str, Any] = {}
    workspace: str | None = None
    run_id: str | None = None
    config: dict[str, Any] = {}


class RunResponse(BaseModel):
    """POST /api/runs response body."""

    execution_id: str
    status: str = "pending"
    message: str = "Workflow execution started"


class ValidateRequest(BaseModel):
    """POST /api/validate request body."""

    workflow: str


# ── Router factory ────────────────────────────────────────────────────


def _handle_health() -> dict[str, Any]:
    """Liveness probe — always 200 if the process is up."""
    return check_health().model_dump()


def _handle_readiness(execution_service: Any, request: Request) -> dict[str, Any]:
    """Readiness probe — 503 when draining."""
    gate = True
    if hasattr(request.app.state, "shutdown_manager"):
        gate = request.app.state.shutdown_manager.readiness_gate

    resp = check_readiness(
        execution_service=execution_service,
        readiness_gate=gate,
    )
    if resp.status != "ready":
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=resp.model_dump()
        )
    return resp.model_dump()


async def _handle_create_run(
    execution_service: Any,
    body: RunRequest,
    config_root: str,
    tenant_id: str | None = None,
) -> RunResponse:
    """Start a workflow execution."""
    # Security: prevent path traversal
    config_root_resolved = Path(config_root).resolve()
    workflow_file = (config_root_resolved / body.workflow).resolve()
    try:
        workflow_file.relative_to(config_root_resolved)
    except ValueError:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Invalid workflow path"
        )

    try:
        execution_id = await execution_service.execute_workflow_async(
            workflow_path=body.workflow,
            input_data=body.inputs,
            workspace=body.workspace,
            run_id=body.run_id,
            tenant_id=tenant_id,
        )
        return RunResponse(execution_id=execution_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.exception("Run creation failed")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error: workflow execution failed",
        ) from e


async def _handle_list_runs(
    execution_service: Any,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """List workflow executions with optional filtering."""
    from temper_ai.interfaces.dashboard.execution_service import WorkflowExecutionStatus

    status_enum = None
    if status is not None:
        try:
            status_enum = WorkflowExecutionStatus(status)
        except ValueError:
            return {"runs": [], "total": 0}

    runs = await execution_service.list_executions(
        status=status_enum,
        limit=limit,
        offset=offset,
    )
    return {"runs": runs, "total": len(runs)}


async def _handle_get_run(execution_service: Any, run_id: str) -> dict[str, Any]:
    """Get execution status by ID."""
    try:
        result = await execution_service.get_execution_status(run_id)
    except Exception:
        logger.exception("Failed to retrieve run status for %s", run_id)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve run status",
        )
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Run not found")
    return cast(dict[str, Any], result)


async def _handle_cancel_run(execution_service: Any, run_id: str) -> dict[str, Any]:
    """Cancel a running workflow execution."""
    cancelled = await execution_service.cancel_execution(run_id)
    if not cancelled:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Run not found or already completed",
        )
    return {"status": "cancelled", "execution_id": run_id}


async def _handle_get_run_events(
    execution_service: Any,
    run_id: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Get events for a specific run."""
    # Look up the workflow_id from execution metadata
    meta = await execution_service.get_execution_status(run_id)
    if meta is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Run not found")

    workflow_id = meta.get("workflow_id")
    if not workflow_id:
        return {"events": [], "total": 0}

    try:
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend

        backend = SQLObservabilityBackend(buffer=False)
        events = backend.get_run_events(
            workflow_id=workflow_id, limit=limit, offset=offset
        )
        return {"events": events, "total": len(events)}
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to query events: %s", e)
        return {"events": [], "total": 0}


def _handle_validate_workflow(
    config_root: str, body: ValidateRequest
) -> dict[str, Any]:
    """Validate a workflow config without executing."""
    # Security: prevent path traversal
    config_root_resolved = Path(config_root).resolve()
    workflow_file = (config_root_resolved / body.workflow).resolve()
    try:
        workflow_file.relative_to(config_root_resolved)
    except ValueError:
        return {"valid": False, "errors": ["Invalid workflow path"], "warnings": []}
    if not workflow_file.exists():
        return {
            "valid": False,
            "errors": [f"File not found: {body.workflow}"],
            "warnings": [],
        }

    from temper_ai.shared.utils.exceptions import ConfigValidationError
    from temper_ai.workflow.runtime import RuntimeConfig, WorkflowRuntime

    errors: list[str] = []
    try:
        rt = WorkflowRuntime(config=RuntimeConfig(config_root=config_root))
        rt.load_config(str(workflow_file))
    except (ConfigValidationError, ValueError) as exc:
        errors.append(str(exc))
    except FileNotFoundError as exc:
        errors.append(str(exc))

    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def _handle_list_available_workflows(config_root: str) -> dict[str, Any]:
    """List workflow config files from config_root."""
    workflows_dir = Path(config_root) / "workflows"
    if not workflows_dir.exists():
        return {"workflows": [], "total": 0}

    workflows: list[dict[str, Any]] = []
    for path in sorted(workflows_dir.glob("*.yaml")):
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            wf = config.get("workflow", {}) if config else {}
            workflows.append(
                {
                    "path": f"workflows/{path.name}",
                    "name": wf.get("name", path.stem),
                    "description": wf.get("description", ""),
                    "version": wf.get("version", ""),
                    "tags": wf.get("tags", []),
                    "inputs": wf.get("inputs", {}),
                    "use_cases": wf.get("use_cases", []),
                }
            )
        except Exception:  # noqa: BLE001
            continue

    return {"workflows": workflows, "total": len(workflows)}


def _register_run_routes(
    router: APIRouter,
    execution_service: Any,
    config_root: str = "configs",
    auth_enabled: bool = False,
) -> None:
    """Register run CRUD routes on the router."""
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []
    read_deps = [Depends(require_auth)] if auth_enabled else []

    if auth_enabled:

        @router.post("/runs", response_model=RunResponse)
        async def create_run(
            body: RunRequest = Body(...),
            ctx: AuthContext = Depends(require_role("owner", "editor")),
        ) -> RunResponse:
            """Start a workflow execution."""
            return await _handle_create_run(
                execution_service, body, config_root, tenant_id=ctx.tenant_id
            )

    else:

        @router.post("/runs", response_model=RunResponse, dependencies=write_deps)
        async def create_run(body: RunRequest = Body(...)) -> RunResponse:  # type: ignore[misc]
            """Start a workflow execution."""
            return await _handle_create_run(execution_service, body, config_root)

    @router.get("/runs", dependencies=read_deps)
    async def list_runs(
        status: str | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """List workflow executions."""
        return await _handle_list_runs(execution_service, status, limit, offset)

    @router.get("/runs/{run_id}", dependencies=read_deps)
    async def get_run(run_id: str) -> dict[str, Any]:
        """Get execution status by ID."""
        return await _handle_get_run(execution_service, run_id)

    @router.post("/runs/{run_id}/cancel", dependencies=write_deps)
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """Cancel a running workflow execution."""
        return await _handle_cancel_run(execution_service, run_id)

    @router.get("/runs/{run_id}/events", dependencies=read_deps)
    async def get_run_events(
        run_id: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """Get events for a specific run."""
        return await _handle_get_run_events(execution_service, run_id, limit, offset)


def create_server_router(
    execution_service: Any,
    data_service: Any,
    config_root: str = "configs",
    auth_enabled: bool = False,
) -> APIRouter:
    """Create the server-mode API router.

    Args:
        execution_service: WorkflowExecutionService instance.
        data_service: DashboardDataService for querying recorded data.
        config_root: Config directory root path.
        auth_enabled: When True, attach auth dependencies to protected routes.
    """
    router = APIRouter()
    read_deps = [Depends(require_auth)] if auth_enabled else []

    @router.get("/health")
    def health() -> dict[str, Any]:
        """Liveness probe — always 200 if the process is up."""
        return _handle_health()

    @router.get("/health/ready")
    def readiness(request: Request) -> dict[str, Any]:
        """Readiness probe — 503 when draining."""
        return _handle_readiness(execution_service, request)

    _register_run_routes(
        router, execution_service, config_root=config_root, auth_enabled=auth_enabled
    )

    @router.post("/validate", dependencies=read_deps)
    def validate_workflow(body: ValidateRequest = Body(...)) -> dict[str, Any]:
        """Validate a workflow config without executing."""
        return _handle_validate_workflow(config_root, body)

    @router.get("/workflows/available", dependencies=read_deps)
    def list_available_workflows() -> dict[str, Any]:
        """List workflow config files from config_root."""
        return _handle_list_available_workflows(config_root)

    return router
