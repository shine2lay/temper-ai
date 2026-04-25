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

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from temper_ai.api.app_state import AppState
from temper_ai.api.data_service import get_workflow_execution, list_workflow_executions
from temper_ai.api.websocket import ws_manager
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.runner._helpers import (
    McpPreconnectError,
    bind_delegate_tool,
    build_dispatch_limits,
    preconnect_mcp_servers,
)
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.executor import execute_graph
from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared state — initialized by server.py lifespan, accessed by all routes.
# This replaces the old module-level singletons and global statements.
_app_state: AppState | None = None


def init_app_state(state: AppState) -> None:
    """Called by server.py lifespan to inject shared state."""
    global _app_state
    _app_state = state


def _state() -> AppState:
    """Get the shared app state. Raises if server hasn't started."""
    if _app_state is None:
        raise RuntimeError("App state not initialized — server lifespan hasn't run yet")
    return _app_state


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
    """Start a workflow execution.

    Two modes, picked by $TEMPER_EXECUTION_MODE:
      inprocess (default) — run in a server-process thread (legacy behavior)
      subprocess          — spawn a `temper run-workflow` subprocess

    Subprocess mode is opt-in until phase 6 flips the default. In both
    modes, the response shape is identical: returns execution_id + status,
    and the caller polls GET /api/workflows/{id} or watches the WebSocket.
    """
    execution_id = str(uuid.uuid4())

    # Validate workflow exists before starting. Pass inputs so any
    # `type: template` nodes can be expanded at load time. Both modes
    # share this validation so a bad workflow name fails fast as 400.
    try:
        nodes, config = _state().graph_loader.load_workflow(
            body.workflow, inputs=body.inputs
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Mode dispatch — three modes:
    #   inprocess (default): server thread runs workflow (legacy)
    #   subprocess: server spawns a child process in its own container
    #   external: server inserts row + returns; an external watcher
    #             (temper watch-queue, in the worker container) picks it up
    #             and spawns the worker. Solves the toolchain problem —
    #             worker container has pytest/npm/docker-cli baked in.
    import os as _os
    mode = _os.environ.get("TEMPER_EXECUTION_MODE", "inprocess").lower()
    if mode == "subprocess":
        return _start_run_subprocess(execution_id, body, config)
    if mode == "external":
        return _start_run_external(execution_id, body, config)

    # Build execution context

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
        try:
            preconnect_mcp_servers(mcp_manager, mcp_tools)
        except McpPreconnectError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    recorder = EventRecorder(
        execution_id, notifier=_build_notifier(execution_id, config.name),
    )
    # Start execution in background thread
    cancel_event = threading.Event()
    _state().running[execution_id] = cancel_event

    checkpoint_svc = CheckpointService(execution_id)

    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_state().memory_service,
        llm_providers=_state().llm_providers,
        workspace_path=body.workspace_path,
        cancel_event=cancel_event,
        checkpoint_service=checkpoint_svc,
        gate_registry=_state().gates,
        graph_loader=_state().graph_loader,
        dispatch_limits=build_dispatch_limits(config),
    )

    # Bind execution context to Delegate tool so it can create sub-agents
    bind_delegate_tool(run_tool_executor, context)

    thread = threading.Thread(
        target=_run_workflow,
        args=(nodes, body.inputs, context, config.name, execution_id, config.outputs),
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=execution_id, status="running")


def _start_run_external(
    execution_id: str, body: RunRequest, config,
) -> RunResponse:
    """Insert WorkflowRun row + return; external watcher will spawn the worker.

    The server doesn't track the worker process at all in this mode — the
    watcher (running in the temper-worker container) owns spawn/poll/kill.
    The server's only job is to durably record what was requested.

    Same WorkflowRun row contract as subprocess mode; the watcher reads
    workflow_name + workspace_path + inputs and runs `temper run-workflow`.
    """
    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id,
            workflow_name=config.name,
            workspace_path=body.workspace_path or "",
            inputs=body.inputs or {},
            status="queued",
        ))

    return RunResponse(execution_id=execution_id, status="queued")


