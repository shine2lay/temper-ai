"""H-STOP-2: a Stop that cuts a member's turn keeps that turn's unsaved work.

The team's end commits each cut turn's working folder, as it is, to ``stopped/<turn_id>`` in
that member's own copy, and lists it on the ``ended`` event, the Team page's ``work`` and the
event feed (temper_ai/pi_agent/stopped_work.py, FlowTeam.end). A settled turn's leftovers are
not touched, and neither are a member's HEAD, branches and index or the team's shared version.

Model-free: turns are claimed by hand on the ledger, the box stop is a stand-in (no Docker),
and the member copies are real git repositories.

The save works on folders members wrote, so it is bounded (Architecture's land check of
#107, M2 and M3): it never follows a link on the way to a file, a git that stalls is killed
with everything it started, and past its caps (paths, bytes, output) the save is refused.

Before any of its git starts over a member's folder, the save runs #110's check (M1, #112):
it waits, within its seconds, until nothing may still write in the folder (the cut turn's box
is gone), and a folder that holds a .git of its own is not saved. Docker is a stand-in here
too (LeaderTeam.list_boxes).
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from temper_ai.pi_agent import flow_view, stopped_work
from temper_ai.pi_agent.box import BoxesUnknown
from temper_ai.pi_agent.ledger import events
from temper_ai.pi_agent.team_leader import LeaderTeam
from temper_ai.pi_agent.team_runtime import Team
from temper_ai.pi_agent.team_view import TeamReader
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

NAMES = ("lead", "builder")
FILES = {"app.py": "print('hello')\n", "notes.txt": "old notes\n", ".gitignore": "*.log\n"}
OTHERS = "--format=%(refname) %(objectname)"


def _team(led, box, run_id, tmp_path, files=FILES):
    for name in files:
        (tmp_path / "src" / name).parent.mkdir(parents=True, exist_ok=True)
    src = ls.project(tmp_path / "src", files)
    return ls.open_flow(led, box, run_id=run_id, source=src, names=NAMES)


def _claim(team, member: str) -> dict:
    """``member``'s turn, claimed as the flow loop claims it (a member at rest gets a
    message first)."""
    if member != team.leader:
        team.post(member, f"over to {member}", sender="temper", sender_kind="temper",
                  kind="info")
    claimed = team.ledger.claim_turn(team.run_id, ts.HOST, attempt_id="attempt-1", flow=True,
                                     only=member)
    assert claimed is not None, f"{member}'s turn could not be claimed"
    return claimed[0]


def _cut(team, member: str) -> dict:
    """A running turn with a box, as a Stop finds it."""
    turn = _claim(team, member)
    assert team.ledger.record_box(turn["turn_id"], turn["epoch"], f"pi-box-{member}")
    return turn


def _state(team, name: str) -> dict:
    """What a save must never change in a member's copy: HEAD, every branch but the new
    stopped/ ones, and the index."""
    refs = [r for r in ls.copy_git(team, name, "for-each-ref", OTHERS).splitlines()
            if not r.startswith("refs/heads/stopped/")]
    return {"head": ls.copy_git(team, name, "symbolic-ref", "HEAD"),
            "commit": ls.head(team, name), "refs": refs,
            "index": (team.project.git_dir(name) / "index").read_bytes()}


def _shared_refs(team, tmp_path) -> str:
    return ls.git(tmp_path, f"--git-dir={team.shared.path}", "for-each-ref", OTHERS)


def _stopped_branches(team, name: str) -> list[str]:
    return ls.copy_git(team, name, "for-each-ref", "--format=%(refname:short)",
                       "refs/heads/stopped/").split()


def _branch_files(team, name: str, branch: str) -> dict[str, str]:
    listed = ls.copy_git(team, name, "ls-tree", "-r", "-z", "--name-only", branch)
    return {p: ls.copy_git(team, name, "show", f"{branch}:{p}") for p in listed.split("\0") if p}


def _folder_files(folder, ignored: set[str]) -> dict[str, str]:
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_file() and rel not in ignored:
            out[rel] = p.read_text().strip()
    return out


def _ended(led, run_id) -> list[dict]:
    reader = TeamReader(led, run_id, ts.HOST, "lead")
    return [e["data"] for e in reader._rows(events, order=events.c.seq) if e["kind"] == "ended"]


def _page(led, run_id) -> tuple[list, list]:
    """What the Team page gets: the run reply's ``work.kept_work`` and the feed's ended
    events' ``kept_work``."""
    reader = TeamReader(led, run_id, ts.HOST, "lead")
    feed = flow_view.events_view(reader, 0, 1000)["events"]
    return (flow_view.FlowRead(reader, {}).work(None)["kept_work"],
            [e["kept_work"] for e in feed if e["kind"] == "ended"])


