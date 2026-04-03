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
from temper_ai.checkpoint.service import CheckpointService
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

    # Register MCP tools and pre-connect needed servers
    from temper_ai.tools.mcp_client import mcp_manager
    from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents

    agent_configs = [
        node.agent_config for node in nodes if hasattr(node, "agent_config")
    ]
    mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
    if mcp_tools:
        run_tool_executor.register_tools(dict(mcp_tools))
        _preconnect_mcp_servers(mcp_manager, mcp_tools)  # raises on failure

    recorder = EventRecorder(execution_id, notifier=ws_manager)
    # Start execution in background thread
    cancel_event = threading.Event()
    _running[execution_id] = cancel_event

    checkpoint_svc = CheckpointService(execution_id)

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
        cancel_event=cancel_event,
        checkpoint_service=checkpoint_svc,
    )

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
    from temper_ai.observability.event_types import EventType
    start_events = get_events(event_type=EventType("workflow.started"), execution_id=execution_id, limit=1)
    if start_events:
        update_event(start_events[0]["id"], status="cancelled", data={"cancelled_reason": "Stale run cancelled by user"})
        logger.info("Marked stale execution %s as cancelled", execution_id)
    return {"status": "cancelled", "execution_id": execution_id}


class ResumeRequest(BaseModel):
    """Request to resume a workflow from checkpoints."""

    workflow: str | None = None  # Override workflow config (default: use original)
    workspace_path: str | None = None


class ForkRequest(BaseModel):
    """Request to fork a workflow from a specific checkpoint."""

    workflow: str  # Workflow config to use for the fork
    source_execution_id: str
    sequence: int  # Checkpoint sequence to fork from
    inputs: dict = {}
    workspace_path: str | None = None


@router.post("/api/runs/{execution_id}/resume", response_model=RunResponse)
def resume_run(execution_id: str, body: ResumeRequest | None = None):
    """Resume a workflow from its last checkpoint.

    Loads all checkpoints for the execution, reconstructs node_outputs,
    and continues from where it left off. Uses current agent/workflow
    configs (not the configs at crash time).
    """
    body = body or ResumeRequest()

    # Find the original workflow name from events
    result = get_workflow_execution(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")

    workflow_name = body.workflow or result.get("workflow_name")
    if not workflow_name:
        raise HTTPException(status_code=400, detail="Cannot determine workflow name. Provide 'workflow' in request body.")

    # Load current workflow config
    try:
        nodes, config = _graph_loader.load_workflow(workflow_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Reconstruct state from checkpoints
    checkpoint_svc = CheckpointService(execution_id)
    restored_outputs = checkpoint_svc.reconstruct()

    if not restored_outputs:
        raise HTTPException(status_code=400, detail="No checkpoints found — nothing to resume from")

    logger.info(
        "Resuming execution '%s' with %d checkpointed nodes: %s",
        execution_id, len(restored_outputs), list(restored_outputs.keys()),
    )

    # Rebuild context
    from temper_ai.api.websocket import ws_manager

    workspace = body.workspace_path or result.get("input_data", {}).get("workspace_path")

    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=workspace, policy_engine=policy_engine)
    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    recorder = EventRecorder(execution_id, notifier=ws_manager)
    cancel_event = threading.Event()
    _running[execution_id] = cancel_event

    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_memory_service,
        llm_providers=_llm_providers,
        workspace_path=workspace,
        cancel_event=cancel_event,
        checkpoint_service=checkpoint_svc,
    )

    # Reconstruct original inputs from the first run
    original_inputs = result.get("input_data", {})

    thread = threading.Thread(
        target=_run_workflow_with_checkpoints,
        args=(nodes, original_inputs, context, config.name, execution_id, restored_outputs),
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=execution_id, status="resuming")


