"""REST API routes for the dashboard (data query endpoints only).

Workflow execution, health, and validation endpoints are provided by the
server router (src/server/routes.py), which is included in both server
and dashboard modes.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.dashboard.data_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
)

logger = logging.getLogger(__name__)


def _handle_list_workflows(
    data_service: Any,
    limit: int,
    offset: int,
    status: str | None,
    tenant_id: str | None = None,
) -> Any:
    """List workflow executions with pagination."""
    return data_service.list_workflows(
        limit=limit, offset=offset, status=status, tenant_id=tenant_id
    )


def _handle_get_workflow(
    data_service: Any, workflow_id: str, tenant_id: str | None = None
) -> Any:
    """Get full workflow snapshot by ID."""
    result = data_service.get_workflow_snapshot(workflow_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


def _handle_get_workflow_trace(
    data_service: Any, workflow_id: str, tenant_id: str | None = None
) -> Any:
    """Get hierarchical trace for a workflow."""
    result = data_service.get_workflow_trace(workflow_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail="Workflow trace not found"
        )
    return result


def _handle_get_stage(
    data_service: Any, stage_id: str, tenant_id: str | None = None
) -> Any:
    """Get stage execution details."""
    result = data_service.get_stage(stage_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Stage not found")
    return result


def _handle_get_agent(
    data_service: Any, agent_id: str, tenant_id: str | None = None
) -> Any:
    """Get agent execution details."""
    result = data_service.get_agent(agent_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Agent not found")
    return result


def _handle_get_llm_call(
    data_service: Any, llm_call_id: str, tenant_id: str | None = None
) -> Any:
    """Get LLM call details."""
    result = data_service.get_llm_call(llm_call_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="LLM call not found")
    return result


def _handle_get_tool_call(
    data_service: Any, tool_call_id: str, tenant_id: str | None = None
) -> Any:
    """Get tool call details."""
    result = data_service.get_tool_call(tool_call_id, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail="Tool call not found"
        )
    return result


def _register_auth_endpoints(router: APIRouter, data_service: Any) -> None:
    """Register all dashboard endpoints with auth dependencies."""

    @router.get("/workflows")
    def list_workflows(
        limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(0, ge=0),
        status: str | None = Query(None),
        ctx: AuthContext = Depends(require_auth),
    ) -> Any:
        """List all workflow executions."""
        return _handle_list_workflows(
            data_service, limit, offset, status, tenant_id=ctx.tenant_id
        )

    @router.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str, ctx: AuthContext = Depends(require_auth)) -> Any:
        """Get a single workflow execution by ID."""
        return _handle_get_workflow(data_service, workflow_id, tenant_id=ctx.tenant_id)

    @router.get("/workflows/{workflow_id}/trace")
    def get_workflow_trace(
        workflow_id: str, ctx: AuthContext = Depends(require_auth)
    ) -> Any:
        """Get trace data for a workflow execution."""
        return _handle_get_workflow_trace(
            data_service, workflow_id, tenant_id=ctx.tenant_id
        )

    @router.get("/workflows/{workflow_id}/data-flow")
    def get_data_flow(
        workflow_id: str, ctx: AuthContext = Depends(require_auth)
    ) -> Any:
        """Get data flow for a workflow execution."""
        return data_service.get_data_flow(workflow_id, tenant_id=ctx.tenant_id)

    @router.get("/stages/{stage_id}")
    def get_stage(stage_id: str, ctx: AuthContext = Depends(require_auth)) -> Any:
        """Get stage details for a workflow execution."""
        return _handle_get_stage(data_service, stage_id, tenant_id=ctx.tenant_id)

    @router.get("/agents/{agent_id}")
    def get_agent(agent_id: str, ctx: AuthContext = Depends(require_auth)) -> Any:
        """Get agent details for a workflow execution."""
        return _handle_get_agent(data_service, agent_id, tenant_id=ctx.tenant_id)

    @router.get("/llm-calls/{llm_call_id}")
    def get_llm_call(llm_call_id: str, ctx: AuthContext = Depends(require_auth)) -> Any:
        """Get LLM call details for a workflow execution."""
        return _handle_get_llm_call(data_service, llm_call_id, tenant_id=ctx.tenant_id)

    @router.get("/tool-calls/{tool_call_id}")
    def get_tool_call(
        tool_call_id: str, ctx: AuthContext = Depends(require_auth)
    ) -> Any:
        """Get tool call details for a workflow execution."""
        return _handle_get_tool_call(
            data_service, tool_call_id, tenant_id=ctx.tenant_id
        )


def _register_dev_endpoints(router: APIRouter, data_service: Any) -> None:
    """Register all dashboard endpoints without auth (dev mode)."""

    @router.get("/workflows")
    def list_workflows_dev(
        limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(0, ge=0),
        status: str | None = Query(None),
    ) -> Any:
        """List workflow executions (dev mode, no auth)."""
        return _handle_list_workflows(data_service, limit, offset, status)

    @router.get("/workflows/{workflow_id}")
    def get_workflow_dev(workflow_id: str) -> Any:
        """Get a workflow execution by ID (dev mode, no auth)."""
        return _handle_get_workflow(data_service, workflow_id)

    @router.get("/workflows/{workflow_id}/trace")
    def get_workflow_trace_dev(workflow_id: str) -> Any:
        """Get trace data (dev mode, no auth)."""
        return _handle_get_workflow_trace(data_service, workflow_id)

    @router.get("/workflows/{workflow_id}/data-flow")
    def get_data_flow_dev(workflow_id: str) -> Any:
        """Get data flow (dev mode, no auth)."""
        return data_service.get_data_flow(workflow_id)

    @router.get("/stages/{stage_id}")
    def get_stage_dev(stage_id: str) -> Any:
        """Get stage details (dev mode, no auth)."""
        return _handle_get_stage(data_service, stage_id)

    @router.get("/agents/{agent_id}")
    def get_agent_dev(agent_id: str) -> Any:
        """Get agent details (dev mode, no auth)."""
        return _handle_get_agent(data_service, agent_id)

    @router.get("/llm-calls/{llm_call_id}")
    def get_llm_call_dev(llm_call_id: str) -> Any:
        """Get LLM call details (dev mode, no auth)."""
        return _handle_get_llm_call(data_service, llm_call_id)

    @router.get("/tool-calls/{tool_call_id}")
    def get_tool_call_dev(tool_call_id: str) -> Any:
        """Get tool call details (dev mode, no auth)."""
        return _handle_get_tool_call(data_service, tool_call_id)


def create_router(data_service: Any, auth_enabled: bool = False) -> APIRouter:
    """Create APIRouter wired to the given DashboardDataService."""
    router = APIRouter()

    if auth_enabled:
        _register_auth_endpoints(router, data_service)
    else:
        _register_dev_endpoints(router, data_service)

    return router
