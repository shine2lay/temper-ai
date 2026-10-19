"""M1: Temper's host git never follows a .git a member planted (task #110).

Temper runs git on the host over each member's working folder (``--work-tree``), with the
copy's git data outside it (``--git-dir``). git takes a folder below the top that holds a
``.git`` -- a ``gitdir:`` file, a link, a folder whose ``commondir`` points elsewhere, or a
repository a scaffolder made -- for another repository: it follows it, reads that repository and
records its commit as a gitlink. A member can write any of these into its folder. So before any
git runs over the folder, Temper looks without following anything and refuses while one is
there, or while the copy's index already holds a gitlink the Project didn't start with.

Model-free: plain git in tmp folders. ``subprocess.run`` is spied on to show that no git process
starts over the folder; Linux inotify shows that nothing opens the planted repository. The B1
tests at the end (nothing may still write in the folder) use the team's ledger in the test
database and a stand-in for Docker.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa

import temper_ai.pi_agent.box as pi_box
from temper_ai.pi_agent import member_tree
from temper_ai.pi_agent.rpc import RpcError
from temper_ai.pi_agent.shared_version import SharedVersion, VersionError
from temper_ai.pi_agent.team_leader import CopyError, LeaderTeam, ProjectCopies
from temper_ai.pi_agent.turn import TurnRequest, run_turn
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

WORK = "the member's own notes\n"
#: The tree of the start project (``app.py``) plus the member's ``notes.md``: content-addressed,
#: so the same files give the same tree before and after the check.
TREE = "85e423bf872d5edacce915e7c3d64711c3f7551a"


def _quoted(*paths: str) -> str:
    return ", ".join(json.dumps(p) for p in paths)


def _refused_git(*paths: str) -> str:
    return ("Temper won't run git over your folder while it holds a .git of its own: "
            f"{_quoted(*paths)}. Remove them and try again.")


def _refused_gitlink(*paths: str) -> str:
    return ("Temper won't run git over your folder while your copy holds a gitlink the Project "
            f"didn't start with: {_quoted(*paths)}. It has to be removed from the copy's index "
            "on the host first.")


NOT_TOLD = ("Temper won't run git over your folder unless git is told the copy's own git dir, "
            "outside the folder, and runs from the folder's top.")


# --- the team, the spy and the watch -----------------------------------------------------------


class Team:
    """A team on a one-commit project, as the team node makes it: the leader's copy, mallory's
    copy (unless the test makes it), the shared version, and one review commit of the leader's
    (``lead_sha``) to move a copy to."""

    def __init__(self, tmp: Path, *, ensure_mallory: bool = True, source: Path | None = None):
        self.tmp = tmp
        self.src = source or ls.project(tmp / "proj")
        self.copies = ProjectCopies(tmp / "team", str(self.src), writer_check=ls.no_writer)
        self.pdirs: dict[str, Path] = {}
        for name in ("lead", "mallory"):
            pdir = tmp / "team" / "members" / name
            pdir.mkdir(parents=True)
            self.pdirs[name] = pdir
        self.copies.ensure("lead", self.pdirs["lead"])
        if ensure_mallory:
            self.copies.ensure("mallory", self.pdirs["mallory"])
        self.shared = SharedVersion(self.copies)
        self.shared.ensure()
        self.lead_sha = self.copies.commit_review("lead", self.pdirs["lead"], "act-1")

    @property
    def pdir(self) -> Path:
        return self.pdirs["mallory"]

    @property
    def ws(self) -> Path:
        return ProjectCopies.worktree(self.pdir)

    @property
    def gd(self) -> Path:
        return self.copies.git_dir("mallory")

    def step(self, step: str) -> object:
        c, s, p = self.copies, self.shared, self.pdir
        if step == "differs":
            return c.differs("mallory", p, c._head(self.gd) or "")
        return {
            "share": lambda: s.share("mallory", p),
            "sync": lambda: s.sync("mallory", p),
            "unshared": lambda: s.unshared("mallory", p),
            "commit_review": lambda: c.commit_review("mallory", p, "act-2"),
            "changes": lambda: c.changes("mallory", p),
            "move_to": lambda: c.move_to("mallory", p, "lead", "act-1", self.lead_sha),
            "ensure": lambda: c.ensure("mallory", p),
        }[step]()


def _sub(cmd: list[str]) -> str:
    """The git subcommand of a hardened git command line."""
    rest = cmd[1:]
    while rest:
        if rest[0] == "-c":
            rest = rest[2:]
        elif rest[0].startswith("--git-dir=") or rest[0].startswith("--work-tree="):
            rest = rest[1:]
        else:
            return rest[0]
    return ""


class GitSpy:
    """Every git process started while it is on: its command line and its working folder."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.calls: list[tuple[list[str], str]] = []
        real = subprocess.run

        def spy(cmd, *args, **kw):
            if isinstance(cmd, list | tuple) and cmd and cmd[0] == "git":
                self.calls.append(([str(c) for c in cmd], str(kw.get("cwd") or "")))
            return real(cmd, *args, **kw)

        monkeypatch.setattr(subprocess, "run", spy)

    def over(self, folder: Path) -> list[str]:
        """The subcommands of the git processes started over ``folder``: given it (or a folder
        in it) as the work tree, or run in it."""
        def inside(text: str) -> bool:
            path = Path(text)
            return path == folder or folder in path.parents

        out = []
        for cmd, cwd in self.calls:
            trees = [c.split("=", 1)[1] for c in cmd if c.startswith("--work-tree=")]
            if any(inside(t) for t in trees) or (cwd and inside(cwd)):
                out.append(_sub(cmd))
        return out


_IN_ACCESS, _IN_OPEN = 0x1, 0x20


class Opens:
    """Linux inotify on a folder and every folder below it: the names opened or read there."""

    def __init__(self, folder: Path):
        self.libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        for here, dirs, _files in os.walk(folder):
            if self.libc.inotify_add_watch(self.fd, os.fsencode(here), _IN_ACCESS | _IN_OPEN) < 0:
                raise OSError(ctypes.get_errno(), f"inotify_add_watch {here}")
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(here, d))]
        self.seen()     # setting the watches up opened every folder: drop those events

    def seen(self) -> list[str]:
        names: list[str] = []
        while True:
            try:
                data = os.read(self.fd, 1 << 16)
            except BlockingIOError:
                return names
            pos = 0
            while pos < len(data):
                _wd, _mask, _cookie, size = struct.unpack_from("iIII", data, pos)
                names.append(data[pos + 16:pos + 16 + size].rstrip(b"\0").decode() or ".")
                pos += 16 + size

    def close(self) -> None:
        os.close(self.fd)


def _gitlinks(git_dir: Path) -> set[tuple[str, str]]:
    """Every gitlink (path, commit) in any commit the repository holds."""
    found: set[tuple[str, str]] = set()
    for commit in ls.git(git_dir, f"--git-dir={git_dir}", "rev-list", "--all").split():
        for line in ls.git(git_dir, f"--git-dir={git_dir}", "ls-tree", "-r", commit).splitlines():
            meta, _, path = line.partition("\t")
            mode, _kind, oid = meta.split()
            if mode == "160000":
                found.add((path, oid))
    return found


