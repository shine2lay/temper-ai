"""Separate processes racing on one team (R2 B6, A3's turn lease and WRITER-1): two workers
never run the same turn, never both take over a cut-off turn, and a message posted while a
turn is being claimed lands in that batch or waits for the next -- never lost, never twice.
Each process opens its own connection to the same database (SQLite file or the tier's
Postgres) and starts on one signal."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.support import HOST, check_invariants, open_team, rows

REPO = Path(__file__).resolve().parents[3]


def _race(db_url: str, run_id: str, actions: list[str], tmp_path: Path) -> list[dict]:
    """Start one process per action, wait until each has its connection open, then let them
    all go at once. Returns each process's outcome, in the order given."""
    start = tmp_path / f"go-{len(list(tmp_path.glob('go-*')))}"
    procs = [subprocess.Popen(
        [sys.executable, "-m", "tests.test_runner.pi_team.race_child", db_url, run_id, HOST,
         action, f"p{i}", str(start)],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i, action in enumerate(actions)]
    try:
        for p in procs:
            line = p.stdout.readline().strip()
            assert line == "ready", (line, p.stderr.read() if p.poll() is not None else "")
        start.touch()
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=120)
            assert p.returncode == 0, err[-3000:]
            outs.append(json.loads(out.strip().splitlines()[-1]))
        return outs
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()


def test_b6_double_pickup_one_turn(led, box, db_url, run_id, tmp_path):
    """R2 B6 (A3 rule 4, WRITER-1): four processes claim the same team's next turn at the same
    moment; exactly one gets it, with the whole batch; the others get nothing and change
    nothing. With that turn unsettled nobody can claim another."""
    team = open_team(led, box, run_id=run_id)
    goal = team.post("lead", "Write the README.", sender="temper", sender_kind="temper",
                     kind="goal", dedupe_key=f"{run_id}:goal")
    outs = _race(db_url, run_id, ["claim"] * 4, tmp_path)
    winners = [o for o in outs if o["turn_id"]]
    assert len(winners) == 1, outs
    assert winners[0]["batch"] == [goal["message_id"]]
    snap = rows(led, run_id)
    (turn,) = snap["turns"]
    assert (turn["turn_id"], turn["state"], turn["claimed_by"]) == (
        winners[0]["turn_id"], "running", winners[0]["me"])
    assert [p["member"] for p in snap["participants"] if p["state"] == "running"] == ["lead"]
    (msg,) = snap["messages"]
    assert (msg["state"], msg["turn_id"], msg["delivery_count"]) == (
        "consumed", turn["turn_id"], 1)
    team.post("builder", "while the lead works")
    assert led.claim_turn(run_id, HOST, attempt_id="late") is None
    check_invariants(led, run_id)


def test_b6_double_takeover_one_recovery(led, box, db_url, run_id, tmp_path):
    """R2 B6 + B11 (C1): the owner of a running turn is gone; three processes take over at the
    same moment. Exactly one confirms the box gone and opens one recovery wait; the others take
    nothing. The turn is never claimed twice or replayed.

    Each process that still reads the turn running moves its epoch on once, so the epoch can
    move on more than once: a process that reads the turn after another moved it on moves it
    on again, and the first one's take-over then fails its fence (made certain in
    test_b6_takeover_overtaken_while_stopping_the_box). It failed CI once (run 37335739068)
    when this test still expected exactly one move."""
    team = open_team(led, box, run_id=run_id)
    team.post("lead", "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")
    turn, _batch = led.claim_turn(run_id, HOST, attempt_id="dead-owner")
    assert led.record_box(turn["turn_id"], turn["epoch"], "temper-pi-deadbeef")
    outs = _race(db_url, run_id, ["take_over"] * 3, tmp_path)
    took = [o for o in outs if o["took"]]
    assert len(took) == 1, outs
    ((turn_id, wait_id),) = took[0]["took"]
    after = led.turn(turn_id)
    assert (turn_id, after["state"]) == (turn["turn_id"], "uncertain")
    # Moved on at least once (the old owner's writes fail), and at most once per process.
    assert turn["epoch"] < after["epoch"] <= turn["epoch"] + 3, (turn["epoch"], after["epoch"])
    assert after["box_stop"]["box"] == "temper-pi-deadbeef" and after["box_stop"]["confirmed"]
    waits = rows(led, run_id)["waits"]
    assert [(w["wait_id"], w["kind"], w["state"]) for w in waits] == [
        (wait_id, "recovery", "open")]
    # The old owner's late writes fail their fence.
    assert not led.mark_effect(turn_id, "committed", epoch=turn["epoch"])
    assert led.claim_turn(run_id, HOST, attempt_id="next") is None
    check_invariants(led, run_id)


