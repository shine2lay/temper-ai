"""C7: the single Pi step's own waits go through ``ask_owner`` (temper_ai/stage/step_waits.py).

Its question after a turn and its recovery waits let the worker go like any step's wait; the
answer carries the run on and the step picks up at the same wait id, never repeating a settled
turn. A Pi step may come first in a workflow. Runs on SQLite and on the Postgres tier.
"""

from __future__ import annotations

import re

import pytest

from temper_ai.pi_agent import host as host_mod
from temper_ai.pi_agent.host import PiHost
from temper_ai.pi_agent.ledger import gate_name_for
from temper_ai.pi_agent.owner_waits import wait_row
from temper_ai.shared.clock import utcnow
from temper_ai.shared.types import Status
from temper_ai.stage.exceptions import CancellationError, RunParked
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import step_support
from tests.test_runner.pi_parking import support as pw


def _prompts() -> int:
    """Model prompts sent across every worker the fake started: one per turn run."""
    return sum(s["prompts"] for s in FakeBox.STARTS)


def _statuses(eid: str) -> list[str]:
    return [a["status"] for a in pw.attempts(eid)]


def _asked_names(eid: str) -> list[str]:
    """The names of every owner-wait event the run recorded (gates' and steps' alike)."""
    return [str((e.get("data") or {}).get("name"))
            for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("gate_path")]


# --- (a) the question after a turn ---------------------------------------------------------

def test_a_pi_steps_question_lets_the_worker_go_and_the_answer_carries_it_on(pw_run):
    c, state = pw_run.client, pw_run.state
    eid = sup.start(c, "pi_talk", pw_run.ws)
    first = pw.wait_parked(state, eid, 1)
    w1 = sup.open_wait(eid, "owner")

    # Saved where it waits, under the wait's own id; no thread holds the run.
    assert pw.parked(first)["path"] == "talk"
    assert pw.parked(first)["wait_id"] == w1["wait_id"]
    assert pw.parked(first)["event_id"] == w1["ask_event_id"]
    assert w1["gate_name"] == f"talk~ask-{w1['wait_id']}"
    assert eid not in state.running and pw.run_threads(eid) == []
    assert _prompts() == 1

    # A message, not "done": the next attempt delivers it, runs turn 2 and asks again --
    # under a new id (answers are spent only when the step completes).
    r = pw.approve(c, eid, w1["gate_name"], event_id=w1["ask_event_id"],
                   response="look once more")
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True
    second = pw.wait_parked(state, eid, 2)
    w2 = sup.open_wait(eid, "owner", other_than=w1["wait_id"])
    assert pw.parked(second)["wait_id"] == w2["wait_id"] != w1["wait_id"]
    assert pw.run_threads(eid) == []
    snap = sup.ledger().snapshot(eid)
    assert [(t["turn_no"], t["state"]) for t in snap["turns"]] == [(1, "completed"),
                                                                    (2, "completed")]
    assert _prompts() == 2, "turn 1 was never run again"

    n = pw.finish_pi(c, eid)
    assert _statuses(eid)[:n - 1] == ["parked", "parked"]
    assert [a["status"] for a in pw.wait_ended(eid, n)] == ["parked", "parked", "completed"]
    assert _prompts() == 2
    assert sup.node_status(eid, "audit")[-1] == "completed"


# --- (b) recovery waits ------------------------------------------------------------------

def test_each_recovery_pause_asks_the_owner_under_its_own_id(pw_run):
    """A held turn's recovery wait lets the worker go; after a retry the turn is held again
    and the second pause asks again under a new id -- the first answer is never reused."""
    c, state = pw_run.client, pw_run.state
    FakeBox.behaviour = "usage_limit"
    eid = sup.start(c, "pi_talk", pw_run.ws)
    pw.wait_parked(state, eid, 1)
    r1 = sup.open_wait(eid, "recovery")
    assert r1["subject"]["options"] == ["accept", "retry"]
    assert pw.parked(pw.attempts(eid)[-1])["wait_id"] == r1["wait_id"]

    sup.approve(c, eid, r1["gate_name"], "retry")
    pw.wait_parked(state, eid, 2)
    r2 = sup.open_wait(eid, "recovery", other_than=r1["wait_id"])
    assert r2["wait_id"] != r1["wait_id"] and r2["gate_name"] != r1["gate_name"]
    assert pw.parked(pw.attempts(eid)[-1])["wait_id"] == r2["wait_id"]
    assert _prompts() == 2, "the retry ran the turn once more, then paused again"

    # Accept keeps the held turn as it stands: the owner is asked what comes next.
    sup.approve(c, eid, r2["gate_name"], "accept")
    pw.wait_parked(state, eid, 3)
    owner = sup.open_wait(eid, "owner")
    assert owner["wait_id"] not in (r1["wait_id"], r2["wait_id"])
    snap = sup.ledger().snapshot(eid)
    decided = {w["wait_id"]: (w["decision"] or {}).get("recovery") for w in snap["waits"]}
    assert decided[r1["wait_id"]] == "retry" and decided[r2["wait_id"]] == "accept"

    n = pw.finish_pi(c, eid)
    assert [a["status"] for a in pw.wait_ended(eid, n)] == [
        "parked", "parked", "parked", "completed"]
    assert _prompts() == 2
    names = _asked_names(eid)
    assert len(names) == len(set(names)) == 3, "one ask per wait, each under its own name"


