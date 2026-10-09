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

A team member's turn can also take messages while it runs (FLOW, owner bp-d3f3f571): the
request's ``inbox`` is polled during the turn and each new item goes to Pi once, as a steer
(delivered after the current tool calls, before the next model call). Its text must start
with :data:`TEAM_MESSAGE_PREFIX`, the one input the box's guard lets in mid-turn. Once the box
is gone, the session file says which handed messages reached the turn
(``TurnReport.handed_in``). ``on_tools`` gets the running turn's tool-call counts.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from temper_ai.llm.pi_stream import PiEventMapper, Redactor, record_outcome
from temper_ai.pi_agent.box import (
    PROBE_DIR,
    STATE_FILE,
    BoxConfig,
    BoxError,
    BoxSpec,
    WorkerBox,
    check_session,
)
from temper_ai.pi_agent.event_guard import TOKEN_GUARD, guarded
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.member_tree import (
    MemberLink,
    member_entry,
    member_file_sha256,
    read_member_text,
)
from temper_ai.pi_agent.rpc import RpcError

COMMAND_TIMEOUT = 60.0
UI_SILENT = ("notify", "setStatus", "setWidget", "setTitle", "set_editor_text")
#: Extension commands each allowed extension must register, by its folder in the box.
EXPECTED_COMMANDS = {"identity": "/ext/identity/", "temper-box-state": "/ext/temper-box/"}
#: How a running worker shows each allowed add-on loaded (R2 LR8, M2 binding). Pi is started
#: with ``--no-extensions`` and then exactly the pinned entries (box.py ``pi_args``), and Pi
#: 0.87.1 exits with status 1 when any ``--extension`` fails to load (dist/main.js, "Failed
#: to load extension"): so a worker that answers ``get_state`` with an add-on's entry on its
#: container's command line has loaded that add-on. Each add-on also proves it is at work:
#: ``tool`` -- the tool it brings is active (``tools_exact`` reads the active list back);
#: ``env_not_off`` -- its switch variable is not set to off. An add-on with no entry here is
#: refused (fail closed). A Pi other than 0.87.1 needs A4 rerun before this holds.
ADD_ON_PROOFS: dict[str, dict[str, str]] = {
    "pi-tldr": {"tool": "tldr"},
    "pi-image-trim": {"env_not_off": "PI_IMAGE_TRIM"},
}
_OFF = {"0", "off", "false", "no"}
#: How often a running team turn's inbox is polled (also right after each tool call ends).
INBOX_POLL_S = 2.0
#: At most this often, ``on_tools`` gets the running turn's tool-call counts.
TOOLS_EVERY_S = 5.0
_PREFIX_LINE = re.compile(r'^const TEAM_MESSAGE_PREFIX = "([^"\\\n]+)";$', re.M)


def _prefix_from_box_extension() -> str:
    """Temper's team-message prefix, read from its one definition in the box extension
    (``assets/temper-box/index.ts``), so the host and the box's input guard can't drift apart.
    An extension without exactly one such line stops the import: no turn could hand a message
    in that the guard would let through."""
    found = _PREFIX_LINE.findall((PROBE_DIR / "index.ts").read_text(encoding="utf-8"))
    if len(found) != 1:
        raise RuntimeError("temper-box/index.ts must define TEAM_MESSAGE_PREFIX exactly once, "
                           "on one line, as a plain double-quoted string")
    return found[0]


#: The text every team message handed into a running turn starts with (the box's input guard
#: lets nothing else in mid-turn). Defined once, in the box extension.
TEAM_MESSAGE_PREFIX = _prefix_from_box_extension()


class Handed(TypedDict):
    """One team message for a running turn: the ledger's ``seq`` and the text to hand in
    (made by :func:`render_handed`)."""

    seq: int
    text: str