def _tree(git_dir: Path, commit: str) -> str:
    return ls.git(git_dir, f"--git-dir={git_dir}", "rev-parse", f"{commit}^{{tree}}")


# --- the happy path first: clean folders run as before ----------------------------------------


def test_m1_happy_path_clean_folders_run_the_same_git_and_make_the_same_commits(
        tmp_path, monkeypatch):
    """A whole team on clean folders: every step runs the same git over each folder as before
    the check, in the same order, makes the same commits (the same tree) and nothing is
    refused. Only reads with no work tree are added."""
    spy = GitSpy(monkeypatch)
    team = Team(tmp_path)
    lead_ws = ProjectCopies.worktree(team.pdirs["lead"])
    (team.ws / "notes.md").write_text(WORK)

    synced = team.shared.sync("mallory", team.pdir)
    got = team.shared.share("mallory", team.pdir, note="notes")
    assert team.shared.unshared("mallory", team.pdir) is None
    sha = team.copies.commit_review("mallory", team.pdir, "act-2")
    team.copies.move_to("lead", team.pdirs["lead"], "mallory", "act-2", sha)
    assert team.copies.differs("lead", team.pdirs["lead"], sha) is None
    assert team.copies.changes("mallory", team.pdir) == 0

    assert synced.kept_leftovers and synced.conflicts == ()
    assert got.status == "shared" and got.version is not None and got.version.version_no == 1
    assert _tree(team.shared.path, got.head) == TREE
    assert _tree(team.gd, sha) == TREE
    assert _tree(team.copies.git_dir("lead"), sha) == TREE
    assert sorted(p.name for p in lead_ws.iterdir()) == ["app.py", "notes.md"]
    # as before the check (pinned on fecacf06): ensure; sync; share; unshared; review; changes
    assert spy.over(team.ws) == ["reset", "status", "add", "commit", "merge", "status", "merge",
                                 "status", "add", "commit", "status"]
    # ensure; its review act-1; move_to; differs
    assert spy.over(lead_ws) == ["reset", "add", "commit", "reset", "clean", "status"]
    assert _gitlinks(team.gd) == set() and _gitlinks(team.shared.path) == set()


# --- a .git a member planted below the top: refused before git runs ----------------------------


CASES = ["gitdir_file", "git_link", "commondir", "git_init", "index_gitlink"]
STEPS = ["share", "sync", "unshared", "commit_review", "changes", "differs", "move_to", "ensure"]