def test_a_stop_at_a_failed_turns_recovery_wait_is_asked_and_stops_the_step(pw_run):
    c, state = pw_run.client, pw_run.state
    FakeBox.behaviour = "provider_error"
    eid = sup.start(c, "pi_talk", pw_run.ws)
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    assert c.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    pw.wait_parked(state, eid, 2)
    rec = sup.open_wait(eid, "recovery")
    assert rec["subject"]["options"] == ["retry", "stop"]
    assert pw.parked(pw.attempts(eid)[-1])["wait_id"] == rec["wait_id"]

    sup.approve(c, eid, rec["gate_name"], "stop")
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["failed", "parked", "failed"]
    assert _prompts() == 1, "nothing ran again"
    snap = sup.ledger().snapshot(eid)
    assert snap["waits"][0]["decision"]["recovery"] == "stop"
    said = [e for e in sup.events(eid) if "and the owner stopped the step" in str(e["data"])]
    assert said, "the step says the owner stopped it"


def test_f1_a_recovery_answer_naming_no_choice_is_asked_again_and_a_picked_retry_counts(pw_run):
    """M3 F1 for the single Pi step: words naming no choice decide nothing -- never an accept
    by default -- and the owner is asked again at a new wait for the same turn; a picked
    option, sent the way the run page sends it (``answers``), is that choice."""
    c, state = pw_run.client, pw_run.state
    FakeBox.behaviour = "usage_limit"
    eid = sup.start(c, "pi_talk", pw_run.ws)
    pw.wait_parked(state, eid, 1)
    r1 = sup.open_wait(eid, "recovery")
    r = pw.pick(c, eid, r1["gate_name"], event_id=r1["ask_event_id"],
                question=r1["subject"]["question"], custom="not sure yet")
    assert r.status_code == 200, r.text

    pw.wait_parked(state, eid, 2)
    r2 = sup.open_wait(eid, "recovery", other_than=r1["wait_id"])
    assert r2["subject"]["turn_id"] == r1["subject"]["turn_id"]
    assert r2["subject"]["options"] == ["accept", "retry"]
    assert r2["subject"]["question"].startswith("That answer was not one of: accept, retry, stop.")
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["uncertain"], "nothing was accepted"
    decided = {w["wait_id"]: (w["decision"] or {}).get("recovery") for w in snap["waits"]}
    assert decided[r1["wait_id"]] == "invalid"
    assert _prompts() == 1

    r = pw.pick(c, eid, r2["gate_name"], "retry", event_id=r2["ask_event_id"],
                question=r2["subject"]["question"])
    assert r.status_code == 200, r.text
    pw.wait_parked(state, eid, 3)
    r3 = sup.open_wait(eid, "recovery", other_than=r2["wait_id"])
    assert _prompts() == 2, "the picked retry ran the turn once more (held again)"
    snap = sup.ledger().snapshot(eid)
    decided = {w["wait_id"]: (w["decision"] or {}).get("recovery") for w in snap["waits"]}
    assert decided[r2["wait_id"]] == "retry"

    r = pw.pick(c, eid, r3["gate_name"], "accept", event_id=r3["ask_event_id"],
                question=r3["subject"]["question"])
    assert r.status_code == 200, r.text
    pw.wait_parked(state, eid, 4)
    sup.open_wait(eid, "owner")
    n = pw.finish_pi(c, eid)
    assert pw.wait_ended(eid, n)[-1]["status"] == "completed"
    assert _prompts() == 2


