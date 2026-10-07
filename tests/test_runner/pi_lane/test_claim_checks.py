"""What the Pi lane settles when it claims a run, before any copy or model call (runner/
pi_lane.py claim_checks): a team's project folder on its real paths (ADR-M4-12, SW-33), by the
same function the team's node runs, and the run's one account, picked by room from the allowed
slots (ADR-M4-09, -14) or, under ``account_pick: settings_order``, the first allowed slot with
no capacity check (ADR-M4-19), and recorded on the run. Model-free: throwaway git
repositories, planted links, fake room figures.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.pi_agent import accounts, team_check
from temper_ai.pi_agent.accounts import record_account
from temper_ai.pi_agent.member import DEFAULT_PROVIDER
from temper_ai.pi_agent.team_config import ACCOUNT_PICK_REFUSAL, TeamConfig
from temper_ai.pi_agent.token_scan import LogGuard
from temper_ai.runner import pi_lane, pi_preflight
from temper_ai.runner.lanes import LANE_RECORD_KEY
from tests.test_pi_agent import support as sup
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


def _row_now(eid: str) -> dict:
    found = ls.row(eid)
    return {"workflow_name": found.workflow_name, "inputs": found.inputs,
            "workspace_path": found.workspace_path, "spawner_metadata": found.spawner_metadata}


@pytest.mark.parametrize("stale", [True, False], ids=["stale-row", "fresh-row"])
def test_the_account_that_won_the_run_is_checked_and_a_disallowed_winner_refuses(
        claim, monkeypatch, tmp_path, stale):
    """A claim whose row was read before another claim recorded the run's account (a double
    claim, a race) gets the winner back: it is the run's account, checked like any recorded
    one. Settings that no longer allow it refuse the run; the winner is never swapped or
    picked again. A fresh row (the control) refuses the same way."""
    ls.make_row("p1")
    before = _row_now("p1")
    record_account("p1", {"slot": "acct-b", "by": "room"})  # the other claim won
    ls.team_settings(monkeypatch, tmp_path / "settings", account_slots=["acct-c"])
    ls.write_room(claim.room, {"acct-c": {"five_hour": 1, "seven_day": 1}})
    refusal = pi_lane.claim_checks("p1", before if stale else _row_now("p1"), [])
    assert refusal is not None and refusal.kind == "account"
    assert "the run's account acct-b is no longer allowed" in refusal.message
    assert ls.account_of("p1")["slot"] == "acct-b"


def test_a_stale_claim_whose_winner_is_still_allowed_runs_on_the_winner(claim):
    ls.write_room(claim.room, {"acct-b": {"five_hour": 5, "seven_day": 70},
                               "acct-c": {"five_hour": 5, "seven_day": 10}})
    ls.make_row("p1")
    before = _row_now("p1")
    record_account("p1", {"slot": "acct-b", "by": "room"})  # the other claim won
    assert pi_lane.claim_checks("p1", before, []) is None  # this claim would pick acct-c
    assert ls.account_of("p1") == {"slot": "acct-b", "by": "room"}


# --- the settings' order, with no capacity check (ADR-M4-19) --------------------------------------


@pytest.fixture
def by_order(claim, monkeypatch):
    """The frozen first trial's settings: ``account_pick: settings_order`` over the slots
    (acct-c, acct-b), no account-room file named and none on disk, and tripwires on all a
    capacity check would touch -- the room reader and every socket connection (the host
    helper's is a Unix socket) -- each counted."""
    settings = claim.tmp / "settings"
    ls.team_settings(monkeypatch, settings, account_pick="settings_order",
                     account_room_file=None, account_slots=["acct-c", "acct-b"])
    claim.room.unlink()
    room_reader = sup.Tripwire("accounts.read_room")
    monkeypatch.setattr(accounts, "read_room", room_reader)
    sockets = sup.socket_tripwire(monkeypatch)
    return SimpleNamespace(
        settings=lambda **keys: ls.team_settings(monkeypatch, settings, **keys),
        counts=lambda: {"read_room": room_reader.calls, "socket_connect": sockets.calls})


def test_by_the_settings_order_the_claim_records_the_first_allowed_slot_before_work_and_keeps_it(
        claim, by_order, record_property):
    """ADR-M4-19's happy path at the claim. The first claim admits the run on the first
    allowed slot in the settings' order, recorded on the run's row before any member works,
    as exactly ``{slot, picked_at, by, capacity}`` with no figure; a member's box takes that
    slot (run_account is where host.py gets BoxSpec.slot). A resume or a fork after the
    order changed keeps it; a new run takes the new order's first slot. Nothing read a room
    file or opened a socket."""
    ls.make_row("p1")
    assert claim.check("p1") is None
    account = ls.account_of("p1")
    assert set(account) == {"slot", "picked_at", "by", "capacity"}
    assert (account["slot"], account["by"], account["capacity"]) == (
        "acct-c", "settings_order", "not_checked")
    assert accounts.run_account("p1") == account  # the member box's slot: acct-c

    by_order.settings(account_slots=["acct-b", "acct-c"])
    for start in ("resume", "fork"):
        assert claim.check("p1", start=start) is None
        assert ls.account_of("p1") == account
    ls.make_row("p2")
    assert claim.check("p2") is None
    assert ls.account_of("p2")["slot"] == "acct-b"

    by_order.settings(account_slots=["acct-b"])  # the run's slot dropped: refused, never moved
    refusal = claim.check("p1", start="resume")
    assert refusal is not None and refusal.kind == "account"
    assert "the run's account acct-c is no longer allowed" in refusal.message
    assert ls.account_of("p1") == account
    record_property("tripwire_calls", by_order.counts())
    assert by_order.counts() == {"read_room": 0, "socket_connect": 0}


def test_by_the_settings_order_two_claims_at_once_under_different_orders_get_one_account(
        claim, by_order, monkeypatch, record_property):
    """Two claims of one run settle at the same moment, each under its own order of the same
    slots (each alone would pick a different one): the row lock lets one record its pick,
    and the other gets that account back."""
    from temper_ai.database import get_database

    if get_database().engine.dialect.name != "postgresql":
        pytest.skip("the row lock (SELECT ... FOR UPDATE) is Postgres's; SQLite has none")
    ls.make_row("p1")
    before = _row_now("p1")
    together = threading.Barrier(2)
    real_record = accounts.record_account

    def record_together(eid: str, account: dict) -> dict:
        together.wait(timeout=20)
        return real_record(eid, account)

    monkeypatch.setattr(accounts, "record_account", record_together)
    orders = {"b-first": ("acct-b", "acct-c"), "c-first": ("acct-c", "acct-b")}
    got: dict[str, dict] = {}
    errors: list[BaseException] = []

    def settle(name: str, slots: tuple[str, ...]) -> None:
        try:
            got[name] = accounts.settle("p1", before, config=TeamConfig(
                account_slots=slots, account_pick="settings_order"))
        except BaseException as exc:  # noqa: BLE001 - shown by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=settle, args=item) for item in orders.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(t.is_alive() for t in threads) and errors == []
    winner = ls.account_of("p1")
    assert got == {"b-first": winner, "c-first": winner}
    assert winner["slot"] in ("acct-b", "acct-c") and winner["capacity"] == "not_checked"
    record_property("tripwire_calls", by_order.counts())
    assert by_order.counts() == {"read_room": 0, "socket_connect": 0}


@pytest.mark.parametrize("keys", [
    {"account_pick": "settings_order"},
    {"account_pick": "Settings_Order"},
    {"account_pick": None},
], ids=["settings-order-beside-a-room-file", "wrong-case", "null"])
def test_an_account_pick_that_can_t_be_used_refuses_the_claim_before_any_reading_or_work(
        claim, by_order, monkeypatch, record_property, keys):
    """Architecture's #75 check, F1, at the claim. The settings change to an account_pick
    that can't be used, beside an account-room file on disk with room for every slot: a run
    with its account kept (claimed again, resumed or forked) and a new run's first claim are
    all refused, kind account, before any member works -- nothing recorded or changed on the
    rows, no room file read and no socket opened."""
    ls.make_row("p1")
    assert claim.check("p1") is None
    account = ls.account_of("p1")
    ls.give_accounts(monkeypatch, claim.tmp / "settings", slots=("acct-c", "acct-b"))
    by_order.settings(**keys)
    ls.make_row("p2")
    for eid, start in (("p1", None), ("p1", "resume"), ("p1", "fork"), ("p2", None)):
        refusal = claim.check(eid, start=start)
        assert refusal is not None and refusal.kind == "account", (eid, start)
        assert ACCOUNT_PICK_REFUSAL in refusal.message
    assert ls.account_of("p1") == account
    nothing_recorded("p2")
    record_property("tripwire_calls", by_order.counts())
    assert by_order.counts() == {"read_room": 0, "socket_connect": 0}


# --- what a refused claim says and stores (SW-52) ------------------------------------------------

#: An inert token-shaped canary, built so that no literal token sits in the source.
CANARY = "sk-ant-" + "oat01-" + "Q" * 40


def _room_with(kind: str) -> bytes:
    row = '{"slot": "acct-b", "status": "ok", "observed_at": "2026-10-06T20:00:00Z"'
    if kind == "top-field":
        return f'{{"schema_version": 1, "slots": [], "{CANARY}": 1}}'.encode()
    if kind == "row-field":
        return f'{{"schema_version": 1, "slots": [{row}, "{CANARY}": 1}}]}}'.encode()
    if kind == "window-field":
        return (f'{{"schema_version": 1, "slots": [{row}, "five_hour": '
                f'{{"used_percent": 1, "{CANARY}": 1}}}}]}}').encode()
    if kind == "schema-value":
        return f'{{"schema_version": "{CANARY}", "slots": []}}'.encode()
    if kind == "duplicate-key":
        return f'{{"schema_version": 1, "slots": [], "{CANARY}": 1, "{CANARY}": 2}}'.encode()
    if kind == "duplicate-slot":
        twin = f'{{"slot": "{CANARY}", "status": "ok"}}'
        return f'{{"schema_version": 1, "slots": [{twin}, {twin}]}}'.encode()
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["top-field", "row-field", "window-field", "schema-value",
                                  "duplicate-key", "duplicate-slot"])
