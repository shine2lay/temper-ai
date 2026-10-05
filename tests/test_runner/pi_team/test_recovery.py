"""Cut-off, failed and taken-over turns (R2 B1, B11, C1, N1) and restarts between steps
(A3's crash windows). A restart is a new :class:`Team` with a new attempt id over the same
tables: everything it knows it reads from them."""

from __future__ import annotations

import pytest

from temper_ai.pi_agent.host import owner_reply, recovery_word
from temper_ai.pi_agent.ledger import Binding, TakeoverRefused
from temper_ai.pi_agent.team_runtime import Team
from temper_ai.stage.gate import normalise_response
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.support import (
    PROMPTS,
    SCRIPTS,
    SENDS,
    Stopper,
    check_invariants,
    headers,
    ids_in,
    make_team,
    message,
    open_team,
    run_until_quiet,
    send,
)

BOX = "temper-pi-" + "ab" * 10


def _goal(team, run_id, to="lead", body="Write the README."):
    return team.post(to, body, sender="temper", sender_kind="temper", kind="goal",
                     dedupe_key=f"{run_id}:goal")


def _restart(led, box, run_id, attempt="attempt-2", **kw):
    """A new attempt over the same tables (a Resume, a restart, another worker)."""
    team = make_team(led, box, run_id=run_id, attempt=attempt, **kw)
    assert team.open({}) is None
    return team


def _dead_turn(led, run_id, *, box_name=BOX, effect="intent", sends=()):
    """A turn whose attempt died mid-turn: claimed, box named, prompt maybe sent, never
    settled. ``sends`` are messages its member sent before dying (held with the turn)."""
    turn, batch = led.claim_turn(run_id, ts.HOST, attempt_id="attempt-dead",
                                 claimed_by="elsewhere:1:boot")
    assert led.record_box(turn["turn_id"], turn["epoch"], box_name)
    if effect != "none":
        assert led.mark_effect(turn["turn_id"], effect, epoch=turn["epoch"])
    part = led.participant(turn["participant_id"])
    binding = Binding(run_id=run_id, host_path=ts.HOST,
                      participant_id=part["participant_id"], member=part["member"],
                      session_id=part["session_id"], turn_id=turn["turn_id"],
                      epoch=turn["epoch"])
    sent = [led.member_send(binding, {"client_msg_id": f"call_dead{i}", **s})
            for i, s in enumerate(sends)]
    assert all(s["ok"] for s in sent), sent
    return turn, batch, binding, sent


# --- M3 F1: what the owner said at a recovery wait --------------------------------------


@pytest.mark.parametrize(("text", "options", "word"), [
    ("retry", ["accept", "retry"], "retry"),
    ("Retry.", ["retry", "stop"], "retry"),
    ("accept, it is fine", ["accept", "retry"], "accept"),
    ("stop", ["accept", "retry"], "stop"),
    ("STOP", ["retry", "stop"], "stop"),
    ("Q: lead's turn 1 did not finish\nA: retry", ["accept", "retry"], None),
    ("", ["accept", "retry"], None),
    ("not sure yet", ["accept", "retry"], None),
    ("accept", ["retry", "stop"], None),
])
def test_f1_a_recovery_answer_names_one_of_its_choices_or_nothing(text, options, word):
    assert recovery_word(text, options) == word


def test_f1_a_picked_option_reads_as_the_pick_never_as_the_rendered_text():
    """The run page's GateModal sends ``answers[{selected}]``; the stored response's ``text``
    is "Q: ...\\nA: retry". What the owner said is the pick (then any words written with it)."""
    picked = normalise_response({"answers": [{"id": "q1", "question": "lead turn 1?",
                                              "selected": ["retry"]}]})
    assert picked["text"].startswith("Q: ")
    assert owner_reply(picked) == "retry"
    written = normalise_response({"answers": [{"id": "q1", "question": "q",
                                               "selected": ["accept"], "custom": "looks done"}]})
    assert owner_reply(written) == "accept looks done"
    assert owner_reply(normalise_response({"response": "retry"})) == "retry"
    assert owner_reply(None) == ""


# --- B1: a retried turn gets the same messages, same ids, in the same conversation -----