def test_a_stop_keeps_a_cut_turns_unsaved_work_on_a_stopped_branch(led, box, run_id, tmp_path,
                                                                   monkeypatch):
    team = _team(led, box, run_id, tmp_path)
    settled = _claim(team, "lead")
    assert ts.settle(led, settled) is not None
    (ls.workspace(team, "lead") / "draft.md").write_text("left after a settled turn\n")
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    (ws / "app.py").write_text("print('changed')\n")
    (ws / "notes.txt").unlink()
    (ws / "server.py").write_text("serve()\n")
    (ws / "README.md").write_text("# The server\n")
    (ws / "sub" / "dir").mkdir(parents=True)
    (ws / "sub" / "dir" / "new.txt").write_text("deep\n")
    (ws / "debug.log").write_text("ignored by the project's .gitignore\n")

    class LastWrite(ts.Stopper):
        """The box's last write lands before it is confirmed gone: the save comes after."""

        def __call__(self, name: str) -> dict:
            (ws / "late.txt").write_text("written as the box stopped\n")
            return super().__call__(name)

    stopper = LastWrite()
    monkeypatch.setattr(Team, "stop_box", stopper)
    before = {n: _state(team, n) for n in NAMES}
    shared_before = _shared_refs(team, tmp_path)

    out = team.end("run_cancelled")

    assert stopper.calls == ["pi-box-builder"]
    assert out["cancelled_turns"] == [cut["turn_id"]]
    branch = f"stopped/{cut['turn_id']}"
    assert _stopped_branches(team, "builder") == [branch]
    # exactly the working folder as the stop left it (ignored files aside), on top of HEAD
    assert _branch_files(team, "builder", branch) == _folder_files(ws, {"debug.log"})
    assert ls.copy_git(team, "builder", "rev-parse", f"{branch}^") == before["builder"]["commit"]
    kept = [{"member": "builder", "turn": cut["turn_id"], "branch": branch,
             "commit": ls.copy_git(team, "builder", "rev-parse", branch),
             "files": [{"path": "README.md", "change": "added"},
                       {"path": "app.py", "change": "modified"},
                       {"path": "late.txt", "change": "added"},
                       {"path": "notes.txt", "change": "deleted"},
                       {"path": "server.py", "change": "added"},
                       {"path": "sub/dir/new.txt", "change": "added"}],
             "files_total": 6, "skipped": [], "skipped_total": 0, "error": None}]
    assert out["kept_work"] == kept
    # nothing else moved: no member's HEAD, branches or index, nor the shared version; the
    # settled turn's leftovers stay as they are
    assert {n: _state(team, n) for n in NAMES} == before
    assert _shared_refs(team, tmp_path) == shared_before
    assert _stopped_branches(team, "lead") == []
    assert (ls.workspace(team, "lead") / "draft.md").read_text() == "left after a settled turn\n"
    assert (ws / "server.py").read_text() == "serve()\n"
    # the run's end record lists it, and so does what the Team page reads
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": kept}]
    assert _page(led, run_id) == (kept, [kept])


