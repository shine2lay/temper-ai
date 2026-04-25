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
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage.executor import execute_graph, execute_graph_with_state
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
    status: str  # "completed" | "failed" | "cancelled"
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

    Returns:
        ExecuteResult with terminal status + headline metrics. Caller is
        responsible for cleanup of per-run resources (cancel_event removal
        from any global registry, ws_manager.cleanup, tool_executor.shutdown).
        These cleanup steps are intentionally NOT done here so the runner
        stays decoupled from the route handler's bookkeeping; the route
        handler's `finally` block continues to own them in phase 1.
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
    nodes, config = runner_ctx.graph_loader.load_workflow(
        workflow_name, inputs=inputs,
    )

    # --- Tool executor + safety policy ---
    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)
        logger.info("Safety policies loaded: %d", len(policy_engine.policies))

    run_tool_executor = ToolExecutor(
        workspace_root=workspace_path,
        policy_engine=policy_engine,
    )
    run_tool_executor.register_tools(
        {name: cls() for name, cls in TOOL_CLASSES.items()},
    )

    # MCP tools — pre-connect any servers the workflow's agents reference.
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
    )

    # Bind Delegate tool so agents can spawn sub-agents
    bind_delegate_tool(run_tool_executor, context)

    # --- Execute (the real workflow engine) ---
    try:
        if is_resume:
            result = execute_graph_with_state(
                nodes, inputs, context,
                graph_name=workflow_name,
                is_workflow=True,
                initial_outputs=initial_outputs,
                resume_metadata=resume_metadata,
            )
        else:
            result = execute_graph(
                nodes, inputs, context,
                graph_name=workflow_name,
                is_workflow=True,
                workflow_outputs=config.outputs,
            )
    except Exception as exc:
        logger.exception("Workflow '%s' failed during execute_graph: %s", workflow_name, exc)
        return ExecuteResult(
            exit_code=1,
            status="failed",
            error=str(exc),
        )

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
    )