def _plant(case: str, ws: Path, gd: Path, outside: Path, *, top: bool = False) -> Path | None:
    """Put the case's .git into the member's folder (``top``: at the folder's top, else in
    ``sub``); returns the git folder git would follow there, if any."""
    here = ws if top else ws / "sub"
    here.mkdir(parents=True, exist_ok=True)
    if case == "gitdir_file":           # a: a .git file naming another repository
        (here / ".git").write_text(f"gitdir: {outside / '.git'}\n")
        return outside / ".git"
    if case == "git_link":              # b: a link to another repository's .git
        os.symlink(outside / ".git", here / ".git")
        return outside / ".git"
    if case == "commondir":             # c: a .git folder whose commondir is another repository
        (here / ".git").mkdir()
        (here / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (here / ".git" / "commondir").write_text(f"{outside / '.git'}\n")
        return outside / ".git"
    if case == "git_init":              # d: a repository made in the folder, as a scaffolder does
        if not top:
            (here / "index.js").write_text("console.log('scaffolded')\n")
        ls.git(here, "init", "-q", "-b", "main")
        ls.git(here, "add", "-A")
        ls.git(here, "commit", "-q", "-m", "scaffold")
        return here / ".git"
    # e: the copy's own index (host-owned) already records the outside repository's commit
    vendored = ws / "vendored"
    vendored.mkdir(parents=True, exist_ok=True)
    if not (gd / "HEAD").exists():
        ls.git(ws, f"--git-dir={gd}", "init", "-q")
    oid = ls.git(outside, "rev-parse", "HEAD")
    ls.git(ws, f"--git-dir={gd}", f"--work-tree={ws}", "update-index", "--add", "--cacheinfo",
           f"160000,{oid},vendored")
    return None


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("step", STEPS)
def test_m1_git_never_runs_over_a_member_folder_that_holds_a_git_of_its_own(
        tmp_path, monkeypatch, step, case):
    """Cases a-e on every path that runs git over a member's folder: the step is refused with
    the wrapper's own error before any git process starts over the folder, nothing opens the
    planted repository and no gitlink is recorded anywhere."""
    team = Team(tmp_path, ensure_mallory=step != "ensure")
    outside = ls.project(tmp_path / "outside", {"secret.txt": "another repository's file\n"})
    (team.ws).mkdir(parents=True, exist_ok=True)
    (team.ws / "notes.md").write_text(WORK)
    target = _plant(case, team.ws, team.gd, outside)
    opened = Opens(target) if target is not None else None
    spy = GitSpy(monkeypatch)

    refused: Exception | None = None
    try:
        team.step(step)
    except (CopyError, VersionError) as exc:
        refused = exc

    problems = []
    over = spy.over(team.ws)
    if over:
        problems.append(f"git ran over the member's folder: {over}")
    seen = opened.seen() if opened is not None else []
    if seen:
        problems.append(f"the planted repository was opened: {sorted(set(seen))}")
    links = (_gitlinks(team.gd) if (team.gd / "HEAD").exists() else set()) | _gitlinks(
        team.shared.path)
    if links:
        problems.append(f"gitlinks recorded: {sorted(links)}")
    expected = _refused_gitlink("vendored") if case == "index_gitlink" else _refused_git("sub/.git")
    if refused is None:
        problems.append("the step was not refused")
    elif not (isinstance(refused, CopyError) and isinstance(refused, VersionError)):
        problems.append(f"refused with {type(refused).__name__}, not the shared refusal type")
    elif str(refused) != expected:
        problems.append(f"refused with: {refused}")
    assert not problems, f"{case} / {step}: " + " | ".join(problems)
    if case != "index_gitlink":
        assert os.path.lexists(team.ws / "sub" / ".git"), "Temper never removes a member's files"


# --- a .git at the top of the folder: git never reads it, so it is allowed ---------------------


@pytest.mark.parametrize("case", ["gitdir_file", "git_link", "commondir", "git_init"])
def test_m1_a_git_at_the_top_of_the_folder_is_never_read_so_it_is_allowed(
        tmp_path, monkeypatch, case):
    """Temper always names the git dir and the work tree, so git never looks for a .git at
    the work tree's top: a member's own .git there (a gitdir: file, a link, a commondir folder,
    a repository it made) is neither opened nor recorded, and every step works as on a clean
    folder."""
    team = Team(tmp_path)
    outside = ls.project(tmp_path / "outside", {"secret.txt": "another repository's file\n"})
    (team.ws / "notes.md").write_text(WORK)
    target = _plant(case, team.ws, team.gd, outside, top=True)
    assert target is not None
    opened = Opens(target)
    spy = GitSpy(monkeypatch)

    got = team.shared.share("mallory", team.pdir)
    assert team.shared.unshared("mallory", team.pdir) is None
    sha = team.copies.commit_review("mallory", team.pdir, "act-2")
    assert team.copies.changes("mallory", team.pdir) == 0
    assert team.copies.differs("mallory", team.pdir, sha) is None
    team.copies.move_to("mallory", team.pdir, "lead", "act-1", team.lead_sha)

    assert got.status == "shared"
    assert _tree(team.shared.path, got.head) == TREE
    assert opened.seen() == [], "git opened the member's top .git"
    assert _gitlinks(team.gd) == set() and _gitlinks(team.shared.path) == set()
    assert "add" in spy.over(team.ws), "git still runs over the folder"
    assert os.path.lexists(team.ws / ".git"), "Temper never removes a member's files"


# --- B4: only the top's exact ".git" is passed by; any other spelling there is refused -----


#: Names that only start like ``.git``, and a folder called ``git``: ordinary files to git.
CLEAN_NAMES = {".github/workflows/ci.yml": "on: push\n", ".gitkeep": "",
               ".git-blame-ignore-revs": "\n", "git/notes.txt": "a folder called git\n",
               "docs/.gitkeep": ""}


def _plant_top_spelling(ws: Path, outside: Path) -> Path:
    """Security's B4 case: a folder named ``.GIT`` at the folder's top (an ordinary folder to
    git on this filesystem, which git walks into) holding a ``.git`` file naming another
    repository. Returns the git folder git would follow there."""
    (ws / ".GIT").mkdir(parents=True)
    (ws / ".GIT" / ".git").write_text(f"gitdir: {outside / '.git'}\n")
    return outside / ".git"


@pytest.mark.parametrize("step", STEPS)
def test_m1_b4_a_git_spelled_otherwise_at_the_top_is_refused_before_git_runs(
        tmp_path, monkeypatch, step):
    """Only the top's own entry spelled exactly ``.git`` is one git never reads. ``.GIT`` at
    the top is an ordinary folder to git, which walks into it and follows the ``.git`` inside:
    every step on both wrappers is refused before any git starts over the folder, nothing
    opens the planted repository and no gitlink is recorded."""
    team = Team(tmp_path, ensure_mallory=step != "ensure")
    outside = ls.project(tmp_path / "outside", {"secret.txt": "another repository's file\n"})
    team.ws.mkdir(parents=True, exist_ok=True)
    (team.ws / "notes.md").write_text(WORK)
    opened = Opens(_plant_top_spelling(team.ws, outside))
    spy = GitSpy(monkeypatch)

    refused: Exception | None = None
    try:
        team.step(step)
    except (CopyError, VersionError) as exc:
        refused = exc

    problems = []
    over = spy.over(team.ws)
    if over:
        problems.append(f"git ran over the member's folder: {over}")
    seen = opened.seen()
    if seen:
        problems.append(f"the planted repository was opened: {sorted(set(seen))}")
    links = (_gitlinks(team.gd) if (team.gd / "HEAD").exists() else set()) | _gitlinks(
        team.shared.path)
    if links:
        problems.append(f"gitlinks recorded: {sorted(links)}")
    if refused is None:
        problems.append("the step was not refused")
    elif not (isinstance(refused, CopyError) and isinstance(refused, VersionError)):
        problems.append(f"refused with {type(refused).__name__}: {refused}")
    elif str(refused) != _refused_git(".GIT"):
        problems.append(f"refused with: {refused}")
    assert not problems, f".GIT / {step}: " + " | ".join(problems)
    assert (team.ws / ".GIT" / ".git").exists(), "Temper never removes a member's files"


@pytest.mark.parametrize("step", ["share", "commit_review"])
def test_m1_b4_clean_names_that_only_start_like_git_run_git_as_before(
        tmp_path, monkeypatch, step):
    """Clean controls on both wrappers: ``.github``, ``.gitkeep``, ``.git-blame-ignore-revs``
    and a folder called ``git``, at the top and below it, are nothing to refuse: git runs over
    the folder as before and records them."""
    team = Team(tmp_path)
    (team.ws / "notes.md").write_text(WORK)
    for rel, text in CLEAN_NAMES.items():
        (team.ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (team.ws / rel).write_text(text)
    spy = GitSpy(monkeypatch)

    if step == "share":
        got = team.shared.share("mallory", team.pdir)
        assert got.status == "shared"
        git_dir, commit = team.shared.path, got.head
    else:
        git_dir, commit = team.gd, team.copies.commit_review("mallory", team.pdir, "act-2")

    assert "add" in spy.over(team.ws), "git still runs over the folder"
    names = set(ls.git(git_dir, f"--git-dir={git_dir}", "ls-tree", "-r", "--name-only",
                       commit).split())
    assert set(CLEAN_NAMES) <= names
    assert _gitlinks(team.gd) == set() and _gitlinks(team.shared.path) == set()


def test_m1_b4_the_walk_passes_by_only_the_tops_exact_git(tmp_path):
    from temper_ai.pi_agent.member_tree import nested_git

    outside = ls.project(tmp_path / "outside")
    root = tmp_path / "ws"
    (root / ".git").mkdir(parents=True)                       # the top's own: passed by
    (root / ".GIT").mkdir()                                   # Security's B4 case: a folder
    (root / ".GIT" / ".git").write_text(f"gitdir: {outside / '.git'}\n")
    (root / ".Git").write_text(f"gitdir: {outside / '.git'}\n")    # a file
    os.symlink(outside / ".git", root / ".gIT")              # a link
    for rel in CLEAN_NAMES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")

    assert nested_git(root) == [".GIT", ".Git", ".gIT"]


# --- the walk itself ------------------------------------------------------------------------


def test_m1_the_walk_names_every_git_below_the_top_of_any_type_and_never_follows_a_link(
        tmp_path):
    from temper_ai.pi_agent.member_tree import nested_git

    outside = ls.project(tmp_path / "outside")
    root = tmp_path / "ws"
    (root / ".git").mkdir(parents=True)                     # the top's own: git ignores it
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / ".git").write_text(f"gitdir: {outside / '.git'}\n")     # a file
    (root / "c").mkdir()
    os.symlink(outside / ".git", root / "c" / ".git")       # a link
    (root / "d" / ".git" / "deeper" / ".git").mkdir(parents=True)               # a folder
    (root / "e").mkdir()
    os.mkfifo(root / "e" / ".git")                          # anything else
    (root / "f").mkdir()
    (root / "f" / ".GIT").write_text("gitdir: /elsewhere\n")    # any letter case
    os.symlink(outside, root / "linked")                    # a link to a repository: not followed
    os.symlink(root, root / "a" / "loop")                   # a loop: not followed
    (root / "plain" / "deep").mkdir(parents=True)
    (root / "plain" / "deep" / "file.git").write_text("not a .git\n")

    assert nested_git(root) == ["a/b/.git", "c/.git", "d/.git", "e/.git", "f/.GIT"]
    assert nested_git(root / "plain") == []


def test_m1_the_refusal_names_at_most_five_paths(tmp_path, monkeypatch):
    team = Team(tmp_path)
    for name in "gfedcba":
        (team.ws / name).mkdir()
        (team.ws / name / ".git").write_text("gitdir: /nowhere\n")
    spy = GitSpy(monkeypatch)
    with pytest.raises(CopyError) as refused:
        team.copies.changes("mallory", team.pdir)
    # the walk stops at the sixth it finds (which six depends on the listing order): five are
    # named and the rest only said
    head = "Temper won't run git over your folder while it holds a .git of its own: "
    tail = " and more. Remove them and try again."
    text = str(refused.value)
    assert text.startswith(head) and text.endswith(tail)
    named = [json.loads(q) for q in text[len(head):-len(tail)].split(", ")]
    assert len(named) == 5 and named == sorted(named)
    assert set(named) <= {f"{n}/.git" for n in "abcdefg"}
    assert spy.over(team.ws) == []


@pytest.mark.parametrize("cap", ["entries", "depth", "seconds"])
def test_m1_a_folder_the_check_cannot_finish_is_refused(tmp_path, monkeypatch, cap):
    """The walk has caps on the entries it looks at, how deep it goes and the time it takes;
    hitting one refuses, so git never runs over a folder nobody checked."""
    team = Team(tmp_path)
    for i in range(6):
        (team.ws / f"f{i}.txt").write_text("x\n")
    (team.ws / "a" / "b" / "c").mkdir(parents=True)
    limit = {"entries": ("GIT_CHECK_ENTRIES", 5), "depth": ("GIT_CHECK_DEPTH", 2),
             "seconds": ("GIT_CHECK_SECONDS", 0.0)}[cap]
    monkeypatch.setattr(member_tree, *limit)
    spy = GitSpy(monkeypatch)

    with pytest.raises(CopyError) as refused:
        team.copies.commit_review("mallory", team.pdir, "act-2")

    assert isinstance(refused.value, VersionError)
    assert str(refused.value) == {
        "entries": "Temper won't run git over your folder: it holds more than 5 entries, the "
                   "most Temper checks for a .git of its own.",
        "depth": "Temper won't run git over your folder: it nests folders deeper than 2, the "
                 "most Temper checks for a .git of its own.",
        "seconds": "Temper won't run git over your folder: checking it for a .git of its own "
                   "took longer than 0 seconds.",
    }[cap]
    assert spy.over(team.ws) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens any folder")
def test_m1_a_folder_the_walk_cannot_open_is_refused(tmp_path, monkeypatch):
    team = Team(tmp_path)
    shut = team.ws / "shut"
    (shut / "inner").mkdir(parents=True)
    shut.chmod(0)
    spy = GitSpy(monkeypatch)
    try:
        with pytest.raises(CopyError) as refused:
            team.copies.changes("mallory", team.pdir)
    finally:
        shut.chmod(0o755)
    assert isinstance(refused.value, VersionError)
    assert str(refused.value) == ("Temper won't run git over your folder: it can't read "
                                  '"shut" (EACCES) to check it for a .git of its own.')
    assert spy.over(team.ws) == []


# --- the walk's resources (Security B2) -------------------------------------------------------


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


class Listings:
    """While on, every folder listing (``os.scandir``) is counted as it hands out entries: how
    many it handed out, and the most descriptors the process held meanwhile (over the count
    before). ``fail_in``: the listing of a folder of that name fails with EIO."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, fail_in: str | None = None):
        self.pulled = 0
        self.most_fds = 0
        base = _open_fds()
        real = os.scandir
        spy = self

        class Counted:
            def __init__(self, listing, fails: bool):
                self.listing, self.fails = listing, fails

            def __iter__(self):
                return self

            def __next__(self):
                if self.fails:
                    raise OSError(errno.EIO, "input/output error")
                entry = next(self.listing)
                spy.pulled += 1
                spy.most_fds = max(spy.most_fds, _open_fds() - base)
                return entry

            def close(self):
                self.listing.close()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()

        def scandir(path="."):
            fails = (fail_in is not None and isinstance(path, int)
                     and os.readlink(f"/proc/self/fd/{path}").endswith(f"/{fail_in}"))
            return Counted(real(path), fails)

        monkeypatch.setattr(os, "scandir", scandir)


def test_m1_the_walk_holds_descriptors_by_depth_and_counts_entries_as_they_come(
        tmp_path, monkeypatch):
    """A wide folder doesn't open a descriptor per subfolder before looking into them, and a
    long listing is counted as it is read: the entries cap refuses before the rest is read."""
    wide = tmp_path / "wide"
    for i in range(300):
        (wide / f"d{i:03}").mkdir(parents=True)
        (wide / f"d{i:03}" / "file.txt").write_text("x\n")
    long = tmp_path / "long"
    long.mkdir()
    for i in range(2000):
        (long / f"f{i:04}.txt").write_text("")

    listings = Listings(monkeypatch)
    assert member_tree.nested_git(wide) == []
    assert listings.pulled == 600
    assert listings.most_fds <= 6, "a descriptor per subfolder: it grew with breadth"

    listings = Listings(monkeypatch)
    monkeypatch.setattr(member_tree, "GIT_CHECK_ENTRIES", 100)
    with pytest.raises(member_tree.GitCheckUnfinished) as unfinished:
        member_tree.nested_git(long)
    assert str(unfinished.value) == ("it holds more than 100 entries, the most Temper checks "
                                     "for a .git of its own")
    assert listings.pulled == 101, "the whole listing was read before the cap"


def test_m1_a_listing_that_fails_midway_is_refused(tmp_path, monkeypatch):
    team = Team(tmp_path)
    (team.ws / "a" / "b").mkdir(parents=True)
    Listings(monkeypatch, fail_in="a")
    spy = GitSpy(monkeypatch)
    with pytest.raises(CopyError) as refused:
        team.copies.changes("mallory", team.pdir)
    assert isinstance(refused.value, VersionError)
    assert str(refused.value) == ("Temper won't run git over your folder: it can't read "
                                  '"a" (EIO) to check it for a .git of its own.')
    assert spy.over(team.ws) == []


# --- what a refusal says (Security B3) --------------------------------------------------------


def test_m1_a_refusal_shows_odd_paths_as_quoted_escaped_data_and_no_command(
        tmp_path, monkeypatch):
    """A member names its files. A refusal shows them quoted, with control, non-ASCII and quote
    characters escaped and long ones cut, and gives no command to copy."""
    team = Team(tmp_path)
    odd = ["-rf --no-preserve-root", "\x1b[31mred", "a\nb", 'q"uote\\', "\u00e9" + "x" * 100]
    for name in odd:
        (team.ws / name).mkdir()
        (team.ws / name / ".git").write_text("gitdir: /nowhere\n")
    spy = GitSpy(monkeypatch)
    with pytest.raises(CopyError) as refused:
        team.copies.changes("mallory", team.pdir)
    text = str(refused.value)
    assert all(" " <= c <= "~" for c in text), "a control or non-ASCII character got through"
    assert "rm " not in text and "Remove them and try again." in text
    assert '"-rf --no-preserve-root/.git"' in text
    assert '"\\u001b[31mred/.git"' in text and '"a\\nb/.git"' in text
    assert '"q\\"uote\\\\/.git"' in text
    long = "\u00e9" + "x" * 100 + "/.git"
    assert json.dumps(long[:28] + "..." + long[-29:]) in text
    assert spy.over(team.ws) == []

    for name in odd:
        (team.ws / name / ".git").unlink()
    outside = ls.project(tmp_path / "outside")
    ls.git(team.ws, f"--git-dir={team.gd}", f"--work-tree={team.ws}", "update-index", "--add",
           "--cacheinfo", f"160000,{ls.git(outside, 'rev-parse', 'HEAD')},bad\x07name")
    with pytest.raises(CopyError) as refused:
        team.copies.changes("mallory", team.pdir)
    assert str(refused.value) == _refused_gitlink("bad\x07name")
    assert '"bad\\u0007name"' in str(refused.value)


# --- git is always told the git dir (Security: no discovery fallback) ------------------------


def test_m1_git_over_a_member_folder_must_be_told_its_git_dir_outside_the_folder(
        tmp_path, monkeypatch):
    """The top's own .git is allowed only because git is told the git dir: without it, or with
    one inside the folder, from a folder below the top or with a GIT_ variable that could point
    it elsewhere, git might look for a repository itself, so both wrappers refuse."""
    team = Team(tmp_path)
    outside = ls.project(tmp_path / "outside")
    (team.ws / ".git").write_text(f"gitdir: {outside / '.git'}\n")
    (team.ws / "sub").mkdir()
    spy = GitSpy(monkeypatch)
    c, s, ws, gd = team.copies, team.shared, team.ws, team.gd
    tries = [
        lambda: c._g(["status"], work_tree=ws),
        lambda: c._g(["status"], git_dir=ws / "own.git", work_tree=ws),
        lambda: c._g(["status"], git_dir=gd, work_tree=ws, cwd=ws / "sub"),
        lambda: s._git(["status"], work_tree=ws),
        lambda: s._git(["status"], git_dir=gd, work_tree=ws,
                       env={"GIT_DIR": str(outside / ".git")}),
    ]
    for attempt in tries:
        with pytest.raises(CopyError) as refused:
            attempt()
        assert isinstance(refused.value, VersionError) and str(refused.value) == NOT_TOLD
    assert spy.calls == []
    assert c._g(["status", "--porcelain"], git_dir=gd, work_tree=ws, cwd=ws) == b""


# --- a gitlink the Project started with -------------------------------------------------------


def test_m1_a_gitlink_the_project_started_with_is_allowed_and_any_other_is_refused(
        tmp_path, monkeypatch):
    """A workspace with a submodule gives every copy its gitlink (SW-34): that one, at the same
    path and commit, is the Project's own and every step works. A gitlink at another commit,
    or at another path, is refused."""
    sub = ls.project(tmp_path / "subrepo", {"inside.txt": "the submodule's own file\n"})
    src = ls.project(tmp_path / "proj")
    ls.git(src, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub),
           "vendor/sub")
    ls.git(src, "commit", "-q", "-m", "a submodule")
    team = Team(tmp_path, source=src)
    own = ("vendor/sub", ls.git(sub, "rev-parse", "HEAD"))
    (team.ws / "notes.md").write_text(WORK)

    got = team.shared.share("mallory", team.pdir)
    sha = team.copies.commit_review("mallory", team.pdir, "act-2")
    assert got.status == "shared"
    assert team.copies.changes("mallory", team.pdir) == 0
    assert _gitlinks(team.gd) == {own} and _gitlinks(team.shared.path) == {own}

    other = ls.git(src, "rev-parse", "HEAD")    # a commit, but not the one the Project holds
    ls.git(team.ws, f"--git-dir={team.gd}", f"--work-tree={team.ws}", "update-index",
           "--cacheinfo", f"160000,{other},vendor/sub")
    spy = GitSpy(monkeypatch)
    with pytest.raises(CopyError) as refused:
        team.copies.commit_review("mallory", team.pdir, "act-3")
    assert isinstance(refused.value, VersionError)
    assert str(refused.value) == _refused_gitlink("vendor/sub")
    assert spy.over(team.ws) == []
    assert team.copies._head(team.gd) == sha, "no commit was made"


def test_m1_a_gitlink_kept_in_a_split_index_is_refused_too(tmp_path, monkeypatch):
    """The index is only read with ``ls-files`` when it may hold a gitlink. A split index keeps
    entries in a ``sharedindex`` file beside it, so then it is always read."""
    team = Team(tmp_path)
    outside = ls.project(tmp_path / "outside")
    _plant("index_gitlink", team.ws, team.gd, outside)
    ls.git(team.ws, f"--git-dir={team.gd}", f"--work-tree={team.ws}", "update-index",
           "--split-index")
    assert list(team.gd.glob("sharedindex.*"))
    spy = GitSpy(monkeypatch)
    with pytest.raises(CopyError) as refused:
        team.copies.commit_review("mallory", team.pdir, "act-2")
    assert str(refused.value) == _refused_gitlink("vendored")
    assert spy.over(team.ws) == []
    assert any(_sub(cmd) == "ls-files" for cmd, _cwd in spy.calls)


# --- B1: nothing may still write in the folder while Temper's git runs over it -----------------
#
# Security's B1 (rm-391c37c3): something still writing in the folder could plant a .git between
# the check and git. So right before each git call over a member's folder Temper also refuses
# while Docker lists a box of that member in any state but exited or dead, while the ledger shows
# a turn of that member in flight, or while Docker can't be asked (the lead's option A,
# rm-0d94e81f). These tests use the team's ledger; Docker is a stand-in that answers Temper's
# listing.

BOX = "temper-pi-" + "ab" * 10
OTHER_BOX = "temper-pi-" + "cd" * 10
ROW = '{{json .Names}}\t{{json .State}}\t{{json (.Label "temper.pi.turn")}}'


class Docker:
    """Docker as Temper's box listing reaches it: the boxes it answers with (name, state, turn
    label) or a failure, and every listing Temper asked for."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, boxes: tuple = (),
                 fail: str | None = None):
        self.boxes, self.fail, self.asked = list(boxes), fail, []
        monkeypatch.setattr(LeaderTeam, "list_boxes", None, raising=False)
        monkeypatch.setattr(pi_box, "_docker_cli", self)

    def __call__(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        self.asked.append(list(args))
        if self.fail == "timeout":
            raise subprocess.TimeoutExpired(["docker", *args], timeout)
        if self.fail == "missing":
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "docker")
        if self.fail == "error":
            return subprocess.CompletedProcess(args, 1, "", "Cannot connect to the Docker "
                                               "daemon at unix:///var/run/docker.sock.\n")
        if self.fail == "garbage":
            return subprocess.CompletedProcess(args, 0, f"{BOX} running\n", "")
        rows = "".join("\t".join(json.dumps(v) for v in b) + "\n" for b in self.boxes)
        return subprocess.CompletedProcess(args, 0, rows, "")