# --- (c) a Pi step as the first node -----------------------------------------------------

def test_a_first_node_pi_step_parks_survives_a_restart_and_the_answer_completes_it(pw_run):
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c, state = pw_run.client, pw_run.state
    eid = sup.start(c, "pi_first", pw_run.ws)
    first = pw.wait_parked(state, eid, 1)
    w = sup.open_wait(eid, "owner")
    assert pw.parked(first)["path"] == "talk" and pw.parked(first)["wait_id"] == w["wait_id"]
    # Nothing ran before it, yet it has a place to resume from: its own wait's checkpoint.
    saved = step_support.checkpoints(c, eid, "step_parked", pi=True)
    assert [cp["id"] for cp in saved] == [w["ask_event_id"]]

    # The server restarts while it waits: a parked run is not interrupted, and nothing
    # carries it on before the owner answers.
    marked = reconcile_and_report(started_before=utcnow())
    assert eid not in [m["execution_id"] for m in marked]
    sup.restart_service(now=utcnow(), marked=marked)
    assert parked.carry_on_at_startup() == []
    assert len(pw.attempts(eid)) == 1

    r = pw.approve(c, eid, w["gate_name"], event_id=w["ask_event_id"], response="done")
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert _prompts() == 1, "the settled turn was not run again"
    assert sup.node_status(eid, "audit")[-1] == "completed"


# --- (h) run() lets parking and cancelling through ----------------------------------------

@pytest.mark.parametrize("exc", [
    RunParked(event_id="ev-1", node="talk", path="talk", round=1, checkpoint_id="ev-1",
              wait_id="w1"),
    CancellationError("the run was cancelled"),
], ids=["parked", "cancelled"])
def test_run_lets_parking_and_cancelling_through(monkeypatch, exc):
    def raising(self, input_data, context, started):
        raise exc

    monkeypatch.setattr(PiHost, "_run", raising)
    with pytest.raises(type(exc)):
        PiHost({"name": "talk", "role": "scout"}).run({}, None)


def test_run_still_turns_any_other_error_into_a_failed_step(monkeypatch):
    def raising(self, input_data, context, started):
        raise RuntimeError("boom")

    monkeypatch.setattr(PiHost, "_run", raising)
    result = PiHost({"name": "talk", "role": "scout"}).run({}, None)
    assert result.status == Status.FAILED and result.error == "Pi step failed: RuntimeError"


# --- (i) a wait that cannot park holds the worker; a cancel ends the conversation ---------

def test_a_wait_that_cannot_be_saved_holds_the_worker_and_a_cancel_ends_the_conversation(
        pw_run, monkeypatch):
    from temper_ai.checkpoint.service import CheckpointService

    tried: list[str] = []

    def cannot_save(self, event_id, path, gate_round, *, wait_id=None):
        tried.append(path)
        raise RuntimeError("the checkpoint store is down")

    raised: list[str] = []
    real_run = PiHost.run

    def watched(self, input_data, context):
        try:
            return real_run(self, input_data, context)
        except BaseException as exc:
            raised.append(type(exc).__name__)
            raise

    monkeypatch.setattr(CheckpointService, "save_wait_parked", cannot_save)
    monkeypatch.setattr(PiHost, "run", watched)
    c = pw_run.client
    eid = sup.start(c, "pi_talk", pw_run.ws)
    w = sup.open_wait(eid, "owner")
    # The wait's event is recorded before the step tries to save it: wait for the try.
    sup.wait_for(lambda: tried == ["talk"], what="the step to try to save its wait")
    # The wait could not be saved, so it holds its worker (no parked record).
    assert pw.run_threads(eid), "the worker waits at the question"
    assert pw.parked(pw.attempts(eid)[-1]) is None
    led = sup.ledger()
    led.post(eid, "talk", sup.ROLE, "one more thing", dedupe_key=f"{eid}:c7:late-note")

    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "the owner stopped it"})
    assert r.status_code in (200, 202), r.text
    assert pw.wait_ended(eid, 1)[-1]["status"] == "cancelled"
    assert raised[0] == "CancellationError", "the cancel went up through the step"
    assert "RunParked" not in raised

    snap = led.snapshot(eid)
    assert [x["state"] for x in snap["waits"]] == ["cancelled"]
    assert {p["state"] for p in snap["participants"]} == {"ended"}
    late = [m for m in snap["messages"] if m["body"] == "one more thing"]
    assert [(m["state"], m["undelivered_reason"]) for m in late] == [
        ("undelivered", "run_cancelled")]
    asked = [e for e in sup.events(eid, event_type="stage.started")
             if (e.get("data") or {}).get("name") == w["gate_name"]]
    assert asked and all(e["status"] == "rejected" for e in asked)
    assert sup.node_status(eid, "talk")[-1] != "failed"


