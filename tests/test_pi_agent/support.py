"""Shared pieces of the Pi agent step's sealed tests: a stand-in Pi worker, workflows, a stub
loader, run helpers.

Nothing here starts a container, reaches a model provider, a database server, Redis or the
network: runs use a private SQLite file and an in-process Temper, and the worker box is
replaced by :class:`FakeBox`, which answers Pi's RPC the way Pi 0.87.1 does (same records,
same session file) from a short script.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from temper_ai.agent.base import AgentABC
from temper_ai.pi_agent.box import BoxConfig, BoxSpec
from temper_ai.pi_agent.rpc import RpcError
from temper_ai.shared.types import AgentResult, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig

# An attempt carried on ("parked") is followed by the next one within moments (C7: a Pi
# step's owner wait lets the worker go, and the answer carries the run on).
ACTIVE = ("running", "queued", "waiting", "pending", "parked")
PI_VERSION = "0.87.1"
IMAGE = "sha256:" + "0" * 64
ROLE = "scout"
NOTE_WORD = "quartzfinch"
CHECK_WORD = "lanternmoss"
USAGE_LIMIT_ERROR = ("429 rate_limit_error: You have reached your usage limit; it resets at "
                     "03:00.")

# --- the box config and its folders --------------------------------------------------


def make_search_tools(runtime: Path) -> dict:
    """Stand-in rg and fd at the runtime's top level; returns the box config's ``search_tools``
    block for them (the pinned versions, the stand-ins' own digests)."""
    from temper_ai.pi_agent.search_tools import PINS

    block = {}
    for name, pin in PINS.items():
        binary = runtime / name
        binary.write_text(f"#!/bin/sh\necho stand-in {name}\n")
        binary.chmod(0o755)
        block[name] = {"version": pin.version,
                       "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    return block


def make_box_config(root: Path, **over: Any) -> Path:
    """A complete box config over stand-in folders, stand-in rg and fd pinned (Pi's grep and
    find need them); returns the JSON file's path."""
    runtime = root / "runtime"
    (runtime / "pi" / "dist" / "bundle").mkdir(parents=True, exist_ok=True)
    (runtime / "node").write_text("stand-in")
    (runtime / "pi" / "dist" / "bundle" / "cli.js").write_text("// stand-in")
    (runtime / "pi" / "package.json").write_text(json.dumps({"version": PI_VERSION}))
    search_tools = make_search_tools(runtime)
    ext = root / "identity-ext"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "index.ts").write_text("export default function () {}\n")
    conf = root / "identity-config"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "pi-identity.json").write_text(json.dumps({"notesDir": "notes"}))
    role = root / "identities" / ROLE
    role.mkdir(parents=True, exist_ok=True)
    (role / "identity.json").write_text(json.dumps({"id": ROLE, "title": "Scout"}))
    (role / "notebook.md").write_text(f"## Check\nThe check word is {CHECK_WORD}.\n")
    raw = {
        "image": IMAGE, "runtime_dir": str(runtime), "pi_version": PI_VERSION,
        "identity_extension": str(ext), "identity_config": str(conf),
        "identities_dir": str(root / "identities"), "state_root": str(root / "state"),
        "host_node": "/nonexistent/node", "host_pi": "/nonexistent/pi",
        "socket_root": str(root / "sock"),
        "routes": {"openai-codex": {"provider": "openai-codex", "host": "chatgpt.com"}},
        "turn_timeout_s": 5.0, "model_calls_per_turn": 4, "search_tools": search_tools,
    }
    raw.update(over)
    path = root / "box.json"
    path.write_text(json.dumps(raw))
    return path


ADD_ON_NAMES = ("pi-image-trim", "pi-tldr")


def make_add_ons(root: Path, names: tuple[str, ...] = ADD_ON_NAMES) -> dict:
    """Stand-in pinned add-on copies; returns the box config's ``add_ons`` section."""
    from temper_ai.pi_agent.box import tree_sha256

    pins = {}
    for name in names:
        folder = root / "addons" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.ts").write_text(f"// {name} stand-in\nexport default function () {{}}\n")
        pins[name] = {"dir": str(folder), "entry": "index.ts", "sha256": tree_sha256(folder)}
    return pins


