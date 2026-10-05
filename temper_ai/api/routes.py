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
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, WebSocket
from pydantic import AliasChoices, BaseModel, Field

from temper_ai.api.app_state import AppState
from temper_ai.api.data_service import (
    get_agent_index,
    get_tool_calls,
    get_workflow_execution,
    list_workflow_executions,
)
from temper_ai.api.websocket import ws_manager
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import (
    decide_event,
    gate_events,
    get_event,
    get_events,
    update_event,
)
from temper_ai.runner import holds
from temper_ai.runner import parked as pi_parked
from temper_ai.runner._helpers import (
    McpPreconnectError,
    bind_delegate_tool,
    build_dispatch_limits,
    preconnect_mcp_servers,
)
from temper_ai.runner.queue import AlreadyQueued, queue_run
from temper_ai.runner.resume import (
    apply_dispatch_history_on_resume as _apply_dispatch_history_on_resume,
)
from temper_ai.runner.resume import (
    find_latest_workflow_event as _find_latest_workflow_event,
)
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.exceptions import RunParked
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.failure import FailurePolicy
from temper_ai.stage.gate import (
    APPROVED,
    REJECTED,
    WAITING,
    describe_gate,
    gate_path,
    names_gate,
    normalise_response,
    refusal,
    several_waiting,
    signal_key,
)
from temper_ai.stage.input_defaults import fill_input_defaults
from temper_ai.stage.pi_workflows import is_pi_workflow
from temper_ai.stage.plan import build_restore, resume_plan
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
    response = _start_run(body)
    _note_event_run(body.workflow, response.execution_id)
    return response


def _note_event_run(workflow: str, execution_id: str) -> None:
    """If an event from outside (Linear, Notion, Slack, Telegram) is being
    handled on this thread and it started this run, write that on the event,
    so a retry of the event never starts the run twice."""
    try:
        from temper_ai.integrations.inbox import service as inbox

        inbox.note_run(workflow, execution_id)
    except Exception:  # noqa: BLE001 - the run started either way
        logger.exception("Could not note run %s on the event that started it", execution_id)


def _start_run(body: RunRequest) -> RunResponse:
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
    # share this validation so a bad workflow name fails fast as 400. It includes
    # the strategies' run-start checks (only the Pi team has one, with its switch
    # on), so a refused team never becomes a run.
    from temper_ai.stage.topology import run_start_options
    try:
        nodes, config = _state().graph_loader.load_workflow(
            body.workflow, inputs=body.inputs, **run_start_options(),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # What the run starts with: each declared default in place of an input left out, null or
    # empty (the loader read the same values). Every mode runs with these and records them, so the
    # run's saved inputs show what was used (stage/input_defaults.py).
    body = body.model_copy(
        update={"inputs": fill_input_defaults(getattr(config, "inputs", None), body.inputs)})

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
        # What a failure does in this workflow: hold its clean-ups (the default) or run them.
        failure_policy=FailurePolicy.parse(getattr(config, "on_failure", None)),
        # A Pi workflow's gates let the worker go while they wait (runner/parked.py).
        park_at_gates=is_pi_workflow(nodes),
    )

    # Bind execution context to Delegate tool so it can create sub-agents
    bind_delegate_tool(run_tool_executor, context)

    thread = threading.Thread(
        target=_run_workflow,
        args=(nodes, body.inputs, context, config.name, execution_id, config.outputs),
        daemon=True,
        name=f"temper-run-{execution_id}",
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
    extra: dict | None = None,
) -> None:
    """Queue a run for the worker, which starts it in its own box.

    ``start`` is how the box begins: a fresh run (None), or ``resume`` /
    ``fork`` from the run's checkpoints, or ``cleanup`` to run only the
    clean-ups a failed run was holding (read by ``temper run-workflow``).
    ``extra`` is anything else the box needs to know: the steps someone ticked
    to run again (``rerun``), or the only paths a pass may run (``only``).
    A resumed run keeps its row: a finished one goes back to queued. One
    that is still queued or running is refused, so a run never has two
    boxes. (runner/queue.py does it; this says a refusal as a 409.)
    """
    try:
        queue_run(execution_id, workflow_name, workspace_path, inputs, start=start, extra=extra)
    except AlreadyQueued as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    # The clean-ups this run is holding, if it stopped at a failure: the page shows what is
    # being kept for it and how long is left before it is let go.
    hold = holds.waiting(execution_id)
    if hold:
        result["hold"] = hold
    return result