# --- (j) a wait settled elsewhere ---------------------------------------------------------

def _settle_first(monkeypatch, settle) -> list[str]:
    """Wrap the bridge so another actor settles the wait just before this step asks it."""
    real = host_mod.ask_owner_for_wait
    seen: list[str] = []

    def wrapped(context, ledger, wait_id, **kw):
        if not seen:
            seen.append(wait_id)
            settle(context, ledger, wait_row(ledger, wait_id))
        return real(context, ledger, wait_id, **kw)

    monkeypatch.setattr(host_mod, "ask_owner_for_wait", wrapped)
    return seen


def test_a_wait_decided_elsewhere_is_applied_and_the_step_goes_on(pw_run, monkeypatch):
    def finish(context, ledger, row):
        part = ledger.snapshot(row["run_id"])["participants"][0]
        assert ledger.decide_wait(row["wait_id"], {"owner": "finish", "by": "elsewhere"},
                                  "attempt-elsewhere",
                                  participant_states=[(part["participant_id"], "retired")])

    seen = _settle_first(monkeypatch, finish)
    eid = sup.start(pw_run.client, "pi_talk", pw_run.ws)
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["completed"]
    assert len(seen) == 1
    snap = sup.ledger().snapshot(eid)
    assert [(x["wait_id"], x["state"], x["decision"]["by"]) for x in snap["waits"]] == [
        (seen[0], "decided", "elsewhere")]
    assert _asked_names(eid) == [], "a decided wait is never asked"
    assert sup.node_status(eid, "talk")[-1] == "completed"
    assert sup.node_status(eid, "audit")[-1] == "completed"


def test_a_wait_cancelled_elsewhere_stops_the_step_without_failing_it(pw_run, monkeypatch):
    """The run was stopped and its conversation ended (as the cancel of a parked run does,
    runner/parked.py) just before this attempt asked: the step stops, not failed."""
    def end(context, ledger, row):
        ledger.end_team(row["run_id"], row["host_path"], "run_cancelled", "attempt-elsewhere")
        context.cancel_event.set()

    seen = _settle_first(monkeypatch, end)
    eid = sup.start(pw_run.client, "pi_talk", pw_run.ws)
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["cancelled"]
    assert len(seen) == 1
    snap = sup.ledger().snapshot(eid)
    assert [x["state"] for x in snap["waits"]] == ["cancelled"]
    assert _asked_names(eid) == [], "a cancelled wait is never asked"
    assert sup.node_status(eid, "talk")[-1] == "cancelled"
    assert not [e for e in sup.events(eid) if "Pi step failed" in str(e["data"])]
    assert sup.node_status(eid, "audit") == [], "nothing runs after a stopped step"


# --- (k) no "~wait-" names any more -------------------------------------------------------

def test_every_pi_wait_is_asked_under_its_ask_name_and_no_wait_name_is_left(pw_run):
    from temper_ai.runner import parked

    c, state = pw_run.client, pw_run.state
    eid = sup.start(c, "pi_talk", pw_run.ws)
    pw.wait_parked(state, eid, 1)
    w1 = sup.open_wait(eid, "owner")
    sup.approve(c, eid, w1["gate_name"], "again")
    pw.wait_parked(state, eid, 2)
    n = pw.finish_pi(c, eid)
    assert pw.wait_ended(eid, n)[-1]["status"] == "completed"

    waits = sup.ledger().snapshot(eid)["waits"]
    assert len(waits) == 2
    assert sorted(_asked_names(eid)) == sorted(f"talk~ask-{w['wait_id']}" for w in waits)
    assert all(w["gate_name"] == gate_name_for("talk", w["wait_id"]) for w in waits)
    everything = [str((e.get("data") or {}).get("name")) for e in sup.events(eid)]
    assert not [x for x in everything if "~wait-" in x]
    assert re.fullmatch(r"talk~ask-[A-Za-z0-9._-]+", gate_name_for("talk", "abc123"))
    assert not hasattr(parked, "_PI_OWN_WAIT")
