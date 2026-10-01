"""Fakes for the Slack, Telegram and notify tests: a Slack and a Telegram
that record what temper sends, and a temper (``TemperOps``) with runs,
gates and workflows held in memory."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import pytest

from temper_ai.config.search import search_workflows
from temper_ai.integrations.slack.access import AccessConfig
from temper_ai.integrations.slack.client import SlackError
from temper_ai.integrations.slack.ops import OpsError
from temper_ai.integrations.telegram.client import TelegramError

OWNER = "U0OWNER01"
OTHER = "U0OTHER02"
# Telegram: the owner's user id is also their private chat's id.
TG_OWNER = 8000000001
TG_OTHER = 8000000002
TG_GROUP = -5000000001
TG_BOT = 7000000001
TG_BOT_NAME = "temper_test_bot"


class FakeAccess:
    """The access rules a handler asks, as the test sets them.

    The default is no access file at all: everyone may do everything, which
    is what every test that is not about access expects.
    """

    def __init__(self, config: AccessConfig | None = None) -> None:
        self.config = config or AccessConfig(on=False)

    def get(self) -> AccessConfig:
        return self.config


class FakeSlack:
    """Records posts, edits and response_url answers. ``forbidden`` channels
    answer not_in_channel, like a channel the bot was never added to."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.forbidden: set[str] = set()
        self.threads: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.views: list[dict[str, Any]] = []
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

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        self.views.append({"trigger_id": trigger_id, "view": view})
        return {"ok": True}

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
        self.answers: list[dict[str, Any]] = []   # what each approve carried
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

    def cancel(self, execution_id: str, reason: str, by: str = "") -> dict[str, Any]:
        self.cancelled.append((execution_id, reason))
        self.runs[execution_id]["status"] = "cancelled"
        for g in self.gates:
            if g["execution_id"] == execution_id:
                ev = self.decisions[g["id"]]
                ev["status"] = "rejected"
                ev["data"].update(gate_status="rejected", **({"gate_decided_by": by} if by else {}))
        self.gates = [g for g in self.gates if g["execution_id"] != execution_id]
        return {"status": "cancelled"}

    def resume(self, execution_id: str) -> str:
        self.resumed.append(execution_id)
        return execution_id

    # gates
    def add_gate(self, event_id: str, execution_id: str, node: str, at: datetime,
                 questions: list[dict[str, Any]] | None = None,
                 upstream: list[dict[str, Any]] | None = None) -> None:
        data = {"name": node, "gate": True,
                "gate_context": {"upstream": list(upstream or []), "questions": list(questions or [])}}
        self.gates.append({"id": event_id, "execution_id": execution_id, "timestamp": _iso(at), "data": data})
        # The gate's event as gate_decision reads it: the same data, which
        # an answer adds to.
        self.decisions[event_id] = {"status": "waiting", "data": data}

    def waiting_gates(self, execution_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        # Newest first, like the real one.
        return [g for g in reversed(self.gates) if execution_id is None or g["execution_id"] == execution_id]

    def gate_info(self, execution_id: str, node: str) -> dict[str, Any] | None:
        for g in self.gates:
            if g["execution_id"] == execution_id and g["data"]["name"] == node:
                context = g["data"]["gate_context"]
                return {"node_name": node, "event_id": g["id"], "questions": context["questions"],
                        "upstream": context["upstream"]}
        return None

    def gate_decision(self, event_id: str) -> dict[str, Any] | None:
        return self.decisions.get(event_id)

    def run_is_alive(self, execution_id: str) -> bool:
        return execution_id in self.alive

    def approve(self, execution_id: str, node: str, answers: list[dict[str, Any]] | None = None,
                response: str = "", by: str = "") -> dict[str, Any]:
        waiting = [g for g in self.gates if g["execution_id"] == execution_id and g["data"]["name"] == node]
        if not waiting:
            raise OpsError(f"No gate waiting for node '{node}'")
        self.approved.append((execution_id, node))
        self.answers.append({"execution_id": execution_id, "node": node, "answers": list(answers or []),
                             "response": response, "by": by})
        for g in waiting:
            ev = self.decisions[g["id"]]
            ev["status"] = "approved"
            ev["data"].update(gate_status="approved",
                              gate_response={"response": response, "answers": list(answers or [])},
                              **({"gate_decided_by": by} if by else {}))
        self.gates = [g for g in self.gates if g not in waiting]
        return {"status": "approved"}

    def record_who(self, execution_id: str, node: str | None, who: str) -> int:
        done = 0
        for g in self.gates:
            if g["execution_id"] == execution_id and (node is None or g["data"]["name"] == node):
                self.decisions[g["id"]]["data"]["gate_decided_by"] = who
                done += 1
        return done

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
    """A config dir with a Slack file; returns a writer for it."""
    folder = tmp_path / "slack"
    folder.mkdir()

    def write(body: str) -> None:
        (folder / "slack.yaml").write_text(body)

    write(f"""
slack:
  dashboard_url: https://temper.test
  agents:
    - dm: {OWNER}
    - channel: C0RUNS001
""")
    from temper_ai.integrations.slack import config as config_mod

    monkeypatch.setattr(config_mod, "default_config_dir", lambda: tmp_path)
    return write


NOTIFY_YAML = f"""
notify:
  dashboard_url: https://temper.test
  stuck_after: 30m
  places:
    slack: {{slack: {{dm: {OWNER}}}}}
    runs: {{slack: {{channel: C0RUNS001}}}}
    telegram: {{telegram: {TG_OWNER}}}
    qa-group: {{telegram: {TG_GROUP}}}
  defaults:
    question: origin
    stuck: origin
    failed: origin
    finished: origin
  fallback:
    question: slack
    stuck: slack
    failed: [slack, runs]
    finished: runs
  workflows:
    slack_pick: off
    noisy: {{finished: off}}
  agents: [telegram]
"""

TELEGRAM_YAML = f"""
telegram:
  owners: [{TG_OWNER}]
  groups: []
  zone: America/Los_Angeles
"""


@pytest.fixture
def notify_config(tmp_path, monkeypatch):
    """Config dirs with a notify file and a Telegram file (both used by
    default everywhere); returns a writer for the notify file."""
    (tmp_path / "notify").mkdir(exist_ok=True)
    (tmp_path / "telegram").mkdir(exist_ok=True)

    def write(body: str) -> None:
        path = tmp_path / "notify" / "notify.yaml"
        path.write_text(body)
        # A rewrite within one clock tick must still count as a change.
        import os
        import time

        stamp = time.time() + write.count  # type: ignore[attr-defined]
        os.utime(path, (stamp, stamp))
        write.count += 1  # type: ignore[attr-defined]

    write.count = 1  # type: ignore[attr-defined]
    write(NOTIFY_YAML)
    (tmp_path / "telegram" / "telegram.yaml").write_text(TELEGRAM_YAML)
    from temper_ai.integrations.notify import config as notify_mod
    from temper_ai.integrations.telegram import config as telegram_mod

    monkeypatch.setattr(notify_mod, "default_config_dir", lambda: tmp_path)
    monkeypatch.setattr(telegram_mod, "default_config_dir", lambda: tmp_path)
    return write


class FakeTelegram:
    """Records what temper sends and edits. ``forbidden`` chats answer 403,
    like a chat that blocked the bot."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.markups: list[dict[str, Any]] = []
        self.callbacks: list[tuple[str, str, bool]] = []
        self.left: list[int] = []
        self.members: dict[tuple[int, int], str] = {}
        self.forbidden: set[int] = set()
        self.updates: list[dict[str, Any]] = []
        self._ids = itertools.count(100)

    def send(self, chat_id: int | str, text: str, *, reply_to: int | None = None,
             keyboard: list[list[dict[str, Any]]] | None = None, force_reply: str | None = None,
             html: bool = True, quiet: bool = False) -> dict[str, Any]:
        if int(chat_id) in self.forbidden:
            raise TelegramError("sendMessage", 403, "Forbidden: bot was blocked by the user")
        message_id = next(self._ids)
        self.sent.append({"chat": int(chat_id), "text": text, "reply_to": reply_to, "keyboard": keyboard,
                          "force_reply": force_reply, "quiet": quiet, "message_id": message_id})
        return {"message_id": message_id, "chat": {"id": int(chat_id)}, "text": text}

    def edit_text(self, chat_id: int | str, message_id: int, text: str,
                  keyboard: list[list[dict[str, Any]]] | None = None) -> dict[str, Any]:
        self.edits.append({"chat": int(chat_id), "message_id": message_id, "text": text, "keyboard": keyboard})
        return {}

    def edit_markup(self, chat_id: int | str, message_id: int,
                    keyboard: list[list[dict[str, Any]]] | None = None) -> dict[str, Any]:
        self.markups.append({"chat": int(chat_id), "message_id": message_id, "keyboard": keyboard})
        return {}

    def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        self.callbacks.append((callback_id, text, alert))

    def leave_chat(self, chat_id: int | str) -> None:
        self.left.append(int(chat_id))

    def get_chat_member(self, chat_id: int | str, user_id: int | str) -> dict[str, Any]:
        status = self.members.get((int(chat_id), int(user_id)), "left")
        return {"status": status, "user": {"id": int(user_id), "first_name": "Shine"}}

    def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return {"id": int(chat_id), "type": "private" if int(chat_id) > 0 else "group"}

    def get_me(self) -> dict[str, Any]:
        return {"id": TG_BOT, "is_bot": True, "first_name": "Temper", "username": TG_BOT_NAME}

    def get_updates(self, offset: int | None, timeout: int = 25, allowed: list[str] | None = None) -> list[dict]:
        return [u for u in self.updates if offset is None or u["update_id"] >= offset]

    # what the tests look at
    def last(self, chat: int | None = None) -> dict[str, Any]:
        return [m for m in self.sent if chat is None or m["chat"] == chat][-1]

    @staticmethod
    def buttons(keyboard: list[list[dict[str, Any]]] | None) -> list[tuple[str, str]]:
        return [(b["text"], b.get("callback_data") or b.get("url") or "") for row in keyboard or [] for b in row]


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()
