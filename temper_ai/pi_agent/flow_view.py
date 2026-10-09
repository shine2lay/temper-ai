"""The Team page's read of a free-flowing team (FLOW E5 + E6; contract
company-lab FLOW/api-fields.md): the run at a glance (phase, spend against the next check-in,
what needs the owner, each member's state and what it is on, the shared version and its share
history) and the team's event feed with a cursor.

Everything comes from the team's ledger tables and its event feed (``pi_team_events``);
nothing here writes, and nothing is guessed: a value the tables don't hold is ``None``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temper_ai.pi_agent.accounts import FIVE_HOUR, limit_kind, limit_restart_ready
from temper_ai.pi_agent.ledger import events, first_line, messages, turns, waits
from temper_ai.pi_agent.settings_wait import SETTINGS
from temper_ai.pi_agent.team_leader import WAIT_KIND_SHOWN, _at
from temper_ai.pi_agent.team_view import (
    RUN_ENDED,
    TeamReader,
    utc_moment,
    utc_text,
    wait_words,
)
from temper_ai.shared.clock import utcnow

FLOW = "flow"
ROUNDS = "rounds"
#: First lines the page shows are cut here (the full text: the message read route).
TEXT = 160
#: Share history kept in the run reply (newest first); the feed has them all.
SHARES_SHOWN = 20
#: Messages counted in ``links``: released in the last hour.
LINKS_WINDOW = timedelta(hours=1)
#: A message is released once it left ``held``.
RELEASED = ("pending", "consumed", "undelivered")
#: The engine's rest reasons, as the page names them.
IDLE_REASONS = {"start": "start", "idle": "idle_call", "no_tool": "no_tool_call"}
#: How a ledger turn ending is named on the page.
TURN_ENDED = {"completed": "completed", "failed": "failed", "uncertain": "held",
              "retry": "failed", "limit": "cancelled", "drain": "cancelled",
              "cancelled": "cancelled"}
#: The leader's done refused, by reason code (the engine's -> the page's).
REFUSAL_CODES = {"share": "conflict", "message": "new_messages", "share_after": "new_shares",
                 "held": "open_waits", "copy": "copy_differs"}
#: The phase while a team-level wait of that kind is open.
WAIT_PHASE = {"closing": "closing", SETTINGS: "settings", "limit": "limit", "pause": "check_in",
              "stalled": "quiet"}
PHASE_WORDS = {
    "starting": "Starting: the leader has the goal",
    "closing": "Finishing up: the leader said done",
    "quiet": "Everyone is idle",
    "settings": "Settings changed: go on or stop?",
    "done": "Done",
    "stopped": "Stopped by the owner",
    "interrupted": "Interrupted",
}


def run_kind(record: dict, reviews: list[dict]) -> str:
    """``rounds`` for a team that ran in review rounds (its trial set ``pause_after_rounds``,
    or it has review records), else ``flow``."""
    return ROUNDS if record.get("pause_after_rounds") is not None or reviews else FLOW


def _short(commit: str | None) -> str | None:
    return commit[:12] if commit else None


def _cut(text: Any) -> str | None:
    return first_line(str(text), TEXT) if text else None


class FlowRead:
    """One read of a free-flowing team's rows, shared by every part of the reply."""

    def __init__(self, reader: TeamReader, record: dict):
        self.reader = reader
        self.ledger = reader.ledger
        self.record = record
        self.now = utcnow()
        self.parts = reader._member_rows()
        self.by_pid = {p["participant_id"]: p for p in self.parts.values()}
        self.turns = reader._rows(turns, order=turns.c.started_at)
        self.waits = reader._rows(waits, order=waits.c.opened_at)
        self.open = [w for w in self.waits if w["state"] == "open"]
        self.msgs = reader._rows(messages, order=messages.c.seq)
        self.events = reader._rows(events, order=events.c.seq)
        self.cursor = self.events[-1]["seq"] if self.events else 0

    # --- money ---------------------------------------------------------------------------

    def spend(self) -> dict:
        cost = self.reader.usage()["cost_usd"]
        every = float(self.record.get("pause_every_usd") or 100.0)
        pauses = [w for w in self.waits if w["kind"] == "pause"]
        last = max((float((w["decision"] or {}).get("spend_usd")
                          or (w["subject"] or {}).get("at_usd") or 0.0) for w in pauses
                    if w["state"] == "decided"
                    and (w["decision"] or {}).get("answer") in ("continue", "guide")),
                   default=0.0)
        return {"cost_usd": cost, "pause_every_usd": every, "last_check_in_usd": last,
                "next_check_in_usd": round(last + every, 6),
                "since_check_in_usd": round(cost - last, 6), "check_ins": len(pauses)}

    # --- waits ---------------------------------------------------------------------------

    @staticmethod
    def owner_answers(w: dict) -> bool:
        """Whether the owner can answer this open wait now (the closing check and a 5-hour
        limit are Temper's own: the team carries on by itself)."""
        if w["kind"] == "closing":
            return False
        if w["kind"] == "limit":
            s = w["subject"] or {}
            return (s.get("kind") or limit_kind(s.get("limit"))) != FIVE_HOUR \
                and limit_restart_ready(s)
        return True

    def you(self) -> dict:
        mine = [w for w in self.open if self.owner_answers(w)]
        settings = [w for w in mine if w["kind"] == SETTINGS]
        if settings:
            mine = settings  # changed pins are answered before earlier member/check-in waits
        first = None
        if mine:
            w, s = mine[0], mine[0]["subject"] or {}
            first = {"wait_id": w["wait_id"], "kind": WAIT_KIND_SHOWN.get(w["kind"], w["kind"]),
                     "member": s.get("member"), "header": s.get("header") or w["kind"],
                     "words": wait_words(s),
                     "opened_at": _at(w["opened_at"])}
        return {"count": len(mine), "first": first}

    def member_wait(self, pid: str) -> dict | None:
        return next((w for w in self.open
                     if (w["subject"] or {}).get("participant_id") == pid), None)

    # --- members -------------------------------------------------------------------------

    def state_of(self, p: dict) -> str:
        if p["state"] in ("ended", "retired"):
            return "ended"
        if p["state"] == "running":
            return "working"
        if p["state"] == "uncertain" or self.member_wait(p["participant_id"]):
            return "held"
        if p["state"] == "failed":
            return "failed"
        if p.get("idle_reason"):
            return "idle"
        return "ready"

    def _member_events(self, name: str, kind: str) -> list[dict]:
        return [e for e in self.events if e["member"] == name and e["kind"] == kind]

    def member(self, base: dict) -> dict:
        name = base["name"]
        p = self.parts.get(name)
        if p is None:
            return {**base, "state": None, "since": None, "turn_no": None, "on": None,
                    "idle_note": None, "idle_reason": None, "tools_now": None,
                    "ready_messages": 0, "last_sent": None, "last_share": None,
                    "conflicts": [], "wait_id": None, "last_activity_at": None}
        pid = p["participant_id"]
        state = self.state_of(p)
        mine = [t for t in self.turns if t["participant_id"] == pid]
        running = next((t for t in mine if t["state"] == "running"), None)
        wait = self.member_wait(pid)
        since: Any = None
        if state == "working" and running:
            since = running["started_at"]
        elif state == "idle":
            since = p.get("idle_since")
        elif state == "held" and wait:
            since = wait["opened_at"]
        elif mine:
            since = mine[-1]["ended_at"] or mine[-1]["started_at"]
        released = [m for m in self.msgs if m["state"] in RELEASED]
        to_me = [m for m in released if m["to_participant"] == pid]
        sent = [m for m in released if m["sender"] == name and m["sender_kind"] == "member"]
        shares = self._member_events(name, "share")
        on = None
        asked = [m for m in to_me if m["kind"] == "work_request"]
        if asked:
            m = asked[-1]
            on = {"kind": "work_request", "text": _cut(m["body"]), "from": m["sender"],
                  "at": _at(m["created_at"]), "message_id": m["message_id"]}
        elif shares and shares[-1]["data"].get("note"):
            e = shares[-1]
            on = {"kind": "share", "text": _cut(e["data"]["note"]), "from": name,
                  "at": e["at"], "message_id": None}
        elif p.get("idle_note"):
            on = {"kind": "idle", "text": _cut(p["idle_note"]), "from": name,
                  "at": utc_text(p.get("idle_since")), "message_id": None}
        elif name == self.reader.leader:
            goal = next((m for m in to_me if m["kind"] == "goal"), None)
            if goal:
                on = {"kind": "goal", "text": _cut(goal["body"]), "from": "temper",
                      "at": _at(goal["created_at"]), "message_id": goal["message_id"]}
        last_sent = None
        if sent:
            m = sent[-1]
            last_sent = {"to": m["to_member"], "kind": m["kind"], "text": _cut(m["body"]),
                         "at": _at(m["created_at"]), "message_id": m["message_id"]}
            if name == self.reader.leader:
                on = {"kind": "message", "text": last_sent["text"], "to": m["to_member"],
                      "from": name, "at": last_sent["at"], "message_id": m["message_id"]}
        last_share = None
        if shares:
            d = shares[-1]["data"]
            last_share = {"version_no": d.get("version_no"),
                          "commit_short": _short(d.get("commit")), "note": d.get("note"),
                          "at": shares[-1]["at"]}
        activity = [e["at"] for e in self.events if e["member"] == name]
        last_turn = base.get("last_turn")
        if last_turn and mine:
            t = mine[-1]
            prior = next((x for x in mine if x["turn_id"] == t.get("retry_of")), None)
            last_turn = {**last_turn, "retry_of": prior["turn_no"] if prior else None,
                         "ended_by": (t["worker"] or {}).get("ended_by")
                         or ("no_tool_call" if (t["worker"] or {}).get("tool_calls") == 0
                             else None)}
        return {
            **base, "last_turn": last_turn, "state": state, "since": utc_text(since),
            "turn_no": running["turn_no"] if running else None, "on": on,
            "idle_note": p.get("idle_note") if state == "idle" else None,
            "idle_reason": IDLE_REASONS.get(p.get("idle_reason") or "") if state == "idle"
            else None,
            "tools_now": ([{"name": k, "count": v} for k, v in
                           sorted(((running["worker"] or {}).get("tools_now") or {}).items(),
                                  key=lambda item: (-item[1], item[0]))]
                          if running else None),
            "ready_messages": sum(1 for m in to_me if m["state"] == "pending"),
            "last_sent": last_sent, "last_share": last_share,
            "conflicts": [{"path": c.get("path"), "kind": c.get("kind")}
                          for c in p.get("conflicts") or []],
            "wait_id": wait["wait_id"] if wait else None,
            "last_activity_at": max(activity) if activity else None}

    def links(self) -> list[dict]:
        now = self.now
        pairs: dict[tuple[str, str], dict] = {}
        for m in self.msgs:
            at = utc_moment(m["created_at"])
            if (m["state"] not in RELEASED or m["sender_kind"] != "member" or at is None
                    or now - at > LINKS_WINDOW):
                continue
            link = pairs.setdefault((m["sender"], m["to_member"]),
                                    {"from": m["sender"], "to": m["to_member"], "count": 0,
                                     "last_at": None})
            link["count"] += 1
            link["last_at"] = _at(m["created_at"])
        return list(pairs.values())

    # --- the shared version --------------------------------------------------------------

    def work(self, outcome: dict | None) -> dict:
        shares = []
        for e in self.events:
            if e["kind"] != "share":
                continue
            d = e["data"]
            shares.append({"version_no": d.get("version_no"), "commit": d.get("commit"),
                           "commit_short": _short(d.get("commit")), "by": e["member"],
                           "at": e["at"], "note": d.get("note"),
                           "files_changed": d.get("files_changed"),
                           "files_total": d.get("files_total")})
        shares.reverse()
        closing = [e for e in self.events if e["kind"] == "closing"]
        summary = ((outcome or {}).get("done") or {}).get("summary") or (
            closing[-1]["data"].get("summary") if closing else None)
        return {"latest": shares[0] if shares else None, "shares": shares[:SHARES_SHOWN],
                "shares_total": len(shares), "summary": summary}

    # --- the phase -----------------------------------------------------------------------

    def phase(self, outcome: dict | None, run_status: str | None,
              members: list[dict]) -> dict:
        running = sum(1 for t in self.turns if t["state"] == "running")
        out: dict[str, Any] = {"name": "working", "words": None, "since": None,
                               "running": running, "asked": False, "reason": None,
                               "resumes_at": None, "resets_known": None, "usage": None,
                               "usage_checked_at": None, "resume_verified": False,
                               "blocked_windows": []}
        ended = [e for e in self.events if e["kind"] == "ended"]
        if outcome:
            decision = outcome["decision"]
            name = {"cancelled": "stopped"}.get(decision, decision)
            out.update(name=name, reason=outcome.get("reason"),
                       since=ended[-1]["at"] if ended else outcome.get("at"))
            out["words"] = (PHASE_WORDS.get(name)
                            or f"Failed: {outcome.get('reason') or 'the team ended'}")
            return out
        if run_status in RUN_ENDED or run_status == "interrupted":
            out.update(name="interrupted", words=PHASE_WORDS["interrupted"],
                       reason=f"the run ended ({run_status}) without the team ending")
            return out
        drain = next((e for e in reversed(self.events)
                      if e["kind"] in ("draining", "driver_started")), None)
        if drain is not None and drain["kind"] == "draining":
            return {**out, "name": "draining", "since": _at(drain["at"]),
                    "words": "Temper is restarting: the team carries on after it"}
        team_waits = [w for w in self.open if w["kind"] in WAIT_PHASE]
        if team_waits:
            w = next((x for x in team_waits if x["kind"] in ("closing", SETTINGS)),
                     team_waits[0])
            s = w["subject"] or {}
            name = WAIT_PHASE[w["kind"]]
            out.update(name=name, since=_at(w["opened_at"]),
                       asked=self.owner_answers(w) and running == 0)
            if name == "check_in":
                at = float(s.get("at_usd") or 0.0)
                out["words"] = (f"Check-in at ${at:g}: {running} turns finishing" if running
                                else f"Check-in at ${at:g}: continue, guide or stop?")
            elif name == "limit":
                out["resumes_at"] = utc_text(s.get("resumes_at"))
                out["resets_known"] = s.get("how") == "reset"
                weekly = (s.get("kind") or limit_kind(s.get("limit"))) != FIVE_HOUR
                reading = s.get("usage") or {}
                out.update(usage=s.get("usage"), reason=reading.get("reason"),
                           usage_checked_at=utc_text(s.get("usage_checked_at")),
                           resume_verified=s.get("resume_verified") is True,
                           blocked_windows=list(s.get("blocked_windows") or []))
                out["words"] = ("Usage is available again: restart or stop?" if out["asked"]
                                else "Usage cannot be checked; the team keeps waiting"
                                if reading.get("status") == "unavailable"
                                else "The account hit its weekly limit; the team waits, then "
                                     "asks you before restarting" if weekly else
                                     "The account hit its usage limit; it carries on only "
                                     "after fresh usage shows room")
            else:
                out["words"] = PHASE_WORDS.get(name)
            return out
        if not self.turns:
            out.update(name="starting", words=PHASE_WORDS["starting"])
            return out
        states = [m["state"] for m in members]
        member_waits = [w for w in self.open if self.owner_answers(w)]
        if running == 0 and member_waits and "ready" not in states:
            out.update(name="waiting_for_owner", asked=True,
                       since=_at(member_waits[0]["opened_at"]),
                       words=f"Waiting for you: {len(member_waits)} "
                             f"question{'s' if len(member_waits) != 1 else ''}")
            return out
        out["words"] = f"{running} of {len(members)} members are working"
        return out


