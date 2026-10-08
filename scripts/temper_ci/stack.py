"""temper-ci's own clone of temper-ai, and what the gate reads from it.

Until 2026-10-08 this module also built a throwaway temper for every commit
and ran a smoke set in it. That is gone: there is one temper only, the live
one, and no test copies of it. What stays is the clone, so the gate can
fetch a commit, say what it changed and write down its tree, and the deploy
can go back to a commit it has recorded.

The clone is temper-ci's own, so ``~/temper-ai`` is never checked out,
fetched into or otherwise touched.
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .paths import MAIN_REPO, MIRROR, sh


class MirrorError(RuntimeError):
    pass


def mirror() -> Path:
    """temper-ci's own clone of temper-ai, made once and fetched since.

    Its own, deliberately: making a worktree or fetching inside
    ``~/temper-ai`` would be changing the main folder, which nothing here is
    allowed to do.
    """
    MIRROR.parent.mkdir(parents=True, exist_ok=True)
    if not (MIRROR / "HEAD").exists() and not (MIRROR / ".git").exists():
        r = sh("git", "clone", "--quiet", "--bare", str(MAIN_REPO), str(MIRROR), timeout=600)
        if r.returncode:
            raise MirrorError(f"could not clone {MAIN_REPO} into {MIRROR}: {r.stderr.strip()}")
        sh("git", "-C", str(MIRROR), "remote", "add", "upstream",
           f"https://github.com/{paths.GH_REPO}.git")
    return MIRROR


def fetch(ref: str = "") -> None:
    """Bring the mirror up to date with GitHub (and with the main folder)."""
    m = mirror()
    sh("git", "-C", str(m), "fetch", "--quiet", "--prune", "origin",
       "+refs/heads/*:refs/heads/*", timeout=300)
    sh("git", "-C", str(m), "fetch", "--quiet", "--prune", "upstream",
       "+refs/heads/*:refs/remotes/github/*", timeout=300)
    # Pull requests too, so the owner can look at one by hand after reading it — including one
    # from a fork, whose commits are on no branch here. Fetching is only reading.
    sh("git", "-C", str(m), "fetch", "--quiet", "--prune", "upstream",
       "+refs/pull/*/head:refs/remotes/pr/*", timeout=300)
    if ref:
        sh("git", "-C", str(m), "fetch", "--quiet", "upstream", ref, timeout=300)


def has_commit(sha: str) -> bool:
    return sh("git", "-C", str(mirror()), "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def changed_files(sha: str) -> list[str]:
    """What this commit changed against its first parent (everything, for a root commit)."""
    m = mirror()
    parents = sh("git", "-C", str(m), "rev-list", "--parents", "-n", "1", sha).stdout.split()
    if len(parents) < 2:
        return sh("git", "-C", str(m), "ls-tree", "-r", "--name-only", sha).stdout.split("\n")
    r = sh("git", "-C", str(m), "diff", "--name-only", f"{sha}^", sha)
    return [f for f in r.stdout.split("\n") if f]


def tree_sha(sha: str) -> str:
    return sh("git", "-C", str(mirror()), "rev-parse", f"{sha}^{{tree}}").stdout.strip()
