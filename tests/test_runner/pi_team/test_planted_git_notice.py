"""A refusal the member can fix is told, not a dead end (task #115, #110's S1).

Since #110 (M1), Temper won't run git over a member's folder that holds a .git of its own,
more entries or deeper folders than its check looks at, or a folder it can't read. Before
#115 that refusal ended the whole Project at a share, and at the sync before a turn it kept
the turn from starting, so the member never got a turn in which to fix it. Now the member is
told why and what it can do: at a share by the refused share's notice, at a sync in the
framing of a turn that starts without the merge. After refusals in 2 turns in a row it rests
until a message wakes it, and Temper asks once: the leader, or the owner when the member is
the leader. A writer that may still be live, git set up wrong and a stray gitlink behave as
after #110, and so does a refusal that comes once git has written into the folder in the
same call (a conflicting merge's finish, a share's merge again after a lost race).

Model-free: every member is a scripted Pi, and git runs in tmp folders. ``subprocess.run``
is spied on to show that no git process starts over a folder while its .git is there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from temper_ai.pi_agent import flow_view, member_tree, team_flow
from temper_ai.pi_agent.ledger import participants
from temper_ai.pi_agent.shared_version import (
    NO_MARKERS,
    Conflict,
    SharedVersion,
    VersionError,
)
from temper_ai.pi_agent.team_flow import FlowTeam, flow_framing
from temper_ai.pi_agent.team_leader import (
    FolderWriter,
    MemberGitRefused,
    ProjectCopies,
    TeamFailure,
)
from temper_ai.pi_agent.team_view import TeamReader
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

NAMES = ("lead", "builder")
SETTINGS = {**ls.FLOW_SETTINGS, "max_parallel": 1}
NO_GIT = ("Don't create a git repository inside your folder (git init, git clone, or a "
          "scaffolder that runs git init: use its no-git option). Temper won't share your "
          "work while your folder holds a .git of its own.")
#: What M1 says, cause by cause, about the folders :func:`_make` gives each cause.
REFUSED = {
    "planted": ("Temper won't run git over your folder while it holds a .git of its own: "
                '"sub/.git". Remove them and try again.'),
    "entries": ("Temper won't run git over your folder: it holds more than 5 entries, the "
                "most Temper checks for a .git of its own."),
    "depth": ("Temper won't run git over your folder: it nests folders deeper than 2, the "
              "most Temper checks for a .git of its own."),
    "unreadable": ("Temper won't run git over your folder: it can't read \"shut\" (EACCES) "
                   "to check it for a .git of its own."),
    "writer": ("Temper won't run git over your folder while a box of yours is still live: "
               "temper-pi-x (running)."),
    "stall": ("Temper won't run git over your folder: checking it for a .git of its own "
              "took longer than 0 seconds."),
    "setup": ("Temper won't run git over your folder unless git is told the copy's own git "
              "dir, outside the folder, and runs from the folder's top."),
    "gitlink": ("Temper won't run git over your folder while your copy holds a gitlink the "
                "Project didn't start with: \"vendor/lib\". It has to be removed from the "
                "copy's index on the host first."),
}
#: What the member can do about each cause it can fix.
FIXES = {
    "planted": ("Don't create a new one: no git init or git clone in your folder, and give a "
                "scaffolder its no-git option."),
    "entries": ("Remove generated folders you can make again, such as node_modules, .venv or "
                "build output, and try again."),
    "depth": "Remove or flatten the deepest folders, and try again.",
    "unreadable": ("Fix that folder's permissions so Temper can list and read it, or remove "
                   "it, and try again."),
}
WRITER = FolderWriter("box_live", " while a box of yours is still live: temper-pi-x (running)")
#: What the resting leader gets when the owner answers its refusals with no words (#119, S5).
NO_WORDS = "The owner answered with no words: you get another turn."
NOT_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root opens any folder")
FIXABLE = ("planted", "entries", "depth", pytest.param("unreadable", marks=NOT_ROOT))
#: What the member reads at a refused share: what to do, or that there's nothing to fix.
SHARE_TOLD = {
    **{c: f"Not shared: {REFUSED[c]} {FIXES[c]}" for c in FIXES},
    "writer": (f"Not shared: {REFUSED['writer']} Temper couldn't yet confirm that nothing "
               "else writes in your folder, so there's nothing for you to fix: share again "
               "later."),
    "stall": (f"Not shared: {REFUSED['stall']} There's nothing for you to fix: share again "
              "later."),
}
#: A conflict recorded for the member before its sync; a refused sync keeps it.
KEPT = Conflict("app.py", NO_MARKERS, "you and builder both changed it", True)
_REAL_RUN = subprocess.run  # the member's own git: the spy below doesn't see it


def _told(cause: str) -> str:
    return f"{REFUSED[cause]} {FIXES[cause]}"


def _sync_told(cause: str) -> str:
    return ("[Temper] Temper didn't bring the team's shared version into your copy this turn. "
            f"{_told(cause)} Until it's fixed, your copy misses the others' latest shared "
            "work, and your shares are refused.")


def _resting(member: str, told: str) -> str:
    return (f"{member} is resting: Temper refused to run git over its folder in 2 turns in a "
            f"row, so its work can't reach the team's shared version. What Temper told "
            f"{member}: \"{told}\" Send {member} a message to give it another try, or carry "
            "on without its work.")


class GitSpy:
    """Every git process Temper starts while it is on: its command line and its folder."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.calls: list[tuple[list[str], str]] = []

        def spy(cmd, *args, **kw):
            if isinstance(cmd, list | tuple) and cmd and cmd[0] == "git":
                self.calls.append(([str(c) for c in cmd], str(kw.get("cwd") or "")))
            return _REAL_RUN(cmd, *args, **kw)

        monkeypatch.setattr(subprocess, "run", spy)

    def over(self, folder: Path, start: int = 0, end: int | None = None) -> list[list[str]]:
        """The git processes among ``calls[start:end]`` started over ``folder``: given it
        (or a folder in it) as the work tree, or run in it."""
        def inside(text: str) -> bool:
            path = Path(text)
            return path == folder or folder in path.parents

        return [cmd for cmd, cwd in self.calls[start:end]
                if any(inside(c.split("=", 1)[1]) for c in cmd if c.startswith("--work-tree="))
                or (cwd and inside(cwd))]