def box_config(root: Path, **over: Any) -> BoxConfig:
    return BoxConfig.load(str(make_box_config(root, **over)))


def spec(pdir: Path, session_id: str = "sess-1", **over: Any) -> BoxSpec:
    values = {"participant_dir": pdir, "session_id": session_id, "role": ROLE,
              "provider": "openai-codex", "model": "gpt-6.1-sol", "thinking": "medium",
              "tools": ["read"]}
    values.update(over)
    return BoxSpec(**values)


# --- Pi's events (what Pi 0.87.1 writes on its RPC stdout) ----------------------------

SETTLED = {"type": "agent_settled"}


def assistant(text: str = "", *, stop: str = "stop", error: str | None = None) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": [{"type": "text", "text": text}] if text else [],
                           "stopReason": stop, "provider": "openai-codex", "model": "gpt-6.1-sol",
                           "usage": {"input": 12, "output": 3, "totalTokens": 15, "cost": {"total": 0}}}
    if error:
        msg["errorMessage"] = error
    return msg


def said(message: dict, deltas: tuple[str, ...] = ()) -> list[dict]:
    out: list[dict] = [{"type": "message_start", "message": {"role": "assistant", "content": []}}]
    if deltas:
        out.append({"type": "message_update", "assistantMessageEvent": {"type": "text_start", "contentIndex": 0}})
        out += [{"type": "message_update",
                 "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": d}}
                for d in deltas]
        out.append({"type": "message_update", "assistantMessageEvent": {"type": "text_end", "contentIndex": 0}})
    out.append({"type": "message_end", "message": message})
    return out


def read_tool(tool_id: str, text: str) -> list[dict]:
    ask = assistant(stop="toolUse")
    ask["content"] = [{"type": "toolCall", "id": tool_id, "name": "read", "arguments": {"path": "note.txt"}}]
    return [*said(ask),
            {"type": "tool_execution_start", "toolCallId": tool_id, "toolName": "read",
             "args": {"path": "note.txt"}},
            {"type": "tool_execution_end", "toolCallId": tool_id, "toolName": "read",
             "result": {"content": [{"type": "text", "text": text}]}, "isError": False}]


# --- the stand-in worker ----------------------------------------------------------------


