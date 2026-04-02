"""Core API routes — workflow execution and querying.

POST /api/runs              — start a workflow
GET  /api/workflows         — list executions
GET  /api/workflows/{id}    — get full execution hierarchy
POST /api/runs/{id}/cancel  — cancel a running workflow (TODO)
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from temper_ai.api.data_service import get_workflow_execution, list_workflow_executions
from temper_ai.api.websocket import ws_manager
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.loader import GraphLoader
from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared infrastructure (initialized once)
_config_store = ConfigStore()
_graph_loader = GraphLoader(_config_store)
_tool_executor = ToolExecutor()
# Register all built-in tools so agents can reference them by name
_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})
_memory_service = MemoryService(InMemoryStore())

# Track running workflows for cancellation
_running: dict[str, threading.Event] = {}

# LLM providers — populated by server.py at startup
_llm_providers: dict[str, Any] = {}


def set_llm_providers(providers: dict[str, Any]):
    """Called by server.py to inject LLM provider instances."""
    global _llm_providers
    _llm_providers = providers


def set_memory_service(service: MemoryService):
    """Called by server.py to inject a configured memory service."""
    global _memory_service
    _memory_service = service


# --- Request/Response models ---

class RunRequest(BaseModel):
    """Request to start a workflow execution."""

    workflow: str  # Workflow config name (loaded from config store)
    inputs: dict = {}
    workspace_path: str | None = None


class RunResponse(BaseModel):
    """Response from starting a workflow execution."""

    execution_id: str
    status: str


# --- Routes ---

@router.post("/api/runs", response_model=RunResponse)
def start_run(body: RunRequest):
    """Start a workflow execution in a background thread.

    Returns immediately with the execution_id. Use WebSocket or
    GET /api/workflows/{id} to track progress.
    """
    execution_id = str(uuid.uuid4())

    # Validate workflow exists before starting
    try:
        nodes, config = _graph_loader.load_workflow(body.workflow)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build execution context
    from temper_ai.api.websocket import ws_manager

    # Create per-run policy engine from workflow safety config (if any)
    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        try:
            policy_engine = PolicyEngine.from_config(config.safety)
            logger.info("Safety policies loaded: %d", len(policy_engine.policies))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid safety config: {exc}") from exc

    # Create per-run tool executor with safety policies
    run_tool_executor = ToolExecutor(
        workspace_root=body.workspace_path,
        policy_engine=policy_engine,
    )
    # Register built-in tools
    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    # Register MCP tools (lazy — connects on first call)
    try:
        from temper_ai.tools.mcp_client import mcp_manager
        from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents

        # Scan agent configs used in this workflow to find MCP tool references
        agent_configs = []
        for node in nodes:
            if hasattr(node, "agent_config"):
                agent_configs.append(node.agent_config)

        mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
        if mcp_tools:
            run_tool_executor.register_tools(mcp_tools)
    except Exception:
        pass  # MCP is optional

    recorder = EventRecorder(execution_id, notifier=ws_manager)
    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_memory_service,
        llm_providers=_llm_providers,
        workspace_path=body.workspace_path,
    )

    # Start execution in background thread
    cancel_event = threading.Event()
    _running[execution_id] = cancel_event

    thread = threading.Thread(
        target=_run_workflow,
        args=(nodes, body.inputs, context, config.name, execution_id),
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=execution_id, status="running")


@router.get("/api/workflows")
def list_workflows(limit: int = 20, offset: int = 0, status: str | None = None):
    """List workflow executions with summary data."""
    return list_workflow_executions(limit=limit, offset=offset, status=status)


@router.get("/api/workflows/{execution_id}")
def get_workflow(execution_id: str):
    """Get full workflow execution hierarchy."""
    result = get_workflow_execution(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return result


@router.post("/api/runs/{execution_id}/cancel")
def cancel_run(execution_id: str):
    """Cancel a running workflow execution.

    If the execution is actively running in this server, sets the cancel event.
    If it's an orphaned run (stale from a server restart), marks it as cancelled
    directly in the event store.
    """
    cancel_event = _running.get(execution_id)
    if cancel_event is not None:
        cancel_event.set()
        return {"status": "cancelling", "execution_id": execution_id}

    # Not in _running — could be an orphaned stale run. Check if it exists in DB.
    result = get_workflow_execution(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")

    if result.get("status") != "running":
        return {"status": result.get("status"), "execution_id": execution_id}

    # Orphaned running workflow — update the workflow.started event status directly
    # so the list query picks up the new status.
    from temper_ai.observability.recorder import get_events, update_event
    start_events = get_events(event_type="workflow.started", execution_id=execution_id, limit=1)
    if start_events:
        update_event(start_events[0]["id"], status="cancelled", data={"cancelled_reason": "Stale run cancelled by user"})
        logger.info("Marked stale execution %s as cancelled", execution_id)
    return {"status": "cancelled", "execution_id": execution_id}


@router.get("/api/runtime-config")
def get_runtime_config():
    """Runtime config for the frontend (auth tokens, feature flags, etc.)."""
    return {"dashboard_token": None}


@router.websocket("/ws/{execution_id}")
async def websocket_endpoint(websocket: WebSocket, execution_id: str):
    """WebSocket endpoint for real-time execution updates."""
    await ws_manager.connect(websocket, execution_id)


# --- Background execution ---

def _run_workflow(nodes, inputs, context, workflow_name, execution_id):
    """Run a workflow in a background thread."""
    try:
        logger.info("Starting workflow '%s' (execution: %s)", workflow_name, execution_id)
        result = execute_graph(
            nodes, inputs, context,
            graph_name=workflow_name,
            is_workflow=True,
        )
        logger.info(
            "Workflow '%s' completed: status=%s, cost=$%.4f, tokens=%d",
            workflow_name, result.status, result.cost_usd, result.total_tokens,
        )
    except Exception as exc:
        logger.error("Workflow '%s' failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _running.pop(execution_id, None)
        ws_manager.cleanup(execution_id)
        # Clean up per-run tool executor thread pool
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)


    # _EventBroadcastRecorder replaced by shared EventRecorder
    # from temper_ai.observability.event_recorder