def test_with_nothing_unsaved_no_branch_is_made(led, box, run_id, tmp_path):
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    (ls.workspace(team, "builder") / "trace.log").write_text("only an ignored file changed\n")
    before = _state(team, "builder")

    out = team.end("run_cancelled")

    assert out["cancelled_turns"] == [cut["turn_id"]]
    assert out["kept_work"] == []
    assert _stopped_branches(team, "builder") == []
    assert _state(team, "builder") == before
    assert _ended(led, run_id) == [{"reason": "run_cancelled"}]
    assert _page(led, run_id) == ([], [[]])


def test_a_save_that_fails_is_recorded_and_the_team_still_ends(led, box, run_id, tmp_path,
                                                               caplog, monkeypatch):
    monkeypatch.setattr(Team, "stop_box", ts.Stopper())
    team = _team(led, box, run_id, tmp_path)
    lead_turn = _cut(team, "lead")
    builder_turn = _cut(team, "builder")
    (ls.workspace(team, "lead") / "plan.md").write_text("the plan\n")
    # the builder's working folder is now a link: Temper never follows one (SW-51)
    ws = ls.workspace(team, "builder")
    elsewhere = tmp_path / "elsewhere"
    ws.rename(elsewhere)
    ws.symlink_to(elsewhere, target_is_directory=True)

    with caplog.at_level(logging.WARNING, logger="temper_ai.pi_agent.team_flow"):
        out = team.end("run_cancelled")

    assert sorted(out["cancelled_turns"]) == sorted([lead_turn["turn_id"],
                                                     builder_turn["turn_id"]])
    by_member = {k["member"]: k for k in out["kept_work"]}
    assert by_member["lead"]["branch"] == f"stopped/{lead_turn['turn_id']}"
    assert by_member["lead"]["files"] == [{"path": "plan.md", "change": "added"}]
    assert by_member["lead"]["error"] is None
    failed = by_member["builder"]
    assert (failed["branch"], failed["commit"], failed["files"]) == (None, None, [])
    assert "a link" in failed["error"]
    assert "builder" in caplog.text and builder_turn["turn_id"] in caplog.text
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


def test_a_file_over_5_mib_is_left_out_and_listed(led, box, run_id, tmp_path):
    team = _team(led, box, run_id, tmp_path, {**FILES, "data.bin": "small\n"})
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    limit = stopped_work.MAX_FILE_BYTES
    (ws / "big.bin").write_bytes(b"x" * (limit + 1))
    (ws / "data.bin").write_bytes(b"y" * (limit + 1))
    (ws / "edge.bin").write_bytes(b"z" * limit)
    (ws / "small.txt").write_text("kept\n")

    out = team.end("run_cancelled")

    (kept,) = out["kept_work"]
    branch = f"stopped/{cut['turn_id']}"
    assert kept["branch"] == branch
    assert kept["files"] == [{"path": "edge.bin", "change": "added"},
                             {"path": "small.txt", "change": "added"}]
    assert sorted(kept["skipped"], key=lambda s: s["path"]) == [
        {"path": "big.bin", "bytes": limit + 1}, {"path": "data.bin", "bytes": limit + 1}]
    assert kept["skipped_total"] == 2
    files = ls.copy_git(team, "builder", "ls-tree", "-r", "--name-only", branch).split()
    assert "big.bin" not in files
    assert ls.copy_git(team, "builder", "show", f"{branch}:data.bin") == "small"


@pytest.mark.parametrize("cap", ["TOTAL_SECONDS", "MEMBER_SECONDS"])
def test_out_of_time_is_recorded_and_the_team_still_ends(led, box, run_id, tmp_path,
                                                         monkeypatch, cap):
    monkeypatch.setattr(stopped_work, cap, 0.0)
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    (ls.workspace(team, "builder") / "server.py").write_text("serve()\n")

    out = team.end("run_cancelled")

    (entry,) = out["kept_work"]
    assert (entry["member"], entry["turn"], entry["branch"]) == ("builder", cut["turn_id"], None)
    assert "time" in entry["error"]
    assert _stopped_branches(team, "builder") == []
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


