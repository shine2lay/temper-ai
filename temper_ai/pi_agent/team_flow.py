"""Free-flowing teams (FLOW; ADR-FLOW-01/02).

Every member of a free-flowing team works at the same time in its own copy of the Project,
and stays on: once a turn ends, the member's next turn starts at once, with whatever reached
it meanwhile, until it says it has nothing to do (the ``idle`` tool, or a turn with no tool
call at all). A message wakes it again. There are no rounds anywhere.

- **Start**: only the leader gets the goal and the team list; the
  others wait (``idle_reason`` ``start``) until a message reaches them.
- **One shared version** (F3, R3, S2): before each turn Temper commits what the member left
  in its copy and merges the team's shared version into it (``shared_version.sync``); the
  ``share`` tool merges the member's copy into the shared version once its turn has
  finished. Conflicts are recorded and named at the member's next turn.
- **Done** (F5, R2): the leader's ``done(summary)`` shares its copy and opens the closing:
  nothing new starts, the running turns finish, and done counts only when nothing reached
  the leader after its done call, no share landed after it, and no member is held or
  failed. Otherwise the leader is told why and gets one more turn on its own.
- **Holds** (R2): a member's failed or cut-off turn is retried once by itself, after its
  box is confirmed gone (C1); a second failure holds only that member (a recovery wait).
  Run-level holds: the check-in at every ``pause_every_usd`` of spend (F6, R4), the
  account's usage limit (a 5-hour limit carries on by itself at its reset; a
  weekly or unknown one asks the owner before restarting), the settings wait,
  Stop and cancel, a lane stop, and the closing.
- **R1**: a turn that ends at its call cap or time limit, with its box confirmed gone, is a
  normal end: its tool calls are carried out and the member's next turn starts at once.

The run parks (an owner question, no worker held) only when no turn is running and nothing
can be claimed. While turns run, owner questions are put to the owner without parking and
their answers are picked up as they come.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import logging
import threading
import time
from typing import Any

import sqlalchemy as sa

from temper_ai.pi_agent import host_helper, team_versions
from temper_ai.pi_agent.accounts import (
    FIVE_HOUR,
    call_trouble,
    limit_after_check,
    limit_ready,
    limit_restart_ready,
    limit_resume,
    refusal_problem,
    turn_ending,
)
from temper_ai.pi_agent.box import stop_leftover_box
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.ledger import (
    _LOCK,
    ACCOUNT_REFUSED,
    Binding,
    acts,
    messages,
    participants,
    turns,
    waits,
)
from temper_ai.pi_agent.route import model as route_model
from temper_ai.pi_agent.route.router import Refusal
from temper_ai.pi_agent.shared_version import (
    Conflict,
    SharedVersion,
    VersionError,
    conflict_lines,
)
from temper_ai.pi_agent.team import ROUNDS_TEAM
from temper_ai.pi_agent.team_leader import (
    MAX_NOTE,
    MAX_SUMMARY,
    NOT_NOW,
    PAUSE_OPTIONS,
    LeaderTeam,
    Outcome,
    TeamFailure,
    answer_who,
    owner_words,
    tools_note,
)
from temper_ai.pi_agent.team_runtime import (
    StepResult,
    TeamMember,
    member_tools,
    stop_words,
)
from temper_ai.runner.pi_lane import draining, leave_if_draining
from temper_ai.stage.exceptions import CancellationError

logger = logging.getLogger(__name__)

SHARE = "share"
IDLE = "idle"
DONE = "done"
FLOW_OPS = (SHARE, IDLE, DONE)
FLOW_FIELDS: dict[str, tuple[str, ...]] = {SHARE: ("note",), IDLE: ("note",), DONE: ("summary",)}
#: The check-in's spend step when a team names none: every $100.
PAUSE_EVERY_USD = 100.0
LIMIT_OPTIONS = ("restart", "stop")
#: How often an owner question is looked at again while turns are running, in seconds.
POLL_ASK_S = 3.0
#: How long the loop waits for a running turn to end before looking around again.
TICK_S = 1.0
#: How a share ended that lets done count (F5).
SHARE_OK = ("shared", "unchanged")


class _Halt(threading.Event):
    """The cancel signal a flow team's turns watch: the run's own cancel, or the team's
    halt (Stop, a lane stop, the end). Behaves like the ``threading.Event`` turns read."""

    def __init__(self, run_event: Any) -> None:
        super().__init__()
        self.run_event = run_event
        self.why: str | None = None

    @property
    def own(self) -> threading.Event:
        return self

    def set(self, why: str = "stop") -> None:
        if self.why is None:
            self.why = why
        super().set()

    def is_set(self) -> bool:
        return super().is_set() or bool(self.run_event is not None and self.run_event.is_set())

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = 0.1 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                return False
            super().wait(min(0.1, remaining))
        return True

    def run_cancelled(self) -> bool:
        return bool(self.run_event is not None and self.run_event.is_set())


def flow_framing(name: str, leader: str, roster: list[str], tools: list[str]) -> str:
    """What every turn of a free-flowing team's member starts with."""
    others = [m for m in roster if m != name]
    lead = ("You are the team's leader." if name == leader
            else f"The team's leader is {leader}.")
    text = (
        f"[Temper] You are {name}, a member of a team working through Temper: "
        f"{', '.join(roster)}. {lead} Everyone works at the same time, each in their own copy "
        "of the Project (your working folder). Temper keeps one shared version of the team's "
        "work: before each of your turns it merges the shared version into your copy, and "
        "the share tool merges your copy into it once your turn has finished. Share whenever "
        "a piece of your work is ready for the others.\n"
        "Talk with send_message: work_request to ask a member for something (they owe you a "
        "reply), reply to answer one, info for anything else. Messages that reach you while "
        "you work are shown to you in this turn. Your next turn starts as soon as this one "
        "ends; when nothing is your part right now, call idle (a turn with no tool call at "
        "all counts as idle too). A message wakes you again.")
    if name == leader:
        text += (
            "\nAs the leader: split the goal into parts, send each member its part as a "
            f"work_request ({', '.join(others) or 'nobody else'}), and decide when the work is "
            "finished. When it is, call done with a short summary: Temper shares your copy, "
            "lets the running turns finish and counts done only if nothing new reached you "
            "and nobody shared after your done call. Otherwise you are told why and carry on.")
    else:
        text += ("\nWork on what is asked of you, tell whoever asked (usually the leader) when "
                 "it is done or if you are stuck, and share your work.")
    return text + "\n" + tools_note(tools)


