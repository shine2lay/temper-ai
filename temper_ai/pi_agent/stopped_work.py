"""A cut turn's unsaved work, kept when a free-flowing team ends (H-STOP-2).

When a Stop or a cancel cuts a member's turn, what that turn changed is still only files in
the member's working folder: no commit holds them and the shared version never got them.
:func:`save_unsaved_work_to_stopped_branch` commits the folder as it is to the branch
``stopped/<turn_id>`` in that member's own copy (``<team root>/git/<member>.git``), and the
team's ``ended`` event lists it (``kept_work``), so the owner can find it.

It only adds a commit and a branch. A temporary index starts from the member's HEAD and takes
the working folder as it is: its ``.gitignore`` is respected, and a file over
:data:`MAX_FILE_BYTES` is left out and listed as skipped. The member's HEAD, branch and index,
and the team's shared version, are never touched.

The folder is the member's to write, so the save follows no link and is bounded. Sizes are
taken by a no-follow walk from the folder (:func:`member_tree.member_file_size`); a path with a
link (or a file) on the way is not given to git, which takes the change through the entry on
the way: the link itself is kept as a link, never followed. All of the
save fits the caller's seconds: the time is checked before every step and for every changed
path, and each git call runs in a session of its own whose whole process group (git and
anything it started) is killed when the call ends, runs out of time or writes more than
:data:`MAX_OUTPUT_BYTES`. More than :data:`MAX_PATHS` changed paths, or more than
:data:`MAX_TOTAL_BYTES` to keep, refuses the save. A save refused or failed changes nothing
but the copy's unreferenced objects, and its files stay in the folder.

Before any of its git runs over the folder, the save runs #110's check (M1, #112,
:func:`_wait_for_box_gone_then_check_folder`): it waits, within its seconds, until no box may
still write in the folder (the Stop is removing the cut turn's box), and a folder that holds
a .git of its own is not saved, so git never follows a .git the member planted.
"""

from __future__ import annotations

import contextlib
import os
import re
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from temper_ai.pi_agent.member_tree import (
    MemberLink,
    member_file_size,
    nested_git,
    quoted_member_path,
)
from temper_ai.pi_agent.team_folders import GIT

#: A file bigger than this (5 MiB) is left out of the kept commit and listed as skipped.
MAX_FILE_BYTES = 5 * 1024 * 1024
#: The most one save takes on: changed paths, bytes in the files it keeps, and bytes of output
#: from one git call (its status above all). Past any of them the save is refused.
MAX_PATHS = 20_000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
#: Seconds for one member's save, and for all the saves of one team end together: the end
#: stays well inside its minute.
MEMBER_SECONDS = 10.0
TOTAL_SECONDS = 30.0
#: Files, and skipped files, named in the record; the branch holds every kept one.
FILES_LISTED = 200
BRANCH_PREFIX = "stopped/"
#: How a changed file is named in the record (``git diff-tree --name-status`` letters).
CHANGES = {"A": "added", "M": "modified", "D": "deleted", "T": "type_changed"}
_TURN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
#: How long a killed git may take to be reaped before the save stops waiting for it.
_REAP_SECONDS = 1.0
_CHUNK = 1 << 16
#: How often the save asks again whether a box may still write in the member's folder.
WRITER_POLL_SECONDS = 0.25
#: How the writer check's answer (``LeaderTeam.writer_in_member_folder``) begins while a worker
#: box of the run may still write in the folder: the one answer the save waits out.
_BOX_LIVE = " while a box "
#: The planted .git entries a refusal names; past them it says "and more".
GIT_NAMED = 5
_T = TypeVar("_T")


class StoppedWorkError(Exception):
    """A cut turn's unsaved work could not be kept; its files stay where they are. ``commit``,
    when set, is a commit that holds the work although no branch names it."""

    def __init__(self, message: str, *, commit: str | None = None) -> None:
        super().__init__(message)
        self.commit = commit


