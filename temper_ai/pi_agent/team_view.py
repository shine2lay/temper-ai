"""The Team page's read of one team run (M3 contract section 5; api.json ``TeamRun``).

Everything comes from the team's ledger tables, the trial's row and the run's recorded
caller actions (#45); nothing here writes. The outcome is read only from
``pi_team_outcomes`` (M3 A2): the node's structured output is a copy for later workflow
nodes and is never read back here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from temper_ai.pi_agent.ledger import Ledger, acts, turns, waits
from temper_ai.pi_agent.settings_wait import GO_ON, SETTINGS, SETTINGS_STATE, STOP
from temper_ai.pi_agent.team_leader import (
    DECIDE,
    GIVE_VIEW,
    MAX_FILES,
    MAX_SUMMARY,
    VIEW_LIMIT,
    VIEW_PREVIEW,
    WAIT_KIND_SHOWN,
    TeamRows,
    _at,
    story,
)
from temper_ai.pi_agent.team_outcome import UNKNOWN_CALLER, by_name
from temper_ai.shared.clock import as_utc

#: The page's state while a wait of that kind is the one Temper asks (contract section 5).
WAIT_STATE = {"pause": "paused", "stalled": "quiet", "recovery": "member_waiting",
              "question": "member_waiting", SETTINGS: SETTINGS_STATE}
#: Where an owner action came from, for display only (M3 E15).
SOURCES = ("team_page", "run_page", "chat", "api", "unknown")
#: The run's own statuses that mean the team can't change any more.
RUN_ENDED = ("completed", "failed", "cancelled")
#: Caller actions shown as owner actions, with the kind the page names them by.
ACTION_KINDS = {"start": "start", "cancel": "stop", "message": "message"}


def utc_moment(value: datetime | str | None) -> datetime | None:
    """A time the Team API passes on, as an aware UTC datetime; ``None`` stays ``None``.
    ``value`` is a datetime or ISO text, with or without an offset: no offset means UTC, which
    is what every zoneless time temper stores means (a recorded event's timestamp is one).
    Text that isn't ISO is a ValueError."""
    if value is None or value == "":
        return None
    return as_utc(value if isinstance(value, datetime) else datetime.fromisoformat(value))


def utc_text(value: datetime | str | None) -> str | None:
    """A time the Team API sends: ISO 8601 with ``+00:00`` written out, so the page never has
    to guess the zone (#60). ``None`` stays ``None``."""
    moment = utc_moment(value)
    return moment.isoformat() if moment else None


#: Where a time-less entry sorts: first.
_EARLIEST = datetime.min.replace(tzinfo=UTC)


class TeamReader(TeamRows):
    """One team's rows, read without a box or a recorder (the API's side)."""

    def __init__(self, ledger: Ledger, run_id: str, host_path: str, leader: str):
        self.ledger = ledger
        self.run_id = run_id
        self.host_path = host_path
        self.leader = leader


# --- the answers a wait takes ------------------------------------------------------------

def _answer(word: str, needs_text: str, means: str) -> dict:
    return {"answer": word, "needs_text": needs_text, "means": means}


def answers_for(kind: str, subject: dict, leader: str) -> list[dict]:
    """The answers an open wait takes, in the order the page offers them, each with whether it
    needs words (``required``, ``optional`` or ``none``) and what it does, worded by Temper.
    ``kind`` is the page's (pause, stalled, recovery, question, settings)."""
    member = subject.get("member") or "the member"
    stop_cancels = _answer("stop", "optional", "The team stops here and the run ends cancelled. "
                                               "Any words you give are kept with it.")
    if kind == "pause":
        return [_answer("continue", "none", "The team carries on, and the count of rounds "
                                            "starts again."),
                _answer("guide", "required", f"{leader} gets your words as guidance, and the "
                                             "team carries on; the count of rounds starts again."),
                stop_cancels]
    if kind == "stalled":
        return [_answer("nudge", "optional", f"{leader} gets a nudge to finish or say done, with "
                                             "your words if you give any."),
                stop_cancels]
    if kind == "recovery":
        offered = [o for o in (subject.get("options") or []) if o in ("accept", "retry")]
        out = []
        if "accept" in offered:
            out.append(_answer("accept", "none", f"Keep what {member}'s turn did, without "
                                                 "running it again."))
        if "retry" in offered or not offered:
            out.append(_answer("retry", "none", f"{member} gets the same messages again in a "
                                                "new turn."))
        out.append(_answer("stop", "optional", "The team stops here and the run ends failed. "
                                               "Any words you give are kept with it."))
        return out
    if kind == "question":
        return [_answer("reply", "required", f"{member} gets your reply at its next turn.")]
    if kind == SETTINGS:
        return [_answer(GO_ON, "none", "The team carries on with the new settings, then your "
                                       "last answer is applied."),
                _answer(STOP, "optional", "The team stops here and the run ends cancelled; "
                                          "your last answer is not applied. Any words you give "
                                          "are kept with it.")]
    return []


def response_for(kind: str, answer: str, text: str) -> str:
    """The words the team's wait reads for a typed answer (the approve route's ``response``):
    ``guide: <text>``, ``nudge <text>``, ``stop <words>``, the reply itself for a question."""
    if kind == "question":
        return text
    if answer == "guide":
        return f"guide: {text}"
    return f"{answer} {text}".strip()


# --- the parts of a team run ----------------------------------------------------------------

def owner_answers(reader: TeamReader, owners: Iterable[str]) -> list[dict]:
    """One typed timeline entry per decided wait: what was answered, who answered it and where
    from (M3 E14, E21). A wait decided before #48 kept no caller: ``unknown caller``."""
    out = []
    for w in reader._rows(waits, waits.c.state == "decided", order=waits.c.decided_at):
        d, s = w["decision"] or {}, w["subject"] or {}
        answer = d.get("answer") or d.get("recovery")
        by = by_name(d.get("by"), owners) or UNKNOWN_CALLER
        source = d.get("source") if d.get("source") in SOURCES else "unknown"
        entry: dict[str, Any] = {
            "event_type": f"owner answer: {answer}", "from_agent": by, "to_agent": "temper",
            "timestamp": _at(w["decided_at"]),
            "data": {"wait_id": w["wait_id"], "answer": answer, "answered_by": by,
                     "answered_source": source, "request_id": d.get("request_id")},
            "entry": "owner_answer", "wait_kind": WAIT_KIND_SHOWN.get(w["kind"], w["kind"]),
            "answered_by": by, "answered_source": source, "request_id": d.get("request_id")}
        if isinstance(s.get("round"), int):
            entry["round"] = s["round"]
        if w["kind"] == SETTINGS and d.get("applied") is False:
            # A go on that came too late: the settings changed again before it was applied,
            # so nothing was re-pinned and a new settings wait names the newer ones.
            entry["data"]["applied"] = False
        out.append(entry)
    return out


def turn_entries(reader: TeamReader, names: dict[str, str]) -> list[dict]:
    """One typed timeline entry per member turn (M3 E14)."""
    out = []
    for t in reader._rows(turns, order=turns.c.started_at):
        member = names.get(t["participant_id"], t["participant_id"])
        error = str(t["error"] or "")
        data: dict[str, Any] = {"turn_id": t["turn_id"], "turn_no": t["turn_no"],
                                "state": t["state"], "ended_at": _at(t["ended_at"]),
                                "account_slot": t.get("account_slot")}
        if error:
            data["error"] = error[:VIEW_PREVIEW] + ("..." if len(error) > VIEW_PREVIEW else "")
        out.append({"event_type": f"turn {t['turn_no']}: {t['state']}", "from_agent": member,
                    "timestamp": _at(t["started_at"]), "data": data, "entry": "member_turn"})
    return out


def timeline(reader: TeamReader, owners: Iterable[str]) -> dict:
    """The newest :data:`VIEW_LIMIT` entries of the team's story, oldest first, and how many
    earlier ones are not shown."""
    names = {p["participant_id"]: p["member"] for p in reader._member_rows().values()}
    entries = story(reader, full=True, answers=owner_answers(reader, owners),
                    turn_rows=turn_entries(reader, names))
    hidden = max(0, len(entries) - VIEW_LIMIT)
    return {"entries": entries[hidden:], "not_shown": hidden}


def open_waits_view(reader: TeamReader, asked: dict[str, str]) -> list[dict]:
    """The open waits in the order Temper asks them (oldest first; the loop asks the first).
    ``asked`` maps a wait's step name to the waiting owner event asking it: only the first can
    have one (M3 E12). Each keeps its question and, apart, the reply syntax chat shows after it
    (``reply_hint``, M3 E22). A settings wait (SW-85, M3 E24) is asked before any other and
    carries its typed fields: ``settings_changes`` (one entry per changed setting: ``scope``
    team or member, ``member``, ``key``, ``value_kind`` text or sha256, ``old``, ``new``) and
    ``pins`` (each named member's ``pin_old`` and ``pin_new`` digests); both are None for
    other kinds."""
    out = []
    for i, w in enumerate(reader.ledger.open_waits(reader.run_id, reader.host_path)):
        s = w["subject"] or {}
        kind = WAIT_KIND_SHOWN.get(w["kind"], w["kind"])
        event_id = asked.get(w["gate_name"]) if i == 0 else None
        header = s.get("header") or (f"{s.get('member')} turn {s.get('turn_no')}"
                                     if kind == "recovery" else kind)
        out.append({
            "wait_id": w["wait_id"], "event_id": event_id, "node_name": w["gate_name"],
            "asked": event_id is not None, "kind": kind, "header": header,
            "question": s.get("question"), "reply_hint": s.get("reply_hint"),
            "answers": answers_for(kind, s, reader.leader),
            "round": s.get("round"), "member": s.get("member"), "turn_no": s.get("turn_no"),
            "why": s.get("why"),
            # A limit's recovery wait names the run's account, the limit and its reset
            # (ADR-M4-09); None for other waits.
            "account_slot": s.get("account_slot"), "limit": s.get("limit"),
            "resets": s.get("resets"),
            "asked_again": (int(s.get("asked_again") or 0) if kind in ("recovery", SETTINGS)
                            else None),
            "settings_changes": (list(s.get("settings_changes") or []) if kind == SETTINGS
                                 else None),
            "pins": ([{k: p.get(k) for k in ("member", "pin_old", "pin_new")}
                      for p in s.get("pins") or []] if kind == SETTINGS else None),
            "opened_at": _at(w["opened_at"])})
    return out


def _effective(worker: dict | None) -> dict | None:
    """The model and thinking a turn actually used, from its receipt (M3 E4): ``unknown``
    where the receipt doesn't say."""
    eff = (worker or {}).get("effective")
    if not isinstance(eff, dict):
        return {"model": "unknown", "thinking": "unknown"} if worker else None
    return {"model": eff.get("model") or "unknown", "thinking": eff.get("thinking") or "unknown"}


def members_view(reader: TeamReader, trial_members: list[dict],
                 open_waits: list[dict]) -> list[dict]:
    """Each member, in the trial's order: what it was asked to run on and what it actually ran
    on, what it is doing, its turns and their cost, and its last turn."""
    rows = reader._member_rows()
    by_participant: dict[str, list[dict]] = {}
    for t in reader._rows(turns, order=turns.c.turn_no):
        by_participant.setdefault(t["participant_id"], []).append(t)
    waiting_on = {w["member"] for w in open_waits if w.get("member")}
    out = []
    for m in trial_members:
        name = m["name"]
        row = rows.get(name)
        mine = by_participant.get(row["participant_id"], []) if row else []
        pin = (row or {}).get("pin") or {}
        ended = [t for t in mine if t["ended_at"]]
        last = mine[-1] if mine else None
        state = (row or {}).get("state")
        if state in ("ended", "retired"):
            activity = "ended"
        elif name in waiting_on:
            activity = "waiting_on_owner"
        elif state in ("running", "uncertain"):
            activity = "working"
        elif state == "failed":
            activity = "failed"
        else:
            activity = "idle"
        out.append({
            "name": name, "role": m.get("role"), "leader": bool(m.get("leader")),
            "activity": activity, "turns": len(mine),
            "cost_usd": round(sum(float(((t["worker"] or {}).get("usage") or {})
                                        .get("cost_usd") or 0.0) for t in mine), 6),
            "model": pin.get("model") or m.get("model"),
            "thinking": pin.get("thinking") or m.get("thinking"),
            "effective": _effective(ended[-1]["worker"]) if ended else None,
            "last_turn": ({"turn_no": last["turn_no"], "state": last["state"],
                           "started_at": _at(last["started_at"]),
                           "ended_at": _at(last["ended_at"]), "error": last["error"],
                           "account_slot": last.get("account_slot")}
                          if last else None)})
    return out


def reviews_view(reader: TeamReader) -> list[dict]:
    """Each review: its round, version, every member's view of it, and the leader's decision
    with why a done was refused."""
    rounds = {r["review_id"]: r["round"] for r in reader._reviews()}
    views: dict[str, dict[str, dict]] = {}
    for a in reader._rows(acts, acts.c.op == GIVE_VIEW, acts.c.state == "carried_out",
                          order=acts.c.seq):
        args = a["args"] or {}
        views.setdefault(a["review_id"], {})[a["member"]] = {
            "verdict": args.get("verdict"), "note": args.get("note"),
            "review_id": a["review_id"], "round": rounds.get(a["review_id"])}
    refusals: dict[str, str] = {}
    for a in reader._rows(acts, acts.c.op == DECIDE, acts.c.state == "carried_out",
                          order=acts.c.seq):
        refused = (a["result"] or {}).get("refused")
        rid = a["review_id"] or (a["args"] or {}).get("review_id")
        if refused and rid:
            refusals[rid] = refused
    return [{"review_id": r["review_id"], "round": r["round"], "state": r["state"],
             "commit": r["commit_sha"], "files_count": len(r["files"] or {}),
             "views": views.get(r["review_id"], {}), "decision": r["decision"],
             "refusal": refusals.get(r["review_id"]), "summary": r["summary"]}
            for r in reader._reviews()]


def outcome_view(row: dict | None, owners: Iterable[str]) -> dict | None:
    """The team's outcome as ``pi_team_outcomes`` holds it (M3 A2), or None while the team
    hasn't ended."""
    if not row or not row.get("decision"):
        return None
    done = None
    if row["decision"] == "done":
        rec = row.get("record") or {}
        version = rec.get("version") or {}
        commit = version.get("commit")
        files = sorted((version.get("files") or {}).items())
        done = {"review_id": rec.get("review_id"), "round": rec.get("round"),
                "commit": commit, "commit_short": commit[:12] if commit else None,
                "summary": (rec.get("summary") or "")[:MAX_SUMMARY] or None,
                "files": [{"path": p, "sha256": h} for p, h in files[:MAX_FILES]],
                "objections": rec.get("objections") or [],
                "branch": rec.get("branch"), "rounds": rec.get("rounds"),
                "cost_usd": float((rec.get("cost") or {}).get("cost_usd") or 0.0)}
    return {"decision": row["decision"], "reason": row["reason"],
            "owner_words": row.get("owner_words"), "problems": list(row.get("problems") or []),
            "by": by_name(row.get("decided_by"), owners), "at": row.get("at"), "done": done}


def owner_actions(reader: TeamReader | None, actions: list[dict],
                  owners: Iterable[str]) -> list[dict]:
    """Who did what to the run, oldest first (M3 E15): its start, its stop (a cancel), each
    message sent from the Team page -- from the API guard's record of each (#45) -- and each
    answer, from the wait it decided. ``by`` is the credential's name (``owner`` for the
    owner's), ``unknown caller`` when there was none; ``source`` is for display only."""
    out: list[dict[str, Any]] = []
    for ev in actions:
        d = ev.get("data") or {}
        kind = ACTION_KINDS.get(d.get("action") or "")
        if kind is None:
            continue
        source = d.get("caller_source") if d.get("caller_source") in SOURCES else "unknown"
        detail = {k: v for k, v in d.items() if k not in (
            "action", "caller", "caller_from", "caller_request_id", "caller_source",
            "request_id")}
        # a recorded event's timestamp has no zone: it is UTC, sent with its offset
        out.append({"at": utc_text(ev.get("timestamp")), "kind": kind,
                    "by": by_name(d.get("caller"), owners) or UNKNOWN_CALLER,
                    "source": source,
                    "request_id": d.get("request_id") or d.get("caller_request_id"),
                    "detail": detail})
    if reader is not None:
        for a in owner_answers(reader, owners):
            out.append({"at": a["timestamp"], "kind": "answer", "by": a["answered_by"],
                        "source": a["answered_source"], "request_id": a["request_id"],
                        "detail": {"wait_id": a["data"]["wait_id"], "wait_kind": a["wait_kind"],
                                   "answer": a["data"]["answer"]}})
    # by the moment, not the text: the two sources write different precisions
    out.sort(key=lambda a: utc_moment(a["at"]) or _EARLIEST)
    return out


def team_state(*, outcome: dict | None, run_status: str | None, open_waits: list[dict],
               began: bool) -> str:
    """The team's state, in the contract's order (section 5): its outcome; else interrupted;
    else the asked wait's kind; else starting while no member turn has begun; else running.
    A run that ended without the team's outcome (it ended before the team node wrote one)
    reads by the run's own status."""
    if outcome:
        decision = outcome["decision"]
        return "stopped" if decision == "cancelled" else decision
    if run_status in RUN_ENDED:
        return {"completed": "done", "cancelled": "stopped"}.get(run_status, "failed")
    if run_status == "interrupted":
        return "interrupted"
    if open_waits:
        return WAIT_STATE.get(open_waits[0]["kind"], "running")
    if not began:
        return "starting"
    return "running"


def round_view(reader: TeamReader, pause_after: int | None) -> dict:
    """The round now, and how many rounds kept going since the last continue or guide."""
    reviews = reader._reviews()
    return {"current": max((r["round"] for r in reviews), default=0),
            "keep_goings": len(reader.keep_goings()), "pause_after_rounds": pause_after}