class FakeRpc:
    """Pi's RPC channel as the turn runner sees it (``send``/``reply``/``next``/``command``)."""

    def __init__(self, box: FakeBox, sink: Callable[[dict], None]):
        self.box = box
        self.sink = sink
        self.responses: dict[str, dict] = {}
        self.queue: queue.Queue[dict] = queue.Queue()
        self.replies: list[dict] = []
        self.sent: list[dict] = []
        self.dead = False
        self._seq = 0

    def send(self, command: str, **fields: Any) -> str:
        if self.dead:
            raise RpcError("command_pipe_closed")
        self._seq += 1
        rid = f"t{self._seq}"
        self.sent.append({"type": command, **{k: v for k, v in fields.items() if k != "message"}})
        for record in self.box.answer(rid, command, fields):
            self.queue.put(record)
        return rid

    def reply(self, record: dict) -> None:
        self.replies.append(record)
        self.box.log.setdefault("ui_replies", []).append(record)

    def next(self, deadline: float) -> dict:
        while True:
            try:
                record = self.queue.get(timeout=max(0.0, min(0.05, deadline - time.monotonic())))
            except queue.Empty:
                if self.dead:
                    raise RpcError("protocol_eof") from None
                if time.monotonic() >= deadline:
                    raise RpcError("protocol_deadline") from None
                continue
            if record.get("type") == "response":
                self.responses[record["id"]] = record
            self.sink(record)
            return record

    def response(self, rid: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        while rid not in self.responses:
            self.next(deadline)
        return self.responses[rid]

    def command(self, command: str, timeout: float = 60, **fields: Any) -> dict:
        return self.response(self.send(command, **fields), timeout)


class FakeBox:
    """Stands in for :class:`temper_ai.pi_agent.box.WorkerBox`: no container, no sockets.

    ``behaviour`` (class attribute, set by a test) says what Pi does with a prompt:
    ``answer`` (default: reads note.txt with the read tool when asked to, then answers with
    what it knows), ``provider_error`` (the provider refuses; Pi settles with an error),
    ``usage_limit`` (the provider refuses with a usage limit; Pi settles with that error),
    ``die`` (the worker dies after the prompt), ``die_in_tool`` (the worker dies while a
    tool runs), ``hang`` (nothing more comes), ``ui`` (an extension asks the owner a
    question first). ``lie`` names a check the worker fails (``model``, ``identity``,
    ``tools``, ``notebook``, ``stray_extension``, and for the add-on read-back
    ``add_on_missing``, ``add_on_extra``, ``image_trim_off``). Every start is logged in
    ``STARTS``.
    """

    behaviour = "answer"
    lie: str | None = None
    STARTS: list[dict] = []
    on_prompt: Callable[[FakeBox], None] | None = None

    def __init__(self, cfg: BoxConfig, spec: BoxSpec, redactor: Any):
        self.cfg = cfg
        self.spec = spec
        self.route = cfg.routes[spec.provider]
        self.redactor = redactor
        self.pdir = Path(spec.participant_dir)
        # Named like a worker box; the name is on the turn before the box starts (R2 C1).
        self.name = f"temper-pi-{uuid.uuid4().hex[:20]}"
        self.allowance = 0
        self.killed = False
        self.closed = False
        self.rpc: FakeRpc | None = None
        self.leaf: str | None = None
        self.inspected = {"network_none": True, "read_only_root": True, "cap_drop_all": True}
        self.launched: dict | None = None
        self.log: dict[str, Any] = {"session_id": spec.session_id, "prompts": 0,
                                    "commands": [], "allowance_at_prompt": None,
                                    "tools": list(spec.tools), "add_ons": list(spec.add_ons)}
        FakeBox.STARTS.append(self.log)

    # --- the WorkerBox surface ---

    def allow(self, count: int) -> None:
        self.allowance = count

    def start(self, sink: Callable[[dict], None]) -> FakeRpc:
        for sub in ("sessions", "workspace", "state", "memory/identities"):
            (self.pdir / sub).mkdir(parents=True, exist_ok=True)
        for stale in ("box-state.json", "box-blocked.json", "box-rewind.json"):
            (self.pdir / "state" / stale).unlink(missing_ok=True)
        # Pi reopens a session at its file's last entry.
        entries = self._entries()[1:]
        self.leaf = entries[-1]["id"] if entries else None
        # What Docker would report: the extensions on Pi's command line and the environment.
        extensions = self.expected_extensions()
        env: dict[str, str] = {}
        if FakeBox.lie == "add_on_missing" and self.spec.add_ons:
            extensions = extensions[:-1]
        elif FakeBox.lie == "add_on_extra":
            extensions = [*extensions, "/ext/addons/stray/index.ts"]
        elif FakeBox.lie == "image_trim_off":
            env["PI_IMAGE_TRIM"] = "off"
        self.launched = {"extensions": extensions, "env": env}
        self.rpc = FakeRpc(self, sink)
        return self.rpc

    def expected_extensions(self) -> list[str]:
        from temper_ai.pi_agent.box import pi_extensions

        return pi_extensions(self.cfg, self.spec, self.route)

    def kill(self) -> None:
        self.killed = True
        if self.rpc:
            self.rpc.dead = True

    def close(self) -> dict:
        self.closed = True
        return {"container": "fake0000", "created": True, "container_removed": True,
                "handoffs": 1 if self.log["prompts"] else 0, "handoffs_denied": 0}

    # --- what Pi does ---

    @property
    def session_file(self) -> Path:
        found = sorted((self.pdir / "sessions").glob(f"*_{self.spec.session_id}.jsonl"))
        if found:
            return found[0]
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        return self.pdir / "sessions" / f"{stamp}_{self.spec.session_id}.jsonl"

    def _append(self, entry: dict) -> None:
        path = self.session_file
        if not path.exists():
            header = {"type": "session", "version": 3, "id": self.spec.session_id,
                      "timestamp": datetime.now(UTC).isoformat(), "cwd": "/w/workspace"}
            path.write_text(json.dumps(header) + "\n")
        new_id = os.urandom(4).hex()
        with path.open("a") as fh:
            fh.write(json.dumps({"id": new_id, "parentId": self.leaf,
                                 "timestamp": datetime.now(UTC).isoformat(), **entry}) + "\n")
        self.leaf = new_id

    def _branch(self) -> list[dict]:
        by_id = {e["id"]: e for e in self._entries()[1:]}
        out, node = [], by_id.get(self.leaf)
        while node is not None:
            out.append(node)
            node = by_id.get(node.get("parentId"))
        return list(reversed(out))

    def _branch_settled(self) -> bool:
        msgs = [e["message"] for e in self._branch() if e.get("type") == "message"]
        return not msgs or (msgs[-1].get("role") == "assistant" and msgs[-1].get("stopReason")
                            in ("stop", "error", "aborted", "length"))

    def _entries(self) -> list[dict]:
        path = self.session_file
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

    def _identity(self) -> str | None:
        ids = [e["data"]["id"] for e in self._branch()
               if e.get("type") == "custom" and e.get("customType") == "identity"]
        return ids[-1] if ids else None

    def answer(self, rid: str, command: str, fields: dict) -> list[dict]:
        self.log["commands"].append(command)

        def ok(data: Any = None) -> dict:
            return {"type": "response", "id": rid, "command": command, "success": True,
                    "data": data}

        if command == "get_state":
            model = self.spec.model if self.lie != "model" else "other-model"
            file = self.session_file
            return [ok({"model": {"provider": self.spec.provider, "id": model},
                        "thinkingLevel": self.spec.thinking, "sessionId": self.spec.session_id,
                        "sessionFile": f"/w/sessions/{file.name}" if file.exists() else None,
                        "isStreaming": False})]
        if command == "get_commands":
            rows = [{"name": "identity", "source": "extension",
                     "sourceInfo": {"path": "/ext/identity/index.ts"}},
                    {"name": "temper-box-state", "source": "extension",
                     "sourceInfo": {"path": "/ext/temper-box/index.ts"}}]
            if self.lie == "stray_extension":
                rows.append({"name": "sneaky", "source": "extension",
                             "sourceInfo": {"path": "/w/agent/extensions/sneaky.ts"}})
            return [ok({"commands": rows})]
        if command != "prompt":
            return [ok()]
        message = str(fields.get("message") or "")
        if message.startswith("/identity "):
            role = message.split(" ", 1)[1].strip()
            if self.lie == "identity":
                role = "someone-else"
            self._append({"type": "custom", "customType": "identity",
                          "data": {"v": 1, "id": role, "via": "command"}})
            return [ok()]
        if message.startswith("/temper-box-rewind "):
            target = message.split(" ", 1)[1].strip()
            known = {e["id"] for e in self._entries()[1:]}
            if target in known:
                self.leaf = target
            self.log.setdefault("rewinds", []).append(target)
            (self.pdir / "state" / "box-rewind.json").write_text(json.dumps({
                "v": 1, "target": target, "cancelled": target not in known, "error": None,
                "leaf_id": self.leaf, "branch_settled": self._branch_settled()}))
            return [ok()]
        if message == "/temper-box-state":
            ident = self._identity()
            nb = self.pdir / "memory" / "identities" / str(ident) / "notebook.md"
            sha = hashlib.sha256(nb.read_bytes()).hexdigest() if nb.is_file() else None
            if self.lie == "notebook":
                sha = "0" * 64
            tools = sorted(self.spec.tools) + (["bash"] if self.lie == "tools" else [])
            (self.pdir / "state" / "box-state.json").write_text(json.dumps({
                "v": 1, "mode": "rpc", "has_ui": True, "session_id": self.spec.session_id,
                "leaf_id": self.leaf, "branch_settled": self._branch_settled(),
                "identity_id": ident, "identity_via": "command",
                "identity_entries": [{"id": ident, "via": "command"}] if ident else [],
                "active_tools": tools, "notebook_sha256": sha, "helper_env": False}))
            return [ok()]
        return self._model_turn(rid, message, ok)

    def _model_turn(self, rid: str, message: str, ok: Callable[..., dict]) -> list[dict]:
        if not self._branch_settled():
            # The probe's input guard: no model call on top of a cut-off turn.
            (self.pdir / "state" / "box-blocked.json").write_text(json.dumps(
                {"blocked": True, "branch_settled": False}))
            self.log["blocked"] = True
            return [ok()]
        self.log["prompts"] += 1
        self.log["allowance_at_prompt"] = self.allowance
        if FakeBox.on_prompt is not None:
            FakeBox.on_prompt(self)
        self._append({"type": "message", "message": {"role": "user", "content": [
            {"type": "text", "text": message}]}})
        out: list[dict] = [ok()]
        mode = self.behaviour
        if mode == "ui":
            out.append({"type": "extension_ui_request", "id": "ui-1", "method": "select",
                        "title": "Pick one", "options": ["a", "b"]})
            mode = "answer"
        if mode in ("die", "hang"):
            if mode == "die":
                self.kill()
            return out
        if mode == "die_in_tool":
            ask = read_tool("call_1", "")[:-1]
            self._append({"type": "message", "message": {**assistant(stop="toolUse")}})
            self.kill()
            return [*out, *ask]
        if mode in ("provider_error", "usage_limit"):
            msg = assistant(stop="error", error=USAGE_LIMIT_ERROR if mode == "usage_limit"
                            else "400 invalid_request_error: the request was refused")
            self._append({"type": "message", "message": msg})
            return [*out, *said(msg), {"type": "agent_end", "messages": []}, SETTLED]
        # answer
        memory = (self.pdir / "workspace" / "note.txt")
        reply_parts = []
        events: list[dict] = []
        if "note.txt" in message and "without using any tools" not in message:
            text = memory.read_text() if memory.is_file() else ""
            events += read_tool(f"call_{self.log['prompts']}", text)
            self._append({"type": "message", "message": assistant(stop="toolUse")})
            self._append({"type": "message", "message": {"role": "toolResult", "content": [
                {"type": "text", "text": text}]}})
            reply_parts.append(text.split()[0] if text else "")
        else:
            seen = [e for e in self._branch() if e.get("type") == "message"
                    and e["message"].get("role") == "toolResult"]
            if seen:
                reply_parts.append(seen[-1]["message"]["content"][0]["text"].split()[0])
        nb = self.pdir / "memory" / "identities" / ROLE / "notebook.md"
        if nb.is_file() and CHECK_WORD in nb.read_text():
            reply_parts.append(CHECK_WORD)
        reply = " ".join(p for p in reply_parts if p) or "ok"
        msg = assistant(reply)
        self._append({"type": "message", "message": msg})
        half = len(reply) // 2
        events += said(msg, (reply[:half], reply[half:]))
        return [*out, *events, {"type": "agent_end", "messages": []}, SETTLED]


def reset_fake() -> None:
    FakeBox.behaviour = "answer"
    FakeBox.lie = None
    FakeBox.on_prompt = None
    FakeBox.STARTS.clear()


# --- an ordinary first node ----------------------------------------------------------

STEP_TYPE = "pi_test_step"


class StepAgent(AgentABC):
    """An ordinary script-like node: completes at once with a fixed output."""

    def run(self, input_data: dict, context: Any) -> AgentResult:
        return AgentResult(status=Status.COMPLETED, output=f"{self.name} done")


# --- workflows and the loader -----------------------------------------------------------


def step(name: str, depends_on=()) -> AgentNode:
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on)),
                     {"name": name, "type": STEP_TYPE})


