"""The sealed box in real, disposable containers (BS1 model-free gate: G01, G10, G12).

Every container here is labelled temper.test=box-sealed, is named after its test and this
test process (box_fixtures.run_id), runs with --network none, and
holds only a synthetic install tree (tests/test_spawner/box_fixtures.py) whose "secrets"
are synthetic text. No database, model, account or production service is touched. The box
runs a probe in place of the runner; it only runs if the box's own start check passed.

Skipped when docker can't be used here, unless TEMPER_TEST_BOX_REQUIRED=1.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from temper_ai.shared.box_env import BoxEnv
from temper_ai.spawner import box_profile
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.box_seal import WorkerView
from temper_ai.spawner.docker_spawner import DockerSpawner
from tests.test_spawner.box_fixtures import (
    OWN_LABEL,
    SYNTHETIC_MARK,
    BoxDocker,
    Install,
    MemoryStore,
    box_image,
    box_user,
    docker_ok,
    hostile_code,
    image_id,
    run_id,
    swap_dir,
)

pytestmark = [pytest.mark.timeout(900)]

RUN_COMMAND = "/app/.venv/bin/python -m temper_ai.cli.main run-workflow"
ALLOWED = BoxEnv(names=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "TEMPER_DATABASE_URL"}),
                 agent_tools=frozenset({"PATH", "HOME", "WORKSPACE_DIR"}))


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


@pytest.fixture
def install(tmp_path, image) -> Install:
    ref, iid = image
    return Install(tmp_path / "host", user=box_user(), image_ref=ref, image_id=iid).build()


@pytest.fixture(autouse=True)
def sealed_install(monkeypatch):
    for name in ("TEMPER_BOX_ENV", "TEMPER_DOCKER_WORKSPACES", "TEMPER_DOCKER_IMAGE",
                 "TEMPER_SPAWNER", "TEMPER_EXECUTION_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(box_profile.BOUNDARY_ENV, box_profile.SEALED)
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", RUN_COMMAND)
    yield
    left = subprocess.run(["docker", "ps", "-aq", "--filter", f"label={OWN_LABEL}"],
                          capture_output=True, text=True, timeout=60)
    for cid in left.stdout.split():
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=60)


def _spawner(install: Install, store: MemoryStore, docker: BoxDocker) -> DockerSpawner:
    return DockerSpawner(
        template_container="worker-self",
        workspace_lookup=lambda eid: store.rows[eid]["workspace"],
        run=docker, box_env=lambda: ALLOWED, profile_store=store,
        worker_view=WorkerView(None), engine_launches=install.engine_table(),
    )


def _start(install: Install, eid: str, workspace, *, before_run=None,
           store: MemoryStore | None = None) -> tuple[MemoryStore, BoxDocker]:
    store = store or MemoryStore()
    store.add(eid, workspace=str(workspace), status="queued")
    docker = BoxDocker(install, before_run=before_run)
    _spawner(install, store, docker).spawn(eid)
    return store, docker


def _probe(workspace) -> dict:
    return json.loads((workspace / "probe.json").read_text())


def _refused(install: Install, eid: str, workspace, before_run, *expect: str) -> str:
    with pytest.raises(SpawnerError) as caught:
        _start(install, eid, workspace, before_run=before_run)
    message = str(caught.value)
    assert "box refused" in message, message
    for text in expect:
        assert text in message, message
    for ws in (install.run_a, install.run_b):
        if ws.is_dir():
            assert not (ws / "probe.json").exists()
            assert not (ws / "PWNED").exists()
    return message


# -- G01: two runs, every alias ---------------------------------------------------------------


def test_two_sealed_runs_see_only_their_own_folder(install):
    run_a, run_b = run_id("run-a-1"), run_id("run-b-1")
    store, _ = _start(install, run_a, install.run_a)
    _start(install, run_b, install.run_b, store=store)

    a, b = _probe(install.run_a), _probe(install.run_b)
    assert a["own_write"] and b["own_write"]
    assert a["own_marks"] == [f"mark-{run_a}"] and b["own_marks"] == [f"mark-{run_b}"]
    assert not a["present"][str(install.run_b)] and not b["present"][str(install.run_a)]
    for probe in (a, b):
        shown = sorted(p for p, there in probe["present"].items()
                       if there and p not in (str(install.run_a), str(install.run_b),
                                              str(install.data)))
        assert shown == [], f"a sealed box shows {shown}"
        assert probe["data_read"] and not probe["data_write"]
        assert probe["tmp_write"]
        written = sorted(p for p, ok in probe["writable"].items() if ok and p != "/tmp")
        assert written == [], f"a tool could change {written}"
        assert not any(probe["shadowed"].values()), probe["shadowed"]
        assert probe["claude"] == "fake-claude 2.1.10"
        assert probe["uid"] == os.getuid() and probe["uid"] != 0
        assert not probe["env_has_mark"]
        assert "SYNTH_SERVICE_TOKEN" not in probe["env_names"]
        assert "PYTHONPATH" not in probe["env_names"]
    for eid in (run_a, run_b):
        doc = store.record(eid)["doc"]
        assert doc["boundary"] == "sealed" and doc["hardening"] == "partial"
        assert [g["class"] for g in doc["network_graph"]] == ["runner+tools (mixed, in-process)"]
        assert doc["network_graph"][0]["enforcer"] is None
        assert doc["closure"]["network"] == "negative"
        steps = {r.get("step") for r in doc["residuals"]}
        assert {"BS2", "BS3", "BS4", "BS5", "BS6"} <= steps
        assert not any(SYNTHETIC_MARK in json.dumps(r) for r in store.rows[eid].values()
                       if isinstance(r, dict))


def test_the_profile_records_no_key_views_and_pins_every_grant(install):
    eid = run_id("run-a-2")
    store, docker = _start(install, eid, install.run_a)
    doc = store.record(eid)["doc"]
    targets = {g["target"]: g for g in doc["grants"]}
    assert set(targets) == {
        "/app/temper_ai", "/app/configs", "/app/local/__init__.py",
        "/app/local/register_providers.py", "/app/local/providers", "/app/local/agents",
        "/app/.local/bin/claude", str(install.run_a), "/app/shared-data"}
    assert all(g["pin"]["ino"] for g in doc["grants"])
    assert [t for t, g in targets.items() if not g["read_only"]] == [str(install.run_a)]
    for gone in ("/app/repo", "/app/workspaces", "/app/.env", "/app/standee-ssh",
                 "/app/github-deploy", "/app/.claude/.credentials.json", "/app/command-center",
                 "/var/run/docker.sock", "/opt/claude/versions", "/app/local/standee-ssh"):
        assert gone in doc["runtime"]["absent"], gone
    args = list(docker.runs[0].args)
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "--mount"]
    assert len(mounts) == len(targets)
    assert not [m for m in mounts if "docker.sock" in m or str(install.repo) in m
                or str(install.local / "standee-ssh") in m or str(install.creds) in m]
    cmd = " ".join(args)
    assert "--read-only" in cmd and "--network none" in cmd and "--cap-drop ALL" in cmd


# -- races: a source root changes between the worker's check and docker's use -----------------


def _race(change):
    def hook(cmd):
        change()
        return cmd
    return hook


def test_a_swapped_workspace_is_refused(install):
    _refused(install, run_id("race-ws"), install.run_a,
             _race(lambda: swap_dir(install.run_a, lambda p: p.mkdir(mode=0o777))),
             "swapped")


def test_a_workspace_swapped_for_a_link_to_another_run_is_refused(install):
    _refused(install, run_id("race-link"), install.run_a,
             _race(lambda: swap_dir(install.run_a, lambda p: p.symlink_to(install.run_b))),
             "swapped")
    assert not list(install.run_b.iterdir())


def test_a_swapped_workspaces_parent_is_refused(install):
    def change():
        swap_dir(install.workspaces, lambda p: (p / "run-a").mkdir(parents=True, mode=0o777))
    _refused(install, run_id("race-parent"), install.run_a, _race(change), "swapped")


def test_a_swapped_code_root_never_runs(install):
    _refused(install, run_id("race-code"), install.run_a,
             _race(lambda: swap_dir(install.code, hostile_code)), "/app/temper_ai", "swapped")


def test_a_swapped_claude_binary_is_refused(install):
    def change():
        newest = install.versions / "2.1.10"
        newest.rename(install.versions / "2.1.10.moved")
        newest.write_text("#!/bin/sh\necho evil\n")
        newest.chmod(0o755)
    _refused(install, run_id("race-claude"), install.run_a, _race(change),
             "/app/.local/bin/claude")


# -- a box that isn't what its profile says ---------------------------------------------------


def _without_mount(target: str):
    def hook(cmd):
        out = []
        for i, part in enumerate(cmd):
            if part == "--mount" and f"target={target}" in cmd[i + 1].split(","):
                continue
            if i and cmd[i - 1] == "--mount" and f"target={target}" in part.split(","):
                continue
            out.append(part)
        return out
    return hook


def test_a_missing_grant_is_refused_before_tools(install):
    _refused(install, run_id("tamper-missing"), install.run_a, _without_mount(str(install.run_a)),
             "granted but not mounted")


def test_an_extra_mount_of_the_main_repo_is_refused(install):
    def hook(cmd):
        at = cmd.index("--entrypoint")
        return [*cmd[:at], "--mount", f"type=bind,source={install.repo},target=/app/repo,readonly",
                *cmd[at:]]
    _refused(install, run_id("tamper-repo"), install.run_a, hook, "/app/repo")


def test_writable_runner_code_is_refused(install):
    def hook(cmd):
        return [c.replace(",readonly", "") if "target=/app/temper_ai" in c else c for c in cmd]
    _refused(install, run_id("tamper-code-rw"), install.run_a, hook,
             "/app/temper_ai is mounted writable")


def test_a_writable_root_filesystem_is_refused(install):
    _refused(install, run_id("tamper-root-rw"), install.run_a,
             lambda cmd: [c for c in cmd if c != "--read-only"], "root filesystem is writable")


def test_a_box_that_can_gain_privileges_is_refused(install):
    def hook(cmd):
        at = cmd.index("no-new-privileges")
        return cmd[:at - 1] + cmd[at + 1:]
    _refused(install, run_id("tamper-nnp"), install.run_a, hook, "gain privileges")


def test_a_root_box_is_refused(install):
    def hook(cmd):
        at = cmd.index("--user")
        return [*cmd[:at + 1], "0:0", *cmd[at + 2:]]
    _refused(install, run_id("tamper-root"), install.run_a, hook, "runs as root")


def test_a_changed_profile_is_refused(install):
    def hook(cmd):
        out = list(cmd)
        for i, part in enumerate(out):
            if part.startswith(f"{box_profile.PROFILE_ENV}="):
                doc = json.loads(part.split("=", 1)[1])
                doc["grants"] = [g for g in doc["grants"] if g["kind"] != "workspace"]
                out[i] = f"{box_profile.PROFILE_ENV}={box_profile.canonical(doc)}"
        return out
    _refused(install, run_id("tamper-profile"), install.run_a, hook, "digest")
