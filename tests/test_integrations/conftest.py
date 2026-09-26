"""Fakes for the Slack tests: a Slack that records what temper sends, and a
temper (``TemperOps``) with runs, gates and workflows held in memory."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import pytest

from temper_ai.config.search import search_workflows
from temper_ai.integrations.slack.client import SlackError
from temper_ai.integrations.slack.ops import OpsError

OWNER = "U0OWNER01"
OTHER = "U0OTHER02"


class FakeSlack:
    """Records posts, edits and response_url answers. ``forbidden`` channels
    answer not_in_channel, like a channel the bot was never added to."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.forbidden: set[str] = set()
        self.threads: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.scopes: tuple[str, ...] = ()
        self._ts = itertools.count(1)

    def _next_ts(self) -> str:
        return f"1790000000.{next(self._ts):06d}"

    def post(self, channel: str, text: str, blocks: list[dict] | None = None, thread_ts: str | None = None,
             broadcast: bool = False) -> dict[str, Any]:
        if channel in self.forbidden:
            raise SlackError("chat.postMessage", "not_in_channel")
        ts = self._next_ts()
        msg = {"channel": channel, "text": text, "blocks": blocks, "thread_ts": thread_ts,
               "broadcast": broadcast, "ts": ts}
        self.posts.append(msg)
        self.threads.setdefault((channel, thread_ts or ts), []).append({"ts": ts, "text": text, "bot_id": "B1"})
        return {"ok": True, "channel": channel, "ts": ts}

    def update(self, channel: str, ts: str, text: str, blocks: list[dict] | None = None) -> dict[str, Any]:
        self.updates.append({"channel": channel, "ts": ts, "text": text, "blocks": blocks})
        return {"ok": True}

    def replies(self, channel: str, ts: str, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.threads.get((channel, ts), []))[:limit]

    def open_dm(self, user: str) -> str:
        return f"D{user}"

    def user_name(self, user: str) -> str:
        return {OWNER: "shine"}.get(user, user)

    def resolve(self, target: str) -> str:
        if target.startswith(("U", "W")):
            return self.open_dm(target)
        if target.startswith("#"):
            return f"C{target[1:].upper()}"
        return target

    def respond(self, url: str, payload: dict[str, Any]) -> None:
        self.responses.append({"url": url, **payload})

    def auth_test(self) -> dict[str, Any]:
        return {"ok": True, "user": "temper", "user_id": "UBOT", "team": "Roamee", "team_id": "T1"}

    def open_socket_url(self, token: str | None = None) -> str:
        return "wss://example.invalid/socket"

    # what the tests look at
    def texts(self) -> list[str]:
        return [p["text"] for p in self.posts]

    def buttons(self, message: dict[str, Any]) -> list[str]:
        return [e.get("action_id") for b in (message.get("blocks") or []) if b.get("type") == "actions"
                for e in b.get("elements") or []]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class FakeOps:
    """TemperOps with everything in memory."""

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self.entries = entries if entries is not None else [
            {"name": "trigger_probe", "description": "Echo a note back; a cheap probe for triggers.",
             "inputs": {"note": {"type": "string", "required": False, "description": "What to echo"}}},
            {"name": "gate_demo", "description": "Ask a person to approve before the last step.",
             "inputs": {"topic": {"type": "string", "required": True, "description": "What it is about"},
                        "rounds": {"type": "integer", "required": False, "description": "How many rounds"}}},
            {"name": "mystery", "description": "", "inputs": {}},
        ]
        self.runs: dict[str, dict[str, Any]] = {}
        self.summaries: dict[str, dict[str, Any]] = {}
        self.started: list[tuple[str, dict[str, Any]]] = []
        self.cancelled: list[tuple[str, str]] = []
        self.approved: list[tuple[str, str]] = []
        self.resumed: list[str] = []
        self.gates: list[dict[str, Any]] = []      # waiting gate events
        self.decisions: dict[str, dict[str, Any]] = {}
        self.alive: set[str] = set()
        self.activity: dict[str, datetime] = {}
        self.outputs: dict[tuple[str, str], dict[str, Any]] = {}
        self.agent_texts: dict[tuple[str, str], str] = {}
        self.start_error: str | None = None
        self._ids = itertools.count(1)
        self.on_start: Any = None

    # workflows
    def catalog(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self.entries]

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        return search_workflows(query, limit=limit, entries=self.catalog())

    # runs
    def add_run(self, execution_id: str, workflow: str, status: str, start: datetime,
                end: datetime | None = None, **summary: Any) -> dict[str, Any]:
        run = {"id": execution_id, "workflow_name": workflow, "status": status, "start_time": _iso(start),
               "end_time": _iso(end) if end else None}
        self.runs[execution_id] = run
        self.summaries[execution_id] = {"execution_id": execution_id, "workflow": workflow, "status": status,
                                        "nodes": [], **summary}
        return run

    def start(self, workflow: str, inputs: dict[str, Any]) -> str:
        if self.start_error:
            raise OpsError(self.start_error)
        execution_id = f"{next(self._ids):08x}-0000-4000-8000-000000000000"
        self.started.append((workflow, inputs))
        self.add_run(execution_id, workflow, "running", datetime.now(UTC))
        self.alive.add(execution_id)
        if self.on_start:
            self.on_start(execution_id, workflow, inputs)
        return execution_id

    def summary(self, execution_id: str) -> dict[str, Any]:
        if execution_id not in self.summaries:
            return {"error": f"no run with id {execution_id}"}
        return dict(self.summaries[execution_id], status=self.runs[execution_id]["status"])

    def recent(self, status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        runs = list(self.runs.values())
        return [r for r in runs if status is None or r["status"] == status][:limit]

    def resolve(self, ref: str) -> str:
        matches = [r for r in self.runs if r.startswith(ref.lower())]
        if len(matches) != 1:
            raise OpsError(f"No recent run starts with `{ref}`." if not matches else "ambiguous")
        return matches[0]

    def cancel(self, execution_id: str, reason: str) -> dict[str, Any]:
        self.cancelled.append((execution_id, reason))
        self.runs[execution_id]["status"] = "cancelled"
        for g in self.gates:
            if g["execution_id"] == execution_id:
                self.decisions[g["id"]] = {"status": "rejected", "data": {"gate_status": "rejected"}}
        self.gates = [g for g in self.gates if g["execution_id"] != execution_id]
        return {"status": "cancelled"}

    def resume(self, execution_id: str) -> str:
        self.resumed.append(execution_id)
        return execution_id

    # gates
    def add_gate(self, event_id: str, execution_id: str, node: str, at: datetime) -> None:
        self.gates.append({"id": event_id, "execution_id": execution_id, "timestamp": _iso(at),
                           "data": {"name": node, "gate": True, "gate_context": {"upstream": [], "questions": []}}})
        self.decisions[event_id] = {"status": "waiting", "data": {"name": node}}

    def waiting_gates(self, execution_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return [g for g in self.gates if execution_id is None or g["execution_id"] == execution_id]

    def gate_info(self, execution_id: str, node: str) -> dict[str, Any] | None:
        for g in self.gates:
            if g["execution_id"] == execution_id and g["data"]["name"] == node:
                return {"node_name": node, "event_id": g["id"]}
        return None

    def gate_decision(self, event_id: str) -> dict[str, Any] | None:
        return self.decisions.get(event_id)

    def run_is_alive(self, execution_id: str) -> bool:
        return execution_id in self.alive

    def approve(self, execution_id: str, node: str) -> dict[str, Any]:
        waiting = [g for g in self.gates if g["execution_id"] == execution_id and g["data"]["name"] == node]
        if not waiting:
            raise OpsError(f"No gate waiting for node '{node}'")
        self.approved.append((execution_id, node))
        for g in waiting:
            self.decisions[g["id"]] = {"status": "approved", "data": {"gate_status": "approved"}}
        self.gates = [g for g in self.gates if g not in waiting]
        return {"status": "approved"}

    def structured_output(self, execution_id: str, node: str) -> dict[str, Any] | None:
        return self.outputs.get((execution_id, node))

    def agent_output(self, execution_id: str, node: str) -> str:
        return self.agent_texts.get((execution_id, node), "")

    def last_activity(self, execution_id: str) -> Any:
        return self.activity.get(execution_id)


@pytest.fixture
def slack() -> FakeSlack:
    return FakeSlack()


@pytest.fixture
def ops() -> FakeOps:
    return FakeOps()


@pytest.fixture
def slack_config(tmp_path, monkeypatch):
    """A config dir with a Slack routing file; returns a writer for it."""
    folder = tmp_path / "slack"
    folder.mkdir()

    def write(body: str) -> None:
        (folder / "slack.yaml").write_text(body)

    write(f"""
slack:
  dashboard_url: https://temper.test
  stuck_after: 30m
  notify:
    gate: {{dm: {OWNER}}}
    stuck: {{dm: {OWNER}}}
    failed: {{dm: {OWNER}, channel: C0RUNS001}}
    finished: {{channel: C0RUNS001}}
  workflows:
    slack_pick: off
    noisy: {{finished: off}}
  agents:
    - dm: {OWNER}
    - channel: C0RUNS001
""")
    from temper_ai.integrations.slack import config as config_mod

    monkeypatch.setattr(config_mod, "default_config_dir", lambda: tmp_path)
    return write
