"""The committed zero-cost Pi workflow, ``ci_pi_waits``, loaded from configs/ as the server
loads it and run on L2's stand-in box: what the live check does, with no model."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"


@pytest.fixture
def ci(pw_run):
    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import init_app_state
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.config import ConfigStore
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.stage.loader import GraphLoader

    st = AppState(config_store=ConfigStore(),
                  graph_loader=GraphLoader(_FileConfigs(REPO_CONFIGS)),  # type: ignore[arg-type]
                  llm_providers={"mock": MagicMock()},
                  memory_service=MemoryService(InMemoryStore()))
    init_app_state(st)
    pw_run.state = st
    return pw_run


def _answer(ci, eid: str, name: str, n_attempts: int) -> None:
    pw.wait_parked(ci.state, eid, n_attempts=n_attempts)
    gate = pw.open_gate(ci.client, eid, name)
    r = pw.approve(ci.client, eid, name, event_id=gate["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text


def test_ci_pi_waits_ships_after_two_answers_and_one_pi_turn(ci):
    eid = sup.start(ci.client, "ci_pi_waits", ci.ws, {"verdict": "done"})
    _answer(ci, eid, "ask", 1)  # the first node: nothing ran before it
    n = pw.finish_pi(ci.client, eid)  # the Pi step's own wait lets go too (C7)
    _answer(ci, eid, "review", n)
    attempts = pw.wait_ended(eid, n + 1)
    assert [a["status"] for a in attempts] == ["parked"] * 3 + ["completed"]
    assert len(FakeBox.STARTS) == 1
    for name in ("ask", "talk", "review", "ship"):
        assert sup.node_status(eid, name).count("completed") == 1, name


def test_ci_pi_waits_goes_red_when_its_loop_runs_out(ci):
    eid = sup.start(ci.client, "ci_pi_waits", ci.ws, {"verdict": "again"})
    _answer(ci, eid, "ask", 1)
    n = pw.finish_pi(ci.client, eid)
    _answer(ci, eid, "review", n)
    _answer(ci, eid, "review", n + 1)
    attempts = pw.wait_ended(eid, n + 2)
    assert [a["status"] for a in attempts] == ["parked"] * 4 + ["failed"]
    assert "ran out of rounds: 2 of 2" in str(sup.events(eid, event_type="stage.started"))
    assert "completed" not in sup.node_status(eid, "ship")
