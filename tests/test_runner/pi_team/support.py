"""Stand-ins for team tests: a scripted Pi per member, a recorder, and the tables' invariants.

No model and no network. Every member's "Pi" is :class:`TeamFakeBox` (L2's stand-in worker
with a team channel): at each turn it plays the member's next script -- the messages it sends
through Temper's team channel, and what it says -- and records the prompt it was given.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from typing import Any

from temper_ai.pi_agent.ledger import UNSETTLED, Binding, Ledger
from temper_ai.pi_agent.team_runtime import StepResult, Team, TeamMember
from temper_ai.pi_agent.turn import run_turn
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import SETTLED, FakeBox, assistant, said

HOST = "build.team"
NAMES = ("lead", "builder", "checker")
SETTINGS = {"mode": {"type": "leader", "leader": "lead"}, "communication": {"type": "all"},
            "pause_after_rounds": 3}

#: What each member does at its next turns: member -> turns, each a list of actions.
SCRIPTS: dict[str, list[list[dict]]] = defaultdict(list)
#: Every prompt each member was given, in order.
PROMPTS: dict[str, list[str]] = defaultdict(list)
#: Every send a member made, with Temper's answer.
SENDS: list[dict] = []


def reset() -> None:
    sup.reset_fake()
    SCRIPTS.clear()
    PROMPTS.clear()
    SENDS.clear()
    Team.turn_runner = None
    Team.stop_box = None


# --- scripts -----------------------------------------------------------------------------

def send(to: str | None = None, body: str = "", kind: str = "info", **extra: Any) -> dict:
    payload: dict[str, Any] = {"kind": kind, "body": body, **extra}
    if to is not None:
        payload["to"] = to
    return {"send": payload}


def reply_to_first(body: str, *, sender: str | None = None, **extra: Any) -> dict:
    """A reply to the first message of this turn's batch (or the first from ``sender``)."""
    def build(prompt: str) -> dict:
        heads = headers(prompt)
        if sender is not None:
            heads = [h for h in heads if h["from"] == f'member "{sender}"']
        return {"kind": "reply", "body": body, "in_reply_to": heads[0]["id"], **extra}
    return {"send": build}


HEADER = re.compile(r"^\[temper:(?P<tag>[0-9a-f]+)\] message (?P<i>\d+) of (?P<n>\d+) · "
                    r"id (?P<id>\S+) · from (?P<from>.+?) · kind (?P<kind>\S+)"
                    r"(?P<rest>.*)$")


def headers(prompt: str) -> list[dict]:
    """The message headers Temper wrote in a batch, in order."""
    out = []
    for line in prompt.splitlines():
        m = HEADER.match(line)
        if m:
            out.append({**m.groupdict(), "redelivered": "given again" in m["rest"]})
    return out


def ids_in(prompt: str) -> list[str]:
    return [h["id"] for h in headers(prompt)]


class TeamFakeBox(FakeBox):
    """L2's stand-in worker, playing the member's script through the box's team channel."""

    def _model_turn(self, rid: str, message: str, ok: Any) -> list[dict]:
        team = self.spec.team
        if team is None or self.behaviour != "answer" or not self._branch_settled():
            return super()._model_turn(rid, message, ok)
        member = team.binding.member
        self.log["prompts"] += 1
        self.log["allowance_at_prompt"] = self.allowance
        self.log["member"] = member
        PROMPTS[member].append(message)
        self._append({"type": "message", "message": {"role": "user", "content": [
            {"type": "text", "text": message}]}})
        actions = SCRIPTS[member].pop(0) if SCRIPTS[member] else []
        out: list[dict] = [ok()]
        text = "ok"
        for action in actions:
            if "call" in action:
                action["call"](self, message)
            elif "send" in action:
                payload = action["send"]
                payload = dict(payload(message) if callable(payload) else payload)
                payload.setdefault("client_msg_id", f"call_{uuid.uuid4().hex[:12]}")
                answer = team.handle(payload)
                SENDS.append({"member": member, "payload": payload, "reply": answer})
                out += self._tool(payload["client_msg_id"], payload, answer)
            elif "say" in action:
                text = action["say"]
            elif "die" in action:  # the worker dies here: the turn is cut off
                self.kill()
                return out
            elif "hang" in action:  # nothing more comes: the hang guard cuts the turn off
                return out
            elif "error" in action:  # the provider refuses: Pi settles with an error
                msg = assistant(stop="error", error=action["error"])
                self._append({"type": "message", "message": msg})
                return [*out, *said(msg), {"type": "agent_end", "messages": []}, SETTLED]
        msg = assistant(text)
        self._append({"type": "message", "message": msg})
        return [*out, *said(msg, (text,)), {"type": "agent_end", "messages": []}, SETTLED]

    def close(self) -> dict:
        self.log["closed"] = True
        return super().close()

    def _tool(self, call_id: str, payload: dict, answer: dict) -> list[dict]:
        ask = assistant(stop="toolUse")
        ask["content"] = [{"type": "toolCall", "id": call_id, "name": "send_message",
                           "arguments": payload}]
        shown = json.dumps(answer)
        self._append({"type": "message", "message": ask})
        self._append({"type": "message", "message": {
            "role": "toolResult", "toolCallId": call_id, "toolName": "send_message",
            "content": [{"type": "text", "text": shown}]}})
        return [*said(ask),
                {"type": "tool_execution_start", "toolCallId": call_id,
                 "toolName": "send_message", "args": payload},
                {"type": "tool_execution_end", "toolCallId": call_id,
                 "toolName": "send_message",
                 "result": {"content": [{"type": "text", "text": shown}]},
                 "isError": not answer.get("ok")}]


