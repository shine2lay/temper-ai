"""One Pi turn in a worker box: checks first, then exactly one prompt, then teardown.

Order (every check happens before the turn's first model call, R1 K6/K10):

1. the participant's session folder holds exactly its one session file (or none before the
   first turn), with the participant's id and working folder, and a settled last message;
2. the pinned start config still matches (Pi version, image, route, model, thinking, tools,
   extension digests, workflow, agent config);
3. the box starts sealed (checked by ``docker inspect``) with no credential allowance;
4. Pi reports the session id, session file, model and thinking it was started with -- these
   Pi-reported values are the turn's *effective settings*;
5. only the two allowed extensions registered commands;
6. the role is bound through pi-identity's public ``/identity`` command (first start) and the
   probe reports that identity, exactly the launched tools, and the participant's private
   notebook snapshot;
7. only then the credential allowance opens, the turn is marked "prompt sent" in the ledger
   and the batch goes to Pi as one prompt.

The turn is settled only from the session on disk after the box is gone. A worker that dies,
times out or leaves a tool call open after the prompt was sent makes the turn *uncertain*
(the owner decides: accept or retry); it is never re-run here.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from temper_ai.llm.pi_stream import PiEventMapper, Redactor, record_outcome
from temper_ai.pi_agent.box import (
    STATE_FILE,
    BoxConfig,
    BoxError,
    BoxSpec,
    WorkerBox,
    check_session,
    file_sha256,
)
from temper_ai.pi_agent.rpc import RpcError

COMMAND_TIMEOUT = 60.0
UI_SILENT = ("notify", "setStatus", "setWidget", "setTitle", "set_editor_text")
#: Extension commands each allowed extension must register, by its folder in the box.
EXPECTED_COMMANDS = {"identity": "/ext/identity/", "temper-box-state": "/ext/temper-box/"}


@dataclass
class TurnRequest:
    run_id: str
    agent_name: str
    node_path: str
    participant: dict
    turn: dict
    text: str
    spec: BoxSpec
    agent_event_id: str
    recorder: Any
    cancel_event: threading.Event | None = None
    first_start: bool = False
    #: The owner decided about the cut-off turn before this one (accept or retry): an
    #: unsettled session may be moved back to its last settled entry before the prompt.
    rewind_allowed: bool = False


@dataclass
class TurnReport:
    #: completed | failed (nothing uncertain: before the prompt, or Pi settled with an error)
    #: | uncertain (the prompt was sent and the turn did not settle cleanly)
    state: str
    output: str = ""
    error: str | None = None
    model_call_ids: list[str] = field(default_factory=list)
    effective: dict | None = None
    checks: dict = field(default_factory=dict)
    worker: dict = field(default_factory=dict)
    prompt_sent: bool = False
    outcome: Any = None


class ChunkSink:
    """The recorder the mapper writes to: events pass through; live chunks go out without
    the mapper's ``seq`` (Temper's chunk plumbing is unchanged by the Pi step)."""

    def __init__(self, inner: Any):
        self.inner = inner

    def record(self, *args: Any, **kwargs: Any) -> Any:
        return self.inner.record(*args, **kwargs)

    def broadcast_stream_chunk(self, agent_id: str, content: str, chunk_type: str = "content",
                               done: bool = False, call_id: str | None = None,
                               seq: int | None = None) -> None:
        try:
            self.inner.broadcast_stream_chunk(agent_id, content, chunk_type=chunk_type,
                                              done=done, call_id=call_id)
        except Exception:  # noqa: BLE001 - live chunks are best effort; events are durable
            pass


class TurnFailure(Exception):
    def __init__(self, code: str, message: str, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def run_turn(cfg: BoxConfig, req: TurnRequest, ledger: Any,
             box_factory: Callable[..., WorkerBox] = WorkerBox) -> TurnReport:
    """Run one turn. Never raises: every failure is a report the host turns into state."""
    started = time.monotonic()
    pdir = Path(req.spec.participant_dir)
    redactor = Redactor()
    mapper = PiEventMapper(ChunkSink(req.recorder), execution_id=req.run_id,
                           agent_event_id=req.agent_event_id, agent_name=req.agent_name,
                           session_id=req.spec.session_id, node_path=req.node_path,
                           redactor=redactor)
    feeding = threading.Event()
    ui_refused: list[str] = []
    box: WorkerBox | None = None
    report = TurnReport(state="failed")
    rpc = None

    def sink(record: dict) -> None:
        if record.get("type") == "extension_ui_request":
            method = str(record.get("method") or "")
            if method not in UI_SILENT and rpc is not None:
                reply: dict[str, Any] = {"type": "extension_ui_response", "id": record.get("id")}
                reply.update({"confirmed": False} if method == "confirm" else {"cancelled": True})
                try:
                    rpc.reply(reply)
                except RpcError:
                    pass
                ui_refused.append(method or "unknown")
            return
        if feeding.is_set():
            mapper.handle(record)

    try:
        # 1. the session folder (K6)
        session = check_session(pdir / "sessions", req.spec.session_id,
                                must_exist=not req.first_start)
        report.checks["session_before"] = session
        if not session["settled"] and not (req.rewind_allowed and session.get("settle_point")):
            raise TurnFailure("session_not_settled",
                              "the Pi session's last message is not settled: a turn was cut "
                              "off; the owner must decide before another turn runs")
        if session["exists"] and session["identity_entries"] < 1:
            raise TurnFailure("session_without_identity",
                              "the Pi session has no identity entry: refusing to resume it")
        # 2. the pin (K6)
        report.checks["pin"] = "matched"  # compared by the host before this call
        # 3. the box
        box = box_factory(cfg, req.spec, redactor)
        box.allow(0)
        rpc = box.start(sink)
        report.checks["sealed"] = box.inspected
        # 4. what Pi reports
        state = _ok(rpc.command("get_state", COMMAND_TIMEOUT), "get_state")
        model = state.get("model") or {}
        effective = {"provider": model.get("provider"), "model": model.get("id"),
                     "thinking": state.get("thinkingLevel"),
                     "session_id": state.get("sessionId")}
        report.effective = effective
        file_ok = str(state.get("sessionFile") or "").startswith("/w/sessions/") \
            or (req.first_start and not state.get("sessionFile"))
        mismatched = [k for k, want in (("session_id", req.spec.session_id),
                                        ("provider", req.spec.provider),
                                        ("model", req.spec.model),
                                        ("thinking", req.spec.thinking))
                      if effective[k] != want]
        if mismatched or not file_ok:
            raise TurnFailure("settings_not_effective",
                              "Pi did not start with the pinned settings: "
                              + ", ".join(mismatched or ["session file"]))
        # 5. extension commands
        commands = (_ok(rpc.command("get_commands", COMMAND_TIMEOUT), "get_commands")
                    .get("commands") or [])
        report.checks["extension_commands"] = _check_commands(
            commands, box.route.extension, bundled_extensions(Path(cfg.runtime_dir)),
            add_ons=req.spec.add_ons)
        # 5b. after the owner's decision about a cut-off turn: back to the last settled entry
        if not session["settled"]:
            report.checks["rewound"] = _rewind(rpc, pdir, session)
        # 6. role, tools, notebook
        if req.first_start:
            _ok(rpc.command("prompt", COMMAND_TIMEOUT, message=f"/identity {req.spec.role}"),
                "identity")
        state_file = pdir / "state" / Path(STATE_FILE).name
        _ok(rpc.command("prompt", COMMAND_TIMEOUT, message="/temper-box-state"), "box state")
        box_state = json.loads(state_file.read_text(encoding="utf-8"))
        notebook = file_sha256(pdir / "memory" / "identities" / req.spec.role / "notebook.md")
        report.checks["role"] = _check_role(box_state, req.spec, notebook)
        if ui_refused:
            raise TurnFailure("ui_request_refused",
                              f"Pi asked for owner input ({', '.join(ui_refused)}); refused")
        # 7. the prompt
        box.allow(cfg.model_calls_per_turn)
        ledger.mark_effect(req.turn["turn_id"], "intent")
        report.prompt_sent = True
        feeding.set()
        if cfg.fault == "kill_after_prompt":
            rid = rpc.send("prompt", message=req.text)
            box.kill()
        else:
            rid = rpc.send("prompt", message=req.text)
        _wait_settled(rpc, rid, mapper, cfg.turn_timeout_s, req.cancel_event, pdir)
        feeding.clear()
    except TurnFailure as exc:
        report.error = f"{exc.code}: {exc}"
        if exc.code == "box_blocked_prompt":
            # The probe stopped the prompt before any model call: a visible failure.
            report.prompt_sent = False
        report.state = "uncertain" if (exc.uncertain or report.prompt_sent) else "failed"
    except (BoxError, RpcError) as exc:
        code = getattr(exc, "code", None) or str(exc)
        report.error = f"{code}: {exc}" if isinstance(exc, BoxError) else \
            f"the worker stopped answering ({code})"
        report.state = "uncertain" if report.prompt_sent else "failed"
    except Exception as exc:  # noqa: BLE001 - a host bug must not look like success
        report.error = f"turn runner error: {type(exc).__name__}"
        report.state = "uncertain" if report.prompt_sent else "failed"
    finally:
        feeding.clear()
        if box is not None:
            report.worker = box.close()
            if ui_refused:
                report.worker["ui_requests_refused"] = list(ui_refused)

    duration = time.monotonic() - started
    if not report.prompt_sent:
        report.model_call_ids = []
        return report

    # Settled only from the session on disk, after the worker is gone (K7).
    try:
        after = check_session(pdir / "sessions", req.spec.session_id, must_exist=True)
    except BoxError as exc:
        after = {"settled": False, "error": exc.code}
    report.checks["session_after"] = after
    outcome = mapper.finish()
    extra: list[str] = []
    if report.error:
        extra.append(report.error)
    if not after.get("settled"):
        extra.append("the Pi session on disk did not end with a settled answer")
    if not report.worker.get("container_removed"):
        extra.append("the worker container was not removed")
    if extra:
        outcome.errors = [*outcome.errors, *[e for e in extra if e not in outcome.errors]]
        outcome.status = "failed"
    outcome_data_extra = {"pi_effective": report.effective,
                          "pi_turn_checks": _public_checks(report.checks)}
    report.outcome = outcome
    report.model_call_ids = mapper.call_ids
    report.output = outcome.output
    try:
        _record_end(req.recorder, mapper, outcome, duration, outcome_data_extra)
    except Exception:  # noqa: BLE001 - the ledger still holds the turn's state
        pass
    if outcome.status == "completed":
        report.state = "completed"
        report.error = None
    elif report.state != "uncertain" and mapper.settled and after.get("settled") \
            and not mapper.open_tool_calls:
        # Pi settled with an error (provider error, refused login, empty answer): visible failure.
        report.state = "failed"
        report.error = outcome.error
    else:
        report.state = "uncertain"
        report.error = outcome.error
    return report


def _record_end(recorder: Any, mapper: PiEventMapper, outcome: Any, duration: float,
                extra: dict) -> None:
    class _Extra:
        def record(self, event_type: Any, data: dict | None = None, **kw: Any) -> Any:
            return recorder.record(event_type, data={**(data or {}), **extra}, **kw)

    record_outcome(_Extra(), mapper, outcome, duration)  # type: ignore[arg-type]


def _public_checks(checks: dict) -> dict:
    return {k: v for k, v in checks.items()
            if k in ("pin", "extension_commands", "role", "rewound")}


def _rewind(rpc: Any, pdir: Path, session: dict) -> dict:
    """Move the session's active branch back to its settle point (same file, no model call)
    and check Pi reports exactly that leaf on a settled branch."""
    target = str(session["settle_point"])
    out = pdir / "state" / "box-rewind.json"
    _ok(rpc.command("prompt", COMMAND_TIMEOUT, message=f"/temper-box-rewind {target}"), "rewind")
    try:
        got = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = {}
    if got.get("cancelled") is not False or got.get("error") or got.get("leaf_id") != target \
            or got.get("branch_settled") is not True:
        raise TurnFailure("rewind_failed", "the Pi session could not be moved back to its last "
                                           "settled entry")
    return {"from_leaf": session.get("leaf_id"), "to": target}


def _ok(response: dict, what: str) -> dict:
    if not response.get("success"):
        raise TurnFailure("command_refused", f"Pi refused the {what} command")
    return response.get("data") or {}


def bundled_extensions(runtime_dir: Path) -> frozenset[str]:
    """The extensions shipped inside the pinned Pi runtime (dist/extensions/<name>); Pi lists
    their commands as inline. They are part of the pinned bundle, as L1 accepted them."""
    root = runtime_dir / "pi" / "dist" / "extensions"
    try:
        return frozenset(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return frozenset()


def _check_commands(commands: list[dict], auth_extension: str | None,
                    bundled: frozenset[str] = frozenset(),
                    add_ons: Sequence[str] = ()) -> dict:
    """Every extension command must come from an extension this turn loaded: identity, the
    box probe, the route's login extension, the member's add-ons (their pinned copies under
    /ext/addons/<name>/) or the pinned runtime's own bundle."""
    seen: dict[str, str] = {}
    from_add_ons: dict[str, list[str]] = {}
    stray = []
    builtin = []
    for row in commands:
        if row.get("source") != "extension":
            continue
        info = row.get("sourceInfo") or {}
        path = str(info.get("path") or "")
        name = str(row.get("name") or "")
        add_on = next((a for a in add_ons if path.startswith(f"/ext/addons/{a}/")), None)
        if path.startswith("/ext/identity/") or path.startswith("/ext/temper-box/") or \
                (auth_extension and path.startswith("/ext/auth/")):
            seen[name] = path
        elif add_on:
            from_add_ons.setdefault(add_on, []).append(name)
        elif (path.startswith("/pi-runtime/pi/") or info.get("source") == "inline") \
                and name in bundled:
            builtin.append(name)
        else:
            stray.append(f"{name[:40]} ({path[:60]})")
    missing = [n for n, where in EXPECTED_COMMANDS.items()
               if not str(seen.get(n, "")).startswith(where)]
    if stray or missing:
        raise TurnFailure("extensions_not_allowed",
                          "unexpected extension commands: " + ", ".join(sorted(stray)[:5]) if stray else
                          "an allowed extension did not load: " + ", ".join(missing))
    return {"allowed": sorted(seen), "pinned_runtime_builtin": sorted(builtin), "stray": 0,
            "add_ons": {name: sorted(cmds) for name, cmds in sorted(from_add_ons.items())}}


