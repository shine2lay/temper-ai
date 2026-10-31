"""A legacy box gets a git worktree's main repository only for a real worktree (E7).

A run whose workspace is a `git worktree` has a .git file naming <main>/.git/worktrees/<name>,
and its legacy box gets <main> read-write at its host path. Any run can write its own .git, so
that name proves nothing by itself: <main> is mounted only when it is inside WORKSPACE_DIR or an
explicit root of TEMPER_DOCKER_MAIN_REPO_ROOTS (unset: no extra roots), is not WORKSPACE_DIR
or its ancestor, the way there has no symlink, and the worktree record's back-link,
<record>/gitdir, which `git worktree add` writes,
names this workspace's .git. Any other gitdir that would need a mount stops the spawn with
MainRepoRefused, naming the workspace and the path refused (docs/boxes.md, "A worktree's main
repository"). Sealed boxes never get a main repository, and still don't.

Real git makes the worktrees here, in throwaway folders under tmp_path. The last test runs git
inside a real, disposable legacy box on a synthetic tree with no network (skipped without
docker, unless TEMPER_TEST_BOX_REQUIRED=1). Nothing real is read or mounted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from temper_ai.shared.box_env import BoxEnv
from temper_ai.spawner import box_profile
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.box_profile import BoxProfileError
from temper_ai.spawner.box_seal import WorkerView
from temper_ai.spawner.docker_spawner import (
    MAIN_REPO_ROOTS_ENV,
    DockerSpawner,
    MainRepoRefused,
    Mount,
    workspace_mounts,
)
from tests.test_spawner.box_fixtures import (
    TEST_LABEL,
    WORKFLOW,
    BoxDocker,
    Install,
    MemoryStore,
    box_user,
    docker_ok,
    image_id,
    run_id,
)

#: Settings a test here may set, cleared for every test.
SETTINGS = (MAIN_REPO_ROOTS_ENV, "TEMPER_BOX_ENV", "TEMPER_BOX_LOGIN_FILE", "TEMPER_DOCKER_WORKSPACES",
            "TEMPER_DOCKER_IMAGE", "TEMPER_DOCKER_RUN_COMMAND", "TEMPER_BOX_CAPABILITIES",
            box_profile.BOUNDARY_ENV, box_profile.BOOTSTRAP_ENV)
BOX_LIST = BoxEnv(names=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "TEMPER_DATABASE_URL"}),
                  agent_tools=frozenset({"PATH", "HOME", "WORKSPACE_DIR"}))
GIT_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, "LC_ALL": "C",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


@pytest.fixture(autouse=True)
def _no_settings(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def install(tmp_path) -> Install:
    return Install(tmp_path / "host", user=box_user()).build()


# -- helpers -----------------------------------------------------------------------------------


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=GIT_ENV, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def repository(path: Path) -> Path:
    """A repository with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=path)
    (path / "README.md").write_text("synthetic\n")
    git("add", "README.md", cwd=path)
    git("commit", "-q", "-m", "first", cwd=path)
    return path


def worktree(main: Path, path: Path) -> Path:
    """git's own `worktree add`, on a new branch named after the folder."""
    git("worktree", "add", "-q", "-b", path.name, str(path), cwd=main)
    return path


def record_of(workspace: Path) -> Path:
    """The worktree record the workspace's .git names."""
    return Path((workspace / ".git").read_text().split("gitdir:", 1)[1].strip())


def plant(workspace: Path, gitdir: str | bytes) -> Path:
    """What any run can do: write its own workspace's .git file."""
    workspace.mkdir(parents=True, exist_ok=True)
    named = gitdir if isinstance(gitdir, bytes) else gitdir.encode()
    (workspace / ".git").write_bytes(b"gitdir: " + named + b"\n")
    return workspace


def lay_record(main: Path, name: str, back_link: str | None) -> Path:
    """A worktree record laid out by hand, as git lays one out; ``back_link`` its gitdir file."""
    record = main / ".git" / "worktrees" / name
    record.mkdir(parents=True)
    if back_link is not None:
        (record / "gitdir").write_text(back_link + "\n")
    return record


def checkout(install: Install) -> Path:
    """The install's checkout: the folder its configs come from (not implicitly allowed)."""
    return install.configs.parent


def mounts(install: Install, workspace: Path, roots: list[str] | None = None) -> list[Mount]:
    """workspace_mounts as a legacy box's spawner calls it; no extra roots by default."""
    return workspace_mounts(str(workspace), workspace_dir=str(install.workspaces),
                            main_repo_roots=[] if roots is None else roots)