def fake_runner(cfg: Any, req: Any, ledger: Any) -> Any:
    return run_turn(cfg, req, ledger, box_factory=TeamFakeBox)


class Stopper:
    """Stands in for the leftover-box stop (R2 C1): no Docker. ``result`` is what Docker
    would say; every call is logged."""

    def __init__(self, **result: Any):
        self.calls: list[str] = []
        self.result = {"found": False, "was_running": False, "removed": False,
                       "confirmed": True, "error": None, **result}

    def __call__(self, name: str) -> dict:
        self.calls.append(name)
        return {"box": name, **self.result}


# --- the recorder and the team ---------------------------------------------------------

class Recorder:
    """Temper's event recorder, in memory."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.status: dict[str, str] = {}

    def record(self, event_type: Any, data: dict | None = None, parent_id: str | None = None,
               execution_id: str | None = None, status: str | None = None,
               event_id: str | None = None) -> str:
        eid = event_id or f"ev{len(self.events) + 1}-{uuid.uuid4().hex[:6]}"
        self.events.append({"type": str(event_type), "data": data or {}, "status": status,
                            "id": eid, "parent": parent_id})
        if status:
            self.status[eid] = status
        return eid

    def broadcast_stream_chunk(self, agent_id: Any, content: Any, chunk_type: str = "content",
                               done: bool = False, call_id: Any = None) -> None:
        return None

    def event_status(self, eid: str) -> str | None:
        return self.status.get(eid)

    def update_event(self, eid: str, status: str | None = None, data: dict | None = None) -> None:
        if status:
            self.status[eid] = status


def member(name: str, **over: Any) -> TeamMember:
    cfg = {"name": name, "type": "pi", "role": sup.ROLE, "provider": "openai-codex",
           "model": "gpt-6.1-sol", "thinking": "medium", "tools": ["Read"], "add_ons": []}
    cfg.update(over)
    return TeamMember(name, cfg)


def new_run() -> str:
    return f"run-{uuid.uuid4().hex[:16]}"


def make_team(led: Ledger, box: Any, *, run_id: str, names: tuple[str, ...] = NAMES,
              settings: dict | None = None, attempt: str = "attempt-1",
              recorder: Recorder | None = None, members: list[TeamMember] | None = None,
              host: str = HOST) -> Team:
    return Team(led, box, run_id=run_id, host_path=host,
                members=members or [member(n) for n in names],
                team_settings=settings or SETTINGS, recorder=recorder or Recorder(),
                attempt_id=attempt, workflow="team_test")


def open_team(led: Ledger, box: Any, **kw: Any) -> Team:
    team = make_team(led, box, **kw)
    refusal = team.open({})
    assert refusal is None, refusal
    return team


def run_until_quiet(team: Team, limit: int = 30) -> list[StepResult]:
    """Steps until the team has nothing to do, waits on the owner, or a turn ends badly."""
    out: list[StepResult] = []
    for _ in range(limit):
        res = team.step()
        out.append(res)
        if res.kind != "completed":
            break
    return out


def by_member(results: list[StepResult]) -> list[tuple[str | None, str]]:
    return [(r.member, r.kind) for r in results]


def claim_bound(led: Ledger, run_id: str, host: str = HOST,
                attempt: str = "attempt-1") -> tuple[dict, list[dict], Binding]:
    """Claim the team's next turn by hand: (turn, batch, the binding its box would get)."""
    claimed = led.claim_turn(run_id, host, attempt_id=attempt)
    assert claimed is not None, "nothing to claim"
    turn, batch = claimed
    part = led.participant(turn["participant_id"])
    binding = Binding(run_id=run_id, host_path=host, participant_id=part["participant_id"],
                      member=part["member"], session_id=part["session_id"],
                      turn_id=turn["turn_id"], epoch=turn["epoch"])
    return turn, batch, binding


def settle(led: Ledger, turn: dict, *, retire: bool = False,
           attempt: str = "attempt-1") -> dict | None:
    """Complete a hand-claimed turn."""
    return led.finish_turn(turn["turn_id"], epoch=turn["epoch"], output="done",
                           model_call_ids=[], worker=None, ask_owner=None,
                           attempt_id=attempt, retire=retire)


def info(to: str, body: str = "x", n: int | str = 1, **extra: Any) -> dict:
    """A member's info message payload, as the send tool builds it."""
    return {"to": to, "kind": "info", "body": body, "client_msg_id": f"call_{n}", **extra}


