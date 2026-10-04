"""An answer a step took is spent once the step finishes, even when this process never saw
it ask (#39's finding 5), and nothing about a run's waits stays in memory once its go is over
(#39's ``_ASKED`` nit): temper_ai/stage/step_waits.py ``note_unspent_answers``,
``forget_step``, ``forget_run``.

Nothing reaches a model or the network (pi_parking/conftest.py's guard).
"""

from __future__ import annotations

import pytest

from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage import step_waits
from temper_ai.stage.exceptions import RunParked
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_parking import step_support as ask
from tests.test_runner.pi_parking import support as pw


@pytest.fixture
def sw(pw_run, monkeypatch):
    ask.install(monkeypatch, pw_run.tmp)
    return pw_run


def _remembered(eid: str) -> list[tuple[str, str]]:
    return [k for k in list(step_waits._ASKED) if k[0] == eid]


class _Saves:
    def save_wait_parked(self, event_id, path, gate_round, *, wait_id=None):
        return event_id


def test_an_answer_taken_before_the_process_died_is_spent_when_resume_finishes_the_step(sw):
    """Outside a Pi workflow the step takes its answer, keeps it in its own record and stops
    before it finished; the process that saw it ask is gone (its memory is fresh). Resume
    runs the step again and it finishes from its record without asking: the answer is spent
    all the same, so the step's next go asks afresh."""
    c = sw.client
    eid = sup.start(c, "plain_ask_stops", sw.ws)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["failed"]
    assert ask.load_record(eid, "ask")["answers"] == {"pause-after-round-1": "go on"}
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "approved" and not asked["data"].get("gate_used_at")

    step_waits._ASKED.clear()  # the process died: a new one knows nothing of what was asked
    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["failed", "completed"]
    assert ask.READ == [("ask", "pause-after-round-1", "go on")], "asked nothing on resume"
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["data"].get("gate_used_at"), "the answer was left unspent"

    # The step's next go asks afresh (round 2), not with the answer it already used.
    ctx = ExecutionContext(
        run_id=eid, workflow_name="plain_ask_stops", node_path="ask", agent_name="ask",
        event_recorder=EventRecorder(eid), tool_executor=None, checkpoint_service=_Saves(),
        gate_registry={}, park_at_gates=True, step_path="ask",
    )
    with pytest.raises(RunParked) as next_go:
        step_waits.ask_owner(ctx, "pause-after-round-1", question="Go on?")
    assert next_go.value.event_id != asked["id"] and next_go.value.round == 2
    step_waits.forget_run(eid)


def test_a_step_that_took_its_answer_and_failed_leaves_nothing_in_memory(sw):
    """A step that took its answer and failed: its go is over, so nothing stays in memory;
    the answer stays unspent in the run's record for the go that carries it on."""
    c = sw.client
    eid = sup.start(c, "plain_ask_stops", sw.ws)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["failed"]
    assert _remembered(eid) == []
    (asked,) = ask.step_waits(eid, "ask")
    assert not asked["data"].get("gate_used_at"), "kept for the go that carries it on"

    # And with the process still the same one, Resume spends it as well.
    assert c.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["failed", "completed"]
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["data"].get("gate_used_at")
    assert _remembered(eid) == []


def test_a_go_that_lets_its_worker_go_leaves_nothing_in_memory_and_carries_on(sw):
    """A Pi run: the step takes round 1's answer and lets go at round 2. That go of the run is
    over, so nothing of it stays in memory; carrying it on still spends both answers."""
    c = sw.client
    eid = sup.start(c, "sw_rounds", sw.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(sw.state, eid, n_attempts=1)
    first = pw.open_gate(c, eid, ask.name_of("ask", 1))
    assert pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"]).status_code == 200
    pw.wait_parked(sw.state, eid, n_attempts=2)
    second = pw.open_gate(c, eid, ask.name_of("ask", 2))
    assert _remembered(eid) == [], "a parked go left what its step asked in memory"
    assert pw.approve(c, eid, ask.name_of("ask", 2), event_id=second["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 3)] == ["parked", "parked", "completed"]
    assert [bool(w["data"].get("gate_used_at")) for w in ask.step_waits(eid, "ask")] == [True, True]
    assert _remembered(eid) == []


def test_a_finished_run_leaves_nothing_in_memory(sw):
    c = sw.client
    eid = sup.start(c, "plain_ask", sw.ws)
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    assert pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"]).status_code == 200
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["completed"]
    assert _remembered(eid) == []
