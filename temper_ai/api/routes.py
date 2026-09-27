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
from pydantic import AliasChoices, BaseModel, Field

from temper_ai.api.app_state import AppState
from temper_ai.api.data_service import get_workflow_execution, list_workflow_executions
from temper_ai.api.websocket import ws_manager
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_events, update_event
from temper_ai.runner._helpers import (
    McpPreconnectError,
    bind_delegate_tool,
    build_dispatch_limits,
    preconnect_mcp_servers,
)
from temper_ai.runner.resume import (
    apply_dispatch_history_on_resume as _apply_dispatch_history_on_resume,
)
from temper_ai.runner.resume import (
    find_latest_workflow_event as _find_latest_workflow_event,
)
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.gate import normalise_response
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
    """Request to start a workflow execution.

    Accepts ``workflow_name`` as well as ``workflow``: every run the API
    *returns* names the field ``workflow_name``, so posting it back is the
    obvious thing to try and it used to fail with a bare 422.
    """

    workflow: str = Field(  # Workflow config name (loaded from config store)
        validation_alias=AliasChoices("workflow", "workflow_name"),
        serialization_alias="workflow",
    )
    inputs: dict = {}
    workspace_path: str | None = None
    # Where this run's questions and notices go, over its workflow's
    # `notify:` (docs/notify.md), e.g. {"question": "telegram", "finished": "off"}.
    notify: dict | str | None = None

    model_config = {"populate_by_name": True}


class RunResponse(BaseModel):
    """Response from starting a workflow execution."""

    execution_id: str
    status: str


# --- Routes ---