def rows(led: Ledger, run_id: str, host: str = HOST) -> dict[str, list[dict]]:
    snap = led.snapshot(run_id)
    return {k: [r for r in v if r["host_path"] == host] for k, v in snap.items()}


def message(led: Ledger, run_id: str, message_id: str) -> dict:
    found = [m for m in led.snapshot(run_id)["messages"] if m["message_id"] == message_id]
    assert len(found) == 1, message_id
    return found[0]


# --- the invariants (tables.md I1-I8), after every scenario ------------------------------

def check_invariants(led: Ledger, run_id: str, host: str = HOST) -> None:
    snap = rows(led, run_id, host)
    parts = {p["participant_id"]: p for p in snap["participants"]}
    turns = {t["turn_id"]: t for t in snap["turns"]}
    msgs = snap["messages"]
    by_seq = {m["seq"]: m for m in msgs}

    # I1 at most one turn per team holds the team's claim.
    assert sum(1 for t in turns.values() if t["claim_key"]) <= 1, "I1"
    for t in turns.values():
        assert (t["claim_key"] is not None) == (t["state"] in UNSETTLED), ("I1", t["state"])

    # I2 every consumed message names a turn of its recipient that took it; at most one
    # settled, non-superseded turn carries it.
    for m in msgs:
        carriers = [t for t in turns.values() if m["seq"] in (t["input_seqs"] or [])]
        if m["state"] == "consumed":
            t = turns.get(m["turn_id"])
            assert t is not None and t["participant_id"] == m["to_participant"], ("I2", m["seq"])
            assert m["seq"] in (t["input_seqs"] or []), ("I2", m["seq"])
        settled = [t for t in carriers if t["state"] not in UNSETTLED
                   and t["state"] != "superseded"]
        assert len(settled) <= 1, ("I2 carried twice", m["seq"])

    # I3 a member message's sender is a real turn of that member, never a payload.
    for m in msgs:
        if m["sender_kind"] != "member":
            assert m["sender_turn"] is None and m["sender_participant"] is None, ("I3", m["seq"])
            continue
        t = turns[m["sender_turn"]]
        p = parts[m["sender_participant"]]
        assert t["participant_id"] == p["participant_id"], ("I3", m["seq"])
        assert m["sender"] == p["member"] and m["sender_session"] == p["session_id"], "I3"

    # I4 held only while the sending turn is unsettled; a failed/superseded/cancelled turn's
    # messages are all undelivered with its reason.
    reasons = {"failed": {"turn_failed"}, "superseded": {"turn_superseded", "turn_failed"},
               "cancelled": {"turn_cancelled"}}
    for m in msgs:
        if m["sender_kind"] != "member":
            continue
        t = turns[m["sender_turn"]]
        if m["state"] == "held":
            assert t["state"] in UNSETTLED, ("I4 held after settle", m["seq"], t["state"])
        if t["state"] in reasons:
            assert m["state"] == "undelivered", ("I4", m["seq"], t["state"], m["state"])
            assert m["undelivered_reason"] in reasons[t["state"]], ("I4", m["undelivered_reason"])

    # I5 per member, turns take messages in seq order, never above the claim's cutoff.
    for t in turns.values():
        seqs = list(t["input_seqs"] or [])
        assert seqs == sorted(seqs), ("I5 batch order", t["turn_id"])
        assert t["cut_seq"] is not None and all(s <= t["cut_seq"] for s in seqs), "I5 cutoff"
    for pid in parts:
        mine = sorted((t for t in turns.values() if t["participant_id"] == pid
                       and t["state"] != "superseded"), key=lambda t: t["turn_no"])
        flat = [s for t in mine for s in (t["input_seqs"] or [])]
        assert flat == sorted(flat) and len(flat) == len(set(flat)), ("I5 order", pid, flat)

    # I6 nothing crosses runs or teams.
    for m in msgs:
        assert m["run_id"] == run_id and m["host_path"] == host, "I6"
        if m["to_participant"]:
            p = parts.get(m["to_participant"])
            assert p is not None and p["run_id"] == run_id and p["host_path"] == host, "I6"
        if m["turn_id"]:
            assert m["turn_id"] in turns, ("I6 delivering turn elsewhere", m["seq"])

    # I7 given more than once only in a retry's batch; ids never change.
    assert len({m["message_id"] for m in msgs}) == len(msgs), "I7 ids"
    for m in msgs:
        if (m["delivery_count"] or 0) > 1:
            assert any(t["retry_of"] and m["seq"] in (t["input_seqs"] or [])
                       for t in turns.values()), ("I7", m["seq"])

    # I8 after the team ended: nothing held or pending, no turn unsettled.
    if parts and all(p["state"] == "ended" for p in parts.values()):
        assert not [m for m in msgs if m["state"] in ("held", "pending")], "I8 messages"
        assert not [t for t in turns.values() if t["state"] in UNSETTLED], "I8 turns"
    _ = by_seq
