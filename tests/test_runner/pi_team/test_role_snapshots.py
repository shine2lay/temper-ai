"""A team's role snapshots (M4 SW-25, L4-F4): each member joins with its own copy of its role
folder, its digest on the member's row, on SQLite and on the tier's Postgres. A refused snapshot
refuses the team before any turn; the next open copies afresh. Once on record, a snapshot is
the member's: the role's real folder changing mid-run (M1's live run, Design's folder) never
reaches it. Model-free: the stand-in members never run a turn here.
"""

from __future__ import annotations

import os
from pathlib import Path

from temper_ai.pi_agent.member_tree import leftovers, tree_digest
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_team import support as ts


def _role(box) -> Path:
    return Path(box.identities_dir) / sup.ROLE


def _snapshot(row: dict) -> Path:
    return Path(row["session_dir"]).parent / "memory" / "identities" / sup.ROLE


def test_sw25_every_member_s_digest_is_on_its_row(led, box, run_id):
    team = ts.open_team(led, box, run_id=run_id)
    rows = led.participants_of(run_id, ts.HOST)
    assert sorted(r["member"] for r in rows) == sorted(ts.NAMES)
    digest = tree_digest(_role(box))
    for row in rows:
        assert row["snapshot_sha256"] == digest, row["member"]
        assert tree_digest(_snapshot(row)) == digest
        assert leftovers(_snapshot(row)) == []
    assert len({str(_snapshot(r)) for r in rows}) == 3, "each member has its own copy"
    assert team.open({}) is None  # found again: nothing copied twice


def test_sw25_a_role_folder_changing_mid_run_never_reaches_the_members(led, box, run_id):
    ts.open_team(led, box, run_id=run_id)
    joined = tree_digest(_role(box))
    (_role(box) / "notebook.md").write_text("Rewritten by the role's own chat mid-run.\n")
    (_role(box) / "notes").mkdir(exist_ok=True)
    (_role(box) / "notes" / "n1.md").write_text("a note written mid-run\n")

    again = ts.make_team(led, box, run_id=run_id, attempt="attempt-2")
    assert again.open({}) is None
    for row in led.participants_of(run_id, ts.HOST):
        assert row["snapshot_sha256"] == joined
        assert tree_digest(_snapshot(row)) == joined
        assert sup.CHECK_WORD in (_snapshot(row) / "notebook.md").read_text()


def test_sw25_a_link_out_of_the_role_folder_refuses_the_team_naming_member_and_link(
        led, box, run_id):
    os.symlink("/etc/passwd", _role(box) / "passwd")
    team = ts.make_team(led, box, run_id=run_id)
    refusal = team.open({})
    assert refusal is not None and refusal.startswith(
        "member lead's role snapshot was refused: the role folder 'scout' has a link 'passwd' "
        "pointing outside it ('/etc/passwd'); Temper never follows links out of a role folder")
    rows = led.participants_of(run_id, ts.HOST)
    assert all(r["snapshot_sha256"] is None for r in rows)
    assert not any(os.path.lexists(_snapshot(r)) for r in rows)
    assert not led.any_turn_began(run_id, ts.HOST)
    assert ts.rows(led, run_id)["turns"] == []

    # the owner removes the link; the next attempt's open copies afresh and records each digest
    os.unlink(_role(box) / "passwd")
    again = ts.make_team(led, box, run_id=run_id, attempt="attempt-2")
    assert again.open({}) is None
    digest = tree_digest(_role(box))
    assert [r["snapshot_sha256"] for r in led.participants_of(run_id, ts.HOST)] == [digest] * 3


def test_sw25_rows_attached_by_an_attempt_that_died_before_its_snapshots_get_them_next_time(
        led, box, run_id):
    """The rows are written, then the process dies before any snapshot is on record (half a
    copy at most): the next open removes what is there and copies afresh."""
    team = ts.make_team(led, box, run_id=run_id)
    pins = {name: team.pin(m) for name, m in team.members.items()}
    rows = led.attach_team(run_id, ts.HOST, [(n, sup.ROLE, pins[n]) for n in ts.NAMES],
                           session_root=str(team.root), attempt_id="attempt-1")
    first = rows[0][0]
    half = _snapshot(first).parent / f".{sup.ROLE}.partial-dead"
    (half / "notes").mkdir(parents=True)
    (half / "notebook.md").write_text("half a copy\n")

    again = ts.make_team(led, box, run_id=run_id, attempt="attempt-2")
    assert again.open({}) is None
    digest = tree_digest(_role(box))
    for row in led.participants_of(run_id, ts.HOST):
        assert row["snapshot_sha256"] == digest
        assert tree_digest(_snapshot(row)) == digest and leftovers(_snapshot(row)) == []
