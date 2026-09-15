"""Tool implementations for the temper MCP server.

These call the same functions the REST API does, so an agent driving temper
over MCP sees exactly what the dashboard sees.

The guiding constraint is the caller's context window. A real run's full
detail payload is large — a `blog_writer` run in a production database is
~91 KB, roughly 23k tokens — so returning it from a single tool call would
crowd out whatever the agent was actually doing. Every tool here is
therefore summary-first: `get_run` reports one line per node, and the bulky
material (prompts, responses, outputs) is fetched deliberately, one node or
one call at a time, with an explicit character budget.
"""

from __future__ import annotations

import functools
import json
from typing import Any

import anyio

# Default ceiling for any single free-text field we hand back. Generous
# enough to read an answer, small enough that a surprise never costs more
# than a few thousand tokens.
DEFAULT_MAX_CHARS = 4000

# Floor for one string inside a structure: below this a message is too
# short to tell you anything.
_MIN_LEAF_CHARS = 256

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _clip(value: Any, max_chars: int = DEFAULT_MAX_CHARS) -> Any:
    """Bound any field to max_chars, saying what it dropped.

    Structures are bounded too, not just strings. A chat prompt arrives as
    a list of message dicts, so clipping only `str` left the single
    largest field in the payload unbounded — exactly the thing this is
    supposed to prevent.
    """
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        dropped = len(value) - max_chars
        return (
            f"{value[:max_chars]}\n\n[truncated {dropped} more characters — "
            f"raise max_chars to see them]"
        )
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, default=str)
        if len(rendered) <= max_chars:
            return value  # small enough to keep as it is
        # Share the budget between the strings inside, so a chat prompt
        # comes back as recognisable messages — every role visible, each
        # one opening with its first few hundred characters — rather than
        # as one truncated blob.
        share = max(_MIN_LEAF_CHARS, max_chars // max(_count_string_leaves(value), 1))
        clipped = _clip_leaves(value, share)
        if len(json.dumps(clipped, default=str)) <= max_chars * 2:
            return clipped
        # Too many pieces to show any of them usefully: hand back the
        # beginning as text rather than blowing the budget.
        return _clip(rendered, max_chars)
    return value


def _count_string_leaves(value: Any) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, list):
        return sum(_count_string_leaves(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_string_leaves(item) for item in value.values())
    return 0


def _clip_leaves(value: Any, max_chars: int) -> Any:
    """Clip every string inside a structure, keeping the structure."""
    if isinstance(value, str):
        return _clip(value, max_chars)
    if isinstance(value, list):
        return [_clip_leaves(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: _clip_leaves(item, max_chars) for key, item in value.items()}
    return value


def _node_summary(node: dict) -> dict:
    """One compact line per node: what ran, how it went, what it cost."""
    agents = ([node["agent"]] if node.get("agent") else []) + (node.get("agents") or [])
    summary = {
        "name": node.get("name"),
        "type": node.get("type"),
        "status": node.get("status"),
        "duration_seconds": node.get("duration_seconds"),
    }
    if node.get("total_tokens"):
        summary["tokens"] = node["total_tokens"]
    if node.get("cost_usd"):
        summary["cost_usd"] = round(node["cost_usd"], 4)
    if node.get("error_message"):
        summary["error"] = _clip(node["error_message"], 500)
    if agents:
        summary["agents"] = [a.get("agent_name") for a in agents if a]
    # Enough shape that an agent can reason about ordering and loops
    # without fetching the whole graph.
    if node.get("depends_on"):
        summary["depends_on"] = node["depends_on"]
    if node.get("child_nodes"):
        summary["children"] = [_node_summary(c) for c in node["child_nodes"]]
    return summary


def _iter_nodes(nodes: list[dict]):
    """Walk the node tree, including dispatched/nested children."""
    for node in nodes:
        yield node
        if node.get("child_nodes"):
            yield from _iter_nodes(node["child_nodes"])


def _find_node(run: dict, node_name: str) -> dict | None:
    for node in _iter_nodes(run.get("nodes") or []):
        if node.get("name") == node_name:
            return node
    return None


def _agents_of(node: dict) -> list[dict]:
    return [a for a in ([node.get("agent")] + (node.get("agents") or [])) if a]


class TemperTools:
    """Tool bodies, bound to the server's own state.

    Kept as a class so the CLI bridge and the mounted HTTP server share one
    implementation; neither can drift from the engine it reports on.
    """

    def __init__(self) -> None:
        # Imported lazily: the CLI must be able to load this module without
        # standing up server state.
        from temper_ai.api import routes

        self._routes = routes

    # -- discovery ---------------------------------------------------------

    def list_workflows(self) -> dict:
        """Workflows available to run, with the inputs each one declares."""
        from temper_ai.api.routes import _state

        store = _state().config_store
        workflows = []
        for entry in store.list(config_type="workflow"):
            name = entry.get("name")
            if not name:
                continue
            try:
                raw = store.get(name, "workflow")
            except Exception:  # pragma: no cover - a config that won't load
                continue
            body = raw.get("workflow", raw)
            declared = body.get("inputs") or {}
            inputs = {}
            for key, spec in declared.items():
                # Both the modern schema ({type, required}) and the old
                # shorthand (name: "string") appear in the wild.
                if isinstance(spec, dict):
                    inputs[key] = {
                        "type": spec.get("type", "string"),
                        "required": bool(spec.get("required", False)),
                    }
                else:
                    inputs[key] = {"type": str(spec), "required": False}
            workflows.append(
                {
                    "name": name,
                    "description": _clip(body.get("description"), 300),
                    "inputs": inputs,
                }
            )
        return {"workflows": sorted(workflows, key=lambda w: w["name"] or "")}

    def list_runs(
        self,
        workflow: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Recent runs, newest first."""
        result = self._routes.list_workflows(limit=min(limit, 100), offset=0, status=status)
        runs = result.get("runs", [])
        if workflow:
            runs = [r for r in runs if r.get("workflow_name") == workflow]
        return {"runs": runs, "total_matching_status": result.get("total")}

    # -- running -----------------------------------------------------------

    def run_workflow(
        self,
        workflow: str,
        inputs: dict | None = None,
        workspace_path: str | None = None,
    ) -> dict:
        """Start a run and return immediately with its id.

        Runs can take minutes, so this never blocks; call `wait_for_run` or
        poll `get_run`.
        """
        request = self._routes.RunRequest(
            workflow=workflow,
            inputs=inputs or {},
            workspace_path=workspace_path,
        )
        response = self._routes.start_run(request)
        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        data["next"] = "poll get_run(execution_id) or call wait_for_run(execution_id)"
        return data

    async def wait_for_run(self, execution_id: str, timeout_seconds: float = 120.0) -> dict:
        """Wait until a run reaches a terminal state, or the timeout.

        Returns the same summary as `get_run`, plus `timed_out` so the
        caller can tell "still running" from "finished".

        Async on purpose. FastMCP calls synchronous tools directly on the
        event loop, so sleeping here in a sync function froze the whole
        server — dashboard, API and every other MCP call — for as long as
        an agent waited. The polling sleep yields, and each database read
        happens on a worker thread.
        """
        deadline = anyio.current_time() + timeout_seconds
        while True:
            summary = await anyio.to_thread.run_sync(
                functools.partial(self.get_run, execution_id)
            )
            if summary.get("error"):
                return summary
            if summary.get("status") in TERMINAL_STATUSES:
                summary["timed_out"] = False
                return summary
            if anyio.current_time() >= deadline:
                summary["timed_out"] = True
                summary["hint"] = "still running — call wait_for_run again to keep waiting"
                return summary
            await anyio.sleep(1.0)

    def cancel_run(self, execution_id: str) -> dict:
        """Ask a running workflow to stop."""
        return self._routes.cancel_run(execution_id)

    # -- inspection --------------------------------------------------------

    def get_run(self, execution_id: str, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
        """Status of a run plus one line per node.

        Deliberately omits prompts, responses and node outputs — use
        `get_node_output` or `get_llm_call` for those.
        """
        from temper_ai.api.data_service import get_workflow_execution

        run = get_workflow_execution(execution_id)
        if not run:
            return {"error": f"no run with id {execution_id}"}

        nodes = run.get("nodes") or []
        return {
            "execution_id": run.get("id"),
            "workflow": run.get("workflow_name"),
            "status": run.get("status"),
            "start_time": run.get("start_time"),
            "end_time": run.get("end_time"),
            "duration_seconds": run.get("duration_seconds"),
            "total_tokens": run.get("total_tokens"),
            "total_cost_usd": run.get("total_cost_usd"),
            "inputs": run.get("input_data"),
            "output": _clip(run.get("workflow_output"), max_chars),
            "error_message": _clip(run.get("error_message"), max_chars),
            "nodes": [_node_summary(n) for n in nodes],
            "failed_nodes": [
                n.get("name")
                for n in _iter_nodes(nodes)
                if n.get("status") == "failed"
            ],
        }

    def get_node_output(
        self,
        execution_id: str,
        node_name: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """What one node's agent(s) produced: output, structured output, input."""
        from temper_ai.api.data_service import get_workflow_execution

        run = get_workflow_execution(execution_id)
        if not run:
            return {"error": f"no run with id {execution_id}"}
        node = _find_node(run, node_name)
        if not node:
            available = [n.get("name") for n in _iter_nodes(run.get("nodes") or [])]
            return {"error": f"no node {node_name!r} in this run", "available": available}

        agents = []
        for agent in _agents_of(node):
            agents.append(
                {
                    "agent": agent.get("agent_name"),
                    "role": agent.get("role"),
                    "status": agent.get("status"),
                    "input": _clip(agent.get("input_data"), max_chars),
                    "output": _clip(agent.get("output"), max_chars),
                    "structured_output": _clip(agent.get("structured_output"), max_chars),
                    "error_message": _clip(agent.get("error_message"), max_chars),
                    "llm_call_ids": [c.get("id") for c in (agent.get("llm_calls") or [])],
                    "tool_calls": [
                        {
                            "tool": t.get("tool_name"),
                            "status": t.get("status"),
                            "duration_seconds": t.get("duration_seconds"),
                        }
                        for t in (agent.get("tool_calls") or [])
                    ],
                }
            )
        return {
            "node": node_name,
            "status": node.get("status"),
            "error_message": _clip(node.get("error_message"), max_chars),
            "agents": agents,
        }

    def get_llm_call(
        self,
        execution_id: str,
        call_id: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """The prompt, response and thinking of one LLM call.

        This is the expensive one — ask for it when you need to know *why*
        a node produced what it did.
        """
        from temper_ai.api.data_service import get_workflow_execution

        run = get_workflow_execution(execution_id)
        if not run:
            return {"error": f"no run with id {execution_id}"}

        for node in _iter_nodes(run.get("nodes") or []):
            for agent in _agents_of(node):
                for call in agent.get("llm_calls") or []:
                    if call.get("id") == call_id:
                        return {
                            "node": node.get("name"),
                            "agent": agent.get("agent_name"),
                            "provider": call.get("provider"),
                            "model": call.get("model"),
                            "status": call.get("status"),
                            "tokens": call.get("total_tokens"),
                            "cost_usd": call.get("estimated_cost_usd"),
                            "prompt": _clip(call.get("prompt"), max_chars),
                            "response": _clip(call.get("response"), max_chars),
                            "thinking": _clip(call.get("thinking"), max_chars),
                            "error_message": _clip(call.get("error_message"), max_chars),
                        }
        return {"error": f"no LLM call {call_id!r} in run {execution_id}"}

    # -- gates -------------------------------------------------------------

    def list_gates(self, execution_id: str) -> dict:
        """Approval gates this run is waiting on."""
        return self._routes.list_gates(execution_id)

    def approve_gate(self, execution_id: str, node_name: str) -> dict:
        """Release a waiting gate so the run continues."""
        return self._routes.approve_gate(execution_id, node_name)
