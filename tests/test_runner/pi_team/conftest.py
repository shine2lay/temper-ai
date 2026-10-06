"""Fixtures for team messaging tests: the ledger on SQLite or the tier's Postgres, L2's box
config, scripted members, and no network.

The database is the tier's Postgres when that runs (tests/pgtier.py), else a private SQLite
file that several connections (threads, processes) can share: never the live one.
"""

from __future__ import annotations

import pytest

from temper_ai.pi_agent.ledger import Ledger
from temper_ai.pi_agent.team_runtime import Team
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_team import support as ts


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Connections refused and counted: zero is the proof no model or service was reached."""
    guard = sup.NetGuard().install(monkeypatch)
    ts.reset()
    Team.turn_runner = ts.fake_runner
    Team.stop_box = ts.Stopper()
    yield guard
    ts.reset()
    assert guard.attempts == [], f"network connection attempted: {guard.attempts}"


@pytest.fixture(autouse=True)
def _in_the_pi_lane(monkeypatch):
    """Pi steps run only in the Pi lane: every test here runs as it, with the ordinary test
    step allowed beside the Pi step (tests/test_pi_agent/support.into_the_pi_lane says why)."""
    sup.into_the_pi_lane(monkeypatch)


@pytest.fixture(autouse=True)
def _invariants_after_every_scenario(request):
    """tables.md I1-I8 after every team scenario, by construction (#37's land check, binding 3):
    every team a test left rows for is checked once the test is over, whether or not the test
    checked it itself. A test that stores rows takes ``led``; one that does not stores none."""
    if "led" not in request.fixturenames:
        yield
        return
    led = request.getfixturevalue("led")  # set up first, so it is torn down after this check
    before = ts.team_keys(led)
    yield
    ts.check_all_invariants(led, before)


@pytest.fixture
def db_url(request, tmp_path) -> str:
    """The URL every connection of this test uses (a child process too)."""
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        return f"sqlite:///{tmp_path / 'team.db'}"
    return url


@pytest.fixture
def led(db_url) -> Ledger:
    from temper_ai.database.engine import create_test_engine

    if db_url.startswith("sqlite"):
        engine = create_test_engine(db_url)
    else:
        from temper_ai.database import get_database

        engine = get_database().engine
    ledger = Ledger(engine)
    ledger.ensure()
    yield ledger
    if db_url.startswith("sqlite"):
        engine.dispose()


@pytest.fixture
def box(tmp_path):
    return sup.box_config(tmp_path / "box")


@pytest.fixture
def run_id() -> str:
    return ts.new_run()
