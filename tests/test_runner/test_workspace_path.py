"""F-WS: one workspace rule at admission and legacy bind construction.

Whole-feature happy path first; no Docker daemon, model, workflow or real data.
The database tier runs these same tests against throwaway Postgres as well as SQLite.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from temper_ai.api import routes
from temper_ai.database import get_session
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.queue import queue_run, queue_run_in
from temper_ai.spawner import box_seal
from temper_ai.spawner.box_seal import WorkspacePathRefused
from temper_ai.spawner.docker_spawner import DockerSpawner, Mount, workspace_mounts
from tests.test_spawner.box_fixtures import Install, MemoryStore
from tests.test_spawner.test_docker_spawner import FakeDocker


@pytest.fixture
def install(tmp_path, monkeypatch):
    tree = Install(tmp_path / "host", user="999:999").build()
    monkeypatch.setenv("WORKSPACE_DIR", str(tree.workspaces))
    for name in ("TEMPER_BOX_RUNTIME_BOUNDARY", "TEMPER_BOX_SECRET_BOOTSTRAP",
                 "TEMPER_BOX_ENV", "TEMPER_BOX_LOGIN_FILE", "TEMPER_DOCKER_MAIN_REPO_ROOTS",
                 "TEMPER_DOCKER_WORKSPACES"):
        monkeypatch.delenv(name, raising=False)
    return tree


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    monkeypatch.setattr(routes, "require_caller_may", lambda _action: None)
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(
        graph_loader=SimpleNamespace(load_workflow=lambda name, **_kwargs: (
            [], SimpleNamespace(name=name, inputs=None))),
    ))
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as http:
        yield http


def _rows():
    with get_session() as session:
        return [row.model_dump() for row in session.exec(select(WorkflowRun)).all()]


def _spawn(install, workspace: str, *, eid="workspace-run"):
    store = MemoryStore()
    store.add(eid, workspace=workspace)
    docker = FakeDocker(answers={"inspect": [(0, install.inspect(), "")]})
    spawner = DockerSpawner(
        template_container="worker-self", workspace_lookup=lambda _eid: workspace,
        profile_store=store, run=docker,
    )
    return spawner, docker, store


def _mounts(docker):
    (cmd,) = docker.commands("run")
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "--mount"]


def test_inside_workspace_queues_spawns_and_mounts_while_automatic_workspaces_still_queue(install, client):
    workspace = str(install.run_a)
    response = client.post("/api/runs", json={"workflow": "wf", "workspace_path": workspace})
    assert response.status_code == 200, response.text
    eid = response.json()["execution_id"]
    assert response.json()["status"] == "queued"
    (row,) = _rows()
    assert row["execution_id"] == eid and row["workspace_path"] == workspace
    spawner, docker, store = _spawn(install, row["workspace_path"], eid=eid)
    spawner.spawn(eid)
    assert f"type=bind,source={workspace},target={workspace}" in _mounts(docker)
    assert store.record(eid)["doc"]["boundary"] == "legacy"

    for i, automatic in enumerate((None, "")):
        queue_run(f"auto-{i}", "wf", automatic, {})
        spawner, docker, _ = _spawn(install, "", eid=f"auto-{i}")
        spawner.spawn(f"auto-{i}")
        assert not any(f"target={workspace}" in mount for mount in _mounts(docker))
    assert [row["workspace_path"] for row in _rows() if row["execution_id"].startswith("auto-")] == ["", ""]


CASES = ("outside", "root", "prefix", "symlink", "outside-link", "comma", "double-quote", "single-quote")


def _bad_path(install, case):
    root = install.workspaces
    if case == "outside":
        return str(install.root)
    if case == "root":
        return str(root)
    if case == "outside-link":
        path = install.root / "outside-link"
        path.symlink_to(install.run_a, target_is_directory=True)
        return str(path)
    if case == "prefix":
        path = Path(str(root) + "x")
    elif case == "symlink":
        path = root / "escape"
        path.symlink_to(install.root, target_is_directory=True)
        return str(path)
    else:
        suffix = {"comma": ",readonly", "double-quote": '"quoted', "single-quote": "'quoted"}[case]
        path = root / f"bad{suffix}"
    path.mkdir()
    return str(path)


def _refuses_at_all_boundaries(install, client, workspace):
    before = _rows()
    with pytest.raises(WorkspacePathRefused) as queue_error:
        queue_run("refused", "wf", workspace, {})
    assert repr(workspace) in str(queue_error.value)
    with get_session() as session, pytest.raises(WorkspacePathRefused):
        queue_run_in(session, "refused-transaction", "wf", workspace, {})
    response = client.post("/api/runs", json={"workflow": "wf", "workspace_path": workspace})
    assert response.status_code == 400, response.text
    assert repr(workspace) in response.json()["detail"]
    assert _rows() == before
    spawner, docker, store = _spawn(install, workspace)
    with pytest.raises(WorkspacePathRefused) as spawn_error:
        spawner.spawn("workspace-run")
    assert repr(workspace) in str(spawn_error.value)
    assert docker.commands("run") == []
    assert store.rows["workspace-run"]["metadata"] == {}


@pytest.mark.parametrize("case", CASES)
def test_unsafe_workspaces_never_queue_or_spawn(install, client, case):
    _refuses_at_all_boundaries(install, client, _bad_path(install, case))


def test_non_plain_path_with_nul_is_a_refusal_not_an_internal_error(install, client):
    _refuses_at_all_boundaries(install, client, str(install.workspaces / "bad\0path"))


def test_refused_resume_preserves_the_old_row(install, client):
    with get_session() as session:
        session.add(WorkflowRun(execution_id="refused", workflow_name="old", status="failed",
                                workspace_path=str(install.root), inputs={"keep": True},
                                error={"message": "old failure"}))
    _refuses_at_all_boundaries(install, client, str(install.root))


def test_spawn_rechecks_a_symlink_changed_after_queue(install):
    path = install.workspaces / "later"
    path.symlink_to(install.run_a, target_is_directory=True)
    queue_run("later", "wf", str(path), {})
    path.unlink()
    path.symlink_to(install.root, target_is_directory=True)
    spawner, docker, _ = _spawn(install, str(path), eid="later")
    with pytest.raises(WorkspacePathRefused):
        spawner.spawn("later")
    assert docker.commands("run") == []


def test_an_inside_symlink_binds_its_resolved_source_not_the_link(install):
    link = install.workspaces / "inside-link"
    link.symlink_to(install.run_a, target_is_directory=True)
    queue_run("inside-link", "wf", str(link), {})
    assert workspace_mounts(str(link), workspace_dir=str(install.workspaces)) == [
        Mount(str(install.run_a), str(link), read_only=False),
    ]


@pytest.mark.parametrize("bad_name", ["a,b", 'a"b', "a'b"])
def test_resolved_source_must_also_be_safe_mount_syntax(install, client, bad_name):
    target = install.workspaces / bad_name
    target.mkdir()
    link = install.workspaces / "plain-name"
    link.symlink_to(target, target_is_directory=True)
    _refuses_at_all_boundaries(install, client, str(link))


def test_alias_descendants_require_the_actual_workspace_mapping(install, monkeypatch):
    # Stand in for /app/workspaces in this process, without changing the real host.
    alias = install.root / "alias"
    alias.symlink_to(install.workspaces, target_is_directory=True)
    monkeypatch.setattr(box_seal, "WORKSPACES_ALIAS", str(alias))
    path = str(alias / install.run_a.name)
    queue_run("alias", "wf", path, {})
    assert workspace_mounts(path, covered=[Mount(str(install.workspaces), str(alias), False)],
                            workspace_dir=str(install.workspaces)) == []
    with pytest.raises(WorkspacePathRefused):
        queue_run("alias-root", "wf", str(alias), {})
    with pytest.raises(WorkspacePathRefused):
        workspace_mounts(str(alias), covered=[Mount(str(install.workspaces), str(alias), False)],
                         workspace_dir=str(install.workspaces))

    # A different inherited source and an alias not backed by WORKSPACE_DIR confer no access.
    alias.unlink()
    alias.symlink_to(install.root, target_is_directory=True)
    with pytest.raises(WorkspacePathRefused):
        queue_run("wrong-alias", "wf", path, {})
    with pytest.raises(WorkspacePathRefused):
        workspace_mounts(path, covered=[Mount(str(install.root), str(alias), False)],
                         workspace_dir=str(install.workspaces))
    alias.unlink()
    with pytest.raises(WorkspacePathRefused):
        queue_run("absent-alias", "wf", path, {})


def test_arbitrary_inherited_mount_does_not_grant_workspace_access(install):
    with pytest.raises(WorkspacePathRefused):
        workspace_mounts(str(install.root), covered=[Mount(str(install.root), str(install.root), False)],
                         workspace_dir=str(install.workspaces))


def test_missing_workspace_setting_is_not_an_unrestricted_root(install, client, monkeypatch):
    monkeypatch.delenv("WORKSPACE_DIR")
    with pytest.raises(WorkspacePathRefused):
        queue_run("unset", "wf", str(install.run_a), {})
    assert client.post("/api/runs", json={"workflow": "wf", "workspace_path": str(install.run_a)}).status_code == 400
    with pytest.raises(WorkspacePathRefused):
        workspace_mounts(str(install.run_a))


# Each changed containment guard has a bite: use the same refusal proof, with
# just that guard removed in memory, then let monkeypatch restore the module.
MUTATIONS = (
    ("outside", " or not _inside(path, root)", ""),
    ("prefix", "not _inside(path, root)", "not path.startswith(root)"),
    ("root", " or path == root", ""),
    ("symlink", ".resolve()", ""),
    ("outside-link", "paths = [(workspace_path, workspace_dir)]", "paths = []"),
    ("double-quote", "if resolve and any(c in path for c in", "if False and any(c in path for c in"),
    ("single-quote", "if resolve and any(c in path for c in", "if False and any(c in path for c in"),
)


@pytest.mark.parametrize("case,old,new", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_containment_guard_has_a_bite(install, client, monkeypatch, case, old, new):
    source = inspect.getsource(box_seal.workspace_in_tree)
    assert old in source
    namespace = dict(vars(box_seal))
    exec(compile(source.replace(old, new), "<F-WS guard removed>", "exec"), namespace)
    monkeypatch.setattr(box_seal, "workspace_in_tree", namespace["workspace_in_tree"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        _refuses_at_all_boundaries(install, client, _bad_path(install, case))


@pytest.mark.parametrize("old", [
    "alias = os.path.samefile(WORKSPACES_ALIAS, workspace_dir)",
    "alias = (workspace_dir, WORKSPACES_ALIAS) in alias_mounts",
])
def test_alias_mapping_guards_have_bites(install, monkeypatch, old):
    source = inspect.getsource(box_seal.workspace_in_tree)
    assert source.count(old) == 1
    namespace = dict(vars(box_seal))
    # The alias proof substitutes a temporary spelling, so the compiled rule uses it too.
    namespace["WORKSPACES_ALIAS"] = str(install.root / "alias")
    exec(compile(source.replace(old, "alias = True"), "<F-WS alias mapping removed>", "exec"), namespace)
    monkeypatch.setattr(box_seal, "workspace_in_tree", namespace["workspace_in_tree"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_alias_descendants_require_the_actual_workspace_mapping(install, monkeypatch)


def test_plain_path_comma_guard_has_a_bite(install, client, monkeypatch):
    plain = box_seal._plain
    monkeypatch.setattr(box_seal, "_plain", lambda path: plain(path.replace(",", "_")))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        _refuses_at_all_boundaries(install, client, _bad_path(install, "comma"))