def rw(path: Path) -> Mount:
    return Mount(str(path), str(path), read_only=False)


def assert_refused(call, workspace: Path, named: str, reason: str) -> None:
    """``call`` raises MainRepoRefused naming the workspace, the path refused and ``reason``."""
    with pytest.raises(MainRepoRefused) as caught:
        call()
    text = str(caught.value)
    assert text.startswith(f"Main repository mount refused for workspace {workspace}: "
                           f"its .git names {named!r}, "), text
    assert reason in text, text


@dataclass
class TemplateDocker:
    """docker for a spawner: the template's inspect answered, no old box, every `run` kept."""

    inspect: str
    runs: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        if cmd[1:4] == ["inspect", "--format", "{{.State.Status}}"]:  # an old box: gone
            return subprocess.CompletedProcess(cmd, 1, "", f"Error: No such object: {cmd[-1]}")
        if cmd[1] == "inspect":
            return subprocess.CompletedProcess(cmd, 0, self.inspect, "")
        if cmd[1] == "run":
            self.runs.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "cid-1\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def spawner(install: Install, store: MemoryStore, docker, **kwargs) -> DockerSpawner:
    return DockerSpawner(template_container="worker-self",
                         workspace_lookup=lambda eid: store.rows[eid]["workspace"],
                         run=docker, box_env=lambda: BOX_LIST, profile_store=store,
                         worker_view=WorkerView(None), **kwargs)


def host_binds(cmd: list[str]) -> list[tuple[str, bool]]:
    """The run's binds at their own host path, (source, read-only), in docker's order."""
    binds = []
    for i, part in enumerate(cmd):
        if part == "--mount":
            fields = dict(f.split("=", 1) if "=" in f else (f, "") for f in cmd[i + 1].split(","))
            if fields["source"] == fields["target"]:
                binds.append((fields["source"], "readonly" in fields))
    return binds


# -- a real worktree ---------------------------------------------------------------------------


def test_a_real_worktree_inside_workspace_dir_gets_its_repository_and_git_finds_all_it_needs(install):
    """The whole feature: a repository strictly inside WORKSPACE_DIR and git's own worktree.
    The box gets the repository read-write beside the workspace, and everything git in the
    worktree reads and writes is inside those two mounts. No extra root is configured."""
    main = repository(install.workspaces / "repos" / "proj")
    ws = worktree(main, install.run_a)

    assert mounts(install, ws) == [rw(ws), rw(main)]
    for asked in ("--git-dir", "--git-common-dir"):
        found = Path(git("rev-parse", "--path-format=absolute", asked, cwd=ws)).resolve()
        assert found.is_relative_to(main.resolve()), (asked, found)

    # The spawner, setting unset: only WORKSPACE_DIR permits a main repository.
    store = MemoryStore()
    store.add("wt-happy", workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    spawner(install, store, docker).spawn("wt-happy")
    (cmd,) = docker.runs
    assert host_binds(cmd) == [(str(ws), False), (str(main), False)]


def test_a_worktree_of_a_repository_inside_workspace_dir_needs_no_root(install):
    main = repository(install.workspaces / "repos" / "proj")
    ws = worktree(main, install.workspaces / "run-c")
    assert mounts(install, ws, roots=[]) == [rw(ws), rw(main)]


def test_the_same_worktree_is_refused_once_its_repository_is_not_allowed(install, monkeypatch):
    """An unrelated repository is allowed only when named; this fixture's checkout is a sibling
    of WORKSPACE_DIR, not its ancestor (the ancestor cases are in test_main_repo_ancestors)."""
    main = repository(checkout(install))
    ws = worktree(main, install.run_a)
    assert mounts(install, ws, roots=[str(main)]) == [rw(ws), rw(main)]
    named = str(record_of(ws))
    reason = f"whose repository {main} is outside WORKSPACE_DIR and the allowed roots"
    assert_refused(lambda: mounts(install, ws, roots=[]), ws, named, reason)

    # Naming WORKSPACE_DIR permits no additional repository.
    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, str(install.workspaces))
    store = MemoryStore()
    store.add("wt-gone", workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    assert_refused(lambda: spawner(install, store, docker).spawn("wt-gone"), ws, named, reason)
    assert docker.runs == []


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_the_default_has_no_extra_roots_and_workspace_dir_stays_allowed(install, monkeypatch, empty):
    if empty is not None:
        monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, empty)
    docker = TemplateDocker(install.inspect())
    unset = spawner(install, MemoryStore(), docker)
    assert unset.main_repo_roots(unset.template()) == ()

    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, " /srv/repos:/opt/more ")
    given = spawner(install, MemoryStore(), docker)
    assert given.main_repo_roots(given.template()) == ("/srv/repos", "/opt/more")
    main = repository(install.workspaces / "repos" / "proj")
    ws = worktree(main, install.workspaces / "run-c")
    assert given.legacy_mounts(str(ws), given.template())[1][-2:] == [rw(ws), rw(main)]