def save_unsaved_work_to_stopped_branch(project: Any, member: str, pdir: Path, turn_id: str,
                                        *, reason: str, seconds: float) -> dict | None:
    """Commit ``member``'s working folder as it is, on top of its HEAD, to the new branch
    ``stopped/<turn_id>`` of its own copy (``project``: the team's ProjectCopies), all of it
    within ``seconds``. Returns the record entry, or None when nothing is unsaved and nothing
    was skipped. Raises StoppedWorkError (or the copy's CopyError for a working folder that is
    not a real folder); then nothing is changed but the copy's unreferenced objects."""
    if not _TURN_ID.fullmatch(turn_id or ""):
        raise StoppedWorkError(f"turn id {turn_id!r} cannot name a branch")
    deadline = time.monotonic() + seconds
    git_dir = project.git_dir(member)
    work_tree = project.checked_worktree(pdir)
    _wait_for_box_gone_then_check_folder(project, work_tree, git_dir, deadline)
    with tempfile.TemporaryDirectory(prefix="temper-stopped-") as tmp:
        def git(args: list[str], given: Path | None = None) -> bytes:
            return _git(args, git_dir=git_dir, work_tree=work_tree, home=Path(project.root),
                        index=Path(tmp) / "index", deadline=deadline, given=given)

        head = git(["rev-parse", "--verify", "-q", "HEAD^{commit}"]).decode().strip()
        git(["read-tree", head])
        paths = _changed_paths(git(["status", "--porcelain", "-z", "--untracked-files=all",
                                    "--no-renames"]))
        if len(paths) > MAX_PATHS:
            raise StoppedWorkError(f"{len(paths)} changed paths, more than {MAX_PATHS}: refused")
        keep: list[bytes] = []
        skipped: list[dict] = []
        total = 0
        for path in paths:
            _check_time(deadline, "while sizing the changed files")
            try:
                size = member_file_size(work_tree, os.fsdecode(path))
            except MemberLink:  # git refuses a path beyond a link; the link's own entry
                continue        # replaces it in the index
            if size is not None and size > MAX_FILE_BYTES:
                skipped.append({"path": _text(path), "bytes": size})
            else:
                keep.append(path)
                total += size or 0
        if total > MAX_TOTAL_BYTES:
            raise StoppedWorkError(f"the unsaved files hold {total} bytes, more than "
                                   f"{MAX_TOTAL_BYTES}: refused")
        if keep:
            listed = Path(tmp) / "paths"
            listed.write_bytes(b"\0".join(keep))
            git(["add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"], given=listed)
        tree = git(["write-tree"]).decode().strip()
        entry = {"member": member, "turn": turn_id, "branch": None, "commit": None,
                 "files": [], "files_total": 0, "skipped": skipped[:FILES_LISTED],
                 "skipped_total": len(skipped), "error": None}
        if tree == git(["rev-parse", f"{head}^{{tree}}"]).decode().strip():
            return entry if skipped else None
        # listed before the branch is made, so a branch that is made is always in the record
        files = _changes(git(["diff-tree", "-r", "-z", "--no-renames", "--name-status", head,
                              tree]))
        branch = BRANCH_PREFIX + turn_id
        message = (f"Temper: {member}'s unsaved work from turn {turn_id}, cut when the team "
                   f"ended ({reason})\n\nKept as it was in the member's working folder; the "
                   f"member's own branch and the team's shared version are unchanged.\n")
        commit = git(["commit-tree", tree, "-p", head, "-m", message]).decode().strip()
        try:
            # "" as the old value: the branch is made new, never moved (an existing one refuses).
            git(["update-ref", "-m", "Temper: a cut turn's unsaved work",
                 f"refs/heads/{branch}", commit, ""])
        except StoppedWorkError as exc:
            raise StoppedWorkError(f"its work is in commit {commit}, on no branch: {exc}",
                                   commit=commit) from None
    entry.update(branch=branch, commit=commit, files=files[:FILES_LISTED],
                 files_total=len(files))
    return entry