def render_handed(message: dict) -> str:
    """The text of one team message handed into a running turn: the team-message prefix, then
    the message framed exactly as a turn's batch (:func:`render_batch`: its id, its real sender
    and its kind, all from the ledger), so the member can't mistake who sent it."""
    return (TEAM_MESSAGE_PREFIX + "A team message reached you during this turn.\n"
            + render_batch([message], team=True))


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
    #: Team messages for this member that arrived while its turn runs. Polled about every
    #: :data:`INBOX_POLL_S` and right after each tool call ends, while Pi's run is active
    #: (from its agent_start until it settles), on the turn's own thread; each new ``seq``
    #: goes to Pi once, as a steer. An item whose text lacks :data:`TEAM_MESSAGE_PREFIX` is
    #: never sent (reported unconfirmed). A failing inbox is noted, never fails the turn.
    #: None: nothing is handed in, as before.
    inbox: Callable[[], list[Handed]] | None = None
    #: Gets the running turn's tool calls counted by tool name, most first, at most every
    #: :data:`TOOLS_EVERY_S` and only when they changed. None: not counted.
    on_tools: Callable[[dict[str, int]], None] | None = None


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
    #: Only with an ``inbox``: which handed messages reached the turn, read from the session
    #: file once the box is confirmed gone: ``{"confirmed": [seq...], "unconfirmed":
    #: [seq...], "unexpected": n}``, plus ``"refused": [seq...]`` (Pi answered the steer
    #: with an error) and ``"problems": [words...]`` when there were any. Confirmed: its exact
    #: text is a user message this turn added to the file. Unconfirmed: everything else that
    #: was polled (not sent, refused by Pi or the box's guard, queued too late, or the box not
    #: confirmed gone). ``unexpected`` counts user messages of this turn that start with the
    #: team-message prefix but were not handed in by Temper.
    handed_in: dict | None = None