def test_a_template_with_its_configs_at_the_host_root_allows_no_checkout(install):
    """The template cannot restore an implicit root, including a checkout at /."""
    described = json.loads(install.inspect())
    for mount in described[0]["Mounts"]:
        if mount["Destination"] == "/app/configs":
            mount["Source"] = "/configs"
    at_root = spawner(install, MemoryStore(), TemplateDocker(json.dumps(described)))
    assert at_root.main_repo_roots(at_root.template()) == ()


def test_a_worktree_named_through_a_symlinked_workspace_path_still_mounts(install):
    """git writes the back-link as it resolved the worktree's path, and the run's row may
    name the workspace through a symlink: that is still this workspace."""
    main = repository(install.workspaces / "repos" / "proj")
    worktree(main, install.run_a)
    link = install.root / "linked-run-a"
    link.symlink_to(install.run_a)
    assert mounts(install, link) == [rw(link), rw(main)]


def test_a_back_link_spelled_as_the_row_spells_the_workspace_names_it(install):
    """A back-link that keeps the symlinked spelling (a relative one, worktree.useRelativePaths,
    is read from the record, so it names the workspace the way its path was given)."""
    main = repository(install.workspaces / "repos" / "proj")
    link = install.root / "linked-run-a"
    link.symlink_to(install.run_a)
    plant(install.run_a, str(lay_record(main, "run-a", f"{link}/.git")))
    assert mounts(install, link) == [rw(link), rw(main)]


@pytest.mark.parametrize("value", ["relative/path", "/srv/a::/srv/b", "/", "/srv/a/../b", "/srv/a/"])
def test_a_setting_the_worker_cant_read_starts_no_box(monkeypatch, value):
    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, value)
    with pytest.raises(SpawnerError, match=f"^{MAIN_REPO_ROOTS_ENV}=.*no box starts until it is fixed"):
        DockerSpawner(template_container="worker-self", workspace_lookup=lambda _eid: None,
                      run=TemplateDocker("[]"))


# -- nothing more to mount ---------------------------------------------------------------------


@pytest.mark.parametrize("what", ["no .git", "a .git folder", "a gitdir inside the workspace",
                                  "an empty .git", "not a gitdir line", "a .git symlink"])
def test_a_workspace_that_is_no_worktree_gets_only_itself(install, what):
    ws = install.run_a
    if what == "a .git folder":
        repository(ws)
    elif what == "a gitdir inside the workspace":
        git("init", "-q", "--separate-git-dir", str(ws / ".repository"), str(ws), cwd=install.root)
    elif what == "an empty .git":
        (ws / ".git").write_text("")
    elif what == "not a gitdir line":  # a typo: what follows it is an outside path
        (ws / ".git").write_text(f"gitdir={install.root}/elsewhere/.git/worktrees/run-a\n")
    elif what == "a .git symlink":  # never followed: it would name a valid record
        main = repository(install.workspaces / "repos" / "proj")
        worktree(main, ws)
        copy = install.root / "elsewhere" / "dot-git"
        copy.parent.mkdir()
        copy.write_text((ws / ".git").read_text())
        (ws / ".git").unlink()
        (ws / ".git").symlink_to(copy)
    assert mounts(install, ws) == [rw(ws)]


@pytest.mark.timeout(20)
def test_a_git_file_that_is_a_fifo_gets_only_itself_and_never_waits(install):
    os.mkfifo(install.run_a / ".git")
    assert mounts(install, install.run_a) == [rw(install.run_a)]


def test_a_workspace_with_no_git_file_spawns_with_its_own_folder_only(install):
    store = MemoryStore()
    store.add("plain-1", workspace=str(install.run_a))
    docker = TemplateDocker(install.inspect())
    spawner(install, store, docker).spawn("plain-1")
    (cmd,) = docker.runs
    assert host_binds(cmd) == [(str(install.run_a), False)]