def pi_node(name: str = "talk", depends_on=("brief",), **cfg: Any) -> AgentNode:
    values = {"name": name, "type": "pi", "role": ROLE, "provider": "openai-codex",
              "model": "gpt-6.1-sol", "thinking": "medium", "tools": ["Read"], "add_ons": [],
              "message": "Read note.txt with the read tool and tell me its first word. "
                         "Topic: {{ topic }}.",
              "workspace_files": {"note.txt": f"{NOTE_WORD} is the first word."},
              "poll_seconds": 0.02}
    values.update(cfg)
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on)), values)


WORKFLOWS: dict[str, Callable[[], list]] = {
    "pi_talk": lambda: [step("brief"), pi_node(), step("audit", ["talk"])],
    "pi_first": lambda: [pi_node(depends_on=()), step("audit", ["talk"])],
    "pi_two_roles": lambda: [step("brief"), pi_node(roles=["a", "b"])],
}


class StubLoader:
    def load_workflow(self, name: str, inputs: dict | None = None, *, run_start: bool = False):
        cfg = SimpleNamespace(name=name, safety=None, outputs=None, on_failure=None,
                              defaults=None, notify=None)
        return WORKFLOWS[name](), cfg

    def _resolve_node(self, nc):
        raise ValueError(f"Pi test workflows dispatch nothing ({nc.name})")