def not_kept_entry(member: str | None, turn_id: str, error: Any) -> dict:
    """The record entry of a cut turn whose unsaved work could not be kept (with the commit
    that holds it when the error names one, though no branch does)."""
    return {"member": member, "turn": turn_id, "branch": None,
            "commit": getattr(error, "commit", None), "files": [], "files_total": 0,
            "skipped": [], "skipped_total": 0,
            "error": str(error)[:500] or type(error).__name__}


def _wait_for_box_gone_then_check_folder(project: Any, work_tree: Path, git_dir: Path,
                                         deadline: float) -> None:
    """M1 at the Stop (#112): #110's check before the save's first git over ``work_tree``.

    First it waits, asking ``project.writer_check`` again every :data:`WRITER_POLL_SECONDS`,
    until no worker box of the run may still write in the folder: the Stop has recorded the
    cut turn ended and is removing its box. Anything else that may write (a turn of the member
    in flight, Docker that can't be asked, a folder that is no member's) refuses at once. Then
    the whole check, ``project.refuse_git_over_member_folder``: a folder that holds a .git of
    its own (or that the check refuses for another reason) is not saved, naming up to
    :data:`GIT_NAMED` of them. All of it within the deadline: a check still running then is
    left to end by its own caps (it only reads: docker ps, a walk of the folder, git on the
    copy's own git dir) and the save is refused. Raises StoppedWorkError."""
    while True:
        writer = _by_deadline(lambda: project.writer_check(work_tree), deadline,
                              "while asking whether its box is gone")
        if writer is None:
            break
        if not writer.startswith(_BOX_LIVE):
            raise StoppedWorkError(f"not saved: Temper won't run git over its folder{writer}")
        if deadline - time.monotonic() <= WRITER_POLL_SECONDS:
            raise StoppedWorkError("not saved: its box was still live (Temper won't run git "
                                   f"over its folder{writer})")
        time.sleep(WRITER_POLL_SECONDS)
    try:
        _by_deadline(lambda: project.refuse_git_over_member_folder(work_tree, git_dir,
                                                                    cwd=work_tree),
                     deadline, "while checking its folder for a .git of its own")
    except StoppedWorkError:
        raise
    except Exception as exc:  # MemberGitRefused, or the check could not run: no git over it
        try:
            planted = _by_deadline(lambda: nested_git(work_tree), deadline,
                                   "while naming the .git it holds")
        except Exception:   # GitCheckUnfinished, or out of time: the check's own words say why
            planted = []
        if not planted:
            raise StoppedWorkError(f"not saved: {exc}") from None
        named = ", ".join(quoted_member_path(p) for p in planted[:GIT_NAMED])
        if len(planted) > GIT_NAMED:
            named += " and more"   # the walk stops one past them
        raise StoppedWorkError(f"not saved: its folder holds a .git of its own ({named})") from None