def test_b1_retry_redelivers_same_ids(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    note = team.post("lead", "and keep it short")
    SCRIPTS["lead"] = [[{"die": True}], [{"say": "done"}]]

    first = run_until_quiet(team)
    assert ts.by_member(first) == [("lead", "held")]
    count_before = len(led.snapshot(run_id)["messages"])
    assert team.decide(first[0].wait, "retry") is None
    run_until_quiet(team)

    p1, p2 = PROMPTS["lead"]
    assert ids_in(p1) == ids_in(p2) == [goal["message_id"], note["message_id"]]
    assert [h["redelivered"] for h in headers(p1)] == [False, False]
    assert [h["redelivered"] for h in headers(p2)] == [True, True]
    assert len(led.snapshot(run_id)["messages"]) == count_before  # never re-posted as new
    old, new = led.turns_of(led.member_row(run_id, ts.HOST, "lead")["participant_id"])
    assert (old["state"], new["retry_of"]) == ("superseded", old["turn_id"])
    assert new["input_seqs"] == old["input_seqs"]
    for mid in (goal["message_id"], note["message_id"]):
        row = message(led, run_id, mid)
        assert (row["delivery_count"], row["turn_id"]) == (2, new["turn_id"])
    # The same conversation: one session, both prompts in it, in order.
    starts = [s for s in ts.FakeBox.STARTS if s.get("member") == "lead"]
    assert len({s["session_id"] for s in starts}) == 1
    check_invariants(led, run_id)


# --- restarts between steps (A3 crash windows) --------------------------------------------

def test_restart_between_post_and_turn(led, box, run_id):
    """Posted, then the attempt stopped before any turn: the next attempt delivers it once,
    and re-posting the same goal on the re-run returns the original."""
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)

    again = _restart(led, box, run_id)
    assert again.resume() == []
    assert _goal(again, run_id)["duplicate"] is True
    results = run_until_quiet(again)
    assert ts.by_member(results) == [("lead", "completed"), (None, "idle")]
    assert ids_in(PROMPTS["lead"][0]) == [goal["message_id"]]
    assert message(led, run_id, goal["message_id"])["delivery_count"] == 1
    check_invariants(led, run_id)


def test_restart_mid_turn_takeover(led, box, run_id):
    """The attempt died during a turn: the next one stops the old box, then opens a recovery
    wait; the turn's input comes again with the same ids only after the owner says retry,
    and what the dead turn sent is never delivered."""
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    dead, _batch, _binding, sent = _dead_turn(
        led, run_id, sends=[{"to": "builder", "kind": "work_request", "body": "from the dead"}])

    stopper = Team.stop_box = Stopper(found=True, was_running=True, removed=True)
    again = _restart(led, box, run_id)
    waits = again.resume()
    assert stopper.calls == [BOX]
    assert [w["kind"] for w in waits] == ["recovery"]
    subject = waits[0]["subject"]
    assert subject["turn_id"] == dead["turn_id"] and subject["options"] == ["accept", "retry"]
    assert subject["effect_state"] == "intent"
    assert again.step().kind == "waiting"
    assert again.decide(waits[0], "retry") is None
    SCRIPTS["lead"] = [[{"say": "redone"}]]
    run_until_quiet(again)

    assert ids_in(PROMPTS["lead"][0]) == [goal["message_id"]]
    assert headers(PROMPTS["lead"][0])[0]["redelivered"] is True
    row = message(led, run_id, sent[0]["message_id"])
    assert (row["state"], row["undelivered_reason"]) == ("undelivered", "turn_superseded")
    assert "builder" not in PROMPTS
    check_invariants(led, run_id)


# --- B11: a cut-off turn pauses the whole team; finished turns are never replayed -------