@router.get("/api/workflows/{execution_id}/agents")
def get_workflow_agents(execution_id: str):
    """Every agent the run started, by id: name, node, status, times, cost.

    Light and quick, unlike the full record: the run page asks for it when
    output streams in for an agent it has not seen yet, so it can name it.
    """
    agents = get_agent_index(execution_id)
    if agents is None:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return {"execution_id": execution_id, "agents": agents}


# contains= on GET /api/runs/{id}/tool-calls: how many strings, and how long each may be.
MAX_CONTAINS = 20
MAX_CONTAINS_CHARS = 300


@router.get("/api/runs/{execution_id}/tool-calls")
def get_run_tool_calls(execution_id: str, contains: Annotated[list[str] | None, Query()] = None):
    """Every tool call of the run with the files it named, never what was in them.

    For a script step auditing its own run (it has no database): each call's attempt,
    agent, node, round, tool, status and the paths it named; the run's refused calls under
    ``blocked``. Each ``contains=`` string found anywhere in a call's inputs is listed in its
    ``hits``; the inputs themselves never leave the server. See data_service.get_tool_calls.
    """
    contains = contains or []
    if len(contains) > MAX_CONTAINS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_CONTAINS} contains= strings")
    if any(not 1 <= len(text) <= MAX_CONTAINS_CHARS for text in contains):
        raise HTTPException(
            status_code=400, detail=f"Each contains= string takes 1 to {MAX_CONTAINS_CHARS} characters",
        )
    result = get_tool_calls(execution_id, contains)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return result


@router.get("/api/runs/{execution_id}/agents/{attempt_id}/log")
def get_script_log(
    execution_id: str,
    attempt_id: str,
    after_seq: int | None = None,
    before_seq: int | None = None,
    max_bytes: int | None = None,
):
    """One page of a script agent's saved log: what its script printed, oldest row first.

    ``attempt_id`` is the agent's id on the run page (its agent.started event): each attempt, a
    retry included, has its own log. With no cursor the page is the newest output; ``before_seq``
    pages back from a row, ``after_seq`` catches up after one. A page is whole rows, about
    ``max_bytes`` of output (256 KB unless asked, 4 MB at most). See observability/script_logs.py.
    """
    from temper_ai.observability.script_logs import DEFAULT_PAGE_BYTES, read_script_log

    if after_seq is not None and before_seq is not None:
        raise HTTPException(status_code=400, detail="Ask for after_seq or before_seq, not both")
    page = read_script_log(
        execution_id, attempt_id, after_seq=after_seq, before_seq=before_seq,
        max_bytes=max_bytes if max_bytes and max_bytes > 0 else DEFAULT_PAGE_BYTES,
    )
    if page is None:
        raise HTTPException(
            status_code=404, detail=f"Run '{execution_id}' has no agent '{attempt_id}'",
        )
    return page


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
    rejected: dict[str, Any] = {"gate_status": REJECTED, "gate_decided_at": _now_iso()}
    if reason:
        rejected["gate_response"] = {"response": reason, "answers": [], "text": reason}
    for ev in _waiting_gate_events(execution_id):
        # Only a wait still open: an approval that got there first stands as it was given.
        decide_event(str(ev["id"]), expect=(WAITING,), status=REJECTED, data=rejected)
    cancel_event = _state().running.get(execution_id)
    if cancel_event is not None:
        cancel_event.set()
        return {"status": "cancelling", "execution_id": execution_id}

    # A Pi run parked at a gate with no worker: nothing is left to stop, so it ends here.
    if not _run_is_alive(execution_id) and pi_parked.cancel_parked(execution_id, reason or None):
        return {"status": "cancelled", "execution_id": execution_id}

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
    # Steps that finished and are to run again anyway -- ticked on the preview. Everything
    # that used their results runs again with them (stage/plan.py).
    rerun: list[str] = []