class Flow:
    """A free-flowing team opened as the team node opens it (lead, builder, checker): the
    builder's review commit to move a copy to, and the lead's own notes in its folder."""

    def __init__(self, led, box, run_id: str, tmp: Path):
        self.led, self.run_id = led, run_id
        self.team = ls.open_flow(led, box, run_id=run_id, source=ls.project(tmp / "proj"))
        self.pdirs = {n: self.team._pdir(r) for n, r in self.team._member_rows().items()}
        self.builder_sha = self.team.project.commit_review("builder", self.pdirs["builder"],
                                                           "act-1")
        (self.ws / "notes.md").write_text(WORK)

    @property
    def ws(self) -> Path:
        return ProjectCopies.worktree(self.pdirs["lead"])

    def claim(self, member: str = "lead", *, attempt: str = "attempt-1",
              box_name: str | None = None) -> dict:
        """The member's next turn, claimed by hand, its box named as ``run_turn`` names it."""
        turn, _batch, binding = ts.claim_bound(self.led, self.run_id, attempt=attempt)
        assert binding.member == member
        if box_name:
            assert self.led.record_box(turn["turn_id"], turn["epoch"], box_name)
        return turn

    def step(self, step: str) -> object:
        c, s, p = self.team.project, self.team.shared, self.pdirs["lead"]
        if step == "ensure":
            shutil.rmtree(c.git_dir("lead"))     # no copy yet: ensure makes it over the folder
            return c.ensure("lead", p)
        if step == "differs":
            return c.differs("lead", p, c._head(c.git_dir("lead")) or "")
        return {
            "share": lambda: s.share("lead", p),
            "sync": lambda: s.sync("lead", p),
            "unshared": lambda: s.unshared("lead", p),
            "commit_review": lambda: c.commit_review("lead", p, "act-2"),
            "changes": lambda: c.changes("lead", p),
            "move_to": lambda: c.move_to("lead", p, "builder", "act-1", self.builder_sha),
        }[step]()


