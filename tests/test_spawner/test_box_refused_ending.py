"""G02: how a box whose runner refused its one-shot delivery may end. No docker.

When a delivery fails the spawner kills the box at once (BS2: "the box was stopped and the
delivery revoked", spawner/docker_spawner.py) and doesn't wait for the runner, which
acknowledges its refusal, waits for the writer to see it, then says why ("box refused:
...") and exits 4 (spawner/box_bootstrap.py, cli/main.py). So in the real-box tests
(test_box_bootstrap_docker.py) a refusing box ends one of two ways: exit 4 from its runner,
or 137 from the spawner's kill, which can land after the runner said why but before it
exited (CI run 37540347760: `assert 137 == 4`), or before it said why. The kill counts
only when the tests' docker wrapper recorded the spawner's own `docker kill <name>` of
that box and docker took it.
"""

from __future__ import annotations

import subprocess

import pytest

from temper_ai.spawner import box_bootstrap
from tests.test_spawner.test_box_bootstrap_docker import (
    KILLED_EXIT,
    OneshotDocker,
    _refused_ending,
)

REFUSED = box_bootstrap.REFUSED_EXIT


def test_the_two_endings_are_the_runners_4_and_the_kills_137():
    assert (REFUSED, KILLED_EXIT) == (4, 137)


@pytest.mark.parametrize(("code", "killed", "said"), [
    (REFUSED, False, True),
    (REFUSED, True, True),  # the runner ended itself before docker delivered the kill
    (KILLED_EXIT, True, True),  # the old rule (== REFUSED_EXIT) failed this one
    (KILLED_EXIT, True, False),
], ids=["4", "4, killed too", "137 killed after it said why (CI run 37540347760)",
        "137 killed before it said why"])
def test_a_refusing_box_ends_by_its_runner_or_by_the_spawners_kill(code, killed, said):
    _refused_ending(code, killed=killed, said=said)


@pytest.mark.parametrize(("code", "killed", "said"), [
    (KILLED_EXIT, False, True),
    (KILLED_EXIT, False, False),
    (REFUSED, False, False),
    (REFUSED, True, False),
    *[(code, killed, True) for code in (143, 0, 1) for killed in (True, False)],
], ids=["137, no kill recorded", "137, no kill recorded, said nothing",
        "4 without saying why", "4 without saying why, killed too",
        "143 killed", "143", "0 killed", "0", "1 killed", "1"])
def test_any_other_ending_fails_and_names_its_code(code, killed, said):
    with pytest.raises(AssertionError, match=rf"exit code {code}\b"):
        _refused_ending(code, killed=killed, said=said)


def test_the_wrapper_counts_only_a_kill_of_that_box_docker_took(monkeypatch):
    """OneshotDocker keeps each `docker kill` the spawner runs; killed(name) is true only
    for `docker kill <name>` that docker took (exit 0)."""
    turned_down = {"box-b"}  # docker kill on a box that had ended: "is not running", exit 1

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, int(cmd[-1] in turned_down), "", "")

    monkeypatch.setattr(subprocess, "run", run)
    docker = OneshotDocker(install=None)
    for cmd in (["docker", "kill", "box-a"], ["docker", "kill", "box-b"],
                ["docker", "kill", "--signal", "TERM", "box-c"], ["docker", "exec", "box-d"]):
        docker(cmd)
    assert [k.args[-1] for k in docker.kills] == ["box-a", "box-b", "box-c"]
    assert docker.killed("box-a")
    assert not docker.killed("box-b")  # it had ended before the kill came
    assert not docker.killed("box-c")  # a SIGTERM stop doesn't end a box with 137
    assert not docker.killed("box-d")  # never killed