def _register_run_tools(run_tool_executor: ToolExecutor, nodes) -> None:
    """Give a run its tools: the built-ins, then whatever MCP servers its agents declare.

    Every path that builds a ToolExecutor goes through here — start, resume and fork. Registering the
    built-ins alone is not a smaller capability, it is a silent one: an agent that declared
    ``playwright.browser_navigate`` still starts, the name simply resolves to nothing, and an LLM with no
    browser does not stop. It writes a plausible answer about what it could not do. A resumed QA step
    reported ``verdict: fail`` that way, having never opened a page.
    """
    from temper_ai.tools.mcp_client import mcp_manager
    from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents

    run_tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    agent_configs = [cfg for node in nodes for cfg in node.agent_configs()]
    mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
    if mcp_tools:
        run_tool_executor.register_tools(dict(mcp_tools))
        try:
            preconnect_mcp_servers(mcp_manager, mcp_tools)
        except McpPreconnectError as exc:
            # 503 on start; on resume/fork the caller decides, since the run already exists.
            raise HTTPException(status_code=503, detail=str(exc)) from exc


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

    notify_block = None
    if body.notify is not None:
        from temper_ai.integrations.notify.config import NotifyConfigError, parse_block
        try:
            notify_block = parse_block(body.notify, "notify")
        except NotifyConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Validate workflow exists before starting. Pass inputs so any
    # `type: template` nodes can be expanded at load time. Both modes
    # share this validation so a bad workflow name fails fast as 400.
    try:
        nodes, config = _state().graph_loader.load_workflow(
            body.workflow, inputs=body.inputs
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if notify_block is not None:
        # Saved before the run starts, so its first question already follows it.
        from temper_ai.integrations.notify import store as notify_store
        from temper_ai.integrations.notify.config import KINDS
        # parse_block only accepts a mapping or off, so a plain value is off.
        notify_store.save_run_settings(execution_id, body.notify if isinstance(body.notify, dict)
                                       else {kind: "off" for kind in KINDS})

    # Mode dispatch — three modes:
    #   inprocess (default): server thread runs workflow (legacy)
    #   subprocess: server spawns a child process in its own container
    #   external: server inserts row + returns; an external watcher
    #             (temper watch-queue, in the worker container) picks it up
    #             and spawns the worker. Solves the toolchain problem —
    #             worker container has pytest/npm/docker-cli baked in.
    mode = _execution_mode()
    if mode == "subprocess":
        return _start_run_subprocess(execution_id, body, config)
    if mode == "external":
        return _start_run_external(execution_id, body, config)

    # Build execution context

    # Per-run policy engine: the platform baseline plus the workflow's safety
    # config (if any), see PolicyEngine.for_run.
    from temper_ai.safety import PolicyEngine
    try:
        policy_engine = PolicyEngine.for_run(config.safety)
        logger.info("Safety policies loaded: %d", len(policy_engine.policies))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid safety config: {exc}") from exc

    # Create per-run tool executor with safety policies
    run_tool_executor = ToolExecutor(
        workspace_root=body.workspace_path,
        policy_engine=policy_engine,
    )
    _register_run_tools(run_tool_executor, nodes)

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
    _queue_run(execution_id, config.name, body.workspace_path, body.inputs)
    return RunResponse(execution_id=execution_id, status="queued")


def _execution_mode() -> str:
    """inprocess (default), subprocess or external: where runs execute."""
    import os
    return os.environ.get("TEMPER_EXECUTION_MODE", "inprocess").lower()


def _queue_run(
    execution_id: str,
    workflow_name: str,
    workspace_path: str | None,
    inputs: dict | None,
    start: str | None = None,
) -> None:
    """Queue a run for the worker, which starts it in its own box.

    ``start`` is how the box begins: a fresh run (None), or ``resume`` /
    ``fork`` from the run's checkpoints (read by ``temper run-workflow``).
    A resumed run keeps its row: a finished one goes back to queued. One
    that is still queued or running is refused, so a run never has two
    boxes.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    metadata = {"start": start} if start else {}
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            session.add(WorkflowRun(
                execution_id=execution_id,
                workflow_name=workflow_name,
                workspace_path=workspace_path or "",
                inputs=inputs or {},
                status="queued",
                spawner_metadata=metadata,
            ))
            return
        if row.status in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Execution '{execution_id}' is already {row.status}",
            )
        row.workflow_name = workflow_name
        row.workspace_path = workspace_path or ""
        row.inputs = inputs or {}
        row.status = "queued"
        row.spawner_kind = None
        row.spawner_handle = None
        row.spawner_metadata = metadata
        row.cancel_requested = False
        row.started_at = None
        row.completed_at = None
        row.result = None
        row.error = None
        session.add(row)


def _run_row(execution_id: str) -> dict | None:
    """The run's WorkflowRun row as a plain dict, or None (runs in a box have one)."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            return None
        return {
            "workflow_name": row.workflow_name,
            "workspace_path": row.workspace_path or None,
            "inputs": row.inputs,
            "status": row.status,
            "error": row.error,
        }


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


# Registered before /api/workflows/{execution_id}, which would otherwise
# take "search" for an execution id.
@router.get("/api/workflows/search")
def search_workflow_configs(q: str = "", limit: int = 10):
    """Workflow configs matching the words of ``q``, best first.

    Matches each workflow's name, description, and input names and
    descriptions; a word in the name ranks highest. An empty ``q`` lists
    every workflow. ``undescribed`` names the workflows with no
    description, which only a search by name can find.
    """
    from temper_ai.config.search import search_workflows

    return search_workflows(q, limit=min(max(limit, 1), 500))


@router.get("/api/slack/status")
def slack_status():
    """Whether this server runs Slack, and how its socket and notices are doing."""
    from temper_ai.integrations.slack.service import status

    return status()


@router.get("/api/telegram/status")
def telegram_status():
    """Whether this server runs the Telegram bot, its polling, and the chats it knows."""
    from temper_ai.integrations.telegram.service import status

    return status()


@router.get("/api/notify/status")
def notify_status():
    """The notify loop: which places are on, what it sent and held, its config."""
    from temper_ai.integrations.notify.service import status

    return status()


@router.get("/api/workflows/{execution_id}")
def get_workflow(execution_id: str):
    """Get full workflow execution hierarchy."""
    result = get_workflow_execution(execution_id)
    if not result:
        # A run is registered before its first event is written, so for a
        # fraction of a second POST /api/runs handed back an id that this
        # endpoint answered 404 for. Anything that started a run and polled
        # immediately — an agent over MCP, a script — saw "not found" for a
        # run that was about to exist. A run queued for a box has no events
        # until the box starts it, a few seconds later; its row stands in.
        if execution_id in _state().running:
            return _run_placeholder(execution_id, "running")
        row = _run_row(execution_id)
        if row is not None:
            return _run_placeholder(execution_id, row["status"], row)
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    if _execution_mode() == "external" and result.get("status") not in _ACTIVE_STATUSES:
        # A resume waiting for its box still shows the attempt before it.
        row = _run_row(execution_id)
        if row is not None and row["status"] in ("queued", "running"):
            result["status"] = row["status"]
    return result


_ACTIVE_STATUSES = ("pending", "queued", "running", "waiting")


def _run_placeholder(execution_id: str, status: str, row: dict | None = None) -> dict:
    """What GET /api/workflows/{id} says about a run with no events yet."""
    row = row or {}
    return {
        "id": execution_id,
        "workflow_name": row.get("workflow_name"),
        "status": status,
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "nodes": [],
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "total_llm_calls": 0,
        "total_tool_calls": 0,
        "input_data": row.get("inputs"),
        "workspace_path": row.get("workspace_path"),
        "output_data": None,
        "workflow_output": None,
        "error_message": (row.get("error") or {}).get("message"),
        "fork_source": None,
    }


class CancelRequest(BaseModel):
    """Optional with a cancel: why. It matters most when the run is parked at
    a gate, where cancelling *is* the human's answer (a rejection), and a
    rejection without a reason is a decision nobody can learn from later."""

    reason: str = ""


@router.post("/api/runs/{execution_id}/cancel")
def cancel_run(execution_id: str, body: CancelRequest | None = None):
    """Cancel a running workflow execution.

    Three paths in priority order:
      1. In-process run: cancel_event in this server's `running` dict → set it
      2. Subprocess run: WorkflowRun row exists → set cancel_requested=true so
         the reaper sends SIGTERM (worker writes the cancelled milestone)
      3. Stale run: only an event row exists → mark the workflow.started
         event cancelled (legacy fallback for crashed in-process runs)

    Whichever path, a gate the run is waiting at is marked ``rejected`` first,
    with the reason as its response: the gate's own record then says how it
    was answered, the same way an approval does, and ``GET .../decisions``
    can list the two side by side.
    """
    reason = (body.reason if body else "").strip()
    rejected: dict[str, Any] = {"gate_status": "rejected", "gate_decided_at": _now_iso()}
    if reason:
        rejected["gate_response"] = {"response": reason, "answers": [], "text": reason}
    for ev in _waiting_gate_events(execution_id):
        update_event(ev["id"], status="rejected", data=rejected)
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

    # `workspace_path` is recorded alongside the inputs on workflow.started;
    # older runs kept it inside input_data, so accept both.
    workspace = (
        body.workspace_path
        or result.get("workspace_path")
        or (result.get("input_data") or {}).get("workspace_path")
    )

    if _execution_mode() == "external":
        # Its box restores the checkpoints and replays the dispatches
        # (temper run-workflow), the same steps as below.
        _queue_run(execution_id, config.name, workspace,
                   result.get("input_data") or {}, start="resume")
        return RunResponse(execution_id=execution_id, status="queued")

    from temper_ai.safety import PolicyEngine
    policy_engine = PolicyEngine.for_run(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=workspace, policy_engine=policy_engine)
    # The resumed nodes are the ones that had not finished, so they are exactly the ones that still need
    # their tools — including the MCP ones, which a resume used to drop.
    _register_run_tools(run_tool_executor, nodes)

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
        kwargs={"workflow_outputs": config.outputs, "resume_metadata": resume_metadata},
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

    if _execution_mode() == "external":
        # The checkpoints are already copied under the new id; its box
        # restores them (temper run-workflow).
        _record_fork_metadata(new_execution_id, body, restored_outputs, nodes)
        _queue_run(new_execution_id, config.name, body.workspace_path,
                   body.inputs or {}, start="fork")
        return RunResponse(execution_id=new_execution_id, status="queued")

    from temper_ai.safety import PolicyEngine
    policy_engine = PolicyEngine.for_run(config.safety)

    run_tool_executor = ToolExecutor(workspace_root=body.workspace_path, policy_engine=policy_engine)
    _register_run_tools(run_tool_executor, nodes)

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

    _record_fork_metadata(new_execution_id, body, restored_outputs, nodes)

    inputs = body.inputs or {}
    thread = threading.Thread(
        target=_run_workflow_with_checkpoints,
        args=(nodes, inputs, context, config.name, new_execution_id, restored_outputs),
        kwargs={"workflow_outputs": config.outputs},
        daemon=True,
    )
    thread.start()

    return RunResponse(execution_id=new_execution_id, status="running")


def _record_fork_metadata(new_execution_id: str, body: ForkRequest, restored_outputs: dict, nodes) -> None:
    """Store a fork.metadata event so the data service can link the fork to its source."""
    import uuid as _uuid

    from temper_ai.observability.models import Event as _Event
    from temper_ai.observability.recorder import _db_write_with_retry
    from temper_ai.stage.stage_node import StageNode as _StageNode

    # The top-level node names that were restored. Checkpoints are keyed by
    # node path: a stage's children as `stage.child`.
    restored_keys = set(restored_outputs.keys())
    restored_top_level: set[str] = set()
    for node in nodes:
        if node.name in restored_keys:
            restored_top_level.add(node.name)
        if isinstance(node, _StageNode) and node.child_nodes:
            if any(f"{node.name}.{cn.name}" in restored_keys for cn in node.child_nodes):
                restored_top_level.add(node.name)

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


class GateAnswer(BaseModel):
    """The human's answer to one question an upstream node asked."""

    id: str
    question: str = ""
    selected: list[str] = Field(default_factory=list)
    custom: str = ""


class GateApproval(BaseModel):
    """What the human sends with an approval. Every field is optional; an
    empty body is a plain approval, as before."""

    response: str = ""
    answers: list[GateAnswer] = Field(default_factory=list)


@router.post("/api/runs/{execution_id}/approve/{node_name}")
def approve_gate(execution_id: str, node_name: str, body: GateApproval | None = None):
    """Approve a gate node, allowing the workflow to continue.

    The gate node must be in a 'waiting' state. In-process runs are
    unblocked through the shared gate registry; runs executing in a worker
    process/container (subprocess or external mode) cannot see that
    registry, so the waiting event is also marked ``approved`` in the
    database, which the worker polls.

    The optional body carries the human's answers to the questions the
    previous node asked and/or a free-text response; the gated node
    receives it as its ``gate`` input (see :mod:`temper_ai.stage.gate`).
    """
    gate_key = f"{execution_id}:{node_name}"
    gate_event = _state().gates.get(gate_key)
    waiting_events = _waiting_gate_events(execution_id, node_name)
    if gate_event is None and not waiting_events:
        raise HTTPException(
            status_code=404,
            detail=f"No gate waiting for node '{node_name}' in execution '{execution_id}'",
        )
    response = normalise_response(body.model_dump() if body else None)
    approved = {"gate_status": "approved", "gate_decided_at": _now_iso(),
                **({"gate_response": response} if response else {})}
    for ev in waiting_events:
        update_event(ev["id"], status="approved", data=approved)
    if gate_event is not None:
        if response is not None:
            gate_event.response = response
        gate_event.set()
    return {
        "status": "approved",
        "execution_id": execution_id,
        "node_name": node_name,
        "response": response,
    }


@router.get("/api/runs/{execution_id}/gates")
def list_gates(execution_id: str):
    """List all gates currently waiting for approval in an execution.

    Each gate carries what the human should see: ``upstream`` (the outputs
    of the nodes the gated node depends on) and ``questions`` (the ones
    those outputs asked, in the ask_user_question shape), plus the
    ``event_id`` of the wait so a loop that gates the same node again is a
    new gate to the dashboard.
    """
    prefix = f"{execution_id}:"
    by_name: dict[str, dict] = {}
    for ev in _waiting_gate_events(execution_id):
        data = ev.get("data") or {}
        name = data.get("name", "")
        if not name:
            continue
        gate_context = data.get("gate_context") or {}
        by_name[name] = {
            "node_name": name,
            "status": "waiting",
            "event_id": ev.get("id"),
            "upstream": gate_context.get("upstream") or [],
            "questions": gate_context.get("questions") or [],
        }
    for key, signal in _state().gates.items():
        if key.startswith(prefix) and not signal.is_set():
            name = key.split(":", 1)[1]
            by_name.setdefault(
                name,
                {"node_name": name, "status": "waiting", "event_id": None, "upstream": [], "questions": []},
            )
    waiting = [by_name[n] for n in sorted(by_name)]
    return {"execution_id": execution_id, "gates": waiting}


def _waiting_gate_events(execution_id: str, node_name: str | None = None) -> list[dict]:
    """Persisted ``stage.started`` events still in ``waiting`` for gate nodes."""
    events = get_events(
        execution_id=execution_id,
        event_type=EventType("stage.started"),
        status="waiting",
        limit=100,
    )
    return [
        ev for ev in events
        if (ev.get("data") or {}).get("gate")
        and (node_name is None or (ev.get("data") or {}).get("name") == node_name)
    ]


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


@router.get("/api/runs/{execution_id}/decisions")
def list_decisions(execution_id: str):
    """Every gate this run has opened, and how each was answered.

    ``/gates`` is for the dashboard: what is waiting *now*, with the upstream
    output to read before deciding. This is the record afterwards: one entry
    per gate opened, in order, with ``status`` (``waiting`` / ``approved`` /
    ``rejected``), when it opened and when it was decided, the questions it
    asked and the ``response`` the human gave (answers and free text; a plain
    approval has none). A loop that gates the same node twice lists it twice.

    The upstream outputs are left out on purpose: they are large, and the
    point of this listing is the decisions, which a caller keeping a record
    of them over time wants to fetch for every run it has ever made.
    """
    events = get_events(execution_id=execution_id, event_type=EventType("stage.started"), limit=2000)
    decisions = []
    for ev in events:
        data = ev.get("data") or {}
        if not data.get("gate"):
            continue
        gate_context = data.get("gate_context") or {}
        decisions.append({
            "node_name": data.get("name", ""),
            "event_id": ev.get("id"),
            "status": data.get("gate_status") or ev.get("status") or "waiting",
            "opened_at": ev.get("timestamp"),
            "decided_at": data.get("gate_decided_at"),
            "questions": gate_context.get("questions") or [],
            "response": data.get("gate_response"),
        })
    return {"execution_id": execution_id, "decisions": decisions}


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
    from temper_ai.observability.webhook_notifier import WebhookNotifier

    webhook = WebhookNotifier()
    return CompositeNotifier(
        ws_manager,
        JsonlNotifier(
            execution_id, workflow_name,
            metadata={"spawned_via": "in-process route handler"},
        ),
        # None unless TEMPER_WEBHOOK_URL is set; CompositeNotifier drops it.
        webhook if webhook.enabled else None,
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
    """Runtime config for the frontend.

    Reports *whether* a token is required, never the token itself: an
    open endpoint that hands out the credential is theatre, not
    authentication.
    """
    from temper_ai.api.auth import auth_enabled

    return {"auth_required": auth_enabled()}


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
    *, workflow_outputs: dict[str, str] | None = None, resume_metadata: dict | None = None,
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
            # A resumed or forked run owes the workflow's declared outputs like any
            # other: without these, `workflow_output` on the finished run is empty
            # and whoever reads the run to learn what it did reads a blank.
            workflow_outputs=workflow_outputs,
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
