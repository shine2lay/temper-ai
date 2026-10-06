"""The committed zero-cost Pi workflow, ``ci_pi_waits``, loaded from configs/ as the server
loads it and run on L2's stand-in box, with no model.

The Pi lane runs only Pi steps, team stages of Pi members and gates, so it refuses
``ci_pi_waits`` at submit for its script steps (the first test). The tests after it allow
script steps beside the Pi step, for this file only, to prove parking on the committed
config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"


@pytest.fixture
def ci_as_committed(pw_run):
    return _with_repo_configs(pw_run)


@pytest.fixture
def ci(pw_run, monkeypatch):
    """Script steps allowed beside the Pi step, for this file only (see the module's note)."""
    from temper_ai.runner import lanes

    monkeypatch.setattr(lanes, "PI_LANE_AGENT_TYPES", (*lanes.PI_LANE_AGENT_TYPES, "script"))
    return _with_repo_configs(pw_run)


def _with_repo_configs(pw_run):
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


def test_the_pi_lane_refuses_ci_pi_waits_at_submit_naming_its_script_steps(ci_as_committed):
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    ci_as_committed.ws.mkdir(parents=True, exist_ok=True)
    r = ci_as_committed.client.post(
        "/api/runs", json={"workflow": "ci_pi_waits", "inputs": {"verdict": "done"},
                           "workspace_path": str(ci_as_committed.ws)})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "runs in the Pi lane" in detail
    for name in ("ask", "review", "ship"):
        assert f"'{name}' is a script step" in detail, detail
    assert "'talk'" not in detail  # the Pi step itself is the lane's
    with get_session() as session:
        assert session.exec(select(WorkflowRun)).all() == []  # never became a run


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