def _refused_while(what: str) -> str:
    return f"Temper won't run git over your folder while {what}."


def _no_docker(detail: str) -> str:
    return f"Temper won't run git over your folder: it can't ask Docker which boxes are live ({detail})."


def _refused(flow: Flow, step: str, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], object]:
    """(git over the lead's folder, the refusal or None) for one step."""
    spy = GitSpy(monkeypatch)
    try:
        flow.step(step)
    except CopyError as exc:
        return spy.over(flow.ws), exc
    return spy.over(flow.ws), None


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("case", ["live_box", "turn_in_flight", "docker_error", "leftover_box"])
def test_b1_git_never_runs_over_a_folder_something_may_still_write_in(
        led, box, run_id, tmp_path, monkeypatch, case, step):
    """Each step over the lead's folder is refused before any git starts over it while: its
    turn is over but its box is still live (never removed); a turn of it is in flight (Docker
    lists nothing: not made yet, or gone); Docker can't be asked; a box an earlier attempt of
    the same run left is still live."""
    flow = Flow(led, box, run_id, tmp_path)
    if case == "live_box":
        turn = flow.claim(box_name=BOX)
        ts.settle(led, turn)
        Docker(monkeypatch, ((BOX, "running", turn["turn_id"][:16]),))
        want = _refused_while(f"a box of yours is still live: {BOX} (running)")
    elif case == "turn_in_flight":
        flow.claim(box_name=BOX)
        Docker(monkeypatch)
        want = _refused_while("a turn of yours is still in flight: turn 1 (running)")
    elif case == "docker_error":
        Docker(monkeypatch, fail="error")
        want = _no_docker("docker ps failed with exit 1")
    else:
        turn = flow.claim(attempt="attempt-0", box_name=BOX)
        ts.settle(led, turn, attempt="attempt-0")
        Docker(monkeypatch, ((BOX, "created", turn["turn_id"][:16]),))
        want = _refused_while(f"a box of yours is still live: {BOX} (created)")
    over, refused = _refused(flow, step, monkeypatch)
    assert over == [], "git ran over the member's folder"
    assert refused is not None, "the step was not refused"
    assert isinstance(refused, VersionError) and str(refused) == want