def _check_role(state: dict, spec: BoxSpec, notebook_sha: str | None) -> dict:
    tools = sorted(spec.tools)
    checks = {
        "mode_rpc": state.get("mode") == "rpc",
        "identity": state.get("identity_id") == spec.role,
        "identity_entry": any(e.get("id") == spec.role for e in state.get("identity_entries") or []),
        "tools_exact": state.get("active_tools") == tools,
        "notebook_snapshot": notebook_sha is not None and state.get("notebook_sha256") == notebook_sha,
        "session": state.get("session_id") == spec.session_id,
        "branch_settled": state.get("branch_settled") is True,
        "no_helper_env": state.get("helper_env") is False,
    }
    failed = sorted(k for k, ok in checks.items() if not ok)
    if failed:
        raise TurnFailure("role_not_verified",
                          "the worker is not the role it was started as: " + ", ".join(failed))
    return {**checks, "has_ui": state.get("has_ui")}


def _wait_settled(rpc: Any, rid: str, mapper: PiEventMapper, timeout: float,
                  cancel: threading.Event | None, pdir: Path) -> None:
    deadline = time.monotonic() + timeout
    blocked = pdir / "state" / "box-blocked.json"
    answered = False
    while True:
        if cancel is not None and cancel.is_set():
            raise TurnFailure("cancelled", "the run was cancelled during the turn", True)
        if blocked.exists():
            raise TurnFailure("box_blocked_prompt",
                              "the worker refused the prompt before any model call")
        if answered and mapper.settled:
            return
        step = min(deadline, time.monotonic() + 0.5)
        try:
            rpc.next(step)
        except RpcError as exc:
            if str(exc) == "protocol_deadline" and time.monotonic() < deadline:
                pass
            elif str(exc) == "protocol_deadline":
                raise TurnFailure("turn_timeout", "the turn did not settle in time", True) from None
            else:
                raise
        if not answered and rid in rpc.responses:
            answered = True
            if not rpc.responses[rid].get("success"):
                raise TurnFailure("prompt_refused", "Pi refused the prompt")