def _start_run_subprocess(
    execution_id: str, body: RunRequest, config,
) -> RunResponse:
    """Spawn a worker subprocess instead of running in this server process.

    Insert the WorkflowRun row first (worker reads it at startup), then
    ask the spawner to launch. If the spawn fails, mark the row failed
    and surface 503 — the caller can retry.

    Cancellation, monitoring, and terminal-state writes are owned by the
    reaper + worker respectively; this function returns as soon as the
    process is launched.
    """
    from datetime import UTC, datetime

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun
    from temper_ai.spawner import SpawnerError, get_spawner

    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id,
            workflow_name=config.name,
            workspace_path=body.workspace_path or "",
            inputs=body.inputs or {},
            status="queued",
        ))

    spawner = get_spawner()
    try:
        handle = spawner.spawn(execution_id)
    except SpawnerError as exc:
        # Mark failed so the dashboard reflects reality. Don't keep the
        # queued row around — caller knows it didn't start.
        with get_session() as session:
            from sqlmodel import select
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
            ).first()
            if row is not None:
                row.status = "failed"
                row.completed_at = datetime.now(UTC)
                row.error = {"message": str(exc), "kind": "spawn"}
                session.add(row)
        raise HTTPException(status_code=503, detail=f"Spawner failed: {exc}") from exc

    # Stamp the handle so the reaper can poll/kill it.
    with get_session() as session:
        from sqlmodel import select
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is not None:
            row.spawner_kind = handle.kind.value
            row.spawner_handle = handle.handle
            row.spawner_metadata = handle.metadata
            session.add(row)

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

    Three paths in priority order:
      1. In-process run: cancel_event in this server's `running` dict → set it
      2. Subprocess run: WorkflowRun row exists → set cancel_requested=true so
         the reaper sends SIGTERM (worker writes the cancelled milestone)
      3. Stale run: only an event row exists → mark the workflow.started
         event cancelled (legacy fallback for crashed in-process runs)
    """
    cancel_event = _state().running.get(execution_id)
    if cancel_event is not None:
        cancel_event.set()
        return {"status": "cancelling", "execution_id": execution_id}

    # Subprocess run? WorkflowRun row is the source of truth for spawner-managed runs.
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is not None and row.status in ("queued", "running"):
            row.cancel_requested = True
            session.add(row)
            return {"status": "cancelling", "execution_id": execution_id}

    # Not in running dict — could be an orphaned stale run. Check if it exists in DB.
    result = get_workflow_execution(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")

    if result.get("status") != "running":
        return {"status": result.get("status"), "execution_id": execution_id}

    # Orphaned running workflow — update the workflow.started event status directly
    # so the list query picks up the new status.
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import get_events, update_event
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
        nodes, config = _state().graph_loader.load_workflow(workflow_name)
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

    workspace = body.workspace_path or (result.get("input_data") or {}).get("workspace_path")

    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=workspace, policy_engine=policy_engine)
    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    recorder = EventRecorder(
        execution_id, notifier=_build_notifier(execution_id, config.name),
    )
    cancel_event = threading.Event()
    _state().running[execution_id] = cancel_event

    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_state().memory_service,
        llm_providers=_state().llm_providers,
        workspace_path=workspace,
        cancel_event=cancel_event,
        checkpoint_service=checkpoint_svc,
        gate_registry=_state().gates,
        graph_loader=_state().graph_loader,
        dispatch_limits=build_dispatch_limits(config),
    )

    bind_delegate_tool(run_tool_executor, context)

    # Reconstruct original inputs from the first run
    original_inputs = result.get("input_data") or {}

    # Replay any dispatch_applied checkpoints — materialize dispatched nodes
    # into the loaded workflow and rebuild DispatchRunState so caps still
    # enforce correctly against the pre-crash history.
    replayed_dispatches = _apply_dispatch_history_on_resume(
        checkpoint_svc=checkpoint_svc,
        graph_loader=_state().graph_loader,
        nodes=nodes,
        context=context,
    )

    # Build resume metadata so the new workflow.started event carries a
    # link back to the prior attempt + the list of names whose outputs
    # came from checkpoint. This lets the view distinguish "fresh start"
    # from "resume" without inferring from event count.
    prev_workflow_event = _find_latest_workflow_event(execution_id)
    resume_metadata = {
        "resume_of": prev_workflow_event["id"] if prev_workflow_event else None,
        "restored_node_names": sorted(restored_outputs.keys()),
        "replayed_dispatches": replayed_dispatches or [],
    }

    thread = threading.Thread(
        target=_run_workflow_with_checkpoints,
        args=(nodes, original_inputs, context, config.name, execution_id, restored_outputs),
        kwargs={"resume_metadata": resume_metadata},
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
        nodes, config = _state().graph_loader.load_workflow(body.workflow)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Forking execution '%s' at sequence %d → new execution '%s' with %d nodes restored",
        body.source_execution_id, body.sequence, new_execution_id, len(restored_outputs),
    )


    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=body.workspace_path, policy_engine=policy_engine)
    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    recorder = EventRecorder(
        new_execution_id, notifier=_build_notifier(new_execution_id, config.name),
    )
    cancel_event = threading.Event()
    _state().running[new_execution_id] = cancel_event

    context = ExecutionContext(
        run_id=new_execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=_state().memory_service,
        llm_providers=_state().llm_providers,
        workspace_path=body.workspace_path,
        cancel_event=cancel_event,
        checkpoint_service=fork_svc,
        gate_registry=_state().gates,
        graph_loader=_state().graph_loader,
        dispatch_limits=build_dispatch_limits(config),
    )

    bind_delegate_tool(run_tool_executor, context)

    # Record fork metadata so the data service can link back to the source.
    # Determine top-level node names that were restored.
    from temper_ai.stage.stage_node import StageNode as _StageNode
    restored_keys = set(restored_outputs.keys())
    restored_top_level: set[str] = set()
    for node in nodes:
        if node.name in restored_keys:
            restored_top_level.add(node.name)
        if isinstance(node, _StageNode) and node.child_nodes:
            if any(cn.name in restored_keys for cn in node.child_nodes):
                restored_top_level.add(node.name)

    # Store fork metadata as an event so the data service can link to the source.
    import uuid as _uuid

    from temper_ai.observability.models import Event as _Event
    from temper_ai.observability.recorder import _db_write_with_retry
    fork_event = _Event(
        id=str(_uuid.uuid4()),
        type="fork.metadata",
        execution_id=new_execution_id,
        status="completed",
        data={
            "source_execution_id": body.source_execution_id,
            "fork_sequence": body.sequence,
            "restored_node_names": sorted(restored_top_level),
        },
    )
    _db_write_with_retry(lambda s: s.add(fork_event))

    inputs = body.inputs or {}
    thread = threading.Thread(
        target=_run_workflow_with_checkpoints,
        args=(nodes, inputs, context, config.name, new_execution_id, restored_outputs),
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=new_execution_id, status="running")


@router.post("/api/runs/{execution_id}/approve/{node_name}")
def approve_gate(execution_id: str, node_name: str):
    """Approve a gate node, allowing the workflow to continue.

    The gate node must be in a 'waiting' state. Once approved, the
    executor thread unblocks and the node executes.
    """
    gate_key = f"{execution_id}:{node_name}"
    gate_event = _state().gates.get(gate_key)
    if gate_event is None:
        raise HTTPException(
            status_code=404,
            detail=f"No gate waiting for node '{node_name}' in execution '{execution_id}'",
        )
    gate_event.set()
    return {"status": "approved", "execution_id": execution_id, "node_name": node_name}


@router.get("/api/runs/{execution_id}/gates")
def list_gates(execution_id: str):
    """List all gates currently waiting for approval in an execution."""
    prefix = f"{execution_id}:"
    waiting = [
        {"node_name": key.split(":", 1)[1], "status": "waiting"}
        for key in _state().gates
        if key.startswith(prefix) and not _state().gates[key].is_set()
    ]
    return {"execution_id": execution_id, "gates": waiting}


@router.get("/api/runs/{execution_id}/checkpoints")
def get_checkpoints(execution_id: str):
    """Get checkpoint history for an execution."""
    svc = CheckpointService(execution_id)
    history = svc.get_history()
    return {"execution_id": execution_id, "checkpoints": history, "total": len(history)}


def _build_notifier(execution_id: str, workflow_name: str):
    """Compose the notifier sinks for an in-process workflow run.

    Two sinks: ws_manager (live WebSocket broadcast) + JsonlNotifier
    (per-run forensic log). Subprocess workers build their own composite
    in cmd_run_workflow — we don't share construction because the subprocess
    side adds Redis chunks that the in-process side doesn't need.
    """
    from temper_ai.observability.composite_notifier import CompositeNotifier
    from temper_ai.observability.jsonl_logger import JsonlNotifier
    return CompositeNotifier(
        ws_manager,
        JsonlNotifier(
            execution_id, workflow_name,
            metadata={"spawned_via": "in-process route handler"},
        ),
    )


def _find_latest_workflow_event(execution_id: str) -> dict | None:
    """Return the most recent `workflow.started` event for the given run, or
    None if none exists. Used during resume to stamp the new workflow event
    with `data.resume_of` pointing back to the prior attempt.
    """
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import get_events
    candidates = get_events(
        execution_id=execution_id,
        event_type=EventType.WORKFLOW_STARTED,
        limit=100,
    )
    if not candidates:
        return None
    # Latest by timestamp wins.
    return max(candidates, key=lambda e: e.get("timestamp") or "")


def _apply_dispatch_history_on_resume(
    checkpoint_svc, graph_loader, nodes, context,
) -> list[str]:
    """Rebuild the DAG + DispatchRunState from saved dispatch_applied events.

    Called before executor restart during resume. For each persisted dispatch:
      - materialize every added node via GraphLoader._resolve_node and insert
        it into `nodes` so the executor sees it alongside the original YAML
      - re-populate DispatchRunState (depths, parents, fingerprints,
        dispatched_count) so post-resume dispatches still respect caps

    op=remove targets are already handled by reconstruct() which marks them
    SKIPPED in the restored node_outputs.

    Returns: list of dispatcher names whose state was replayed (for resume
    metadata stamping on the new workflow.started event).
    """
    from temper_ai.stage.dispatch_limits import DispatchRunState
    from temper_ai.stage.models import NodeConfig

    history = checkpoint_svc.reconstruct_dispatch_history()
    if not history:
        return []

    # Seed the state if the context doesn't have one yet — on resume, no
    # dispatch has fired in this executor process, so state starts empty.
    if context.dispatch_state is None:
        context.dispatch_state = DispatchRunState()
    state = context.dispatch_state

    existing_names = {n.name for n in nodes}
    replayed_dispatchers: list[str] = []
    for event in history:
        dispatcher_name = event["dispatcher_name"]
        # Record dispatcher's own fingerprint + depth so cycle/depth walks
        # work on post-resume dispatches.
        state.fingerprints.setdefault(
            dispatcher_name,
            event["dispatcher_fingerprint"],
        )
        dispatcher_depth = event["dispatcher_depth"]

        for node_dict in event["added_nodes"]:
            name = node_dict.get("name")
            if not isinstance(name, str):
                logger.warning(
                    "dispatch_applied entry for '%s' has a node without a "
                    "name — skipping restore of that node", dispatcher_name,
                )
                continue
            if name in existing_names:
                # Name already in DAG (shouldn't happen, but be defensive)
                continue
            try:
                nc = NodeConfig.from_dict(node_dict)
                built = graph_loader._resolve_node(nc)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Resume: failed to re-materialize dispatched node '%s' "
                    "(from dispatcher '%s'): %s",
                    name, dispatcher_name, exc,
                )
                continue
            nodes.append(built)
            existing_names.add(name)
            # Rebuild state so future dispatches from this node see correct depth etc.
            new_depth = dispatcher_depth + 1
            state.depths[name] = new_depth
            state.parents[name] = dispatcher_name
            # Compute the restored child's fingerprint identically to how
            # the original run did — see _enforce_caps_and_build.
            from temper_ai.stage.dispatch_limits import fingerprint_node
            agent_ref = node_dict.get("agent") or name
            state.fingerprints[name] = fingerprint_node(
                agent_ref, node_dict.get("input_map") or {},
            )
        state.dispatched_count += event["dispatched_count_delta"]
        if dispatcher_name not in replayed_dispatchers:
            replayed_dispatchers.append(dispatcher_name)

    logger.info(
        "Resume: replayed %d dispatch_applied event(s); DAG now has %d nodes, "
        "dispatched_count=%d",
        len(history), len(nodes), state.dispatched_count,
    )
    return replayed_dispatchers


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

def _run_workflow(nodes, inputs, context, workflow_name, execution_id, workflow_outputs=None):
    """Run a workflow in a background thread."""
    try:
        logger.info("Starting workflow '%s' (execution: %s)", workflow_name, execution_id)
        result = execute_graph(
            nodes, inputs, context,
            graph_name=workflow_name,
            is_workflow=True,
            workflow_outputs=workflow_outputs,
        )
        logger.info(
            "Workflow '%s' completed: status=%s, cost=$%.4f, tokens=%d",
            workflow_name, result.status, result.cost_usd, result.total_tokens,
        )
    except Exception as exc:
        logger.error("Workflow '%s' failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _state().running.pop(execution_id, None)
        ws_manager.cleanup(execution_id)
        # Clean up per-run tool executor thread pool
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)


def _run_workflow_with_checkpoints(
    nodes, inputs, context, workflow_name, execution_id, restored_outputs,
    *, resume_metadata: dict | None = None,
):
    """Run a workflow with pre-populated node_outputs from checkpoints.

    `resume_metadata`, when provided, flows through to the WORKFLOW_STARTED
    event so the view can identify the new attempt as a resume of a prior
    workflow event (instead of inferring from event count).
    """
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
            resume_metadata=resume_metadata,
        )
        logger.info(
            "Workflow '%s' resumed and completed: status=%s, cost=$%.4f, tokens=%d",
            workflow_name, result.status, result.cost_usd, result.total_tokens,
        )
    except Exception as exc:
        logger.error("Workflow '%s' resume failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _state().running.pop(execution_id, None)
        ws_manager.cleanup(execution_id)
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)