@pytest.mark.parametrize("state", ["created", "running", "paused", "restarting", "removing",
                                   "exited", "dead"])
def test_b1_only_an_exited_or_dead_box_frees_the_folder(
        led, box, run_id, tmp_path, monkeypatch, state):
    """Every Docker state but exited and dead counts as a box that may still write."""
    flow = Flow(led, box, run_id, tmp_path)
    turn = flow.claim(box_name=BOX)
    ts.settle(led, turn)
    Docker(monkeypatch, ((BOX, state, turn["turn_id"][:16]),))
    over, refused = _refused(flow, "share", monkeypatch)
    if state in ("exited", "dead"):
        assert refused is None and over == ["status", "add", "commit", "merge"]
    else:
        assert over == [] and refused is not None
        assert str(refused) == _refused_while(f"a box of yours is still live: {BOX} ({state})")


@pytest.mark.parametrize(("fail", "detail"), [
    ("error", "docker ps failed with exit 1"),
    ("timeout", "docker ps took too long"),
    ("missing", "docker ps could not run"),
    ("garbage", "docker ps answered with a line Temper can't read"),
])
def test_b1_docker_that_cannot_be_asked_is_refused(
        led, box, run_id, tmp_path, monkeypatch, fail, detail):
    flow = Flow(led, box, run_id, tmp_path)
    Docker(monkeypatch, fail=fail)
    over, refused = _refused(flow, "share", monkeypatch)
    assert over == [] and refused is not None and str(refused) == _no_docker(detail)


@pytest.mark.parametrize("label", ["", "0123456789abcdef"])
def test_b1_a_live_box_of_the_run_temper_cannot_place_is_refused(
        led, box, run_id, tmp_path, monkeypatch, label):
    """A live box of this run whose turn label names no turn of the run might be any member's."""
    flow = Flow(led, box, run_id, tmp_path)
    Docker(monkeypatch, ((OTHER_BOX, "running", label),))
    over, refused = _refused(flow, "share", monkeypatch)
    assert over == [] and refused is not None
    assert str(refused) == _refused_while(
        f"a box of this run that Temper can't place is live: {OTHER_BOX} (running)")