# --- the save is bounded: links, stalls and caps (land check #107, M2 and M3) -------------------


def test_a_linked_folder_on_the_way_is_never_followed(led, box, run_id, tmp_path):
    team = _team(led, box, run_id, tmp_path,
                 {**FILES, "d/file": "tracked\n", "a/b/file": "tracked too\n"})
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    big = stopped_work.MAX_FILE_BYTES + 1
    for rel in ("d", "a/b"):
        # the folder on the way to a tracked file becomes a link to a folder outside, where a
        # file of the same name is too big to keep: its size would show if it were looked at
        outside = tmp_path / "outside" / rel
        outside.mkdir(parents=True)
        (outside / "file").write_bytes(b"o" * big)
        shutil.rmtree(ws / rel)
        (ws / rel).symlink_to(outside, target_is_directory=True)

    out = team.end("run_cancelled")

    (kept,) = out["kept_work"]
    branch = f"stopped/{cut['turn_id']}"
    assert (kept["branch"], kept["error"]) == (branch, None)
    # nothing outside the folder was looked at: no outside file is listed as skipped
    assert kept["skipped"] == []
    assert sorted(kept["files"], key=lambda f: f["path"]) == [
        {"path": "a/b", "change": "added"}, {"path": "a/b/file", "change": "deleted"},
        {"path": "d", "change": "added"}, {"path": "d/file", "change": "deleted"}]
    # the links are kept as links, as the folder has them, never as what they point to
    tree = ls.copy_git(team, "builder", "ls-tree", "-r", branch).splitlines()
    for rel in ("a/b", "d"):
        (line,) = [t for t in tree if t.endswith(f"\t{rel}")]
        assert line.startswith("120000 blob ")
        assert ls.copy_git(team, "builder", "show", f"{branch}:{rel}") == str(
            tmp_path / "outside" / rel)
    assert not [t for t in tree if t.endswith("/file")]


def test_the_record_names_the_first_files_and_skips_and_counts_them_all(led, box, run_id,
                                                                       tmp_path, monkeypatch):
    monkeypatch.setattr(stopped_work, "FILES_LISTED", 1)
    monkeypatch.setattr(stopped_work, "MAX_FILE_BYTES", 10)
    team = _team(led, box, run_id, tmp_path)
    _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    for name in ("a.bin", "b.bin"):
        (ws / name).write_bytes(b"x" * 11)
    for name in ("a.txt", "b.txt"):
        (ws / name).write_text("kept\n")

    (kept,) = team.end("run_cancelled")["kept_work"]

    assert (len(kept["files"]), kept["files_total"]) == (1, 2)
    assert (len(kept["skipped"]), kept["skipped_total"]) == (1, 2)
    # the branch holds every kept file, listed or not
    assert ls.copy_git(team, "builder", "ls-tree", "--name-only", kept["branch"]).split() == [
        ".gitignore", "a.txt", "app.py", "b.txt", "notes.txt"]


def test_an_existing_stopped_branch_is_never_moved_and_the_error_keeps_the_commit(
        led, box, run_id, tmp_path):
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    (ls.workspace(team, "builder") / "server.py").write_text("serve()\n")
    branch = f"stopped/{cut['turn_id']}"
    ls.copy_git(team, "builder", "branch", branch)  # already there, at the member's HEAD
    head = ls.head(team, "builder")

    out = team.end("run_cancelled")

    (entry,) = out["kept_work"]
    assert (entry["member"], entry["branch"], entry["files"]) == ("builder", None, [])
    assert "already exists" in entry["error"]
    # the work is in the commit the error names, though no branch names it; the branch stayed
    assert entry["commit"] and entry["commit"] in entry["error"]
    assert ls.copy_git(team, "builder", "show", f"{entry['commit']}:server.py") == "serve()"
    assert ls.copy_git(team, "builder", "rev-parse", branch) == head
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


