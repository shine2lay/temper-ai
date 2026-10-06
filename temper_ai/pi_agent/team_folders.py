"""Where a team may work: the project folder checks (M3 E5, A4 as amended by M4 item 0, SW-62).

Two levels:

* **lexical** -- everywhere, no file access: a full path, no ``..``, no spaces or control
  characters, and inside a listed project root by its text;
* **real** -- only where the folder is visible: after links the folder is still inside a
  root, it is the top of a git work tree this git can read, its git folders are inside the
  roots, it has a commit (or, when the team carries on, still has the commit its copies
  started from), and no tracked file has uncommitted changes.

Where the checks run decides what a folder that isn't visible means. The server (the Team
page's check and trial start) sees no project folder in production -- nothing under the roots
is mounted into it, because it is the run-box template -- so there it runs the lexical check
and gives the note :data:`NOT_VISIBLE_NOTE` instead of refusing. The authoritative check runs
in the Pi lane when it claims the run (runner/pi_lane.py, ADR-M4-12) and again where the
team's node starts (``authoritative=True``), both before any copy or model call: there a
folder that can't be seen is a plain problem, "<path> isn't reachable inside Temper".

Every git command runs hardened (:data:`GIT`, :func:`git_env`): no system or global config,
no hooks, no prompts. Nothing here writes to the folder.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

GIT = ("git", "-c", "safe.directory=*", "-c", "core.hooksPath=/dev/null", "-c",
       "core.fsmonitor=false", "-c", "core.autocrlf=false", "-c", "user.name=Temper", "-c",
       "user.email=temper@localhost", "-c", "commit.gpgsign=false", "-c", "gc.auto=0")
GIT_TIMEOUT = 120
WHERE = "project"
NOT_VISIBLE_NOTE = "folder checks run when the Pi lane starts the team"
NOT_GIT = ("the workspace is not a git repository: the team works on copies of its committed "
           "content")
NO_COMMIT = ("the workspace's git repository has no commit yet: the team works on copies of "
             "its committed content")
DIRTY = ("the workspace has uncommitted changes to tracked files; commit or stash them first: "
         "the team copies committed content only")
#: What git says when a repository's format is newer than it reads (an unknown
#: ``extensions.*`` or ``core.repositoryformatversion``).
_FORMAT_WORDS = ("repository extension", "repository format", "repositoryformatversion")


def format_problem(stderr: str) -> str | None:
    """The plain problem when git refused a repository for its format, else None."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    text = " ".join(lines)
    if not any(w in text.lower() for w in _FORMAT_WORDS):
        return None
    return ("the workspace's git repository uses a format this git can't read "
            f"({text[:200]}): the team works on copies of its committed content")


@dataclass(frozen=True)
class Root:
    """A listed project root: ``base`` itself, or (``children``) any folder directly in it."""

    text: str
    base: str
    children: bool

    def holds(self, path: str) -> bool:
        """Whether ``path`` is this root's folder, by text."""
        return os.path.dirname(path) == self.base if self.children else path == self.base


def roots_of(entries: Iterable[str]) -> list[Root]:
    """The roots as listed (``/a/b`` or ``/a/*``); entries were checked when loaded."""
    out = []
    for text in entries:
        children = text.endswith("/*")
        out.append(Root(text, text[:-2] if children else text, children))
    return out


def git_env(home: str | None = None) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "HOME": home or os.devnull, "LC_ALL": "C"}


