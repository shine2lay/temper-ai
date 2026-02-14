"""REST API routes for the dashboard (data query endpoints only).

Workflow execution, health, and validation endpoints are provided by the
server router (src/server/routes.py), which is included in both server
and dashboard modes.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from src.dashboard.data_service import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT

logger = logging.getLogger(__name__)


def _handle_list_workflows(
    data_service: Any,
    limit: int,
    offset: int,
    status: Optional[str],
) -> Any:
    """List workflow executions with pagination."""
    return data_service.list_workflows(limit=limit, offset=offset, status=status)


def _handle_get_workflow(data_service: Any, workflow_id: str) -> Any:
    """Get full workflow snapshot by ID."""
    result = data_service.get_workflow_snapshot(workflow_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


def _handle_get_workflow_trace(data_service: Any, workflow_id: str) -> Any:
    """Get hierarchical trace for a workflow."""
    result = data_service.get_workflow_trace(workflow_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Workflow trace not found")
    return result


def _handle_get_stage(data_service: Any, stage_id: str) -> Any:
    """Get stage execution details."""
    result = data_service.get_stage(stage_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Stage not found")
    return result


def _handle_get_agent(data_service: Any, agent_id: str) -> Any:
    """Get agent execution details."""
    result = data_service.get_agent(agent_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Agent not found")
    return result


def _handle_get_llm_call(data_service: Any, llm_call_id: str) -> Any:
    """Get LLM call details."""
    result = data_service.get_llm_call(llm_call_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="LLM call not found")
    return result


def _handle_get_tool_call(data_service: Any, tool_call_id: str) -> Any:
    """Get tool call details."""
    result = data_service.get_tool_call(tool_call_id)
    if result is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Tool call not found")
    return result


def create_router(data_service: Any) -> APIRouter:
    """Create APIRouter wired to the given DashboardDataService."""
    router = APIRouter()

    @router.get("/workflows")
    def list_workflows(
        limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(0, ge=0),
        status: Optional[str] = Query(None),
    ) -> Any:
        """List workflow executions with pagination."""
        return _handle_list_workflows(data_service, limit, offset, status)

    @router.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> Any:
        """Get full workflow snapshot by ID."""
        return _handle_get_workflow(data_service, workflow_id)

    @router.get("/workflows/{workflow_id}/trace")
    def get_workflow_trace(workflow_id: str) -> Any:
        """Get hierarchical trace for a workflow."""
        return _handle_get_workflow_trace(data_service, workflow_id)

    @router.get("/workflows/{workflow_id}/data-flow")
    def get_data_flow(workflow_id: str) -> Any:
        """Get data flow graph between stages."""
        return data_service.get_data_flow(workflow_id)

    @router.get("/stages/{stage_id}")
    def get_stage(stage_id: str) -> Any:
        """Get stage execution details."""
        return _handle_get_stage(data_service, stage_id)

    @router.get("/agents/{agent_id}")
    def get_agent(agent_id: str) -> Any:
        """Get agent execution details."""
        return _handle_get_agent(data_service, agent_id)

    @router.get("/llm-calls/{llm_call_id}")
    def get_llm_call(llm_call_id: str) -> Any:
        """Get LLM call details."""
        return _handle_get_llm_call(data_service, llm_call_id)

    @router.get("/tool-calls/{tool_call_id}")
    def get_tool_call(tool_call_id: str) -> Any:
        """Get tool call details."""
        return _handle_get_tool_call(data_service, tool_call_id)

    return router