class ForkRequest(BaseModel):
    """Request to fork a workflow from a specific checkpoint."""

    workflow: str  # Workflow config to use for the fork
    source_execution_id: str
    sequence: int  # Checkpoint sequence to fork from
    inputs: dict = {}
    workspace_path: str | None = None


def _stopped_at(run: dict | None) -> str | None:
    """Where the run stopped, as its workflow event recorded it.

    ``get_workflow_execution`` lifts it out of the event's data to the top (``stopped``);
    older answers and the raw event keep it under ``data``, so look in both.
    """
    run = run or {}
    stopped = run.get("stopped") or (run.get("data") or {}).get("stopped") or {}
    path = stopped.get("path") if isinstance(stopped, dict) else None
    return str(path) if path else None


def _plan_for(execution_id: str, workflow: str | None, rerun: list[str]) -> dict:
    """What a resume of this run would do with each of its steps, and what it is holding.

    The page shows it before anything runs, and the resume itself works it out the same way
    from the same function, so what someone approves is what happens (stage/plan.py).
    """
    run = get_workflow_execution(execution_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    name = workflow or run.get("workflow_name")
    if not name:
        raise HTTPException(status_code=400, detail="Cannot determine workflow name")
    try:
        nodes, _config = _state().graph_loader.load_workflow(name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = resume_plan(
        nodes, CheckpointService(execution_id),
        rerun=rerun, stopped_at=_stopped_at(run),
    )
    out = plan.as_dict()
    out["execution_id"] = execution_id
    out["workflow_name"] = name
    out["hold"] = holds.waiting(execution_id)
    return out


@router.get("/api/runs/{execution_id}/resume-preview")
def resume_preview(execution_id: str, workflow: str | None = None, rerun: str = ""):
    """What a resume would keep, run again, or make again -- grouped by stage.

    ``rerun`` is a comma-separated list of steps ticked to run again even though they
    finished; the answer takes them, and everything that used their results, with it.
    """
    ticked = [p.strip() for p in rerun.split(",") if p.strip()]
    return _plan_for(execution_id, workflow, ticked)


@router.post("/api/runs/{execution_id}/cleanup")
def release_cleanups(execution_id: str):
    """Give up on picking this run up: run the clean-ups it was holding, now.

    The run itself stays failed. Its box starts once more and runs those steps and nothing
    else, so the dev stack and the worktree it was keeping for a resume are let go.
    """
    run = get_workflow_execution(execution_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    ended = holds.end(execution_id, "released", by="give_up")
    if ended is None:
        raise HTTPException(status_code=409,
                            detail="This run is not holding any clean-ups")
    _queue_cleanup_pass(ended)
    return {"execution_id": execution_id, "status": "queued",
            "cleanups": [c.get("path") for c in ended["cleanups"]]}


def _queue_cleanup_pass(hold: dict) -> None:
    """Start the run once more, in its own box, to run only the clean-ups it was holding."""
    execution_id = hold["execution_id"]
    paths = [str(c.get("path")) for c in hold.get("cleanups", []) if c.get("path")]
    if not paths:
        return
    mode = _execution_mode()
    if mode == "inprocess":
        logger.info("%s: its held clean-ups are for its box to run; this server runs in "
                    "process, so they are left alone", execution_id)
        return
    _queue_run(execution_id, hold["workflow_name"], hold.get("workspace_path") or None,
               hold.get("inputs") or {}, start="cleanup", extra={"only": paths})
    if mode == "subprocess":
        # External mode has a watcher that picks the queued row up; here the server is the
        # one that starts boxes, so it starts this one itself.
        from temper_ai.spawner import SpawnerError, get_spawner
        try:
            get_spawner().spawn(execution_id)
        except SpawnerError:
            logger.exception("%s: could not start a box for its held clean-ups", execution_id)
            raise HTTPException(
                status_code=503,
                detail="Could not start a box to run the held clean-ups",
            ) from None
    logger.info("%s: running its held clean-ups now (%s)", execution_id, ", ".join(paths))


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
    pi_run = is_pi_workflow(nodes)

    # A Pi run often starts by asking the owner something, so it can be resumed before its
    # first step has finished: it starts again from its first step, and a wait it had opened
    # is waited on again, not asked twice (docs/gates.md). Any other workflow needs a
    # finished step to resume from.
    if not restored_outputs and not pi_run:
        raise HTTPException(status_code=400, detail="No checkpoints found — nothing to resume from")

    # A Pi run parked at a gate is carried on once, by whoever claims its parked attempt
    # first: the owner's answer, the worker that let go, start-up, or this button.
    parked = pi_parked.parked_attempt(execution_id) if pi_run else None
    if parked is not None and not pi_parked.claim(parked):
        raise HTTPException(status_code=409, detail=f"Execution '{execution_id}' is already being carried on")
    if pi_run and parked is None:
        # Never a second copy of a Pi run: one is going here, or another asker has just
        # claimed it and is starting it. (A box's row refuses a second box on its own.)
        if execution_id in _state().running or pi_parked.being_carried_on(execution_id):
            raise HTTPException(status_code=409, detail=f"Execution '{execution_id}' is already running")
    try:
        return _start_resume(execution_id, body, result, nodes, config, checkpoint_svc, restored_outputs)
    except BaseException:
        if parked is not None:
            pi_parked.release(parked)
        raise


def _start_resume(
    execution_id: str,
    body: ResumeRequest,
    result: dict,
    nodes: list,
    config: Any,
    checkpoint_svc: CheckpointService,
    restored_outputs: dict,
) -> RunResponse:
    """Start the resumed attempt: in its own box, or on a thread here (resume_run checked it)."""
    # This attempt takes over any clean-ups the last one was holding: they are its business
    # now, and an old deadline must not tear down the setup it is about to use.
    holds.take_over(execution_id, by=execution_id)
    stopped_at = _stopped_at(result)

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

    # The run's own inputs, each declared default in place of one it left out: a run started
    # before defaults were filled in has none of them (stage/input_defaults.py).
    original_inputs = fill_input_defaults(getattr(config, "inputs", None), result.get("input_data"))

    if _execution_mode() == "external":
        # Its box restores the checkpoints and replays the dispatches
        # (temper run-workflow), the same steps as below.
        _queue_run(execution_id, config.name, workspace,
                   original_inputs, start="resume",
                   extra={"rerun": list(body.rerun or [])})
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
        failure_policy=FailurePolicy.parse(getattr(config, "on_failure", None)),
        park_at_gates=is_pi_workflow(nodes),
    )

    bind_delegate_tool(run_tool_executor, context)

    # What this resume will do with each step, worked out once and shared with the preview,
    # so what someone approved on the page is what runs (stage/plan.py).
    context.restore, _plan = build_restore(
        nodes, checkpoint_svc, restored_outputs,
        rerun=body.rerun or (), stopped_at=stopped_at,
    )

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
        name=f"temper-run-{execution_id}",
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

    # Each declared default in place of an input the fork leaves out (stage/input_defaults.py).
    inputs = fill_input_defaults(getattr(config, "inputs", None), body.inputs)

    logger.info(
        "Forking execution '%s' at sequence %d → new execution '%s' with %d nodes restored",
        body.source_execution_id, body.sequence, new_execution_id, len(restored_outputs),
    )

    # A fork of a run that is holding its clean-ups takes them over: it is using that setup
    # now, and the source's deadline must not tear it down underneath it. The fork holds
    # them again itself, with its own deadline, if it too stops at a failure.
    holds.take_over(body.source_execution_id, by=new_execution_id)

    if _execution_mode() == "external":
        # The checkpoints are already copied under the new id; its box
        # restores them (temper run-workflow).
        _record_fork_metadata(new_execution_id, body, restored_outputs, nodes)
        _queue_run(new_execution_id, config.name, body.workspace_path,
                   inputs, start="fork")
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
        failure_policy=FailurePolicy.parse(getattr(config, "on_failure", None)),
        park_at_gates=is_pi_workflow(nodes),
    )

    bind_delegate_tool(run_tool_executor, context)

    _record_fork_metadata(new_execution_id, body, restored_outputs, nodes)

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
    # Which wait this answers (the ``event_id`` /gates lists). With it, an approval made in a
    # tab or message from an earlier round is refused (409) instead of answering the next one.
    event_id: str | None = None
    # One per click: the same request sent again returns the first result and changes nothing.
    request_id: str | None = None
    # Who is answering ("Ana (Slack)"), kept with the decision and named in a refusal.
    by: str = ""


NEEDS_RESUME = ("Approved and kept. The run is not running, so it needs Resume; when it comes "
                "back it goes on with this answer without asking again.")

# Without a database row to decide on, only the in-process signal can say whether an approval
# was first; this keeps two of them from both getting through.
_SIGNAL_LOCK = threading.Lock()


@router.post("/api/runs/{execution_id}/approve/{node_name}")
def approve_gate(execution_id: str, node_name: str, body: GateApproval | None = None):
    """Approve one wait at a gate, allowing the workflow to continue.

    Which wait: the body's ``event_id`` (what ``GET .../gates`` lists, and what every
    message and button carries). Without one, the wait at ``node_name`` -- a step's name or
    its path -- when exactly one is open there; several open there is a 409 listing them.

    The approval lands only while that wait is still open, so of two at once exactly one
    gets through; the other, and one aimed at a wait already answered or replaced (an older
    round, a stale tab), gets a 409 saying who answered and when. A ``request_id`` sent
    again returns the first result and touches nothing else.

    In-process runs are unblocked through the shared gate registry; runs
    executing in a worker process/container (subprocess or external mode)
    poll the waiting event, which is marked ``approved`` in the database.
    An approval of a run that is not running is kept (``needs_resume``):
    when the run is resumed it goes on with it without asking again.

    The optional body carries the human's answers to the questions the
    previous node asked and/or a free-text response; the gated node
    receives it as its ``gate`` input (see :mod:`temper_ai.stage.gate`).
    """
    body = body or GateApproval()
    request_id = (body.request_id or "").strip() or None
    if request_id:
        first = _first_answer_to(execution_id, request_id)
        if first is not None:
            return first
    try:
        event, signal = _gate_to_approve(execution_id, node_name, (body.event_id or "").strip() or None)
    except HTTPException as exc:
        # The same request sent twice at once: the other copy may have answered the wait
        # between the look above and this one. Its answer is this request's answer.
        if request_id and exc.status_code in (404, 409):
            first = _first_answer_to(execution_id, request_id)
            if first is not None:
                return first
        raise
    response = normalise_response(body.model_dump(include={"response", "answers"}))
    alive = _run_is_alive(execution_id)
    # A Pi run that let its worker go at this wait, or is letting go (its box gone but not yet
    # seen gone, or its thread ending), is carried on by the answer: it does not need Resume
    # (runner/parked.py).
    parked = pi_parked.parked_attempt(execution_id)
    by = body.by.strip()
    decided: dict[str, Any] = {
        "gate_status": APPROVED, "gate_decided_at": _now_iso(),
        **({"gate_decided_by": by} if by else {}),
        **({"gate_request_id": request_id} if request_id else {}),
        **({"gate_response": response} if response else {}),
        **({} if alive or parked else {"gate_kept_for_resume": True}),
        **({"gate_carries_on": True} if parked else {}),
    }
    if event is not None:
        won, after = decide_event(str(event["id"]), expect=(WAITING,), status=APPROVED, data=decided)
        if not won:
            if after is None:
                raise HTTPException(status_code=404, detail=f"Approval {event['id']} is gone")
            if request_id and (after.get("data") or {}).get("gate_request_id") == request_id:
                return _approval_reply(execution_id, after, repeated=True)
            raise HTTPException(status_code=409, detail=refusal(describe_gate(after)))
        gate = describe_gate(after or event)
        signal = signal or _state().gates.get(signal_key(execution_id, str(event["id"])))
    else:
        assert signal is not None  # _gate_to_approve found one or raised
        with _SIGNAL_LOCK:
            if signal.is_set():
                raise HTTPException(status_code=409, detail=refusal(_signal_gate(signal, APPROVED)))
            signal.response = response
            signal.set()
        return {**_signal_gate(signal, APPROVED), "execution_id": execution_id, "response": response,
                "request_id": request_id, "repeated": False, "needs_resume": False}
    if signal is not None:
        if response is not None:
            signal.response = response
        signal.set()
    # A Pi run parked here, or that parked while this answer went in, carries on now. (If it
    # was still letting go, the worker carries it on as it lets go: one of the two sees the
    # other, and the claim makes sure only one starts it.)
    carried = _carry_on_parked(execution_id, by="answer")
    reply = _approval_reply(execution_id, {**(after or event), "status": APPROVED,
                                           "data": {**(event.get("data") or {}), **decided}})
    if parked is not None or carried:
        carries_on = carried or _carried_on_elsewhere(execution_id)
        reply["carries_on"] = carries_on
        if not carries_on and pi_parked.parked_attempt(execution_id) is not None:
            # It could not be started: the answer is kept, and Resume carries it on.
            reply.update(needs_resume=True, message=NEEDS_RESUME)
    else:
        carries_on = False
    logger.info("Gate: approved '%s' round %s of %s (event %s)%s", gate["path"], gate["round"],
                execution_id[:8], gate["event_id"],
                "; carrying the run on" if carried
                else "; the worker carries the run on as it lets go" if carries_on
                else "" if alive or parked else "; the run needs Resume")
    return reply


def _carried_on_elsewhere(execution_id: str) -> bool:
    """Whether a parked Pi run this answer did not start itself carries on all the same.

    Its worker is still letting go (and carries it on as it does: the run is still alive), or
    someone else claimed it first (its newest attempt is no longer the parked one, and it was
    not cancelled). False when it is still parked with nothing letting it go.
    """
    if pi_parked.parked_attempt(execution_id) is not None:
        return _run_is_alive(execution_id)
    latest = _find_latest_workflow_event(execution_id) or {}
    return latest.get("status") != pi_parked.CANCELLED


def _approval_reply(execution_id: str, ev: dict[str, Any], *, repeated: bool = False) -> dict[str, Any]:
    """What an approval returns -- again, unchanged, for the same request sent twice."""
    data = ev.get("data") or {}
    needs_resume = bool(data.get("gate_kept_for_resume")) and not data.get("gate_used_at")
    return {
        **describe_gate(ev),
        "status": APPROVED,
        "execution_id": execution_id,
        "node_name": data.get("name", ""),
        "response": data.get("gate_response"),
        "repeated": repeated,
        "needs_resume": needs_resume,
        **({"message": NEEDS_RESUME} if needs_resume else {}),
    }


def _first_answer_to(execution_id: str, request_id: str) -> dict[str, Any] | None:
    """The result of the approval this request already made, if it made one."""
    for ev in gate_events(execution_id):
        if (ev.get("data") or {}).get("gate_request_id") == request_id:
            return _approval_reply(execution_id, ev, repeated=True)
    return None


def _gate_to_approve(execution_id: str, node: str, event_id: str | None) -> tuple[dict | None, Any]:
    """The wait an approval is for: its event (when the run keeps them) and in-process signal.

    Raises 404 when there is none, 409 when the one named is no longer open, or when the
    approval names only a step and several waits are open there.
    """
    registry = _state().gates
    prefix = f"{execution_id}:"
    if event_id:
        event = get_event(event_id)
        data = (event or {}).get("data") or {}
        if event is not None and event.get("execution_id") == execution_id and data.get("gate"):
            if not names_gate(data, node):
                raise HTTPException(status_code=404, detail=(
                    f"Approval {event_id} is at '{gate_path(data)}', not '{node}'"))
            if event.get("status") != WAITING:
                raise HTTPException(status_code=409, detail=refusal(describe_gate(event)))
            return event, registry.get(signal_key(execution_id, event_id))
        signal = registry.get(signal_key(execution_id, event_id))
        if signal is not None and node in (signal.node_name, signal.path):
            return None, signal
        raise HTTPException(status_code=404, detail=(
            f"No approval {event_id} at '{node}' in execution '{execution_id}'"))
    open_waits = _waiting_gate_events(execution_id)
    waits = [ev for ev in open_waits if names_gate(ev.get("data") or {}, node)]
    known = {str(ev.get("id")) for ev in open_waits}
    signals = [s for key, s in list(registry.items())
               if key.startswith(prefix) and not s.is_set() and node in (s.node_name, s.path)
               and s.event_id not in known]
    if not waits and not signals:
        raise HTTPException(
            status_code=404,
            detail=f"No gate waiting for node '{node}' in execution '{execution_id}'",
        )
    if len(waits) + len(signals) > 1:
        listed = [describe_gate(ev) for ev in waits] + [_signal_gate(s, WAITING) for s in signals]
        raise HTTPException(status_code=409, detail=several_waiting(node, listed))
    if waits:
        return waits[0], registry.get(signal_key(execution_id, str(waits[0]["id"])))
    return None, signals[0]


def _signal_gate(signal: Any, status: str) -> dict[str, Any]:
    """A wait known only to this process (its run keeps no events), as a refusal shows it."""
    return {"event_id": signal.event_id or None, "node_name": signal.node_name, "path": signal.path,
            "round": signal.round, "status": status, "answered_by": None, "answered_at": None,
            "request_id": None, "replaced_by": None, "opened_at": None}


def _run_is_alive(execution_id: str) -> bool:
    """Is some process running this run, so that an approval reaches it now?"""
    if execution_id in _state().running:
        return True
    try:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        with get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            return row is not None and row.status in ("queued", "running")
    except Exception as exc:  # noqa: BLE001 - cannot tell: say nothing about Resume
        logger.warning("could not tell whether %s is running: %s", execution_id[:8], exc)
        return True


@router.get("/api/runs/{execution_id}/gates")
def list_gates(execution_id: str):
    """List all gates currently waiting for approval in an execution.

    One entry per open wait, ordered by step and round. Each carries what the human
    should see: ``upstream`` (the outputs of the nodes the gated node depends on) and
    ``questions`` (the ones those outputs asked, in the ask_user_question shape), plus
    which wait it is -- ``event_id``, the step's ``path`` and the ``round`` -- which an
    approval sends back so it answers this wait and no other.
    """
    prefix = f"{execution_id}:"
    waiting: list[dict] = []
    known: set[str] = set()
    for ev in _waiting_gate_events(execution_id):
        data = ev.get("data") or {}
        name = data.get("name", "")
        if not name:
            continue
        gate_context = data.get("gate_context") or {}
        known.add(str(ev.get("id")))
        waiting.append({
            "node_name": name,
            "status": WAITING,
            "event_id": ev.get("id"),
            "path": gate_path(data),
            "round": data.get("gate_round"),
            "opened_at": ev.get("timestamp"),
            "upstream": gate_context.get("upstream") or [],
            "questions": gate_context.get("questions") or [],
        })
    for key, signal in list(_state().gates.items()):
        if key.startswith(prefix) and not signal.is_set() and signal.event_id not in known:
            waiting.append({"node_name": signal.node_name, "status": WAITING, "event_id": signal.event_id or None,
                            "path": signal.path, "round": signal.round, "opened_at": None,
                            "upstream": [], "questions": []})
    waiting.sort(key=lambda g: (str(g["path"]), g["round"] or 0, str(g["opened_at"] or "")))
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
        and (node_name is None or names_gate(ev.get("data") or {}, node_name))
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
    ``rejected`` / ``replaced`` -- a run picked up again asked in a new one),
    which wait it was (``path``, ``round``), when it opened and when and by
    whom it was decided, the questions it asked and the ``response`` the human
    gave (answers and free text; a plain approval has none). A loop that gates
    the same node twice lists it twice.

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
            "path": gate_path(data),
            "round": data.get("gate_round"),
            "status": data.get("gate_status") or ev.get("status") or "waiting",
            "opened_at": ev.get("timestamp"),
            "decided_at": data.get("gate_decided_at"),
            "decided_by": data.get("gate_decided_by"),
            "request_id": data.get("gate_request_id"),
            "replaced_by": data.get("gate_replaced_by"),
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
    except RunParked as parked:
        logger.info("Workflow '%s' waits on you at '%s'; its thread lets go", workflow_name, parked.path)
    except Exception as exc:
        logger.error("Workflow '%s' failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _let_go(execution_id, context)
        ws_manager.cleanup(execution_id)
        # Clean up per-run tool executor thread pool
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)
        _see_to_parked(execution_id, context)


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
    except RunParked as parked:
        logger.info("Workflow '%s' waits on you at '%s'; its thread lets go", workflow_name, parked.path)
    except Exception as exc:
        logger.error("Workflow '%s' resume failed: %s", workflow_name, exc, exc_info=True)
    finally:
        _let_go(execution_id, context)
        ws_manager.cleanup(execution_id)
        if hasattr(context, 'tool_executor') and context.tool_executor:
            context.tool_executor.shutdown(wait=False)
        _see_to_parked(execution_id, context)


