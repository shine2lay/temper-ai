"""Messages handed into a running turn keep one sender's order (I5 rule 3; Architecture's
ruling in #114's land check, rm-d1c13ecb).

A free-flowing team's member takes messages while its turn runs: Temper takes them from the
ledger and hands each to Pi as a steer. Pi can refuse a steer; the refused message goes back
to pending and reaches the member at its next claim. Had Temper gone on steering after the
refusal, the sender's later message would reach the member first, and a member that trusts
a sender's corrections ("ignore my last message") would act on the stale one. So a turn
steers one handed message at a time, the next only after Pi accepted the one before, and
nothing more after a refused one: what was taken but never steered goes back with it, and
the next claim takes them in seq order. A message that goes back is pending as if it had
never been handed in: the next claim delivers it once, and its frame never tells the member
it is given again.

Engine-driven: the checker (Z) runs its turn through the turn runner with the stand-in
worker played live (``TeamFakeBox._live``), while the leader's (X) turns are claimed and
settled by hand around it. Each test ends with the invariants, I5 strict.
"""

from __future__ import annotations

from temper_ai.pi_agent.inbox import render_batch
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.test_release_order import X, Z, _claim, _send


def _working_checker(led, box, run_id: str) -> tuple:
    """A free-flowing team whose checker (Z) has claimed a turn: the leader (X) took the
    goal and sent Z its first message. The team, and Z's turn with its batch."""
    team = ls.open_flow(led, box, run_id=run_id)
    _x_sends(led, run_id, 0)
    claimed = led.claim_turn(run_id, ts.HOST, attempt_id="attempt-1", flow=True, only=Z)
    assert claimed is not None, "Z's turn could not be claimed"
    return team, *claimed


def _x_sends(led, run_id: str, *notes: int) -> list[int]:
    """One turn of X's: a message to Z per note, released as the turn settles. Their seqs."""
    x, _, binding = _claim(led, run_id, X)
    seqs = [_send(led, run_id, binding, Z, n) for n in notes]
    ts.settle(led, x)
    return seqs


def _refuse(led, run_id: str, seq: int) -> None:
    """Pi refuses the steer that hands message ``seq`` in (and accepts every other)."""
    [mid] = [m["message_id"] for m in led.snapshot(run_id)["messages"] if m["seq"] == seq]
    FakeBox.refuse_steer = lambda text: "the steer was refused" if mid in text else None


def _steered(led, run_id: str) -> list[int]:
    """The seqs Z's box got steers for, in the order they were sent."""
    by_id = {m["message_id"]: m["seq"] for m in led.snapshot(run_id)["messages"]}
    [log] = [log for log in FakeBox.STARTS if log.get("member") == Z]
    return [next(seq for mid, seq in by_id.items() if mid in text)
            for text in log.get("steers", [])]


def _next_batch(led, run_id: str) -> list[dict]:
    """Z's next claim (settled at once): its batch."""
    claimed = led.claim_turn(run_id, ts.HOST, attempt_id="attempt-1", flow=True, only=Z)
    assert claimed is not None, "Z's next turn could not be claimed"
    turn, batch = claimed
    ts.settle(led, turn)
    return batch


def test_after_a_refused_steer_nothing_more_is_steered(led, box, run_id):
    """(a) X's 5 is handed into Z's turn and Pi refuses its steer; X's 8, released later in
    the same turn, is never steered: it stays pending, and Z's next claim takes 5 and 8, in
    order. (Steering 8 there showed 8 to Z, and 5 came back after it.)"""
    team, z, batch = _working_checker(led, box, run_id)
    [five] = _x_sends(led, run_id, 1)
    eight: list[int] = []
    _refuse(led, run_id, five)
    ts.SCRIPTS[Z].append([{"agent_start": True},
                          {"later": lambda: eight.extend(_x_sends(led, run_id, 2))},
                          {"tool": "checked"}, {"say": "done"}])

    assert team._run(z, batch).kind == "completed"
    after = _next_batch(led, run_id)
    ts.check_invariants(led, run_id)  # I5, strict

    assert [m["seq"] for m in after] == [five, *eight]
    assert [m["delivery_count"] for m in after] == [1, 1]  # as new: never "given again"
    assert _steered(led, run_id) == [five]
    handed = led.turn(z["turn_id"])["worker"]["handed_in"]
    assert (handed["confirmed"], handed["unconfirmed"], handed["refused"]) == ([], [five], [five])


