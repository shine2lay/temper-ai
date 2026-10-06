"""H1 (HOME-REVIEW, SW-75): the subprocess spawner beside a Docker socket only in the Pi lane.

A run started as a child process shares its worker's Docker socket, which is the host. So
``TEMPER_SPAWNER=subprocess`` in a process that can reach Docker is refused everywhere except
the Pi lane (``TEMPER_LANE=pi``), whose runs are Pi runs that start only their member boxes;
and a watcher that is refused never starts. The Pi lane itself refuses to start without its
own settings. tests/conftest.py hides this host's socket from every other test.
"""

from __future__ import annotations

import argparse
import logging
from types import SimpleNamespace

import pytest

from temper_ai.cli import watch_queue as wq
from temper_ai.runner import pi_lane
from temper_ai.runner.lanes import LaneSettingError
from temper_ai.spawner import factory
from temper_ai.spawner.factory import SubprocessBesideDocker, get_spawner, reset_spawner
from temper_ai.spawner.subprocess_spawner import SubprocessSpawner
from temper_ai.worker_proto import SpawnerKind


@pytest.fixture(autouse=True)
def _fresh_spawner():
    reset_spawner()
    yield
    reset_spawner()


@pytest.fixture
def docker_socket(tmp_path, monkeypatch):
    """This process can reach Docker: a socket where Docker's is."""
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setattr(factory, "DOCKER_SOCKETS", ("/nonexistent/docker.sock", str(sock)))
    return sock


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    """``temper watch-queue`` as a service starts it, on a private database: returns its
    exit code, and fails the test if it got as far as watching."""
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{tmp_path / 'watch.db'}")
    monkeypatch.setattr(wq, "_requeue_stuck_claims", _started)

    def start() -> int:
        return wq.cmd_watch_queue(argparse.Namespace(poll_interval=0.01, reaper_interval=60))

    return start


def _started(*args, **kwargs):
    raise AssertionError("the watcher started")


# --- The spawner -----------------------------------------------------------------------------


def test_without_docker_the_subprocess_spawner_is_as_before():
    assert isinstance(get_spawner("subprocess"), SubprocessSpawner)


def test_beside_a_docker_socket_it_is_refused_outside_the_pi_lane(docker_socket):
    with pytest.raises(SubprocessBesideDocker) as refused:
        get_spawner("subprocess")
    assert str(refused.value).startswith(
        f"TEMPER_SPAWNER=subprocess in a process that can reach Docker ({docker_socket}): its "
        f"runs would hold the host's Docker socket.")


def test_a_docker_host_setting_counts_as_reaching_docker(monkeypatch):
    monkeypatch.setattr(factory, "DOCKER_HOST_ENVS", ("DOCKER_HOST",))
    monkeypatch.setenv("DOCKER_HOST", "tcp://10.0.0.2:2375")
    with pytest.raises(SubprocessBesideDocker, match=r"can reach Docker \(DOCKER_HOST\)"):
        get_spawner("subprocess")


def test_the_pi_lane_runs_its_runs_as_child_processes_beside_the_socket(docker_socket,
                                                                         monkeypatch):
    monkeypatch.setenv("TEMPER_LANE", "pi")
    assert isinstance(get_spawner("subprocess"), SubprocessSpawner)


def test_a_lane_setting_temper_doesn_t_know_refuses_too(docker_socket, monkeypatch):
    monkeypatch.setenv("TEMPER_LANE", "pi2")
    with pytest.raises(LaneSettingError):
        get_spawner("subprocess")


def test_a_server_in_subprocess_mode_beside_a_socket_starts_nothing(docker_socket, monkeypatch):
    """The server's own subprocess mode gets the spawner the same way: refused."""
    monkeypatch.setenv("TEMPER_SPAWNER", "subprocess")
    with pytest.raises(SubprocessBesideDocker):
        get_spawner()


# --- The watcher -----------------------------------------------------------------------------


def test_a_watcher_given_the_socket_without_the_pi_lane_setting_won_t_start(
        watcher, docker_socket, monkeypatch, caplog):
    monkeypatch.setenv("TEMPER_SPAWNER", "subprocess")
    with caplog.at_level(logging.ERROR, logger=wq.logger.name):
        assert watcher() == 2
    assert "Watcher won't start: TEMPER_SPAWNER=subprocess in a process that can reach " \
           "Docker" in caplog.text


def test_a_watcher_with_a_lane_setting_temper_doesn_t_know_won_t_start(watcher, monkeypatch,
                                                                        caplog):
    monkeypatch.setenv("TEMPER_LANE", "Pi")
    with caplog.at_level(logging.ERROR, logger=wq.logger.name):
        assert watcher() == 2
    assert "TEMPER_LANE='Pi' is not a lane temper knows (pi)" in caplog.text


@pytest.mark.parametrize("kind,switch,problem", [
    (SpawnerKind.docker, "1", "the Pi lane starts its runs as child processes "
                              "(TEMPER_SPAWNER=subprocess), not with the docker spawner"),
    (SpawnerKind.subprocess, "", "the Pi lane needs TEMPER_PI_AGENT=1"),
])
def test_the_pi_lane_won_t_start_without_its_own_settings(watcher, monkeypatch, caplog, kind,
                                                         switch, problem):
    monkeypatch.setenv("TEMPER_LANE", "pi")
    monkeypatch.setenv("TEMPER_PI_AGENT", switch)
    monkeypatch.setattr(wq, "get_spawner", lambda: SimpleNamespace(kind=kind))
    monkeypatch.setattr(pi_lane, "start_up", _started)
    with caplog.at_level(logging.ERROR, logger=wq.logger.name):
        assert watcher() == 2
    assert f"The Pi lane won't start: {problem}" in caplog.text


def test_with_its_settings_the_pi_lane_s_watcher_gets_past_its_checks(watcher, docker_socket,
                                                                     monkeypatch):
    """The positive control: socket, lane, subprocess spawner and the switch."""
    monkeypatch.setenv("TEMPER_LANE", "pi")
    monkeypatch.setenv("TEMPER_SPAWNER", "subprocess")
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    monkeypatch.setenv("TEMPER_PI_DRAIN_MARK", str(docker_socket.parent / "drain"))
    reached = []
    monkeypatch.setattr(pi_lane, "eager_import", lambda: reached.append("eager_import"))
    monkeypatch.setattr(pi_lane, "start_up", lambda: reached.append("start_up") or {})
    with pytest.raises(AssertionError, match="the watcher started"):
        watcher()
    assert reached == ["eager_import", "start_up"]
