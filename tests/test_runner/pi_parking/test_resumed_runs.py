"""A resumed Pi run shows how its newest attempt stands (SW-79), and only one Resume carries a
cut-off Pi run on (SW-80): L3 F1 and F2, with the model-free Pi.

On SQLite and on the Postgres tier (tests/pgtier.py), where every asker of the same moment
holds a connection of its own.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw

SHOWN_IN = ("page", "list", "team_detail", "team_list")


def _shown(client, eid: str) -> dict[str, str]:
    """The run's status on the run page (the run API), in the run list, and through the Team
    page's two readers."""
    from temper_ai.api.data_service import run_detail_status, run_list_statuses

    return {"page": pw.detail(client, eid)["status"], "list": pw.listed(client, eid)["status"],
            "team_detail": str(run_detail_status(eid)),
            "team_list": run_list_statuses([eid])[eid]}


def _everywhere(status: str) -> dict[str, str]:
    return dict.fromkeys(SHOWN_IN, status)


def _failed_then_resumed_to_its_recovery_question(run) -> tuple[str, dict]:
    """A Pi run whose turn failed after spending money (L3 run C), resumed: it waits at its
    recovery question. The spent money made the failed attempt the run's most complete one,
    which is how the run came to show failed."""
    from temper_ai.observability.recorder import update_event

    FakeBox.behaviour = "provider_error"
    eid = sup.start(run.client, "pi_talk", run.ws)
    first = pw.wait_ended(eid, 1)[-1]
    assert first["status"] == "failed"
    update_event(first["id"], data={"cost_usd": 0.42})
    assert _shown(run.client, eid) == _everywhere("failed")

    FakeBox.behaviour = "answer"
    r = run.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    rec = sup.open_wait(eid, "recovery")
    assert len(sup.attempts(eid)) >= 2
    return eid, rec


def test_a_resumed_run_at_its_recovery_question_is_waiting_and_a_stop_ends_it_failed(pw_run):
    """SW-79: waiting while the question is open -- not the red, finished-looking "failed" of
    its first attempt -- and failed once the owner answers stop."""
    eid, rec = _failed_then_resumed_to_its_recovery_question(pw_run)

    assert _shown(pw_run.client, eid) == _everywhere("waiting")

    assert sup.approve(pw_run.client, eid, rec["gate_name"], "stop").status_code == 200
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "failed" and not sup.run_held(eid),
                 what=f"the stop to end {eid}")
    assert _shown(pw_run.client, eid) == _everywhere("failed")
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["failed"]


def test_a_resumed_run_answered_retry_runs_then_completes(pw_run):
    """SW-79: running while the retried turn runs, waiting at the step's own question after
    it, completed at the end."""
    eid, rec = _failed_then_resumed_to_its_recovery_question(pw_run)
    assert _shown(pw_run.client, eid) == _everywhere("waiting")

    in_turn, go_on = threading.Event(), threading.Event()

    def hold_the_turn(_box) -> None:
        in_turn.set()
        go_on.wait(timeout=20)

    FakeBox.on_prompt = hold_the_turn
    try:
        assert sup.approve(pw_run.client, eid, rec["gate_name"], "retry").status_code == 200
        assert in_turn.wait(timeout=20), "the retried turn never started"
        assert _shown(pw_run.client, eid) == _everywhere("running")
    finally:
        go_on.set()
        FakeBox.on_prompt = None

    owner = sup.open_wait(eid, "owner")
    assert _shown(pw_run.client, eid) == _everywhere("waiting")
    assert sup.approve(pw_run.client, eid, owner["gate_name"], "done").status_code == 200
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "completed" and not sup.run_held(eid),
                 what=f"{eid} to complete")
    assert _shown(pw_run.client, eid) == _everywhere("completed")
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["superseded", "completed"]