def test_b1_clean_another_members_live_box_and_the_turn_git_runs_for_leave_git_as_before(
        led, box, run_id, tmp_path, monkeypatch):
    """The clean control: the lead's own turn, claimed and not yet given a box, syncs as
    before; once it is over, its exited box gone, the builder working in its own live box, the
    lead's share runs the same git over its folder as before the check. One listing is asked
    right before each git call over the folder, for exactly this run's boxes by label."""
    flow = Flow(led, box, run_id, tmp_path)
    docker = Docker(monkeypatch)
    turn, batch, _binding = ts.claim_bound(led, run_id)
    spy = GitSpy(monkeypatch)
    flow.team.prompt_for(ts.member("lead"), turn, batch)
    # as before the check (pinned on 03bb848c): the sync keeps the lead's notes, then merges
    assert spy.over(flow.ws) == ["status", "add", "commit", "merge"]
    ts.settle(led, turn)
    flow.team.post("builder", "start on the tests")
    builder_turn = flow.claim("builder", box_name=OTHER_BOX)
    docker.boxes = [(OTHER_BOX, "running", builder_turn["turn_id"][:16]),
                    (BOX, "exited", turn["turn_id"][:16])]
    docker.asked.clear()
    over, refused = _refused(flow, "share", monkeypatch)
    # as before the check: the notes were kept by the sync, so the share only merges
    assert refused is None and over == ["status", "merge"]


def test_b1_docker_is_asked_for_exactly_this_runs_boxes_right_before_each_git_call(
        led, box, run_id, tmp_path, monkeypatch):
    """One listing right before each git call over the folder, by the exact labels every
    worker box gets (never by a name prefix), in every state."""
    flow = Flow(led, box, run_id, tmp_path)
    docker = Docker(monkeypatch)
    over, refused = _refused(flow, "share", monkeypatch)
    assert refused is None and over == ["status", "add", "commit", "merge"]
    assert docker.asked == [["ps", "--all", "--no-trunc", "--filter", "label=temper.pi.box=1",
                             "--filter", f"label=temper.pi.run={run_id}", "--format", ROW]] * 4


# The check-to-git window across attempts (the lead's fence, #110): an older attempt's turn
# thread can name its box, then stall before creating it while a newer attempt takes the turn
# over and, finding no container, counts the box as gone. Without a fence that thread would
# later create and start the box: a writer the check can miss if it starts between the check
# and git, and a second box on the folder beside the member's next turn. So right before the
# container starts, the turn is asked again (the box name's fenced write). These run the real
# run_turn and WorkerBox; Docker is a stand-in with containers in it.

TAKEN = "the turn was taken over by another attempt after its box was created"


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


class Containers:
    """Docker with containers in it, one table for a worker box's own calls (create, rm, ps by
    name), a take-over's (inspect, kill, rm), ``docker start`` (the box's RPC) and the listing
    Temper's git check asks for. ``on_create`` runs once, when a box asks to be created, before
    its container exists: the stale owner's stall. ``rm_fails`` makes every removal fail.
    ``log`` keeps the order of creates, fences, removals and starts."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, log: list, *, on_create=None,
                 rm_fails: bool = False):
        self.table: dict[str, list[str]] = {}            # name -> [state, turn label]
        self.log, self.on_create, self.rm_fails = log, on_create, rm_fails
        monkeypatch.setattr(LeaderTeam, "list_boxes", None, raising=False)
        monkeypatch.setattr(pi_box, "_docker_cli", self)
        monkeypatch.setattr(pi_box, "Rpc", self.start)

    def __call__(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        def ok(out: str = "") -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args, 0, out, "")

        verb, name = args[0], args[-1]
        if verb == "create":
            if self.on_create is not None:
                stall, self.on_create = self.on_create, None
                stall()
            made = args[args.index("--name") + 1]
            turn = next((a.split("=", 1)[1] for a in args if a.startswith("temper.pi.turn=")),
                        "")
            self.table[made] = ["created", turn]
            self.log.append(("create", made))
            return ok("c0ffee\n")
        if verb == "ps" and ROW in args:                     # the git check's listing
            return ok("".join("\t".join(json.dumps(v) for v in (n, *row)) + "\n"
                              for n, row in self.table.items()))
        if verb == "ps":                                    # by exact name, after a removal
            asked = args[args.index("--filter") + 1].removeprefix("name=^").removesuffix("$")
            return ok("c0ffee\n" if asked in self.table else "")
        if name not in self.table:
            return subprocess.CompletedProcess(
                args, 1, "", f"Error response from daemon: No such container: {name}\n")
        if verb == "inspect":
            running = self.table[name][0] == "running"
            return ok(f"{str(running).lower()}\n" if "{{.State.Running}}" in args else "c0ffee\n")
        if verb == "kill":
            self.table[name][0] = "exited"
            return ok(name + "\n")
        if verb == "rm":
            if self.rm_fails:
                return subprocess.CompletedProcess(
                    args, 1, "", "Error response from daemon: could not remove the container\n")
            del self.table[name]
            self.log.append(("removed", name))
            return ok(name + "\n")
        raise AssertionError(f"Docker was asked for {args}")

    def start(self, cmd: list[str], **_kw) -> _Attached:
        """``docker start --attach``: the container runs if it is still there, else it fails."""
        box_name = cmd[-1]
        ran = box_name in self.table
        if ran:
            self.table[box_name][0] = "running"
        self.log.append(("start", box_name, ran))
        return _Attached()


class _Attached:
    """What run_turn reaches through a started box: a Pi that never answers."""

    def command(self, *_a, **_k):
        raise RpcError("protocol_eof")

    def reply(self, *_a, **_k):
        raise RpcError("protocol_eof")

    def close(self) -> dict:
        return {}


class Fence:
    """The team's ledger as run_turn writes to it. The second write of the box's name is the
    fence before the box starts: ``error`` makes it raise, ``then`` runs right after it."""

    def __init__(self, led, log: list, *, then=None, error: Exception | None = None):
        self.led, self.log, self.then, self.error, self.writes = led, log, then, error, 0

    def __getattr__(self, attr: str):
        return getattr(self.led, attr)

    def record_box(self, turn_id: str, epoch: int | None, name: str | None) -> bool:
        self.writes += 1
        if self.writes == 1:
            return self.led.record_box(turn_id, epoch, name)
        if self.error is not None:
            self.log.append(("fence", "error"))
            raise self.error
        held = self.led.record_box(turn_id, epoch, name)
        self.log.append(("fence", held))
        if self.then is not None:
            self.then()
        return held


class _Recorder:
    def record(self, event_type, data=None, parent_id=None, execution_id=None, status=None,
               event_id=None):
        return event_id or "ev"

    def broadcast_stream_chunk(self, *a, **k):
        pass


def _turn_in_a_box(flow: Flow, turn: dict, ledger, containers: Containers, tmp_path: Path,
                   short_root: Path):
    """The lead's turn as the Pi lane runs it, in a real WorkerBox over the lead's folder,
    labelled as the team labels its boxes; only Docker and Pi are stand-ins."""
    def worker_box(cfg, spec, redactor):
        made = pi_box.WorkerBox(cfg, spec, redactor, owner_token=lambda _p: "",
                                connector=lambda _host: socket.socketpair()[0])
        made._docker = containers
        made._check_search_tools = lambda: None
        made._read_back_pins = lambda: {}
        made._inspect = lambda: {"stand_in": "sealed as asked"}
        return made

    pdir = flow.pdirs["lead"]
    spec = sup.spec(pdir, labels={"run": flow.run_id[:36], "turn": turn["turn_id"][:16]})
    req = TurnRequest(run_id=flow.run_id, agent_name="lead", node_path="team",
                      participant={"participant_id": turn["participant_id"]}, turn=turn,
                      text="Carry on.", spec=spec, agent_event_id="agent-1",
                      recorder=_Recorder(), first_start=True)
    cfg = sup.box_config(tmp_path / "box", socket_root=str(short_root))
    return run_turn(cfg, req, ledger, box_factory=worker_box)


def _take_over(led, run_id: str, containers: Containers, took: list):
    """A newer attempt taking the team's cut-off turns over, as a resume does."""
    def take() -> None:
        took.extend(led.take_over(run_id, ts.HOST, "attempt-2", stop_box=lambda name: (
            pi_box.stop_leftover_box(name, docker=containers))))
    return take


