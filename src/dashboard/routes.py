"""REST API routes for the dashboard."""
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.dashboard.data_service import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT

logger = logging.getLogger(__name__)


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
        return data_service.list_workflows(limit=limit, offset=offset, status=status)

    @router.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> Any:
        """Get full workflow snapshot by ID."""
        result = data_service.get_workflow_snapshot(workflow_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return result

    @router.get("/workflows/{workflow_id}/trace")
    def get_workflow_trace(workflow_id: str) -> Any:
        """Get hierarchical trace for a workflow."""
        result = data_service.get_workflow_trace(workflow_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Workflow trace not found")
        return result

    @router.get("/workflows/{workflow_id}/data-flow")
    def get_data_flow(workflow_id: str) -> Any:
        """Get data flow graph between stages."""
        return data_service.get_data_flow(workflow_id)

    @router.get("/stages/{stage_id}")
    def get_stage(stage_id: str) -> Any:
        """Get stage execution details."""
        result = data_service.get_stage(stage_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Stage not found")
        return result

    @router.get("/agents/{agent_id}")
    def get_agent(agent_id: str) -> Any:
        """Get agent execution details."""
        result = data_service.get_agent(agent_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return result

    @router.get("/llm-calls/{llm_call_id}")
    def get_llm_call(llm_call_id: str) -> Any:
        """Get LLM call details."""
        result = data_service.get_llm_call(llm_call_id)
        if result is None:
            raise HTTPException(status_code=404, detail="LLM call not found")
        return result

    @router.get("/tool-calls/{tool_call_id}")
    def get_tool_call(tool_call_id: str) -> Any:
        """Get tool call details."""
        result = data_service.get_tool_call(tool_call_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Tool call not found")
        return result

    return router