def test_resumes_and_the_pick_up_at_the_same_moment_start_one_attempt(pw_run, caplog):
    """SW-80 (L3 run D): four Resumes and temper's own pick-up, all at once, on a Pi run cut
    off while its turn ran. Exactly one starts an attempt; the others are told 409 and start
    nothing; the owner is asked once, and a retry runs the turn once more."""
    from fastapi.testclient import TestClient

    from temper_ai.runner import pickup
    from temper_ai.server import app
    from temper_ai.shared.clock import utcnow

    box_json = Path(os.environ["TEMPER_PI_BOX_CONFIG"])
    eid = sup.crash_child(pw_run.url, pw_run.tmp, "pi_talk", pw_run.ws, box_json)["execution_id"]
    since = utcnow()
    marked = sup.reconcile_only()
    assert eid in [m["execution_id"] for m in marked]
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["running"]
    before = len(sup.attempts(eid))

    askers = 5
    start = threading.Barrier(askers)
    answers: list[tuple[int, str]] = []
    picks: list[pickup.Picks] = []

    def resume() -> None:
        client = TestClient(app)
        start.wait(timeout=20)
        r = client.post(f"/api/runs/{eid}/resume", json={})
        answers.append((r.status_code, r.text))

    def pick_up() -> None:
        start.wait(timeout=20)
        picks.append(pickup.pick_up_interrupted(
            marked, settle_s=0, since=since, resume=pickup._resume_through_the_button,
            tell=lambda text: True, sleep=lambda _s: None))

    threads = [threading.Thread(target=resume) for _ in range(askers - 1)]
    threads.append(threading.Thread(target=pick_up))
    with caplog.at_level(logging.INFO, logger="temper_ai.runner.pickup"):
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)

    picked = [c.execution_id for c in picks[0].picked]
    started = sum(code == 200 for code, _ in answers) + picked.count(eid)
    assert started == 1, (answers, picks[0])
    refused = [text for code, text in answers if code != 200]
    assert all(code in (200, 409) for code, _ in answers), answers
    assert all("already" in text for text in refused), refused
    if not picked:
        assert [c.why for c in picks[0].left] == [pickup.ALREADY_CARRIED_ON]
    assert not [r for r in caplog.records
                if r.name == "temper_ai.runner.pickup" and r.levelno >= logging.ERROR]

    rec = sup.open_wait(eid, "recovery")
    assert len(sup.attempts(eid)) == before + 1, "one attempt started, not one per asker"
    asked = [w for w in sup.ledger().snapshot(eid)["waits"] if w["kind"] == "recovery"]
    assert len(asked) == 1, "the owner is asked once"
    assert FakeBox.STARTS == [], "nothing ran again before the owner decided"

    assert sup.approve(pw_run.client, eid, rec["gate_name"], "retry").status_code == 200
    owner = sup.open_wait(eid, "owner")
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["superseded", "completed"]
    assert len(FakeBox.STARTS) == 1, "the turn ran once more, in one box"
    assert sup.approve(pw_run.client, eid, owner["gate_name"], "done").status_code == 200
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "completed" and not sup.run_held(eid),
                 what=f"{eid} to complete")


# The race behind the SW-80 flake (queue #63): an asker that chose to carry the cut-off run on
# got to its claim only after another asker's attempt had started and parked at its recovery
# question. These two hold the late asker at exactly that point, so the race happens every
# time, with no load and no luck.


def _cut_off_mid_turn(run) -> tuple[str, list[dict], datetime, int]:
    """A Pi run cut off while its turn ran (its worker died), marked at start-up: its id, what
    start-up marked, when that start-up began, and how many attempts the run has."""
    from temper_ai.shared.clock import utcnow

    box_json = Path(os.environ["TEMPER_PI_BOX_CONFIG"])
    eid = sup.crash_child(run.url, run.tmp, "pi_talk", run.ws, box_json)["execution_id"]
    since = utcnow()
    marked = sup.reconcile_only()
    assert eid in [m["execution_id"] for m in marked]
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["running"]
    return eid, marked, since, len(sup.attempts(eid))


def _parked_at_its_recovery_question(eid: str, before: int) -> dict:
    """The one attempt a Resume started has asked the recovery question and parked there: the
    run let its worker go. The open wait."""
    rec = sup.open_wait(eid, "recovery")
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "waiting" and not sup.run_held(eid),
                 what=f"{eid} to park at its recovery question")
    assert len(sup.attempts(eid)) == before + 1
    return rec


def _checkpoints(eid: str) -> list[tuple[int, str, str | None, str | None]]:
    from sqlmodel import select

    from temper_ai.checkpoint.models import Checkpoint
    from temper_ai.database import get_session

    with get_session() as session:
        rows = session.exec(select(Checkpoint).where(Checkpoint.execution_id == eid)
                            .order_by(Checkpoint.sequence)).all()  # type: ignore[arg-type]
        return [(r.sequence, r.event_type, r.node_name, r.status) for r in rows]


def _left_to_the_attempt_that_parked(eid: str, before: int, rec: dict,
                                     checkpoints: list[tuple]) -> None:
    """The late asker started nothing and touched nothing: one attempt, still parked; its
    recovery question open, asked once, under the same ask; no checkpoint written since; no
    box started."""
    assert len(sup.attempts(eid)) == before + 1, "one attempt started, not two"
    assert sup.attempts(eid)[-1]["status"] == "waiting"
    asked = [w for w in sup.ledger().snapshot(eid)["waits"] if w["kind"] == "recovery"]
    assert [(w["wait_id"], w["state"]) for w in asked] == [(rec["wait_id"], "open")]
    ask = sup.asked_event(eid, asked[0])
    assert ask is not None and ask["id"] == rec["ask_event_id"]
    assert _checkpoints(eid) == checkpoints, "nothing else wrote the run's checkpoints"
    assert FakeBox.STARTS == [], "nothing ran again before the owner decided"


