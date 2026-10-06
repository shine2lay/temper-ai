"""The approved version as a local branch in the trial's source repo (M3 E10, M4 item 0d).

Trials only, once the team is done: ``team/<trial_id>`` at the approved review's commit,
create-only. Never forced, never pushed, never checked out: the source repo's working tree and
index are left alone, and only a folder inside the project roots is touched.

Two ways, one switch: when the box config names the host helper's socket
(``host_helper_socket``, M4 ADR-M4-02/12), the helper makes the branch -- one line per
connection, ``branch <repo> <leader git dir> <commit> <trial_id>``, answered ``made``,
``exists`` or ``denied <reason>``. Otherwise this process makes it with the hardened git of
the project copies (host-process instances and tests).

Either way the done record gets the same fields, ``{name, made, why}``: a branch already at
the commit counts as made; one that exists elsewhere is ``made: false, why: "exists"``; a
denial or any other failure leaves done as done, with the why.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Sequence

from temper_ai.pi_agent.team_folders import Root, folder_check, run_git

logger = logging.getLogger(__name__)

HELPER_TIMEOUT = 60
MAX_ANSWER = 4096


def branch_name(trial_id: str) -> str:
    return f"team/{trial_id}"


def _result(trial_id: str, made: bool, why: str | None) -> dict:
    return {"name": branch_name(trial_id), "made": made, "why": why}


def make_branch(*, source: str, leader_git_dir: str, commit: str, trial_id: str,
                roots: Sequence[Root], helper_socket: str = "") -> dict:
    """Make ``team/<trial_id>`` at ``commit`` in ``source``; never raises."""
    try:
        if helper_socket:
            return via_helper(helper_socket, source=source, leader_git_dir=leader_git_dir,
                              commit=commit, trial_id=trial_id)
        return in_process(source=source, leader_git_dir=leader_git_dir, commit=commit,
                          trial_id=trial_id, roots=roots)
    except Exception as exc:  # noqa: BLE001 - done stays done; the why says what happened
        logger.warning("trial %s: the branch could not be made", trial_id, exc_info=True)
        return _result(trial_id, False, f"the branch could not be made ({exc.__class__.__name__})")


def via_helper(path: str, *, source: str, leader_git_dir: str, commit: str,
               trial_id: str) -> dict:
    """Ask the host helper over its socket (one request line, one answer line)."""
    line = f"branch {source} {leader_git_dir} {commit} {trial_id}\n"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(HELPER_TIMEOUT)
    try:
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            return _result(trial_id, False, f"the host helper isn't running ({path})")
        sock.sendall(line.encode())
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        answer = b""
        while b"\n" not in answer and len(answer) < MAX_ANSWER:
            chunk = sock.recv(1024)
            if not chunk:
                break
            answer += chunk
    except TimeoutError:
        return _result(trial_id, False, "the host helper gave no answer")
    except OSError as exc:
        return _result(trial_id, False, f"the host helper could not be asked ({exc.__class__.__name__})")
    finally:
        sock.close()
    text = answer.decode("utf-8", "replace").split("\n", 1)[0].strip()
    if text == "made":
        return _result(trial_id, True, None)
    if text == "exists":
        return _result(trial_id, False, "exists")
    if text == "denied" or text.startswith("denied "):
        reason = text[len("denied"):].strip()
        return _result(trial_id, False, f"denied: {reason}" if reason else "denied")
    if not text:
        return _result(trial_id, False, "the host helper gave no answer")
    return _result(trial_id, False, f"the host helper answered '{text[:200]}'")


def in_process(*, source: str, leader_git_dir: str, commit: str, trial_id: str,
               roots: Sequence[Root]) -> dict:
    """Make the branch here: fetch the commit from the leader's copy into a temporary ref,
    create the branch only if it doesn't exist, drop the temporary ref."""
    problems, _notes = folder_check(source, roots, authoritative=True)
    if problems:
        return _result(trial_id, False, problems[0])
    ref = f"refs/heads/{branch_name(trial_id)}"
    tmp = f"refs/temper/branch-tmp/{trial_id}"

    def existing() -> str | None:
        code, out, _err = run_git(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], source)
        return out.strip() if code == 0 and out.strip() else None

    def settled(at: str) -> dict:
        return _result(trial_id, True, None) if at == commit else _result(trial_id, False, "exists")

    at = existing()
    if at:
        return settled(at)
    code, _out, err = run_git(["-c", "fetch.fsckObjects=true", "fetch", "-q", "--no-tags",
                               "--no-write-fetch-head", leader_git_dir, f"+{commit}:{tmp}"],
                              source)
    try:
        if code != 0:
            last = (err.strip().splitlines() or [""])[-1][:200]
            return _result(trial_id, False, f"git fetch failed: {last}")
        zero = "0" * len(commit)
        code, _out, err = run_git(["update-ref", ref, commit, zero], source)
        if code != 0:
            at = existing()
            if at:
                return settled(at)
            last = (err.strip().splitlines() or [""])[-1][:200]
            return _result(trial_id, False, f"git update-ref failed: {last}")
        return _result(trial_id, True, None)
    finally:
        run_git(["update-ref", "-d", tmp], source)