class _MidTurn:
    """A running team turn's live side (FLOW, owner bp-d3f3f571): team messages handed in as
    Pi steers, and the turn's tool-call counts. Every call happens on the turn runner's
    thread (the RPC sink runs inside ``rpc.next``)."""

    def __init__(self, inbox: Callable[[], list[Handed]] | None,
                 on_tools: Callable[[dict[str, int]], None] | None,
                 clock: Callable[[], float] = time.monotonic):
        self.inbox = inbox
        self.on_tools = on_tools
        self.clock = clock
        self.rpc: Any = None  # set when the prompt is sent
        # Pi's run is active: from its agent_start until its agent_settled (Pi takes a steer
        # then, and a steer it queued late still runs before it settles).
        self.running = False
        self.sent: dict[int, str] = {}  # seq -> text, in the order sent
        self.unsent: list[int] = []  # seqs never sent: no prefix, or the worker was gone
        self.steers: dict[str, int] = {}  # RPC request id -> seq
        self.refused: list[int] = []  # seqs whose steer Pi answered with an error
        self.problems: list[str] = []
        self.tool_ended = False
        self.polled_at: float | None = None
        self.tool_ids: set[str] = set()
        self.counts: Counter[str] = Counter()
        self.counts_new = False
        self.counts_at: float | None = None

    def observe(self, record: dict) -> bool:
        """See one Pi record of the turn. True for the answer to one of these steers: it is
        kept from the event mapper (a refused steer never fails the turn; it stays
        unconfirmed)."""
        kind = record.get("type")
        if kind == "agent_start":
            self.running = True
        elif kind == "agent_settled":
            self.running = False
        elif kind in ("tool_execution_start", "tool_execution_end"):
            call_id = record.get("toolCallId")
            if call_id:  # one call, however many of its events arrive
                counted = str(call_id) not in self.tool_ids
                self.tool_ids.add(str(call_id))
            else:
                counted = kind == "tool_execution_start"
            if counted:
                self.counts[str(record.get("toolName") or "tool")[:64]] += 1
                self.counts_new = True
            if kind == "tool_execution_end":
                self.tool_ended = True
        elif kind == "response" and record.get("command") == "steer" \
                and record.get("id") in self.steers:
            if not record.get("success"):
                self.refused.append(self.steers[record["id"]])
            return True
        return False

    def tick(self) -> None:
        """Called by the turn's wait loop after each record and at least every half second."""
        now = self.clock()
        if self.inbox is not None and self.rpc is not None and self.running and (
                self.tool_ended or self.polled_at is None
                or now - self.polled_at >= INBOX_POLL_S):
            self.tool_ended = False
            self.polled_at = now
            self._hand_in()
        if self.on_tools is not None and self.counts_new and (
                self.counts_at is None or now - self.counts_at >= TOOLS_EVERY_S):
            self.counts_new = False
            self.counts_at = now
            counts = dict(sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0])))
            try:
                self.on_tools(counts)
            except Exception as exc:  # noqa: BLE001 - a counting bug never fails the turn
                self._problem(f"on_tools failed ({type(exc).__name__})")

    def _hand_in(self) -> None:
        assert self.inbox is not None
        try:
            items = list(self.inbox() or [])
        except Exception as exc:  # noqa: BLE001 - the turn goes on; the messages stay pending
            self._problem(f"inbox failed ({type(exc).__name__})")
            return
        for item in items:
            seq = item.get("seq") if isinstance(item, dict) else None
            if not isinstance(seq, int) or isinstance(seq, bool):
                self._problem("a handed message had no seq: not sent")
                continue
            if seq in self.sent or seq in self.unsent:
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.startswith(TEAM_MESSAGE_PREFIX):
                self.unsent.append(seq)
                self._problem("a handed message lacked the team-message prefix: not sent")
                continue
            try:
                rid = self.rpc.send("steer", message=text)
            except RpcError:  # the worker is gone: the turn ends uncertain
                self.unsent.append(seq)
                raise
            self.sent[seq] = text
            self.steers[rid] = seq

    def _problem(self, words: str) -> None:
        if words not in self.problems:
            self.problems.append(words)

    def handed_in(self, turn_user_texts: list[str] | None) -> dict:
        """Each handed ``seq`` confirmed only when its exact text is a user message this turn
        wrote to the session file; ``turn_user_texts`` None (box not confirmed gone, file
        unreadable) confirms nothing."""
        found = set(turn_user_texts or ())
        confirmed = [s for s, text in self.sent.items() if text in found]
        unconfirmed = [s for s in [*self.sent, *self.unsent] if s not in confirmed]
        handed = set(self.sent.values())
        unexpected = sum(1 for text in turn_user_texts or ()
                         if text.startswith(TEAM_MESSAGE_PREFIX) and text not in handed)
        out: dict[str, Any] = {"confirmed": confirmed, "unconfirmed": unconfirmed,
                               "unexpected": unexpected}
        if self.refused:
            out["refused"] = list(self.refused)
        if self.problems:
            out["problems"] = list(self.problems)
        return out


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
    # Every event and live chunk of the turn leaves through the Pi lane's door (event_guard).
    recorder = guarded(req.recorder)
    redactor = Redactor(guard=TOKEN_GUARD)
    mapper = PiEventMapper(ChunkSink(recorder), execution_id=req.run_id,
                           agent_event_id=req.agent_event_id, agent_name=req.agent_name,
                           session_id=req.spec.session_id, node_path=req.node_path,
                           redactor=redactor)
    feeding = threading.Event()
    ui_refused: list[str] = []
    box: WorkerBox | None = None
    report = TurnReport(state="failed")
    rpc = None
    mid = _MidTurn(req.inbox, req.on_tools) \
        if req.inbox is not None or req.on_tools is not None else None

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
            if mid is not None and mid.observe(record):
                return
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
        # The box's name is on the turn before its container exists, so a takeover can always
        # find and stop it (R2 C1); a turn that is no longer this owner's starts nothing.
        if not ledger.record_box(req.turn["turn_id"], req.turn.get("epoch"),
                                 getattr(box, "name", None)):
            raise TurnFailure("turn_taken_over", "the turn was taken over by another attempt; "
                              "no worker was started")
        box.allow(0)
        rpc = box.start(sink)
        report.checks["sealed"] = box.inspected
        # The identity and login digests the start read back (M2-roles D3, SW-26).
        report.checks["pins_read_back"] = getattr(box, "pins_read_back", None)
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
        _ok(rpc.command("prompt", COMMAND_TIMEOUT, message="/temper-box-state"), "box state")
        # Files under the participant's folder are the member's to write: read no-follow
        # (SW-51). A link is refused; a notebook that is one has no digest, so the role check
        # fails rather than read through it.
        try:
            box_state = json.loads(read_member_text(pdir, f"state/{Path(STATE_FILE).name}"))
        except MemberLink as exc:
            raise TurnFailure("member_link_refused", str(exc)) from None
        notebook = member_file_sha256(pdir, f"memory/identities/{req.spec.role}/notebook.md")
        report.checks["role"] = _check_role(box_state, req.spec, notebook)
        report.checks["add_ons"] = _check_add_ons(box, req.spec, box_state)
        if ui_refused:
            raise TurnFailure("ui_request_refused",
                              f"Pi asked for owner input ({', '.join(ui_refused)}); refused")
        # 7. the prompt
        box.allow(cfg.model_calls_per_turn)
        if not ledger.mark_effect(req.turn["turn_id"], "intent", epoch=req.turn.get("epoch")):
            raise TurnFailure("turn_taken_over", "the turn was taken over by another attempt; "
                              "the prompt was not sent")
        report.prompt_sent = True
        feeding.set()
        if mid is not None:
            mid.rpc = rpc
        if cfg.fault == "kill_after_prompt":
            rid = rpc.send("prompt", message=req.text)
            box.kill()
        else:
            rid = rpc.send("prompt", message=req.text)
        _wait_settled(rpc, rid, mapper, cfg.turn_timeout_s, req.cancel_event, pdir, mid)
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
        if mid is not None and req.inbox is not None:
            report.handed_in = mid.handed_in(None)
        return report

    # Settled only from the session on disk, after the worker is gone (K7).
    try:
        after = check_session(pdir / "sessions", req.spec.session_id, must_exist=True)
    except BoxError as exc:
        after = {"settled": False, "error": exc.code}
    report.checks["session_after"] = after
    if mid is not None and req.inbox is not None:
        # The same file, once the box is confirmed gone: which handed messages reached Pi.
        gone = bool(report.worker.get("container_removed"))
        report.handed_in = mid.handed_in(
            _turn_user_texts(pdir, report.checks.get("session_before") or {}, after)
            if gone else None)
    outcome = mapper.finish()
    from temper_ai.pi_agent import token_scan
    from temper_ai.pi_agent.accounts import whole_result_refusal

    refusal = whole_result_refusal(outcome) if outcome.status == "completed" else None
    if refusal:
        # The account's refusal alone, from calls with no model output, is never an answer:
        # the turn fails with it as its error (ADR-M4-16).
        outcome.errors = [refusal]
        outcome.output = ""
        outcome.structured_output = None
        outcome.status = "failed"
    hits = token_scan.scan(outcome.output, f"{req.agent_name}'s answer").merge(
        token_scan.scan_obj(outcome.structured_output, f"{req.agent_name}'s answer")) \
        if outcome.status == "completed" else None
    if hits:
        # SW-52: an answer holding a login token never leaves the run; the turn fails naming
        # the rules that matched, never the text.
        outcome.errors = [f"the answer was withheld: {hits.words()}"]
        outcome.output = ""
        outcome.structured_output = None
        outcome.status = "failed"
    extra: list[str] = []
    if report.error:
        extra.append(report.error)
    if not after.get("settled"):
        extra.append("the Pi session on disk did not end with a settled answer")
    if not report.worker.get("container_removed"):
        extra.append("the worker container was not removed")
    if extra:
        outcome.errors = [*outcome.errors, *[e for e in extra if e not in outcome.errors]]
    # An error's words leave the run too (the turn's row, the run view): never a token.
    outcome.errors = [token_scan.withhold(str(e)) for e in outcome.errors]
    if outcome.last_error:
        outcome.last_error = token_scan.withhold(outcome.last_error)
    if report.error:
        report.error = token_scan.withhold(report.error)
        outcome.status = "failed"
    refused = report.worker.get("handoff_refused")
    if refused and outcome.status != "completed":
        # The host's plain refusal of the login hand-off (it names the account slot) leads.
        outcome.errors = [refused, *[e for e in outcome.errors if e != refused]]
    outcome_data_extra = {"pi_effective": report.effective,
                          "pi_turn_checks": _public_checks(report.checks)}
    report.outcome = outcome
    report.model_call_ids = mapper.call_ids
    report.output = outcome.output
    try:
        _record_end(recorder, mapper, outcome, duration, outcome_data_extra)
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
            if k in ("pin", "extension_commands", "role", "rewound", "add_ons",
                     "pins_read_back")}