def install_app_state():
    from unittest.mock import MagicMock

    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import init_app_state
    from temper_ai.config import ConfigStore
    from temper_ai.memory import InMemoryStore, MemoryService

    st = AppState(config_store=ConfigStore(), graph_loader=StubLoader(),
                  llm_providers={"mock": MagicMock()},
                  memory_service=MemoryService(InMemoryStore()))
    init_app_state(st)
    return st


def register_types() -> None:
    """The Pi type (as the switch would) plus the ordinary test step, with the stand-in box."""
    import functools

    from temper_ai.agent import register_agent_type
    from temper_ai.pi_agent.host import PiHost
    from temper_ai.pi_agent.turn import run_turn

    register_agent_type("pi", PiHost)
    register_agent_type(STEP_TYPE, StepAgent)
    PiHost.turn_runner = functools.partial(run_turn, box_factory=FakeBox)


def unregister_types() -> None:
    from temper_ai.agent import AGENT_TYPES
    from temper_ai.pi_agent.host import PiHost

    AGENT_TYPES.pop("pi", None)
    AGENT_TYPES.pop(STEP_TYPE, None)
    PiHost.turn_runner = None


# --- running and reading back ---------------------------------------------------------


def start(client, workflow: str, workspace: Path, inputs: dict | None = None) -> str:
    Path(workspace).mkdir(parents=True, exist_ok=True)
    r = client.post("/api/runs", json={"workflow": workflow, "inputs": inputs or {"topic": "l2"},
                                       "workspace_path": str(workspace)})
    assert r.status_code == 200, r.text
    return r.json()["execution_id"]


