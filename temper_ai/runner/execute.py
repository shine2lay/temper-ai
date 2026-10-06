"""Workflow execution entry point — extracted from temper_ai.api.routes.

Phase 1 goal: take the workflow-execution logic that's currently inlined in
the route handlers (`_run_workflow`, `_run_workflow_with_checkpoints`) and
make it a standalone callable that doesn't depend on FastAPI / route state.

Server still calls this from a thread (no behavior change). Phase 2 will
have a CLI invoke this standalone. Phase 3 will have a subprocess spawner
invoke this in a fresh process.

The function is intentionally synchronous + thread-friendly (returns when
done), matching the existing wrappers' contract. No async; no signal
handling; the caller (route handler in phase 1, CLI in phase 2, subprocess
main() in phase 3) is responsible for those.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.runner._helpers import (
    McpPreconnectError,
    bind_delegate_tool,
    build_dispatch_limits,
    preconnect_mcp_servers,
)
from temper_ai.runner.parked import PARKED_STATUS
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.exceptions import RunParked
from temper_ai.stage.executor import execute_graph, execute_graph_with_state
from temper_ai.stage.failure import FailurePolicy
from temper_ai.stage.pi_workflows import is_pi_workflow
from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from temper_ai.runner.context import RunnerContext

logger = logging.getLogger(__name__)


@dataclass
class ExecuteResult:
    """Outcome of an execute_workflow call.

    Returned to the caller (server thread today; CLI process tomorrow) so it
    can surface terminal status via whatever channel matters (DB row update,
    process exit code, etc.).
    """

    exit_code: int  # 0 = success, 1 = workflow failure, 2 = setup failure
    status: str  # "completed" | "failed" | "cancelled" | "waiting" (a Pi run that let its worker go at a gate)
    cost_usd: float = 0.0
    total_tokens: int = 0
    error: str | None = None


def execute_workflow(
    *,
    execution_id: str,
    workflow_name: str,
    workspace_path: str | None,
    inputs: dict[str, Any],
    runner_ctx: RunnerContext,
    notifier: Any = None,
    cancel_event: threading.Event | None = None,
    initial_outputs: dict[str, Any] | None = None,
    resume_metadata: dict[str, Any] | None = None,
    replay_dispatch_history: bool = False,
    rerun: list[str] | None = None,
    run_only: list[str] | None = None,
) -> ExecuteResult:
    """Run one workflow end-to-end.

    Args:
        execution_id: stable run identifier; used for events, checkpoints, ws routing.
        workflow_name: which workflow YAML to load via runner_ctx.graph_loader.
        workspace_path: filesystem root for tools (file writes, bash cwd, etc.).
        inputs: workflow-level inputs (top of `inputs.*` references).
        runner_ctx: server-bound state (graph loader, llm providers, memory, configs).
        notifier: optional WS notifier (today: api.websocket.ws_manager). None means
            no live event broadcast — events still land in DB via EventRecorder.
        cancel_event: caller-owned threading.Event. Set to request cancellation;
            the executor checks at node boundaries. None means uncancellable.
        initial_outputs: pre-populated node_outputs for resume. None = fresh run.
        resume_metadata: passed through to the WORKFLOW_STARTED event so the
            view can identify the new attempt as a resume. None = fresh run.
        replay_dispatch_history: on a resume, put back the nodes the run's
            dispatchers added before it stopped (and their caps), the way the
            server's resume route does. Its ``replayed_dispatches`` go into
            ``resume_metadata``.
        rerun: node paths that finished but are to run again anyway -- what someone
            ticked on the preview. Everything that used their results runs again too.
        run_only: node paths this pass may run; everything else is passed over.
            Used for the pass that runs the clean-ups a failed run was holding,
            once the wait is over (Give up, or the deadline). None = the whole run.

    Returns:
        ExecuteResult with terminal status + headline metrics. The tool
        executor is made here and shut down here (its thread pool and scratch
        directory end with the run; the caller never sees it). Cleanup of the
        resources the caller does own (cancel_event removal from any global
        registry, ws_manager.cleanup) is intentionally NOT done here so the
        runner stays decoupled from the route handler's bookkeeping.
    """
    is_resume = initial_outputs is not None
    op_label = "Resuming" if is_resume else "Starting"
    resume_suffix = (
        f" — {len(initial_outputs)} nodes pre-loaded" if initial_outputs else ""
    )
    logger.info(
        "%s workflow '%s' (execution: %s)%s",
        op_label,
        workflow_name,
        execution_id,
        resume_suffix,
    )

    # --- Workflow loading (raises on bad config; caller decides whether to surface) ---
    # A new run also gets the strategies' run-start checks (only the Pi team has one,
    # with its switch on); a resume doesn't check again.
    from temper_ai.stage.topology import run_start_options
    nodes, config = runner_ctx.graph_loader.load_workflow(
        workflow_name, inputs=inputs, **({} if is_resume else run_start_options()),
    )
    # Each declared default in place of an input left out, null or empty, the values the loader
    # read: a resume, a fork and a run queued before defaults were filled in get them too, and
    # every step that reads the run's inputs (one that checks them again on a resume included)
    # sees what the run used (stage/input_defaults.py).
    from temper_ai.stage.input_defaults import fill_input_defaults
    inputs = fill_input_defaults(getattr(config, "inputs", None), inputs)

    # --- Tool executor + safety policy ---
    # Baseline tripwires plus the workflow's own safety block, see PolicyEngine.for_run.
    from temper_ai.safety import PolicyEngine
    policy_engine = PolicyEngine.for_run(config.safety)
    logger.info("Safety policies loaded: %d", len(policy_engine.policies))

    run_tool_executor = ToolExecutor(
        workspace_root=workspace_path,
        policy_engine=policy_engine,
    )
    # A sealed box registers only the tools its classified launch has (box_guard.py); an
    # agent naming any other stops with ToolsNotRegisteredError before any tool runs.
    from temper_ai.spawner import box_guard
    kept, left_out = box_guard.classified_tools(TOOL_CLASSES)
    if left_out:
        logger.info("Sealed box: %d tool(s) outside the run's classified launch are not "
                    "registered", len(left_out))
    run_tool_executor.register_tools({name: TOOL_CLASSES[name]() for name in kept})

    # MCP tools — pre-connect any servers the workflow's agents reference.
    from temper_ai.tools.mcp_client import mcp_manager
    from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents

    agent_configs = [cfg for node in nodes for cfg in node.agent_configs()]
    mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
    mcp_kept, mcp_left_out = box_guard.classified_tools(mcp_tools)
    if mcp_left_out:
        logger.error("Sealed box: MCP tools outside the run's classified launch are not "
                     "registered: %s", ", ".join(sorted(mcp_left_out)))
        mcp_tools = {name: mcp_tools[name] for name in mcp_kept}
    if mcp_tools:
        run_tool_executor.register_tools(dict(mcp_tools))
        try:
            preconnect_mcp_servers(mcp_manager, mcp_tools)
        except McpPreconnectError as exc:
            logger.error("MCP preconnect failed for '%s': %s", workflow_name, exc)
            return ExecuteResult(
                exit_code=2,
                status="failed",
                error=str(exc),
            )

    # --- Recorder, cancel, checkpoint ---
    recorder = EventRecorder(execution_id, notifier=notifier)
    if cancel_event is None:
        cancel_event = threading.Event()  # no-op if caller doesn't share it
    checkpoint_svc = CheckpointService(execution_id)

    # --- ExecutionContext ---
    # Note: gate_registry and dispatch_limits live in AppState today. RunnerContext
    # doesn't carry them yet; caller must inject via the optional fields if they're
    # needed (route handler will). Phase 3+ may move them into RunnerContext if the
    # CLI needs them too.
    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=run_tool_executor,
        memory_service=runner_ctx.memory_service,
        llm_providers=runner_ctx.llm_providers,
        workspace_path=workspace_path,
        cancel_event=cancel_event,
        checkpoint_service=checkpoint_svc,
        gate_registry=getattr(runner_ctx, "gate_registry", None) or {},
        graph_loader=runner_ctx.graph_loader,
        dispatch_limits=build_dispatch_limits(config),
        # What a failure does in this workflow: hold the clean-ups (the default) or run them.
        failure_policy=FailurePolicy.parse(getattr(config, "on_failure", None)),
        run_only=set(run_only) if run_only else None,
        # A Pi workflow's gates let the worker go while they wait (runner/parked.py).
        park_at_gates=is_pi_workflow(nodes),
    )

    # Bind Delegate tool so agents can spawn sub-agents
    bind_delegate_tool(run_tool_executor, context)

    if is_resume:
        # What the resume will do with each step, worked out once -- the same answer the
        # preview showed, so what was approved is what happens (stage/plan.py).
        from temper_ai.stage.plan import build_restore
        stopped = (resume_metadata or {}).get("stopped_at")
        context.restore, resume_plan = build_restore(
            nodes, checkpoint_svc, initial_outputs or {}, rerun=rerun or (), stopped_at=stopped,
        )
        if resume_metadata is not None:
            resume_metadata = {**resume_metadata, "plan": resume_plan.as_dict()["counts"]}

    if replay_dispatch_history:
        from temper_ai.runner.resume import apply_dispatch_history_on_resume
        replayed = apply_dispatch_history_on_resume(
            checkpoint_svc=checkpoint_svc,
            graph_loader=runner_ctx.graph_loader,
            nodes=nodes,
            context=context,
        )
        if resume_metadata is not None:
            resume_metadata = {**resume_metadata, "replayed_dispatches": replayed}

    # A workflow whose scripts start other runs gets its own key for them, for this process's
    # life only (api/run_tokens.py); every other run gets none.
    holds_run_key = bool(getattr(config, "starts_runs", False))
    if holds_run_key:
        from temper_ai.api.run_tokens import open_for_run
        open_for_run(execution_id, config.name)
    # A run that gets its GitHub tokens from the server (every run in its own box) holds a key to
    # ask with, for this process's life only, and gives it to nobody: not its script steps, not its
    # agents' tools (api/run_tokens.py GITHUB_TOKENS). Every such run, not only those listing a
    # GitHub tool, because Delegate, AddNode and dispatch can bring one in while the run goes on.
    from temper_ai.integrations.github import app as github_app
    holds_github_key = github_app.asks_server_for_tokens()
    if holds_github_key:
        from temper_ai.api.run_tokens import GITHUB_TOKENS
        from temper_ai.api.run_tokens import open_for_run as open_key_for_run
        github_app.use_run_key(open_key_for_run(execution_id, config.name, kind=GITHUB_TOKENS))

    # --- Execute (the real workflow engine) ---
    try:
        if is_resume:
            result = execute_graph_with_state(
                nodes, inputs, context,
                graph_name=workflow_name,
                is_workflow=True,
                initial_outputs=initial_outputs,
                # Same workflow, so the same declared outputs: a resumed run that
                # does not map them finishes reporting nothing about what it did.
                workflow_outputs=config.outputs,
                resume_metadata=resume_metadata,
            )
        else:
            result = execute_graph(
                nodes, inputs, context,
                graph_name=workflow_name,
                is_workflow=True,
                workflow_outputs=config.outputs,
            )
    except RunParked as parked:
        # Not over: it waits on the owner with its place saved, and this worker can go. The
        # answer carries it on in a new box (runner/parked.py).
        logger.info("Workflow '%s' waits on you at '%s'; its worker lets go", workflow_name, parked.path)
        return ExecuteResult(exit_code=0, status=PARKED_STATUS)
    except Exception as exc:
        logger.exception("Workflow '%s' failed during execute_graph: %s", workflow_name, exc)
        return ExecuteResult(
            exit_code=1,
            status="failed",
            error=str(exc),
        )
    finally:
        # The executor is per run: its thread pool and its scratch directory
        # end with the run. (The API routes and `temper run` do the same.)
        run_tool_executor.shutdown(wait=False)
        if holds_run_key:
            from temper_ai.api.run_tokens import close_for_run
            close_for_run(execution_id)
        if holds_github_key:
            from temper_ai.api.run_tokens import GITHUB_TOKENS
            from temper_ai.api.run_tokens import close_for_run as close_key_for_run
            github_app.use_run_key(None)
            close_key_for_run(execution_id, kind=GITHUB_TOKENS)

    logger.info(
        "Workflow '%s' %s: status=%s, cost=$%.4f, tokens=%d",
        workflow_name,
        "resumed and completed" if is_resume else "completed",
        result.status,
        result.cost_usd,
        result.total_tokens,
    )

    return ExecuteResult(
        exit_code=0 if result.status == "completed" else 1,
        status=result.status,
        cost_usd=result.cost_usd,
        total_tokens=result.total_tokens,
        # a run that ended cancelled by itself says why (M3 E18: an owner's stop answer)
        error=result.error if result.status == "cancelled" else None,
    )
