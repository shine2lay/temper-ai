"""I5, release order (Architecture's ruling rm-1deb65bf, option a): a member gets its messages
in the order they were released to it, not in seq order across the whole team.

A member's message is held until its sending turn settles (docs/pi-team-messages.md), and a
claim or a hand-in takes everything pending for the member at that moment. So when two
members' turns overlap, the one that settles first is delivered first, whatever the seqs say.
The old I5 checked seq order across the whole team and failed the free-flowing team test
under load on exactly that flip; here the flip is made by hand, deterministically.

The new I5 (support.check_release_order) replays the team's event feed in
``pi_team_events.seq`` order and checks every handover (a claim's batch, or one mid-turn
hand-in): it takes every message pending for the member then, in seq order; nothing pending
is skipped; one sender's messages stay in order; a claim's batch never goes above its cut.
The bad ledgers at the end are forged by hand, each with one defect, and must fail with that
rule's label; the same ledger without the defect passes.

Model-free: the ledger is driven directly, as a free-flowing team's turns drive it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

from temper_ai.pi_agent.ledger import Binding
from tests.test_runner.pi_team import support as ts

#: X holds a message while Y's overtake it on their way to Z.
X, Y, Z = "lead", "builder", "checker"


def _open(led, box, run_id: str) -> None:
    """The team, with its goal waiting for the leader (X), as a free-flowing team starts."""
    team = ts.open_team(led, box, run_id=run_id)
    team.post(X, "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")


def _claim(led, run_id: str, name: str) -> tuple[dict, list[int], Binding]:
    """``name``'s turn, claimed as a free-flowing team claims it: the turn, its batch's seqs
    and the binding its box would get."""
    claimed = led.claim_turn(run_id, ts.HOST, attempt_id="attempt-1", flow=True, only=name)
    assert claimed is not None, f"{name}'s turn could not be claimed"
    turn, batch = claimed
    part = led.participant(turn["participant_id"])
    binding = Binding(run_id=run_id, host_path=ts.HOST, participant_id=part["participant_id"],
                      member=part["member"], session_id=part["session_id"],
                      turn_id=turn["turn_id"], epoch=turn["epoch"])
    return turn, [m["seq"] for m in batch], binding


def _send(led, run_id: str, binding: Binding, to: str, n: int) -> int:
    """A member's message to ``to``, held with its running turn: its seq."""
    sent = led.member_send(binding, ts.info(to, f"note {n}", n=n))
    assert sent["ok"], sent
    return ts.message(led, run_id, sent["message_id"])["seq"]


def _old_i5(snap: dict[str, list[dict]]) -> None:
    """The I5 this replaces, as it was: seq order across each member's turns. Kept here as the
    proof that the flip test bites."""
    parts = {p["participant_id"]: p for p in snap["participants"]}
    turns = {t["turn_id"]: t for t in snap["turns"]}
    for t in turns.values():
        seqs = list(t["input_seqs"] or [])
        assert seqs == sorted(seqs), ("I5 batch order", t["turn_id"])
        assert t["cut_seq"] is not None and all(s <= t["cut_seq"] for s in seqs), "I5 cutoff"
    for pid in parts:
        mine = sorted((t for t in turns.values() if t["participant_id"] == pid
                       and t["state"] != "superseded"), key=lambda t: t["turn_no"])
        flat = [s for t in mine for s in (t["input_seqs"] or [])]
        assert flat == sorted(flat) and len(flat) == len(set(flat)), ("I5 order", pid, flat)


# --- ledgers the engine writes ----------------------------------------------------------


def test_overlapping_turns_reach_a_member_in_release_order(led, box, run_id):
    """The gate's flake, by hand: X's 5 is held with X's running turn while Y sends 6 and 7
    and settles first. Z's first claim takes 6 and 7 (all that is pending), its next one 5.
    The old I5 calls that out of order; the new one passes it."""
    _open(led, box, run_id)
    x, _, x_binding = _claim(led, run_id, X)
    five = _send(led, run_id, x_binding, Z, 1)
    y, _, y_binding = _claim(led, run_id, Y)
    six, seven = _send(led, run_id, y_binding, Z, 1), _send(led, run_id, y_binding, Z, 2)
    ts.settle(led, y)  # Y settles first: 6 and 7 leave
    z1, first, _ = _claim(led, run_id, Z)
    ts.settle(led, x)  # then X: 5 leaves
    ts.settle(led, z1)
    z2, second, _ = _claim(led, run_id, Z)
    ts.settle(led, z2)

    assert five < six < seven
    assert (first, second) == ([six, seven], [five])
    with pytest.raises(AssertionError, match="I5 order"):
        _old_i5(ts.rows(led, run_id))
    ts.check_invariants(led, run_id)


