"""Fixtures for the Pi lane's tests (docs/pi-lane.md).

The server's side by default: this process is not the Pi lane, the execution mode is
external (production's), and runs are only written, never started. No model, no network and
no Docker are reached. The database is the tier's Postgres when that runs (tests/pgtier.py),
else a private SQLite file: never the live one (tests/conftest.py checks every init).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_pi_agent import support as sup
from tests.test_runner.pi_lane import support as ls


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Connections refused and counted: zero is the proof no model or service was reached."""
    for name in ("TEMPER_REDIS_URL", "REDIS_URL", "TEMPER_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    guard = sup.NetGuard().install(monkeypatch)
    yield guard
    assert guard.attempts == [], f"network connection attempted: {guard.attempts}"


@pytest.fixture(autouse=True)
def _not_the_pi_lane(monkeypatch):
    """No lane and no Pi switch unless a test sets them (tests/conftest.py clears the lane)."""
    monkeypatch.delenv("TEMPER_PI_AGENT", raising=False)
    monkeypatch.delenv("TEMPER_PI_BOX_CONFIG", raising=False)


@pytest.fixture
def srv(tmp_path, request, monkeypatch):
    """The temper server with the lane tests' workflows, in external mode."""
    from fastapi.testclient import TestClient

    from temper_ai.database import init_database, reset_database
    from temper_ai.server import app
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        # Threads share the database: a file, not one in-memory connection.
        url = f"sqlite:///{tmp_path / 'lane.db'}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    monkeypatch.setenv("TEMPER_DATABASE_URL", url)
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    for name, build in ls.WORKFLOWS.items():
        monkeypatch.setitem(sup.WORKFLOWS, name, build)
    state = sup.install_app_state()
    ws = tmp_path / "ws"
    ws.mkdir()
    yield SimpleNamespace(url=url, client=TestClient(app), state=state, tmp=tmp_path, ws=ws)
    if url.startswith("sqlite"):
        reset_database()
