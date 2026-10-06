"""A resumed Pi run shows how its newest attempt stands (SW-79), and only one Resume carries a
cut-off Pi run on (SW-80): L3 F1 and F2, with the model-free Pi.

On SQLite and on the Postgres tier (tests/pgtier.py), where every asker of the same moment
holds a connection of its own.
"""

from __future__ import annotations

import logging
import os
import threading
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