@pytest.mark.parametrize("gitdir", ["/app/workspaces/capmap_base/.git/worktrees/capmap_ref",
                                    "{workspaces}/repos/proj/.git/worktrees/run-a"])
def test_a_record_inside_a_mount_the_box_has_brings_nothing_more(install, monkeypatch, gitdir):
    """TEMPER_DOCKER_WORKSPACES=all: the box has the whole tree at its host path and at
    /app/workspaces (where the capmap_* folders' records are named), so nothing is added."""
    monkeypatch.setenv("TEMPER_DOCKER_WORKSPACES", "all")
    plant(install.run_a, gitdir.format(workspaces=install.workspaces))
    store = MemoryStore()
    store.add("all-1", workspace=str(install.run_a))
    docker = TemplateDocker(install.inspect())
    spawner(install, store, docker).spawn("all-1")
    (cmd,) = docker.runs
    assert host_binds(cmd) == [(str(install.workspaces), False)]


# -- refused -----------------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["git's own worktree", "a planted .git"])
def test_a_repository_outside_every_allowed_folder_is_refused(install, how):
    secret = install.root / "elsewhere" / "secret"
    if how == "git's own worktree":  # its back-link is real: only where it lives is wrong
        ws = worktree(repository(secret), install.run_a)
    else:  # an existing outside folder, its record even laid with a back-link to this workspace
        lay_record(secret, "run-a", f"{install.run_a}/.git")
        ws = plant(install.run_a, f"{secret}/.git/worktrees/run-a")
    assert_refused(lambda: mounts(install, ws), ws, f"{secret}/.git/worktrees/run-a",
                   f"whose repository {secret} is outside WORKSPACE_DIR and the allowed roots")


@pytest.mark.parametrize("gitdir", ["/.git/worktrees/x", "../" * 40 + ".git/worktrees/x"])
def test_a_gitdir_that_makes_the_host_root_the_repository_is_refused(install, gitdir):
    ws = plant(install.run_a, gitdir)
    assert_refused(lambda: mounts(install, ws), ws, "/.git/worktrees/x",
                   "whose repository is WORKSPACE_DIR itself or contains it")


@pytest.mark.parametrize("target", ["its folder", "its repository", "a record laid inside it",
                                    "a record in another folder of its .git"])
def test_a_gitdir_naming_another_runs_workspace_is_refused(install, target):
    """Another run's workspace is inside WORKSPACE_DIR, but only a worktree record git made
    (<repository>/.git/worktrees/<name>) is a gitdir: even one with a back-link naming this
    workspace, laid anywhere else, is refused."""
    other = repository(install.run_b)
    named = {"its folder": other, "its repository": other / ".git",
             "a record laid inside it": other / "x" / "worktrees" / "run-a",
             "a record in another folder of its .git": other / ".git" / "modules" / "run-a"}[target]
    if target.startswith("a record"):
        named.mkdir(parents=True)
        (named / "gitdir").write_text(f"{install.run_a}/.git\n")
    ws = plant(install.run_a, str(named))
    assert_refused(lambda: mounts(install, ws), ws, str(named), "which is not a git worktree record")


def test_the_workspaces_tree_itself_is_never_the_repository(install):
    """As if the shared tree were one repository, with a record naming this workspace: any run
    can lay that out, and it would give the box every other run's workspace."""
    lay_record(install.workspaces, "run-a", f"{install.run_a}/.git")
    ws = plant(install.run_a, f"{install.workspaces}/.git/worktrees/run-a")
    # Even with a root holding the tree, as the live checkout holds its workspaces folder.
    assert_refused(lambda: mounts(install, ws, roots=[str(install.root)]), ws,
                   f"{install.workspaces}/.git/worktrees/run-a", "whose repository is WORKSPACE_DIR itself")


@pytest.mark.parametrize("char", [",", '"'])
def test_a_repository_path_that_would_break_the_mount_argument_is_refused(install, char):
    """docker reads --mount as comma-separated options: a repository at
    <tree>/e,source=/etc would bind the host's /etc instead. Even git's own worktree of it."""
    main = repository(install.workspaces / f"e{char}source=" / "etc")
    ws = worktree(main, install.run_a)
    assert_refused(lambda: mounts(install, ws), ws, str(record_of(ws)),
                   "can't go into a docker --mount argument")