def flow_view(reader: TeamReader, record: dict, *, outcome: dict | None,
              run_status: str | None, members: list[dict], started_at: Any,
              ended_at: Any = None) -> dict:
    """The glance fields of a free-flowing team's run reply (contract sections 3-6).
    ``members`` are today's member entries (team_view.members_view), extended here."""
    read = FlowRead(reader, record)
    mine = [read.member(m) for m in members]
    counts: dict[str, int] = {"members": len(mine)}
    for state in ("working", "ready", "idle", "held", "failed", "ended"):
        counts[state] = sum(1 for m in mine if m["state"] == state)
    start = utc_moment(started_at)
    ended = bool(outcome or run_status in RUN_ENDED or run_status == "interrupted")
    end = (utc_moment(ended_at or (outcome or {}).get("at")) if ended else read.now)
    if end is None and ended:
        ending = next((e for e in reversed(read.events) if e["kind"] == "ended"), None)
        end = utc_moment(ending["at"]) if ending else None
    activity = [e["at"] for e in read.events if e["kind"] not in ("wait_opened",)]
    feed_waits = {w["wait_id"]: w for w in read.waits}
    return {
        "kind": FLOW,
        "phase": read.phase(outcome, run_status, mine),
        "as_of": utc_text(read.now),
        "started_at": utc_text(start),
        "elapsed_s": int((end - start).total_seconds()) if start and end else None,
        "last_activity_at": max(activity) if activity else None,
        "spend": read.spend(),
        "you": read.you(),
        "counts": counts,
        "members": mine,
        "links": read.links(),
        "work": read.work(outcome),
        "events_cursor": read.cursor,
        "events_total": sum(1 for e in read.events if _event(e, feed_waits) is not None),
    }