def approve(client, eid: str, gate_name: str, text: str):
    return client.post(f"/api/runs/{eid}/approve/{gate_name}", json={"response": text})


def events(eid: str, **kw: Any) -> list[dict]:
    from temper_ai.observability.recorder import get_events

    return get_events(execution_id=eid, limit=100000, **kw)


def attempts(eid: str) -> list[dict]:
    return events(eid, event_type="workflow.started")


def wait_for(fn: Callable[[], Any], timeout: float = 20.0, every: float = 0.02,
             what: str = "condition") -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(every)
    raise AssertionError(f"timed out waiting for {what}")


def wait_ended(eid: str, n_attempts: int = 1, timeout: float = 20.0) -> list[dict]:
    """Wait until attempt ``n_attempts`` has ended and the thread that ran it has let go. The
    attempt row ends before that thread leaves the server's running runs, so a Resume sent in
    between is refused as already running (409)."""
    def ended():
        a = attempts(eid)
        if len(a) < n_attempts or a[-1]["status"] in ACTIVE:
            return None
        return None if run_held(eid) else a
    return wait_for(ended, timeout, what=f"attempt {n_attempts} of {eid} to end")


def run_held(eid: str) -> bool:
    """Whether this server still holds the run: in its running runs, or a live thread named
    after it (in-process mode)."""
    from temper_ai.api.routes import _state

    try:
        running = _state().running
    except RuntimeError:  # no server state installed in this test
        running = {}
    return eid in running or any(t.name == f"temper-run-{eid}" and t.is_alive()
                                 for t in threading.enumerate())