def test_a_refused_room_file_never_echoes_its_content_in_the_refusal_or_its_records(
        claim, kind):
    """A room file the reader refuses is named in fixed words: no key or value of the file
    reaches the refusal, the run's row or its refused attempt (SW-52)."""
    from temper_ai.pi_agent.token_scan import scan
    from tests.test_pi_agent import support as sup

    claim.room.write_bytes(_room_with(kind))
    ls.make_row("p1")
    refusal = claim.check("p1")
    assert refusal is not None and refusal.kind == "account"
    assert "account-room file" in refusal.message
    assert not scan(refusal.message), "the refusal echoed the file"
    pi_lane.record_refusal("p1", _row_now("p1"), refusal)
    (attempt,) = sup.attempts("p1")
    assert attempt["data"]["refused"] == "account"
    assert not scan(str(attempt["data"]["error"])), "the stored attempt echoed the file"
    nothing_recorded("p1")


def test_a_refusal_s_words_leave_with_any_token_withheld():
    """The boundary behind the fixed words: whatever a refusal is given, its message holds
    no token by the time it is logged or stored."""
    from temper_ai.pi_agent.token_scan import scan

    refusal = pi_lane.Refusal("account", f"something went wrong near {CANARY}")
    assert not scan(refusal.message) and refusal.message.startswith("something went wrong")


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