# --- the event feed ---------------------------------------------------------------------------

def _event(e: dict, waits_by_id: dict[str, dict]) -> dict | None:
    """One feed event in the contract's shape, or None for the engine's own bookkeeping."""
    d, kind = e["data"] or {}, e["kind"]
    base = {"seq": e["seq"], "at": e["at"], "kind": kind, "member": e["member"]}
    if kind == "message":
        return {**base, "from": e["member"], "from_kind": d.get("sender_kind"),
                "to": d.get("to"), "message_kind": d.get("message_kind"),
                "text": d.get("subject"), "message_id": d.get("message_id"),
                "mid_turn": bool(d.get("mid_turn"))}
    if kind == "turn_start":
        return {**base, "turn_no": d.get("turn_no"), "retry_of": d.get("retry_of")}
    if kind == "turn_end":
        return {**base, "turn_no": d.get("turn_no"),
                "ended": TURN_ENDED.get(d.get("state") or "", d.get("state")),
                "ended_by": d.get("ended_by")
                or ("no_tool_call" if d.get("tool_calls") == 0 else None),
                "cost_usd": d.get("cost_usd"),
                "tool_calls": d.get("tool_calls")}
    if kind == "share":
        return {**base, "version_no": d.get("version_no"),
                "commit_short": _short(d.get("commit")), "note": d.get("note"),
                "files_changed": d.get("files_changed")}
    if kind == "share_refused":
        return {**base, "why": d.get("status"), "paths": d.get("paths") or []}
    if kind == "conflict":
        return {**base, "paths": d.get("paths") or [], "at_step": d.get("at_step")}
    if kind == "idle":
        return {**base, "note": d.get("note"),
                "reason": IDLE_REASONS.get(d.get("reason") or "", d.get("reason"))}
    if kind == "wake":
        return {**base, "by": d.get("by")}
    if kind == "closing":
        return {**base, "summary": _cut(d.get("summary"))}
    if kind == "done_refused":
        return {**base, "reasons": [{"code": REFUSAL_CODES.get(r.get("reason"), r.get("reason")),
                                     "words": r.get("detail")} for r in d.get("reasons") or []]}
    if kind == "done":
        return {**base, "summary": d.get("summary"), "version_no": d.get("version_no"),
                "commit_short": _short(d.get("commit"))}
    if kind == "check_in":
        return {**base, "at_usd": d.get("at_usd")}
    if kind in ("wait_opened", "wait_answered"):
        w = waits_by_id.get(d.get("wait_id") or "") or {}
        s = w.get("subject") or {}
        if d.get("wait_kind") == "closing":
            return None
        if d.get("wait_kind") == "limit":
            if kind == "wait_opened":
                # the wait's latest check time, and only while it is still open: a settled
                # limit has no next check (F2)
                live = w.get("state") == "open"
                return {**base, "kind": "limit",
                        "resumes_at": utc_text(s.get("resumes_at")) if live else None,
                        "resets_known": s.get("how") == "reset",
                        "weekly": (s.get("kind") or limit_kind(s.get("limit"))) != FIVE_HOUR}
            if d.get("word") in ("resumed", "restart"):
                return {**base, "kind": "limit_over"}
        wk = str(d.get("wait_kind") or "")
        out = {**base, "wait_id": d.get("wait_id"),
               "wait_kind": WAIT_KIND_SHOWN.get(wk, wk)}
        if kind == "wait_opened":
            return {**out, "words": wait_words(s) or _cut(d.get("question"))}
        return {**out, "answer": d.get("word"), "by": d.get("by")}
    if kind == "ended":
        return {**base, "decision": {"team_done": "done", "team_stopped": "stopped",
                                     "run_cancelled": "cancelled"}.get(d.get("reason") or "",
                                                                       "failed"),
                "reason": d.get("reason")}
    return None  # handed_in and other bookkeeping: not on the page


def events_view(reader: TeamReader, after: int, limit: int) -> dict:
    """``GET .../events?after=&limit=``: the feed's events after ``after``, in order, in the
    contract's shape; ``cursor`` the newest returned (or ``after``); ``more`` when more wait."""
    rows = reader.ledger.events_after(reader.run_id, reader.host_path, after, limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    waits_by_id = {w["wait_id"]: w for w in reader._rows(waits)}
    out = [x for x in (_event(e, waits_by_id) for e in rows) if x is not None]
    return {"events": out, "cursor": rows[-1]["seq"] if rows else after, "more": more,
            "as_of": utc_text(utcnow())}