def run_git(args: Sequence[str], cwd: str, *, timeout: int = GIT_TIMEOUT) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) of one hardened git command; -1 when it could not run."""
    try:
        done = subprocess.run([*GIT, *args], cwd=cwd, env=git_env(), capture_output=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", exc.__class__.__name__
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _p(text: str) -> str:
    return f"{WHERE}: {text}"


def lexical_problems(path: str, roots: Sequence[Root]) -> list[str]:
    """The checks that need no file access: the same answer on every machine."""
    if not isinstance(path, str) or not path.startswith("/"):
        return [_p("give the folder's full path (it starts with /)")]
    if any(ch.isspace() or not ch.isprintable() for ch in path):
        return [_p("the folder's path can't have spaces or control characters")]
    parts = path.split("/")
    if ".." in parts:
        return [_p("the path can't go up a folder ('..')")]
    norm = os.path.normpath(path)
    if not any(root.holds(norm) for root in roots):
        listed = ", ".join(r.text for r in roots) or "none are set"
        return [_p(f"{path} is outside the allowed project folders ({listed})")]
    return []


def _inside_any(real: str, bases: Sequence[str]) -> bool:
    return any(real == b or real.startswith(b.rstrip("/") + "/") for b in bases)


def real_problems(path: str, roots: Sequence[Root], *, fresh: bool = True,
                  start_commit: str | None = None) -> list[str]:
    """The checks on the folder itself, where it is visible (lexical checks passed).
    ``fresh`` is false when the team carries on with copies already made from it: the
    folder's own commits and uncommitted changes no longer matter then, but the commit the
    copies started from (``start_commit``, when known) must still be in it."""
    norm = os.path.normpath(path)
    real = os.path.realpath(norm)
    held = False
    for root in roots:
        base = os.path.realpath(root.base)
        if (os.path.dirname(real) == base) if root.children else (real == base):
            held = True
    if not held:
        return [_p(f"{path} leads outside the allowed project folders through a link")]
    code, out, err = run_git(["rev-parse", "--show-toplevel"], real)
    if code != 0:
        return [_p(format_problem(err) or NOT_GIT)]
    top = os.path.realpath(out.strip())
    if top != real:
        return [_p(f"{path} is inside a git repository but is not its top folder ({top})")]
    bases = [os.path.realpath(r.base) for r in roots]
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        code, out, _err = run_git(["rev-parse", flag], real)
        where = out.strip()
        if code != 0 or not where:
            return [_p(NOT_GIT)]
        git_dir = os.path.realpath(os.path.join(real, where))
        if not _inside_any(git_dir, bases):
            return [_p(f"its git folder {git_dir} is outside the allowed project folders")]
    if start_commit:
        code, _out, _err = run_git(["cat-file", "-e", f"{start_commit}^{{commit}}"], real)
        if code != 0:
            return [_p(f"the commit the team's copies started from ({start_commit[:12]}) is "
                       "no longer in the workspace's repository")]
    if not fresh:
        return []
    code, out, _err = run_git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], real)
    if code != 0 or not out.strip():
        return [_p(NO_COMMIT)]
    code, out, _err = run_git(["status", "--porcelain", "--untracked-files=no"], real)
    if code != 0:
        return [_p(NOT_GIT)]
    if out.strip():
        return [_p(DIRTY)]
    return []


def folder_check(path: str, roots: Sequence[Root], *, authoritative: bool,
                 fresh: bool = True,
                 start_commit: str | None = None) -> tuple[list[str], list[str]]:
    """(problems, notes) for a team's project folder.

    ``authoritative`` is the check where the Pi lane claims the run and where the team's
    node starts: a folder that can't be seen there is a problem. Elsewhere (the server) a
    folder whose root isn't visible gets the lexical check and :data:`NOT_VISIBLE_NOTE`; a
    visible one gets the real checks too. ``fresh`` and ``start_commit``: see
    :func:`real_problems`."""
    problems = lexical_problems(path, roots)
    if problems:
        return problems, []
    norm = os.path.normpath(path)
    root = next(r for r in roots if r.holds(norm))
    if not authoritative and not os.path.isdir(root.base):
        return [], [NOT_VISIBLE_NOTE]
    if not os.path.isdir(norm):
        return [_p(f"{path} isn't reachable inside Temper")], []
    return real_problems(path, roots, fresh=fresh, start_commit=start_commit), []