class FlowTeam(LeaderTeam):
    """A team that runs free-flowing (the module's doc). Reuses the leader team's tables,
    tool recording, owner waits and run view; replaces its tools, turn ends and loop."""

    OPS = FLOW_OPS
    ACT_FIELDS = FLOW_FIELDS

    def __init__(self, *args: Any, leader: str, goal: str, project: Any,
                 pause_every_usd: float = PAUSE_EVERY_USD, max_parallel: int | None = None,
                 **kw: Any) -> None:
        super().__init__(*args, leader=leader, pause_after=0, goal=goal, project=project, **kw)
        self.pause_every = float(pause_every_usd or PAUSE_EVERY_USD)
        self.cap = max(1, int(max_parallel or len(self.members) or 1))
        self.halt = _Halt(self.cancel_event)
        self.run_cancel = self.cancel_event
        self.cancel_event = self.halt
        self._last_poll = 0.0
        self._pending_end: str | None = None

    @property
    def shared(self) -> SharedVersion:
        return SharedVersion(self.project)

    def open(self, values: dict | None = None) -> str | None:
        """As a team opens, plus: a team that already ran in review rounds (turns, but none
        of a free-flowing team's events) is never carried on as a free-flowing one."""
        try:
            self.ledger.ensure()
        except Exception:  # noqa: BLE001 - the base open says what is wrong with the database
            return super().open(values)
        if (self._rows(turns) and not self.ledger.last_event_seq(self.run_id, self.host_path)):
            return ROUNDS_TEAM
        return super().open(values)

    def rest_the_others(self) -> None:
        """Only the leader starts: every other member that never had a
        turn or a message waits for one (``idle_reason`` ``start``)."""
        for name, row in self._member_rows().items():
            if name != self.leader:
                self.ledger.rest(row["participant_id"], "start", only_if_new=True)

    # --- tools and prompt -------------------------------------------------------------------

    def tools_for(self, member: TeamMember) -> list[str]:
        own = {SHARE, IDLE} | ({DONE} if member.name == self.leader else set())
        return sorted(set(member_tools(member.config)) | own)

    def prompt_for(self, member: TeamMember, turn: dict, batch: list[dict]) -> str:
        part = self.ledger.participant(turn["participant_id"]) or {}
        pdir = self._pdir(part)
        recorded = [Conflict.from_dict(c) for c in part.get("conflicts") or []]
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            synced = self.shared.sync(member.name, pdir, recorded)
            conn.execute(participants.update().where(
                participants.c.participant_id == turn["participant_id"]).values(
                conflicts=[c.as_dict() for c in synced.conflicts]))
        new = [c for c in synced.conflicts if c.path not in {r.path for r in recorded}]
        if new:
            self.ledger.record_event(self.run_id, self.host_path, "conflict", member.name,
                                     at_step="sync",
                                     paths=[{"path": c.path, "kind": c.kind} for c in new])
        text = flow_framing(member.name, self.leader, sorted(self.members),
                            self.tools_for(member))
        lines = conflict_lines(list(synced.conflicts))
        if lines:
            text += "\n\n" + "\n".join(lines)
        if batch:
            return text + "\n\n" + render_batch(batch, team=True)
        return text + ("\n\n[Temper] No new messages: carry on with your part, or call idle "
                       "if nothing is yours right now.")

    def request_extras(self, turn: dict) -> dict:
        """Wire the running turn's fenced inbox and tool counts (Part B, owner part 2/3)."""
        from temper_ai.pi_agent.turn import render_handed

        def inbox() -> list:
            return [{"seq": m["seq"], "text": render_handed(m)}
                    for m in self.ledger.hand_in(turn["turn_id"], turn["epoch"])]

        def on_tools(counts: dict[str, int]) -> None:
            self.ledger.turn_tools(turn["turn_id"], turn["epoch"], counts)

        def on_usage(usage: dict[str, int | float]) -> None:
            self.ledger.turn_usage(turn["turn_id"], turn["epoch"], usage)

        return {"inbox": inbox, "on_tools": on_tools, "on_usage": on_usage}

    @staticmethod
    def _act_args(op: str, payload: dict) -> dict:
        limit, name = (MAX_SUMMARY, "summary") if op == DONE else (MAX_NOTE, "note")
        value = payload.get(name)
        if value is None and op != DONE:
            return {name: None}
        if not isinstance(value, str) or not value.strip():
            raise Refusal(route_model.INVALID_MESSAGE, f"{name} must be a non-empty string")
        if len(value) > limit:
            raise Refusal(route_model.INVALID_MESSAGE, f"{name} must be at most {limit} characters")
        return {name: value.strip()}

    def _allow(self, conn: Any, binding: Binding, op: str, args: dict,
               mine: list[dict]) -> str:
        if any(a["op"] == op for a in mine):
            raise Refusal(NOT_NOW, f"{op} was already called in this turn")
        if op == SHARE:
            return ("Recorded. When this turn has finished, Temper merges your copy into the "
                    "team's shared version and tells you about any conflict.")
        if op == IDLE:
            return ("Recorded. After this turn you rest until a message reaches you; a "
                    "message that already reached you starts your next turn at once.")
        if binding.member != self.leader:
            raise Refusal(route_model.NOT_AUTHORIZED, f"only the leader ({self.leader}) can say "
                                                      "done")
        open_closing = conn.execute(sa.select(waits.c.subject).where(
            waits.c.run_id == self.run_id, waits.c.host_path == self.host_path,
            waits.c.kind == "closing", waits.c.state == "open")).scalars().all()
        if any((s or {}).get("stage") == "finishing" for s in open_closing):
            raise Refusal(NOT_NOW, "the team is already finishing on an earlier done")
        return ("Recorded. When this turn has finished, Temper shares your copy, lets the "
                "running turns finish and counts done only if nothing new reached you and "
                "nobody shared after this call; otherwise you are told why.")

    # --- carrying out the tools -------------------------------------------------------------

    def carry_out(self) -> None:
        """Carry out, once and in order, every team-tool call whose turn has finished; a
        call of a turn that failed, was retried or cancelled is void. A turn still running
        holds back only its own member's later calls."""
        while True:
            act = self._next_flow_act()
            if act is None:
                return
            state = act["turn_state"]
            if state in ("failed", "superseded", "cancelled"):
                self._settle_act(act, "void", {"void": f"its turn {state}"})
                continue
            getattr(self, f"_carry_{act['op']}")(act)

    def _next_flow_act(self) -> dict | None:
        with _LOCK, self.ledger.engine.connect() as conn:
            rows = conn.execute(sa.select(acts, turns.c.state.label("turn_state")).join(
                turns, turns.c.turn_id == acts.c.turn_id).where(
                acts.c.run_id == self.run_id, acts.c.host_path == self.host_path,
                acts.c.state == "recorded").order_by(acts.c.seq)).mappings().all()
        blocked: set[str] = set()
        for row in rows:
            if row["participant_id"] in blocked:
                continue
            if row["turn_state"] in ("completed", "accepted", "failed", "superseded",
                                     "cancelled"):
                return dict(row)
            blocked.add(row["participant_id"])
        return None

    def _share(self, member: str, act_id: str, note: str | None) -> dict:
        """Merge ``member``'s copy into the shared version (after its turn has finished) and
        record the outcome: a version record and a ``share`` event, or a notice to the member
        naming the conflicts."""
        rows = self._member_rows()
        row = rows.get(member)
        if row is None:
            raise TeamFailure(f"{member} has no conversation")
        recorded = [Conflict.from_dict(c) for c in row.get("conflicts") or []]
        try:
            with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
                got = self.shared.share(member, self._pdir(row), recorded, note)
                conn.execute(participants.update().where(
                    participants.c.participant_id == row["participant_id"]).values(
                    conflicts=[c.as_dict() for c in got.conflicts]))
                if got.status in ("conflict", "refused"):
                    self.ledger.post(self.run_id, self.host_path, member, got.text,
                                     sender="temper", sender_kind="temper", kind="notice",
                                     dedupe_key=f"{self.run_id}:{self.host_path}:share:{act_id}",
                                     conn=conn)
                    self.ledger._event(conn, self.run_id, self.host_path, "share_refused",
                                       member, act_id=act_id, status=got.status,
                                       paths=[c.path for c in got.conflicts])
        except VersionError as exc:
            raise TeamFailure(f"{member}'s share could not be carried out: {exc}") from exc
        result: dict[str, Any] = {"status": got.status, "text": got.text}
        if got.version is not None:
            v = got.version
            result["version"] = v.as_dict()
            try:
                made = team_versions.build(self.project, member, v.commit)
                made["note"] = made.get("note") or v.note
            except Exception:  # noqa: BLE001 - the share stands; its record says why it's bare
                logger.warning("pi team: a shared version's record could not be made",
                               exc_info=True)
                made = {"commit_sha": v.commit, "files": [], "diff": "", "truncated": False,
                        "note": "the version's files could not be read for its record"}
            with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
                team_versions.store(conn, run_id=self.run_id, host_path=self.host_path,
                                    kind="share", record=made, act_id=act_id, member=member)
                self.ledger._event(conn, self.run_id, self.host_path, "share", member,
                                   act_id=act_id, version_no=v.version_no, commit=v.commit,
                                   note=v.note, files_changed=v.files_changed,
                                   files_total=v.files_total)
        return result

    def _carry_share(self, act: dict) -> None:
        result = self._share(act["member"], act["act_id"], (act["args"] or {}).get("note"))
        self._settle_act(act, "carried_out", result)

    def _carry_idle(self, act: dict) -> None:
        # The member's rest itself was set when its turn finished (finish_turn's rest).
        self._settle_act(act, "carried_out", {"rested": True})

    def _carry_done(self, act: dict) -> None:
        for w in self._closing_waits():
            if (w["subject"] or {}).get("stage") == "lone":
                self.ledger.decide_wait(w["wait_id"], {"answer": "done_again"}, self.attempt_id)
        result = self._share(act["member"], act["act_id"], "done")
        summary = (act["args"] or {}).get("summary")
        subject = {"label": "closing", "header": "closing", "stage": "finishing",
                   "act_id": act["act_id"], "turn_id": act["turn_id"], "summary": summary,
                   "began_at": act["created_at"],  # the done call, not its turn's start
                   "share_status": result["status"], "share_text": result["text"],
                   "question": "The leader said done: the team is finishing."}
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            self.ledger._open_wait(conn, self.run_id, self.host_path, "closing", subject,
                                   self.attempt_id)
            self.ledger._event(conn, self.run_id, self.host_path, "closing", act["member"],
                               act_id=act["act_id"], summary=summary)
        self._settle_act(act, "carried_out", {"closing": True, **result})

    # --- the closing (F5 + R2) ---------------------------------------------------------------

    def _closing_waits(self) -> list[dict]:
        return [dict(w) for w in self._rows(waits, waits.c.kind == "closing",
                                            waits.c.state == "open", order=waits.c.opened_at)]

    def _closing(self) -> dict | None:
        found = self._closing_waits()
        return found[0] if found else None

    def done_refusals(self, wait: dict) -> list[dict]:
        """Why the leader's done doesn't count (empty: it counts). Checked once nothing runs."""
        s = wait["subject"] or {}
        began = str(s.get("began_at") or "")
        out: list[dict] = []
        if s.get("share_status") not in SHARE_OK:
            out.append({"reason": "share", "detail": s.get("share_text") or "your share failed"})
        lead = self._member_rows().get(self.leader) or {}
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path):
            different = self.shared.unshared(self.leader, self._pdir(lead))
        if different:
            out.append({"reason": "copy", "detail": different})
        late = [m for m in self._rows(messages, messages.c.to_participant
                                      == lead.get("participant_id"))
                if m["sender_kind"] != "temper" and m["state"] in ("pending", "consumed")
                and str(m["released_at"] or "") > began]
        if late:
            out.append({"reason": "message", "detail": "messages reached you after your done "
                        "call: " + ", ".join(sorted({str(m["sender"]) for m in late}))})
        later = [v for v in self.shared.versions()
                 if v.version_no > 0 and v.by != self.leader and str(v.at) > began]
        if later:
            out.append({"reason": "share_after", "detail": "shared after your done call: "
                        + ", ".join(sorted({str(v.by) for v in later}))})
        held = [w for w in self.ledger.open_waits(self.run_id, self.host_path)
                if (w["subject"] or {}).get("participant_id")]
        failed = [r["member"] for r in self._member_rows().values()
                  if r["state"] in ("failed", "uncertain")]
        if held or failed:
            names = sorted({str((w["subject"] or {}).get("member")) for w in held} | set(failed))
            out.append({"reason": "held", "detail": "these members are held or failed: "
                        + ", ".join(names)})
        return out

    def _settle_closing(self, wait: dict) -> bool:
        """With nothing running: count done, or tell the leader why not and give it one
        more turn on its own (stage ``lone``); a lone stage ends once the leader's turn did."""
        s = wait["subject"] or {}
        if s.get("stage") == "lone":
            started = [t for t in self._rows(turns, turns.c.participant_id
                                             == self._leader_pid())
                       if str(t["started_at"] or "") >= str(wait["opened_at"] or "")]
            if started or not self._leader_can_go():
                self.ledger.decide_wait(wait["wait_id"], {"answer": "carried_on"},
                                        self.attempt_id)
                return True
            return False  # let _fill give the leader its lone turn, not a busy loop
        reasons = self.done_refusals(wait)
        if not reasons:
            self.ledger.decide_wait(wait["wait_id"], {"answer": "done"}, self.attempt_id)
            head = self.shared.head()
            self.ledger.record_event(self.run_id, self.host_path, "done", self.leader,
                                     summary=s.get("summary"), version_no=head.version_no,
                                     commit=head.commit)
            self.end("team_done")
            return True
        text = ("Your done did not count yet: " + "; ".join(r["detail"] for r in reasons)
                + ". Look at what is new, then share and say done again when the work is "
                  "finished.")
        self.ledger.decide_wait(wait["wait_id"], {"answer": "refused", "reasons": reasons},
                                self.attempt_id, deliveries=[(self.leader, text)])
        self.ledger.record_event(self.run_id, self.host_path, "done_refused", self.leader,
                                 reasons=reasons)
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            self.ledger._open_wait(conn, self.run_id, self.host_path, "closing",
                                   {"label": "closing", "header": "closing", "stage": "lone",
                                    "after": s.get("act_id"), "reasons": reasons,
                                    "question": "The leader's done did not count yet."},
                                   self.attempt_id)
        return True

    def _leader_pid(self) -> str | None:
        return (self._member_rows().get(self.leader) or {}).get("participant_id")

    def _leader_can_go(self) -> bool:
        row = self._member_rows().get(self.leader) or {}
        if row.get("state") != "idle" or row.get("idle_reason"):
            pending = self._rows(messages, messages.c.to_participant == row.get("participant_id"),
                                 messages.c.state == "pending")
            return bool(pending) and row.get("state") == "idle"
        return True

    def done_record(self) -> dict:
        """Temper's record of done (F5): the shared version, the leader's summary, every
        share in order, turns per member and the whole spend."""
        decided = [w for w in self._rows(waits, waits.c.kind == "closing",
                                         waits.c.state == "decided", order=waits.c.decided_at)
                   if (w["decision"] or {}).get("answer") == "done"]
        s = (decided[-1]["subject"] if decided else None) or {}
        head = self.shared.head()
        commit = head.commit if head is not None else None
        files: dict = {}
        if commit:
            try:
                files = self.project.files(self.leader, commit)[0]
            except Exception:  # noqa: BLE001 - the record stands without its file list
                logger.warning("pi team: the done version's files could not be read",
                               exc_info=True)
        return {
            "decision": "done",
            "kind": "flow",
            "summary": s.get("summary"),
            "version": {"commit": commit, "files": files},
            "shares": [{"who": v.by, "commit": v.commit, "order": v.version_no, "note": v.note}
                       for v in self.shared.versions() if v.version_no > 0],
            "turns": {r["member"]: int(r["turns"] or 0) for r in self._member_rows().values()},
            "cost": self.usage(),
            "project": self.project.record() if self.project.record_path.exists() else {},
            "leader": self.leader,
            "branch": None,
        }

    # --- how a turn ended ---------------------------------------------------------------------

    def settle(self, turn: dict, name: str, cfg: dict, report: Any, worker: dict,
               agent_event_id: str) -> StepResult:
        saved = self.ledger.turn(turn["turn_id"]) or {}
        known = (saved.get("worker") or {}).get("usage") or {}
        if known:  # a cut-off must not replace already recorded spend with an empty receipt
            usage = worker.get("usage") or {}
            worker = {**worker, "usage": {
                "cost_usd": max(float(known.get("cost_usd") or 0),
                                float(usage.get("cost_usd") or 0)),
                "total_tokens": max(int(known.get("total_tokens") or 0),
                                    int(usage.get("total_tokens") or 0)),
                "llm_calls": max(int(known.get("llm_calls") or 0),
                                 int(usage.get("llm_calls") or 0)),
            }}
        gone = bool(worker.get("container_removed"))
        handed = getattr(report, "handed_in", None) or {}
        if gone:
            unconfirmed = set(handed.get("unconfirmed") or []) | set(handed.get("refused") or [])
            self.ledger.unhand(turn["turn_id"], sorted(unconfirmed))
        worker = {**worker, "handed_in": handed} if handed else worker
        halting = self.halt.is_set()
        error = str(report.error or "")
        trouble = call_trouble(report.outcome, report.error) if report.state != "completed" else None
        if report.state != "completed" and gone and not halting:
            ended_by = ("time_limit" if error.startswith("turn_timeout")
                        else "call_cap" if int(worker.get("calls_capped") or 0) > 0 else None)
            if ended_by and trouble is None:  # R1: a normal end, not an account hold/refusal
                report.state = "completed"
                worker = {**worker, "ended_by": ended_by}
        if report.state == "completed":
            return self._finish(turn, name, report, worker, agent_event_id)
        if report.state == "uncertain" and trouble is not None:
            # FLOW still knows how the account stopped the call even when the transport
            # cut off too. Ordinary step/round-team recovery mapping stays unchanged.
            report.state = "failed"
        ending = turn_ending(report, self.account_slot, self.account.get("room"))
        if ending.kind == "refused" or not gone:
            return super().settle(turn, name, cfg, report, worker, agent_event_id)
        if halting:
            if self.halt.why == "drain" and not self.halt.run_cancelled():
                return self._requeue(turn, name, report, worker, agent_event_id, "drain")
            return super().settle(turn, name, cfg, report, worker, agent_event_id)
        details = ending.details or {}
        if ending.kind == "held" and details.get("limit"):
            step = self._requeue(turn, name, report, worker, agent_event_id, "limit")
            if step.kind == "requeued":
                self._open_limit(details, name, turn)
            return step
        if not self.ledger.retried_before(turn):
            return self._requeue(turn, name, report, worker, agent_event_id, "retry")
        step = super().settle(turn, name, cfg, report, worker, agent_event_id)
        if step.kind == "failed":
            self.ledger.open_recovery_for_failed(self.run_id, self.host_path, self.attempt_id)
        return step

    def _finish(self, turn: dict, name: str, report: Any, worker: dict,
                agent_event_id: str) -> StepResult:
        idle = [a for a in self._rows(acts, acts.c.turn_id == turn["turn_id"],
                                      acts.c.op == IDLE, acts.c.state != "void")]
        tool_calls = int(getattr(report.outcome, "tool_calls", 0) or 0)
        rest = (("idle", (idle[0]["args"] or {}).get("note")) if idle
                else ("no_tool", None) if report.outcome is not None and tool_calls == 0
                else None)
        worker = {**worker, "tool_calls": tool_calls if report.outcome is not None else None}
        res = self.ledger.finish_turn(turn["turn_id"], epoch=turn["epoch"],
                                      output=report.output,
                                      model_call_ids=report.model_call_ids, worker=worker,
                                      ask_owner=None, attempt_id=self.attempt_id, rest=rest)
        if res is None:
            return StepResult("lost", member=name, turn=turn)
        return StepResult("completed", member=name, turn=self.ledger.turn(turn["turn_id"]),
                          released=res.get("released") or {})

    def _requeue(self, turn: dict, name: str, report: Any, worker: dict,
                 agent_event_id: str, why: str) -> StepResult:
        error = f"{name} turn {turn['turn_no']}: {report.error or why}"
        if not self.ledger.requeue_turn(turn["turn_id"], epoch=turn["epoch"], error=error,
                                        model_call_ids=report.model_call_ids, worker=worker,
                                        why=why):
            return StepResult("lost", member=name, turn=turn)
        self._close_turn_event({**turn, "agent_event_id": agent_event_id, "member": name},
                               f"{why}: {error}")
        return StepResult("requeued", member=name, turn=turn, error=error)

    def _open_limit(self, details: dict, member: str, turn: dict) -> None:
        resume = limit_resume(details)
        weekly = resume["kind"] != FIVE_HOUR
        question = (f"The account's usage limit stopped {member}'s turn "
                    f"({details.get('limit') or 'limit'}). "
                    + ("The team waits, holding its work, and asks you before it restarts."
                       if weekly else
                       f"The team checks again at {resume['resumes_at']} and carries on by "
                       "itself only after fresh usage shows room."))
        subject = {**details, **resume, "label": "usage-limit", "header": "usage-limit",
                   "member": member, "turn_no": turn["turn_no"], "question": question,
                   "reply_hint": "Reply 'restart' or 'stop'.", "options": list(LIMIT_OPTIONS)}
        self.ledger.open_wait_unless_open(self.run_id, self.host_path, "limit", subject,
                                          self.attempt_id)

    def _refresh_limit(self, wait: dict) -> dict | None:
        """Verify the held account with the helper, preserving the wait and the kept slot.
        No login refresh, room writer, slot choice or model call is involved."""
        subject = wait["subject"] or {}
        recorded = subject.get("account_slot")
        if recorded is not None and recorded != self.account_slot:
            reading = {"status": "unavailable", "reason": "account_mismatch"}
        else:
            reading = host_helper.usage(getattr(self.box, "host_helper_socket", ""),
                                         self.account_slot)
        updated = limit_after_check(subject, reading)
        slot = self.account_slot or "unknown"
        if limit_restart_ready(updated):
            updated["question"] = (
                f"Account {slot}'s fresh usage check shows room again. "
                + ("The team keeps its work and waits for your answer before restarting."
                   if updated.get("kind") != FIVE_HOUR else
                   "The team carries on by itself."))
        else:
            state = ("is still at its usage limit" if reading.get("status") == "ok" else
                     "could not be checked; this is not proof that its usage limit reset")
            updated["question"] = (
                f"Account {slot} {state}. The team keeps its work and waits. "
                f"Next usage check: {updated['resumes_at']}. "
                + ("When usage shows room, it asks you before restarting."
                   if updated.get("kind") != FIVE_HOUR else
                   "It carries on by itself only after fresh usage shows room."))
        return self.ledger.update_limit_wait(wait["wait_id"], subject, updated)

    # --- owner answers ------------------------------------------------------------------------

    def apply(self, wait: dict, answer: Any) -> None:
        kind = wait["kind"]
        if kind == "recovery":
            word, rest = owner_words(answer)
            tid = (wait["subject"] or {}).get("turn_id")
            turn = self.ledger.turn(tid) if tid else None
            if word in ("retry", "accept") and turn is not None:
                self._confirm_turn_box_gone(turn)  # C1 also fences an owner's manual retry
            # A stop is recorded here; the loop drains other turns before ending the team.
            self.decide(wait, f"{word} {rest}".strip(), words=rest, who=answer_who(answer))
            return
        if kind not in ("pause", "limit"):
            super().apply(wait, answer)
            return
        wid, subject = wait["wait_id"], wait["subject"] or {}
        text = str(getattr(answer, "text", "") or "")
        base = {"text_sha256": hashlib.sha256(text.encode()).hexdigest(), **answer_who(answer)}
        word, rest = owner_words(answer)
        if kind == "pause":
            at = subject.get("at_usd")
            base = {"at_usd": at, "spend_usd": self.usage()["cost_usd"], **base}
            if word == "continue":
                self.ledger.decide_wait(wid, {"answer": "continue", **base}, self.attempt_id)
            elif word == "guide" and rest:
                self.ledger.decide_wait(
                    wid, {"answer": "guide", **base}, self.attempt_id,
                    deliveries=[(self.leader, f"Guidance from the owner at the check-in at "
                                              f"${float(at or 0):g}: {rest}")])
            elif word == "stop":
                self.ledger.decide_wait(wid, {"answer": "stop", **base,
                                              "words": stop_words(rest)}, self.attempt_id)
            else:  # never a continue: the owner is asked again
                self.ledger.decide_wait(wid, {"answer": "invalid", **base}, self.attempt_id,
                                        reask=subject)
            return
        if word == "restart":
            # An answer may have waited a long time. Re-check before clearing the hold,
            # including after a parked run is resumed; an old ready row is not permission.
            checked = self._refresh_limit(wait)
            if checked is None or self.halt.is_set():
                return
            current = checked["subject"] or {}
            if limit_restart_ready(current):
                self.ledger.decide_wait(wid, {"answer": "restart", **base,
                                              "usage_checked_at": current.get("usage_checked_at")},
                                        self.attempt_id)
            else:
                self.ledger.decide_wait(wid, {"answer": "restart_deferred", **base},
                                        self.attempt_id, reask=current)
        elif word == "stop":
            self.ledger.decide_wait(wid, {"answer": "stop", **base, "words": stop_words(rest)},
                                    self.attempt_id)
        else:
            self.ledger.decide_wait(wid, {"answer": "invalid", **base}, self.attempt_id,
                                    reask=subject)

    def _check_in(self) -> None:
        """Open the check-in once the team's whole spend (R4: failed, cut-off and retried
        turns included) reaches the next step of ``pause_every_usd`` past the last answer."""
        spend = float(self.usage()["cost_usd"])
        base = 0.0
        for w in self._rows(waits, waits.c.kind == "pause", waits.c.state == "decided"):
            if (w["decision"] or {}).get("answer") in ("continue", "guide"):
                base = max(base, float((w["decision"] or {}).get("spend_usd")
                                       or (w["subject"] or {}).get("at_usd") or 0.0))
        due = round(base + self.pause_every, 2)
        if spend < due:
            return
        subject = {"label": f"pause-at-${due:g}", "header": f"pause-at-${due:g}",
                   "at_usd": due, "spend_usd": round(spend, 4),
                   "question": (f"The team has spent ${spend:.2f} (check-in at ${due:g}). "
                                "Nothing new starts; running turns finish."),
                   "reply_hint": (f"Reply 'continue', 'guide: <what to tell {self.leader}>', "
                                  "or 'stop'."),
                   "options": list(PAUSE_OPTIONS)}
        if self._open_wait("pause", subject, only_if_none_of_kind=True) is not None:
            self.ledger.record_event(self.run_id, self.host_path, "check_in", None,
                                     at_usd=due, spend_usd=round(spend, 4))

    # --- the loop -----------------------------------------------------------------------------

    def _confirm_turn_box_gone(self, turn: dict) -> None:
        """C1: a kill request alone never permits another writer, or a successful Stop."""
        if ((turn.get("worker") or {}).get("container_removed")
                or (turn.get("box_stop") or {}).get("confirmed") or not turn.get("box_name")):
            return
        result = (type(self).stop_box or stop_leftover_box)(turn["box_name"])
        self.ledger._fenced(turn["turn_id"], turn["epoch"], box_stop=result)
        if not result.get("confirmed"):
            raise TeamFailure(f"cannot confirm {turn['box_name']} stopped; its claim stays held")

    def end(self, reason: str) -> dict:
        # Do not fence live receipt writers out early: their last calls still count (R4).
        # In particular an account refusal or a member's recovery Stop can arrive while
        # other members are in flight. Halt them and let the loop join them first.
        if getattr(self, "_inflight", None):
            self._pending_end = reason
            self.halt.set(reason)
            return {"deferred": True}
        for turn in self._rows(turns):
            self._confirm_turn_box_gone(turn)
        self._pending_end = None
        out = super().end(reason)
        self.ledger.record_event(self.run_id, self.host_path, "ended", None, reason=reason)
        return out

    def _drive(self, context: Any) -> Outcome:
        self.ledger.record_event(self.run_id, self.host_path, "driver_started", None)
        pool = cf.ThreadPoolExecutor(max_workers=self.cap, thread_name_prefix="pi-flow")
        running: dict[cf.Future, str] = {}
        self._inflight = running
        self._pending_end = None
        try:
            return self._loop(context, pool, running)
        finally:
            if running:
                self.halt.set("end")
                cf.wait(list(running))
            running.clear()
            pool.shutdown(wait=True)
            if self._pending_end is not None:
                self.end(self._pending_end)
            reason = self._end_reason()
            if reason:
                from temper_ai.stage.step_waits import finish_usage_timer

                for wait in self._rows(waits, waits.c.kind == "limit"):
                    finish_usage_timer(context, wait["wait_id"], cancelled=reason != "team_done")

    def _gather(self, running: dict[cf.Future, str]) -> Outcome | None:
        for fut in [f for f in running if f.done()]:
            name = running.pop(fut)
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001 - a turn that broke stops the team
                logger.exception("pi team: %s's turn broke", name)
                self.halt.set("failed")
                return Outcome("failed", f"{name}'s turn could not be run: {exc}")
            if result.kind == "refused":
                self.halt.set("refused")
                self.end(ACCOUNT_REFUSED)
            elif result.kind == "lost":
                self.halt.set("lost")
                return Outcome("failed", "another attempt of this run is running the team: "
                                         "refusing to run it twice")
        return None

    def _ended(self) -> Outcome | None:
        reason = self._end_reason()
        if reason is None:
            return None
        if reason == "team_done":
            return Outcome("done", record=self.done_record())
        if reason == "team_stopped":
            return Outcome("stopped", self.stopped() or "the team was stopped")
        if reason == "run_cancelled":
            return Outcome("cancelled", "the run was cancelled")
        if reason == ACCOUNT_REFUSED:
            return Outcome("failed", refusal_problem(self.account_slot))
        return Outcome("failed", f"the team ended ({reason}) before it was done")

    def _loop(self, context: Any, pool: cf.ThreadPoolExecutor,
              running: dict[cf.Future, str]) -> Outcome:
        while True:
            self.show()
            broke = self._gather(running)
            if broke is not None:
                return broke
            if self._pending_end is not None:
                if running:
                    self._tick(running)
                    continue
                self.end(self._pending_end)
            ended = self._ended()
            if ended is not None:
                if running:
                    self.halt.set("end")
                    self._tick(running)
                    continue
                return ended
            if self.halt.run_cancelled():
                self.halt.set("cancel")
                if running:
                    self._tick(running)
                    continue
                self.end("run_cancelled")
                continue
            if not running and not self.stopped() and self.open_settings_wait():
                wait = next(w for w in self.ledger.open_waits(self.run_id, self.host_path)
                            if w["kind"] == "settings")
                answer = self.ask(context, wait)
                if answer is not None:
                    self.apply(wait, answer)
                continue
            try:
                self.carry_out()
            except TeamFailure as exc:
                self.halt.set("failed")
                if running:
                    cf.wait(list(running))
                    running.clear()
                return Outcome("failed", str(exc))
            if self.stopped():
                self.halt.set("stop")
                if running:
                    self._tick(running)
                    continue
                self.end("team_stopped")
                continue
            closing = self._closing()
            if closing is not None and not running and self._settle_closing(closing):
                continue
            self._check_in()
            if self._limit_due(context, running):
                continue
            if self._answers(context, running):
                continue
            if draining():
                self._halt_for_draining()
                if running:
                    self._tick(running)
                    continue
                leave_if_draining(f"team {self.host_path}")
            if self.halt.why == "drain":  # the lane's stop was called off: carry on
                self.halt.why = None
                self.halt.own.clear()
                self.ledger.record_event(self.run_id, self.host_path, "driver_started", None)
            only = None
            if closing is not None:
                stage = (closing["subject"] or {}).get("stage")
                only = self.leader if stage == "lone" else ""
            started = self._fill(pool, running, only)
            if started or running:
                if not started:
                    self._tick(running)
                continue
            if self._park(context):
                continue
            self._open_stalled()

    def _halt_for_draining(self) -> None:
        if self.halt.why != "drain":
            self.ledger.record_event(self.run_id, self.host_path, "draining", None)
        self.halt.set("drain")

    def _tick(self, running: dict[cf.Future, str]) -> None:
        if running:
            cf.wait(list(running), timeout=TICK_S, return_when=cf.FIRST_COMPLETED)

    def _fill(self, pool: cf.ThreadPoolExecutor, running: dict[cf.Future, str],
              only: str | None) -> bool:
        """Start every turn that can start now, up to the cap. ``only``: the one member that
        may start ("" = none: the team is finishing)."""
        if only == "":
            return False
        started = False
        while len(running) < self.cap:
            got = self.ledger.claim_turn(self.run_id, self.host_path, attempt_id=self.attempt_id,
                                         flow=True, max_parallel=self.cap, only=only)
            if got is None:
                break
            turn, batch = got
            part = self.ledger.participant(turn["participant_id"]) or {}
            running[pool.submit(self._run, turn, batch)] = str(part.get("member") or "unknown member")
            started = True
        return started

    def _limit_due(self, context: Any, running: dict[cf.Future, str]) -> bool:
        """Finish running turns, then park until the next fresh usage check, no worker held.
        Only verified available usage permits a 5-hour auto-resume or a weekly owner
        question. An unavailable or still-limited reading keeps the hold without expiry.
        True while no turn may start."""
        from temper_ai.stage.step_waits import finish_usage_timer, park_until

        for w in self.ledger.open_waits(self.run_id, self.host_path):
            if w["kind"] != "limit":
                continue
            s = w["subject"] or {}
            if running:
                self._tick(running)
                return True
            if draining():
                self._halt_for_draining()
                leave_if_draining(f"team {self.host_path}")
            if limit_ready(s):
                finish_usage_timer(context, w["wait_id"])
                checked = self._refresh_limit(w)
                if checked is None or self.halt.is_set():
                    return True
                s = checked["subject"] or {}
                if limit_restart_ready(s):
                    if s.get("kind") != FIVE_HOUR:
                        return False  # verified room: now (not earlier) ask the owner
                    self.ledger.decide_wait(
                        w["wait_id"], {"answer": "resumed", "by": "temper",
                                      "usage_checked_at": s.get("usage_checked_at")},
                        self.attempt_id)
                    return True
            park_until(context, w["wait_id"], resumes_at=str(s.get("resumes_at")))
            self.halt.own.wait(TICK_S * 5)  # only if this context could not save a checkpoint
            return True
        return False

    def _askable(self) -> list[dict]:
        return [w for w in self.ledger.open_waits(self.run_id, self.host_path)
                if w["kind"] not in ("closing", "settings")
                and not (w["kind"] == "limit" and
                         ((w["subject"] or {}).get("kind") == FIVE_HOUR
                          or not limit_restart_ready(w["subject"] or {})))]

    def _answers(self, context: Any, running: dict[cf.Future, str]) -> bool:
        """While turns run, pick up the owner's answers without parking (every few
        seconds). True when an answer was applied."""
        if not running or time.monotonic() - self._last_poll < POLL_ASK_S:
            return False
        self._last_poll = time.monotonic()
        applied = False
        for wait in self._askable():
            if wait["kind"] in ("pause", "stalled", "limit"):
                continue  # team-level questions wait until all running turns finish
            try:
                answer = self.ask(context, wait, hold=False)
            except CancellationError:
                raise
            if answer is not None:
                self.apply(wait, answer)
                applied = True
        return applied

    def _park(self, context: Any) -> bool:
        """Nothing runs and nothing can start: ask the owner the first open question (this
        parks the run when unanswered). False when there is none."""
        found = self._askable()
        if not found:
            return False
        wait = found[0]
        answer = self.ask(context, wait)
        if answer is not None:
            self.apply(wait, answer)
        return True