def ledger():
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger

    led = Ledger(get_database().engine)
    led.ensure()
    return led


def asked_event(eid: str, wait: dict) -> dict | None:
    """The event a Pi wait was asked under (``ask_owner``'s, named after the wait), the
    latest still waiting; None before the step asked it."""
    found = [e for e in events(eid, event_type="stage.started")
             if (e["data"] or {}).get("name") == wait["gate_name"] and e["status"] == "waiting"]
    return found[-1] if found else None


def open_wait(eid: str, kind: str | None = None, timeout: float = 20.0,
              other_than: str | None = None) -> dict:
    """An open Pi wait the step has asked (its event is waiting), with that event's id as
    ``ask_event_id``. ``other_than``: a wait id to skip (the one just answered)."""
    def find():
        for w in ledger().snapshot(eid)["waits"]:
            if (w["state"] != "open" or (kind is not None and w["kind"] != kind)
                    or w["wait_id"] == other_than):
                continue
            ev = asked_event(eid, w)
            if ev is not None:
                return {**w, "ask_event_id": ev["id"]}
        return None
    return wait_for(find, timeout, what=f"an open {kind or ''} wait in {eid}")


def turn_agents(eid: str) -> list[dict]:
    """The run's Pi turns as the run page sees them: one agent.started each."""
    return [e for e in events(eid, event_type="agent.started")
            if (e["data"] or {}).get("executed_by") == "pi"]


def agent_end(eid: str, agent_event_id: str) -> dict | None:
    ends = [e for e in events(eid) if e["parent_id"] == agent_event_id
            and e["type"] in ("agent.completed", "agent.failed")]
    return ends[-1] if ends else None


def node_status(eid: str, name: str) -> list[str]:
    return [e["status"] for e in events(eid, event_type="stage.started")
            if (e["data"] or {}).get("name") == name]


# --- crashing and restarting ----------------------------------------------------------

WORKTREE = Path(__file__).resolve().parents[2]
_DROP_ENV = ("OPENAI_API_KEY", "OPENAI_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
             "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY", "TEMPER_REDIS_URL", "REDIS_URL",
             "TEMPER_WEBHOOK_URL")


