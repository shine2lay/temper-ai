"""ask_owner and park (temper_ai/stage/step_waits.py) on their own, with stand-in recorders.

The whole path -- a Pi run letting its worker go at a step's own wait, the answer carrying
it on, restarts, cancel -- is in tests/test_runner/pi_parking/test_step_waits*.py.
"""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from temper_ai.shared.types import ExecutionContext
from temper_ai.stage import step_waits as sw
from temper_ai.stage.exceptions import CancellationError, RunParked


class Recorder:
    """Keeps a run's waits the way the event recorder does, in memory."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.recorded = 0

    def record(self, event_type: Any, *, data: dict, parent_id: Any = None,
               execution_id: Any = None, status: Any = None, event_id: Any = None) -> str:
        self.recorded += 1
        self.events[event_id] = {"id": event_id, "status": status, "data": dict(data)}
        return event_id

    def gate_events(self, name: str | None = None) -> list[dict[str, Any]]:
        return [{**ev, "data": dict(ev["data"])} for ev in self.events.values()
                if name is None or ev["data"].get("name") == name]

    def decide(self, event_id: str, *, expect: tuple, status: str,
               data: dict | None = None) -> tuple[bool, dict | None]:
        ev = self.events[event_id]
        if ev["status"] not in expect:
            return False, ev
        ev["status"] = status
        ev["data"].update(data or {})
        return True, ev

    def update_event(self, event_id: str, *, status: str | None = None,
                     data: dict | None = None) -> None:
        ev = self.events[event_id]
        if status:
            ev["status"] = status
        ev["data"].update(data or {})

    def answer(self, event_id: str, text: str) -> None:
        self.update_event(event_id, status=sw.APPROVED,
                          data={"gate_status": sw.APPROVED,
                                "gate_response": {"response": text, "answers": {}, "text": text},
                                "gate_decided_by": "owner"})


class Checkpoints:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[tuple] = []
        self.gate_calls = 0

    def save_gate_parked(self, event_id: str, path: str, gate_round: int) -> str:
        self.gate_calls += 1
        return self.save_wait_parked(event_id, path, gate_round)

    def save_wait_parked(self, event_id: str, path: str, gate_round: int, *,
                         wait_id: str | None = None) -> str:
        if self.fail:
            raise RuntimeError("database gone")
        self.saved.append((event_id, path, gate_round, wait_id))
        return event_id


def _context(recorder: Any = None, *, step_path: str | None = "team.asker",
             park: bool = True, checkpoints: Any = None, cancel: Any = None) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1", workflow_name="wf", node_path="team.asker", agent_name="asker",
        event_recorder=recorder if recorder is not None else Recorder(), tool_executor=None,
        checkpoint_service=checkpoints, gate_registry={}, park_at_gates=park,
        step_path=step_path, cancel_event=cancel,
    )


@pytest.mark.parametrize("bad", ["", "~wait-1", "round~2", "-first", "has space", "x" * 129,
                                 None, 3])
def test_a_wait_id_that_cannot_name_a_wait_is_refused(bad):
    with pytest.raises(ValueError, match="wait id"):
        sw.ask_owner(_context(), bad, question="Go on?")


def test_a_context_that_names_no_step_is_refused():
    with pytest.raises(ValueError, match="step_path"):
        sw.ask_owner(_context(step_path=None), "pause-after-round-1", question="Go on?")


def test_a_question_is_needed():
    with pytest.raises(ValueError, match="question"):
        sw.ask_owner(_context(), "pause-after-round-1", question="  ")


def test_a_stopped_run_asks_nothing():
    stop = threading.Event()
    stop.set()
    rec = Recorder()
    with pytest.raises(CancellationError):
        sw.ask_owner(_context(rec, cancel=stop), "pause-after-round-1", question="Go on?")
    assert rec.recorded == 0


def test_the_wait_is_named_after_the_step_and_its_id():
    assert sw.wait_name("ship", "pause-after-round-3") == "ship~ask-pause-after-round-3"
    assert sw.wait_name("team.asker", "recover-turn-7") == "team.asker~ask-recover-turn-7"


def test_a_pi_run_lets_go_at_an_open_wait_and_asks_the_same_one_when_run_again():
    rec, saved = Recorder(), Checkpoints()
    ctx = _context(rec, checkpoints=saved)
    with pytest.raises(RunParked) as first:
        sw.ask_owner(ctx, "pause-after-round-1", question="Round 1 is done. Go on?",
                     options=("go on", "stop"))
    parked = first.value
    assert (parked.path, parked.node, parked.round, parked.wait_id) == \
        ("team.asker", "asker", 1, "pause-after-round-1")
    assert parked.checkpoint_id == parked.event_id
    assert saved.saved == [(parked.event_id, "team.asker", 1, "pause-after-round-1")]
    (ev,) = rec.events.values()
    assert ev["status"] == sw.WAITING and ev["data"]["name"] == "team.asker~ask-pause-after-round-1"
    assert ev["data"]["gate_path"] == "team.asker" and ev["data"]["type"] == sw.STEP_WAIT
    assert ev["data"]["gate_context"]["questions"][0]["question"] == "Round 1 is done. Go on?"

    # The step runs again before anyone answered: the same wait, not a second one.
    with pytest.raises(RunParked) as again:
        sw.ask_owner(ctx, "pause-after-round-1", question="Round 1 is done. Go on?")
    assert again.value.event_id == parked.event_id and rec.recorded == 1

    # Answered: the step gets the answer at once and asks nothing.
    rec.answer(parked.event_id, "go on")
    got = sw.ask_owner(ctx, "pause-after-round-1", question="Round 1 is done. Go on?")
    assert (got.event_id, got.text, got.round, got.decided_by) == \
        (parked.event_id, "go on", 1, "owner")
    assert rec.recorded == 1


def test_each_wait_id_is_its_own_wait():
    rec, saved = Recorder(), Checkpoints()
    ctx = _context(rec, checkpoints=saved)
    ids = []
    for n in (1, 2):
        with pytest.raises(RunParked) as parked:
            sw.ask_owner(ctx, f"pause-after-round-{n}", question=f"Round {n} is done. Go on?")
        ids.append(parked.value.event_id)
        rec.answer(parked.value.event_id, "go on")
    assert len(set(ids)) == 2 and [s[3] for s in saved.saved] == ["pause-after-round-1",
                                                                  "pause-after-round-2"]


def test_park_holds_the_worker_when_the_run_saves_no_checkpoints():
    assert sw.park(_context(), event_id="e1", node="asker", path="team.asker", round=1,
                   wait_id="w") is None


def test_park_holds_the_worker_when_the_checkpoint_cannot_be_saved():
    ctx = _context(checkpoints=Checkpoints(fail=True))
    assert sw.park(ctx, event_id="e1", node="asker", path="team.asker", round=1) is None


def test_a_gate_parks_as_it_did_before_step_waits():
    saved = Checkpoints()
    parked = sw.park(_context(checkpoints=saved), event_id="e1", node="review",
                     path="review", round=2)
    assert isinstance(parked, RunParked) and parked.wait_id is None
    assert parked.as_dict() == {"event_id": "e1", "node": "review", "path": "review",
                                "round": 2, "checkpoint_id": "e1"}
    assert saved.saved == [("e1", "review", 2, None)] and saved.gate_calls == 1


def test_a_gate_tells_its_wait_on_the_executors_logger_as_before(caplog):
    from temper_ai.stage import executor

    caplog.set_level(logging.INFO, logger="temper_ai")
    parked = executor._park_at_gate(_context(checkpoints=Checkpoints()),
                                    SimpleNamespace(name="review"), "e1", "review", 2)
    assert isinstance(parked, RunParked)
    told = [(r.name, r.getMessage()) for r in caplog.records]
    assert told == [("temper_ai.stage.executor",
                     "Gate: 'review' round 2 waits on you; the run lets its worker go "
                     "(execution run-1, event e1)")]


def test_finishing_spends_the_answers_so_the_next_go_asks_afresh():
    rec, saved = Recorder(), Checkpoints()
    ctx = _context(rec, checkpoints=saved)
    with pytest.raises(RunParked) as parked:
        sw.ask_owner(ctx, "pause-after-round-1", question="Go on?")
    rec.answer(parked.value.event_id, "go on")
    assert sw.ask_owner(ctx, "pause-after-round-1", question="Go on?").text == "go on"
    sw.spend_answers(ctx, "team.asker")
    assert rec.events[parked.value.event_id]["data"].get("gate_used_at")
    with pytest.raises(RunParked) as next_go:
        sw.ask_owner(ctx, "pause-after-round-1", question="Go on?")
    assert next_go.value.event_id != parked.value.event_id and next_go.value.round == 2


def test_spending_reads_nothing_for_a_step_that_never_asked_outside_a_pi_run():
    class Untouchable:
        def gate_events(self, name=None):
            raise AssertionError("read the waits of a step that never asked")

    sw.spend_answers(_context(Untouchable(), park=False), "plain")


def test_owner_answer_text():
    plain = sw.OwnerAnswer(wait_id="w", event_id="e", round=1, response=None)
    said = sw.OwnerAnswer(wait_id="w", event_id="e", round=1,
                          response={"response": "stop", "answers": {}, "text": ""})
    assert plain.text == "" and said.text == "stop"
