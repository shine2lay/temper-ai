"""The Pi agent step: one ordinary Temper node hosting one Pi conversation (ADR-A6-1).

The node is created by the ordinary ``AgentNode`` like any agent (``type: pi``). It keeps a
conversation with one role in a sealed worker box, turn by turn, and owns the conversation's
state in its own ledger (:mod:`temper_ai.pi_agent.ledger`):

* the role is a *participant* attached by (run, node path, role); a later turn, a Resume or a
  restart re-attaches the same participant and reopens its one Pi session -- never a new one;
* a turn takes every message pending for the participant as one batch, framed by Temper so
  no message can pass for another sender (:mod:`temper_ai.pi_agent.inbox`), runs one worker
  box (:func:`temper_ai.pi_agent.turn.run_turn`), and is shown on the run page as its own
  agent (``agent.started`` .. ``agent.completed|failed``) with its model calls and tools;
* after a turn the owner is asked what next: a reply is the role's next message in the same
  session; ``done`` finishes the step. Every owner wait is written first as a ``pi_waits``
  row, then asked through ``ask_owner`` under that row's own id
  (:mod:`temper_ai.pi_agent.owner_waits`), named ``<node path>~ask-<wait id>`` and answered
  through Temper's ordinary approve route. In a Pi workflow an unanswered wait lets the
  worker go (the run parks, ``RunParked``); the answer carries the run on, this step runs
  again, finds the answer at the same wait id and goes on from its ledger -- a settled turn
  is never run again. Each wait has its own id (every turn, every recovery);
* a turn that was cut off (worker gone, timeout, a tool that never ended, the service
  stopped) is never re-run: it becomes ``uncertain`` -- once its worker box is confirmed
  stopped -- and the owner decides (accept / retry; a retry gives the same messages again,
  same ids, never new copies);
* a turn that failed visibly (the worker could not be started or checked, the provider
  refused, the login was not handed over) fails the step -- red, never green. A Resume of
  the run then asks the owner whether to retry that turn or stop;
* the step raises only ``RunParked`` (its run let the worker go at an owner wait; AgentNode
  passes it up) and ``CancellationError`` (the run was stopped while the step held its
  worker at a wait, which ends the conversation first; AgentNode's retry then stops at
  once). Otherwise it never raises and never returns empty output, so AgentNode never
  re-runs it blind.

A Pi step may be a workflow's first node (C7): an owner wait saves where the run is under
the wait's own id (a ``step_parked`` checkpoint), so the answer carries the run on from
there even when nothing ran before it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from temper_ai.agent.base import AgentABC
from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.box import (
    PROBE_DIR,
    WORKDIR,
    BoxConfig,
    BoxError,
    BoxSpec,
    session_started,
    stop_leftover_box,
    tree_sha256,
)
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.ledger import (
    Ledger,
    LedgerConflict,
    LedgerLayoutError,
    TakeoverRefused,
)
from temper_ai.pi_agent.member import (
    DEFAULT_TOOLS,
    add_on_names,
    config_problems,
    launched_tools,
    settings,
    usage_limit,
)
from temper_ai.pi_agent.member_tree import (
    MemberLink,
    SnapshotRefused,
    member_entry,
    replace_snapshot,
    write_member_file,
)
from temper_ai.pi_agent.owner_waits import WaitDecided, ask_owner_for_wait, wait_row
from temper_ai.pi_agent.search_tools import search_tool_problems
from temper_ai.shared.types import AgentResult, ExecutionContext, Status
from temper_ai.stage.exceptions import CancellationError, RunParked
from temper_ai.stage.gate import REJECTED, WAITING

logger = logging.getLogger(__name__)

AGENT_TYPE = "pi"
FINISH_WORDS = ("", "done", "finish", "finished", "stop", "end")
DEFAULT_QUESTION = ("{role} answered (turn {turn_no}). Reply with the next message for "
                    "{role}, or 'done' to finish this step.")


def _jinja(template: str, values: dict) -> str:
    from temper_ai.llm.prompt_renderer import _filter_safe_values

    return Environment(loader=BaseLoader()).from_string(template).render(
        **_filter_safe_values(values or {}))


LOST_TURN = ("this attempt's turn was taken over by a newer attempt; it changed nothing "
             "after that")


class PiHost(AgentABC):
    """The ``pi`` agent type.

    Config keys: ``role`` (required; a role folder under the box config's identities),
    ``provider``, ``model``, ``thinking``, ``tools`` (default ``[read]``), ``message`` (the
    first message, a template over the node's input), ``workspace_files`` (name -> template,
    written once into the worker's working folder), ``ask_owner`` (the question after each
    turn). ``poll_seconds`` is accepted and ignored (waits are asked through ``ask_owner``).
    """

    uses_llm_settings = False
    #: A step whose conversation another attempt ended stops cancelled (``_settled_meanwhile``):
    #: its stage and run end cancelled with that reason, not "completed" (M3 E18).
    cancelled_ends_stage = True

    #: Test seam: ``fn(cfg, request, ledger) -> TurnReport``; default runs the worker box.
    turn_runner: Any = None
    #: Test seam: ``fn(box_name) -> result``; default confirms a cut-off turn's worker box is
    #: stopped and removed, with Docker (:func:`temper_ai.pi_agent.box.stop_leftover_box`).
    stop_box: Any = None

    def validate_config(self) -> list[str]:
        """Every problem with the config (role, model, Temper tool names, add-ons), all at once."""
        return [f"pi: {problem}" for problem in config_problems(self.config)]

    @property
    def model_settings(self) -> dict:
        """provider, model and thinking, the member defaults filled in (claude-opus-5-5 / max)."""
        return settings(self.config)

    # --- entry ------------------------------------------------------------------------

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        started = time.monotonic()
        try:
            result = self._run(input_data, context, started)
        except (RunParked, CancellationError):
            # The run let its worker go at an owner wait, or was stopped while the step held
            # its worker at one (the conversation has ended): neither is the step failing.
            raise
        except Exception as exc:  # noqa: BLE001 - a raising agent is re-run blind by AgentNode
            logger.exception("Pi step %s failed", self.name)
            text = f"Pi step failed: {type(exc).__name__}"
            result = AgentResult(status=Status.FAILED, output=text, error=text,
                                 duration_seconds=time.monotonic() - started)
        if not result.output:
            result.output = result.error or "Pi step ended without output"
        return result

    # --- the conversation ---------------------------------------------------------------

    def _run(self, input_data: dict, context: ExecutionContext, started: float) -> AgentResult:
        from temper_ai.database import get_database

        self.ctx = context
        self.run_id = context.run_id
        self.host_path = context.node_path or self.name
        self.attempt_id = context.graph_event_id or f"attempt-{uuid.uuid4().hex}"
        self.turns_run = 0
        self.model_calls = 0
        self.last_output = ""
        cfg = self.config
        problems = self.validate_config()
        if problems:
            return self._fail("; ".join(problems), started)
        if context.event_recorder is None:
            return self._fail("a Pi step needs the run's event recorder", started)
        try:
            box = BoxConfig.load()
        except BoxError as exc:
            return self._fail(str(exc), started)
        provider = self.model_settings["provider"]
        if provider not in box.routes:
            return self._fail(f"no worker route for provider {provider!r}", started)
        if not (Path(box.identities_dir) / cfg["role"]).is_dir():
            return self._fail(f"role {cfg['role']!r} is not defined", started)
        unpinned = [name for name in add_on_names(cfg) if name not in box.add_ons]
        if unpinned:
            return self._fail("no pinned copy of add-on(s) " + ", ".join(unpinned)
                              + " in the worker box config", started)
        missing = search_tool_problems(launched_tools(cfg), box)
        if missing:
            return self._fail("; ".join(missing), started)
        self.box = box
        self.ledger = Ledger(get_database().engine)
        try:
            self.ledger.ensure()
        except LedgerLayoutError as exc:  # a layout this build doesn't know (SW-13)
            return self._fail(f"Pi refused this database: {exc}", started)
        pin = self._pin(box)
        root = Path(box.state_root) / self.run_id / _slug(self.host_path)
        part, created = self.ledger.attach_participant(
            self.run_id, self.host_path, cfg["role"], role=cfg["role"], session_root=str(root),
            pin=pin, attempt_id=self.attempt_id)
        pdir = Path(part["session_dir"]).parent
        if not created and part["pin"] != pin:
            changed = changed_keys(pin, part["pin"])
            return self._fail("the Pi step's settings changed since its conversation started ("
                              + ", ".join(changed) + "); refusing to reopen it", started)
        try:
            self._prepare_participant(pdir, input_data, part)
        except SnapshotRefused as exc:
            return self._fail(f"the Pi step's role snapshot was refused: {exc}", started)
        self.participant_id = part["participant_id"]
        self.pdir = pdir
        message = cfg.get("message") or "{{ task }}"
        try:
            self.ledger.post(self.run_id, self.host_path, cfg["role"],
                             _jinja(message, input_data) or "(no message)", sender="owner",
                             sender_kind="owner", kind="task",
                             dedupe_key=f"{self.run_id}:{self.host_path}:seed:0")
        except LedgerConflict:
            return self._fail("the Pi step's first message changed since its conversation "
                              "started; refusing to reopen it with a different one", started)

        # An attempt that died mid-turn: the turn is never re-run blind; the owner decides --
        # and only once its worker box is confirmed stopped (R2 C1).
        try:
            taken = self.ledger.take_over(self.run_id, self.host_path, self.attempt_id,
                                          type(self).stop_box or stop_leftover_box,
                                          why="the service stopped during the turn")
        except TakeoverRefused as exc:
            return self._fail(str(exc), started)
        for turn, _wait in taken:
            self._close_turn_event(turn, "the turn was cut off: the service stopped during it")
        # A Resume after a failed turn: the owner decides (retry / stop), never a re-run.
        self.ledger.open_recovery_for_failed(self.run_id, self.host_path, self.attempt_id)

        while True:
            cancel = context.cancel_event
            if cancel is not None and cancel.is_set():
                # Nothing queued is dropped: it is recorded undelivered (R2 B12).
                self._end_conversation()
                return self._result(Status.CANCELLED, "Pi step cancelled", started,
                                    error="cancelled")
            # The open waits are asked one at a time, oldest first. In a Pi workflow an
            # unanswered one lets the worker go right here (RunParked goes up); its answer
            # carries the run on, and this step runs again and finds it at the same wait id.
            waiting = self.ledger.open_waits(self.run_id, self.host_path)
            if waiting:
                ends = self._settle(waiting[0])
                if ends is not None:
                    status, text, error = ends
                    return self._result(status, text, started, error=error)
                continue
            p = self.ledger.participant(self.participant_id) or {}
            if p.get("state") == "retired":
                return self._result(Status.COMPLETED, None, started)
            if p.get("state") == "failed":
                return self._result(Status.FAILED, self._last_error(), started,
                                    error=self._last_error())
            if p.get("state") == "ended":
                text = "the Pi conversation ended when its run was cancelled"
                return self._result(Status.FAILED, text, started, error=text)
            claimed = self.ledger.claim_turn(self.run_id, self.host_path,
                                             attempt_id=self.attempt_id)
            if claimed is None:
                # Nothing for the role (an accepted turn stands, say): the owner says what
                # comes next, asked about the last turn.
                self.ledger.open_wait(self.run_id, self.host_path, "owner",
                                      self._ask(p, self._last_turn()), self.attempt_id)
                continue
            turn, batch = claimed
            failure = self._do_turn(p, turn, batch)
            if failure:
                return self._result(Status.FAILED, failure, started, error=failure)

    # --- one turn ---------------------------------------------------------------------

    def _do_turn(self, participant: dict, turn: dict, batch: list[dict]) -> str | None:
        """Run one turn. Returns an error text when the step must fail."""
        from temper_ai.pi_agent.turn import TurnRequest, run_turn

        cfg = self.config
        model = self.model_settings
        rec = self.ctx.event_recorder
        agent_event_id = rec.record(
            EventType.AGENT_STARTED, parent_id=self.ctx.parent_event_id,
            execution_id=self.run_id, status="running", data={
                "agent_name": self.name, "node_path": self.host_path, "type": AGENT_TYPE,
                "executed_by": "pi", "role": cfg["role"], "provider": model["provider"],
                "model": model["model"], "thinking": model["thinking"],
                "input_data": {"messages": len(batch)},
                "pi_turn": {"turn_id": turn["turn_id"], "turn_no": turn["turn_no"],
                            "participant_id": participant["participant_id"],
                            "session_id": participant["session_id"],
                            "attempt_id": self.attempt_id},
                "agent_config": self._public_config(),
            })
        self.ledger.set_turn_agent_event(turn["turn_id"], agent_event_id, epoch=turn["epoch"])
        spec = BoxSpec(participant_dir=self.pdir, session_id=participant["session_id"],
                       role=cfg["role"], provider=model["provider"], model=model["model"],
                       thinking=model["thinking"], tools=launched_tools(cfg),
                       labels={"run": self.run_id[:36], "turn": turn["turn_id"][:16]},
                       add_ons=add_on_names(cfg))
        req = TurnRequest(run_id=self.run_id, agent_name=self.name, node_path=self.host_path,
                          participant=participant, turn=turn, text=render_batch(batch),
                          spec=spec, agent_event_id=agent_event_id, recorder=rec,
                          cancel_event=self.ctx.cancel_event,
                          # The role is bound once, in the session's first start; later
                          # starts reopen that session and check the binding is still there.
                          first_start=not session_started(self.pdir),
                          rewind_allowed=self._owner_decided_before(turn))
        runner = type(self).turn_runner or run_turn
        report = runner(self.box, req, self.ledger)
        self.turns_run += 1
        self.model_calls += len(report.model_call_ids)
        worker = {**(report.worker or {}), "effective": report.effective,
                  "checks": _jsonable(report.checks)}
        if report.outcome is None:
            # Nothing reached the model: the turn's agent is closed here, red.
            rec.record(EventType.AGENT_FAILED, parent_id=agent_event_id,
                       execution_id=self.run_id, status="failed", data={
                           "agent_name": self.name, "error": report.error,
                           "output": "", "executed_by": "pi", "pi_effective": report.effective,
                           "tokens": 0, "cost_usd": 0.0})
        if report.state == "completed":
            self.last_output = report.output
            # The owner's "what next" wait is written with the turn's end, in one go: the
            # loop asks it next.
            res = self.ledger.finish_turn(turn["turn_id"], epoch=turn["epoch"],
                                          output=report.output,
                                          model_call_ids=report.model_call_ids, worker=worker,
                                          ask_owner=self._ask(participant, turn),
                                          attempt_id=self.attempt_id)
            return LOST_TURN if res is None else None
        limit = usage_limit(report.error) if report.state != "uncertain" else None
        if report.state == "uncertain" or limit:
            # Cut off: the owner decides (never a blind re-run). A usage or rate limit pauses
            # the step the same way (retry once it resets), naming the limit; never a quiet
            # switch to another model or account.
            # Its recovery wait is written with the hold; the loop asks it next.
            wait = self.ledger.hold_turn(turn["turn_id"], limit or report.error or "cut off",
                                         report.model_call_ids, worker, self.attempt_id,
                                         epoch=turn["epoch"])
            return LOST_TURN if wait is None else None
        error = f"{cfg['role']} turn {turn['turn_no']} failed: {report.error}"
        if not self.ledger.fail_turn(turn["turn_id"], error, report.model_call_ids, worker,
                                     epoch=turn["epoch"]):
            return LOST_TURN
        return error

    def _owner_decided_before(self, turn: dict) -> bool:
        return owner_decided_before(self.ledger, turn)

    def _close_turn_event(self, turn: dict, why: str) -> None:
        rec = self.ctx.event_recorder
        eid = turn.get("agent_event_id")
        if eid and rec.event_status(eid) == "running":
            rec.record(EventType.AGENT_FAILED, parent_id=eid, execution_id=self.run_id,
                       status="failed", data={"agent_name": self.name, "error": why,
                                              "output": "", "executed_by": "pi",
                                              "tokens": 0, "cost_usd": 0.0})
            rec.update_event(eid, status="failed")

    # --- waits ------------------------------------------------------------------------

    def _ask(self, participant: dict, turn: dict | None) -> dict:
        question = self.config.get("ask_owner") or DEFAULT_QUESTION
        return {"question": question.format(role=self.config["role"],
                                            turn_no=(turn or {}).get("turn_no", 0)),
                "options": ["done"]}

    def _settle(self, wait: dict) -> tuple[Status, str, str] | None:
        """Ask the owner at one open wait and apply the answer, once.

        Returns how the step ends -- (status, text, error) -- when the answer ends it, None
        when it goes on. ``RunParked`` goes up untouched: the run lets its worker go here and
        the answer carries it on (this step runs again and gets the answer at the same id).
        ``CancellationError`` -- the run was stopped while the step held its worker here, as a
        wait does when the run cannot save where it is -- goes up too, once the conversation
        has ended.
        """
        subject = wait["subject"] or {}
        try:
            answer = ask_owner_for_wait(
                self.ctx, self.ledger, wait["wait_id"],
                question=ask_text(subject, "The Pi step is waiting for you."),
                header=str(wait["kind"]),
                options=[str(o) for o in subject.get("options") or []])
        except WaitDecided as settled:
            return self._settled_meanwhile(wait, settled.state, settled.decision)
        except CancellationError:
            # Not when a later attempt of the run took the wait over: the conversation is
            # that attempt's now.
            cancel = self.ctx.cancel_event
            if cancel is not None and cancel.is_set():
                self._end_conversation()
            raise
        text = _reply_text(answer.response)
        decision: dict[str, Any] = {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        deliveries: list[tuple[str, str]] = []
        recovery = None
        reask = None
        states: list[tuple[str, str]] = []
        if wait["kind"] == "recovery":
            word = recovery_word(owner_reply(answer.response)[0],
                                 subject.get("options") or ["accept", "retry"])
            if word is None:
                # No choice named: nothing is decided by default; the owner is asked again.
                decision["recovery"] = INVALID
                reask = recovery_asked_again(subject)
            else:
                decision["recovery"] = word
                # A retry gives the turn's own messages again -- same ids, marked as given
                # again -- never new copies (R2 B1); what the turn sent is never delivered (B4).
                recovery = (word, subject["turn_id"])
        elif text.lower() in FINISH_WORDS:
            decision["owner"] = "finish"
            states = [(subject.get("participant_id") or self.participant_id, "retired")]
        else:
            decision["owner"] = "message"
            deliveries = [(self.config["role"], text)]
        if self.ledger.decide_wait(wait["wait_id"], decision, self.attempt_id,
                                   deliveries=deliveries, recovery=recovery,
                                   participant_states=states, reask=reask):
            return self._settled(wait, decision)
        # Another attempt settled it first (compare-and-set): go by what it recorded.
        row = wait_row(self.ledger, wait["wait_id"]) or {}
        return self._settled_meanwhile(wait, str(row.get("state") or "cancelled"),
                                       row.get("decision"))

    def _settled(self, wait: dict, decision: Any) -> tuple[Status, str, str] | None:
        """What a decided wait means for the step: a stop at a recovery wait fails it, with
        neutral text that never names who answered (M3 E16); anything else was done by the
        decision itself (the ledger's same transaction), so the step goes on."""
        if not (isinstance(decision, dict) and decision.get("recovery") == "stop"):
            return None
        subject = wait["subject"] or {}
        did = "failed" if "accept" not in (subject.get("options") or []) else "did not finish"
        text = f"{subject.get('role')} turn {subject.get('turn_no')} {did} and the step was stopped"
        return Status.FAILED, text, text

    def _settled_meanwhile(self, wait: dict, state: str,
                           decision: Any) -> tuple[Status, str, str] | None:
        """The wait was settled elsewhere (another attempt of the run): go on from its row.
        Decided: its decision was applied with it, so the step goes on from it -- the same way
        as when this attempt decided it. Cancelled: the conversation has ended (its run was
        stopped), so the step stops; neither fails the step."""
        if state == "decided":
            return self._settled(wait, decision)
        text = ("the Pi conversation ended while the step waited for the owner (its run was "
                "cancelled)")
        return Status.CANCELLED, text, "cancelled"

    def _end_conversation(self) -> None:
        """The run was stopped: the conversation ends (unsettled turns cancelled, everything
        queued recorded undelivered, R2 B12; open waits cancelled), and every event of each
        cancelled wait still waiting is closed -- found by the wait's name: ``ask_owner`` may
        have asked it more than once."""
        ended = self.ledger.end_team(self.run_id, self.host_path, "run_cancelled",
                                     self.attempt_id)
        rec = self.ctx.event_recorder
        for w in ended["cancelled_waits"]:
            for ev in rec.gate_events(w["gate_name"]) or []:
                if ev.get("status") == WAITING:
                    rec.decide(str(ev["id"]), expect=(WAITING,), status=REJECTED,
                               data={"gate_status": REJECTED, "pi_cancelled": True})

    # --- helpers ----------------------------------------------------------------------

    def _last_turn(self) -> dict | None:
        turns = self.ledger.turns_of(self.participant_id)
        return max(turns, key=lambda t: t["turn_no"]) if turns else None

    def _public_config(self) -> dict:
        cfg = self.config
        return {"type": AGENT_TYPE, "name": self.name, "role": cfg.get("role"),
                **self.model_settings,
                "tools": list(cfg.get("tools") or DEFAULT_TOOLS),
                "add_ons": add_on_names(cfg)}

    def _pin(self, box: BoxConfig) -> dict:
        return pin_for(box, self.config, workflow=self.ctx.workflow_name)

    def _prepare_participant(self, pdir: Path, input_data: dict, part: dict) -> None:
        prepare_participant(self.box, pdir, self.config, input_data, ledger=self.ledger,
                            participant=part)

    def _last_error(self) -> str:
        turns = self.ledger.turns_of(self.participant_id)
        failed = [t for t in turns if t["state"] == "failed"]
        return (failed[-1]["error"] if failed else None) or "the Pi step failed"

    def _fail(self, text: str, started: float) -> AgentResult:
        return AgentResult(status=Status.FAILED, output=text, error=text,
                           duration_seconds=time.monotonic() - started)

    def _result(self, status: Status, text: str | None, started: float,
                error: str | None = None) -> AgentResult:
        snap = self.ledger.snapshot(self.run_id)
        mine = [t for t in snap["turns"] if t["participant_id"] == self.participant_id]
        summary = {
            "role": self.config["role"], "participant_id": self.participant_id,
            "turns": [{"turn_no": t["turn_no"], "state": t["state"],
                       "model_calls": len(t["model_call_ids"] or [])} for t in mine],
            "turns_this_attempt": self.turns_run,
            "model_calls_this_attempt": self.model_calls,
            "waits": [{"kind": w["kind"], "state": w["state"]} for w in snap["waits"]
                      if w["host_path"] == self.host_path],
        }
        completed = [t for t in mine if t["state"] == "completed" and t["output"]]
        output = text or (completed[-1]["output"] if completed else "") or json.dumps(summary)
        return AgentResult(status=status, output=output, structured_output=summary,
                           error=error, llm_calls=self.model_calls,
                           duration_seconds=time.monotonic() - started,
                           metadata={"pi": summary})


def pin_for(box: BoxConfig, cfg: dict, *, workflow: str | None,
            tools: list[str] | None = None, team: str | None = None) -> dict:
    """What a Pi conversation was started with: a reopen with anything else is refused.
    ``tools``: the Pi tools the box launches with (default: the config's); ``team``: the
    team's settings digest, for a team member (R2 C3)."""
    model = settings(cfg)
    route = box.routes[model["provider"]]
    extensions = {"identity": tree_sha256(Path(box.identity_extension)),
                  "temper-box": tree_sha256(PROBE_DIR)}
    if route.extension:
        extensions["auth"] = tree_sha256(Path(route.extension))
    config_sha = config_digest(cfg)
    pin = {"pi_version": box.pi_version, "image": box.image, **model,
           "tools": sorted(tools) if tools is not None else launched_tools(cfg),
           "extensions": extensions,
           "add_ons": {name: box.add_ons[name].sha256 for name in add_on_names(cfg)},
           "route_host": route.host, "workflow": workflow,
           "agent_config_sha256": config_sha, "cwd": WORKDIR}
    if team is not None:
        pin["team"] = team
    return pin


def config_digest(cfg: dict) -> str:
    """The step's settings as one digest, the same in every worker process: a reopen in a new
    worker (an answered wait carries the run on in one) must find what the first one pinned.

    Left out: ``poll_seconds`` (ignored) and keys starting with ``_``, which are not settings
    (a node's ``_KNOWN_FIELDS`` reaches every resolved agent config through the loader's
    merge). A set is hashed sorted: its order follows string hashing, salted per process."""
    def _plain(value: Any) -> Any:
        if isinstance(value, (set, frozenset)):
            return sorted(str(v) for v in value)
        return str(value)

    settings_only = {k: v for k, v in cfg.items()
                     if k != "poll_seconds" and not str(k).startswith("_")}
    return hashlib.sha256(json.dumps(settings_only, sort_keys=True,
                                     default=_plain).encode()).hexdigest()


def prepare_participant(box: BoxConfig, pdir: Path, cfg: dict, values: dict, *,
                        ledger: Ledger, participant: dict) -> str | None:
    """Before the participant's first turn: its private snapshot of the role folder and its
    working files (M4 ADR-M4-08, SW-25). Returns the snapshot's digest, or None when there was
    nothing to do.

    Done on every attach until the snapshot's digest is on the participant row, and recorded
    last: a crash before that leaves nothing the next attempt reuses -- a temporary copy, or a
    snapshot without its digest, is removed and the snapshot taken afresh (no turn runs before
    the digest is recorded). Once recorded the folder is the member's and is never touched
    again; so is the folder of a participant that already had turns (a row from before the
    digest). The snapshot follows no link (:func:`member_tree.take_snapshot`). Raises
    :class:`SnapshotRefused` with the plain problem."""
    if participant.get("snapshot_sha256") or ledger.turns_of(participant["participant_id"]):
        return None
    role = cfg["role"]
    src = Path(box.identities_dir) / role
    dst = pdir / "memory" / "identities" / role
    digest = replace_snapshot(src, dst, what=f"role folder {role!r}")
    try:
        kind = member_entry(pdir, "workspace")
        if kind == "missing":
            (pdir / "workspace").mkdir()
        elif kind != "dir":
            raise SnapshotRefused(f"the participant's working folder {pdir / 'workspace'} is "
                                  "not a folder (a link or a file); Temper won't write into it")
        for name, template in (cfg.get("workspace_files") or {}).items():
            write_member_file(pdir, f"workspace/{name}", _jinja(template, values))
    except MemberLink as exc:
        raise SnapshotRefused(str(exc)) from None
    kept = ledger.record_snapshot(participant["participant_id"], digest)
    if kept != digest:
        raise SnapshotRefused(f"the role folder {role!r} changed while another attempt copied it "
                              "too; the snapshot on record is not this copy. Start the step "
                              "again once nothing is writing to the role folder")
    return digest


def changed_keys(pin: dict, stored: dict) -> list[str]:
    return sorted(k for k in set(pin) | set(stored) if pin.get(k) != stored.get(k))


def owner_decided_before(ledger: Ledger, turn: dict) -> bool:
    """Whether the turn before this one was cut off or failed and the owner decided about
    it (accept or retry): only then may an unsettled session be moved back."""
    earlier = [t for t in ledger.turns_of(turn["participant_id"])
               if t["turn_no"] < turn["turn_no"]]
    return bool(earlier) and max(earlier, key=lambda t: t["turn_no"])["state"] in (
        "accepted", "superseded")


INVALID = "invalid"
"""A recovery wait's decision when the answer named none of its choices: nothing was done and
the owner is asked again, at a new wait for the same turn."""


def recovery_word(text: str, options: list[str]) -> str | None:
    """The owner's choice at a recovery wait: the answer's first word when it is one of the
    wait's options, or ``stop`` (the owner may always stop). A cut-off turn is answered
    ``accept``, ``retry`` or ``stop``; a failed turn ``retry`` or ``stop`` (R2 N1). Anything
    else -- an empty answer, another word, ``accept`` at a failed turn -- is None: it never
    accepts or stops by default, and the owner is asked again (M3 F1)."""
    m = re.match(r"\s*([A-Za-z]+)", text or "")
    word = m.group(1).lower() if m else ""
    if word == "stop" or (word in ("accept", "retry") and word in options):
        return word
    return None


def ask_text(subject: dict, default: str = "") -> str:
    """The text a chat surface (Slack, Telegram, the run page) shows for a wait: its question,
    then its reply hint when it has one (M3 E22). A wait keeps the two apart -- the Team page
    shows the question with the choices instead -- and this joins them back into the same
    text as before they were split. A wait opened before the split has the hint inside its
    question and no ``reply_hint``: it reads as it always did."""
    question = str(subject.get("question") or default)
    hint = str(subject.get("reply_hint") or "")
    return f"{question} {hint}" if hint else question


def recovery_asked_again(subject: dict) -> dict:
    """A recovery wait's subject when the owner's answer named none of its choices: the same
    turn and choices, asked again with the reason first (and the same reply hint)."""
    choices = [str(o) for o in subject.get("options") or []]
    if "stop" not in choices:
        choices.append("stop")
    first = str(subject.get("first_question") or subject.get("question") or "")
    return {**subject, "first_question": first,
            "asked_again": int(subject.get("asked_again") or 0) + 1,
            "question": (f"That answer was not one of: {', '.join(choices)}. Nothing was "
                         f"decided. {first}").strip()}


_CHOICE = re.compile(r"\s*([A-Za-z_-]+)\s*[:,.;\-]*\s*(.*)\Z", re.S)


def split_choice(text: str) -> tuple[str, str]:
    """(first word, the rest) of a typed answer: "guide: be brief" is ("guide", "be brief").
    The word is lower case with ``-`` read as ``_``; no leading word gives ("", the text)."""
    m = _CHOICE.match(text or "")
    if not m:
        return "", str(text or "").strip()
    return m.group(1).lower().replace("-", "_"), m.group(2).strip()


def owner_reply(response: Any) -> tuple[str, str]:
    """What the owner said at a wait, as (choice, words) (M3 E17). A picked option -- how the
    run page sends one (``answers[{selected}]``) -- is the choice, and the typed response plus
    any written text are the words (guide text, nudge words, a reply). With no pick, the typed
    response's first word is the choice and the rest are the words (else the first answered
    question's written text, read the same way). Never the rendered ``Q: ... A: ...`` text,
    whose first word is ``Q:`` (M3 F1)."""
    if isinstance(response, str):
        return split_choice(response)
    if not isinstance(response, dict):
        return "", ""
    typed = str(response.get("response") or "").strip()
    for answer in response.get("answers") or []:
        if not isinstance(answer, dict):
            continue
        picked = next((str(s).strip() for s in answer.get("selected") or []
                       if str(s).strip()), "")
        custom = str(answer.get("custom") or "").strip()
        if picked:
            return (picked.lower().replace("-", "_"),
                    " ".join(part for part in (typed, custom) if part))
        if not typed and custom:
            return split_choice(custom)
    return split_choice(typed)


def _reply_text(response: Any) -> str:
    """The owner's reply from an approval: the typed response, else the first picked or
    written answer (the page's options), else the rendered text."""
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return ""
    text = str(response.get("response") or "").strip()
    if text:
        return text
    for answer in response.get("answers") or []:
        if not isinstance(answer, dict):
            continue
        picked = str(answer.get("custom") or "").strip() or next(
            (str(s).strip() for s in answer.get("selected") or [] if str(s).strip()), "")
        if picked:
            return picked
    return str(response.get("text") or "").strip()


def _slug(path: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_." else "-" for c in path)[:80]
    return f"{keep}-{hashlib.sha256(path.encode()).hexdigest()[:8]}"


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return None