def _answered_through_to_the_end(run, eid: str, rec: dict) -> None:
    """The owner answers retry, then done: the turn runs once more, in one box, and the run
    completes."""
    assert sup.approve(run.client, eid, rec["gate_name"], "retry").status_code == 200
    owner = sup.open_wait(eid, "owner")
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["superseded", "completed"]
    assert len(FakeBox.STARTS) == 1, "the turn ran once more, in one box"
    assert sup.approve(run.client, eid, owner["gate_name"], "done").status_code == 200
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "completed" and not sup.run_held(eid),
                 what=f"{eid} to complete")


def test_a_resume_whose_claim_waited_until_the_started_attempt_parked_starts_nothing(
        pw_run, monkeypatch):
    """A Resume looked at the cut-off run and found it free, then waited at its claim (the
    database was busy) while another Resume claimed the run, started the next attempt, and that
    attempt parked at its recovery question. The late Resume is told 409 and starts nothing.

    Before, its claim counted the other's claim as ended once that attempt stopped running (it
    had parked), took it over and started a second attempt, whose checkpoint writer was made
    before the park: the first checkpoint it wrote reused the sequence the park had taken (the
    flake's IntegrityError, written when the test's clean-up cancelled that attempt).
    """
    from fastapi.testclient import TestClient

    from temper_ai.runner import resume_claim
    from temper_ai.server import app

    eid, _marked, _since, before = _cut_off_mid_turn(pw_run)
    at_its_claim = threading.Event()
    go_on = threading.Event()
    claims: list[str] = []
    real_claim = resume_claim.claim

    def claim_after_the_park(*args, **kwargs):
        claims.append(eid)
        if len(claims) == 1:  # the late Resume's: held until the other's attempt has parked
            at_its_claim.set()
            go_on.wait(timeout=30)
        return real_claim(*args, **kwargs)

    monkeypatch.setattr(resume_claim, "claim", claim_after_the_park)
    late: list[tuple[int, str]] = []

    def resume_late() -> None:
        r = TestClient(app).post(f"/api/runs/{eid}/resume", json={})
        late.append((r.status_code, r.text))

    thread = threading.Thread(target=resume_late)
    thread.start()
    try:
        assert at_its_claim.wait(timeout=20), "the late Resume never got to its claim"
        r = pw_run.client.post(f"/api/runs/{eid}/resume", json={})
        assert r.status_code == 200, r.text
        rec = _parked_at_its_recovery_question(eid, before)
        checkpoints = _checkpoints(eid)
    finally:
        go_on.set()
        thread.join(timeout=30)
    assert not thread.is_alive()

    assert [code for code, _ in late] == [409], late
    assert "already being carried on" in late[0][1]
    _left_to_the_attempt_that_parked(eid, before, rec, checkpoints)
    _answered_through_to_the_end(pw_run, eid, rec)


def test_a_pick_up_that_chose_the_run_before_a_resume_carried_it_on_starts_nothing(
        pw_run, caplog):
    """temper's pick-up chose the cut-off run, then got to it only after a Resume had started
    the next attempt and that attempt had parked at its recovery question. The pick-up carries
    on the attempt the stop cut off and nothing newer: it leaves the run alone (already being
    carried on), with nothing logged as an error.

    Before, it found the parked attempt, claimed it as if the owner had answered, and started a
    second attempt.
    """
    from temper_ai.runner import pickup

    eid, marked, since, before = _cut_off_mid_turn(pw_run)
    chosen = threading.Event()
    go_on = threading.Event()
    picks: list[pickup.Picks] = []

    def resume_once_it_has_parked(execution_id: str) -> None:
        chosen.set()
        go_on.wait(timeout=30)
        pickup._resume_through_the_button(execution_id)

    def pick_up() -> None:
        picks.append(pickup.pick_up_interrupted(
            marked, settle_s=0, since=since, resume=resume_once_it_has_parked,
            tell=lambda text: True, sleep=lambda _s: None))

    thread = threading.Thread(target=pick_up)
    with caplog.at_level(logging.INFO, logger="temper_ai.runner.pickup"):
        thread.start()
        try:
            assert chosen.wait(timeout=20), "the pick-up never chose the run"
            r = pw_run.client.post(f"/api/runs/{eid}/resume", json={})
            assert r.status_code == 200, r.text
            rec = _parked_at_its_recovery_question(eid, before)
            checkpoints = _checkpoints(eid)
        finally:
            go_on.set()
            thread.join(timeout=30)
    assert not thread.is_alive()

    assert [c.execution_id for c in picks[0].picked] == [], picks[0]
    assert [(c.execution_id, c.why) for c in picks[0].left] == [(eid, pickup.ALREADY_CARRIED_ON)]
    assert not [r for r in caplog.records
                if r.name == "temper_ai.runner.pickup" and r.levelno >= logging.ERROR]
    _left_to_the_attempt_that_parked(eid, before, rec, checkpoints)
    _answered_through_to_the_end(pw_run, eid, rec)