@router.post("/api/runs/fork", response_model=RunResponse)
def fork_run(body: ForkRequest):
    """Fork a new execution from a specific checkpoint in another execution.

    Creates a new execution_id that shares history with the source up to
    the fork point, then continues independently.
    """
    new_execution_id = str(uuid.uuid4())

    try:
        fork_svc = CheckpointService.fork(
            source_execution_id=body.source_execution_id,
            sequence=body.sequence,
            new_execution_id=new_execution_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Reconstruct state at the fork point
    restored_outputs = fork_svc.reconstruct()

    # Load workflow
    try:
        nodes, config = _graph_loader.load_workflow(body.workflow)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Forking execution '%s' at sequence %d → new execution '%s' with %d nodes restored",
        body.source_execution_id, body.sequence, new_execution_id, len(restored_outputs),
    )

    from temper_ai.api.websocket import ws_manager

    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=body.workspace_path, policy_engine=policy_engine)
    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    recorder = EventRecorder(new_execution_id, notifier=ws_manager)
    cancel_event = threading.Event()
    _running[new_execution_id] = cancel_event

    context = ExecutionContext(
        run_id=new_execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_memory_service,
        llm_providers=_llm_providers,
        workspace_path=body.workspace_path,
        cancel_event=cancel_event,
        checkpoint_service=fork_svc,
    )

    inputs = body.inputs or {}
    thread = threading.Thread(
        target=_run_workflow_with_checkpoints,
        args=(nodes, inputs, context, config.name, new_execution_id, restored_outputs),
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=new_execution_id, status="running")


@router.get("/api/runs/{execution_id}/checkpoints")
def get_checkpoints(execution_id: str):
    """Get checkpoint history for an execution."""
    svc = CheckpointService(execution_id)
    history = svc.get_history()
    return {"execution_id": execution_id, "checkpoints": history, "total": len(history)}


def _preconnect_mcp_servers(mcp_manager, mcp_tools: dict) -> None:
    """Pre-connect MCP servers needed by this workflow.

    Runs async connections from the sync route context via run_coroutine_threadsafe.
    Logs warnings but never blocks the workflow from starting.
    """
    import asyncio

    server_names = {tool._server_name for tool in mcp_tools.values()}
    if not server_names:
        return

    errors = []

    async def connect_all():
        for name in server_names:
            try:
                await mcp_manager.ensure_connected(name)
            except Exception as e:
                errors.append(f"MCP server '{name}': {e}")

    future = asyncio.run_coroutine_threadsafe(connect_all(), mcp_manager.event_loop)
    future.result(timeout=30)

    if errors:
        raise HTTPException(
            status_code=503,
            detail=f"Required MCP servers failed to connect: {'; '.join(errors)}",
        )


@router.get("/api/mcp-servers")
def list_mcp_servers():
    """List configured MCP server names from config files."""
    import pathlib
    servers = []
    for candidate in [
        pathlib.Path("/app/configs/mcp_servers"),
        pathlib.Path(__file__).resolve().parents[2] / "configs" / "mcp_servers",
        pathlib.Path("configs/mcp_servers"),
    ]:
        if candidate.is_dir():
            servers = sorted(f.stem for f in candidate.glob("*.yaml"))
            break
    return {"mcp_servers": servers}


@router.get("/api/runtime-config")
def get_runtime_config():
    """Runtime config for the frontend (auth tokens, feature flags, etc.)."""
    return {"dashboard_token": None}  # noqa: B105


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


def _run_workflow_with_checkpoints(nodes, inputs, context, workflow_name, execution_id, restored_outputs):
    """Run a workflow with pre-populated node_outputs from checkpoints."""
    try:
        logger.info(
            "Resuming workflow '%s' (execution: %s) — %d nodes pre-loaded",
            workflow_name, execution_id, len(restored_outputs),
        )
        # The executor's _run_batches will skip nodes already in node_outputs
        # We inject restored_outputs by pre-populating them in the execute_graph call
        from temper_ai.stage.executor import execute_graph_with_state
        result = execute_graph_with_state(
            nodes, inputs, context,
            graph_name=workflow_name,
            is_workflow=True,
            initial_outputs=restored_outputs,
        )
        logger.info(
            "Workflow '%s' resumed and completed: status=%s, cost=$%.4f, tokens=%d",
            workflow_name, result.status, result.cost_usd, result.total_tokens,
        )
    except Exception as exc:
        logger.error("Workflow '%s' resume failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _running.pop(execution_id, None)
        ws_manager.cleanup(execution_id)
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)