def test_a_refused_steer_sends_back_the_rest_of_its_hand_in(led, box, run_id):
    """(b) X's 5 and 8 are handed into Z's turn together and Pi refuses 5's steer: 8 is never
    steered and goes back with 5, and Z's next claim takes 5 and 8, in order. (Steering both
    at once showed 8 alone to Z, and 5 came back after it.)"""
    team, z, batch = _working_checker(led, box, run_id)
    five, eight = _x_sends(led, run_id, 1, 2)
    _refuse(led, run_id, five)
    ts.SCRIPTS[Z].append([{"agent_start": True}, {"tool": "checked"}, {"say": "done"}])

    assert team._run(z, batch).kind == "completed"
    after = _next_batch(led, run_id)
    ts.check_invariants(led, run_id)  # I5, strict

    assert [m["seq"] for m in after] == [five, eight]
    assert [m["delivery_count"] for m in after] == [1, 1]  # as new: never "given again"
    assert _steered(led, run_id) == [five]
    handed = led.turn(z["turn_id"])["worker"]["handed_in"]
    assert (handed["confirmed"], handed["unconfirmed"], handed["refused"]) == (
        [], [five, eight], [five])
    assert "a handed message was never steered: not sent" in handed["problems"]


def test_two_messages_of_one_hand_in_both_reach_the_turn_in_order(led, box, run_id):
    """(c) X's 5 and 8 are pending at one hand-in and Pi accepts both: both are steered, 5
    first, and both reach Z in this turn, in order. A hand-in that takes less than all that
    is pending fails I5 here."""
    team, z, batch = _working_checker(led, box, run_id)
    five, eight = _x_sends(led, run_id, 1, 2)
    ts.SCRIPTS[Z].append([{"agent_start": True}, {"tool": "checked"}, {"say": "done"}])

    assert team._run(z, batch).kind == "completed"
    ts.check_invariants(led, run_id)  # I5, strict

    turn = led.turn(z["turn_id"])
    assert turn["input_seqs"] == [*(m["seq"] for m in batch), five, eight]
    assert _steered(led, run_id) == [five, eight]
    handed = turn["worker"]["handed_in"]
    assert (handed["confirmed"], handed["unconfirmed"]) == ([five, eight], [])
    assert "refused" not in handed and "problems" not in handed


def test_a_message_put_back_comes_back_as_new(led, box, run_id):
    """X's 5 is handed into Z's turn, and Z's session never shows it, so it goes back to
    pending (unhand) as if it had never been handed in. Z's next claim delivers it once, and
    its frame never says it is given again. (unhand used to leave the hand-in's count, so
    the next claim counted a second delivery: I7 failed, and Z was told "an earlier try of
    this turn did not finish" about a message it had never seen.)"""
    _, z, _ = _working_checker(led, box, run_id)
    [five] = _x_sends(led, run_id, 1)
    assert [m["seq"] for m in led.hand_in(z["turn_id"], z["epoch"])] == [five]
    assert led.unhand(z["turn_id"], [five]) == 1
    ts.settle(led, z)
    [back] = [m for m in led.snapshot(run_id)["messages"] if m["seq"] == five]
    assert (back["state"], back["turn_id"], back["delivery_count"]) == ("pending", None, 0)

    after = _next_batch(led, run_id)
    ts.check_invariants(led, run_id)  # I7: given more than once only in a retry's batch

    assert [(m["seq"], m["delivery_count"]) for m in after] == [(five, 1)]
    assert "given again" not in render_batch(after, team=True)
