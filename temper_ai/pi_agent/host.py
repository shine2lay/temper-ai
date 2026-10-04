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
* after a turn the owner is asked what next through a wait with its own gate name
  (``<node path>~wait-<id>``), answered through Temper's ordinary approve route: a reply is
  the role's next message in the same session; ``done`` finishes the step;
* a turn that was cut off (worker gone, timeout, a tool that never ended, the service
  stopped) is never re-run: it becomes ``uncertain`` -- once its worker box is confirmed
  stopped -- and the owner decides (accept / retry; a retry gives the same messages again,
  same ids, never new copies);
* a turn that failed visibly (the worker could not be started or checked, the provider
  refused, the login was not handed over) fails the step -- red, never green. A Resume of
  the run then asks the owner whether to retry that turn or stop;
* the step never raises and never returns empty output, so AgentNode never re-runs it blind.

The step refuses to be a workflow's first node (R1 C6): an owner wait needs a checkpoint of
an earlier node to resume from.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
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
    stop_leftover_box,
    tree_sha256,
)
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.ledger import Ledger, LedgerConflict, TakeoverRefused
from temper_ai.pi_agent.member import (
    DEFAULT_TOOLS,
    add_on_names,
    config_problems,
    launched_tools,
    settings,
    usage_limit,
)
from temper_ai.shared.types import AgentResult, ExecutionContext, Status

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
    turn), ``poll_seconds``.
    """

    uses_llm_settings = False

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
        if not self._has_completed_predecessor(context):
            return self._fail("a Pi step cannot be a workflow's first node: put an ordinary "
                              "node before it (it gives an owner wait a checkpoint to resume "
                              "from)", started)
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
        self.box = box
        self.ledger = Ledger(get_database().engine)
        self.ledger.ensure()
        pin = self._pin(box)
        root = Path(box.state_root) / self.run_id / _slug(self.host_path)
        part, created = self.ledger.attach_participant(
            self.run_id, self.host_path, cfg["role"], role=cfg["role"], session_root=str(root),
            pin=pin, attempt_id=self.attempt_id)
        pdir = Path(part["session_dir"]).parent
        if created:
            self._prepare_participant(pdir, input_data)
        elif part["pin"] != pin:
            changed = changed_keys(pin, part["pin"])
            return self._fail("the Pi step's settings changed since its conversation started ("
                              + ", ".join(changed) + "); refusing to reopen it", started)
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
        for wait in self.ledger.open_waits(self.run_id, self.host_path):
            self._publish_wait(wait)

        poll = float(cfg.get("poll_seconds", 0.5))
        while True:
            cancel = context.cancel_event
            if cancel is not None and cancel.is_set():
                # Nothing queued is dropped: it is recorded undelivered (R2 B12).
                ended = self.ledger.end_team(self.run_id, self.host_path, "run_cancelled",
                                             self.attempt_id)
                rec = context.event_recorder
                for w in ended["cancelled_waits"]:
                    if rec.event_status(w["event_id"]) == "waiting":
                        rec.update_event(w["event_id"], status="rejected", data={
                            "gate_status": "rejected", "pi_cancelled": True})
                return self._result(Status.CANCELLED, "Pi step cancelled", started,
                                    error="cancelled")
            for wait in self.ledger.open_waits(self.run_id, self.host_path):
                failed = self._try_decide(wait)
                if failed:
                    return self._result(Status.FAILED, failed, started, error=failed)
            if self.ledger.open_waits(self.run_id, self.host_path):
                (cancel or threading.Event()).wait(poll)
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
                wait = self.ledger.open_wait(self.run_id, self.host_path, "owner",
                                             self._ask(p, None), self.attempt_id)
                self._publish_wait(wait)
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
                          first_start=not any((self.pdir / "sessions").glob("*.jsonl")),
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
            res = self.ledger.finish_turn(turn["turn_id"], epoch=turn["epoch"],
                                          output=report.output,
                                          model_call_ids=report.model_call_ids, worker=worker,
                                          ask_owner=self._ask(participant, turn),
                                          attempt_id=self.attempt_id)
            if res is None:
                return LOST_TURN
            if res["wait"]:
                self._publish_wait(res["wait"])
            return None
        limit = usage_limit(report.error) if report.state != "uncertain" else None
        if report.state == "uncertain" or limit:
            # Cut off: the owner decides (never a blind re-run). A usage or rate limit pauses
            # the step the same way (retry once it resets), naming the limit; never a quiet
            # switch to another model or account.
            wait = self.ledger.hold_turn(turn["turn_id"], limit or report.error or "cut off",
                                         report.model_call_ids, worker, self.attempt_id,
                                         epoch=turn["epoch"])
            if wait is None:
                return LOST_TURN
            self._publish_wait(wait)
            return None
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

    def _publish_wait(self, wait: dict) -> None:
        """Make a wait visible and answerable: its one gate event, recorded once."""
        rec = self.ctx.event_recorder
        if not wait["event_recorded"]:
            if rec.event_status(wait["event_id"]) is None:
                subject = wait["subject"] or {}
                rec.record(EventType.STAGE_STARTED, data={
                    "name": wait["gate_name"], "type": "pi_wait", "depends_on": [],
                    "gate": True, "gate_status": "waiting",
                    "gate_context": {"upstream": [], "questions": [{
                        "question": subject.get("question", ""), "header": wait["kind"],
                        "options": [{"label": o} for o in subject.get("options", [])]}]},
                    "pi_wait": {"wait_id": wait["wait_id"], "kind": wait["kind"],
                                "host_path": self.host_path, "role": subject.get("role"),
                                "turn_id": subject.get("turn_id"),
                                "opened_attempt": wait["opened_attempt"]},
                }, parent_id=self.ctx.parent_event_id, execution_id=self.run_id,
                    status="waiting", event_id=wait["event_id"])
            self.ledger.mark_event_recorded(wait["wait_id"])

    def _try_decide(self, wait: dict) -> str | None:
        """Apply the owner's answer once. Returns an error text when the step must fail."""
        rec = self.ctx.event_recorder
        if rec.event_status(wait["event_id"]) != "approved":
            return None
        data = rec.event_data(wait["event_id"]) or {}
        text = _reply_text(data.get("gate_response"))
        subject = wait["subject"] or {}
        decision: dict[str, Any] = {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        deliveries: list[tuple[str, str]] = []
        recovery = None
        states: list[tuple[str, str]] = []
        failure = None
        if wait["kind"] == "recovery":
            word = recovery_word(text, subject.get("options") or ["accept", "retry"])
            decision["recovery"] = word
            # A retry gives the turn's own messages again -- same ids, marked as given again --
            # never new copies (R2 B1); what the turn sent is never delivered (B4).
            recovery = (word, subject["turn_id"])
            if word == "stop":
                did = ("failed" if "accept" not in (subject.get("options") or [])
                       else "did not finish")
                failure = (f"{subject.get('role')} turn {subject.get('turn_no')} {did} and the "
                           "owner stopped the step")
        elif text.lower() in FINISH_WORDS:
            decision["owner"] = "finish"
            states = [(subject.get("participant_id") or self.participant_id, "retired")]
        else:
            decision["owner"] = "message"
            deliveries = [(self.config["role"], text)]
        applied = self.ledger.decide_wait(wait["wait_id"], decision, self.attempt_id,
                                          deliveries=deliveries, recovery=recovery,
                                          participant_states=states)
        if applied:
            rec.update_event(wait["event_id"], data={
                "pi_applied": True, "pi_decision": {k: v for k, v in decision.items()
                                                    if k != "text_sha256"},
                "pi_decided_attempt": self.attempt_id,
                # Temper's gates read this as "the answer was used" (no Resume needed).
                "gate_used_at": datetime.now(UTC).isoformat()})
            if decision.get("recovery") == "accept":
                # The accepted turn stands; the owner says what comes next.
                p = self.ledger.participant(self.participant_id) or {}
                nxt = self.ledger.open_wait(self.run_id, self.host_path, "owner",
                                            self._ask(p, {"turn_no": subject.get("turn_no")}),
                                            self.attempt_id)
                self._publish_wait(nxt)
            return failure
        return None

    # --- helpers ----------------------------------------------------------------------

    @staticmethod
    def _has_completed_predecessor(context: ExecutionContext) -> bool:
        state = context.run_state or {}
        own = (context.node_path or "").rsplit(".", 1)[-1]
        for name, result in state.items():
            if name == own:
                continue
            status = getattr(result, "status", None)
            if status == Status.COMPLETED or str(status) in ("completed", "Status.COMPLETED"):
                return True
        return False

    def _public_config(self) -> dict:
        cfg = self.config
        return {"type": AGENT_TYPE, "name": self.name, "role": cfg.get("role"),
                **self.model_settings,
                "tools": list(cfg.get("tools") or DEFAULT_TOOLS),
                "add_ons": add_on_names(cfg)}

    def _pin(self, box: BoxConfig) -> dict:
        return pin_for(box, self.config, workflow=self.ctx.workflow_name)

    def _prepare_participant(self, pdir: Path, input_data: dict) -> None:
        prepare_participant(self.box, pdir, self.config, input_data)

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
    config_sha = hashlib.sha256(json.dumps(
        {k: v for k, v in cfg.items() if k not in ("poll_seconds",)}, sort_keys=True,
        default=str).encode()).hexdigest()
    pin = {"pi_version": box.pi_version, "image": box.image, **model,
           "tools": sorted(tools) if tools is not None else launched_tools(cfg),
           "extensions": extensions,
           "add_ons": {name: box.add_ons[name].sha256 for name in add_on_names(cfg)},
           "route_host": route.host, "workflow": workflow,
           "agent_config_sha256": config_sha, "cwd": WORKDIR}
    if team is not None:
        pin["team"] = team
    return pin


def prepare_participant(box: BoxConfig, pdir: Path, cfg: dict, values: dict) -> None:
    """Once per participant: the role's private snapshot and the working files."""
    role = cfg["role"]
    src = Path(box.identities_dir) / role
    dst = pdir / "memory" / "identities" / role
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, symlinks=False)
    work = pdir / "workspace"
    work.mkdir(parents=True, exist_ok=True)
    for name, template in (cfg.get("workspace_files") or {}).items():
        target = work / name
        if not target.exists():
            target.write_text(_jinja(template, values), encoding="utf-8")


def changed_keys(pin: dict, stored: dict) -> list[str]:
    return sorted(k for k in set(pin) | set(stored) if pin.get(k) != stored.get(k))


def owner_decided_before(ledger: Ledger, turn: dict) -> bool:
    """Whether the turn before this one was cut off or failed and the owner decided about
    it (accept or retry): only then may an unsettled session be moved back."""
    earlier = [t for t in ledger.turns_of(turn["participant_id"])
               if t["turn_no"] < turn["turn_no"]]
    return bool(earlier) and max(earlier, key=lambda t: t["turn_no"])["state"] in (
        "accepted", "superseded")


def recovery_word(text: str, options: list[str]) -> str:
    """The owner's answer to a recovery wait. A cut-off turn: ``retry``, ``stop`` or (anything
    else) ``accept``. A failed turn is answered ``retry`` or ``stop`` only (R2 N1): anything
    but ``retry`` stops."""
    first = text.lower().split()[0] if text.strip() else ""
    if first == "retry":
        return "retry"
    if first == "stop" or "accept" not in options:
        return "stop"
    return "accept"


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
