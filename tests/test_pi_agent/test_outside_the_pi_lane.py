"""A Pi step outside the Pi lane refuses (M4 SW-42): the backstop behind the lane mark.

The run process already refuses a Pi run a worker other than the Pi lane claimed
(runner/pi_lane.py check_run; tests/test_runner/pi_lane/test_run_gate.py). Should a Pi step
still be reached outside the lane, the step itself refuses first: no box, no ledger row, no
model. The team stage's own refusal is in tests/test_runner/pi_parking/.
"""

from __future__ import annotations

import json

from temper_ai.pi_agent import host as host_mod
from temper_ai.runner.lanes import OUTSIDE_PI_LANE
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox


def _said(eid: str, text: str) -> bool:
    return any(text in json.dumps(e.get("data") or {}) for e in sup.events(eid))


def test_a_pi_step_outside_the_pi_lane_refuses_before_its_box_or_ledger(pi, monkeypatch):
    monkeypatch.setattr(host_mod, "in_pi_lane", lambda: False)
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert sup.node_status(eid, "talk")[-1] == "failed"
    assert _said(eid, f"{OUTSIDE_PI_LANE}: this worker isn't the Pi lane, so the step did "
                      f"not start")
    assert FakeBox.STARTS == []
    snap = sup.ledger().snapshot(eid)
    assert {name: rows for name, rows in snap.items() if rows} == {}


def test_the_same_step_in_the_pi_lane_gets_as_far_as_its_box(pi):
    """The positive control: in the lane, the step passes the check and starts its box."""
    FakeBox.behaviour = "provider_error"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert len(FakeBox.STARTS) == 1
    assert not _said(eid, OUTSIDE_PI_LANE)
