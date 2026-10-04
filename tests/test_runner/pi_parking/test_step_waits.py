"""A step that asks the owner from inside its own work (temper_ai/stage/step_waits.py), in a
Pi workflow in in-process mode: the run lets go of its thread where the step asks, and the
answer carries it on through Resume's path; the step runs again once and reads its answer.

The step is tests/test_runner/pi_parking/step_support.py's (a durable record, a stable wait
id per round). Nothing reaches a model or the network (pi_parking/conftest.py's guard).
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import step_support as ask
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking.test_in_process import _age, reconcile_and_report_now


@pytest.fixture
def sw(pw_run, monkeypatch):
    ask.install(monkeypatch, pw_run.tmp)
    pw_run.before = ask.threads_now()
    return pw_run


def _parked_here(sw, eid: str, n_attempts: int, path: str, n_round: int, test: str) -> dict:
    """Attempt ``n_attempts`` let go where the step at ``path`` asked after round ``n_round``;
    nothing holds the run. Returns the wait as GET .../gates lists it."""
    attempt = pw.wait_parked(sw.state, eid, n_attempts=n_attempts)
    wait = pw.open_gate(sw.client, eid, ask.name_of(path, n_round))
    note = pw.parked(attempt)
    assert note["event_id"] == wait["event_id"] and note["checkpoint_id"] == wait["event_id"]
    assert note["path"] == path and note["node"] == path.rsplit(".", 1)[-1]
    assert note["wait_id"] == ask.wait_id(n_round)
    assert wait["path"] == path
    counts = ask.held(sw.state, eid, before=sw.before, test=test, attempt=n_attempts,
                      wait_id=note["wait_id"])
    assert ask.nothing_held(counts), counts
    return wait


def test_a_step_that_asks_lets_go_of_its_worker_and_the_answer_carries_it_on(sw):
    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_after_pi", sw.ws)
    # The Pi step's own wait still holds its worker, as before this task.
    sup.open_wait(eid, "owner")
    assert pw.attempts(eid)[-1]["status"] == "running" and pw.run_threads(eid)
    pw.finish_pi(c, eid)

    wait = _parked_here(sw, eid, 1, "ask", 1, "lets_go_and_carries_on")
    assert wait["round"] == 1 and "Round 1 of ask is done" in str(wait["questions"])
    # Saved under the wait's own id; no approval checkpoint.
    (saved,) = ask.checkpoints(c, eid, "step_parked")
    assert saved["id"] == wait["event_id"] and saved["node_name"] == "ask"
    assert saved["metadata"] == {"event_id": wait["event_id"], "path": "ask", "round": 1,
                                 "wait_id": "pause-after-round-1"}
    assert ask.checkpoints(c, eid, "gate_parked") == []
    # The run shows "waiting on you".
    seen = pw.detail(c, eid)
    assert seen["status"] == "waiting" and seen.get("waiting_on_you") is True
    assert pw.listed(c, eid)["status"] == "waiting"
    assert ask.RUNS["ask"] == 1 and ask.READ == []

    r = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"], request_id="tab-1")
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True and r.json()["needs_resume"] is False
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]

    # Finished steps did not run again; the step ran again exactly once and read its answer.
    assert pw.RAN == {"brief": 1, "ship": 1} and len(FakeBox.STARTS) == 1
    assert ask.RUNS["ask"] == 2 and ask.WORK == {("ask", 1): 1}
    assert ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert ask.load_record(eid, "ask")["answers"] == {"pause-after-round-1": "go on"}
    # One wait, answered once, spent when the step finished.
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "approved" and asked["data"].get("gate_used_at")
    assert pw.detail(c, eid)["status"] == "completed"


def test_each_round_waits_with_its_own_id_and_checkpoint_and_old_answers_get_409s(sw):
    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_rounds", sw.ws)
    pw.finish_pi(c, eid)
    first = _parked_here(sw, eid, 1, "ask", 1, "two_rounds")

    r = pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"], request_id="tab-1")
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    # The same click again (a retry) gets the first result; it carries nothing on twice.
    again = pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"],
                       request_id="tab-1")
    assert again.status_code == 200 and again.json()["repeated"] is True, again.text

    second = _parked_here(sw, eid, 2, "ask", 2, "two_rounds")
    assert second["event_id"] != first["event_id"]
    # Another tab answering the first wait late gets a 409 naming who answered.
    late = pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"],
                      request_id="tab-2")
    assert late.status_code == 409 and late.json()["detail"]["reason"] == "already_answered"
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]
    saved = ask.checkpoints(c, eid, "step_parked")
    assert [cp["id"] for cp in saved] == [first["event_id"], second["event_id"]]
    assert [cp["metadata"]["wait_id"] for cp in saved] == ["pause-after-round-1",
                                                            "pause-after-round-2"]

    r = pw.approve(c, eid, ask.name_of("ask", 2), event_id=second["event_id"], response="done")
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["parked", "parked", "completed"]
    assert pw.RAN == {"brief": 1, "ship": 1} and len(FakeBox.STARTS) == 1
    # Three goes: asked round 1; read it and asked round 2; read that and finished. Each
    # round's work was done once.
    assert ask.RUNS["ask"] == 3 and ask.WORK == {("ask", 1): 1, ("ask", 2): 1}
    assert ask.READ == [("ask", "pause-after-round-1", "go on"),
                        ("ask", "pause-after-round-2", "done")]


def test_a_first_step_that_asks_parks_and_resume_waits_on_the_same_wait(sw):
    """Nothing has run and nothing is checkpointed but the wait: Resume runs the step again,
    and it waits on the wait it opened rather than asking twice."""
    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_first", sw.ws)
    asked = _parked_here(sw, eid, 1, "ask", 1, "first_position")
    assert pw.RAN == {} and FakeBox.STARTS == []
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [asked["event_id"]]

    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    again = _parked_here(sw, eid, 2, "ask", 1, "first_position")
    assert again["event_id"] == asked["event_id"]
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]
    assert len(ask.step_waits(eid, "ask")) == 1, "the same wait, not a second one"
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [asked["event_id"]]

    r = pw.approve(c, eid, ask.name_of("ask"), event_id=asked["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    pw.finish_pi(c, eid)
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "completed"]
    assert ask.RUNS["ask"] == 3 and ask.WORK == {("ask", 1): 1}
    assert ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert pw.RAN == {"audit": 1} and len(FakeBox.STARTS) == 1


def test_a_first_step_wait_of_days_survives_restarts_and_an_answer_while_the_server_is_down(
        sw, monkeypatch):
    from temper_ai.api import routes
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_first", sw.ws)
    asked = _parked_here(sw, eid, 1, "ask", 1, "first_position_restarts")
    _age(eid, timedelta(days=3))

    # Server restarts: never marked interrupted, never picked up, never carried on by itself.
    for _restart in range(2):
        marked = reconcile_and_report(started_before=utcnow())
        assert eid not in [m["execution_id"] for m in marked], "not marked interrupted"
        assert eid not in str(sup.restart_service(now=utcnow(), marked=marked))
        assert parked.carry_on_at_startup() == [], "no answer: it stays put"
    attempt = pw.attempts(eid)[-1]
    assert attempt["status"] == "waiting" and pw.parked(attempt)
    assert len(pw.attempts(eid)) == 1 and pw.detail(c, eid)["status"] == "waiting"

    # The answer goes in, but the server stops before carrying the run on.
    with monkeypatch.context() as down:
        down.setattr(routes, "_carry_on_parked", lambda execution_id, by: False)
        r = pw.approve(c, eid, ask.name_of("ask"), event_id=asked["event_id"])
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is False and r.json()["needs_resume"] is True
    assert eid not in [m["execution_id"] for m in reconcile_and_report_now()]
    assert parked.carry_on_at_startup() == [eid]
    pw.finish_pi(c, eid)
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert parked.carry_on_at_startup() == [], "only once"
    assert ask.RUNS["ask"] == 2 and ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert pw.RAN == {"audit": 1}


def test_cancel_while_a_step_waits_stops_the_run(sw):
    from temper_ai.runner import parked

    c = sw.client
    eid = sup.start(c, "sw_after_pi", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))

    r = c.post(f"/api/runs/{eid}/cancel", json={})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    assert ask.step_waits(eid, "ask")[0]["status"] == "rejected"
    late = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"])
    assert late.status_code in (404, 409)
    assert parked.carry_on_at_startup() == []
    assert pw.detail(c, eid)["status"] == "cancelled"
    assert ask.RUNS["ask"] == 1 and ask.READ == [] and pw.RAN == {"brief": 1}


def test_reject_while_a_step_waits_stops_the_run_and_says_why(sw):
    """Reject (Slack's button) stops the run with its reason, through the same cancel."""
    from temper_ai.integrations.slack.ops import TemperOps
    from temper_ai.runner import parked

    c = sw.client
    eid = sup.start(c, "sw_rounds", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    out = TemperOps().cancel(eid, "Rejected in Slack by Owner", by="Owner (Slack)")
    assert out["status"] == "cancelled", out
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "rejected"
    assert "Rejected in Slack by Owner" in str(asked["data"].get("gate_response"))
    late = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"])
    assert late.status_code in (404, 409)
    assert parked.carry_on_at_startup() == []
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    assert ask.RUNS["ask"] == 1 and ask.WORK == {("ask", 1): 1}


def test_two_answers_at_once_one_wins_and_the_run_carries_on_once(sw):
    from fastapi.testclient import TestClient

    from temper_ai.server import app

    c = sw.client
    eid = sup.start(c, "sw_after_pi", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))

    start = threading.Barrier(2)
    replies: dict[str, object] = {}

    def answer(tab: str, text: str) -> None:
        client = TestClient(app)
        start.wait(timeout=10)
        replies[tab] = pw.approve(client, eid, ask.name_of("ask"), event_id=wait["event_id"],
                                  request_id=tab, response=text)

    tabs = [threading.Thread(target=answer, args=(f"tab-{i}", f"answer {i}")) for i in (1, 2)]
    for t in tabs:
        t.start()
    for t in tabs:
        t.join(timeout=20)
    codes = sorted(r.status_code for r in replies.values())  # type: ignore[attr-defined]
    assert codes == [200, 409], {k: r.text for k, r in replies.items()}  # type: ignore[attr-defined]
    (won,) = [k for k, r in replies.items() if r.status_code == 200]  # type: ignore[attr-defined]
    (lost,) = [r for r in replies.values() if r.status_code == 409]  # type: ignore[attr-defined]
    assert lost.json()["detail"]["reason"] == "already_answered"  # type: ignore[attr-defined]

    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert len(pw.attempts(eid)) == 2, "carried on once"
    assert ask.RUNS["ask"] == 2
    assert ask.READ == [("ask", "pause-after-round-1", f"answer {won[-1]}")]


def test_a_gated_step_that_asks_is_approved_once(sw):
    """The step's approval comes first; the step then asks from inside its work. Carrying on
    after that answer does not ask the approval again."""
    c = sw.client
    eid = sup.start(c, "sw_gated", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    gate = pw.open_gate(c, eid, "ask")
    assert pw.approve(c, eid, "ask", event_id=gate["event_id"]).json()["carries_on"] is True

    sw.before = ask.threads_now()
    wait = _parked_here(sw, eid, 2, "ask", 1, "gated_step")
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["parked", "parked", "completed"]
    (approval,) = pw.waits(eid, "ask")
    assert approval["status"] == "approved" and approval["data"].get("gate_used_at")
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "gate_parked")] == [gate["event_id"]]
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [wait["event_id"]]
    assert ask.RUNS["ask"] == 2 and ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert pw.RAN == {"brief": 1, "ship": 1}


