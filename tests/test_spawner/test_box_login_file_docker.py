"""The login file from TEMPER_BOX_LOGIN_FILE in real, disposable legacy boxes (queue #73).

The host's Claude CLI replaces its login file by rename at every login refresh. A bind keeps
the file it found when its container started; a legacy box binds the setting's host path at
each start, so a box started after a refresh reads the new file. The template here still has
its own bind at the same target, which docker would refuse twice ("Duplicate mount point").

Synthetic text only: no real login, model, account or production service is touched, and the
boxes run with --network none (box_fixtures.Install). The box's program only prints the file.

Skipped when docker can't be used here, unless TEMPER_TEST_BOX_REQUIRED=1.
"""

from __future__ import annotations

import os

import pytest

from temper_ai.shared.box_env import BoxEnv
from temper_ai.spawner import box_profile
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.box_seal import WorkerView
from temper_ai.spawner.docker_spawner import (
    LOGIN_FILE_ENV,
    LOGIN_FILE_TARGET,
    DockerSpawner,
)
from tests.test_spawner.box_fixtures import (
    BoxDocker,
    Install,
    MemoryStore,
    box_image,
    box_user,
    docker_ok,
    image_id,
    run_id,
)

pytestmark = [pytest.mark.timeout(600)]

ALLOWED = BoxEnv(names=frozenset({"PATH", "HOME"}), agent_tools=frozenset({"PATH", "HOME"}))


def _unavailable(why: str) -> None:
    if os.environ.get("TEMPER_TEST_BOX_REQUIRED") == "1":
        pytest.fail(f"the real-container box gate can't run: {why}")
    pytest.skip(f"the real-container box gate can't run here: {why}")


@pytest.fixture(scope="module")
def image() -> tuple[str, str]:
    if not docker_ok():
        _unavailable("no docker")
    ref = box_image()
    if ref is None:
        _unavailable("no image (TEMPER_TEST_BOX_IMAGE, temper-ci-server or python:3.12-slim)")
    return ref, image_id(ref)


def _write(path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o644)  # the box's user is the image's, not this one


def test_a_login_file_replaced_by_rename_reaches_the_next_box(image, tmp_path, monkeypatch):
    for name in (box_profile.BOUNDARY_ENV, box_profile.BOOTSTRAP_ENV, "TEMPER_BOX_ENV",
                 "TEMPER_DOCKER_WORKSPACES", "TEMPER_DOCKER_IMAGE", LOGIN_FILE_ENV):
        monkeypatch.delenv(name, raising=False)
    # The box prints the login file in place of the runner (sh -c gets --execution-id as $0).
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", f"sh -c 'cat {LOGIN_FILE_TARGET}'")
    install = Install(tmp_path / "host", user=box_user(), image_ref=image[0],
                      image_id=image[1]).build()
    login = tmp_path / "host-login" / ".credentials.json"
    login.parent.mkdir()
    _write(login, "first synthetic login\n")
    first, second, third = run_id("login-first"), run_id("login-second"), run_id("login-gone")
    store = MemoryStore()
    for execution_id in (first, second, third):
        store.add(execution_id, workspace=str(install.run_a))
    docker = BoxDocker(install)
    spawner = DockerSpawner(
        template_container="worker-self", workspace_lookup=lambda eid: store.rows[eid]["workspace"],
        run=docker, box_env=lambda: ALLOWED, profile_store=store, worker_view=WorkerView(None),
        login_file=str(login),
    )

    spawner.spawn(first)
    assert docker.runs[-1].returncode == 0, docker.runs[-1].stderr
    assert docker.runs[-1].stdout == "first synthetic login\n"

    # What the Claude CLI does at a refresh: a new file, renamed over the old one.
    replacement = login.with_name(".credentials.json.new")
    _write(replacement, "second synthetic login\n")
    old_inode = login.stat().st_ino
    os.replace(replacement, login)
    assert login.stat().st_ino != old_inode

    spawner.spawn(second)
    assert docker.runs[-1].returncode == 0, docker.runs[-1].stderr
    assert docker.runs[-1].stdout == "second synthetic login\n"
    for execution_id in (first, second):
        assert store.record(execution_id)["doc"]["runtime"]["login_file"] == {
            "from": LOGIN_FILE_ENV, "source": str(login), "target": LOGIN_FILE_TARGET,
            "read_only": True}

    # No file at the path: docker refuses the box, nothing starts without it.
    login.unlink()
    with pytest.raises(SpawnerError, match=r"exit \d+"):
        spawner.spawn(third)
    assert docker.runs[-1].returncode != 0 and docker.runs[-1].stdout == ""