def _plant(ws: Path) -> None:
    """A repository made in the member's folder, as git init or a scaffolder makes one."""
    (ws / "sub").mkdir(exist_ok=True)
    (ws / "sub" / "index.js").write_text("console.log('scaffolded')\n")
    _REAL_RUN(["git", "init", "-q", "-b", "main", str(ws / "sub")], check=True,
              capture_output=True, env={**os.environ, **ls.GIT_ENV})


def _remove_git(ws: Path) -> None:
    shutil.rmtree(ws / "sub" / ".git")


PLANT = {"call": lambda box, _message: _plant(Path(box.pdir) / "workspace")}
REMOVE = {"call": lambda box, _message: _remove_git(Path(box.pdir) / "workspace")}


def _make(cause: str, team: FlowTeam, name: str,
          monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Make ``cause`` true of ``name``'s folder; returns how to put it right."""
    ws = ls.workspace(team, name)
    if cause == "planted":
        _plant(ws)
        return lambda: _remove_git(ws)
    if cause in ("entries", "depth", "stall"):
        if cause == "entries":
            for i in range(6):
                (ws / f"f{i}.txt").write_text("x\n")
        if cause == "depth":
            (ws / "a" / "b" / "c").mkdir(parents=True)
            (ws / "a" / "b" / "c" / "deep.txt").write_text("x\n")
        cap, value = {"entries": ("GIT_CHECK_ENTRIES", 5), "depth": ("GIT_CHECK_DEPTH", 2),
                      "stall": ("GIT_CHECK_SECONDS", 0.0)}[cause]
        old = getattr(member_tree, cap)
        monkeypatch.setattr(member_tree, cap, value)
        return lambda: monkeypatch.setattr(member_tree, cap, old)
    if cause == "unreadable":
        shut = ws / "shut"
        (shut / "inner").mkdir(parents=True)
        shut.chmod(0)
        return lambda: shut.chmod(0o755)
    if cause == "writer":
        live = team.project.writer_check
        monkeypatch.setattr(team.project, "writer_check",
                            lambda folder: WRITER if Path(folder) == ws else live(folder))
        return lambda: monkeypatch.setattr(team.project, "writer_check", live)
    if cause == "setup":  # git would be left to find the repository itself
        guard = team.project.refuse_git_over_member_folder

        def no_git_dir(work_tree: Path, git_dir: Path | None, **kw: Any) -> None:
            return guard(work_tree, None if Path(work_tree) == ws else git_dir, **kw)

        monkeypatch.setattr(team.project, "refuse_git_over_member_folder", no_git_dir)
        return lambda: monkeypatch.setattr(team.project, "refuse_git_over_member_folder", guard)
    assert cause == "gitlink"
    ls.copy_git(team, name, "update-index", "--add", "--cacheinfo",
                f"160000,{ls.head(team, name)},vendor/lib")
    return lambda: ls.copy_git(team, name, "update-index", "--force-remove", "vendor/lib")


def _notices(led: Any, run_id: str, member: str) -> list[str]:
    """Temper's notices to ``member``, in order."""
    msgs = sorted(ts.rows(led, run_id)["messages"], key=lambda m: m["seq"])
    return [m["body"] for m in msgs if m["to_member"] == member
            and m["sender_kind"] == "temper" and m["kind"] == "notice"]


def _owner_replies(led: Any, run_id: str, member: str) -> list[str]:
    """The owner's answers delivered to ``member``, in order."""
    msgs = sorted(ts.rows(led, run_id)["messages"], key=lambda m: m["seq"])
    return [m["body"] for m in msgs if m["to_member"] == member and m["kind"] == "owner_reply"]


def _events(led: Any, run_id: str, *kinds: str) -> list[dict]:
    return [e for e in ts.team_events(led, run_id) if e["kind"] in kinds]


def _turn_ids(led: Any, run_id: str, member: str) -> list[str]:
    snap = ts.rows(led, run_id)
    pid = next(p["participant_id"] for p in snap["participants"] if p["member"] == member)
    return [t["turn_id"] for t in sorted(
        (t for t in snap["turns"] if t["participant_id"] == pid and t["state"] == "completed"),
        key=lambda t: t["turn_no"])]


def _lead(on_resting: list[dict] | None = None) -> ls.Turns:
    """The leader asks the builder for its part and says done once the builder wrote back;
    told that the builder rests, it plays ``on_resting``."""
    def play() -> list[dict]:
        prompts = ts.PROMPTS["lead"]
        if len(prompts) == 1:
            return [ts.send("builder", "Write part.md, then share.", "work_request"),
                    ls.op("idle", note="waiting for the part")]
        if on_resting is not None and "builder is resting" in prompts[-1]:
            return on_resting
        if any(h["from"] == 'member "builder"' for h in ts.headers(prompts[-1])):
            return [ls.op("done", summary="The part is in the shared version.")]
        return [ls.op("idle", note="waiting for the part")]
    return ls.Turns(play)


def _open(led: Any, box: Any, run_id: str, tmp_path: Path) -> FlowTeam:
    return ls.open_flow(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"),
                        names=NAMES, settings=SETTINGS)


# --- the whole feature --------------------------------------------------------------------------


def test_a_member_told_of_its_planted_git_removes_it_shares_and_the_run_ends_done(
        led, box, run_id, tmp_path, monkeypatch):
    spy = GitSpy(monkeypatch)
    marks: dict[str, int] = {}

    def plant(box_: Any, message: str) -> None:
        PLANT["call"](box_, message)
        marks["planted"] = len(spy.calls)

    def remove(box_: Any, message: str) -> None:
        marks["removed"] = len(spy.calls)
        REMOVE["call"](box_, message)

    ts.SCRIPTS["lead"] = _lead()
    ts.SCRIPTS["builder"] = [
        [ls.write("part.md", "# part\n"), {"call": plant}, ls.op("share", note="part"),
         ls.op("idle")],
        [{"call": remove}, ls.op("share", note="part, without the .git"),
         ts.send("lead", "part shared", "info"), ls.op("idle")],
    ]
    team = _open(led, box, run_id, tmp_path)
    ws = ls.workspace(team, "builder")

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    # Told why at the refused share, and again as its next turn starts without the merge.
    assert _notices(led, run_id, "builder") == [SHARE_TOLD["planted"]]
    first, second = ts.PROMPTS["builder"]
    assert "Temper didn't bring" not in first
    assert SHARE_TOLD["planted"] in second and _sync_told("planted") in second
    one, two = _turn_ids(led, run_id, "builder")
    seen = [(e["kind"], e["data"].get("cause"), e["data"].get("turn_id"))
            for e in _events(led, run_id, "share_refused", "sync_refused", "share")
            if e["member"] == "builder"]
    assert seen == [("share_refused", "planted", one), ("sync_refused", "planted", two),
                    ("share", None, None)]
    # No git ran over its folder while the .git was there; its share after it went through.
    assert spy.over(ws, marks["planted"], marks["removed"]) == []
    assert spy.over(ws, marks["removed"])
    files = ls.git(team.shared.path, "ls-tree", "-r", "--name-only",
                   outcome.record["version"]["commit"]).split()
    assert {"part.md", "sub/index.js"} <= set(files) and not [f for f in files if ".git/" in f]
    # Fixed at once: it never rested, and nobody was asked about it.
    assert not [n for n in _notices(led, run_id, "lead") if "is resting" in n]
    assert not [e for e in _events(led, run_id, "idle") if e["data"].get("reason") == "refused"]
    # Every turn's framing asks for no git repository in the folder.
    assert all(NO_GIT in p for p in ts.PROMPTS["lead"] + ts.PROMPTS["builder"])
    # The Team page shows both refusals with their cause.
    feed = flow_view.events_view(TeamReader(led, run_id, ts.HOST, "lead"), 0, 1000)["events"]
    shown = {e["kind"]: e for e in feed if e["kind"] in ("share_refused", "sync_refused")}
    assert shown["share_refused"]["cause"] == "planted"
    assert shown["sync_refused"]["cause"] == "planted"
    assert shown["sync_refused"]["reason"]


# --- a share, cause by cause --------------------------------------------------------------------


@pytest.mark.parametrize("cause", [*FIXABLE, "writer", "stall"])
def test_a_refused_share_tells_the_member_why_and_the_run_carries_on(
        led, box, run_id, tmp_path, monkeypatch, cause):
    team = _open(led, box, run_id, tmp_path)
    ws = ls.workspace(team, "builder")
    (ws / "part.md").write_text("# part\n")
    put_right = _make(cause, team, "builder", monkeypatch)
    spy = GitSpy(monkeypatch)
    try:
        got = team._share("builder", "act-1", None)
    finally:
        put_right()

    assert got == {"status": "refused", "text": SHARE_TOLD[cause], "cause": cause}
    assert spy.over(ws) == []  # refused before any git ran over the folder
    assert _notices(led, run_id, "builder") == [SHARE_TOLD[cause]]
    refused = _events(led, run_id, "share_refused")
    assert [(e["member"], e["data"]) for e in refused] == [("builder", {
        "act_id": "act-1", "status": "refused", "paths": [], "cause": cause,
        "reason": SHARE_TOLD[cause], "turn_id": None})]
    with led.engine.connect() as conn:
        streak = team._refusal_streak(conn, "builder")
    if cause in ("writer", "stall"):
        assert streak is None  # nothing for the member to fix: not counted
    else:
        assert streak == {"cause": cause, "count": 1, "first_seq": refused[0]["seq"],
                          "turn": None, "reason": SHARE_TOLD[cause]}
    # Put right, the next share goes through, and the count starts again.
    assert team._share("builder", "act-2", None)["status"] == "shared"
    with led.engine.connect() as conn:
        assert team._refusal_streak(conn, "builder") is None


@pytest.mark.parametrize("cause", ["setup", "gitlink"])
def test_git_set_up_wrong_or_a_stray_gitlink_still_ends_the_run_at_a_share(
        led, box, run_id, tmp_path, monkeypatch, cause):
    team = _open(led, box, run_id, tmp_path)
    (ls.workspace(team, "builder") / "part.md").write_text("# part\n")
    _make(cause, team, "builder", monkeypatch)

    with pytest.raises(TeamFailure) as failed:
        team._share("builder", "act-1", None)

    assert str(failed.value) == f"builder's share could not be carried out: {REFUSED[cause]}"
    assert _notices(led, run_id, "builder") == []
    assert _events(led, run_id, "share_refused") == []


# --- a sync, cause by cause ---------------------------------------------------------------------


@pytest.fixture
def behind(led, box, run_id, tmp_path) -> FlowTeam:
    """The builder shared builder.md, so the shared version is ahead of the leader's copy,
    which has a conflict recorded; the leader's turn (its goal) is next."""
    team = _open(led, box, run_id, tmp_path)
    builder = team._member_rows()["builder"]
    (team._pdir(builder) / "workspace" / "builder.md").write_text("# builder\n")
    assert team.shared.share("builder", team._pdir(builder)).status == "shared"
    led.set_conflicts(team._member_rows()["lead"]["participant_id"], [KEPT.as_dict()])
    return team


@pytest.mark.parametrize("cause", FIXABLE)
def test_a_refused_sync_starts_the_turn_without_the_merge_and_says_why(
        led, run_id, monkeypatch, behind, cause):
    team = behind
    ws = ls.workspace(team, "lead")
    before = ls.head(team, "lead")
    put_right = _make(cause, team, "lead", monkeypatch)
    turn, batch, _ = ts.claim_bound(led, run_id)
    try:
        text = team.prompt_for(ts.member("lead"), turn, batch)
    finally:
        put_right()

    assert _sync_told(cause) in text
    assert "app.py: you and builder both changed it; your copy has it as git left it" in text
    assert not (ws / "builder.md").exists() and ls.head(team, "lead") == before
    assert team._member_rows()["lead"]["conflicts"] == [{**KEPT.as_dict(), "told": True}]
    assert [(e["member"], e["data"]) for e in _events(led, run_id, "sync_refused")] == [
        ("lead", {"turn_id": turn["turn_id"], "cause": cause, "reason": _told(cause)})]
    ts.settle(led, turn)


@pytest.mark.parametrize("cause", ["writer", "stall", "setup", "gitlink"])
def test_a_sync_refused_for_what_the_member_cant_fix_still_keeps_the_turn_from_starting(
        led, run_id, monkeypatch, behind, cause):
    team = behind
    ws = ls.workspace(team, "lead")
    put_right = _make(cause, team, "lead", monkeypatch)
    turn, batch, _ = ts.claim_bound(led, run_id)
    try:
        with pytest.raises(MemberGitRefused) as refused:
            team.prompt_for(ts.member("lead"), turn, batch)
    finally:
        put_right()

    assert (refused.value.cause, str(refused.value)) == (cause, REFUSED[cause])
    assert not (ws / "builder.md").exists()
    assert team._member_rows()["lead"]["conflicts"] == [KEPT.as_dict()]
    assert [(e["member"], e["data"]) for e in _events(led, run_id, "sync_refused")] == [
        ("lead", {"turn_id": turn["turn_id"], "cause": cause, "reason": REFUSED[cause]})]
    ts.settle(led, turn)


def test_a_writer_refusal_at_a_sync_keeps_the_turn_from_starting_until_it_clears(
        led, box, run_id, tmp_path, monkeypatch):
    ts.SCRIPTS["lead"] = _lead()
    ts.SCRIPTS["builder"] = [[ls.write("part.md", "# part\n"), ls.op("share", note="part"),
                              ts.send("lead", "part shared", "info"), ls.op("idle")]]
    team = _open(led, box, run_id, tmp_path)
    ws = ls.workspace(team, "builder")
    live, once = team.project.writer_check, [WRITER]
    monkeypatch.setattr(team.project, "writer_check",
                        lambda folder: once.pop() if Path(folder) == ws and once
                        else live(folder))

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    snap = ts.rows(led, run_id)
    pid = next(p["participant_id"] for p in snap["participants"] if p["member"] == "builder")
    errors = [t["error"] or "" for t in snap["turns"] if t["participant_id"] == pid]
    assert [e for e in errors if f"could not start: {REFUSED['writer']}" in e]
    assert len(ts.PROMPTS["builder"]) == 1  # the refused turn never reached the model
    assert "Temper didn't bring" not in ts.PROMPTS["builder"][0]
    assert [(e["member"], e["data"]["cause"]) for e in _events(led, run_id, "sync_refused")] \
        == [("builder", "writer")]


# --- once git has written into the folder in the same call (Security's N1) ---------------------

#: M1's entries refusal with the cap the tests below set.
ENTRIES_3 = REFUSED["entries"].replace("more than 5 entries", "more than 3 entries")


@pytest.mark.parametrize("at", ["share", "sync"])
def test_a_refusal_once_a_conflicting_merge_wrote_into_the_folder_fails_as_before(
        led, box, run_id, tmp_path, monkeypatch, at):
    """The merge stops on a conflict after writing the builder's files into the leader's
    folder, which takes it past the entries cap, so the check refuses the commit that finishes
    the merge. Git has already changed the folder in this call: the share ends the run and the
    sync keeps the turn from starting, as before #115, and the member isn't told to fix it."""
    team = _open(led, box, run_id, tmp_path)
    bws, ws = ls.workspace(team, "builder"), ls.workspace(team, "lead")
    (bws / "app.py").write_text("print('builder')\n")
    for i in range(6):
        (bws / f"b{i}.txt").write_text("x\n")
    assert team.shared.share("builder", team._pdir(team._member_rows()["builder"])).status \
        == "shared"
    (ws / "app.py").write_text("print('lead')\n")
    monkeypatch.setattr(member_tree, "GIT_CHECK_ENTRIES", 3)
    why = f"a merge in the member's copy could not be finished: {ENTRIES_3}"

    if at == "share":
        with pytest.raises(TeamFailure) as failed:
            team._share("lead", "act-1", None)
        assert str(failed.value) == f"lead's share could not be carried out: {why}"
        assert _events(led, run_id, "share_refused") == []
    else:
        turn, batch, _ = ts.claim_bound(led, run_id)
        with pytest.raises(VersionError) as refused:
            team.prompt_for(ts.member("lead"), turn, batch)
        assert not isinstance(refused.value, MemberGitRefused)
        assert str(refused.value) == why
        assert _events(led, run_id, "sync_refused") == []
        ts.settle(led, turn)
    assert (ws / "b0.txt").exists()  # git had written into the folder before the refusal
    assert _notices(led, run_id, "lead") == []


def test_a_refusal_when_a_share_merges_again_after_a_lost_race_ends_the_run_as_before(
        led, box, run_id, tmp_path, monkeypatch):
    """The builder's share merges the team's version into its folder, which brings the
    leader's files in, then loses the race to the leader's next share. Merging again is
    refused: the folder is past the entries cap now. Git has already changed the folder in
    this call, so the run ends, as before #115."""
    team = _open(led, box, run_id, tmp_path)
    lws, ws = ls.workspace(team, "lead"), ls.workspace(team, "builder")
    lead_pdir = team._pdir(team._member_rows()["lead"])
    for i in range(6):
        (lws / f"l{i}.txt").write_text("x\n")
    assert team.shared.share("lead", lead_pdir).status == "shared"
    for i in range(6):
        (lws / f"l{i}.txt").unlink()
    (lws / "late.md").write_text("# late\n")
    (ws / "part.md").write_text("# part\n")
    monkeypatch.setattr(member_tree, "GIT_CHECK_ENTRIES", 3)
    move, raced = SharedVersion._move, []

    def lose_the_race(self: SharedVersion, *args: Any) -> Any:
        if not raced:  # the leader's share moves the team's version first
            raced.append("racing")
            raced[0] = team.shared.share("lead", lead_pdir).status
        return move(self, *args)

    monkeypatch.setattr(SharedVersion, "_move", lose_the_race)  # team.shared is made anew
    with pytest.raises(TeamFailure) as failed:
        team._share("builder", "act-1", None)

    assert raced == ["shared"]
    assert str(failed.value) == (
        "builder's share could not be carried out: the team's version moved during the share, "
        f"and merging it again could not run: {ENTRIES_3}")
    assert (ws / "l0.txt").exists()  # the first merge had written into the folder
    assert _notices(led, run_id, "builder") == []
    assert _events(led, run_id, "share_refused") == []


# --- refusals in a row: the member rests, and Temper asks once ----------------------------------


def test_a_member_refused_two_turns_in_a_row_rests_and_the_leader_is_told_once(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = _lead(on_resting=[
        ts.send("builder", "Try once more.", "work_request"), ls.op("idle", note="waiting")])
    ts.SCRIPTS["builder"] = [
        [ls.write("part.md", "# part\n"), PLANT, ls.op("share", note="part"), ls.op("idle")],
        [ls.op("share", note="part"), ls.op("idle")],
        [ls.op("share", note="part"), ls.op("idle")],
        [ls.op("share", note="part"), ls.op("idle")],
    ]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    # Turn 2 rests it; the leader's message wakes it for turn 3, which rests it again with
    # no second notice; with nothing left to do the team stalls, and the owner stops it.
    assert outcome.status == "stopped", outcome.text
    assert len(ts.PROMPTS["builder"]) == 3
    assert [n for n in _notices(led, run_id, "lead") if "is resting" in n] == [
        _resting("builder", SHARE_TOLD["planted"])]
    rests = [e for e in _events(led, run_id, "idle")
             if e["member"] == "builder" and e["data"]["reason"] == "refused"]
    assert [e["data"]["note"] for e in rests] == [
        "Temper refused to run git over its folder in 2 turns in a row (planted); a message "
        "wakes it.",
        "Temper refused to run git over its folder in 3 turns in a row (planted); a message "
        "wakes it."]
    assert [a["header"] for a in owner.asked] == ["team-stalled"]
    feed = flow_view.events_view(TeamReader(led, run_id, ts.HOST, "lead"), 0, 1000)["events"]
    assert [e["reason"] for e in feed if e["kind"] == "idle" and e["member"] == "builder"
            and e["reason"] == "git_refused"] == ["git_refused", "git_refused"]


def test_a_turn_whose_sync_was_refused_rests_the_member_even_with_no_share(
        led, box, run_id, tmp_path, monkeypatch):
    ts.SCRIPTS["lead"] = _lead(on_resting=[
        ls.op("done", summary="Carrying on without the builder's part.")])
    ts.SCRIPTS["builder"] = [
        [ls.write("part.md", "# part\n"), PLANT, ls.op("share", note="part"), ls.op("idle")],
        [{"say": "I'll leave it as it is."}],
        [{"say": "Still as it is."}],
    ]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert len(ts.PROMPTS["builder"]) == 2
    assert _sync_told("planted") in ts.PROMPTS["builder"][1]
    assert [n for n in _notices(led, run_id, "lead") if "is resting" in n] == [
        _resting("builder", _told("planted"))]
    assert [e["data"]["reason"] for e in _events(led, run_id, "idle")
            if e["member"] == "builder"][-1] == "refused"


def test_the_leaders_own_refusals_ask_the_owner_once_and_only_the_leader_waits(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "Remove sub/.git, then say done.").install(monkeypatch)
    ts.SCRIPTS["lead"] = [
        [ls.write("lead.md", "# lead\n"), PLANT, ls.op("share", note="mine"), ls.op("idle")],
        [ls.op("share", note="mine"), ls.op("idle")],
        [REMOVE, ls.op("done", summary="Done, without the .git.")],
    ]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert len(owner.asked) == 1
    asked = owner.asked[0]
    subject = asked["row"]["subject"]
    assert asked["row"]["kind"] == "owner" and asked["header"] == "git-refused"
    assert subject["member"] == "lead"
    assert subject["participant_id"] == team._member_rows()["lead"]["participant_id"]
    assert asked["question"].startswith(
        "Temper refused to run git over the folder of lead, the team's leader, in 2 turns in "
        "a row, so its work can't reach the team's shared version, and lead is resting. What "
        f"Temper told lead: \"{SHARE_TOLD['planted']}\"")
    assert "Reply with what to tell lead" in asked["question"]
    assert not [n for n in _notices(led, run_id, "lead") if "is resting" in n]
    assert len(ts.PROMPTS["lead"]) == 3
    assert any(h["kind"] == "owner_reply" for h in ts.headers(ts.PROMPTS["lead"][2]))
    assert _owner_replies(led, run_id, "lead") == ["Remove sub/.git, then say done."]


@pytest.mark.parametrize("answer", ["", "  "], ids=["empty", "blank"])
def test_an_owner_answer_with_no_words_still_gives_the_resting_leader_its_turn(
        led, box, run_id, tmp_path, monkeypatch, answer):
    # #119 (Architecture's S5 on #115): the question promised the leader another turn, so an
    # answer with no words reaches it as Temper's fixed line, and the owner isn't asked again.
    owner = ls.Owner(led, answer, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = [
        [ls.write("lead.md", "# lead\n"), PLANT, ls.op("share", note="mine"), ls.op("idle")],
        [ls.op("share", note="mine"), ls.op("idle")],
        [REMOVE, ls.op("done", summary="Done, without the .git.")],
    ]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert [a["header"] for a in owner.asked] == ["git-refused"] and owner.answers == ["stop"]
    assert _owner_replies(led, run_id, "lead") == [NO_WORDS]
    assert len(ts.PROMPTS["lead"]) == 3 and NO_WORDS in ts.PROMPTS["lead"][2]


def test_the_leaders_done_with_a_planted_git_is_refused_with_the_reason_and_the_run_carries_on(
        led, box, run_id, tmp_path, monkeypatch):
    ts.SCRIPTS["lead"] = [
        [ls.write("lead.md", "# lead\n"), PLANT, ls.op("done", summary="Done.")],
        [REMOVE, ls.op("done", summary="Done, without the .git.")],
    ]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    # Said once: the copy check doesn't repeat the done's own refused share.
    assert [e["data"]["reasons"] for e in _events(led, run_id, "done_refused")] == [
        [{"reason": "share", "detail": SHARE_TOLD["planted"]}]]
    assert len(ts.PROMPTS["lead"]) == 2
    assert _sync_told("planted") in ts.PROMPTS["lead"][1]
    files = ls.git(team.shared.path, "ls-tree", "-r", "--name-only",
                   outcome.record["version"]["commit"]).split()
    assert "lead.md" in files


def test_a_fresh_team_over_the_same_ledger_sees_the_same_count(
        led, box, run_id, tmp_path, monkeypatch):
    src = ls.project(tmp_path / "proj")
    team = ls.open_flow(led, box, run_id=run_id, source=src, names=NAMES, settings=SETTINGS)
    _plant(ls.workspace(team, "builder"))
    assert team._share("builder", "act-1", None)["cause"] == "planted"

    def reopen(attempt: str) -> FlowTeam:
        fresh = FlowTeam(led, box, run_id=run_id, host_path=ts.HOST,
                         members=[ts.member(n) for n in NAMES], team_settings=SETTINGS,
                         recorder=ts.Recorder(), attempt_id=attempt, workflow="team_test",
                         cancel_event=None, account=None, leader="lead",
                         pause_every_usd=100.0, max_parallel=1, goal=ls.GOAL, project=None)
        fresh.project = ProjectCopies(fresh.root, src, writer_check=fresh.writer_in_member_folder)
        assert fresh.open({"goal": ls.GOAL}) is None
        return fresh

    fresh = reopen("attempt-2")
    with led.engine.connect() as conn:
        assert fresh._refusal_streak(conn, "builder")["count"] == 1
    fresh._share("builder", "act-2", None)
    assert fresh._rest_after_refusals("builder", None) is True
    again = reopen("attempt-3")
    again._share("builder", "act-3", None)
    assert again._rest_after_refusals("builder", None) is True

    assert [n for n in _notices(led, run_id, "lead") if "is resting" in n] == [
        _resting("builder", SHARE_TOLD["planted"])]
    assert team._member_rows()["builder"]["idle_reason"] == "refused"


# Rest's guard (#119, Architecture's S1 on #115): a member rests only while idle, and only when
# nothing but Temper's own notices waits for it. Its refused shares' notices wait in each case.


def _refused_twice(led: Any, box: Any, run_id: str, tmp_path: Path) -> FlowTeam:
    team = _open(led, box, run_id, tmp_path)
    _plant(ls.workspace(team, "builder"))
    assert team._share("builder", "act-1", None)["cause"] == "planted"
    assert team._share("builder", "act-2", None)["cause"] == "planted"
    return team


def test_two_refusals_rest_an_idle_member_with_only_temper_notices_waiting(
        led, box, run_id, tmp_path):
    team = _refused_twice(led, box, run_id, tmp_path)
    assert team._rest_after_refusals("builder", None) is True
    assert team._member_rows()["builder"]["idle_reason"] == "refused"


def test_a_running_member_is_never_rested(led, box, run_id, tmp_path):
    team = _refused_twice(led, box, run_id, tmp_path)
    with led.engine.begin() as conn:
        conn.execute(sa.update(participants).where(
            participants.c.run_id == run_id, participants.c.member == "builder").values(
            state="running"))
    assert team._rest_after_refusals("builder", None) is False
    assert team._member_rows()["builder"]["idle_reason"] != "refused"


def test_an_owner_message_already_waiting_keeps_the_member_on(led, box, run_id, tmp_path):
    team = _refused_twice(led, box, run_id, tmp_path)
    led.post(run_id, ts.HOST, "builder", "Please look at sub/.git.")
    assert team._rest_after_refusals("builder", None) is False
    assert team._member_rows()["builder"]["idle_reason"] != "refused"


# --- the parts on their own ---------------------------------------------------------------------


def _e(seq: int, kind: str, **data: Any) -> dict:
    return {"seq": seq, "kind": kind, "data": data}


def test_the_count_is_turns_in_a_row_refused_for_one_cause_the_member_can_fix():
    refusal_streak = team_flow.refusal_streak
    s1 = _e(1, "share_refused", status="refused", cause="planted", turn_id="t1", reason="a")
    start2 = _e(2, "turn_start", turn_id="t2")
    sync2 = _e(3, "sync_refused", cause="planted", turn_id="t2", reason="b")
    s2 = _e(4, "share_refused", status="refused", cause="planted", turn_id="t2", reason="c")

    assert refusal_streak([]) is None
    assert refusal_streak([s1]) == {"cause": "planted", "count": 1, "first_seq": 1,
                                    "turn": "t1", "reason": "a"}
    # a turn's sync and its shares count once
    assert refusal_streak([s1, start2, sync2]) == {"cause": "planted", "count": 2,
                                                   "first_seq": 1, "turn": "t2", "reason": "b"}
    assert refusal_streak([s1, start2, sync2, s2])["count"] == 2
    # a good sync, a version shared, or a share whose check passed ends it
    assert refusal_streak([s1, start2]) is None
    assert refusal_streak([s1, start2, _e(3, "share_refused", status="refused",
                                          cause="planted", turn_id="t2")]) == {
        "cause": "planted", "count": 1, "first_seq": 3, "turn": "t2", "reason": None}
    assert refusal_streak([s1, _e(2, "share", version_no=1)]) is None
    assert refusal_streak([s1, _e(2, "share_refused", status="conflict", paths=["a"])]) is None
    # another cause the member can fix starts a new count
    assert refusal_streak([s1, _e(2, "share_refused", status="refused", cause="entries",
                                  turn_id="t2", reason="d")])["count"] == 1
    # writer and stall neither count nor end it
    writer = [_e(2, "turn_start", turn_id="t2"),
              _e(3, "sync_refused", cause="writer", turn_id="t2", reason="w"),
              _e(4, "turn_start", turn_id="t3"),
              _e(5, "sync_refused", cause="planted", turn_id="t3", reason="e")]
    assert refusal_streak([s1, *writer])["count"] == 2
    stall = _e(2, "share_refused", status="refused", cause="stall", turn_id="t2", reason="s")
    assert refusal_streak([s1, stall]) == refusal_streak([s1])


def test_every_member_is_asked_not_to_make_a_git_repository_in_its_folder():
    for name in NAMES:
        assert NO_GIT in flow_framing(name, "lead", list(NAMES), [])