def test_a_gitdir_holding_a_nul_byte_is_refused(install):
    named = f"{checkout(install)}/a\x00b/.git/worktrees/run-a"
    ws = plant(install.run_a, named.encode())
    assert_refused(lambda: mounts(install, ws), ws, named, "holds a NUL byte")


@pytest.mark.parametrize("where", ["in the checkout", "in the workspaces tree"])
def test_a_symlink_on_the_way_to_the_record_is_refused(install, where):
    """The record is real and names this workspace, but sits outside every allowed folder; a
    symlink inside one makes it look inside."""
    secret = repository(install.root / "elsewhere" / "secret")
    ws = worktree(secret, install.run_a)
    link = (checkout(install) if where == "in the checkout" else install.run_b) / "linked"
    link.symlink_to(secret)
    plant(ws, f"{link}/.git/worktrees/run-a")
    assert_refused(lambda: mounts(install, ws, roots=[str(checkout(install))]), ws,
                   f"{link}/.git/worktrees/run-a", "goes through a symlink")


def test_a_record_the_worker_cant_see_is_refused(install):
    """Even an otherwise allowed record must be visible to the worker."""
    named = f"{install.workspaces}/repos/proj/.git/worktrees/run-a"
    ws = plant(install.run_a, named)
    assert_refused(lambda: mounts(install, ws), ws, named,
                   "which is not a folder the worker can see")


@pytest.mark.parametrize("how", ["taken from git's record", "a record laid without one"])
def test_a_record_without_its_back_link_is_refused(install, how):
    if how == "taken from git's record":
        ws = worktree(repository(install.workspaces / "repos" / "proj"), install.run_a)
        record = record_of(ws)
        (record / "gitdir").unlink()
    else:
        record = lay_record(install.workspaces / "repos" / "proj", "run-a", None)
        ws = plant(install.run_a, str(record))
    assert_refused(lambda: mounts(install, ws), ws, str(record),
                   f"whose back-link file {record}/gitdir can't be read as a plain file")


@pytest.mark.parametrize("how", ["another run's worktree", "a moved worktree"])
def test_a_back_link_naming_another_workspace_is_refused(install, how):
    main = repository(install.workspaces / "repos" / "proj")
    if how == "another run's worktree":
        ws = plant(install.run_a, str(record_of(worktree(main, install.run_b))))
    else:
        ws = install.workspaces / "run-c"
        worktree(main, install.workspaces / "run-old").rename(ws)
    assert_refused(lambda: mounts(install, ws), ws, str(record_of(ws)),
                   f"does not name this workspace's {ws}/.git")


def test_a_back_link_that_is_a_symlink_is_not_followed(install):
    ws = worktree(repository(install.workspaces / "repos" / "proj"), install.run_a)
    back_link = record_of(ws) / "gitdir"
    back_link.rename(back_link.with_name("gitdir.real"))
    back_link.symlink_to(back_link.with_name("gitdir.real"))
    assert_refused(lambda: mounts(install, ws), ws, str(record_of(ws)), "can't be read as a plain file")


@pytest.mark.timeout(20)
def test_a_back_link_that_is_a_fifo_is_refused_without_waiting(install):
    ws = worktree(repository(install.workspaces / "repos" / "proj"), install.run_a)
    back_link = record_of(ws) / "gitdir"
    back_link.unlink()
    os.mkfifo(back_link)
    assert_refused(lambda: mounts(install, ws), ws, str(record_of(ws)), "does not name this workspace's")


