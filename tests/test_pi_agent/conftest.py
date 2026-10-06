"""Pi agent step fixtures: a private SQLite file, an in-process Temper with a stub loader, the
stand-in worker, and no network.

Never the live database: the file lives in pytest's tmp dir and tests/conftest.py's guard
checks every init against it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_pi_agent import support as sup


@pytest.fixture(autouse=True)
def _pi_no_network(monkeypatch):
    """Every Pi test runs with IPv4/IPv6 connections refused and counted: zero is the proof
    that no model provider, database server, Redis or webhook was reached."""
    for name in ("TEMPER_REDIS_URL", "REDIS_URL", "TEMPER_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    guard = sup.NetGuard().install(monkeypatch)
    sup.reset_fake()
    yield guard
    sup.reset_fake()
    assert guard.attempts == [], f"network connection attempted: {guard.attempts}"


@pytest.fixture(autouse=True)
def _in_the_pi_lane(monkeypatch):
    """Pi steps run only in the Pi lane: every test here runs as it, with the ordinary test
    step allowed beside the Pi step (support.into_the_pi_lane says why)."""
    sup.into_the_pi_lane(monkeypatch)


@pytest.fixture
def pi(tmp_path, request, monkeypatch):
    from fastapi.testclient import TestClient

    import temper_ai.stage.executor as executor_mod
    from temper_ai.database import init_database, reset_database
    from temper_ai.server import app
    from tests.conftest import TEST_DATABASE_URL

    url = f"sqlite:///{tmp_path / 'pi.db'}"
    reset_database()
    request.node.stash[TEST_DATABASE_URL] = url
    init_database(url)
    box_json = sup.make_box_config(tmp_path / "box")
    monkeypatch.setenv("TEMPER_DATABASE_URL", url)
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(box_json))
    monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
    sup.register_types()
    state = sup.install_app_state()
    yield SimpleNamespace(url=url, client=TestClient(app), state=state, tmp=tmp_path,
                          box_json=box_json, ws=tmp_path / "ws")
    sup.reset_fake()
    sup.stop_running(state)
    sup.unregister_types()
    reset_database()
