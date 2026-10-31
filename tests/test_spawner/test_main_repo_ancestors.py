"""E7b: a main repository must not add the shared workspace tree, even when explicitly allowed.

Use #220's real-git builders and spawner fixtures; no host checkout or real workspace is read.
The general Install fixture has sibling code/workspace roots. Here the checkout contains the
workspace tree, like the installation that exposed the gap.
"""

import os

import pytest

from temper_ai.spawner.box_seal import WorkspacePathRefused
from temper_ai.spawner.docker_spawner import (
    MAIN_REPO_ROOTS_ENV,
    checked_main_repo,
    workspace_mounts,
)
from tests.test_spawner.box_fixtures import Install, MemoryStore, box_user
from tests.test_spawner.test_main_repo_guard import (
    TemplateDocker,
    assert_refused,
    checkout,
    host_binds,
    plant,
    record_of,
    repository,
    rw,
    spawner,
    worktree,
)
from tests.test_spawner.test_main_repo_guard import (
    _no_settings as _no_settings,
)
from tests.test_spawner.test_main_repo_guard import (
    install as install,
)


@pytest.fixture
def checkout_install(tmp_path):
    result = Install(tmp_path / "host", user=box_user())
    result.workspaces = checkout(result) / "workspaces"
    result.run_a = result.workspaces / "run-a"
    result.run_b = result.workspaces / "run-b"
    return result.build()


def test_an_unrelated_explicit_root_still_spawns_with_both_mounts(install, monkeypatch):
    main = repository(install.root / "independent-repos" / "project")
    ws = worktree(main, install.run_a)
    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, str(main.parent))
    store = MemoryStore()
    store.add("independent", workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    spawner(install, store, docker).spawn("independent")
    (cmd,) = docker.runs
    assert host_binds(cmd) == [(str(ws), False), (str(main), False)]


def test_an_explicit_repository_still_works_without_a_workspace_dir(install):
    """The main-repository guard needs no WORKSPACE_DIR for an explicit root. A legacy box
    without one refuses an explicit workspace before that guard runs (F-WS)."""
    main = repository(install.root / "independent")
    ws = worktree(main, install.run_a)
    assert checked_main_repo(str(ws), [], None, [str(main)]) == str(main)
    with pytest.raises(WorkspacePathRefused):
        workspace_mounts(str(ws), main_repo_roots=[str(main)])


@pytest.mark.parametrize("where", ["checkout", "higher ancestor"])
@pytest.mark.parametrize("setting", ["default", "named", "parent root"])
def test_an_ancestor_is_refused_before_spawn_even_when_named(checkout_install, monkeypatch,
                                                            where, setting):
    install = checkout_install
    main = repository(checkout(install) if where == "checkout" else install.root)
    ws = worktree(main, install.run_a)
    if setting != "default":
        monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, str(main if setting == "named" else main.parent))
    store = MemoryStore()
    store.add("ancestor", workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    assert_refused(lambda: spawner(install, store, docker).spawn("ancestor"), ws,
                   str(record_of(ws)), "whose repository is WORKSPACE_DIR itself or contains it")
    assert docker.runs == []
    assert "box_profile" not in store.rows["ancestor"]["metadata"]


@pytest.mark.parametrize("spelling", ["relative gitdir", "normalized gitdir", "repository alias",
                                     "workspace-root alias", "equal-root alias"])
def test_an_ancestor_or_equal_root_cannot_hide_behind_another_spelling(checkout_install, spelling):
    install = checkout_install
    main = repository(install.workspaces if spelling == "equal-root alias" else checkout(install))
    ws = worktree(main, install.run_a)
    named = str(record_of(ws))
    shared, root = str(install.workspaces), str(main)
    if spelling == "relative gitdir":
        named = os.path.relpath(named, ws)
    elif spelling == "normalized gitdir":
        named = f"{main}/unused/../.git/worktrees/run-a"
    elif spelling == "repository alias":
        alias = install.root / "alias"
        alias.symlink_to(main, target_is_directory=True)
        root = str(alias)
        named = f"{alias}/.git/worktrees/run-a"
    else:
        alias = install.root / "shared-alias"
        alias.symlink_to(install.workspaces, target_is_directory=True)
        shared = str(alias)
        ws = alias / ws.name  # spelled under WORKSPACE_DIR as set, as the server spells it
    plant(ws, named)
    assert_refused(lambda: workspace_mounts(str(ws), workspace_dir=shared, main_repo_roots=[root]),
                   ws, os.path.normpath(os.path.join(ws, named)),
                   "whose repository is WORKSPACE_DIR itself or contains it")


def test_a_lexical_ancestor_is_still_refused_when_the_shared_root_is_a_link(install):
    """Neither spelling may hide the shared root. Even if it resolves elsewhere, the declared
    root is still under the repository; this does not change workspace-path admission."""
    main = repository(checkout(install))
    shared = main / "workspaces"
    shared.symlink_to(install.workspaces, target_is_directory=True)
    ws = worktree(main, install.run_a)
    spelled = shared / ws.name  # under WORKSPACE_DIR as set, as the server spells it
    assert_refused(lambda: workspace_mounts(str(spelled), workspace_dir=str(shared),
                                            main_repo_roots=[str(main)]),
                   spelled, str(record_of(ws)),
                   "whose repository is WORKSPACE_DIR itself or contains it")


def test_a_similar_prefix_is_not_an_ancestor(install):
    main = repository(install.workspaces.with_name("workspace"))
    ws = worktree(main, install.run_a)
    assert workspace_mounts(str(ws), workspace_dir=str(install.workspaces),
                            main_repo_roots=[str(main)]) == [rw(ws), rw(main)]


def test_an_unrelated_explicit_root_can_keep_its_existing_symlink_spelling(install):
    main = repository(install.root / "independent")
    ws = worktree(main, install.run_a)
    alias = install.root / "independent-alias"
    alias.symlink_to(main, target_is_directory=True)
    plant(ws, f"{alias}/.git/worktrees/run-a")
    assert workspace_mounts(str(ws), workspace_dir=str(install.workspaces),
                            main_repo_roots=[str(alias)]) == [rw(ws), rw(alias)]