def test_b6_takeover_overtaken_while_stopping_the_box(led, box, run_id):
    """The interleaving behind the race above, made certain. A moves the cut-off turn's epoch
    on; while A stops the old box, B reads the turn (still running), moves the epoch on again,
    confirms the box gone and opens the recovery wait. A's take-over then fails its fence and
    takes nothing: one recovery wait, and a late write at either older epoch fails."""
    team = open_team(led, box, run_id=run_id)
    team.post("lead", "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")
    turn, _batch = led.claim_turn(run_id, HOST, attempt_id="dead-owner")
    assert led.record_box(turn["turn_id"], turn["epoch"], "temper-pi-deadbeef")

    def gone(name: str) -> dict:
        return {"box": name, "found": False, "was_running": False, "removed": False,
                "confirmed": True, "error": None}

    b_took: list = []

    def a_stops_the_box(name: str) -> dict:
        b_took.extend(led.take_over(run_id, HOST, "attempt-b", stop_box=gone))
        return gone(name)

    assert led.take_over(run_id, HOST, "attempt-a", stop_box=a_stops_the_box) == []
    ((took, wait),) = b_took
    after = led.turn(turn["turn_id"])
    assert (took["turn_id"], after["state"], after["epoch"]) == (
        turn["turn_id"], "uncertain", turn["epoch"] + 2)
    waits = rows(led, run_id)["waits"]
    assert [(w["wait_id"], w["kind"], w["state"]) for w in waits] == [
        (wait["wait_id"], "recovery", "open")]
    # The old owner's late write fails its fence, and so does A's at the epoch it moved to.
    assert not led.mark_effect(turn["turn_id"], "committed", epoch=turn["epoch"])
    assert not led.mark_effect(turn["turn_id"], "committed", epoch=turn["epoch"] + 1)
    assert led.claim_turn(run_id, HOST, attempt_id="next") is None
    check_invariants(led, run_id)


def test_b6_post_racing_claim_lands_once(led, box, db_url, run_id, tmp_path):
    """A3 BATCH-1 across processes: one process claims the lead's turn while two others post
    to every member. Each message the claim could see (seq <= the turn's cut_seq) is in that
    batch; every later one is pending for the next turn; none is lost or delivered twice."""
    team = open_team(led, box, run_id=run_id)
    team.post("lead", "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")
    outs = _race(db_url, run_id, ["post:15", "claim", "post:15"], tmp_path)
    claim = outs[1]
    assert claim["turn_id"], outs
    posted = outs[0]["posted"] + outs[2]["posted"]
    assert len(set(posted)) == 30
    snap = rows(led, run_id)
    turn = next(t for t in snap["turns"] if t["turn_id"] == claim["turn_id"])
    lead = led.member_row(run_id, HOST, "lead")["participant_id"]
    for m in snap["messages"]:
        mine = m["to_participant"] == lead
        if mine and m["seq"] <= turn["cut_seq"]:
            assert (m["state"], m["turn_id"]) == ("consumed", turn["turn_id"]), m["seq"]
            assert m["message_id"] in claim["batch"]
        else:
            assert (m["state"], m["turn_id"]) == ("pending", None), m["seq"]
    assert sorted(claim["batch"]) == sorted(
        m["message_id"] for m in snap["messages"]
        if m["to_participant"] == lead and m["seq"] <= turn["cut_seq"])
    assert len(snap["messages"]) == 31
    check_invariants(led, run_id)
    assert ts.FakeBox.STARTS == []  # no box was started by any of it