def test_b11_cut_turn_pauses_team(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    team.post("builder", "owner's note for the builder")
    SCRIPTS["lead"] = [[send("checker", "check this"), {"die": True}]]

    first = run_until_quiet(team)
    assert ts.by_member(first) == [("lead", "held")]
    # The builder has a message, yet nothing runs while the recovery wait is open.
    for _ in range(3):
        assert team.step().kind == "waiting"
    assert led.claim_turn(run_id, ts.HOST, attempt_id="other") is None
    assert "builder" not in PROMPTS and "checker" not in PROMPTS
    held = message(led, run_id, SENDS[0]["reply"]["message_id"])
    assert held["state"] == "held"

    # Accepting the cut-off turn keeps it and releases what it sent.
    assert team.decide(first[0].wait, "accept") is None
    results = run_until_quiet(team)
    assert [m for m, _ in ts.by_member(results)] == ["builder", "checker", None]
    assert message(led, run_id, held["message_id"])["state"] == "consumed"
    check_invariants(led, run_id)


def test_b11_finished_turn_never_replayed(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "build it", kind="work_request")]]
    SCRIPTS["builder"] = [[{"die": True}], [{"say": "built"}]]

    first = run_until_quiet(team)
    assert ts.by_member(first) == [("lead", "completed"), ("builder", "held")]
    turns_before = {t["turn_id"]: t["state"] for t in led.snapshot(run_id)["turns"]}

    # A restart while the wait is open takes nothing over and replays nothing.
    again = _restart(led, box, run_id)
    waits = again.resume()
    assert [w["wait_id"] for w in waits] == [first[1].wait["wait_id"]]
    assert again.decide(waits[0], "retry") is None
    results = run_until_quiet(again)
    assert ts.by_member(results) == [("builder", "completed"), (None, "idle")]
    assert len(PROMPTS["lead"]) == 1  # the lead's finished turn never ran again
    after = {t["turn_id"]: t["state"] for t in led.snapshot(run_id)["turns"]}
    lead_turn = next(t for t, s in turns_before.items() if s == "completed")
    assert after[lead_turn] == "completed"
    assert ts.Team.stop_box.calls == []
    check_invariants(led, run_id)


def test_b11_hang_guard_opens_recovery(led, tmp_path, run_id):
    """A turn that stops answering is cut off by the hang guard (900 s in production, half
    a second here): a recovery wait, never a failure or a blind re-run."""
    box = ts.sup.box_config(tmp_path / "hang", turn_timeout_s=0.5)
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[{"hang": True}]]

    results = run_until_quiet(team)
    assert ts.by_member(results) == [("lead", "held")]
    wait = results[0].wait
    assert wait["kind"] == "recovery" and wait["subject"]["options"] == ["accept", "retry"]
    turn = led.turn(results[0].turn["turn_id"])
    assert turn["state"] == "uncertain" and turn["claim_key"]
    assert team.step().kind == "waiting"
    check_invariants(led, run_id)


# --- C1: take a turn over only once its old box is confirmed stopped --------------------

