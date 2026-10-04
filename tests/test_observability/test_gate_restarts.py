"""A run picked up again never asks twice, and keeps an answer given while it was down.

A6-06: a resumed attempt opened a second waiting approval next to the first, one
approval answered both, and an approval made while the worker was down was ignored.
The gate now finds its step's earlier waits: an unused approval is the answer; an
open wait from before is waited on again (buttons already sent keep working); any
other open wait at the step is closed as replaced.

"Restarts" here are simulated: an attempt is stopped mid-wait (its thread raises, the
wait stays open in the database, as when a worker dies) and a new attempt reaches the
same gate. Both ways a run is executed are covered: in-process (the API and the run
share one gate registry) and external (the worker has its own; approvals go through
the database alone). Nothing here restarts a real server or worker.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import gate_events, get_event, record
from temper_ai.shared.types import ExecutionContext
from temper_ai.stage import executor as executor_mod
from temper_ai.stage.exceptions import CancellationError
from temper_ai.stage.executor import _wait_for_gate
from temper_ai.stage.loader import GraphLoader
from tests.test_stage.test_executor import _make_agent_node

RUN = "run-restarts-1"


@pytest.fixture(autouse=True)
def _parallel_database(request, tmp_path, monkeypatch):
    """Threads share the database: Postgres in the tier, else a SQLite file (not one connection)."""
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'gates.db'}")
    monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)


@pytest.fixture
def state():
    store = ConfigStore()
    st = AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(st)
    return st



@pytest.fixture
def client(state):
    from temper_ai.server import app
    return TestClient(app)


@pytest.fixture(params=["in_process", "external"])
def mode(request, state):
    return request.param


_STARTED: list[Attempt] = []


@pytest.fixture(autouse=True)
def _no_attempt_outlives_its_test():
    """Stop every attempt a test left waiting, before its database goes away."""
    yield
    while _STARTED:
        attempt = _STARTED.pop()
        attempt.cancel.set()
        attempt.done.wait(5)


class Attempt:
    """One attempt at running the gated step: a worker, in a thread, until it is stopped."""

    def __init__(self, state: AppState, mode: str, node_path: str = "") -> None:
        self.cancel = threading.Event()
        # In-process the run registers its wait where the API looks; a worker keeps its own.
        registry = state.gates if mode == "in_process" else {}
        self.context = ExecutionContext(
            run_id=RUN, workflow_name="wf", node_path=node_path, agent_name="",
            event_recorder=EventRecorder(RUN), tool_executor=MagicMock(),
            cancel_event=self.cancel, gate_registry=registry,
        )
        self.result: dict | None = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.node = _make_agent_node("approve")
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self.result = {"response": _wait_for_gate(self.node, self.context, "parent", {})}
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            self.error = exc
        finally:
            self.done.set()

    def start(self) -> Attempt:
        _STARTED.append(self)
        self.thread.start()
        return self

    def stop(self) -> None:
        """The worker goes away mid-wait. Its wait stays open, as after a crash."""
        self.cancel.set()
        assert self.done.wait(5)
        assert isinstance(self.error, CancellationError)

    def finish(self) -> dict | None:
        assert self.done.wait(5), "the attempt is still waiting"
        if self.error:
            raise self.error
        return (self.result or {}).get("response")


def _open(name: str = "approve") -> list[dict]:
    return [ev for ev in gate_events(RUN, name) if ev["status"] == "waiting"]


def _until_waiting(count: int = 1) -> list[dict]:
    """The open waits this code recorded (with a path), once there are ``count`` of them."""
    deadline = time.time() + 5
    while time.time() < deadline:
        waits = [ev for ev in _open() if (ev.get("data") or {}).get("gate_path")]
        if len(waits) >= count:
            return waits
        time.sleep(0.01)
    raise AssertionError(f"never saw {count} open wait(s): {gate_events(RUN)}")


def _alive(state: AppState, mode: str, alive: bool) -> None:
    """Whether some process is running the run, as the API tells."""
    if mode == "in_process":
        if alive:
            state.running[RUN] = threading.Event()
        else:
            state.running.pop(RUN, None)
        return
    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.get(WorkflowRun, RUN) or WorkflowRun(execution_id=RUN, workflow_name="wf", workspace_path="/w")
        row.status = "running" if alive else "interrupted"
        session.add(row)
        session.commit()


class TestPickedUpAgain:
    def test_an_open_wait_is_waited_on_again_not_asked_twice(self, state, client, mode):
        _alive(state, mode, True)
        first = Attempt(state, mode).start()
        (wait,) = _until_waiting()
        first.stop()

        second = Attempt(state, mode).start()
        time.sleep(0.2)  # let it reach the gate

        assert [ev["id"] for ev in _open()] == [wait["id"]], "one open wait, the one already asked"
        r = client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": wait["id"], "response": "go"})
        assert r.status_code == 200
        assert second.finish()["response"] == "go"
        assert get_event(wait["id"])["data"]["gate_used_at"]

    def test_an_answer_given_while_the_worker_was_down_is_used_without_asking_again(self, state, client, mode):
        _alive(state, mode, True)
        first = Attempt(state, mode).start()
        (wait,) = _until_waiting()
        first.stop()
        _alive(state, mode, False)

        r = client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": wait["id"], "response": "while down",
                                                                   "by": "Ann (Telegram)"})
        assert r.status_code == 200 and r.json()["needs_resume"] is True
        assert "needs Resume" in r.json()["message"]

        _alive(state, mode, True)
        second = Attempt(state, mode).start()

        assert second.finish()["response"] == "while down"
        assert len(gate_events(RUN, "approve")) == 1, "no new wait was opened"
        used = get_event(wait["id"])
        assert used["status"] == "approved" and used["data"]["gate_used_at"]

    def test_a_used_answer_is_not_used_twice(self, state, client, mode):
        """A looped gate: round 1's answer was used; round 2 asks afresh."""
        _alive(state, mode, True)
        first = Attempt(state, mode).start()
        (wait,) = _until_waiting()
        client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": wait["id"]})
        first.finish()

        second = Attempt(state, mode).start()
        waits = _until_waiting()

        assert [ev["data"]["gate_round"] for ev in waits] == [2]
        assert waits[0]["id"] != wait["id"]
        stale = client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": wait["id"]})
        assert stale.status_code == 409 and stale.json()["detail"]["reason"] == "already_answered"
        assert client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": waits[0]["id"]}).status_code == 200
        second.finish()

    def test_a_wait_from_before_waits_had_paths_is_replaced(self, state, client, mode):
        """An open wait recorded by the old code (no path, no round) is closed, not left to answer twice."""
        _alive(state, mode, True)
        legacy = record(EventType.STAGE_STARTED, execution_id=RUN, status="waiting",
                        data={"name": "approve", "type": "agent", "gate": True, "gate_status": "waiting"})

        attempt = Attempt(state, mode).start()
        (wait,) = _until_waiting()

        assert wait["id"] != legacy and wait["data"]["gate_path"] == "approve"
        old = get_event(legacy)
        assert old["status"] == "replaced" and old["data"]["gate_replaced_by"] == wait["id"]
        r = client.post(f"/api/runs/{RUN}/approve/approve", json={"event_id": legacy})
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "replaced"
        assert client.post(f"/api/runs/{RUN}/approve/approve").status_code == 200, "by name: the one open wait"
        attempt.finish()

    def test_a_kept_answer_from_before_waits_had_paths_is_used(self, state, client, mode):
        """An approval the old code kept for a resume (approve-and-resume) is still the answer."""
        _alive(state, mode, True)
        record(EventType.STAGE_STARTED, execution_id=RUN, status="approved",
               data={"name": "approve", "type": "agent", "gate": True, "gate_status": "approved",
                     "gate_kept_for_resume": True,
                     "gate_response": {"response": "kept", "answers": [], "text": "kept"}})

        assert Attempt(state, mode).start().finish()["response"] == "kept"
        assert _open() == []

    def test_an_attempt_whose_wait_was_taken_over_stops(self, state, mode):
        """A worker still polling a wait that a later attempt replaced is not the run any more."""
        _alive(state, mode, True)
        stale = Attempt(state, "external").start()  # its own registry: invisible to the next one
        (wait,) = _until_waiting()

        from temper_ai.observability.recorder import decide_event
        decide_event(wait["id"], expect=("waiting",), status="replaced",
                     data={"gate_status": "replaced", "gate_replaced_by": "later"})

        assert stale.done.wait(5)
        assert isinstance(stale.error, CancellationError)
        assert "taken over" in str(stale.error)


class TestTwoStages:
    def test_same_named_gates_in_two_stages_are_two_waits(self, state, client):
        _alive(state, "in_process", True)
        a = Attempt(state, "in_process", node_path="build").start()
        b = Attempt(state, "in_process", node_path="ship").start()
        waits = _until_waiting(2)

        assert sorted(ev["data"]["gate_path"] for ev in waits) == ["build.approve", "ship.approve"]
        several = client.post(f"/api/runs/{RUN}/approve/approve")
        assert several.status_code == 409 and several.json()["detail"]["reason"] == "several_waiting"

        assert client.post(f"/api/runs/{RUN}/approve/ship.approve", json={"response": "ship"}).status_code == 200
        assert b.finish()["response"] == "ship"
        assert not a.done.is_set(), "the other stage still waits for its own answer"
        assert client.post(f"/api/runs/{RUN}/approve/approve").status_code == 200
        a.finish()