def test_b1_fence_a_box_whose_turn_was_taken_over_before_it_was_created_never_starts(
        led, box, run_id, tmp_path, short_root, monkeypatch):
    """Case 1: the stale thread named its box, then stalled; the take-over found no container.
    When the thread creates it, the fence fails: the container is removed and never started.
    While the taken-over turn is unsettled it still counts as in flight; once it is settled,
    git runs over the folder with no writer."""
    flow = Flow(led, box, run_id, tmp_path)
    log: list = []
    took: list = []
    containers = Containers(monkeypatch, log)
    containers.on_create = _take_over(led, run_id, containers, took)
    turn = flow.claim()
    report = _turn_in_a_box(flow, turn, Fence(led, log), containers, tmp_path, short_root)
    name = log[0][1]
    assert log == [("create", name), ("fence", False), ("removed", name)], "the box started"
    assert containers.table == {}
    assert report.state == "failed"
    assert report.error == f"turn_taken_over: {TAKEN}; the box was removed and never started"
    assert report.worker["container_removed"] is True
    assert report.worker["fenced"] == {"why": TAKEN, "started": False, "removed": True}
    ((taken, wait),) = took
    assert taken["box_stop"]["confirmed"] is True and taken["box_stop"]["found"] is False
    over, refused = _refused(flow, "share", monkeypatch)
    assert over == [] and str(refused) == _refused_while(
        "a turn of yours is still in flight: turn 1 (uncertain)")
    assert led.decide_wait(wait["wait_id"], {"answer": "stop"}, "attempt-2",
                           recovery=("stop", turn["turn_id"]))
    over, refused = _refused(flow, "share", monkeypatch)
    assert refused is None and over == ["status", "add", "commit", "merge"]


def test_b1_fence_a_box_taken_over_after_its_fence_is_removed_and_its_start_fails(
        led, box, run_id, tmp_path, short_root, monkeypatch):
    """Case 2: the fence passes, then a take-over moves the turn on and finds the container
    created, so it removes it: docker start then fails and no box ever runs."""
    flow = Flow(led, box, run_id, tmp_path)
    log: list = []
    took: list = []
    containers = Containers(monkeypatch, log)
    turn = flow.claim()
    fence = Fence(led, log, then=_take_over(led, run_id, containers, took))
    report = _turn_in_a_box(flow, turn, fence, containers, tmp_path, short_root)
    name = log[0][1]
    assert log == [("create", name), ("fence", True), ("removed", name),
                   ("start", name, False)], "the fence was not asked before the box started"
    assert containers.table == {}
    ((taken, _wait),) = took
    assert taken["box_stop"]["found"] is True and taken["box_stop"]["confirmed"] is True
    assert report.state == "failed" and report.error.startswith("the worker stopped answering")
    assert led.turn(turn["turn_id"])["state"] == "uncertain"


def test_b1_fence_that_cannot_be_asked_refuses_and_removes_the_box(
        led, box, run_id, tmp_path, short_root, monkeypatch):
    """Case 3: a fence that hits a database error is a refusal: removed, never started."""
    flow = Flow(led, box, run_id, tmp_path)
    log: list = []
    containers = Containers(monkeypatch, log)
    turn = flow.claim()
    error = sa.exc.OperationalError("UPDATE turns", {}, Exception("database is locked"))
    report = _turn_in_a_box(flow, turn, Fence(led, log, error=error), containers, tmp_path,
                            short_root)
    name = log[0][1]
    assert log == [("create", name), ("fence", "error"), ("removed", name)], "the box started"
    unsure = ("Temper couldn't confirm the turn is still this attempt's after its box was "
              "created (OperationalError)")
    assert report.state == "failed"
    assert report.error == f"turn_taken_over: {unsure}; the box was removed and never started"
    assert report.worker["fenced"] == {"why": unsure, "started": False, "removed": True}


def test_b1_fence_a_box_docker_will_not_remove_is_left_created_and_the_check_refuses(
        led, box, run_id, tmp_path, short_root, monkeypatch):
    """When Docker won't remove the fenced container it is left created, with no process in
    it, and named so in the receipt; Temper's git check counts it live and refuses the folder
    even after its turn is settled."""
    flow = Flow(led, box, run_id, tmp_path)
    log: list = []
    took: list = []
    containers = Containers(monkeypatch, log, rm_fails=True)
    containers.on_create = _take_over(led, run_id, containers, took)
    turn = flow.claim()
    report = _turn_in_a_box(flow, turn, Fence(led, log), containers, tmp_path, short_root)
    name = log[0][1]
    assert log == [("create", name), ("fence", False)], "the box started"
    assert containers.table == {name: ["created", turn["turn_id"][:16]]}
    assert report.error == (f"turn_taken_over: {TAKEN}; the box was never started, but Docker "
                            "didn't remove it, so it is left created with no process in it")
    assert report.worker["container_removed"] is False
    assert report.worker["fenced"] == {
        "why": TAKEN, "started": False, "removed": False,
        "left": ("created, with no process in it: Temper's git check refuses the member's "
                 "folder while it is there; a forced stop's reaper or docker rm --force "
                 f"{name} removes it")}
    ((_taken, wait),) = took
    assert led.decide_wait(wait["wait_id"], {"answer": "stop"}, "attempt-2",
                           recovery=("stop", turn["turn_id"]))
    over, refused = _refused(flow, "share", monkeypatch)
    assert over == [] and str(refused) == _refused_while(
        f"a box of yours is still live: {name} (created)")


def test_b1_fence_a_normal_turn_starts_its_box_as_before_after_one_fence(
        led, box, run_id, tmp_path, short_root, monkeypatch):
    """Case 4: a turn still its attempt's starts its box exactly as before (create, then
    start), with the fence asked once in between."""
    flow = Flow(led, box, run_id, tmp_path)
    log: list = []
    containers = Containers(monkeypatch, log)
    turn = flow.claim()
    fence = Fence(led, log)
    report = _turn_in_a_box(flow, turn, fence, containers, tmp_path, short_root)
    name = log[0][1]
    assert log == [("create", name), ("fence", True), ("start", name, True),
                   ("removed", name)], "the fence was not asked once before the box started"
    assert fence.writes == 2 and led.turn(turn["turn_id"])["box_name"] == name
    assert "fenced" not in report.worker and report.worker["container_removed"] is True
    # the stand-in Pi never answers, so the turn fails after its box started, as it would
    assert report.error.startswith("the worker stopped answering")
