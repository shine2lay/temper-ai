"""Delegate tool — allows agents to invoke other agents/stages as sub-tasks.

An agent calls Delegate like any other tool. The engine creates proper
agent nodes, runs them (with full observability), and returns results
to the calling agent's tool-calling loop.

Usage in agent config:
    tools: [Bash, FileWriter, Delegate]

The agent calls it like:
    Delegate(tasks=[
        {"agent": "implementer", "inputs": {"file": "Button.tsx", "task": "..."}},
        {"agent": "reviewer", "inputs": {"files": ["Button.tsx"]}},
    ])

Each task runs as a visible agent in the DAG. Results come back as JSON
so the calling agent can reason about them and delegate more work.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace as dc_replace
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENCY = 3


class Delegate(BaseTool):
    """Invoke other agents as sub-tasks within the current workflow."""

    name = "Delegate"
    description = (
        "Run one or more agents as sub-tasks. Each task specifies an agent name "
        "and inputs. Results are returned as JSON. Use this to delegate work to "
        "specialized agents and get their output back."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": (
                    "List of tasks to delegate. Each task has 'agent' (agent config name) "
                    "and 'inputs' (dict of input data for that agent)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Name of the agent config to run",
                        },
                        "inputs": {
                            "type": "object",
                            "description": "Input data to pass to the agent",
                        },
                    },
                    "required": ["agent"],
                },
            },
        },
        "required": ["tasks"],
    }
    modifies_state = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._execution_context = None
        self._max_concurrency = (config or {}).get("max_concurrency", _DEFAULT_MAX_CONCURRENCY)

    def bind_context(self, context: Any) -> None:
        """Bind the ExecutionContext so the tool can create and run agents.

        Called by routes.py when setting up the per-run tool executor.
        """
        self._execution_context = context


    def execute(self, **params: Any) -> ToolResult:
        tasks = params.get("tasks", [])
        if not tasks:
            return ToolResult(success=False, result="", error="No tasks provided")

        if self._execution_context is None:
            return ToolResult(success=False, result="", error="Delegate tool not bound to execution context")

        ctx = self._execution_context

        # Load agent configs and create agent instances
        from temper_ai.agent import create_agent
        from temper_ai.config import ConfigStore
        from temper_ai.stage.loader import _unwrap_config

        config_store = ConfigStore()
        results = []

        # Get workflow defaults from the context's workflow config (if available)
        workflow_defaults = {}
        try:
            wf_raw = config_store.get(ctx.workflow_name, "workflow")
            wf_config = _unwrap_config(wf_raw, "workflow")
            workflow_defaults = wf_config.get("defaults", {})
        except Exception:
            pass

        # The graph event ID is where delegated nodes attach as siblings in the DAG.
        # This makes them appear as top-level nodes alongside the calling agent.
        graph_event_id = ctx.graph_event_id or ctx.parent_event_id

        def _run_task(idx: int, task: dict) -> dict:
            agent_ref = task.get("agent", "")
            task_inputs = task.get("inputs", {})

            try:
                raw = config_store.get(agent_ref, "agent")
                agent_config = {**workflow_defaults, **_unwrap_config(raw, "agent")}
            except Exception as exc:
                return {
                    "task_index": idx,
                    "agent": agent_ref,
                    "status": "failed",
                    "error": f"Failed to load agent '{agent_ref}': {exc}",
                    "output": "",
                }

            agent_name = agent_config.get("name", agent_ref)
            node_name = f"delegate:{agent_name}_{idx}"

            # Emit stage.started event parented to the graph — makes this a DAG node
            stage_event_id = ctx.event_recorder.record(
                "stage.started",
                parent_id=graph_event_id,
                execution_id=ctx.run_id,
                status="running",
                data={
                    "name": node_name,
                    "type": "delegate",
                    "depends_on": [ctx.node_path] if ctx.node_path else [],
                    "strategy": None,
                    "delegated_by": ctx.agent_name,
                    "delegate_source": ctx.node_path,
                },
            )

            agent = create_agent(agent_config)
            agent_ctx = dc_replace(
                ctx,
                parent_event_id=stage_event_id,
                agent_name=agent_name,
                node_path=f"{ctx.node_path}.delegate.{agent_ref}_{idx}",
            )

            agent_result = agent.run(task_inputs, agent_ctx)

            # Update stage event with completion status
            ctx.event_recorder.update_event(
                stage_event_id,
                status=agent_result.status.value,
                data={
                    "cost_usd": agent_result.cost_usd,
                    "total_tokens": agent_result.tokens.total_tokens,
                    "duration_seconds": agent_result.duration_seconds,
                },
            )

            # Checkpoint if available
            if ctx.checkpoint_service:
                ctx.checkpoint_service.save_agent_completed(
                    ctx.node_path or "delegate",
                    f"{agent_ref}_{idx}",
                    agent_result,
                )

            return {
                "task_index": idx,
                "agent": agent_ref,
                "status": agent_result.status.value,
                "output": agent_result.output,
                "structured_output": agent_result.structured_output,
                "error": agent_result.error,
                "cost_usd": agent_result.cost_usd,
                "tokens": agent_result.tokens.total_tokens,
            }

        # Run tasks with concurrency control
        if len(tasks) == 1:
            results = [_run_task(0, tasks[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(self._max_concurrency, len(tasks))) as pool:
                futures = {pool.submit(_run_task, i, t): i for i, t in enumerate(tasks)}
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        idx = futures[future]
                        results.append({
                            "task_index": idx,
                            "agent": tasks[idx].get("agent", "?"),
                            "status": "failed",
                            "error": str(exc),
                            "output": "",
                        })

        # Sort by task_index for deterministic output
        results.sort(key=lambda r: r.get("task_index", 0))

        all_ok = all(r.get("status") == "completed" for r in results)
        summary = json.dumps(results, indent=2, default=str)

        return ToolResult(
            success=all_ok,
            result=summary,
            error=None if all_ok else f"{sum(1 for r in results if r.get('status') != 'completed')}/{len(results)} tasks failed",
            metadata={
                "task_count": len(tasks),
                "completed": sum(1 for r in results if r.get("status") == "completed"),
                "failed": sum(1 for r in results if r.get("status") != "completed"),
            },
        )