def test_c1_box_name_recorded_before_box_starts(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    seen = {}

    def look(fake, _prompt):
        running = [t for t in led.snapshot(run_id)["turns"] if t["state"] == "running"]
        seen["box_name"] = running[0]["box_name"]
        seen["fake"] = fake.name

    SCRIPTS["lead"] = [[{"call": look}]]
    run_until_quiet(team)
    assert seen["box_name"] == seen["fake"]
    check_invariants(led, run_id)


def test_c1_leftover_box_stopped_before_takeover(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    dead, *_ = _dead_turn(led, run_id)
    order = []

    class Recording(Stopper):
        def __call__(self, name):
            order.append(("stop", led.turn(dead["turn_id"])["state"]))
            return super().__call__(name)

    Team.stop_box = Recording(found=True, was_running=True, removed=True)
    waits = _restart(led, box, run_id).resume()
    # Stopped while the turn was still the old owner's (running), recorded on the turn.
    assert order == [("stop", "running")]
    turn = led.turn(dead["turn_id"])
    assert turn["state"] == "uncertain" and turn["epoch"] == dead["epoch"] + 1
    assert turn["box_stop"]["box"] == BOX
    assert turn["box_stop"]["was_running"] is True and turn["box_stop"]["confirmed"] is True
    assert waits and waits[0]["subject"]["turn_id"] == dead["turn_id"]
    check_invariants(led, run_id)


def test_c1_stale_owner_writes_refused(led, box, run_id):
    """After a takeover every write of the old owner fails its fence: effect state, agent
    event, sends and settling."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    dead, _batch, binding, _sent = _dead_turn(led, run_id)
    _restart(led, box, run_id).resume()
    old = dead["epoch"]

    assert led.mark_effect(dead["turn_id"], "committed", epoch=old) is False
    assert led.set_turn_agent_event(dead["turn_id"], "ev-late", epoch=old) is False
    assert led.record_box(dead["turn_id"], old, "temper-pi-" + "cd" * 10) is False
    late = led.member_send(binding, {"to": "builder", "kind": "info", "body": "late",
                                     "client_msg_id": "call_late"})
    assert late == {"ok": False, "code": "invalid_channel",
                    "detail": "this turn's message channel is closed"}
    assert led.finish_turn(dead["turn_id"], epoch=old, output="late", model_call_ids=[],
                           worker=None, ask_owner=None, attempt_id="attempt-dead") is None
    assert led.fail_turn(dead["turn_id"], "late", [], None, epoch=old) is False
    turn = led.turn(dead["turn_id"])
    assert turn["state"] == "uncertain" and turn["effect_state"] == "intent"
    assert turn["box_name"] == BOX
    assert not [m for m in led.snapshot(run_id)["messages"] if m["body"] == "late"]
    check_invariants(led, run_id)


def test_c1_unconfirmed_box_fails_red(led, box, run_id):
    """A box that cannot be confirmed gone: nothing is taken over and no recovery wait opens;
    the attempt fails red, with Docker's answer recorded on the turn."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    dead, *_ = _dead_turn(led, run_id)
    Team.stop_box = Stopper(found=True, was_running=True, removed=False, confirmed=False,
                            error="docker: permission denied")

    with pytest.raises(TakeoverRefused) as refused:
        _restart(led, box, run_id).resume()
    assert refused.value.turn_id == dead["turn_id"]
    assert led.open_waits(run_id, ts.HOST) == []
    turn = led.turn(dead["turn_id"])
    assert turn["state"] == "running" and turn["box_stop"]["confirmed"] is False
    assert turn["box_stop"]["error"] == "docker: permission denied"
    assert led.claim_turn(run_id, ts.HOST, attempt_id="attempt-3") is None
    check_invariants(led, run_id)


# --- N1: a failed turn is answered retry or stop --------------------------------------

def test_n1_failed_turn_retry_or_stop(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "early", kind="info"),
                        {"error": "400 invalid_request_error: refused"}],
                       [{"say": "second try"}]]
    first = run_until_quiet(team)
    assert ts.by_member(first) == [("lead", "failed")]

    again = _restart(led, box, run_id)
    waits = again.resume()
    assert [w["subject"]["options"] for w in waits] == [["retry", "stop"]]
    assert again.step().kind == "waiting"
    assert again.decide(waits[0], "retry") is None
    run_until_quiet(again)
    assert ids_in(PROMPTS["lead"][1]) == [goal["message_id"]]
    early = message(led, run_id, SENDS[0]["reply"]["message_id"])
    # Failed, then superseded by the retry: what it sent stays undelivered as turn_failed.
    assert (early["state"], early["undelivered_reason"]) == ("undelivered", "turn_failed")
    check_invariants(led, run_id)


def test_n1_f1_accept_at_a_failed_turn_is_asked_again_never_a_stop(led, box, run_id):
    """A failed turn is answered retry or stop (N1). ``accept`` names neither: it decides
    nothing -- no stop by default -- and the owner is asked again, at a new wait for the same
    turn (M3 F1); ``stop`` there then stops the team."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[{"error": "400 invalid_request_error: refused"}]]
    run_until_quiet(team)
    again = _restart(led, box, run_id)
    wait = again.resume()[0]
    assert again.decide(wait, "accept") is None
    (asked,) = led.open_waits(run_id, ts.HOST)
    assert asked["wait_id"] != wait["wait_id"] and asked["kind"] == "recovery"
    assert asked["subject"]["turn_id"] == wait["subject"]["turn_id"]
    assert asked["subject"]["options"] == ["retry", "stop"]
    assert asked["subject"]["question"].startswith("That answer was not one of: retry, stop.")
    assert asked["subject"]["question"].endswith(wait["subject"]["question"])
    (first,) = [w for w in ts.rows(led, run_id, ts.HOST)["waits"]
                if w["wait_id"] == wait["wait_id"]]
    assert (first["state"], first["decision"]["recovery"]) == ("decided", "invalid")
    assert again.step().kind == "waiting"
    assert led.member_row(run_id, ts.HOST, "lead")["state"] == "uncertain", "nothing decided"

    stopped = again.decide(asked, "stop")
    assert stopped == "lead turn 1 failed and the owner stopped the team"
    lead = led.member_row(run_id, ts.HOST, "lead")
    assert lead["state"] == "failed"
    assert again.step().kind == "failed"
    check_invariants(led, run_id)