def test_hand_ins_take_what_is_pending_below_or_above_the_cut(led, box, run_id):
    """Z's claim takes 6 and 7; X's 5 leaves while Z works and is handed in after them; then
    Y's 8, sent after Z's claim (above its cut), is handed in too. Each handover took what
    was pending then, so both pass; the old I5 counted hand-ins as part of the claim."""
    _open(led, box, run_id)
    x, _, x_binding = _claim(led, run_id, X)
    five = _send(led, run_id, x_binding, Z, 1)
    y, _, y_binding = _claim(led, run_id, Y)
    six, seven = _send(led, run_id, y_binding, Z, 1), _send(led, run_id, y_binding, Z, 2)
    ts.settle(led, y)
    z, first, _ = _claim(led, run_id, Z)
    ts.settle(led, x)  # 5 leaves while Z's turn runs
    below = [m["seq"] for m in led.hand_in(z["turn_id"], z["epoch"])]
    y2, _, y2_binding = _claim(led, run_id, Y)
    eight = _send(led, run_id, y2_binding, Z, 3)
    ts.settle(led, y2)  # 8 leaves while Z's turn still runs
    above = [m["seq"] for m in led.hand_in(z["turn_id"], z["epoch"])]
    ts.settle(led, z)

    turn = led.turn(z["turn_id"])
    assert (first, below, above) == ([six, seven], [five], [eight])
    assert turn["input_seqs"] == [six, seven, five, eight] and eight > turn["cut_seq"]
    with pytest.raises(AssertionError, match="I5 batch order"):
        _old_i5(ts.rows(led, run_id))
    ts.check_invariants(led, run_id)


# --- forged ledgers: one defect each ----------------------------------------------------


class _Forged:
    """A hand-made team ledger: only the rows and events I5 reads, written in the order the
    engine writes them, so that one defect can be put in on purpose."""

    def __init__(self) -> None:
        self.parts = {f"p-{n}": {"participant_id": f"p-{n}", "member": n} for n in (X, Y, Z)}
        self.turns: dict[str, dict] = {}
        self.msgs: list[dict] = []
        self.events: list[dict] = []

    def _event(self, kind: str, member: str, **data: Any) -> None:
        self.events.append({"seq": len(self.events) + 1, "kind": kind, "member": member,
                            "data": data})

    def release(self, seq: int, sender: str, to: str) -> None:
        """``sender``'s message ``seq`` becomes pending for ``to`` (its turn settled)."""
        self.msgs.append({"seq": seq, "message_id": f"m{seq}", "to_participant": f"p-{to}",
                          "sender": sender, "sender_kind": "member"})
        self._event("message", sender, to=to, message_id=f"m{seq}")

    def claim(self, member: str, seqs: list[int], cut: int) -> str:
        pid = f"p-{member}"
        no = 1 + sum(t["participant_id"] == pid for t in self.turns.values())
        tid = f"t{len(self.turns) + 1}"
        self.turns[tid] = {"turn_id": tid, "participant_id": pid, "turn_no": no,
                           "input_seqs": list(seqs), "cut_seq": cut, "retry_of": None,
                           "state": "completed"}
        self._event("turn_start", member, turn_id=tid, turn_no=no, messages=len(seqs))
        return tid

    def hand_in(self, tid: str, seqs: list[int]) -> None:
        self.turns[tid]["input_seqs"] += seqs
        member = self.parts[self.turns[tid]["participant_id"]]["member"]
        for s in seqs:
            self._event("handed_in", member, message_id=f"m{s}", turn_id=tid)

    def unhand(self, tid: str, seqs: list[int]) -> None:
        """Handed in but never shown: back to pending as the turn ends (no event, as the
        ledger's unhand)."""
        self.turns[tid]["input_seqs"] = [s for s in self.turns[tid]["input_seqs"]
                                         if s not in seqs]

    def check(self) -> None:
        ts.check_release_order(self.parts, self.turns, self.msgs, self.events)


def _skip(f: _Forged, bad: bool) -> None:
    """Rule 2: Z's claim leaves 7 pending and takes it at its next claim."""
    f.release(6, Y, Z)
    f.release(7, Y, Z)
    if bad:
        f.claim(Z, [6], cut=7)
        f.claim(Z, [7], cut=7)
    else:
        f.claim(Z, [6, 7], cut=7)


def _sender(f: _Forged, bad: bool) -> None:
    """Rule 3: Y's 7 reaches Z before Y's 6 (each claim takes all that is pending)."""
    first, second = (7, 6) if bad else (6, 7)
    f.release(first, Y, Z)
    f.claim(Z, [first], cut=7)
    f.release(second, Y, Z)
    f.claim(Z, [second], cut=7)


def _sender_after_unhand(f: _Forged, bad: bool) -> None:
    """Rule 3 through an unhand: Y's 7 and 8 are handed in, 8 is shown but 7 is not, so 7
    reaches Z after 8. Unhanding the last one (8) keeps Y's order."""
    f.release(6, Y, Z)
    turn = f.claim(Z, [6], cut=6)
    f.release(7, Y, Z)
    f.release(8, Y, Z)
    f.hand_in(turn, [7, 8])
    gap = 7 if bad else 8
    f.unhand(turn, [gap])
    f.claim(Z, [gap], cut=8)


def _cut(f: _Forged, bad: bool) -> None:
    """Rule 4: a claim's batch above its cut_seq."""
    f.release(6, Y, Z)
    f.release(7, Y, Z)
    f.claim(Z, [6, 7], cut=6 if bad else 7)


@pytest.mark.parametrize(("case", "label"), [
    (_skip, "I5.2 skip"),
    (_sender, "I5.3 sender order"),
    (_sender_after_unhand, "I5.3 sender order"),
    (_cut, "I5.4 cutoff"),
], ids=["skip", "sender", "sender_after_unhand", "cut"])
def test_a_forged_bad_ledger_fails_with_its_rule(case: Callable[[_Forged, bool], None],
                                                 label: str):
    good, bad = _Forged(), _Forged()
    case(good, False)
    good.check()
    case(bad, True)
    with pytest.raises(AssertionError, match=re.escape(label)):
        bad.check()