def _let_go(execution_id: str, context: Any) -> None:
    """The run's thread is ending: it no longer counts as running in this server.

    A Pi run may have been carried on already by the time its old thread ends (the answer
    came while it was letting go), so it frees only its own place, never the new attempt's.
    """
    running = _state().running
    if not getattr(context, "park_at_gates", False):
        running.pop(execution_id, None)
        return
    if running.get(execution_id) is getattr(context, "cancel_event", None):
        running.pop(execution_id, None)


def _see_to_parked(execution_id: str, context: Any) -> None:
    """A Pi run whose thread let go at a gate: cancel it if a cancel came while it let go,
    or carry it on if the answer is already in (runner/parked.py)."""
    if not getattr(context, "park_at_gates", False):
        return
    try:
        if pi_parked.parked_attempt(execution_id) is None:
            return
        cancel_event = getattr(context, "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            pi_parked.cancel_parked(execution_id, by="cancel while letting go")
            return
        _carry_on_parked(execution_id, by="the worker let go")
    except Exception as exc:  # noqa: BLE001 - the run waits; the next answer or start-up looks again
        logger.warning("Run %s: could not see to its parked wait: %s", execution_id, exc)


def _carry_on_parked(execution_id: str, *, by: str) -> bool:
    """Carry a parked Pi run on through Resume's own path, if the owner has answered and no
    worker holds it."""
    if _run_is_alive(execution_id):
        return False
    return pi_parked.carry_on(
        execution_id, start=lambda eid: resume_run(eid, ResumeRequest()), by=by,
    )