def _gone(pid: int, wait: float = 3.0) -> bool:
    """True once ``pid`` has ended (gone, or dead and waiting for its parent to reap it)."""
    end = time.monotonic() + wait
    while True:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError, IndexError):
            return True
        if state in ("Z", "X"):
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.05)


@pytest.mark.parametrize("how", ["git_stalls", "git_exits_but_its_child_holds_the_output"])
def test_a_stalled_git_is_killed_with_its_children_and_the_team_still_ends(
        led, box, run_id, tmp_path, monkeypatch, how):
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    (ws / "server.py").write_text("serve()\n")
    # a git whose status (in the save only: its index is the save's own) starts a child that
    # keeps the output open, then stalls itself or exits
    pid_file, fake = tmp_path / "pids", tmp_path / "fakebin"
    fake.mkdir()
    then = "exec sleep 300" if how == "git_stalls" else "exit 0"
    (fake / "git").write_text(
        "#!/bin/sh\n"
        'case "$GIT_INDEX_FILE" in *temper-stopped-*)\n'
        '  for a in "$@"; do\n'
        '    if [ "$a" = status ]; then\n'
        f'      sleep 300 & echo "$$ $!" > {pid_file}\n'
        f"      {then}\n"
        "    fi\n"
        "  done;;\n"
        "esac\n"
        f'exec {shutil.which("git")} "$@"\n')
    (fake / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(stopped_work, "MEMBER_SECONDS", 1.0)
    took: list[float] = []
    save = stopped_work.save_unsaved_work_to_stopped_branch

    def timed_save(*args, **kwargs):
        started = time.monotonic()
        try:
            return save(*args, **kwargs)
        finally:
            took.append(time.monotonic() - started)

    monkeypatch.setattr(stopped_work, "save_unsaved_work_to_stopped_branch", timed_save)

    out = team.end("run_cancelled")

    pids = [int(p) for p in pid_file.read_text().split()]
    try:
        assert len(pids) == 2
        # the git and its child are both gone, not left running after the save
        assert [p for p in pids if not _gone(p)] == []
    finally:
        for p in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(p, signal.SIGKILL)
    # the save, the killing included, ends within its seconds (and a little for the kill)
    assert len(took) == 1 and took[0] < stopped_work.MEMBER_SECONDS + 1.0
    (entry,) = out["kept_work"]
    assert (entry["member"], entry["turn"], entry["branch"]) == ("builder", cut["turn_id"], None)
    assert "time" in entry["error"]
    assert _stopped_branches(team, "builder") == []
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


@pytest.mark.parametrize(("cap", "value", "says"), [
    ("MAX_PATHS", 3, "4 changed paths"),
    ("MAX_TOTAL_BYTES", 1000, "1600 bytes"),
    ("MAX_OUTPUT_BYTES", 64, "more than 64 bytes of output"),
])
def test_too_much_unsaved_work_is_refused_and_the_team_still_ends(led, box, run_id, tmp_path,
                                                                  monkeypatch, cap, value, says):
    monkeypatch.setattr(stopped_work, cap, value)
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    parts = [ws / f"part-{i}-with-a-longer-name.txt" for i in range(4)]
    for part in parts:
        part.write_bytes(b"p" * 400)
    before = _state(team, "builder")

    out = team.end("run_cancelled")

    (entry,) = out["kept_work"]
    assert (entry["member"], entry["turn"], entry["branch"]) == ("builder", cut["turn_id"], None)
    assert says in entry["error"]
    assert _stopped_branches(team, "builder") == []
    assert _state(team, "builder") == before
    assert all(p.read_bytes() == b"p" * 400 for p in parts)  # the files stay in the folder
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


# --- M1 at the Stop save: #110's check before any of the save's git (#112) ---------------------

#: The git a save with work to keep runs over the member's folder (#107), in order.
SAVE_GIT = ["rev-parse", "read-tree", "status", "add", "write-tree", "rev-parse", "diff-tree",
            "commit-tree", "update-ref"]


def _sub(cmd: list[str]) -> str:
    """The git subcommand of a hardened git command line (past its -c and -- options)."""
    rest = cmd[1:]
    while rest:
        if rest[0] == "-c":
            rest = rest[2:]
        elif rest[0].startswith("--"):
            rest = rest[1:]
        else:
            return rest[0]
    return ""


def _inside(path: str, folder: Path) -> bool:
    p = Path(os.path.abspath(path))
    return p == folder or folder in p.parents


class GitStarts:
    """Every git process started while it is on (the save's own Popen, and subprocess.run's):
    its subcommand and the folders it was given, as work tree or working folder. ``log``, when
    given, gets ``("git", subcommand, folders)`` as each starts."""

    def __init__(self, monkeypatch, log: list | None = None):
        self.calls: list[tuple[str, list[str]]] = []
        self.log = log if log is not None else []
        real = subprocess.Popen

        def spy(cmd, *args, **kw):
            if isinstance(cmd, list | tuple) and cmd and cmd[0] == "git":
                words = [str(c) for c in cmd]
                folders = [w.split("=", 1)[1] for w in words if w.startswith("--work-tree=")]
                if kw.get("cwd"):
                    folders.append(str(kw["cwd"]))
                self.calls.append((_sub(words), folders))
                self.log.append(("git", _sub(words), folders))
            return real(cmd, *args, **kw)

        monkeypatch.setattr(subprocess, "Popen", spy)

    def over(self, folder: Path) -> list[str]:
        """The subcommands of the git processes started over ``folder``: given it (or a folder
        in it) as the work tree, or run in it."""
        return [sub for sub, folders in self.calls if any(_inside(f, folder) for f in folders)]


class Docker:
    """``docker ps`` for the run's worker boxes, as a test scripts it (LeaderTeam.list_boxes,
    which #110's check asks): each call takes the next answer, and the last one again once they
    run out; an answer that is an exception is raised. ``hold``: no answer until it is set.
    Each answer is logged as ``("docker", "live" | "gone" | "error")``."""

    def __init__(self, monkeypatch, answers: list, log: list | None = None, *,
                 hold: threading.Event | None = None):
        self.answers = answers
        self.calls = 0
        self.log = log if log is not None else []
        self.hold = hold
        monkeypatch.setattr(LeaderTeam, "list_boxes", staticmethod(self))

    def __call__(self, run_id: str) -> list[dict]:
        if self.hold is not None:
            self.hold.wait(30)
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if isinstance(answer, Exception):
            self.log.append(("docker", "error"))
            raise answer
        live = [b for b in answer if b["state"] not in ("exited", "dead")]
        self.log.append(("docker", "live" if live else "gone"))
        return answer


def _timed_saves(monkeypatch) -> list[float]:
    """How long each member's save takes, in the order they run."""
    took: list[float] = []
    save = stopped_work.save_unsaved_work_to_stopped_branch

    def timed_save(*args, **kwargs):
        started = time.monotonic()
        try:
            return save(*args, **kwargs)
        finally:
            took.append(time.monotonic() - started)

    monkeypatch.setattr(stopped_work, "save_unsaved_work_to_stopped_branch", timed_save)
    return took


def test_a_folder_holding_a_git_of_its_own_is_not_saved_and_git_never_starts_over_it(
        led, box, run_id, tmp_path, monkeypatch):
    """M1 at the Stop save (#112): the builder's folder holds ``sub/.git``, a ``gitdir:`` file
    naming a repository outside it, which git would follow. #110's check refuses the save
    before any git starts over the folder, the entry says why, and the member's files stay as
    they are. The lead, with no .git of its own, is saved as before."""
    team = _team(led, box, run_id, tmp_path)
    lead_turn = _cut(team, "lead")
    cut = _cut(team, "builder")
    lead_ws, ws = ls.workspace(team, "lead"), ls.workspace(team, "builder")
    (lead_ws / "plan.md").write_text("the plan\n")
    (ws / "server.py").write_text("serve()\n")
    outside = ls.project(tmp_path / "outside", {"secret.txt": "another repository's file\n"})
    planted = f"gitdir: {outside / '.git'}\n"
    (ws / "sub").mkdir()
    (ws / "sub" / "index.js").write_text("console.log('scaffolded')\n")
    (ws / "sub" / ".git").write_text(planted)
    before = _state(team, "builder")
    outside_refs = ls.git(outside, "for-each-ref", OTHERS)
    git = GitStarts(monkeypatch)

    out = team.end("run_cancelled")

    started = {"lead": git.over(lead_ws), "builder": git.over(ws)}
    by_member = {k["member"]: k for k in out["kept_work"]}
    assert by_member["builder"] == {
        "member": "builder", "turn": cut["turn_id"], "branch": None, "commit": None,
        "files": [], "files_total": 0, "skipped": [], "skipped_total": 0,
        "error": 'not saved: its folder holds a .git of its own ("sub/.git")'}
    assert started["builder"] == []        # no git ever started over the folder
    assert _stopped_branches(team, "builder") == []
    assert _state(team, "builder") == before
    # Temper never deletes, moves or edits a member's files; the outside repository is as it was
    assert (ws / "sub" / ".git").read_text() == planted
    assert (ws / "server.py").read_text() == "serve()\n"
    assert ls.git(outside, "for-each-ref", OTHERS) == outside_refs
    # the lead is saved as before, by the same git
    assert started["lead"] == SAVE_GIT
    lead = by_member["lead"]
    assert (lead["branch"], lead["files"], lead["error"]) == (
        f"stopped/{lead_turn['turn_id']}", [{"path": "plan.md", "change": "added"}], None)
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


@pytest.mark.parametrize("docker", ["box_live", "docker_fails", "docker_hangs"])
def test_while_something_may_still_write_in_the_folder_it_is_not_saved_and_git_never_starts(
        led, box, run_id, tmp_path, monkeypatch, docker):
    """M1 at the Stop save (#112; Security's B1 at Stop): the save waits, within its seconds,
    until nothing is left that may write in the member's folder. Here the builder's box is
    still live past them (Docker lists it running), Docker can't be asked, or docker ps does not
    answer in time: then the work is not saved, the entry says why, git never starts over the
    folder, and the save keeps to its seconds (M3). A member whose box is gone is saved."""
    monkeypatch.setattr(stopped_work, "MEMBER_SECONDS", 1.0)
    team = _team(led, box, run_id, tmp_path)
    lead_turn = _cut(team, "lead")
    cut = _cut(team, "builder")
    lead_ws, ws = ls.workspace(team, "lead"), ls.workspace(team, "builder")
    (lead_ws / "plan.md").write_text("the plan\n")
    (ws / "server.py").write_text("serve()\n")
    hold = threading.Event()
    answers = {"box_live": [[{"name": "pi-box-builder", "state": "running",
                              "turn": cut["turn_id"][:16]}]],
               "docker_fails": [BoxesUnknown("docker ps took too long")],
               "docker_hangs": [[]]}[docker]
    Docker(monkeypatch, answers, hold=hold if docker == "docker_hangs" else None)
    git = GitStarts(monkeypatch)
    took = _timed_saves(monkeypatch)

    try:
        out = team.end("run_cancelled")
    finally:
        hold.set()      # a docker ps left waiting answers, and its thread ends

    started = {"lead": git.over(lead_ws), "builder": git.over(ws)}
    by_member = {k["member"]: k for k in out["kept_work"]}
    says = {"box_live": "not saved: its box was still live (Temper won't run git over its folder "
                        "while a box of yours is still live: pi-box-builder (running))",
            "docker_fails": "not saved: Temper won't run git over its folder: it can't ask "
                            "Docker which boxes are live (docker ps took too long)",
            "docker_hangs": "out of time while asking whether its box is gone"}[docker]
    refused = ["builder"] if docker == "box_live" else ["lead", "builder"]
    for name in refused:
        entry = by_member[name]
        assert (entry["branch"], entry["commit"], entry["files"], entry["error"]) == (
            None, None, [], says), name
        assert started[name] == [], name    # no git ever started over the folder
        assert _stopped_branches(team, name) == []
    if docker == "box_live":
        lead = by_member["lead"]
        assert (lead["branch"], lead["error"]) == (f"stopped/{lead_turn['turn_id']}", None)
        assert started["lead"] == SAVE_GIT
    # each save kept to its seconds, the wait and a docker ps that never answered included
    assert len(took) == 2 and max(took) < stopped_work.MEMBER_SECONDS + 1.0
    assert (ws / "server.py").read_text() == "serve()\n"
    assert {p["state"] for p in led.participants_of(run_id, ts.HOST)} == {"ended"}
    assert _ended(led, run_id) == [{"reason": "run_cancelled", "kept_work": out["kept_work"]}]


def test_the_save_waits_for_the_cut_turns_box_to_be_gone_then_keeps_its_work_as_before(
        led, box, run_id, tmp_path, monkeypatch):
    """At Stop the cut turn is the one saved (#112): the stop has recorded it ended and its box
    is being removed. Docker still lists the box (running, then removing) for two answers, then
    exited, then not at all: the save waits, git starts over the folder only after Docker last
    listed the box live, and the work is kept as #107 keeps it."""
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    (ws / "server.py").write_text("serve()\n")
    (ws / "app.py").write_text("print('changed')\n")
    log: list = []
    label = cut["turn_id"][:16]
    Docker(monkeypatch, [[{"name": "pi-box-builder", "state": s, "turn": label}]
                         for s in ("running", "removing", "exited")] + [[]], log)
    git = GitStarts(monkeypatch, log)

    out = team.end("run_cancelled")

    started = git.over(ws)
    lives = [i for i, e in enumerate(log) if e == ("docker", "live")]
    gits = [i for i, e in enumerate(log) if e[0] == "git" and any(_inside(f, ws) for f in e[2])]
    # git started over the folder only after Docker last listed the box live
    assert len(lives) == 2 and gits and min(gits) > max(lives)
    assert started == SAVE_GIT
    branch = f"stopped/{cut['turn_id']}"
    (kept,) = out["kept_work"]
    assert (kept["branch"], kept["error"]) == (branch, None)
    assert kept["files"] == [{"path": "app.py", "change": "modified"},
                             {"path": "server.py", "change": "added"}]
    assert _branch_files(team, "builder", branch) == _folder_files(ws, set())


def test_a_clean_members_save_runs_the_same_git_and_keeps_the_same_work(led, box, run_id,
                                                                       tmp_path, monkeypatch):
    """The control (#112): no .git of its own and no box live. #110's check lets the save run
    exactly the git #107's save runs over the folder, and keep exactly the same work."""
    team = _team(led, box, run_id, tmp_path)
    cut = _cut(team, "builder")
    ws = ls.workspace(team, "builder")
    (ws / "server.py").write_text("serve()\n")
    (ws / "app.py").write_text("print('changed')\n")
    git = GitStarts(monkeypatch)

    out = team.end("run_cancelled")

    started = git.over(ws)
    branch = f"stopped/{cut['turn_id']}"
    assert started == SAVE_GIT
    assert out["kept_work"] == [{
        "member": "builder", "turn": cut["turn_id"], "branch": branch,
        "commit": ls.copy_git(team, "builder", "rev-parse", branch),
        "files": [{"path": "app.py", "change": "modified"},
                  {"path": "server.py", "change": "added"}],
        "files_total": 2, "skipped": [], "skipped_total": 0, "error": None}]
    assert _branch_files(team, "builder", branch) == _folder_files(ws, set())