def test_a_loop_lap_asks_afresh_and_running_out_of_rounds_fails(sw):
    """An answer is spent once its step finishes: the loop's next lap asks again (the same
    wait id, round 2, its own checkpoint), and the loop still ends red when it runs out."""
    c = sw.client
    eid = sup.start(c, "sw_loop", sw.ws)
    pw.finish_pi(c, eid)
    sw.before = ask.threads_now()
    lap1 = _parked_here(sw, eid, 1, "ask", 1, "loop_laps")
    assert lap1["round"] == 1
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=lap1["event_id"],
                      response="again").status_code == 200
    lap2 = _parked_here(sw, eid, 2, "ask", 1, "loop_laps")
    assert lap2["round"] == 2 and lap2["event_id"] != lap1["event_id"]
    stale = pw.approve(c, eid, ask.name_of("ask"), event_id=lap1["event_id"],
                       request_id="old-tab")
    assert stale.status_code == 409
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [lap1["event_id"],
                                                                         lap2["event_id"]]
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=lap2["event_id"],
                      response="again").status_code == 200
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "failed"]
    assert "ran out of rounds: 2 of 2" in str(sup.events(eid, event_type="stage.started"))
    waits = ask.step_waits(eid, "ask")
    assert [w["status"] for w in waits] == ["approved", "approved"]
    assert all(w["data"].get("gate_used_at") for w in waits)
    assert ask.RUNS["ask"] == 4 and len(ask.READ) == 2
    assert pw.RAN == {"brief": 1} and len(FakeBox.STARTS) == 1


