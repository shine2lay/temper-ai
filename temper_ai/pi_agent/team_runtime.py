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
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.accounts import turn_ending
from temper_ai.pi_agent.box import (
    TEAM_TOOL,
    BoxConfig,
    BoxSpec,
    session_started,
    stop_leftover_box,
)
from temper_ai.pi_agent.event_guard import guarded
from temper_ai.pi_agent.host import (
    INVALID,
    _jsonable,
    _slug,
    pin_for,
    prepare_participant,
    recovery_asked_again,
    recovery_word,
    session_rewind_allowed_before,
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
)
from temper_ai.pi_agent.member_tree import SnapshotRefused
from temper_ai.pi_agent.route.model import RESERVED_IDS
from temper_ai.pi_agent.route.router import (
    POLICY_VERSION,
    policy_for,
    reachable,
    roster_entry,
)
from temper_ai.pi_agent.settings_wait import (
    SETTINGS,
    STOP,
    team_stop_text,
    team_subject,
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
    the pause, when the team had nothing left to do, or when its settings changed while it
    waited (SW-85) is the owner's decision, and nothing failed there. A stop at a recovery
    wait follows a failed or cut-off turn: it fails."""
    return wait is not None and wait.get("kind") in ("pause", "stalled", "limit", SETTINGS)


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
        if subject.get("at_usd") is not None:  # a free-flowing team's check-in
            return f"stopped at the check-in at ${float(subject['at_usd']):g}"
        return f"stopped at the pause after round {subject.get('round')}"
    if kind == "limit" and decision.get("answer") == "stop":
        return "stopped at the usage limit"
    if kind == "stalled" and decision.get("answer") == "stop":
        return "stopped when the team had nothing left to do"
    if kind == SETTINGS and decision.get("answer") == STOP:
        return team_stop_text(subject)
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
    turn's end: ``completed``, ``held`` (cut off or a usage limit: a recovery wait is open),
    ``failed`` (the member's turn failed visibly), ``refused`` (the run's account refused
    the call: the turn failed and the team must stop, ADR-M4-16) or ``lost`` (a newer
    attempt took the turn over meanwhile).
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
    communication type, the router's policy version and the leader. A resume under different
    team settings is refused before any turn. The check-in amount and the cap on turns at
    once are not in it: changing them changes nothing a member was told."""
    doc = {
        "members": sorted([m.name, m.config.get("role")] for m in members),
        "communication": (team_settings.get("communication") or {}).get("type", "all"),
        "edges": (team_settings.get("communication") or {}).get("edges"),
        "policy": POLICY_VERSION,
        "leader": (team_settings.get("mode") or {}).get("leader"),
        "team": "free",
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
                 workflow: str | None = None, cancel_event: Any = None,
                 account: dict | None = None):
        self.ledger = ledger
        self.box = box
        #: The run's one account (ADR-M4-09): its slot pins every member's login hand-off
        #: and is recorded on every turn; never another slot, whatever a call returns.
        self.account = dict(account or {})
        self.account_slot = str(self.account.get("slot") or "")
        self.run_id = run_id
        self.host_path = host_path
        self.members = {m.name: m for m in members}
        self.team_settings = dict(team_settings or {"communication": {"type": "all"}})
        self.communication = (self.team_settings.get("communication") or {}).get("type", "all")
        # The team's own records, its turns' and its owner waits' leave through the door.
        self.recorder = guarded(recorder)
        self.attempt_id = attempt_id
        self.parent_event_id = parent_event_id
        self.workflow = workflow
        self.cancel_event = cancel_event
        self.digest = team_digest(members, self.team_settings)
        self.root = Path(box.state_root) / run_id / _slug(host_path)
        #: Each member's settings pin in this attempt (set by :meth:`open`).
        self.pins: dict[str, dict] = {}

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
        members, a database Pi doesn't know (SW-13) or a resume with other members (added,
        removed, or a member with another role: a conversation can't be carried into a
        different team, R2 C3), all without writing anything; or a role snapshot refused,
        after the rows are attached but with nothing on record, so the next open copies
        afresh. Any other changed setting is not refused here: the owner is asked first, at
        a settings wait (:meth:`open_settings_wait`, SW-85)."""
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
            moved = sorted(name for name, row in existing.items()
                           if row["role"] != self.members[name].config["role"])
            if moved:
                return (f"{SETTINGS_CHANGED} since the team started (the role of "
                        + ", ".join(moved) + "); refusing to reopen its conversations")
        self.pins = pins
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

    # --- the settings wait (SW-85) ---------------------------------------------------

    def settings_changed(self) -> list[tuple[str, str, dict, dict]]:
        """Every member still in the conversation whose stored pin differs from its settings
        now (a deploy while the team waited): (member, participant id, stored pin, pin now)."""
        out = []
        for row in self.ledger.participants_of(self.run_id, self.host_path):
            now = self.pins.get(row["member"])
            if (now is not None and row["state"] not in ("ended", "retired")
                    and (row["pin"] or {}) != now):
                out.append((row["member"], row["participant_id"], row["pin"] or {}, now))
        return out

    def open_settings_wait(self) -> bool:
        """A member's settings or the team's differ from the stored pins: the team's one
        settings wait, naming every changed member's settings (opened unless one is open
        already). True when a settings wait is open. It is asked before anything else: no turn runs, and no other answer is
        applied, on settings the owner hasn't confirmed."""
        changed = self.settings_changed()
        if changed:
            self.ledger.open_wait_unless_open(self.run_id, self.host_path, SETTINGS,
                                              team_subject(changed), self.attempt_id)
        return any(w["kind"] == SETTINGS
                   for w in self.ledger.open_waits(self.run_id, self.host_path))

    def resume(self, newer_attempts: Callable[[], Collection[str]] | None = None) -> list[dict]:
        """At the start of every attempt: a turn cut off by a stopped attempt is taken over
        only once its old box is confirmed gone (R2 C1; raises ``TakeoverRefused`` when that
        cannot be confirmed: fail red, take nothing over), and a turn that failed is put to the
        owner (retry or stop, N1). Returns the team's open waits. ``newer_attempts`` names
        the attempts that started after this one: their turns are never taken over
        (``Ledger.take_over``, SW-84)."""
        taken = self.ledger.take_over(self.run_id, self.host_path, self.attempt_id,
                                      type(self).stop_box or stop_leftover_box,
                                      why="the service stopped during the turn",
                                      newer_attempts=newer_attempts)
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
        from temper_ai.pi_agent.turn import TurnReport, TurnRequest, run_turn

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
                # The account by its slot label; inside the box the provider stays the
                # canonical one (ADR-M4-15).
                "account_slot": self.account_slot or None,
            })
        if not self.ledger.set_turn_agent_event(turn["turn_id"], agent_event_id,
                                                epoch=turn["epoch"],
                                                account_slot=self.account_slot):
            return StepResult("lost", member=name, turn=turn)
        pdir = Path(part["session_dir"]).parent
        spec = BoxSpec(participant_dir=pdir, session_id=part["session_id"], role=cfg["role"],
                       provider=model["provider"], model=model["model"],
                       thinking=model["thinking"], tools=self.tools_for(member),
                       labels={"run": self.run_id[:36], "turn": turn["turn_id"][:16]},
                       add_ons=add_on_names(cfg), team=channel, slot=self.account_slot)
        try:
            text = self.prompt_for(member, turn, batch)
        except Exception as exc:  # noqa: BLE001 -- no box exists, but use normal turn policy
            error = f"{name} ({cfg['role']}) turn {turn['turn_no']} could not start: {exc}"
            result = self.settle(turn, name, cfg, TurnReport(state="failed", error=error),
                                 {"box_started": False}, agent_event_id)
            if result.kind != "lost":
                self._close_turn_event({**turn, "agent_event_id": agent_event_id,
                                        "member": name}, error)
            return result
        req = TurnRequest(run_id=self.run_id, agent_name=name, node_path=self.host_path,
                          participant=part, turn=turn, text=text,
                          spec=spec, agent_event_id=agent_event_id, recorder=self.recorder,
                          cancel_event=self.cancel_event,
                          first_start=not session_started(pdir),
                          rewind_allowed=session_rewind_allowed_before(self.ledger, turn),
                          **self.request_extras(turn))
        report = (type(self).turn_runner or run_turn)(self.box, req, self.ledger)
        worker = {**(report.worker or {}), "effective": report.effective,
                  "checks": _jsonable(report.checks)}
        return self.settle(turn, name, cfg, report, worker, agent_event_id)

    def request_extras(self, turn: dict) -> dict:
        """More fields for the turn's request (a free-flowing team adds its inbox)."""
        return {}

    def settle(self, turn: dict, name: str, cfg: dict, report: Any, worker: dict,
               agent_event_id: str) -> StepResult:
        """Record how the turn ended (completed, held for the owner, or failed)."""
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
        # How the turn ended, read on the error path only (ADR-M4-16): a member's answer is
        # never read for an account's words.
        ending = turn_ending(report, self.account_slot, self.account.get("room"))
        if ending.kind == "held":
            # Cut off (a hang, a lost box, a cancel) or a usage limit: the owner decides,
            # and the whole team waits meanwhile (B11). Never a blind re-run. A limit names
            # the account, the limit and the reset; a retry keeps the same account.
            wait = self.ledger.hold_turn(turn["turn_id"], ending.text, report.model_call_ids,
                                         worker, self.attempt_id, epoch=turn["epoch"],
                                         details=ending.details)
            if wait is None:
                return StepResult("lost", member=name, turn=turn)
            return StepResult("held", member=name, turn=turn, wait=wait, error=ending.text)
        # A red turn. When the account refused the call the team stops (no recovery wait, no
        # other slot, no retry: no reset fixes it); the error is never the member's answer.
        error = f"{name} ({cfg['role']}) turn {turn['turn_no']} failed: {ending.text}"
        if not self.ledger.fail_turn(turn["turn_id"], error, report.model_call_ids, worker,
                                     epoch=turn["epoch"]):
            return StepResult("lost", member=name, turn=turn)
        return StepResult("refused" if ending.kind == "refused" else "failed", member=name,
                          turn=turn, error=error)

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