def _by_deadline(call: Callable[[], _T], deadline: float, what: str) -> _T:
    """``call()`` on a thread of its own, waited for until the deadline; past it the save is
    out of time and the call is left to end by its own caps. Only for calls that change
    nothing. Raises what the call raised."""
    _check_time(deadline, what)
    got: dict[str, Any] = {}

    def run() -> None:
        try:
            got["value"] = call()
        except Exception as exc:
            got["error"] = exc

    worker = threading.Thread(target=run, name="pi-stopped-check", daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise StoppedWorkError(f"out of time {what}")
    if "error" in got:
        raise got["error"]
    if "value" not in got:
        raise StoppedWorkError(f"the check stopped without an answer {what}")
    return got["value"]


def _check_time(deadline: float, what: str) -> None:
    if time.monotonic() >= deadline:
        raise StoppedWorkError(f"out of time {what}")


def _git(args: list[str], *, git_dir: Path, work_tree: Path, home: Path, index: Path,
         deadline: float, given: Path | None = None) -> bytes:
    """One hardened git call on the member's copy, with the temporary index and literal
    pathspecs (``given``: a file for its input). Git runs in a session of its own, and its
    whole process group (git and anything it started) is killed when the call ends, the
    deadline passes or it writes more than MAX_OUTPUT_BYTES."""
    what = f"git {args[0]}"
    _check_time(deadline, f"before {what}")
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "HOME": str(home), "LC_ALL": "C",
           "GIT_INDEX_FILE": str(index), "GIT_LITERAL_PATHSPECS": "1"}
    cmd = [*GIT, f"--git-dir={git_dir}", f"--work-tree={work_tree}", *args]
    try:
        with open(given if given is not None else os.devnull, "rb") as stdin:
            proc = subprocess.Popen(cmd, cwd=str(work_tree), env=env, stdin=stdin,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
    except OSError as exc:
        raise StoppedWorkError(f"{what} could not run ({exc.__class__.__name__})") from None
    pipes = [p for p in (proc.stdout, proc.stderr) if p is not None]
    try:
        out, err = _read_until_closed([p.fileno() for p in pipes], deadline, what)
        _wait_until_exited(proc.pid, deadline, what)
    finally:
        # git's whole group (its session is its own); git, not yet reaped, still holds the id
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_REAP_SECONDS)
        for pipe in pipes:
            pipe.close()
    if proc.returncode != 0:
        lines = err.decode("utf-8", "replace").strip().splitlines()
        raise StoppedWorkError(f"{what} failed: {(lines[-1] if lines else '')[:200]}")
    return out


def _read_until_closed(fds: list[int], deadline: float, what: str) -> list[bytes]:
    """What a program writes on ``fds`` until it has closed them all, within the deadline and
    at most MAX_OUTPUT_BYTES in all (anything it started may hold them open: that counts)."""
    got: dict[int, list[bytes]] = {fd: [] for fd in fds}
    size = 0
    with selectors.DefaultSelector() as sel:
        for fd in fds:
            sel.register(fd, selectors.EVENT_READ)
        while sel.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                raise StoppedWorkError(f"{what} ran out of time")
            for key, _ in sel.select(left):
                data = os.read(key.fd, _CHUNK)
                if not data:
                    sel.unregister(key.fd)
                    continue
                size += len(data)
                if size > MAX_OUTPUT_BYTES:
                    raise StoppedWorkError(f"{what} wrote more than {MAX_OUTPUT_BYTES} bytes of "
                                           "output: refused")
                got[key.fd].append(data)
    return [b"".join(got[fd]) for fd in fds]


def _wait_until_exited(pid: int, deadline: float, what: str) -> None:
    """Wait, within the deadline, until the child ``pid`` has exited, without reaping it: until
    it is reaped its id still names its process group, so the group kill reaches only that."""
    pause = 0.001
    while True:
        try:
            if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is not None:
                return
        except ChildProcessError:  # reaped already
            return
        if time.monotonic() >= deadline:
            raise StoppedWorkError(f"{what} ran out of time")
        time.sleep(pause)
        pause = min(pause * 2, 0.05)


def _changed_paths(status: bytes) -> list[bytes]:
    """The paths of ``git status --porcelain -z --no-renames`` entries (``XY path``)."""
    return [entry[3:] for entry in status.split(b"\0") if len(entry) > 3]


def _changes(diff: bytes) -> list[dict]:
    """``git diff-tree -z --name-status`` output as ``[{path, change}]``, in git's order."""
    parts = diff.split(b"\0")
    out = []
    for letter, path in zip(parts[0::2], parts[1::2], strict=False):
        if path:
            code = letter.decode("ascii", "replace")[:1]
            out.append({"path": _text(path), "change": CHANGES.get(code, code)})
    return out


def _text(path: bytes) -> str:
    return path.decode("utf-8", "replace")
