"""What the Pi lane settles when it claims a run, before any copy or model call (runner/
pi_lane.py claim_checks): a team's project folder on its real paths (ADR-M4-12, SW-33), by the
same function the team's node runs, and the run's one account, picked by room from the allowed
slots and recorded on the run (ADR-M4-09, -14). Model-free: throwaway git repositories, planted
links, fake room figures.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.pi_agent import team_check
from temper_ai.pi_agent.accounts import record_account
from temper_ai.pi_agent.member import DEFAULT_PROVIDER
from temper_ai.pi_agent.token_scan import LogGuard
from temper_ai.runner import pi_lane, pi_preflight
from temper_ai.runner.lanes import LANE_RECORD_KEY
from tests.test_runner.pi_lane import support as ls
from tests.test_runner.pi_lane.test_run_gate import SHA, Loader
from tests.test_runner.pi_team.leader_support import git, project

FAILED = "The Pi lane's checks of the team's project folder failed: "


@pytest.fixture
def claim(monkeypatch, tmp_path):
    """check_run in the Pi lane, its slow or outside parts stubbed; the team settings allow
    the projects under ``projects/`` and two account slots with room."""
    ls.as_the_pi_lane(monkeypatch)
    settings = tmp_path / "settings"
    room = ls.give_accounts(monkeypatch, settings)
    projects = tmp_path / "projects"
    ls.team_settings(monkeypatch, settings, project_roots=[f"{projects}/*"])
    monkeypatch.setattr(pi_lane, "eager_import", lambda: None)
    monkeypatch.setattr(pi_preflight, "preflight", lambda *, record=None: [])
    monkeypatch.setattr(pi_lane, "read_commit", lambda root=None: (SHA, ""))
    loader = Loader()

    def check(eid: str, *, start: str | None = None):
        found = ls.row(eid)
        return pi_lane.check_run(eid, {
            "workflow_name": found.workflow_name, "inputs": found.inputs,
            "workspace_path": found.workspace_path,
            "spawner_metadata": found.spawner_metadata}, start=start, graph_loader=loader)

    def team_run(eid: str, workspace: Path | str, **kw) -> None:
        ls.make_row(eid, "lane_team", **kw)
        ls.set_row(eid, workspace_path=str(workspace))

    return SimpleNamespace(check=check, team_run=team_run, projects=projects, room=room,
                           tmp=tmp_path)


def commits(eid: str) -> list[dict]:
    return ((ls.row(eid).spawner_metadata or {}).get(LANE_RECORD_KEY) or {}).get("commits", [])


def nothing_recorded(eid: str) -> None:
    assert ls.account_of(eid) is None and commits(eid) == []


# --- the project folder, on its real paths (SW-33) -------------------------------------------


def test_a_team_s_project_inside_a_root_passes_and_the_run_gets_its_account(claim):
    app = project(claim.projects / "app")
    claim.team_run("t1", app)
    assert claim.check("t1") is None
    account = ls.account_of("t1")
    # the most weekly room: acct-b at 20 % of its week, acct-c at 30 %
    assert account["slot"] == "acct-b" and account["by"] == "room"
    assert [c["commit"] for c in commits("t1")] == [SHA]


def _outside(claim) -> Path:
    return project(claim.tmp / "elsewhere" / "app")


def _link_outside(claim) -> Path:
    claim.projects.mkdir(parents=True, exist_ok=True)
    (claim.projects / "sneaky").symlink_to(project(claim.tmp / "outside"))
    return claim.projects / "sneaky"


def _not_git(claim) -> Path:
    (claim.projects / "plain").mkdir(parents=True)
    return claim.projects / "plain"


def _sub_folder(claim) -> Path:
    """A direct child of the root that is a sub folder of a repository (the root itself)."""
    (claim.projects / "app").mkdir(parents=True)
    project(claim.projects, {"app/a.txt": "a\n"})
    return claim.projects / "app"


def _deeper_child(claim) -> Path:
    project(claim.projects / "group" / "app")
    return claim.projects / "group" / "app"


def _worktree_outside(claim) -> Path:
    elsewhere = project(claim.tmp / "elsewhere")
    claim.projects.mkdir(parents=True, exist_ok=True)
    git(elsewhere, "worktree", "add", "-q", str(claim.projects / "wt"), "-b", "wt")
    return claim.projects / "wt"


@pytest.mark.parametrize("make, says", [
    (_outside, "is outside the allowed project folders"),
    (_link_outside, "leads outside the allowed project folders through a link"),
    (_not_git, "the workspace is not a git repository"),
    (_sub_folder, "is inside a git repository but is not its top folder"),
    (_deeper_child, "is outside the allowed project folders"),
    (_worktree_outside, "is outside the allowed project folders"),
], ids=["outside", "link-outside", "not-git", "sub-folder", "deeper-child", "worktree-outside"])
def test_a_project_folder_the_checks_refuse_stops_the_run_at_claim(claim, make, says):
    claim.team_run("t1", make(claim))
    refusal = claim.check("t1")
    assert refusal is not None and refusal.kind == "project_folder", refusal
    assert refusal.message.startswith(FAILED + "project: ")
    assert says in refusal.message
    nothing_recorded("t1")  # no account picked, no commit: the run never starts


def test_a_folder_that_isn_t_there_in_the_lane_is_refused(claim):
    claim.projects.mkdir(parents=True)
    claim.team_run("t1", claim.projects / "gone")
    refusal = claim.check("t1")
    assert refusal.kind == "project_folder" and "isn't reachable inside Temper" in refusal.message


def test_a_repository_in_a_format_git_can_t_read_is_named(claim):
    app = project(claim.projects / "app")
    git(app, "config", "core.repositoryformatversion", "1")
    git(app, "config", "extensions.temperTestUnknown", "true")
    claim.team_run("t1", app)
    refusal = claim.check("t1")
    assert refusal.kind == "project_folder"
    assert "uses a format this git can't read" in refusal.message
    nothing_recorded("t1")


def test_a_pi_run_without_a_team_has_no_project_folder_to_check(claim):
    ls.make_row("p1", "lane_pi")
    ls.set_row("p1", workspace_path=str(claim.tmp / "no-such-folder"))
    assert claim.check("p1") is None and ls.account_of("p1")["slot"] == "acct-b"


# --- carrying on: the commit the copies started from -------------------------------------------


@pytest.fixture
def state_root(claim, monkeypatch):
    root = claim.tmp / "pi-state"
    monkeypatch.setattr(team_check, "load_box",
                        lambda: (SimpleNamespace(state_root=str(root)), None))
    return root


def started_from(state_root: Path, eid: str, source: Path, commit: str) -> None:
    import json

    rec = state_root / eid / "build.team" / "project.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"source": str(source), "commit": commit}), encoding="utf-8")


def test_a_resumed_team_needs_the_commit_its_copies_started_from(claim, state_root):
    app = project(claim.projects / "app")
    claim.team_run("t1", app)
    started_from(state_root, "t1", app, "5" * 40)
    refusal = claim.check("t1", start="resume")
    assert refusal.kind == "project_folder"
    assert refusal.message == (FAILED + "project: the commit the team's copies started from "
                               "(555555555555) is no longer in the workspace's repository")
    nothing_recorded("t1")


def test_a_resumed_team_with_its_start_commit_passes_whatever_the_folder_s_own_changes(
        claim, state_root):
    app = project(claim.projects / "app")
    start = git(app, "rev-parse", "HEAD")
    (app / "app.py").write_text("changed since\n")
    git(app, "commit", "-qam", "later")
    (app / "app.py").write_text("and not committed\n")
    claim.team_run("t1", app)
    started_from(state_root, "t1", app, start)
    assert claim.check("t1", start="resume") is None


# --- the run's one account (ADR-M4-09, -14) ---------------------------------------------------


def test_the_slot_with_the_most_room_is_picked_and_recorded_by_label_only(claim):
    ls.write_room(claim.room, {"acct-b": {"five_hour": 5, "seven_day": 70},
                               "acct-c": {"five_hour": 50, "seven_day": 10}})
    ls.make_row("p1")
    assert claim.check("p1") is None
    account = ls.account_of("p1")
    assert account["slot"] == "acct-c"
    assert set(account) == {"slot", "picked_at", "by", "room", "room_file"}
    assert account["room"]["seven_day"] == 10.0
    assert account["room_file"] == {
        "sha256": hashlib.sha256(claim.room.read_bytes()).hexdigest(), "schema_version": 1}


def test_a_second_claim_never_overwrites_the_account_the_first_recorded(claim):
    ls.make_row("p1")
    first = record_account("p1", {"slot": "acct-b", "by": "room"})
    assert record_account("p1", {"slot": "acct-c", "by": "room"}) == first
    assert ls.account_of("p1")["slot"] == "acct-b"


def test_a_run_admitted_before_without_an_account_is_refused_and_never_picked_again(claim):
    ls.make_row("p1")
    assert claim.check("p1") is None
    meta = dict(ls.row("p1").spawner_metadata)
    meta[LANE_RECORD_KEY] = {k: v for k, v in meta[LANE_RECORD_KEY].items() if k != "account"}
    ls.set_row("p1", spawner_metadata=meta)
    refusal = claim.check("p1", start="resume")
    assert refusal.kind == "account" and "never again" in refusal.message
    assert ls.account_of("p1") is None


@pytest.mark.parametrize("start", ["resume", "fork"])
def test_a_later_attempt_keeps_the_run_s_account_whatever_the_room_now(claim, start):
    ls.make_row("p1")
    claim.check("p1")
    first = ls.account_of("p1")
    ls.write_room(claim.room, {"acct-b": {"five_hour": 99, "seven_day": 99},
                               "acct-c": {"five_hour": 1, "seven_day": 1}})
    assert claim.check("p1", start=start) is None
    assert ls.account_of("p1") == first and first["slot"] == "acct-b"


def test_no_slot_with_room_refuses_the_run_naming_each_slot(claim):
    ls.write_room(claim.room, {"acct-b": {"five_hour": 90, "seven_day": 10},
                               "acct-c": {"five_hour": 10, "seven_day": 95}})
    ls.make_row("p1")
    refusal = claim.check("p1")
    assert refusal.kind == "account"
    assert refusal.message.startswith("The Pi lane couldn't settle the run's account: ")
    assert "acct-b: 5 h 90%" in refusal.message and "acct-c: 5 h 10%, 7 d 95%" in refusal.message
    nothing_recorded("p1")


def test_stale_room_figures_refuse_the_run(claim):
    ls.write_room(claim.room, {"acct-b": {"five_hour": 1, "seven_day": 1}},
                  observed_at="2026-01-01T00:00:00Z")
    ls.make_row("p1")
    refusal = claim.check("p1")
    assert refusal.kind == "account" and "min old" in refusal.message
    nothing_recorded("p1")


def test_a_run_recorded_on_account_1_is_refused_by_name(claim):
    ls.make_row("p1", metadata={LANE_RECORD_KEY: {"account": {"slot": DEFAULT_PROVIDER}}})
    refusal = claim.check("p1", start="resume")
    assert refusal.kind == "account" and "account 1" in refusal.message
    assert commits("p1") == []


def test_account_1_in_the_settings_is_never_picked(claim, monkeypatch, tmp_path):
    ls.team_settings(monkeypatch, tmp_path / "settings",
                     account_slots=[DEFAULT_PROVIDER, "acct-c"])
    ls.write_room(claim.room, {DEFAULT_PROVIDER: {"five_hour": 0, "seven_day": 0},
                               "acct-c": {"five_hour": 50, "seven_day": 80}})
    ls.make_row("p1")
    assert claim.check("p1") is None
    assert ls.account_of("p1")["slot"] == "acct-c"


# --- the logs of a Pi run (SW-52) ---------------------------------------------------------------


def test_a_claimed_pi_run_s_log_lines_leave_with_tokens_withheld(claim):
    handler = logging.NullHandler()
    logging.getLogger().addHandler(handler)
    try:
        ls.make_row("p1")
        claim.check("p1")
        assert any(isinstance(f, LogGuard) for f in handler.filters)
    finally:
        logging.getLogger().removeHandler(handler)
