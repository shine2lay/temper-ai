"""Fixtures for Pi runs that let go of their worker at an approval.

L2's stand-in Pi (tests/test_pi_agent) behind an in-process Temper: no model, no network.
The database is the tier's Postgres when that runs (tests/pgtier.py), else a private SQLite
file: never the live one (tests/conftest.py checks every init against it).
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tests.test_pi_agent import support as sup
from tests.test_runner.pi_parking import support as pw


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Connections refused and counted: zero is the proof no model or service was reached."""
    for name in ("TEMPER_REDIS_URL", "REDIS_URL", "TEMPER_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    guard = sup.NetGuard().install(monkeypatch)
    sup.reset_fake()
    yield guard
    sup.reset_fake()
    assert guard.attempts == [], f"network connection attempted: {guard.attempts}"


@pytest.fixture(autouse=True)
def _in_the_pi_lane(monkeypatch):
    """Pi steps run only in the Pi lane: every test here runs as it, with this package's
    zero-cost test steps allowed beside the Pi step (support.into_the_pi_lane says why).
    ``pi_team_held_fail`` is test_team_runs.py's HELD_FAIL_TYPE; ``AskNode`` is step_support's
    stand-in for a team stage."""
    from tests.test_runner.pi_parking import step_support

    sup.into_the_pi_lane(monkeypatch, step_support.ASK_TYPE, pw.FAIL_TYPE, pw.VERDICT_TYPE,
                         "pi_team_held_fail", nodes=(step_support.AskNode.__name__,))


@pytest.fixture(autouse=True)
def _team_invariants_after_every_scenario(request):
    """tables.md I1-I8 after every team scenario here, by construction (#37's land check,
    binding 3): every Pi team a run left rows for is checked once the test is over, whether or
    not the test checked it itself. Only tests with a database (``pw_run``) can store rows."""
    if "pw_run" not in request.fixturenames:
        yield
        return
    request.getfixturevalue("pw_run")  # set up first, so it is torn down after this check
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger
    from tests.test_runner.pi_team import support as ts

    before = ts.team_keys(Ledger(get_database().engine))
    yield
    ts.check_all_invariants(Ledger(get_database().engine), before)


@pytest.fixture
def pw_run(tmp_path, request, monkeypatch, _no_network):
    from fastapi.testclient import TestClient

    import temper_ai.stage.executor as executor_mod
    from temper_ai.agent import AGENT_TYPES, register_agent_type
    from temper_ai.database import init_database, reset_database
    from temper_ai.server import app
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        # Threads share the database: a file, not one in-memory connection.
        url = f"sqlite:///{tmp_path / 'pw.db'}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    box_json = sup.make_box_config(tmp_path / "box")
    monkeypatch.setenv("TEMPER_DATABASE_URL", url)
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(box_json))
    monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)

    pw.RAN.clear()
    pw.VERDICT["say"] = "again"
    step_run = sup.StepAgent.run

    def counted(self, input_data, context):
        pw.RAN[self.name] += 1
        return step_run(self, input_data, context)

    monkeypatch.setattr(sup.StepAgent, "run", counted)
    for name, build in pw.WORKFLOWS.items():
        monkeypatch.setitem(sup.WORKFLOWS, name, build)
    sup.register_types()
    register_agent_type(pw.FAIL_TYPE, pw.FailAgent)
    register_agent_type(pw.VERDICT_TYPE, pw.VerdictAgent)
    state = sup.install_app_state()
    yield SimpleNamespace(url=url, client=TestClient(app), state=state, tmp=tmp_path,
                          ws=tmp_path / "ws", net=_no_network)
    sup.reset_fake()
    sup.stop_running(state)
    for thread in [t for t in threading.enumerate() if t.name.startswith("temper-run-")]:
        thread.join(timeout=5)
    sup.unregister_types()
    AGENT_TYPES.pop(pw.FAIL_TYPE, None)
    AGENT_TYPES.pop(pw.VERDICT_TYPE, None)
    if url.startswith("sqlite"):
        reset_database()