def test_a_refused_spawn_starts_no_box_and_keeps_no_profile(install, caplog):
    """The watcher turns the SpawnerError into the run's failure, with this message. The box is
    not started at all, so the log never says it starts without a profile."""
    secret = install.root / "elsewhere" / "secret"
    ws = worktree(repository(secret), install.run_a)
    store = MemoryStore()
    store.add("refused-1", workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    with caplog.at_level(logging.INFO), pytest.raises(SpawnerError) as caught:
        spawner(install, store, docker).spawn("refused-1")
    assert isinstance(caught.value, MainRepoRefused) and str(secret) in str(caught.value)
    assert docker.runs == []
    assert "starts without one" not in caplog.text
    assert "box_profile" not in store.rows["refused-1"]["metadata"]


def test_a_sealed_box_still_never_gets_a_main_repository(install, monkeypatch):
    """Sealed boxes are untouched: even git's own worktree is refused."""
    monkeypatch.setenv(box_profile.BOUNDARY_ENV, "sealed")
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", "/app/.venv/bin/python -m temper_ai.cli.main run-workflow")
    ws = worktree(repository(checkout(install)), install.run_a)
    store = MemoryStore()
    store.add("sealed-wt", workflow=WORKFLOW, workspace=str(ws))
    docker = TemplateDocker(install.inspect())
    with pytest.raises(BoxProfileError, match="is a git worktree of a repository outside it"):
        spawner(install, store, docker, engine_launches=install.engine_table()).spawn("sealed-wt")
    assert docker.runs == []


# -- git inside a real box ---------------------------------------------------------------------

#: A small image with git, run as this user: git refuses a repository another user owns.
GIT_BOX_DOCKERFILE = textwrap.dedent("""
    FROM python:3.12-slim
    RUN apt-get update \\
     && apt-get install -y --no-install-recommends git \\
     && rm -rf /var/lib/apt/lists/*
    USER {user}
""")
#: What the box runs in place of the runner: git status, a commit, and where git's repository is.
IN_THE_BOX = ("set -e; cd {ws}; git status --porcelain >/dev/null; echo made in the box > box.txt; "
              "git add box.txt; "
              'git -c user.name=box -c user.email=box@example.invalid commit -q -m "from the box"; '
              "git rev-parse --path-format=absolute --git-common-dir")
GIT_BOX_ENV = BoxEnv(names=frozenset({"PATH", "HOME"}), agent_tools=frozenset({"PATH", "HOME"}))


def _unavailable(why: str) -> None:
    if os.environ.get("TEMPER_TEST_BOX_REQUIRED") == "1":
        pytest.fail(f"the real-container box gate can't run: {why}")
    pytest.skip(f"the real-container box gate can't run here: {why}")


def git_box_image() -> str | None:
    text = GIT_BOX_DOCKERFILE.format(user=box_user())
    tag = "temper-test-git-box:" + hashlib.sha256(text.encode()).hexdigest()[:12]
    if subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=30).returncode == 0:
        return tag
    built = subprocess.run(["docker", "build", "--label", TEST_LABEL, "-t", tag, "-"],
                           input=text, capture_output=True, text=True, timeout=600)
    return tag if built.returncode == 0 else None


@pytest.mark.timeout(900)
def test_git_works_inside_a_real_legacy_box_on_a_checked_worktree(tmp_path, monkeypatch):
    if os.getuid() == 0:
        _unavailable("the box runs git as this user, and this user is root")
    if not docker_ok():
        _unavailable("no docker")
    image = git_box_image()
    if image is None:
        _unavailable("no image with git (python:3.12-slim and apt-get)")
    install = Install(tmp_path / "host", user=box_user(), image_ref=image,
                      image_id=image_id(image)).build()
    # An unrelated explicitly allowed repository exercises both a real box and removal of
    # that allowance. The opening combined test covers the WORKSPACE_DIR-only default.
    main = repository(checkout(install))
    ws = worktree(main, install.run_a)
    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, str(main))
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", f"sh -c '{IN_THE_BOX.format(ws=ws)}'")
    store = MemoryStore()
    first, second = run_id("git-in-box"), run_id("git-not-allowed")
    for execution_id in (first, second):
        store.add(execution_id, workspace=str(ws))
    docker = BoxDocker(install)

    def box_spawner() -> DockerSpawner:
        return DockerSpawner(template_container="worker-self",
                             workspace_lookup=lambda eid: store.rows[eid]["workspace"],
                             run=docker, box_env=lambda: GIT_BOX_ENV, profile_store=store,
                             worker_view=WorkerView(None))

    box_spawner().spawn(first)
    (box,) = docker.runs
    assert box.returncode == 0, box.stderr
    assert Path(box.stdout.splitlines()[-1]).resolve() == (main / ".git").resolve()
    assert git("log", "-1", "--format=%s", "run-a", cwd=main) == "from the box"
    assert git("status", "--porcelain", cwd=ws) == ""

    # The same worktree with its repository no longer allowed: refused, and no box at all.
    monkeypatch.setenv(MAIN_REPO_ROOTS_ENV, str(install.workspaces))
    with pytest.raises(MainRepoRefused, match="outside WORKSPACE_DIR and the allowed roots"):
        box_spawner().spawn(second)
    assert len(docker.runs) == 1