def test_a_step_that_asks_next_to_a_running_step_lets_go_once_that_step_is_done(sw):
    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_side_by_side", sw.ws)
    wait = _parked_here(sw, eid, 1, "left", 1, "side_by_side")
    assert pw.RAN == {"brief": 1, "right": 1}
    assert pw.approve(c, eid, ask.name_of("left"), event_id=wait["event_id"]).status_code == 200
    pw.finish_pi(c, eid)
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"
    assert pw.RAN == {"brief": 1, "right": 1} and ask.RUNS["left"] == 2


def test_a_step_that_fails_after_its_answer_reads_it_again_on_resume(sw):
    """A failed step keeps its answers: Resume runs it again and it gets the same answer,
    with no new wait (this step keeps no record of its own)."""
    c = sw.client
    eid = sup.start(c, "sw_fails", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "failed"]
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "approved" and not asked["data"].get("gate_used_at")

    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["parked", "failed", "completed"]
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["data"].get("gate_used_at"), "spent once the step finished"
    assert ask.READ == [("ask", "pause-after-round-1", "go on")] * 2
    assert pw.RAN == {"brief": 1, "ship": 1}


def test_a_step_inside_a_stage_asks_under_its_own_path(sw):
    """The team stage's shape: a step that is not an agent, inside a stage, two rounds."""
    c = sw.client
    sw.before = ask.threads_now()
    eid = sup.start(c, "sw_stage", sw.ws)
    pw.finish_pi(c, eid)
    first = _parked_here(sw, eid, 1, "team.asker", 1, "inside_a_stage")
    assert pw.approve(c, eid, ask.name_of("team.asker", 1),
                      event_id=first["event_id"]).status_code == 200
    second = _parked_here(sw, eid, 2, "team.asker", 2, "inside_a_stage")
    assert pw.approve(c, eid, ask.name_of("team.asker", 2),
                      event_id=second["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["parked", "parked", "completed"]
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [first["event_id"],
                                                                         second["event_id"]]
    assert ask.RUNS["asker"] == 3 and ask.WORK == {("asker", 1): 1, ("asker", 2): 1}
    assert pw.RAN == {"brief": 1, "ship": 1}


def test_a_step_that_asks_in_a_workflow_without_a_pi_step_holds_its_worker_as_before(sw):
    c = sw.client
    eid = sup.start(c, "plain_ask", sw.ws)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    attempt = pw.attempts(eid)[-1]
    assert attempt["status"] == "running" and pw.parked(attempt) is None
    assert eid in sw.state.running and pw.run_threads(eid)
    # The wait shows before the step has saved its checkpoint and settled down to wait.
    sup.wait_for(lambda: len(ask.checkpoints(c, eid, "step_waiting")) == 1,
                 what="the held wait's checkpoint")
    assert ask.checkpoints(c, eid, "step_parked") == []
    r = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"])
    assert r.status_code == 200 and "carries_on" not in r.json(), r.text
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["completed"]
    assert ask.RUNS["ask"] == 1 and ask.READ == [("ask", "pause-after-round-1", "go on")]
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "approved" and asked["data"].get("gate_used_at")


def test_cancel_while_a_step_holds_its_worker_opens_no_new_wait(sw):
    """Outside a Pi workflow the step holds its worker; a cancel stops it, and the agent
    step's retry of what raised asks nothing more."""
    c = sw.client
    eid = sup.start(c, "plain_ask", sw.ws)
    pw.open_gate(c, eid, ask.name_of("ask"))
    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "stop it"})
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 1, timeout=30)[-1]["status"] in ("cancelled", "failed")
    assert [w["status"] for w in ask.step_waits(eid, "ask")] == ["rejected"]
    assert ask.READ == [] and pw.RAN == {"brief": 1}