def crash_child(url: str, tmp: Path, workflow: str, workspace: Path, box_json: Path,
                die_at: str = "turn") -> dict:
    """Run ``workflow`` in a separate worker process on the test's private database; the
    process SIGKILLs itself while the Pi turn is running (after the prompt reached Pi), or
    with ``die_at="owner_wait"`` once the step waits for the owner."""
    import subprocess
    import sys

    Path(workspace).mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in _DROP_ENV and not k.startswith("TEMPER_DOCKER_")}
    env.update({"PYTHONPATH": str(WORKTREE), "TEMPER_DATABASE_URL": url,
                "TEMPER_EXECUTION_MODE": "inprocess", "TEMPER_LOG_DIR": str(tmp / "logs-child"),
                "TEMPER_PICK_UP_INTERRUPTED": "0", "TEMPER_TRIGGER_SCHEDULER": "0",
                "TEMPER_SLACK": "0", "TEMPER_PI_BOX_CONFIG": str(box_json)})
    args = {"db_url": url, "workflow": workflow, "workspace": str(workspace), "give_up_s": 30,
            "die_at": die_at}
    proc = subprocess.run([sys.executable, "-m", "tests.test_pi_agent.child", json.dumps(args)],
                          cwd=WORKTREE, env=env, capture_output=True, text=True, timeout=90)
    lines = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{")]
    started = next((x for x in lines if x.get("event") == "started"), {})
    killing = next((x for x in lines if x.get("event") == "killing"), {})
    out = {"returncode": proc.returncode, "execution_id": started.get("execution_id"),
           "killing": killing, "stderr_tail": proc.stderr[-1500:]}
    assert proc.returncode == -9 and out["execution_id"] and killing, out
    assert killing.get("net_attempts") == [], out
    return out


def reconcile_only() -> list[dict]:
    """The first half of a restart: mark the runs the dead worker left open as interrupted
    (so they are not running), without picking them up yet."""
    from temper_ai.observability.reconcile import reconcile_and_report

    return reconcile_and_report()


def restart_service(now=None, marked: list[dict] | None = None) -> dict:
    """What the isolated service does when it comes back: mark the runs the dead worker
    left open as interrupted, then pick them up through the Resume button's own path.
    ``marked`` is what an earlier :func:`reconcile_only` returned."""
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import pickup
    from temper_ai.shared.clock import utcnow

    since = utcnow()
    if marked is None:
        marked = reconcile_and_report()
    told: list[str] = []
    picks = pickup.pick_up_interrupted(
        marked, now=now, settle_s=0, since=since, resume=pickup._resume_through_the_button,
        tell=lambda text: told.append(text) or True, sleep=lambda _s: None)
    return {"marked": [m["execution_id"] for m in marked],
            "picked": [c.execution_id for c in picks.picked],
            "left": [c.execution_id for c in picks.left],
            "failed": [c.execution_id for c in picks.failed]}


class NetGuard:
    """Refuses every IPv4/IPv6 connection and records each attempt and name lookup."""

    def __init__(self):
        import socket

        self.attempts: list[str] = []
        self.lookups: list[str] = []
        self._socket = socket

    def install(self, monkeypatch=None) -> NetGuard:
        sock_mod = self._socket
        guard = self
        orig_connect, orig_connect_ex = sock_mod.socket.connect, sock_mod.socket.connect_ex
        orig_getaddrinfo = sock_mod.getaddrinfo

        def check(sock, address):
            if sock.family in (sock_mod.AF_INET, sock_mod.AF_INET6):
                guard.attempts.append(repr(address))
                raise OSError(f"Pi test network guard: no network connections ({address!r})")

        def connect(sock, address):
            check(sock, address)
            return orig_connect(sock, address)

        def connect_ex(sock, address):
            check(sock, address)
            return orig_connect_ex(sock, address)

        def getaddrinfo(host, *a, **kw):
            guard.lookups.append(str(host))
            return orig_getaddrinfo(host, *a, **kw)

        for obj, name, fn in ((sock_mod.socket, "connect", connect),
                              (sock_mod.socket, "connect_ex", connect_ex),
                              (sock_mod, "getaddrinfo", getaddrinfo)):
            if monkeypatch is not None:
                monkeypatch.setattr(obj, name, fn)
            else:
                setattr(obj, name, fn)
        return self


def _run_threads_left() -> list[threading.Thread]:
    return [t for t in threading.enumerate()
            if t.name.startswith("temper-run-") and t.is_alive()]


def stop_running(state) -> None:
    """Cancel what still runs, then wait for every run thread to end -- also one that has
    let go at a wait (no longer in ``state.running``) but is still seeing to its parked run:
    the test's database is closed right after, under any thread still using it."""
    end = time.monotonic() + 10
    while time.monotonic() < end:
        for entry in list(state.running.values()):
            cancel = getattr(entry, "set", None) or getattr(
                getattr(entry, "cancel_event", None), "set", None)
            if cancel:
                cancel()
        left = _run_threads_left()
        if not state.running and not left:
            return
        for thread in left:
            thread.join(timeout=0.05)
        time.sleep(0.01)


_ = threading  # used by tests through this module