def _rewind(rpc: Any, pdir: Path, session: dict) -> dict:
    """Move the session's active branch back to its settle point (same file, no model call)
    and check Pi reports exactly that leaf on a settled branch."""
    target = str(session["settle_point"])
    _ok(rpc.command("prompt", COMMAND_TIMEOUT, message=f"/temper-box-rewind {target}"), "rewind")
    try:  # no-follow (SW-51): a link there is refused like a missing answer
        got = json.loads(read_member_text(pdir, "state/box-rewind.json"))
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


def _check_add_ons(box: Any, spec: BoxSpec, state: dict) -> dict:
    """Read back that the worker loaded exactly the pinned extensions and that each listed
    add-on is at work, before any model call (R2 LR8; see :data:`ADD_ON_PROOFS`)."""
    launched = getattr(box, "launched", None)
    expected = box.expected_extensions() if hasattr(box, "expected_extensions") else None
    if not isinstance(launched, dict) or expected is None:
        raise TurnFailure("add_ons_not_verified",
                          "how the worker was started could not be read back")
    actual = list(launched.get("extensions") or [])
    if actual != list(expected):
        missing = [e for e in expected if e not in actual]
        extra = [e for e in actual if e not in expected]
        what = (["missing " + ", ".join(missing)] if missing else []) + \
               (["unexpected " + ", ".join(extra)] if extra else []) or ["out of order"]
        raise TurnFailure("add_ons_not_loaded",
                          "the worker was not started with exactly the pinned extensions: "
                          + "; ".join(what))
    env = launched.get("env") or {}
    active = set(state.get("active_tools") or [])
    proven: dict[str, str] = {}
    for name in spec.add_ons:
        proof = ADD_ON_PROOFS.get(name)
        if not proof:
            raise TurnFailure("add_on_unproven",
                              f"add-on '{name}' has no way to read back that it loaded")
        if "tool" in proof and proof["tool"] not in active:
            raise TurnFailure("add_on_not_loaded",
                              f"add-on '{name}': its tool {proof['tool']} is not active")
        var = proof.get("env_not_off")
        if var and str(env.get(var, "")).strip().lower() in _OFF and var in env:
            raise TurnFailure("add_on_not_loaded", f"add-on '{name}' is switched off ({var})")
        proven[name] = "loaded"
    return {"extensions": len(actual), "add_ons": proven}