def test_the_owner_is_told_once_per_wait(sw, monkeypatch):
    """One message per wait: not again while it waits, not again when Resume waits on the
    same wait, and a new one for the next round's wait."""
    from temper_ai.integrations.notify import config as notify_config
    from temper_ai.integrations.notify.config import ConfigWatcher
    from temper_ai.integrations.notify.loop import Notifier
    from temper_ai.integrations.slack.ops import TemperOps
    from temper_ai.integrations.slack.sender import SlackSender
    from temper_ai.integrations.telegram import config as telegram_config
    from tests.test_integrations.conftest import NOTIFY_YAML, TELEGRAM_YAML, FakeSlack

    cfg = sw.tmp / "cfg"
    (cfg / "notify").mkdir(parents=True)
    (cfg / "telegram").mkdir()
    (cfg / "notify" / "notify.yaml").write_text(NOTIFY_YAML)
    (cfg / "telegram" / "telegram.yaml").write_text(TELEGRAM_YAML)
    monkeypatch.setattr(notify_config, "default_config_dir", lambda: cfg)
    monkeypatch.setattr(telegram_config, "default_config_dir", lambda: cfg)
    slack = FakeSlack()
    notifier = Notifier(ConfigWatcher(), TemperOps(), clock=utcnow)
    notifier.register(SlackSender(slack))
    assert notifier.tick() == []  # switching on

    def questions() -> list[str]:
        return [str(p) for p in slack.posts if "of ask is done" in str(p)]

    c = sw.client
    eid = sup.start(c, "sw_rounds", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid)
    first = pw.open_gate(c, eid, ask.name_of("ask", 1))
    notifier.tick()
    assert len(questions()) == 1 and "Round 1 of ask" in questions()[0]
    notifier.tick()
    assert len(questions()) == 1, "told once while it waits"

    # Resume with no answer: the step waits on the same wait again; no second message.
    assert c.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    pw.wait_parked(sw.state, eid, n_attempts=2)
    assert pw.open_gate(c, eid, ask.name_of("ask", 1))["event_id"] == first["event_id"]
    notifier.tick()
    assert len(questions()) == 1, "the same wait: not told again"

    assert pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"]).status_code == 200
    pw.wait_parked(sw.state, eid, n_attempts=3)
    pw.open_gate(c, eid, ask.name_of("ask", 2))
    notifier.tick()
    notifier.tick()
    assert len(questions()) == 2 and "Round 2 of ask" in questions()[1]
