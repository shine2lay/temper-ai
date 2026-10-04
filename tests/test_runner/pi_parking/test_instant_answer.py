"""An approval that comes the very instant a wait can first be answered (#39's finding 1).

A gate opens its wait in two parts: the in-process signal the API can set, and the waiting
event that names the wait for everyone else. An approval sent in the instant between the two
used to find only the signal: it was answered there, with neither its request id nor who sent
it written down, so the same request sent again got a 409 instead of its first answer; in a
Pi workflow the run then let its worker go at a wait the owner had already answered.

Here the approval is sent from inside the run, at the first moment either part exists (the
signal registered, or the waiting event recorded), so that instant happens every time. The
wait must keep the request id and who answered, and the same request sent again must get
``repeated: true`` with the first answer (temper_ai/stage/executor.py ``_wait_for_gate``).
Nothing reaches a model or the network (pi_parking/conftest.py's guard).
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from temper_ai.stage.gate import GateSignal
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw


class _FirstChance:
    """Sends one approval of the step ``node`` the first moment its wait can be answered."""

    def __init__(self, node: str, body: dict[str, Any], *, use_event_id: bool) -> None:
        from fastapi.testclient import TestClient

        from temper_ai.server import app

        self.node, self.body, self.use_event_id = node, body, use_event_id
        self.client = TestClient(app)
        self.reply: Any = None
        self.when = ""
        self.execution_id = ""
        self._lock = threading.Lock()

    def fire(self, execution_id: str, event_id: str, when: str) -> None:
        with self._lock:
            if self.reply is not None:
                return
            body = {**self.body, **({"event_id": event_id} if self.use_event_id else {})}
            self.when, self.execution_id = when, execution_id
            self.reply = self.client.post(f"/api/runs/{execution_id}/approve/{self.node}",
                                          json=body)

    def install(self, state, monkeypatch) -> _FirstChance:
        from temper_ai.observability.event_recorder import EventRecorder

        chance = self

        class Registry(dict):
            """The server's gate registry, noticing a wait's signal as it is registered."""

            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, GateSignal) and value.node_name == chance.node:
                    chance.fire(key.split(":", 1)[0], value.event_id, "signal registered")

        record = EventRecorder.record

        def noticing(recorder, event_type, data=None, parent_id=None, execution_id=None,
                     status=None, event_id=None):
            out = record(recorder, event_type, data, parent_id, execution_id, status, event_id)
            if (status == "waiting" and (data or {}).get("gate")
                    and (data or {}).get("name") == chance.node):
                chance.fire(execution_id or recorder.execution_id, out, "waiting event recorded")
            return out

        monkeypatch.setattr(state, "gates", Registry())
        monkeypatch.setattr(EventRecorder, "record", noticing)
        return self


BODY = {"request_id": "instant-1", "by": "Owner", "response": "go ahead"}


def _kept_who_and_which(wait: dict) -> None:
    data = wait["data"]
    assert data.get("gate_request_id") == "instant-1", data
    assert data.get("gate_decided_by") == "Owner", data
    assert data.get("gate_decided_at"), data


def _sent_again_gets_the_first_answer(c, eid: str, first, *, use_event_id: bool, wait: dict) -> None:
    body = {**BODY, **({"event_id": wait["id"]} if use_event_id else {})}
    again = c.post(f"/api/runs/{eid}/approve/check", json=body)
    assert again.status_code == 200, again.text
    out = again.json()
    assert out["repeated"] is True, out
    assert out["event_id"] == wait["id"] and out["answered_by"] == "Owner"
    assert out["request_id"] == "instant-1"
    assert out["response"] == first.reply.json()["response"]


@pytest.mark.parametrize("use_event_id", [False, True], ids=["by_name", "by_event_id"])
def test_an_answer_in_the_first_instant_keeps_its_request_id_and_who_sent_it(
        pw_run, monkeypatch, use_event_id):
    """A workflow without a Pi step: the gate holds its worker and goes on with the answer."""
    c = pw_run.client
    first = _FirstChance("check", BODY, use_event_id=use_event_id).install(pw_run.state,
                                                                           monkeypatch)
    eid = sup.start(c, "plain_gate", pw_run.ws)
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["completed"]
    assert first.reply is not None and first.execution_id == eid
    assert first.reply.status_code == 200, first.reply.text
    assert first.reply.json()["answered_by"] == "Owner", (first.when, first.reply.json())

    (wait,) = pw.waits(eid, "check")
    assert wait["status"] == "approved" and wait["data"].get("gate_used_at")
    _kept_who_and_which(wait)
    _sent_again_gets_the_first_answer(c, eid, first, use_event_id=use_event_id, wait=wait)
    assert pw.RAN == {"brief": 1, "check": 1, "ship": 1}


def test_an_answer_in_the_first_instant_of_a_pi_wait_is_kept_and_carries_the_run_on(
        pw_run, monkeypatch):
    """A Pi workflow lets its worker go at the gate: the answer it was given in that first
    instant is the wait's answer, and carries the run on (it was lost before)."""
    c, state = pw_run.client, pw_run.state
    first = _FirstChance("check", BODY, use_event_id=False).install(state, monkeypatch)
    eid = sup.start(c, "pw_before_pi", pw_run.ws)

    def answered_or_lost():
        waits = pw.waits(eid, "check")
        if waits and waits[0]["status"] == "approved":
            return "answered"
        a = pw.attempts(eid)
        if (waits and a and a[-1]["status"] == "waiting" and pw.parked(a[-1])
                and eid not in state.running and not pw.run_threads(eid)):
            return "lost"
        return None

    assert sup.wait_for(answered_or_lost, what="the first instant's answer") == "answered", (
        f"the run let go at a wait the owner had answered: {first.when}, "
        f"{first.reply.json() if first.reply is not None else None}")
    pw.finish_pi(c, eid)
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert first.reply.status_code == 200, first.reply.text

    (wait,) = pw.waits(eid, "check")
    assert wait["status"] == "approved" and wait["data"].get("gate_used_at")
    _kept_who_and_which(wait)
    _sent_again_gets_the_first_answer(c, eid, first, use_event_id=False, wait=wait)
    assert pw.RAN == {"brief": 1, "check": 1} and len(FakeBox.STARTS) == 1