def _turn_user_texts(pdir: Path, before: dict, after: dict) -> list[str] | None:
    """The user messages this turn added to the participant's session file (the entries past
    the ones it held before the turn), read without following links (SW-51). None when the
    file can't be read."""
    name = after.get("file")
    if not after.get("exists") or not name:
        return None
    try:
        lines = read_member_text(pdir, f"sessions/{name}").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):  # a link (MemberLink), gone, or not JSON lines
        return None
    start = before.get("entries", 0) if before.get("file") == name else 0
    texts: list[str] = []
    for entry in entries[start:]:
        message = entry.get("message") \
            if isinstance(entry, dict) and entry.get("type") == "message" else None
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.append("".join(str(part.get("text") or "") for part in content
                                 if isinstance(part, dict) and part.get("type") == "text"))
    return texts


def _wait_settled(rpc: Any, rid: str, mapper: PiEventMapper, timeout: float,
                  cancel: threading.Event | None, pdir: Path,
                  mid: _MidTurn | None = None) -> None:
    deadline = time.monotonic() + timeout
    answered = False
    while True:
        if cancel is not None and cancel.is_set():
            raise TurnFailure("cancelled", "the run was cancelled during the turn", True)
        # anything there, a link too (never followed, SW-51), means the worker blocked it
        if member_entry(pdir, "state/box-blocked.json") != "missing":
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
        if mid is not None and answered and not mapper.settled:
            mid.tick()
