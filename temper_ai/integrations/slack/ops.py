"""What Slack can ask temper to do, through the same code as the API.

One class, so the handlers and the notifier can be tested against a fake
of it; the real one calls the route functions directly (no HTTP hop), the
way the trigger scheduler does.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OpsError(RuntimeError):
    """Something the person in Slack should be told, in plain words."""


def _detail(exc: Exception) -> str:
    return str(getattr(exc, "detail", None) or exc)


class TemperOps:
    # -- workflows ---------------------------------------------------------

    def catalog(self) -> list[dict[str, Any]]:
        from temper_ai.config.search import catalog

        return catalog()

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        from temper_ai.config.search import search_workflows

        return search_workflows(query, limit=limit)

    # -- runs ----------------------------------------------------------------

    def start(self, workflow: str, inputs: dict[str, Any]) -> str:
        from temper_ai.api.routes import RunRequest, start_run

        try:
            return start_run(RunRequest(workflow=workflow, inputs=inputs)).execution_id
        except Exception as exc:  # noqa: BLE001 - HTTPException 400/503 and the like
            raise OpsError(_detail(exc)) from exc

    def summary(self, execution_id: str) -> dict[str, Any]:
        """The MCP ``get_run`` shape: status, cost, nodes, failure_summary."""
        from temper_ai.mcp.tools import TemperTools

        out = TemperTools().get_run(execution_id, max_chars=2000)
        # The run's own error only counts the failed steps ("1 node(s) failed:
        # nap"); the step's agent holds the sentence that says what went wrong.
        why = self.step_errors(execution_id)
        if why and out.get("status") == "failed":
            out["failure_summary"] = "; ".join(f"failed at {node}: {err}" for node, err in why[:3])
        return out

    def step_errors(self, execution_id: str) -> list[tuple[str, str]]:
        """(step, error) for each failed step whose agent recorded an error."""
        from temper_ai.api.data_service import get_workflow_execution

        run = get_workflow_execution(execution_id) or {}
        found: list[tuple[str, str]] = []
        stack = list(run.get("nodes") or [])
        while stack:
            n = stack.pop(0)
            stack.extend(n.get("child_nodes") or [])
            if n.get("status") != "failed":
                continue
            agents = ([n["agent"]] if n.get("agent") else []) + list(n.get("agents") or [])
            errors = [str(a.get("error_message")) for a in agents if a and a.get("error_message")]
            err = errors[-1] if errors else n.get("error_message")
            if err:
                found.append((str(n.get("name") or "?"), str(err)))
        return found

    def recent(self, status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        from temper_ai.api.data_service import list_workflow_executions

        return list_workflow_executions(limit=limit, status=status)["runs"]

    def resolve(self, ref: str) -> str:
        """A full run id for an id or its first characters."""
        ref = ref.strip().lower()
        if len(ref) == 36:
            return ref
        matches = [r["id"] for r in self.recent() if str(r.get("id", "")).startswith(ref)]
        if not matches:
            raise OpsError(f"No recent run starts with `{ref}`.")
        if len(set(matches)) > 1:
            raise OpsError(f"`{ref}` matches {len(set(matches))} runs; give more characters.")
        return matches[0]

    def cancel(self, execution_id: str, reason: str, by: str = "") -> dict[str, Any]:
        """Stop a run. ``by`` ("Name (Slack)") is written on its waiting gates
        first, so every copy of their questions can say who stopped it."""
        from temper_ai.api.routes import CancelRequest, cancel_run

        if by:
            self.record_who(execution_id, None, by)
        try:
            return cancel_run(execution_id, CancelRequest(reason=reason))
        except Exception as exc:  # noqa: BLE001
            raise OpsError(_detail(exc)) from exc

    def resume(self, execution_id: str) -> str:
        from temper_ai.api.routes import resume_run

        try:
            return resume_run(execution_id).execution_id
        except Exception as exc:  # noqa: BLE001
            raise OpsError(_detail(exc)) from exc

    # -- gates ---------------------------------------------------------------

    def waiting_gates(self, execution_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Gate waits still open: one event each, newest first.

        With no run given, every run's (the notifier's view).
        """
        from temper_ai.observability.event_types import EventType
        from temper_ai.observability.recorder import get_events

        events = get_events(execution_id=execution_id, event_type=EventType("stage.started"),
                            status="waiting", limit=limit, newest_first=True)
        return [e for e in events if (e.get("data") or {}).get("gate")]

    def gate_info(self, execution_id: str, node: str) -> dict[str, Any] | None:
        from temper_ai.api.routes import list_gates

        for g in list_gates(execution_id).get("gates") or []:
            if g.get("node_name") == node:
                return g
        return None

    def gate_decision(self, event_id: str) -> dict[str, Any] | None:
        """How a gate wait was answered: its event's status and data."""
        from temper_ai.database import get_session
        from temper_ai.observability.models import Event

        with get_session() as session:
            ev = session.get(Event, event_id)
            if ev is None:
                return None
            return {"status": ev.status, "data": ev.data or {}}

    def run_is_alive(self, execution_id: str) -> bool:
        """Is some process running this run (so a gate answer reaches it)?

        After a restart a run parked at a gate has no process; approving
        its old wait changes nothing until the run is resumed.
        """
        from sqlmodel import select

        from temper_ai.api.routes import _state
        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        if execution_id in _state().running:
            return True
        with get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            return row is not None and row.status in ("queued", "running")

    def approve(self, execution_id: str, node: str, answers: list[dict[str, Any]] | None = None,
                response: str = "", by: str = "") -> dict[str, Any]:
        """Approve a waiting gate, with the answers to its questions.

        ``answers`` are {id, question, selected, custom}; ``by`` ("Name
        (Telegram)") is written on the waiting events first: once the gate
        is approved, the notify loop may close the other copies at any
        moment, and they should say who answered.
        """
        from temper_ai.api.routes import GateAnswer, GateApproval, approve_gate

        if by:
            self.record_who(execution_id, node, by)
        body = GateApproval(response=response or "", answers=[GateAnswer(**a) for a in (answers or [])])
        try:
            return approve_gate(execution_id, node, body)
        except Exception as exc:  # noqa: BLE001
            raise OpsError(_detail(exc)) from exc

    def record_who(self, execution_id: str, node: str | None, who: str) -> int:
        """Write ``gate_decided_by`` on the run's waiting gate events (one
        node's, or all). Returns how many; never raises."""
        try:
            from temper_ai.observability.recorder import update_event

            events = self.waiting_gates(execution_id)
            done = 0
            for ev in events:
                if node is None or (ev.get("data") or {}).get("name") == node:
                    update_event(str(ev["id"]), data={"gate_decided_by": who})
                    done += 1
            return done
        except Exception as exc:  # noqa: BLE001 - the decision stands without the name
            logger.warning("could not record who answered %s: %s", execution_id[:8], exc)
            return 0

    # -- a finished run's answer -------------------------------------------------

    def structured_output(self, execution_id: str, node: str) -> dict[str, Any] | None:
        """The last structured output of ``node``'s agents, if any."""
        for agent in reversed(self._agents(execution_id, node)):
            out = agent.get("structured_output")
            if isinstance(out, dict):
                return out
        return None

    def agent_output(self, execution_id: str, node: str) -> str:
        """The text ``node``'s last agent answered with ('' if none)."""
        for agent in reversed(self._agents(execution_id, node)):
            out = agent.get("output")
            if isinstance(out, str) and out.strip():
                return out
        return ""

    def _agents(self, execution_id: str, node: str) -> list[dict[str, Any]]:
        from temper_ai.api.data_service import get_workflow_execution

        run = get_workflow_execution(execution_id) or {}
        stack = list(run.get("nodes") or [])
        while stack:
            n = stack.pop(0)
            if n.get("name") == node:
                agents = ([n["agent"]] if n.get("agent") else []) + (n.get("agents") or [])
                return [a for a in agents if isinstance(a, dict)]
            stack.extend(n.get("child_nodes") or [])
        return []

    def last_activity(self, execution_id: str) -> Any:
        from temper_ai.triggers.scheduler import _last_activity

        return _last_activity(execution_id)
