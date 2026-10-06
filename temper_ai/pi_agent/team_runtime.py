"""A team of Pi members that talk only through Temper (T4 + T5 thin slice, switched off).

Built to Architecture's R2 rules (pi-agent-proofs/R2/review.md) on the Pi ledger
(:mod:`temper_ai.pi_agent.ledger`). Communication ``all`` only; one turn at a time per team.

* Every member has one row and one Pi session for the whole run, reused for every turn
  (R2 B8). Its worker box exists only during a turn: an idle member has no box, and its next
  turn's box reopens the same session.
* A member sends with the ``send_message`` tool of the box's temper-box extension. The tool
  writes to the box's team socket, which is bound by Temper to this member's running turn
  (:class:`TeamChannel`): Temper stamps the sender, session and turn from its own record,
  never from what the model wrote (B2), and routes by A7's rules (:mod:`.route.router`).
  What a turn sends is held with the turn and released only when it settles (B4).
* A turn takes the member's pending messages as one ordered batch, framed so that no body
  can pass for Temper's lines (B5, :mod:`.inbox`). A retried turn gets the same messages
  again, same ids, marked as given again (B1).
* The team's next turn goes to the idle member holding its oldest pending message, claimed
  through the ledger's guarded claim (B6): two processes never run the same turn, and no turn
  starts while any team wait is open. A cut-off turn opens a recovery wait that pauses the
  whole team (B11); it is taken over only once its old box is confirmed gone (C1).
* Ending the team (owner cancel, run end) records every message still queued as undelivered,
  never drops it (B12); a message posted after that is recorded undelivered too (B6).

Nothing here is wired into the team node yet: #38 (the leader loop) drives :class:`Team`.
Everything is behind ``TEMPER_PI_AGENT``: this module is only imported with the switch on.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.box import (
    TEAM_TOOL,
    BoxConfig,
    BoxSpec,
    session_started,
    stop_leftover_box,
)
from temper_ai.pi_agent.host import (
    INVALID,
    _jsonable,
    _slug,
    changed_keys,
    owner_decided_before,
    pin_for,
    prepare_participant,
    recovery_asked_again,
    recovery_word,
)
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.ledger import (
    Binding,
    Ledger,
    LedgerLayoutError,
    process_identity,
)
from temper_ai.pi_agent.member import (
    add_on_names,
    config_problems,
    launched_tools,
    settings,
    usage_limit,
)
from temper_ai.pi_agent.member_tree import SnapshotRefused
from temper_ai.pi_agent.route.model import RESERVED_IDS
from temper_ai.pi_agent.route.router import (
    POLICY_VERSION,
    policy_for,
    reachable,
    roster_entry,
)
from temper_ai.shared.text_limits import STOP_REASON_MAX_CHARS

logger = logging.getLogger(__name__)

AGENT_TYPE = "pi"
SETTINGS_CHANGED = "team settings changed"
#: The longest words kept with a stop answer (M3 E13 ``stop_reason_max_chars``): the API
#: refuses longer ones; a chat answer is cut to this.
STOP_WORDS_MAX = STOP_REASON_MAX_CHARS


def stop_words(words: str | None) -> str | None:
    """The words given with a stop answer as kept (the outcome's ``owner_words``, M3 E18):
    trimmed, at most :data:`STOP_WORDS_MAX` characters, None when there are none."""
    text = str(words or "").strip()[:STOP_WORDS_MAX].strip()
    return text or None


def stop_ends_cancelled(wait: dict | None) -> bool:
    """Whether a stop answer ends the run cancelled rather than failed (M3 E18): a stop at
    the pause or when the team had nothing left to do is the owner's decision, and nothing
    failed there. A stop at a recovery wait follows a failed or cut-off turn: it fails."""
    return wait is not None and wait.get("kind") in ("pause", "stalled")


def recovery_stop_text(member: Any, turn_no: Any, options: Any) -> str:
    """The neutral text for a stop at a recovery wait (M3 E16): a turn that failed (answered
    retry or stop only) or one that was cut off (``accept`` among its options)."""
    did = "failed" if "accept" not in (options or []) else "did not finish"
    return f"{member} turn {turn_no} {did} and the team was stopped"


def stop_text(wait: dict) -> str | None:
    """The neutral text (M3 E16) for a decided wait whose answer stopped the team, or None
    when its answer did not stop it. It never names who answered: that is the outcome's
    ``by``."""
    decision, subject = wait.get("decision") or {}, wait.get("subject") or {}
    kind = wait.get("kind")
    if kind == "pause" and decision.get("answer") == "stop":
        return f"stopped at the pause after round {subject.get('round')}"
    if kind == "stalled" and decision.get("answer") == "stop":
        return "stopped when the team had nothing left to do"
    if kind == "recovery" and decision.get("recovery") == "stop":
        return recovery_stop_text(subject.get("member"), subject.get("turn_no"),
                                  subject.get("options"))
    return None


@dataclass(frozen=True)
class TeamMember:
    """One member: its team name and its agent config (role, model settings, tools...)."""

    name: str
    config: dict


@dataclass
class StepResult:
    """What one :meth:`Team.step` did.

    ``kind``: ``idle`` (no member has a message), ``waiting`` (a team wait is open: nothing
    runs until it is answered), ``busy`` (another attempt holds the team's turn), or the
    turn's end: ``completed``, ``held`` (cut off: a recovery wait is open), ``failed`` (the
    member's turn failed visibly) or ``lost`` (a newer attempt took the turn over meanwhile).
    """

    kind: str
    member: str | None = None
    turn: dict | None = None
    error: str | None = None
    wait: dict | None = None
    released: dict = field(default_factory=dict)


class TeamChannel:
    """A member's message channel for one turn: the box's team socket calls ``handle``.

    The binding (run, team, member, session, turn, epoch) is Temper's own record of which box
    runs which member (R2 B2); nothing in a payload can change it. ``reachable`` is the names
    the member may message (the box shows them to the send tool; Temper still checks every
    send)."""

    def __init__(self, ledger: Ledger, binding: Binding, reachable_names: list[str]):
        self.ledger = ledger
        self.binding = binding
        self.reachable = tuple(reachable_names)

    def handle(self, payload: Any) -> dict:
        return self.ledger.member_send(self.binding, payload)


def team_digest(members: list[TeamMember], team_settings: dict) -> str:
    """What every member's conversation was started under (R2 C3): the roster with roles, the
    communication type, the router's policy version, the leader and pause_after_rounds. A
    resume under different team settings is refused before any turn."""
    doc = {
        "members": sorted([m.name, m.config.get("role")] for m in members),
        "communication": (team_settings.get("communication") or {}).get("type", "all"),
        "edges": (team_settings.get("communication") or {}).get("edges"),
        "policy": POLICY_VERSION,
        "leader": (team_settings.get("mode") or {}).get("leader"),
        "pause_after_rounds": team_settings.get("pause_after_rounds"),
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


def member_tools(cfg: dict) -> list[str]:
    """The Pi tools a member's box launches with: its own and Temper's send tool. Pi turns on
    an extension's tool only when ``--tools`` names it."""
    return sorted(set(launched_tools(cfg)) | {TEAM_TOOL})


class Team:
    """One team's runtime in one attempt. Every decision is read from and written to the
    ledger, so a later attempt (a Resume, a restart, another process) carries on from the
    tables alone."""

    #: Test seams: the turn runner (``run_turn``) and the leftover-box stopper (C1).
    turn_runner: Any = None
    stop_box: Any = None

    def __init__(self, ledger: Ledger, box: BoxConfig, *, run_id: str, host_path: str,
                 members: list[TeamMember], team_settings: dict | None, recorder: Any,
                 attempt_id: str, parent_event_id: str | None = None,
                 workflow: str | None = None, cancel_event: Any = None):
        self.ledger = ledger
        self.box = box
        self.run_id = run_id
        self.host_path = host_path
        self.members = {m.name: m for m in members}
        self.team_settings = dict(team_settings or {"communication": {"type": "all"}})
        self.communication = (self.team_settings.get("communication") or {}).get("type", "all")
        self.recorder = recorder
        self.attempt_id = attempt_id
        self.parent_event_id = parent_event_id
        self.workflow = workflow
        self.cancel_event = cancel_event
        self.digest = team_digest(members, self.team_settings)
        self.root = Path(box.state_root) / run_id / _slug(host_path)

    # --- opening ----------------------------------------------------------------------

    def problems(self) -> list[str]:
        """What stops the team from opening at all (nothing is written)."""
        out: list[str] = []
        if not self.members:
            out.append("a team needs at least one member")
        if self.communication != "all":
            out.append(f"communication {self.communication!r} is not built; use all")
        for name, member in self.members.items():
            if not name or name.lower() in RESERVED_IDS:
                out.append(f"member name {name!r} is reserved")
                continue
            cfg = member.config
            out += [f"member {name}: {p}" for p in config_problems(cfg)]
            if not cfg.get("role"):
                continue
            provider = settings(cfg)["provider"]
            if provider not in self.box.routes:
                out.append(f"member {name}: no worker route for provider {provider!r}")
            if not (Path(self.box.identities_dir) / cfg["role"]).is_dir():
                out.append(f"member {name}: role {cfg['role']!r} is not defined")
            missing = [a for a in add_on_names(cfg) if a not in self.box.add_ons]
            if missing:
                out.append(f"member {name}: no pinned copy of add-on(s) " + ", ".join(missing))
        return out

    def pin(self, member: TeamMember) -> dict:
        return pin_for(self.box, member.config, workflow=self.workflow,
                       tools=self.tools_for(member), team=self.digest)

    # --- seams for the leader loop (#38); the defaults are this module's own behaviour ---

    def tools_for(self, member: TeamMember) -> list[str]:
        """The Pi tools ``member``'s box launches with, pinned with its settings (R2 B16)."""
        return member_tools(member.config)

    def channel_for(self, binding: Binding, reachable_names: list[str]) -> TeamChannel:
        """The team socket's handler for one turn, bound by Temper (R2 B2)."""
        return TeamChannel(self.ledger, binding, reachable_names)

    def prompt_for(self, member: TeamMember, turn: dict, batch: list[dict]) -> str:
        """The turn's prompt: the batch framed by Temper (R2 B5)."""
        return render_batch(batch, team=True)

    def open(self, values: dict | None = None) -> str | None:
        """Attach every member -- one row and one session each -- or find them again, and
        snapshot each member's role folder until its digest is on record (SW-25).
        Returns a refusal text, always before any turn, when the team cannot open: bad
        members, a database Pi doesn't know (SW-13) or a resume under changed settings (R2 C3),
        all without writing anything; or a role snapshot refused, after the rows are attached
        but with nothing on record, so the next open copies afresh."""
        problems = self.problems()
        if problems:
            return "; ".join(problems)
        policy_for(self.communication, self.run_id)  # the router knows `all` only (B7)
        try:
            self.ledger.ensure()
        except LedgerLayoutError as exc:  # SW-13
            return f"Pi refused this database: {exc}"
        pins = {name: self.pin(m) for name, m in self.members.items()}
        existing = {r["member"]: r for r in self.ledger.participants_of(self.run_id,
                                                                         self.host_path)}
        if existing:
            if set(existing) != set(pins):
                return (f"{SETTINGS_CHANGED} since the team started (members); refusing to "
                        "reopen its conversations")
            for name, row in existing.items():
                if row["pin"] != pins[name]:
                    changed = changed_keys(pins[name], row["pin"])
                    if "team" in changed:
                        return (f"{SETTINGS_CHANGED} since the team started; refusing to "
                                "reopen its conversations")
                    return (f"member {name}'s settings changed since its conversation started ("
                            + ", ".join(changed) + "); refusing to reopen it")
        rows = self.ledger.attach_team(
            self.run_id, self.host_path,
            [(name, m.config["role"], pins[name]) for name, m in self.members.items()],
            session_root=str(self.root), attempt_id=self.attempt_id)
        # Every attach, until each member's snapshot is on record (SW-25): a crash before that
        # left nothing a later attempt reuses.
        for row, _created in rows:
            try:
                prepare_participant(self.box, Path(row["session_dir"]).parent,
                                    self.members[row["member"]].config, values or {},
                                    ledger=self.ledger, participant=row)
            except SnapshotRefused as exc:
                return f"member {row['member']}'s role snapshot was refused: {exc}"
        return None

    def resume(self) -> list[dict]:
        """At the start of every attempt: a turn cut off by a stopped attempt is taken over
        only once its old box is confirmed gone (R2 C1; raises ``TakeoverRefused`` when that
        cannot be confirmed: fail red, take nothing over), and a turn that failed is put to the
        owner (retry or stop, N1). Returns the team's open waits."""
        taken = self.ledger.take_over(self.run_id, self.host_path, self.attempt_id,
                                      type(self).stop_box or stop_leftover_box,
                                      why="the service stopped during the turn")
        for turn, _wait in taken:
            self._close_turn_event(turn, "the turn was cut off: the service stopped during it")
        self.ledger.open_recovery_for_failed(self.run_id, self.host_path, self.attempt_id)
        return self.ledger.open_waits(self.run_id, self.host_path)

    # --- messages from outside the team ----------------------------------------------

    def post(self, to_member: str, body: str, *, sender: str = "owner",
             sender_kind: str = "owner", kind: str = "owner_reply",
             dedupe_key: str | None = None) -> dict:
        """A message from the owner or Temper (the brief, an answer). It waits for the
        member's next turn boundary; after the team ended it is recorded undelivered."""
        return self.ledger.post(self.run_id, self.host_path, to_member, body, sender=sender,
                                sender_kind=sender_kind, kind=kind, dedupe_key=dedupe_key)

    # --- turns ------------------------------------------------------------------------

    def step(self) -> StepResult:
        """Run the team's next turn, if any member has one. One at a time per team."""
        claimed = self.ledger.claim_turn(self.run_id, self.host_path,
                                         attempt_id=self.attempt_id,
                                         claimed_by=process_identity())
        if claimed is None:
            state = self.ledger.team_state(self.run_id, self.host_path)
            if state["open_waits"]:
                return StepResult("waiting", wait=state["waits"][0])
            if state["unsettled"]:
                return StepResult("busy", turn=state["turns"][0])
            stuck = [m for m in state["members"] if m["state"] in ("failed", "uncertain")]
            if stuck:
                # A failed turn is put to the owner by the next attempt (resume): retry or
                # stop. Until then the team stays paused.
                return StepResult("failed", member=stuck[0]["member"],
                                  error=f"member {stuck[0]['member']}'s turn needs the "
                                        "owner's decision (retry or stop)")
            return StepResult("idle")
        turn, batch = claimed
        return self._run(turn, batch)

    def _run(self, turn: dict, batch: list[dict]) -> StepResult:
        from temper_ai.pi_agent.turn import TurnRequest, run_turn

        part = self.ledger.participant(turn["participant_id"]) or {}
        name = part["member"]
        member = self.members[name]
        cfg = member.config
        model = settings(cfg)
        roster = [roster_entry(self.run_id, r)
                  for r in self.ledger.participants_of(self.run_id, self.host_path)]
        policy = policy_for(self.communication, self.run_id)
        channel = self.channel_for(
            Binding(run_id=self.run_id, host_path=self.host_path,
                    participant_id=part["participant_id"], member=name,
                    session_id=part["session_id"], turn_id=turn["turn_id"],
                    epoch=turn["epoch"]),
            reachable(policy, roster_entry(self.run_id, part), roster))
        agent_event_id = self.recorder.record(
            EventType.AGENT_STARTED, parent_id=self.parent_event_id,
            execution_id=self.run_id, status="running", data={
                "agent_name": name, "node_path": self.host_path, "type": AGENT_TYPE,
                "executed_by": "pi", "role": cfg["role"], **model,
                "input_data": {"messages": len(batch)},
                "pi_turn": {"turn_id": turn["turn_id"], "turn_no": turn["turn_no"],
                            "participant_id": part["participant_id"],
                            "session_id": part["session_id"], "member": name,
                            "attempt_id": self.attempt_id},
            })
        if not self.ledger.set_turn_agent_event(turn["turn_id"], agent_event_id,
                                                epoch=turn["epoch"]):
            return StepResult("lost", member=name, turn=turn)
        pdir = Path(part["session_dir"]).parent
        spec = BoxSpec(participant_dir=pdir, session_id=part["session_id"], role=cfg["role"],
                       provider=model["provider"], model=model["model"],
                       thinking=model["thinking"], tools=self.tools_for(member),
                       labels={"run": self.run_id[:36], "turn": turn["turn_id"][:16]},
                       add_ons=add_on_names(cfg), team=channel)
        req = TurnRequest(run_id=self.run_id, agent_name=name, node_path=self.host_path,
                          participant=part, turn=turn,
                          text=self.prompt_for(member, turn, batch),
                          spec=spec, agent_event_id=agent_event_id, recorder=self.recorder,
                          cancel_event=self.cancel_event,
                          first_start=not session_started(pdir),
                          rewind_allowed=owner_decided_before(self.ledger, turn))
        report = (type(self).turn_runner or run_turn)(self.box, req, self.ledger)
        worker = {**(report.worker or {}), "effective": report.effective,
                  "checks": _jsonable(report.checks)}
        if report.outcome is None:
            self.recorder.record(EventType.AGENT_FAILED, parent_id=agent_event_id,
                                 execution_id=self.run_id, status="failed", data={
                                     "agent_name": name, "error": report.error, "output": "",
                                     "executed_by": "pi", "tokens": 0, "cost_usd": 0.0})
        if report.state == "completed":
            res = self.ledger.finish_turn(turn["turn_id"], epoch=turn["epoch"],
                                          output=report.output,
                                          model_call_ids=report.model_call_ids, worker=worker,
                                          ask_owner=None, attempt_id=self.attempt_id)
            if res is None:
                return StepResult("lost", member=name, turn=turn)
            return StepResult("completed", member=name, turn=self.ledger.turn(turn["turn_id"]),
                              released=res["released"])
        limit = usage_limit(report.error) if report.state != "uncertain" else None
        if report.state == "uncertain" or limit:
            # Cut off (a hang, a lost box, a cancel) or a usage limit: the owner decides,
            # and the whole team waits meanwhile (B11). Never a blind re-run.
            wait = self.ledger.hold_turn(turn["turn_id"], limit or report.error or "cut off",
                                         report.model_call_ids, worker, self.attempt_id,
                                         epoch=turn["epoch"])
            if wait is None:
                return StepResult("lost", member=name, turn=turn)
            return StepResult("held", member=name, turn=turn, wait=wait,
                              error=limit or report.error)
        error = f"{name} ({cfg['role']}) turn {turn['turn_no']} failed: {report.error}"
        if not self.ledger.fail_turn(turn["turn_id"], error, report.model_call_ids, worker,
                                     epoch=turn["epoch"]):
            return StepResult("lost", member=name, turn=turn)
        return StepResult("failed", member=name, turn=turn, error=error)

    # --- the owner's answers and the end ---------------------------------------------

    def decide(self, wait: dict, answer: str, *, words: str | None = "",
               who: dict | None = None) -> str | None:
        """Apply the owner's answer to a recovery wait once: ``retry`` gives the turn's own
        messages again (same ids) and drops what it sent; ``accept`` keeps a cut-off turn and
        releases what it sent; ``stop`` ends the member's turn failed. A failed turn is
        answered retry or stop only (N1). Anything else (empty, another word, accept at a
        failed turn) decides nothing: the wait closes ``invalid`` and the owner is asked again
        at a new wait for the same turn (M3 F1). ``answer`` is what the owner said
        (:func:`~temper_ai.pi_agent.host.owner_reply`). The decision keeps ``who`` answered
        (``by``, ``source``; M3 E21) and, for a stop, the ``words`` given with it (the
        outcome's ``owner_words``). Returns an error text when the team must stop."""
        if wait["kind"] != "recovery":
            raise ValueError("only recovery waits are answered here")
        subject = wait["subject"] or {}
        options = subject.get("options") or ["accept", "retry"]
        word = recovery_word(answer, options)
        sha = hashlib.sha256(answer.encode()).hexdigest()
        who = dict(who or {})
        if word is None:
            self.ledger.decide_wait(wait["wait_id"],
                                    {"recovery": INVALID, "text_sha256": sha, **who},
                                    self.attempt_id, reask=recovery_asked_again(subject))
            return None
        decision = {"recovery": word, "text_sha256": sha, **who}
        if word == "stop":
            decision["words"] = stop_words(words)
        if not self.ledger.decide_wait(wait["wait_id"], decision, self.attempt_id,
                                       recovery=(word, subject["turn_id"])):
            return None
        if word == "stop":
            return recovery_stop_text(subject.get("member"), subject.get("turn_no"), options)
        return None

    def end(self, reason: str) -> dict:
        """End the team (owner cancel or run end): every message still held or pending is
        recorded undelivered, waits are cancelled, members end (R2 B12). Idempotent.

        Each cancelled wait's still-waiting owner events are closed, found by the wait's
        name (``ask_owner`` may have asked it more than once); nothing is found by the row's
        ``event_id``, which no owner event carries."""
        ended = self.ledger.end_team(self.run_id, self.host_path, reason, self.attempt_id)
        gate_events = getattr(self.recorder, "gate_events", None)
        decide = getattr(self.recorder, "decide", None)
        if gate_events and decide:
            from temper_ai.stage.gate import REJECTED, WAITING

            for w in ended["cancelled_waits"]:
                for ev in gate_events(w["gate_name"]) or []:
                    if ev.get("status") == WAITING:
                        decide(ev["id"], expect=(WAITING,), status=REJECTED,
                               data={"gate_status": REJECTED, "pi_cancelled": True})
        return ended

    def state(self) -> dict:
        """The team's state straight from the tables (quiet = nothing running, nothing
        waiting to be delivered, no open wait or review, nothing done)."""
        return self.ledger.team_state(self.run_id, self.host_path)

    # --- helpers ----------------------------------------------------------------------

    def _close_turn_event(self, turn: dict, why: str) -> None:
        eid = turn.get("agent_event_id")
        status = getattr(self.recorder, "event_status", None)
        if not eid or status is None or status(eid) != "running":
            return
        self.recorder.record(EventType.AGENT_FAILED, parent_id=eid, execution_id=self.run_id,
                             status="failed", data={"agent_name": turn.get("member") or "",
                                                    "error": why, "output": "",
                                                    "executed_by": "pi", "tokens": 0,
                                                    "cost_usd": 0.0})
        update = getattr(self.recorder, "update_event", None)
        if update:
            update(eid, status="failed")
